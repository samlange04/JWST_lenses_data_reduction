#!/usr/bin/env python
"""
Cut the modelling stamp + noise map + preview PNG for one lens + filter from its i2d mosaic.

    uv run python scripts/make_cutouts.py --lens SPT2147-50 --filt F444W [--size 12]

Port of the HST repo's make_cutouts.py with the HST-only machinery removed. Reads the one
`*_i2d.fits` in data/mosaics[_<variant>]/<sample>/<lens>/<FILT>/ and writes, in
data/cutouts[_<S>arcsec]/<sample>/<lens>/<FILT>/:

    cutout[_<variant>]_sci.fits     float32, MJy/sr, the i2d SCI header + cutout WCS
    cutout[_<variant>]_noise.fits   float64 sigma map, same units, 1e8 where excluded
    cutout[_<variant>].png          signal / noise / S/N, origin='upper' (PyAutoLens's view)

**Centre.** Every filter's mosaic was resampled with crval at the catalogue position and
rotation 0 (reduce_nircam.py), so the catalogue coordinate IS the common centre and the SW
(0.03") and LW (0.06") grids nest 2:1 about it. The default `--center catalogue` therefore
gives co-registered stamps across filters with no peak search; `--center peak` exists for a
lens whose catalogue position is off (it finds the brightest median-filtered pixel in a
`--box` window, as the HST repo does), and whichever is used is recorded in
info/lens_cutout_qc.json.

**Noise.** The i2d ERR extension is the propagated per-pixel sigma, sqrt(VAR_POISSON +
VAR_RNOISE + VAR_FLAT), each variance drizzled with the science weights -- i.e. it is
already the total noise including source Poisson, and it is "read, not constructed"
(PyAutoReduce's rule). The stamp's noise is ERR x NOISECOR, where NOISECOR comes from
info/noise_corr_factors.json (per channel/filter, default 1.0; measured with
measure_corr_factor.py once a sample's mosaics exist -- the HST repo found its ERR arrays
understate the noise by 5-25%, white, and the same test is owed here). The Casertano R for
the drop/scale pair is stamped as CASR for information only (it corrects an image-estimated
rms, not an ERR map; see AGENTS.md *Correlated noise*). Pixels with NaN SCI, non-finite or
zero ERR, or zero WHT get sci=0, noise=1e8 (the autolens "masked-by-noise" sentinel).

**One stamp per band.** The sci/noise names carry the reduction variant (cutout_paths.py);
a second variant beside an existing stamp is refused unless --force, which removes the other.
"""
import argparse
import json
import os
import sys
import warnings

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from astropy.io import fits
from astropy.nddata import Cutout2D
from astropy.wcs import WCS
from astropy.wcs.utils import proj_plane_pixel_scales
from astropy.visualization import AsinhStretch, ImageNormalize, PercentileInterval
from scipy.ndimage import median_filter
import astropy.units as u

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lens_samples
import info_json
import cutout_paths

ws_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SENTINEL = 1.0e8
WEIGHT_UNIFORMITY_LIMIT = 0.2
CORR_FACTORS_JSON = os.path.join(ws_path, 'info', 'noise_corr_factors.json')


def weight_uniformity(wht):
    """RMS/median of the positive weights over the stamp (STScI rule of thumb: > ~0.2 means
    the drop is too small for the dither pattern). None if nothing to judge."""
    good = np.asarray(wht, dtype=np.float64)
    good = good[np.isfinite(good) & (good > 0.0)]
    if good.size == 0:
        return None
    return float(good.std() / np.median(good))


def casertano_r(pixfrac, scale_ratio):
    """Casertano et al. 2000 R = 1/r from drop size p and output/native scale s (per axis
    r = 1 - p/(3s) for s >= p, (s/p)(1 - s/(3p)) for s < p). Informational only."""
    if pixfrac is None or scale_ratio is None:
        return None
    if not (0.0 < pixfrac <= 1.0) or scale_ratio <= 0.0:
        return None
    p, s = pixfrac, scale_ratio
    r = (s / p) * (1.0 - s / (3.0 * p)) if s < p else 1.0 - p / (3.0 * s)
    return 1.0 / r


def resolve_corr_factor(cli_value, channel, filt, sample, lens):
    """1.0 < JSON per channel ('NIRCAM/LW') < JSON per filter < JSON per-lens override < CLI."""
    if cli_value is not None:
        return float(cli_value), 'cli'
    data = info_json.load(CORR_FACTORS_JSON)
    value, src = 1.0, 'default'
    for key, label in ((f'NIRCAM/{channel}', 'channel'), (filt, 'filter')):
        if key in data.get('factors', {}):
            value, src = float(data['factors'][key]), f'json:{label}'
    override = data.get('lens_overrides', {}).get(sample, {}).get(lens, {}).get(filt)
    if override is not None:
        value, src = float(override), 'json:lens'
    return value, src


