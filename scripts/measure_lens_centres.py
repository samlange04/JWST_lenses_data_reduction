#!/usr/bin/env python
"""
Measure each lens's light centre and record it as its deflector position, so make_stamps.py cuts
the stamps centred on the lens.

    uv run python scripts/measure_lens_centres.py --sample cowls_spectacular [--lens LENS] [--dry-run] [--force]

The stamps are cut at the lens's catalogue position (the mosaics' CRVAL). That misses the lens
light by 20-50 mas typically, and by ~0.4" for SPT2147-50 (its APT coordinate),
COSJ095917+015424 and COSJ095920+015851 (2026-11-01). The miss is the catalogue's error plus
our mosaics' absolute astrometry (relative alignment only, a-priori to ~0.1"). Modelling code,
the lens-light removal of the mask GUI and the band overview all assume the lens is at the
stamp centre.

Per band, on the modelling stamp, the lens core is the brightest pixel within 0.5" of the stamp
centre after a 1-px Gaussian smoothing, refined by a 3x3 parabola. Bright arcs or images can
outshine the lens in some bands. In the SW bands of COSJ100025+015245 the lensed images peak
0.46" from the lens; so does B1938+666's ring in F277W. So the LW bands, where the old stellar
light of the lens dominates, anchor the centre: their median peak. Every band within
AGREE_ARCSEC of the anchor then votes, and the deflector is the median of those bands' peaks.

The search is only 0.5" wide, so a catalogue position that is not ON the lens finds whatever
lies near it. COSJ095955+021900's COWLS II position sits on a lens-coloured knot 0.97" SW of a
galaxy 8x brighter in F444W, which COWLS II's own Fig. 2 centres on as the lens; the first run
(2026-11-01) took the knot. So every lens is checked for a peak at least BRIGHTER_FACTOR x the
chosen core within BRIGHTER_ARCSEC, which is printed as a warning and the lens is not written;
--near DE,DN (arcsec East, North of the catalogue position) then centres the search on the lens.

A lens that already has deflector_ra/dec (measured by hand: B1938+666) is skipped unless --force.
The result goes into info/samples/lens_samples.json as deflector_ra / deflector_dec /
deflector_note. ra/dec stay the mosaics' CRVAL. Then re-cut the stamps (run_stamps_all.sh,
--center auto) and move any drawn masks with them (AGENTS.md *Stamps*).
"""
import argparse
import datetime
import glob
import json
import os
import sys
import warnings

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS
from scipy.ndimage import gaussian_filter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lens_samples
import stamp_paths

ws_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEARCH_ARCSEC = 0.5       # the core is looked for within this of the stamp centre
AGREE_ARCSEC = 0.06       # a band votes if its peak is within this of the LW anchor (one LW px)
BRIGHTER_ARCSEC = 2.5     # look this far for a galaxy brighter than the chosen core
BRIGHTER_FACTOR = 3.0     # ... by at least this factor (smoothed peak), which flags the lens


def light_peak(sci, scale, search=SEARCH_ARCSEC, smooth_px=1.0, near=(0.0, 0.0)):
    """The core: (col, row) of the brightest smoothed pixel within `search` of the stamp centre
    (or of `near`, arcsec East, North of it), refined to sub-pixel by a 3-point parabola on each axis."""
    n = sci.shape[0]
    c = (n - 1) / 2.0
    sm = gaussian_filter(np.nan_to_num(sci), smooth_px)
    yy, xx = np.mgrid[:n, :n]
    win = np.hypot(xx - (c - near[0] / scale), yy - (c + near[1] / scale)) * scale <= search
    i, j = np.unravel_index(np.argmax(np.where(win, sm, -np.inf)), sm.shape)

    def vertex(a, b, cc):
        den = a - 2 * b + cc
        return 0.0 if den == 0 else float(np.clip(0.5 * (a - cc) / den, -0.5, 0.5))
    return j + vertex(sm[i, j - 1], sm[i, j], sm[i, j + 1]), i + vertex(sm[i - 1, j], sm[i, j], sm[i + 1, j])


def brighter_neighbour(sci, scale, col, row, smooth_px=1.5):
    """The brightest smoothed local peak within BRIGHTER_ARCSEC of (col, row) that is at least
    BRIGHTER_FACTOR x the smoothed value there, as (arcsec East, arcsec North of it, ratio), or None."""
    from scipy.ndimage import maximum_filter
    sm = gaussian_filter(np.nan_to_num(sci), smooth_px)
    n = sci.shape[0]
    yy, xx = np.mgrid[:n, :n]
    core = sm[int(round(row)), int(round(col))]
    pk = (sm == maximum_filter(sm, 7)) & (np.hypot(xx - col, yy - row) * scale <= BRIGHTER_ARCSEC) & (sm >= BRIGHTER_FACTOR * core)
    if core <= 0 or not pk.any():
        return None
    i, j = np.unravel_index(np.argmax(np.where(pk, sm, -np.inf)), sm.shape)
    return -(j - col) * scale, (i - row) * scale, float(sm[i, j] / core)


