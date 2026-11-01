#!/usr/bin/env python
"""
One figure per lens with every band's stamp side by side: data/stamps/<sample>/<lens>/stamp<S>_bands.png.

    uv run python scripts/make_band_overview.py                          # every lens of every sample
    uv run python scripts/make_band_overview.py --sample cowls_spectacular [--lens LENS]

The per-band QC (stamp<S>_dataset.png) shows one band's data, noise, PSF and mask; this shows all
of a lens's bands at once, so the lens and its arcs can be compared across wavelength. Columns are
the bands in wavelength order. Rows:
  1. the full stamp as observed, with the band's contaminant mask outlined (red) where drawn;
  2. a zoom on the lens (+-max(2.5 theta_E, 1.5")), as observed;
  3. the same zoom with the lens light removed (its azimuthal median, masked pixels left out),
     with the image positions (cyan +) where marked and the Einstein radius (dashed).
The zooms, the theta_E circle and the lens-light profile are centred on the lens's measured
centre (deflector_ra/dec, measure_lens_centres.py; else the catalogue position), at its exact
sub-pixel position: the stamps are cut on it but snapped to the 0.06" LW grid, and a profile even
half a pixel off the lens leaves a dipole. The residual offset is printed in the header.
Every panel has its own arcsinh stretch (autogalaxy's arcsinh_stretch, as the GUIs). North is up
and East left (the stamps' rows run South to North, columns East to West). The primary band
(lens_samples.primary_band: reviewed, or choose_primary_band.py's suggestion) is starred, and
the header gives the lens and source redshifts, theta_E and the primary band's source.

make_masks.py, make_positions.py and choose_primary_band.py re-render it after they write; a
re-cut of the stamps (make_stamps.py) does not, so run this after one. Tracked in git with the
stamps (it is a stamp<S>_* file), so it costs ~0.3-0.6 MB of history per render.
"""
import argparse
import glob
import json
import os
import sys
import warnings

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from astropy.io import fits

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lens_samples
import stamp_paths

ws_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FILTER_UM = {'F070W': 0.70, 'F090W': 0.90, 'F115W': 1.15, 'F150W': 1.50, 'F200W': 2.00,
             'F277W': 2.77, 'F356W': 3.56, 'F444W': 4.44}


def load_band(stamp_dir, prefix):
    """The band's sci (no-data pixels NaN), pixel scale, mask (or None), positions (or [])."""
    sci_f = stamp_paths.find_stamp(stamp_dir, prefix, 'sci')
    noise_f = stamp_paths.find_stamp(stamp_dir, prefix, 'noise')
    if sci_f is None:
        return None
    sci = fits.getdata(sci_f).astype(float)
    hdr = fits.getheader(sci_f)
    if noise_f is not None:
        sci = np.where(fits.getdata(noise_f) >= 1e7, np.nan, sci)
    scale = float(hdr['PIXSCALE'])
    mask_f = os.path.join(stamp_dir, f'{prefix}_mask.fits')
    mask = fits.getdata(mask_f).astype(bool) if os.path.exists(mask_f) else None
    pos_f = os.path.join(stamp_dir, f'{prefix}_positions.json')
    positions = []
    if os.path.exists(pos_f):
        with open(pos_f) as f:
            d = json.load(f)
        positions = d['arguments']['values']['array'] if isinstance(d, dict) and 'arguments' in d else d
    return dict(sci=sci, scale=scale, mask=mask, positions=[tuple(p) for p in positions], hdr=hdr)


def radial_subtract(img, cx, cy, exclude=None):
    """`img` minus its azimuthal median profile about the sub-pixel centre (cx, cy) (pixels;
    1-px annuli), `exclude` left out of the medians. autogalaxy's radial_median_subtract (the
    mask GUI's) takes the profile about the ARRAY centre, a pixel corner here, and a lens even
    half a pixel from it leaves a strong dipole."""
    n_y, n_x = img.shape
    yy, xx = np.mgrid[:n_y, :n_x]
    rb = np.hypot(xx - cx, yy - cy).astype(int)
    use = np.isfinite(img) if exclude is None else (np.isfinite(img) & ~exclude)
    prof = np.zeros(rb.max() + 1)
    for k in range(prof.size):
        ring = img[(rb == k) & use]
        if ring.size:
            prof[k] = np.median(ring)
    return img - prof[rb]