def brightest_pixel_position(cutout, box=100, median_size=5):
    """(row, col) of the brightest median-filtered pixel within the central `box`."""
    data = np.nan_to_num(np.asarray(cutout, dtype=np.float64), nan=0.0)
    ny, nx = data.shape
    cy, cx = ny // 2, nx // 2
    h = box // 2
    sub = data[max(cy - h, 0):cy + h, max(cx - h, 0):cx + h]
    sm = median_filter(sub, size=median_size)
    r, c = np.unravel_index(np.argmax(sm), sm.shape)
    return r + max(cy - h, 0), c + max(cx - h, 0)


def plot_cutouts(sci, noise, output_path, title):
    noise_display = np.where(noise >= SENTINEL, np.nan, noise)
    with np.errstate(divide='ignore', invalid='ignore'):
        snr = np.where(noise >= SENTINEL, np.nan, sci / noise)
    fig, axes = plt.subplots(1, 3, figsize=(16, 5.5))
    for ax, (label, data) in zip(axes, [('signal', sci), ('noise', noise_display), ('signal / noise', snr)]):
        finite = data[np.isfinite(data)]
        vmin, vmax = PercentileInterval(99.0).get_limits(finite)
        norm = ImageNormalize(vmin=vmin, vmax=vmax, stretch=AsinhStretch(0.1))
        im = ax.imshow(data, norm=norm, origin='upper', cmap='inferno')
        ax.set_title(label); ax.set_xlabel('pixels')
        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    fig.suptitle(title); fig.tight_layout()
    fig.savefig(output_path, dpi=120, bbox_inches='tight'); plt.close(fig)
    print(f'  wrote {output_path}')