def measure(sample, lens, near=(0.0, 0.0)):
    prefix = stamp_paths.stamp_prefix(stamp_paths.modelling_size(lens, sample))
    peaks, brighter = {}, {}
    for d in stamp_paths.band_dirs(stamp_paths.stamps_root(ws_path), sample, lens, 'F*'):
        f = stamp_paths.find_stamp(d, prefix, 'sci')
        if f is None:
            continue
        hdr = fits.getheader(f)
        sci = fits.getdata(f).astype(float)
        scale = float(hdr['PIXSCALE'])
        # the stamp may be cut on an earlier deflector: `near` is relative to the catalogue position
        cat_col, cat_row = (float(v) for v in WCS(hdr).world_to_pixel(lens_samples.coord(lens, sample)))
        c = (sci.shape[0] - 1) / 2.0
        off = (near[0] - (cat_col - c) * scale, near[1] + (cat_row - c) * scale)
        col, row = light_peak(sci, scale, near=off)
        peaks[os.path.basename(d)] = WCS(hdr).pixel_to_world(col, row)
        b = brighter_neighbour(sci, scale, col, row)
        if b is not None:
            brighter[os.path.basename(d)] = b
    lw = [f for f in peaks if lens_samples.channel(f) == 'LW']
    if not lw:
        return None
    from astropy.coordinates import SkyCoord
    import astropy.units as u
    anchor = SkyCoord(np.median([peaks[f].ra.deg for f in lw]) * u.deg, np.median([peaks[f].dec.deg for f in lw]) * u.deg)
    votes = [f for f in peaks if peaks[f].separation(anchor).arcsec <= AGREE_ARCSEC] or lw
    centre = SkyCoord(np.median([peaks[f].ra.deg for f in votes]) * u.deg,
                      np.median([peaks[f].dec.deg for f in votes]) * u.deg)
    cat = lens_samples.coord(lens, sample)
    de, dn = cat.spherical_offsets_to(centre)
    return dict(centre=centre, votes=votes, rejected=sorted(set(peaks) - set(votes)), brighter=brighter,
                east_mas=float(de.to(u.mas).value), north_mas=float(dn.to(u.mas).value),
                spread_mas=float(max(peaks[f].separation(centre).arcsec for f in votes) * 1e3))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--sample', type=lens_samples.sample_arg, default=None,
                   help='every lens of this sample (not needed with --lens: its sample is found)')
    p.add_argument('--lens', default=None)
    p.add_argument('--dry-run', action='store_true', help='print, do not write lens_samples.json')
    p.add_argument('--force', action='store_true', help='re-measure a lens that already has a deflector')
    p.add_argument('--near', default=None, metavar='DE,DN',
                   help='search around this offset (arcsec East, North of the catalogue position), for a '
                        'lens whose catalogue position is not on it; needs --lens')
    p.add_argument('--note', default=None, help='appended to deflector_note (why --near was needed)')
    a = p.parse_args()
    lens_samples.resolve_sample(p, a, required=True)
    if a.near and not a.lens:
        p.error('--near needs --lens')
    near = tuple(float(v) for v in a.near.split(',')) if a.near else (0.0, 0.0)
    warnings.simplefilter('ignore')
    with open(lens_samples.SAMPLES_JSON) as f:
        data = json.load(f)
    changed = False
    for lens in lens_samples.lenses(a.sample):
        if a.lens and lens != a.lens:
            continue
        e = data[a.sample]['lenses'][lens]
        if 'deflector_ra' in e and not a.force:
            print(f'{lens}: has a deflector already ({e.get("deflector_note", "")[:60]}...), skipped')
            continue
        m = measure(a.sample, lens, near)
        if m is None:
            print(f'{lens}: no LW stamp, skipped')
            continue
        lw_brighter = {f: b for f, b in m['brighter'].items() if lens_samples.channel(f) == 'LW'}
        if lw_brighter:
            f, (be, bn, ratio) = next(iter(lw_brighter.items()))
            print(f'{lens}: WARNING, in {f} a peak {ratio:.1f}x brighter than the core found lies {be:+.2f}" E '
                  f'{bn:+.2f}" N of it: the catalogue position may not be on the lens. Not written; look at the '
                  f'stamp and re-run with --lens {lens} --near DE,DN (arcsec from the catalogue position).')
            continue
        print(f'{lens:18s} {m["east_mas"]:+6.0f} mas E {m["north_mas"]:+6.0f} mas N of the catalogue; '
              f'{len(m["votes"])} bands within {m["spread_mas"]:.0f} mas'
              + (f' (left out: {", ".join(m["rejected"])})' if m['rejected'] else ''))
        if a.dry_run:
            continue
        e['deflector_ra'] = round(float(m['centre'].ra.deg), 8)
        e['deflector_dec'] = round(float(m['centre'].dec.deg), 8)
        e['deflector_note'] = (
            f'Lens-light peak, measure_lens_centres.py ({datetime.date.today().isoformat()}): the median smoothed peak of '
            f'{", ".join(sorted(m["votes"]))}, which agree to {m["spread_mas"]:.0f} mas'
            + (f' ({", ".join(m["rejected"])} left out, >{AGREE_ARCSEC * 1e3:.0f} mas from the LW peak)' if m['rejected'] else '')
            + f'; {m["east_mas"]:+.0f} mas E, {m["north_mas"]:+.0f} mas N of ra/dec, which stay the mosaics\' CRVAL. '
            f'make_stamps --center auto cuts the stamp here, snapped to the 0.06" LW grid.'
            + (f' Searched around {near[0]:+.2f}" E, {near[1]:+.2f}" N of ra/dec (--near). {a.note or ""}'.rstrip() if a.near else ''))
        changed = True
    if changed:
        with open(lens_samples.SAMPLES_JSON, 'w') as f:
            f.write(json.dumps(data, indent=4, ensure_ascii=False) + '\n')
        print(f'wrote {lens_samples.SAMPLES_JSON}')


if __name__ == '__main__':
    sys.exit(main())
