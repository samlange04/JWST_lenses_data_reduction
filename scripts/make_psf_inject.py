#!/usr/bin/env python
"""
Resample-broadened model PSF by artificial-star injection: the HST repo's make_psf_inject.py
(the Anderson 2016 route) for NIRCam.

    uv run python scripts/make_psf_inject.py --lens SPT2147-50 --filt F444W [--keep-work]

STPSF gives a detector-frame PSF; psf_models.model_psf rotates it into the North-up output
grid analytically, which gets the orientation and pixel scale right but not the blur the
resample step puts on a point source, and the analytic drop box that stands in for it is not
enough (COWLS: empirical/model FWHM 1.05-1.11, never below 1, 2026-10-30). The fix the HST
repo made canonical for its model tier: put the model PSF into the individual exposures and
resample them exactly as the science frames were, so the resampled star carries the
broadening, the North-up orientation and the exposure weighting, all made by the real
resample, not emulated.

How, per band:
  * The cal frames of the science mosaic (the rootnames in info/provenance/lens_products.json,
    so the same MIN_EXPTIME cut) are loaded through an Image3Pipeline built from the science
    run's own step overrides (reduce_nircam.image3_steps) and the CRDS parameter references,
    and tweakreg is RE-RUN on the real data: the injected frames must carry the WCS
    corrections the science frames got (relative shifts 1-44 mas, up to 0.7 LW px), and a
    noiseless frame holding one star could not be aligned on its own. Pruned samples (COWLS)
    keep their cal files, so this needs nothing the reduction deleted.
  * Each frame's SCI is zeroed (NaN pixels stay NaN, as resample masks them) and the STPSF
    OVERDIST PSF for that frame's detector, position and date is added at the star, pixel-
    integrated (a 4-subpixel box) and sampled at the star's sub-pixel phase. ERR, DQ and the
    variance arrays are untouched, so the ivm weights are the science weights.
  * Stars are put at the centres of science-grid pixels -- the one nearest the deflector and a
    5 x 5 grid around it, 1.5 kernels apart -- so each resampled star lands centred on an
    output pixel and is a plain crop, with no re-centring interpolation (which an
    undersampled SW PSF would not survive). The grid samples the sub-pixel phase on the
    detectors, which one star cannot: the kernel is the mean of the stars that fall wholly on
    the frames the lens does (see injected_kernel).
  * resample runs with the science parameters onto a sub-grid of the science grid (same
    crval, scale and rotation, crpix moved by whole pixels), so its pixels are the mosaic's.
  * skymatch and outlier_detection are not run: the frames hold no sky, and the injected star
    has no cosmic rays.

make_psf.py's model tier calls injected_kernel() and ships its kernel (PSFMETH
'inject_stpsf'); the analytic box is the fallback if injection fails. Run standalone, this is
the validation route: it writes psf_kernel_injected.fits + psf_injected.png into
data/psf/<sample>/<lens>/<FILT>/, records info/provenance/lens_psf_injected.json and prints
the comparison with the band's shipped PSF, touching neither psf.fits nor lens_psf.json.
"""
import argparse
import os
import shutil
import sys
import time
import warnings

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mmap_fits_write
mmap_fits_write.install()
import info_json
import lens_samples
import psf_models
import reduce_nircam
import stamp_paths

ws_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FOV_PAD = 1.5          # STPSF field = kernel side x this, in detector pixels
SUBGRID_MARGIN = 8     # output px around the kernel in the injected resample
INJECT_FLUX = 1.0e4    # arbitrary; the kernel is renormalised
IN_MEMORY_MAX = 40     # more frames than this -> an on-disk ModelLibrary (B1938's 168)
GRID = 5               # GRID x GRID injected stars, the kernel is their mean (injected_kernel)