def write_fits(data, wcs, header, path):
    hdr = header.copy()
    hdr.update(wcs.to_header())
    fits.PrimaryHDU(data=data, header=hdr).writeto(path, overwrite=True)
    print(f'  wrote {path}  shape={data.shape}')


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--lens', required=True)
    p.add_argument('--filt', required=True)
    p.add_argument('--sample', default=None)
    p.add_argument('--size', type=float, default=cutout_paths.DEFAULT_SIZE, help='arcsec on a side')
    p.add_argument('--variant', default='', choices=('',) + cutout_paths.VARIANT_COMPONENTS,
                   help="which reduction's mosaic to cut (default: the standard one)")
    p.add_argument('--center', choices=['catalogue', 'peak'], default='catalogue')
    p.add_argument('--box', type=int, default=100, help='--center peak search window, px')
    p.add_argument('--median-size', type=int, default=5)
    p.add_argument('--corr-factor', type=float, default=None,
                   help='override the noise inflation (default: info/noise_corr_factors.json, else 1.0)')
    p.add_argument('--force', action='store_true')
    p.add_argument('--output', default=None, help='write here instead of the cutout tree (scratch use)')
    a = p.parse_args()

    sample = a.sample or lens_samples.sample_of(a.lens)
    filt = lens_samples.canonical_filter(a.filt)
    ch = lens_samples.channel(filt)
    coord = lens_samples.coord(a.lens, sample)

    mdir = cutout_paths.mosaic_dir(ws_path, sample, a.lens, filt, a.variant)
    i2d = cutout_paths.find_i2d(mdir)
    if i2d is None:
        print(f'=== NO MOSAIC: {mdir} -- run reduce_nircam.py first')
        return 0
    out_dir = a.output or cutout_paths.cutout_dir(ws_path, sample, a.lens, filt, a.size)
    os.makedirs(out_dir, exist_ok=True)
    sci_path = os.path.join(out_dir, cutout_paths.stamp_name(cutout_paths.PREFIX, 'sci', a.variant))
    noise_path = os.path.join(out_dir, cutout_paths.stamp_name(cutout_paths.PREFIX, 'noise', a.variant))
    png_path = os.path.join(out_dir, cutout_paths.stamp_png_name(cutout_paths.PREFIX, a.variant))
    others = {v: pth for v, pth in cutout_paths.list_stamps(out_dir, cutout_paths.PREFIX, 'sci').items() if v != a.variant}
    if others and not a.output:
        if not a.force:
            print(f'=== REFUSED: {out_dir} already holds another reduction\'s stamp '
                  f'({", ".join(os.path.basename(x) for x in others.values())}); --force replaces it')
            return 1
        for v in others:
            for kind in cutout_paths.STAMP_KINDS:
                pth = os.path.join(out_dir, cutout_paths.stamp_name(cutout_paths.PREFIX, kind, v))
                if os.path.exists(pth):
                    os.remove(pth)
            pth = os.path.join(out_dir, cutout_paths.stamp_png_name(cutout_paths.PREFIX, v))
            if os.path.exists(pth):
                os.remove(pth)

    print(f'=== {sample}/{a.lens} {filt}: {os.path.basename(i2d)} -> {out_dir}')
    with fits.open(i2d) as h:
        phdr = h[0].header
        sci_hdr = h['SCI'].header
        sci = h['SCI'].data.astype(np.float64)
        err = h['ERR'].data.astype(np.float64)
        wht = h['WHT'].data.astype(np.float64)
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        wcs = WCS(sci_hdr)
    scale = float(np.mean(proj_plane_pixel_scales(wcs.celestial)) * 3600.0)
    native = lens_samples.NATIVE_SCALE[ch]

    position = coord
    centre_note = 'catalogue'
    if a.center == 'peak':
        pre = Cutout2D(sci, position=coord, size=u.Quantity((a.size, a.size), u.arcsec), wcs=wcs,
                       mode='partial', fill_value=np.nan)
        r, c = brightest_pixel_position(pre.data, a.box, a.median_size)
        position = pre.wcs.pixel_to_world(c, r)
        centre_note = f'peak (box {a.box}, median {a.median_size})'
    size_q = u.Quantity((a.size, a.size), u.arcsec)
    cut = Cutout2D(sci, position=position, size=size_q, wcs=wcs, mode='partial', fill_value=np.nan)
    cut_err = Cutout2D(err, position=position, size=size_q, wcs=wcs, mode='partial', fill_value=np.nan)
    cut_wht = Cutout2D(wht, position=position, size=size_q, wcs=wcs, mode='partial', fill_value=0.0)

    corr, corr_src = resolve_corr_factor(a.corr_factor, ch, filt, sample, a.lens)
    pixfrac = sci_hdr.get('PIXFRAC', phdr.get('PIXFRAC'))
    casr = casertano_r(pixfrac, scale / native)

    s = cut.data.copy()
    n = cut_err.data * corr
    bad = ~np.isfinite(s) | ~np.isfinite(n) | (n <= 0) | ~(cut_wht.data > 0)
    s[bad] = 0.0
    n[bad] = SENTINEL
    wu = weight_uniformity(cut_wht.data)

    base_hdr = sci_hdr.copy()
    for k in ('XPOSURE', 'TELAPSE', 'FILTER', 'PUPIL', 'INSTRUME', 'DETECTOR', 'CHANNEL',
              'PROGRAM', 'OBSERVTN', 'VISIT', 'DATE-OBS', 'CAL_VER', 'CRDS_CTX', 'TARGPROP'):
        if k in phdr and k not in base_hdr:
            base_hdr[k] = phdr[k]
    base_hdr['BUNIT'] = (sci_hdr.get('BUNIT', 'MJy/sr'), 'surface brightness units of the stamp')
    base_hdr['PIXSCALE'] = (round(scale, 6), 'arcsec/pixel (from the WCS)')
    base_hdr['CUTSIZE'] = (a.size, 'stamp side, arcsec')
    base_hdr['CUTCENT'] = (centre_note, 'how the stamp centre was chosen')
    base_hdr['CUTRA'] = (float(position.ra.deg), 'stamp centre RA, deg')
    base_hdr['CUTDEC'] = (float(position.dec.deg), 'stamp centre Dec, deg')
    base_hdr['REDUCVAR'] = (a.variant or 'standard', 'reduction variant (cutout_paths.py)')
    base_hdr['NBADPIX'] = (int(bad.sum()), 'pixels set to sci=0, noise=1e8')
    noise_hdr = base_hdr.copy()
    noise_hdr['NOISESRC'] = ('i2d ERR', 'propagated sigma: sqrt(VAR_POISSON+RNOISE+FLAT)')
    noise_hdr['NOISECOR'] = (corr, 'inflation applied to ERR (noise_corr_factors.json)')
    noise_hdr['NOISECRS'] = (corr_src, 'where NOISECOR came from')
    if casr is not None:
        noise_hdr['CASR'] = (round(casr, 4), 'Casertano R for this pixfrac/scale (info only)')
    if wu is not None:
        noise_hdr['WHTUNIF'] = (round(wu, 6), 'weight-map RMS/median over the stamp')
        noise_hdr['WHTUNIFL'] = (WEIGHT_UNIFORMITY_LIMIT, 'STScI uniformity limit (<=)')

    write_fits(s.astype(np.float32), cut.wcs, base_hdr, sci_path)
    write_fits(n.astype(np.float64), cut.wcs, noise_hdr, noise_path)
    plot_cutouts(s, n, png_path, f'{a.lens} {filt} ({a.size:g}", {scale:.3f}"/px, x{corr:.2f} noise)')

    if wu is not None and wu > WEIGHT_UNIFORMITY_LIMIT:
        print(f'  WARNING: weight uniformity {wu:.3f} > {WEIGHT_UNIFORMITY_LIMIT}')
    if not a.output:
        info_json.update(cutout_paths.qc_json_path(ws_path, a.size), sample, a.lens, filt, {
            'i2d': os.path.relpath(i2d, ws_path), 'variant': a.variant or 'standard',
            'size_arcsec': a.size, 'shape': list(s.shape), 'pixel_scale': round(scale, 6),
            'center': centre_note, 'center_ra': float(position.ra.deg), 'center_dec': float(position.dec.deg),
            'n_bad': int(bad.sum()), 'weight_uniformity': None if wu is None else round(wu, 4),
            'corr_factor': corr, 'corr_source': corr_src, 'casertano_r': None if casr is None else round(casr, 4),
        })
    print(f'=== done {a.lens} {filt}: {s.shape[0]}x{s.shape[1]} px, {int(bad.sum())} bad px')
    return 0


if __name__ == '__main__':
    sys.exit(main())
