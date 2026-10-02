#!/usr/bin/env python
"""
Rate-level 1/f destripe of NIRCam frames, after the TEMPLATES recipe (Rigby+25 §6.3,
`rigby2025templates`):

  1. an object mask from a first-pass stacked image (our Image3 i2d), thresholded and
     propagated back to each frame through its WCS, OR-ed with a per-frame high-pass
     threshold mask (the stack's 150" field does not cover every detector);
  2. per amplifier (four 512-column strips in DMS orientation), the median of the unmasked
     pixels is measured and the amplifier-to-amplifier offsets (about their mean) are
     subtracted -- the common level is sky and stays for the flat field (see destripe_image);
  3. per amplifier, a 512x1 horizontal median filter of the masked, pedestal-subtracted
     strip -- i.e. one median per detector row per amplifier -- is subtracted.

Why rate level, when Detector1's clean_flicker_noise already runs on the ramp: measured on
SPT0418-47 F150W (AGENTS.md, *striping*), the ramp step removes a third of the banding and
`fit_by_channel` adds nothing. The difference here is the mask: a thresholded, dilated mask
from the deeper stack, so the lens halo and faint sources stop biasing the row medians.

Geometry: NIRCam full frames in DMS orientation have FASTAXIS = +-1 (rows are the fast-read
direction) and SLOWAXIS = +-2, so 1/f banding is horizontal and the four amplifiers are
column strips [0:512], [512:1024], ... -- the same split jwst's median_clean uses. The
module refuses any other layout rather than guess.

Only SCI is modified; ERR / VAR_* / DQ are copied through (the correction is a smooth,
low-amplitude template -- its variance is negligible against the per-pixel terms).
Keywords written to the output primary header: S_DESTRP, DSTRPMSK (mask source), DSTRPPED
(per-amp pedestals), DSTRPRMS (rms of the row-median template, DN/s), DSTRPROW (rows with
too few unmasked pixels, filled by interpolation along the slow axis).

    uv run python scripts/destripe_nircam.py RATE... --i2d I2D --cal-dir DIR --out-dir DIR
"""
import argparse
import os
import sys
import warnings

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

N_OUTPUTS = 4
CHANNEL = 512
MIN_ROW_PIXELS = 48          # fewer unmasked pixels than this in a 512-px row segment: interpolate
DO_NOT_USE = 1


def build_object_mask(i2d_path, nsigma=2.0, smooth_px=2.0, dilate_px=6):
    """Boolean mask (True = object) on the i2d grid, plus its FITS WCS.

    The i2d is lightly smoothed, sigma-clipped for robust background stats, thresholded at
    median + nsigma*std, then dilated. Smoothing first is what catches the lens galaxy's
    low-surface-brightness halo; the 2-sigma threshold (not 3) is deliberate -- a mask that
    is too tight leaves exactly the faint wings that bias a row median."""
    from astropy.io import fits
    from astropy.stats import sigma_clipped_stats
    from astropy.wcs import WCS
    from scipy import ndimage
    with fits.open(i2d_path) as h:
        sci = h['SCI'].data.astype(float)
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            wcs = WCS(h['SCI'].header)
    bad = ~np.isfinite(sci)
    filled = np.where(bad, np.nanmedian(sci), sci)
    sm = ndimage.gaussian_filter(filled, smooth_px) if smooth_px > 0 else filled
    _, med, std = sigma_clipped_stats(sm[~bad], sigma=3.0, maxiters=5)
    mask = sm > med + nsigma * std
    if dilate_px > 0:
        mask = ndimage.binary_dilation(mask, iterations=int(dilate_px))
    mask |= bad                      # outside the mosaic footprint: no information, mask it
    return mask, wcs, {'threshold': float(med + nsigma * std), 'bg_median': float(med),
                       'bg_std': float(std), 'object_frac': float(mask.mean())}


