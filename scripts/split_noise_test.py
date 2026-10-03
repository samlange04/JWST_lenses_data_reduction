#!/usr/bin/env python
"""
Split-dither null test of a band's noise map: the correlated-noise factor for a field too
deep or too crowded for the blank-sky method (B1938+666 at 88 ks).

    uv run python scripts/split_noise_test.py --lens B1938+666 --filt F115W [--jobs 2]

The band's dithers (exposure roots, every detector of a dither kept together) are split into
two interleaved halves and each half is run through Image3 exactly as the standard product
is (reduce_nircam.run_image3: same grid, tweakreg relative, skymatch, outlier_detection) into
data/mosaics_splitA|splitB/<sample>/<lens>/<FILT>/. The difference D = A - B cancels every
astrophysical feature -- faint galaxies, star halos, diffraction spikes, the lens -- and
leaves pure noise with the dataset's own correlation structure. Its predicted variance is
ERR_A^2 + ERR_B^2 pixel by pixel, so

    ratio(s) = robust std of (block sum of D over s x s) / sqrt(block sum of ERR_A^2 + ERR_B^2)

is the same empirical/ERR ratio that applies to the full mosaic's noise map at scale s
(the half mosaics have the same ERR deficit and the same 1/f geometry as the full one; only
the depth differs, which cancels in the ratio). Measured over the whole footprint both
halves cover, and separately inside the 12" stamp region (both halves cover it fully), at
measure_corr_factor.BLOCKS_ARCSEC, plus the row-/column-direction split of the 1-D sums at
0.2" (anisotropy from the 1/f along detector rows). Writes diagnostics/split_noise/<lens>_<FILT>.json
and prints the numbers to copy into info/noise_corr_factors.json lens_overrides.
"""
import argparse
import glob
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lens_samples                                   # noqa: E402
import cutout_paths                                   # noqa: E402
import reduce_nircam                                  # noqa: E402
from measure_corr_factor import BLOCKS_ARCSEC, robust_std   # noqa: E402

WS = reduce_nircam.ws_path


def _exposure_root(cal):
    return reduce_nircam._rootname(cal).rsplit('_', 1)[0]


def split_halves(cals):
    roots = sorted({_exposure_root(c) for c in cals})
    a = {r for i, r in enumerate(roots) if i % 2 == 0}
    return ([c for c in cals if _exposure_root(c) in a], [c for c in cals if _exposure_root(c) not in a], len(roots))


def build_half(cals, sample, lens, filt, tag, coord, scale, field):
    out_dir = cutout_paths.mosaic_dir(WS, sample, lens, filt, tag)
    name = f'{lens.replace("+", "p")}_{filt}'.lower()
    i2d = os.path.join(out_dir, f'{name}_i2d.fits')
    if os.path.exists(i2d):
        print(f'  {tag}: exists, {i2d}')
        return i2d
    reduce_nircam.setup_crds()
    return reduce_nircam.run_image3(cals, out_dir, name, coord, scale, field, 'relative')


def block_curve(D, var, ok, scale):
    """ratio(s) for s in BLOCKS_ARCSEC from n x n block sums; pairs one block apart as in
    measure_corr_factor.block_ratio, horizontally AND vertically (both directions pooled)."""
    out = {}
    for s in BLOCKS_ARCSEC:
        n = max(1, int(round(s / scale)))
        ny, nx = D.shape[0] // n, D.shape[1] // n
        sl = (slice(0, ny * n), slice(0, nx * n))
        S = np.where(ok, D, 0.0)[sl].reshape(ny, n, nx, n).sum(axis=(1, 3))
        V = np.where(ok, var, 0.0)[sl].reshape(ny, n, nx, n).sum(axis=(1, 3))
        good = ok[sl].reshape(ny, n, nx, n).all(axis=(1, 3))
        z = np.concatenate([((S[:, :-2] - S[:, 2:]) / np.sqrt(V[:, :-2] + V[:, 2:]))[good[:, :-2] & good[:, 2:]],
                            ((S[:-2, :] - S[2:, :]) / np.sqrt(V[:-2, :] + V[2:, :]))[good[:-2, :] & good[2:, :]]]) / np.sqrt(2)
        z = z[np.isfinite(z)]
        if z.size < 20:
            out[f'{n * scale:.2f}'] = None
            continue
        rng = np.random.default_rng(0)
        out[f'{n * scale:.2f}'] = dict(npix=n, ratio=float(robust_std(z)), npairs=int(z.size),
                                       err=float(np.std([robust_std(rng.choice(z, z.size)) for _ in range(100)])))
    return out