def render(sample, lens, out=None):
    from autogalaxy.gui.display_util import arcsinh_stretch, mask_boundary
    prefix = stamp_paths.stamp_prefix(stamp_paths.modelling_size(lens, sample))
    lens_dir = os.path.join(stamp_paths.stamps_root(ws_path), sample, lens)
    bands = {}
    for d in glob.glob(os.path.join(lens_dir, 'F*')):
        b = load_band(d, prefix)
        if b is not None:
            bands[os.path.basename(d)] = b
    if not bands:
        return None
    filts = sorted(bands, key=lambda f: FILTER_UM.get(f, 99))
    te = lens_samples.theta_e(lens, sample)
    zl, zs = lens_samples.redshifts(lens, sample)
    primary, psource = lens_samples.primary_band(lens, sample)
    half_zoom = max(2.5 * (te or 0.6), 1.5)
    # The lens centre: the measured deflector (lens_samples.json, measure_lens_centres.py), else
    # the catalogue position, as (East, North) arcsec from the stamp centre. The stamps are cut on
    # it, snapped to the 0.06" LW grid, so it sits within ~30 mas of the centre; one sky point for
    # every band, so the zooms stay registered.
    from astropy.wcs import WCS
    target = lens_samples.deflector_coord(lens, sample) or lens_samples.coord(lens, sample)
    h0, n_, s0 = bands[filts[-1]]['hdr'], bands[filts[-1]]['sci'].shape[0], bands[filts[-1]]['scale']
    tx, ty = (float(v) for v in WCS(h0).world_to_pixel(target))
    e0, n0 = -(tx - (n_ - 1) / 2.0) * s0, (ty - (n_ - 1) / 2.0) * s0

    ncol = len(filts)
    fig, axes = plt.subplots(3, ncol, figsize=(max(3.0 * ncol, 8.0), 9.8), squeeze=False)
    for j, f in enumerate(filts):
        b = bands[f]
        sci, s, mask = b['sci'], b['scale'], b['mask']
        n = sci.shape[0]
        c = (n - 1) / 2.0
        # Rows run South -> North and columns East -> West. Every panel is in arcsec from the
        # stamp centre, East (left) and North positive: pixel (col j, row i) is at
        # East -(j - c) s, North (i - c) s.
        lx, ly = c - e0 / s, c + n0 / s                      # the lens centre in pixels
        sub = radial_subtract(sci, lx, ly, exclude=mask)
        zp = int(np.ceil(half_zoom / s)) + 1
        j0, i0 = max(0, int(round(lx)) - zp), max(0, int(round(ly)) - zp)
        j1, i1 = min(n, int(round(lx)) + zp + 1), min(n, int(round(ly)) + zp + 1)
        for i, (img, zoom) in enumerate(((sci, False), (sci, True), (sub, True))):
            ax = axes[i, j]
            rs, cs = (slice(i0, i1), slice(j0, j1)) if zoom else (slice(0, n), slice(0, n))
            a = img[rs, cs]
            ext = [-(cs.start - 0.5 - c) * s, -(cs.stop - 0.5 - c) * s, (rs.start - 0.5 - c) * s, (rs.stop - 0.5 - c) * s]
            ax.imshow(arcsinh_stretch(a), origin='lower', cmap='gray', extent=ext, interpolation='nearest')
            if mask is not None and mask[rs, cs].any():
                edge = mask_boundary(mask[rs, cs])
                rgba = np.zeros(edge.shape + (4,))
                rgba[edge] = (1.0, 0.15, 0.15, 0.9)
                ax.imshow(rgba, origin='lower', extent=ext, interpolation='nearest')
            if zoom:
                xl, yl = (e0 + half_zoom, e0 - half_zoom), (n0 - half_zoom, n0 + half_zoom)
            else:
                h = (n / 2.0) * s
                xl, yl = (h, -h), (-h, h)
            if i == 2:
                if te:
                    t = np.linspace(0, 2 * np.pi, 200)
                    ax.plot(e0 + te * np.cos(t), n0 + te * np.sin(t), ls='--', lw=0.8, color='gold', alpha=0.8)
                for y, x in b['positions']:
                    # autoarray (y, x) about the stamp centre: y points toward row 0 (South
                    # here), x toward higher columns (West), so (East, North) = (-x, -y)
                    ax.plot(-x, -y, '+', color='cyan', ms=9, mew=1.4)
            ax.set_xlim(*xl)
            ax.set_ylim(*yl)
            ax.set_xticks([]); ax.set_yticks([])
            if i == 0:
                star = ' ★' if f == primary else ''
                ax.set_title(f'{f}{star}\n{s:.2f}"/px', fontsize=10,
                             color='darkred' if f == primary else 'black')
            if j == 0:
                ax.set_ylabel(['as observed (full stamp)', 'as observed (zoom on the lens)',
                               'lens light removed (zoom)'][i], fontsize=9)
            # 1" scale bar, bottom right
            (xa, xb), (ya, yb) = xl, yl
            wx, wy = xa - xb, yb - ya
            bx, by = xb + 0.1 * wx + 1.0, ya + 0.08 * wy
            ax.plot([bx, bx - 1.0], [by, by], color='white', lw=2)
            ax.text(bx - 0.5, by + 0.04 * wy, '1"', color='white', ha='center', fontsize=8)
            if i == 0 and j == 0:                         # compass, top left: N up, E left
                ox, oy, L = xa - 0.45 * wx, yb - 0.55 * wy, 0.16 * wx
                ax.annotate('', xy=(ox, oy + L), xytext=(ox, oy),
                            arrowprops=dict(arrowstyle='->', color='white', lw=1.2))
                ax.annotate('', xy=(ox + L, oy), xytext=(ox, oy),
                            arrowprops=dict(arrowstyle='->', color='white', lw=1.2))
                ax.text(ox, oy + L * 1.12, 'N', color='white', ha='center', va='bottom', fontsize=8)
                ax.text(ox + L * 1.12, oy, 'E', color='white', ha='right', va='center', fontsize=8)
    zl_s = f'{zl:.3f}' if zl is not None else '?'
    zs_s = f'{zs:.3f}' if zs is not None else '?'
    te_s = f'{te:.2f}"' if te else '?'
    prim = f'{primary} ({psource})' if primary else 'not set (no band measurable)'
    fig.suptitle(f'{lens}  ({sample})   z_l {zl_s}   z_s {zs_s}   θ_E {te_s}\n'
                 f'primary band: {prim}  (★)    zooms centred on the measured lens centre, '
                 f'{1e3 * e0:+.0f} mas E, {1e3 * n0:+.0f} mas N of the stamp centre\n'
                 f'red: contaminant mask   cyan +: image positions   dashed: θ_E', fontsize=9.5)
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    out = out or os.path.join(lens_dir, f'{prefix}_bands.png')
    fig.savefig(out, dpi=90)
    plt.close(fig)
    return out


def rerender(sample, lens):
    """Best-effort re-render for the GUIs' hooks: never fatal, a hand-drawn product must not be
    lost to a plotting error."""
    try:
        out = render(sample, lens)
        if out:
            print(f'  band overview: {os.path.relpath(out, ws_path)}')
    except Exception as exc:                              # deliberately broad -- see docstring
        print(f'  NOTE: band overview not re-rendered for {lens} ({exc!r}); run '
              f'uv run python scripts/make_band_overview.py --sample {sample} --lens {lens}')


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--sample', type=lens_samples.sample_arg, default=None, help='default: every sample')
    p.add_argument('--lens', default=None)
    a = p.parse_args()
    warnings.simplefilter('ignore')
    for sample in ([a.sample] if a.sample else lens_samples.samples()):
        for lens in lens_samples.lenses(sample):
            if a.lens and lens != a.lens:
                continue
            out = render(sample, lens)
            print(f'{lens}: ' + (os.path.relpath(out, ws_path) if out else 'no stamps'))


if __name__ == '__main__':
    sys.exit(main())