def frame_mask(cal_path, mosaic_mask, mosaic_wcs, step=4):
    """Propagate the mosaic mask to one frame's detector grid through the cal file's gwcs.

    The gwcs is evaluated on a `step`-px grid and the mosaic pixel coordinates are
    bilinearly interpolated to full resolution (the distortion is smooth; the interpolation
    error is far below a pixel). Returns (mask, inside): pixels mapping outside the mosaic
    footprint carry no stack information and are left unmasked here with inside=False --
    the caller ORs in a per-frame mask. (The 150" mosaic field does not cover a whole SW
    module: half of B1 falls outside it when the lens sits on B4.)"""
    from jwst import datamodels
    from scipy import ndimage
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        with datamodels.open(cal_path) as m:
            ny, nx = m.data.shape
            yy, xx = np.mgrid[0:ny:step, 0:nx:step]
            ra, dec = m.meta.wcs(xx.astype(float), yy.astype(float))
        mx, my = mosaic_wcs.world_to_pixel_values(ra, dec)
    zoom = (ny / mx.shape[0], nx / mx.shape[1])
    mx_full = ndimage.zoom(mx, zoom, order=1)[:ny, :nx]
    my_full = ndimage.zoom(my, zoom, order=1)[:ny, :nx]
    ix = np.rint(mx_full).astype(int)
    iy = np.rint(my_full).astype(int)
    inside = (ix >= 0) & (iy >= 0) & (ix < mosaic_mask.shape[1]) & (iy < mosaic_mask.shape[0])
    out = np.zeros((ny, nx), dtype=bool)
    out[inside] = mosaic_mask[iy[inside], ix[inside]]
    return out, inside


def per_frame_mask(sci, nsigma=2.5, filt_px=15, dilate_px=3):
    """Object mask from the frame itself: high-pass (median filter) then threshold. The
    fallback for detector regions the stack does not cover; shallower than the stack mask
    but it catches stars and galaxy cores, which is what biases a row median most."""
    from astropy.stats import sigma_clipped_stats
    from scipy import ndimage
    fin = np.isfinite(sci)
    filled = np.where(fin, sci, np.nanmedian(sci))
    hp = filled - ndimage.median_filter(filled, size=filt_px)
    _, med, std = sigma_clipped_stats(hp[fin], sigma=3.0, maxiters=5)
    m = hp > med + nsigma * std
    if dilate_px > 0:
        m = ndimage.binary_dilation(m, iterations=int(dilate_px))
    return m | ~fin


def _check_geometry(hdr):
    fast, slow = hdr.get('FASTAXIS'), hdr.get('SLOWAXIS')
    if abs(fast or 0) != 1 or abs(slow or 0) != 2 or hdr.get('SUBARRAY') != 'FULL':
        raise RuntimeError(f'destripe expects a NIRCam FULL frame with FASTAXIS=+-1, SLOWAXIS=+-2; '
                           f'got FASTAXIS={fast} SLOWAXIS={slow} SUBARRAY={hdr.get("SUBARRAY")}')


def destripe_image(sci, object_mask, dq=None):
    """TEMPLATES steps 2-3 on one 2048x2048 rate image. Returns (cleaned, stats)."""
    ny, nx = sci.shape
    if (ny, nx) != (2048, 2048):
        raise RuntimeError(f'full frame expected, got {sci.shape}')
    good = np.isfinite(sci) & ~object_mask
    if dq is not None:
        good &= (dq & DO_NOT_USE) == 0
    template = np.zeros_like(sci, dtype=float)
    pedestals, n_interp = [], 0
    for c in range(N_OUTPUTS):
        g = good[:, c * CHANNEL:(c + 1) * CHANNEL]
        pedestals.append(float(np.median(sci[:, c * CHANNEL:(c + 1) * CHANNEL][g])) if g.any() else 0.0)
    # Only the amplifier-to-amplifier DIFFERENCES are removed: the common level is the sky,
    # which must stay in the frame so Image2 flat-fields it (subtracting it here would
    # imprint sky * (1/flat - 1), a few 1e-3 DN/s of flat structure -- the size of the 1/f).
    rel = [p - float(np.mean(pedestals)) for p in pedestals]
    for c in range(N_OUTPUTS):
        sl = slice(c * CHANNEL, (c + 1) * CHANNEL)
        strip = sci[:, sl].astype(float)
        g = good[:, sl]
        ped = rel[c]
        masked = np.where(g, strip - pedestals[c], np.nan)
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', RuntimeWarning)
            rows = np.nanmedian(masked, axis=1)
        n_ok = g.sum(axis=1)
        valid = (n_ok >= MIN_ROW_PIXELS) & np.isfinite(rows)
        if valid.sum() < 2:
            raise RuntimeError(f'amplifier {c}: {valid.sum()} usable rows -- mask too aggressive?')
        if not valid.all():
            n_interp += int((~valid).sum())
            idx = np.arange(ny)
            rows = np.interp(idx, idx[valid], rows[valid])
        template[:, sl] = ped + rows[:, None]
    cleaned = sci - template
    stats = {'pedestals': [round(p, 5) for p in pedestals], 'pedestal_offsets': [round(p, 5) for p in rel],
             'row_rms': float(np.std(template - np.array(rel).repeat(CHANNEL)[None, :])),
             'rows_interpolated': n_interp, 'unmasked_frac': float(good.mean())}
    return cleaned.astype(sci.dtype), stats