def direction_split(D, var, ok, scale, s_arcsec, det_angle_deg):
    """1-D sums of length s along vs across the detector-row direction (rotate D so rows
    are horizontal), ratio against ERR: the anisotropy the scalar factor hides."""
    from scipy import ndimage
    n = max(2, int(round(s_arcsec / scale)))
    Dr = ndimage.rotate(np.where(ok, D, np.nan), -det_angle_deg, reshape=True, order=0, cval=np.nan)
    Vr = ndimage.rotate(np.where(ok, var, np.nan), -det_angle_deg, reshape=True, order=0, cval=np.nan)
    res = {}
    for name, axis in (('along_rows', 1), ('across_rows', 0)):
        if axis == 1:
            ny, nx = Dr.shape[0], Dr.shape[1] // n
            S = Dr[:, :nx * n].reshape(ny, nx, n).sum(axis=2); V = Vr[:, :nx * n].reshape(ny, nx, n).sum(axis=2)
            z = ((S[:, :-2] - S[:, 2:]) / np.sqrt(V[:, :-2] + V[:, 2:])).ravel() / np.sqrt(2)
        else:
            ny, nx = Dr.shape[0] // n, Dr.shape[1]
            S = Dr[:ny * n].reshape(ny, n, nx).sum(axis=1); V = Vr[:ny * n].reshape(ny, n, nx).sum(axis=1)
            z = ((S[:-2] - S[2:]) / np.sqrt(V[:-2] + V[2:])).ravel() / np.sqrt(2)
        z = z[np.isfinite(z)]
        res[name] = float(robust_std(z)) if z.size > 20 else None
    return res


def detector_row_angle(cal):
    """Angle of the detector x axis on the North-up grid (deg), from the cal's FITS WCS."""
    from astropy.io import fits
    from astropy.wcs import WCS
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        w = WCS(fits.getheader(cal, 'SCI'))
    pc = w.wcs.pc if w.wcs.has_pc() else w.wcs.cd
    return float(np.degrees(np.arctan2(pc[1, 0], pc[0, 0])))


def analyse(i2d_a, i2d_b, scale, size_arcsec, det_angle):
    from astropy.io import fits
    A, B = fits.open(i2d_a), fits.open(i2d_b)
    sa, sb = A['SCI'].data.astype(float), B['SCI'].data.astype(float)
    ea, eb = A['ERR'].data.astype(float), B['ERR'].data.astype(float)
    wa, wb = A['WHT'].data, B['WHT'].data
    ok = np.isfinite(sa) & np.isfinite(sb) & (ea > 0) & (eb > 0) & (wa > 0) & (wb > 0)
    D = sa - sb
    var = ea ** 2 + eb ** 2
    # per-pixel sanity: median |D| / sqrt(var)
    z = D[ok] / np.sqrt(var[ok])
    res = {'per_pixel_ratio': float(robust_std(z)), 'n_ok': int(ok.sum())}
    res['field'] = block_curve(D, var, ok, scale)
    c = D.shape[0] // 2; h = int(round(size_arcsec / scale / 2))
    st = (slice(c - h, c + h), slice(c - h, c + h))
    res['stamp'] = block_curve(D[st], var[st], ok[st], scale)
    res['direction_0.2arcsec'] = direction_split(D, var, ok, scale, 0.2, det_angle)
    res['direction_1arcsec'] = direction_split(D, var, ok, scale, 1.0, det_angle)
    return res


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--lens', required=True)
    p.add_argument('--filt', required=True)
    p.add_argument('--sample', default=None)
    p.add_argument('--analyse-only', action='store_true')
    a = p.parse_args()
    sample = a.sample or lens_samples.sample_of(a.lens)
    filt = lens_samples.canonical_filter(a.filt)
    ch = lens_samples.channel(filt)
    scale = reduce_nircam.DEFAULT_SCALE[ch]
    coord = lens_samples.coord(a.lens, sample)
    cals = sorted(glob.glob(os.path.join(reduce_nircam._stage_dir('stage2', sample, a.lens, filt), '*_cal.fits')))
    if not cals:
        sys.exit(f'no cal files for {a.lens} {filt}')
    half_a, half_b, n_exp = split_halves(cals)
    print(f'=== {sample}/{a.lens} {filt}: {len(cals)} cals, {n_exp} exposures -> A {len(half_a)} / B {len(half_b)}')
    i2d = {}
    for tag, cl in (('splitA', half_a), ('splitB', half_b)):
        i2d[tag] = build_half(cl, sample, a.lens, filt, tag, coord, scale, reduce_nircam.DEFAULT_FIELD) if not a.analyse_only \
            else os.path.join(cutout_paths.mosaic_dir(WS, sample, a.lens, filt, tag), f'{a.lens.replace("+", "p")}_{filt}'.lower() + '_i2d.fits')
    ang = detector_row_angle(cals[0])
    res = analyse(i2d['splitA'], i2d['splitB'], scale, cutout_paths.DEFAULT_SIZE, ang)
    res.update(lens=a.lens, filt=filt, sample=sample, scale=scale, n_exposures=n_exp,
               n_cals=[len(half_a), len(half_b)], detector_row_angle_deg=ang, i2d=i2d)
    out_dir = os.path.join(WS, 'diagnostics', 'split_noise'); os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f'{a.lens}_{filt}.json')
    with open(out, 'w') as fh:
        json.dump(res, fh, indent=2)
    print(f'  per-pixel |D|/sqrt(ERR_A^2+ERR_B^2): {res["per_pixel_ratio"]:.3f}   (drizzle predicts ~0.7)')
    for region in ('field', 'stamp'):
        print(f'  {region:5s} block ratio: ' + '  '.join(f'{k}":{v["ratio"]:.2f}' for k, v in res[region].items() if v))
    for key in ('direction_0.2arcsec', 'direction_1arcsec'):
        d = res[key]; print(f'  {key}: along rows {d["along_rows"]}, across rows {d["across_rows"]}')
    print(f'  wrote {out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