def science_grid(sample, lens, filt, variant=''):
    """The science mosaic's record, cal files and output grid. Returns a dict."""
    from astropy.wcs import WCS
    key = filt + stamp_paths.variant_tag(variant)
    rec = info_json.load(info_json.path(ws_path, 'lens_products.json')).get(sample, {}).get(lens, {}).get(key)
    if not rec:
        raise RuntimeError(f'no lens_products.json record for {sample}/{lens} {key}; reduce it first')
    if variant == 'mastcal':
        cal_dir = os.path.join(ws_path, 'data', 'calibrated', sample, lens, filt)
    else:
        cal_dir = reduce_nircam._stage_dir('stage2', sample, lens, filt, variant)
    cals = [os.path.join(cal_dir, r + '_cal.fits') for r in rec['rootnames']]
    missing = [c for c in cals if not os.path.exists(c)]
    if missing:
        raise RuntimeError(f'{len(missing)} of {len(cals)} cal files missing (e.g. {missing[0]}); '
                           'injection needs the frames the mosaic was made from')
    coord = lens_samples.coord(lens, sample)
    scale = float(rec['scale'])
    field = float(rec.get('field_arcsec') or reduce_nircam.DEFAULT_FIELD)
    n = reduce_nircam.mosaic_side(field, scale)
    w = WCS(naxis=2)
    w.wcs.ctype = ['RA---TAN', 'DEC--TAN']
    w.wcs.crval = [coord.ra.deg, coord.dec.deg]
    w.wcs.crpix = [(n - 1) / 2.0 + 1, (n - 1) / 2.0 + 1]        # resample's crpix is 0-based
    w.wcs.cd = [[-scale / 3600.0, 0.0], [0.0, scale / 3600.0]]
    return dict(rec=rec, cals=cals, coord=coord, scale=scale, field=field, n=n, wcs=w,
                tweakreg=rec.get('tweakreg') or 'relative',
                lens_first=bool(rec.get('tweakreg_lens_first')),
                offsets=rec.get('tweak_offsets_mas') if rec.get('tweakreg') == 'from_lw' else None)


def effective_psf(src, oversample=psf_models.STPSF_OVERSAMPLE):
    """(epsf, c): the oversampled STPSF array `src` (star at its centre) pixel-integrated by a
    box of `oversample` subpixels, i.e. an effective PSF whose value at an offset is the flux a
    detector pixel centred there collects; `c` is the star's index in it (both axes)."""
    pad = 2 * oversample
    return psf_models.drop_convolve_box(np.pad(src, pad), float(oversample)), (src.shape[0] - 1) / 2.0 + pad


def render_epsf(epsf, c, x, y, half, oversample=psf_models.STPSF_OVERSAMPLE):
    """(stamp, iy0, ix0): the effective PSF as detector pixel values around a star at (x, y),
    a (2*half+1)^2 stamp, unit sum, cubic-sampled at each pixel centre."""
    from scipy.ndimage import map_coordinates
    ix, iy = int(round(x)), int(round(y))
    offs = np.arange(-half, half + 1)
    XX, YY = np.meshgrid(offs, offs)
    sx = c + (XX + ix - x) * oversample
    sy = c + (YY + iy - y) * oversample
    stamp = map_coordinates(epsf, [sy.ravel(), sx.ravel()], order=3, mode='constant', cval=0.0)
    stamp = np.clip(stamp.reshape(XX.shape), 0.0, None)
    return stamp / stamp.sum(), iy - half, ix - half