def destripe_rate(rate_path, out_path, object_mask, mask_source=''):
    from astropy.io import fits
    with fits.open(rate_path) as h:
        _check_geometry(h[0].header)
        sci = h['SCI'].data
        cleaned, stats = destripe_image(sci, object_mask, h['DQ'].data)
        h['SCI'].data = cleaned
        p = h[0].header
        p['S_DESTRP'] = ('COMPLETE', 'rate-level 1/f destripe (destripe_nircam.py)')
        p['DSTRPMSK'] = (os.path.basename(mask_source)[:60], 'object-mask source')
        p['DSTRPPED'] = (' '.join(f'{v:.4g}' for v in stats['pedestal_offsets']), 'per-amp offsets removed, DN/s')
        p['DSTRPRMS'] = (round(stats['row_rms'], 6), 'rms of row-median template, DN/s')
        p['DSTRPROW'] = (stats['rows_interpolated'], 'row segments interpolated (too few px)')
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        h.writeto(out_path, overwrite=True)
    return stats


def destripe_frames(rate_files, cal_files, i2d_path, out_dir, verbose=True):
    """The whole recipe for one band. rate_files[i] and cal_files[i] must be the same
    exposure (the cal carries the gwcs the rate lacks). Skips outputs that already exist.
    Returns (destriped rate paths, per-frame stats)."""
    mosaic_mask, wcs, mstats = build_object_mask(i2d_path)
    if verbose:
        print(f'  [destripe] mask from {os.path.basename(i2d_path)}: threshold {mstats["threshold"]:.4f}, '
              f'{100 * mstats["object_frac"]:.1f}% of the mosaic masked', flush=True)
    outs, all_stats = [], {}
    for i, (rate, cal) in enumerate(zip(rate_files, cal_files), 1):
        out = os.path.join(out_dir, os.path.basename(rate))
        outs.append(out)
        if os.path.exists(out):
            continue
        from astropy.io import fits
        stack_m, inside = frame_mask(cal, mosaic_mask, wcs)
        own_m = per_frame_mask(fits.getdata(rate, 'SCI'))
        fm = stack_m | own_m
        st = destripe_rate(rate, out, fm, i2d_path)
        st['stack_coverage'] = float(inside.mean())
        all_stats[os.path.basename(rate)] = st
        if verbose:
            print(f'  [destripe {i}/{len(rate_files)}] {os.path.basename(rate)}: stack covers '
                  f'{100 * st["stack_coverage"]:.0f}%, {100 * st["unmasked_frac"]:.0f}% px used, pedestals '
                  f'{" ".join(f"{p:.3f}" for p in st["pedestals"])}, row rms {st["row_rms"]:.4f} DN/s, '
                  f'{st["rows_interpolated"]} rows interp', flush=True)
    return outs, {'mask': mstats, 'frames': all_stats}


def main():
    p = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    p.add_argument('rates', nargs='+', help='*_rate.fits to destripe')
    p.add_argument('--i2d', required=True, help='first-pass mosaic for the object mask')
    p.add_argument('--cal-dir', required=True, help='dir holding the matching *_cal.fits (gwcs)')
    p.add_argument('--out-dir', required=True)
    a = p.parse_args()
    cals = [os.path.join(a.cal_dir, os.path.basename(r).replace('_rate.fits', '_cal.fits')) for r in a.rates]
    missing = [c for c in cals if not os.path.exists(c)]
    if missing:
        sys.exit(f'no cal for: {missing}')
    destripe_frames(a.rates, cals, a.i2d, a.out_dir)
    return 0


if __name__ == '__main__':
    sys.exit(main())
