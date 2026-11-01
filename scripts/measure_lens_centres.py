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

A lens that already has deflector_ra/dec (measured by hand: B1938+666) is skipped unless --force.
The result goes into info/samples/lens_samples.json as deflector_ra / deflector_dec /
deflector_note. ra/dec stay the mosaics' CRVAL. Then re-cut the stamps (run_stamps_all.sh,
--center auto) and move any drawn masks with them (AGENTS.md *Stamps*).
"""
import argparse
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


def light_peak(sci, scale, search=SEARCH_ARCSEC, smooth_px=1.0):
    """The core: (col, row) of the brightest smoothed pixel within `search` of the stamp centre,
    refined to sub-pixel by a 3-point parabola on each axis."""
    n = sci.shape[0]
    c = (n - 1) / 2.0
    sm = gaussian_filter(np.nan_to_num(sci), smooth_px)
    yy, xx = np.mgrid[:n, :n]
    win = np.hypot(xx - c, yy - c) * scale <= search
    i, j = np.unravel_index(np.argmax(np.where(win, sm, -np.inf)), sm.shape)

    def vertex(a, b, cc):
        den = a - 2 * b + cc
        return 0.0 if den == 0 else float(np.clip(0.5 * (a - cc) / den, -0.5, 0.5))
    return j + vertex(sm[i, j - 1], sm[i, j], sm[i, j + 1]), i + vertex(sm[i - 1, j], sm[i, j], sm[i + 1, j])


def measure(sample, lens):
    prefix = stamp_paths.stamp_prefix(stamp_paths.modelling_size(lens, sample))
    peaks = {}
    for d in sorted(glob.glob(os.path.join(ws_path, 'data', 'stamps', sample, lens, 'F*'))):
        f = stamp_paths.find_stamp(d, prefix, 'sci')
        if f is None:
            continue
        hdr = fits.getheader(f)
        col, row = light_peak(fits.getdata(f).astype(float), float(hdr['PIXSCALE']))
        peaks[os.path.basename(d)] = WCS(hdr).pixel_to_world(col, row)
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
    return dict(centre=centre, votes=votes, rejected=sorted(set(peaks) - set(votes)),
                east_mas=float(de.to(u.mas).value), north_mas=float(dn.to(u.mas).value),
                spread_mas=float(max(peaks[f].separation(centre).arcsec for f in votes) * 1e3))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--sample', type=lens_samples.sample_arg, required=True)
    p.add_argument('--lens', default=None)
    p.add_argument('--dry-run', action='store_true', help='print, do not write lens_samples.json')
    p.add_argument('--force', action='store_true', help='re-measure a lens that already has a deflector')
    a = p.parse_args()
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
        m = measure(a.sample, lens)
        if m is None:
            print(f'{lens}: no LW stamp, skipped')
            continue
        print(f'{lens:18s} {m["east_mas"]:+6.0f} mas E {m["north_mas"]:+6.0f} mas N of the catalogue; '
              f'{len(m["votes"])} bands within {m["spread_mas"]:.0f} mas'
              + (f' (left out: {", ".join(m["rejected"])})' if m['rejected'] else ''))
        if a.dry_run:
            continue
        e['deflector_ra'] = round(float(m['centre'].ra.deg), 8)
        e['deflector_dec'] = round(float(m['centre'].dec.deg), 8)
        e['deflector_note'] = (
            f'Lens-light peak, measure_lens_centres.py (2026-11-01): the median smoothed peak of '
            f'{", ".join(sorted(m["votes"]))}, which agree to {m["spread_mas"]:.0f} mas'
            + (f' ({", ".join(m["rejected"])} left out, >{AGREE_ARCSEC * 1e3:.0f} mas from the LW peak)' if m['rejected'] else '')
            + f'; {m["east_mas"]:+.0f} mas E, {m["north_mas"]:+.0f} mas N of ra/dec, which stay the mosaics\' CRVAL. '
            f'make_stamps --center auto cuts the stamp here, snapped to the 0.06" LW grid.')
        changed = True
    if changed:
        with open(lens_samples.SAMPLES_JSON, 'w') as f:
            f.write(json.dumps(data, indent=4, ensure_ascii=False) + '\n')
        print(f'wrote {lens_samples.SAMPLES_JSON}')


if __name__ == '__main__':
    sys.exit(main())