def injected_kernel(sample, lens, filt, size, variant='', work_dir=None, keep_work=False):
    """The resample-broadened STPSF kernel for one band: (size x size, unit sum, North-up at
    the mosaic scale, centred on the central pixel) and an info dict. Raises on failure.

    A GRID x GRID grid of stars around the lens, each on an output-pixel centre, so each lands
    at a different sub-pixel phase on the detectors; the kernel is their mean. One star is one
    phase, and with 2-4 dithers an undersampled SW star's resampled width depends on it: on
    SPT0418-47 F115W, single stars a pixel or two apart ranged 0.049-0.064" (2026-10-30). Only
    stars that fall wholly on exactly the frames the lens does are used, so every star has the
    lens's depth and weights."""
    from jwst.pipeline import Image3Pipeline
    import make_psf
    t0 = time.time()
    reduce_nircam.setup_crds()
    g = science_grid(sample, lens, filt, variant)
    w, scale, n = g['wcs'], g['scale'], g['n']
    target = lens_samples.deflector_coord(lens, sample) or g['coord']
    px, py = (float(v) for v in w.world_to_pixel(target))
    ix, iy = int(np.floor(px + 0.5)), int(np.floor(py + 0.5))   # at a pixel corner (crval), the upper pixel
    sp = size + size // 2
    k = GRID // 2
    grid = [(ix + i * sp, iy + j * sp) for j in range(-k, k + 1) for i in range(-k, k + 1)]
    stars = w.pixel_to_world([p[0] for p in grid], [p[1] for p in grid])
    centre = GRID * GRID // 2                                 # the star at the lens
    m = 2 * k * sp + size + 2 * SUBGRID_MARGIN + 1
    m += m % 2                                                # even, as the science side
    ox, oy = ix - m // 2, iy - m // 2                        # sub-grid pixel 0 = science pixel o
    print(f'  injection: {len(g["cals"])} cal frames, {len(grid)} stars every {sp} px around science pixel '
          f'({ix}, {iy}), sub-grid {m} px, tweakreg {g["tweakreg"]}', flush=True)

    work_dir = work_dir or os.path.join(ws_path, 'data', 'psf', sample, lens, filt, '_inject_work')
    if os.path.isdir(work_dir):
        shutil.rmtree(work_dir)
    os.makedirs(work_dir)
    lens_star = stars[centre]
    try:
        asn = reduce_nircam.write_asn(g['cals'], f'{lens.replace("+", "p")}_{filt}_inject'.lower(), work_dir)
        mode = 'skip' if g['offsets'] is not None else g['tweakreg']
        steps = reduce_nircam.image3_steps(g['coord'], scale, g['field'], mode, g['lens_first'])
        config, config_file = Image3Pipeline.build_config(asn, steps=steps)
        config.pop('class', None)
        pipe = Image3Pipeline.from_config_section(config, name=config.get('name'), config_file=config_file)
        pipe.in_memory = len(g['cals']) <= IN_MEMORY_MAX
        det_scale = lens_samples.NATIVE_SCALE[lens_samples.channel(filt)]
        library = pipe._load_input_as_library(asn)
        before = {}                                          # the lens on each frame, a-priori WCS
        with library:
            for i, model in enumerate(library):
                before[model.meta.filename] = model.meta.wcs.backward_transform(lens_star.ra.deg, lens_star.dec.deg)
                library.shelve(model, i, modify=False)
        if g['offsets'] is not None:
            # a SW band of a tweakreg_sw_from_lw sample: the science moved each frame by its
            # exposure's LW offset instead of fitting it, so the injection does the same
            with library:
                for i, model in enumerate(library):
                    o = g['offsets'].get(reduce_nircam._rootname(model.meta.filename))
                    if o is not None:
                        model.meta.wcs = reduce_nircam.shift_wcs(model.meta.wcs, o)
                    library.shelve(model, i, modify=o is not None)
        else:
            library = pipe.tweakreg.run(library)

        fov = int(np.ceil(size * scale / det_scale * FOV_PAD)) | 1
        half = fov // 2
        frames, cache = [], {}
        on = np.zeros((len(g['cals']), len(grid)))             # each star's flux on each frame
        with library:
            for i, model in enumerate(library):
                sci = np.where(np.isfinite(model.data), 0.0, np.nan).astype(np.float32)
                ny, nx = sci.shape
                xs, ys = (np.asarray(v, float) for v in model.meta.wcs.backward_transform(stars.ra.deg, stars.dec.deg))
                x0, y0 = before[model.meta.filename]
                rec = dict(file=os.path.basename(model.meta.filename),
                           x=round(float(xs[centre]), 3), y=round(float(ys[centre]), 3),
                           tweakreg=model.meta.cal_step.tweakreg,
                           tweak_shift_mas=round(float(np.hypot(xs[centre] - x0, ys[centre] - y0)) * det_scale * 1e3, 1))
                near = np.isfinite(xs) & np.isfinite(ys) & (xs > -half) & (xs < nx + half) & (ys > -half) & (ys < ny + half)
                if near.any():
                    # one STPSF per frame, at the lens (or the on-frame star nearest it): over the
                    # grid's ~15" the field dependence is far below the phase effect
                    s0 = centre if near[centre] else int(np.flatnonzero(near)[np.argmin(np.abs(np.flatnonzero(near) - centre))])
                    det, date = model.meta.instrument.detector, model.meta.observation.date_beg
                    key = (det, str(date)[:10], round(xs[s0] / 256), round(ys[s0] / 256))
                    if key not in cache:
                        # a grid star just off the detector still spills light onto it; STPSF
                        # wants an on-detector position, and the PSF varies slowly there
                        sx_, sy_ = float(np.clip(xs[s0], 0, nx - 1)), float(np.clip(ys[s0], 0, ny - 1))
                        src, sinfo = psf_models.stpsf_detector_psf(filt, det, sx_, sy_, date, fov)
                        cache[key] = (effective_psf(src), sinfo)
                    (epsf, c), sinfo = cache[key]
                    for s in np.flatnonzero(near):
                        stamp, sy0, sx0 = render_epsf(epsf, c, xs[s], ys[s], half)
                        gy0, gx0 = max(0, sy0), max(0, sx0)
                        gy1, gx1 = min(ny, sy0 + fov), min(nx, sx0 + fov)
                        if gy1 > gy0 and gx1 > gx0:
                            part = stamp[gy0 - sy0:gy1 - sy0, gx0 - sx0:gx1 - sx0]
                            sci[gy0:gy1, gx0:gx1] += INJECT_FLUX * part
                            on[i, s] = part.sum()
                    if on[i, centre] > 0:
                        rec.update(detector=sinfo['detector'], opd=sinfo['opd'], flux_on_frame=round(float(on[i, centre]), 4))
                model.data = sci
                model.meta.background.level = 0.0
                model.meta.background.subtracted = True
                frames.append(rec)
                library.shelve(model, i, modify=True)
        n_inj = int((on[:, centre] > 0).sum())
        if n_inj == 0:
            raise RuntimeError('the lens falls on no frame')
        # a star is used when it lies wholly on exactly the frames the lens lies on
        lens_frames = on[:, centre] > 0
        use = [s for s in range(len(grid))
               if np.array_equal(on[:, s] > 0, lens_frames) and np.all(on[lens_frames, s] > 0.999)]
        if centre not in use:
            use.append(centre)                                # the lens star itself, whatever its coverage
        print(f'  injected into {n_inj}/{len(frames)} frames at the lens ({len(cache)} STPSF calls), '
              f'{len(use)}/{len(grid)} stars used; tweakreg '
              + ', '.join(f"{f['tweakreg']} {f['tweak_shift_mas']} mas" for f in frames if 'detector' in f), flush=True)

        r = pipe.resample
        r.output_shape = [m, m]
        r.crpix = [(n - 1) / 2.0 - ox, (n - 1) / 2.0 - oy]
        r.save_results = False
        r.in_memory = True
        result = r.run(library)
        data = np.nan_to_num(np.asarray(result.data, float))
        cxs, cys = (np.asarray(v, float) for v in result.meta.wcs.backward_transform(stars.ra.deg, stars.dec.deg))
    finally:
        if not keep_work:
            shutil.rmtree(work_dir, ignore_errors=True)

    crops, fwhms = [], []
    for s in use:
        ex, ey = grid[s][0] - ox, grid[s][1] - oy
        if max(abs(cxs[s] - ex), abs(cys[s] - ey)) > 1e-3:
            raise RuntimeError(f'injected resample grid is not the science grid: star {s} at '
                               f'({cxs[s]:.4f}, {cys[s]:.4f}), expected ({ex}, {ey})')
        crop = make_psf._crop_centered(data, size, ex, ey)
        if crop.sum() <= 0:
            raise RuntimeError(f'injected star {s} resampled to nothing')
        crops.append(crop / crop.sum())
        fwhms.append(make_psf.measure_fwhm(crops[-1]))
    kernel = np.mean(crops, axis=0)
    kernel /= kernel.sum()
    from photutils.centroids import centroid_com
    h = size // 2
    dx, dy = centroid_com(kernel[h - 3:h + 4, h - 3:h + 4])
    fw = np.array([f for f in fwhms if f is not None]) * scale
    info = dict(n_frames=len(frames), n_injected=n_inj, n_stars=len(use), star_spacing_px=sp,
                frames=frames, tweakreg=g['tweakreg'],
                lens_star_ra=round(lens_star.ra.deg, 8), lens_star_dec=round(lens_star.dec.deg, 8),
                star_fwhm_arcsec=[round(float(fw.min()), 4), round(float(np.median(fw)), 4), round(float(fw.max()), 4)],
                centroid_offset_mas=[round((dx - 3) * scale * 1e3, 2), round((dy - 3) * scale * 1e3, 2)],
                stpsf_version=next(iter(cache.values()))[1]['stpsf_version'], stpsf_fov_pixels=fov,
                seconds=round(time.time() - t0, 1))
    print(f'  injected kernel: mean of {len(use)} stars (single-star FWHM {fw.min():.4f}-{fw.max():.4f}", '
          f'median {np.median(fw):.4f}"), core centroid offset ({info["centroid_offset_mas"][0]:+.1f}, '
          f'{info["centroid_offset_mas"][1]:+.1f}) mas, {info["seconds"]:.0f}s', flush=True)
    return kernel, info


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--lens', required=True)
    p.add_argument('--filt', required=True)
    p.add_argument('--sample', default=None)
    p.add_argument('--variant', default='', choices=('',) + stamp_paths.VARIANT_COMPONENTS)
    p.add_argument('--keep-work', action='store_true',
                   help='keep data/psf/<sample>/<lens>/<FILT>/_inject_work (the asn) for inspection')
    a = p.parse_args()
    import make_psf
    sample = a.sample or lens_samples.sample_of(a.lens)
    filt = lens_samples.canonical_filter(a.filt)
    ch = lens_samples.channel(filt)
    size = int(make_psf._INSTR[f'NIRCAM/{ch}']['star_size']) | 1
    print(f'{a.lens} {filt}  [NIRCAM/{ch}, kernel {size} px]')
    kernel, info = injected_kernel(sample, a.lens, filt, size, a.variant, keep_work=a.keep_work)

    kernel, pedestal_frac = make_psf.subtract_pedestal(kernel)
    fwhm = make_psf.measure_fwhm(kernel)
    scale = science_grid(sample, a.lens, filt, a.variant)['scale']
    out_dir = os.path.join(ws_path, 'data', 'psf', sample, a.lens, filt)
    os.makedirs(out_dir, exist_ok=True)
    from astropy.io import fits
    hdr = fits.Header()
    hdr['PSFMETH'] = ('inject_stpsf', 'STPSF injected into the cal frames + resample')
    hdr['PSFINJ'] = (True, 'built by artificial-star injection + resample')
    hdr['PSFPXSCL'] = (round(scale, 5), 'kernel pixel scale (arcsec)')
    hdr['PSFFWHM'] = (round(fwhm, 4) if fwhm else 0.0, 'fitted kernel FWHM (pixels)')
    hdr['PSFLENS'], hdr['PSFFILT'] = a.lens, filt
    hdr['PSFNINJ'] = (info['n_injected'], 'frames holding the lens star')
    hdr['PSFNSTI'] = (info['n_stars'], 'injected stars averaged')
    make_psf.write_fits(kernel, hdr, os.path.join(out_dir, 'psf_kernel_injected.fits'))
    make_psf.plot_psf(kernel, None, [], scale, fwhm, os.path.join(out_dir, 'psf_injected.png'),
                      title=f'{a.lens}  {filt}  [inject_stpsf]  ({info["n_stars"]} stars, {info["n_injected"]} frames)')

    shipped = info_json.load(info_json.path(ws_path, 'lens_psf.json')).get(sample, {}).get(a.lens, {}).get(filt) or {}
    record = dict(info, fwhm_pix=round(fwhm, 4) if fwhm else None,
                  fwhm_arcsec=round(fwhm * scale, 4) if fwhm else None, pedestal_frac=round(pedestal_frac, 6),
                  compared_with=shipped.get('method'), compared_fwhm_arcsec=shipped.get('fwhm_arcsec'))
    info_json.update(info_json.path(ws_path, 'lens_psf_injected.json'), sample, a.lens, filt, record)
    if fwhm and shipped.get('fwhm_arcsec'):
        print(f'  FWHM injected {fwhm * scale:.4f}" vs shipped {shipped["method"]} {shipped["fwhm_arcsec"]:.4f}" '
              f'(ratio shipped/injected {shipped["fwhm_arcsec"] / (fwhm * scale):.3f})')
    print('=== done')
    return 0


if __name__ == '__main__':
    sys.exit(main())
