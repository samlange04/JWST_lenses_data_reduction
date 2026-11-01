#!/usr/bin/env python
"""
Download one lens's NIRCam exposures from MAST into a per-lens pool, and sort them by filter.

    uv run python scripts/download_nircam.py --lens SPT0418-47 [--sample spt] [--level uncal]

Why a POOL and not a per-filter download (the trap this script exists to avoid): a NIRCam
MAST *observation* is one filter (``jw01355-o016_t001_nircam_clear-f115w``) but its
*product list* is every file of the visit -- SW and LW are exposed simultaneously and the
visit's other SW filters share the same exposure IDs. Downloading "the F115W observation's
UNCAL files" therefore fetches F150W, F200W, F277W... files too, and nothing in the
filename says which filter a file is. So: download the whole visit's files once into
``data/calibrated/<sample>/<lens>/pool/``, read FILTER/PUPIL/DETECTOR off each header, and
hard-link the file into ``data/calibrated/<sample>/<lens>/<FILTER>/``. The pool is the
MAST cache; the filter dirs are what ``reduce_nircam.py`` reads.

``--level`` picks the starting product (default ``uncal``, see AGENTS.md *Starting level*):
    uncal   raw ramps  -> we run Detector1 ourselves (snowballs, 1/f ``clean_flicker_noise``)
    rate    MAST's Detector1 output  (~4.5x smaller; MAST's ops jwst version and settings)
    cal     MAST's Image2 output     (only useful for a quick look)

**Survey programs (``"mast_query": "position"`` in the sample block, e.g. COSMOS-Web):** the
targets are tiles, not lenses, and one visit spans ~10 arcmin^2 of which a lens needs one
detector or two. So the lens is found by position: every NIRCam/IMAGE observation of the
program within the mosaic field (``--field``, which must cover reduce_nircam.py's), then
only the detector files whose MAST footprint (``Mast.Jwst.Filtered.Nircam`` ``s_region``,
listed for the cal files, which map 1:1 onto uncal/rate names) overlaps that field. A file
MAST lists no footprint for is kept. Neighbouring lenses share exposures: a file already
in another lens's pool of the same sample is hard-linked from there, not downloaded again.

Idempotent: files already in the pool are skipped by astroquery (``cache=True``) and the
sort re-links everything, so re-running after a partial download is safe. Tracking:
``info/provenance/lens_downloads.json`` records, per lens, the level, the obs IDs, and the per-filter
file counts; ``null`` for a filter means MAST had nothing.
"""
import argparse
import glob
import os
import re
import sys
import warnings

import numpy as np
from astropy.io import fits

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lens_samples
import info_json

ws_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

LEVELS = {'uncal': 'UNCAL', 'rate': 'RATE', 'cal': 'CAL'}
_DET_RE = re.compile(r'_(nrc[ab][1-4]|nrc[ab]long)_')
_OBS_RE = re.compile(r'^jw\d{5}-o(\d{3})_')
DEFAULT_FIELD = 150.0       # arcsec; reduce_nircam.DEFAULT_FIELD, used where a sample sets no mosaic_field


def with_retries(fn, *args, attempts=10, wait=60, **kw):
    """Call a MAST query, retrying through dropped connections and server errors.

    `download` retries each file, but a query that fails kills the run before any file is
    fetched: on 2026-10-29 a ConnectionResetError in query_position lost two COWLS lenses
    during a network outage. Re-raises after `attempts` tries."""
    import time
    for attempt in range(1, attempts + 1):
        try:
            return fn(*args, **kw)
        except Exception as exc:
            if attempt == attempts:
                raise
            print(f'    {fn.__name__}: {exc.__class__.__name__} ({str(exc)[:80]}); '
                  f'retry {attempt}/{attempts - 1} in {wait}s', flush=True)
            time.sleep(wait)


def query_observations(sample, lens, filters=None):
    """MAST NIRCam/IMAGE observations of this lens in the sample's program.

    Keyed on proposal_id + target_name: the TEMPLATES program also observed each SPT lens
    under ``<name>-IFU`` / ``-MRS-OFFSET`` targets (MIRI parallels), which an exact
    target_name match excludes. Returns the astropy table, possibly empty.
    """
    from astroquery.mast import Observations
    kw = dict(proposal_id=lens_samples.proposal_id(sample), obs_collection='JWST',
              instrument_name='NIRCAM/IMAGE', target_name=lens_samples.mast_target(lens, sample))
    if filters:
        kw['filters'] = [lens_samples.canonical_filter(f) for f in filters]
    return Observations.query_criteria(**kw)


def query_position(sample, lens, field, filters=None):
    """MAST NIRCam/IMAGE observations of the sample's program whose footprint comes within
    the `field` x `field` arcsec mosaic box around the lens (a circle of its half-diagonal;
    the per-file cut in `footprint_roots` is the exact one). For survey programs whose
    target names are tiles. Returns the astropy table, possibly empty."""
    import astropy.units as u
    from astroquery.mast import Observations
    kw = dict(proposal_id=lens_samples.proposal_id(sample), obs_collection='JWST',
              instrument_name='NIRCAM/IMAGE', coordinates=lens_samples.coord(lens, sample),
              radius=field / np.sqrt(2) * u.arcsec)
    if filters:
        kw['filters'] = [lens_samples.canonical_filter(f) for f in filters]
    return Observations.query_criteria(**kw)


def _overlaps_box(s_region, coord, half):
    """True if the footprint polygon `s_region` ('POLYGON ICRS ra dec ra dec ...') overlaps
    the +-`half` arcsec box around `coord`, in the flat-sky tangent plane (exact enough for
    arcminute footprints at any dec this repo has)."""
    from matplotlib.path import Path
    v = []
    for tok in str(s_region).split():
        try:
            v.append(float(tok))
        except ValueError:
            pass
    v = np.array(v).reshape(-1, 2)
    ra0, dec0 = coord.ra.deg, coord.dec.deg
    x = ((v[:, 0] - ra0 + 180) % 360 - 180) * np.cos(np.radians(dec0)) * 3600
    y = (v[:, 1] - dec0) * 3600
    poly = np.column_stack([x, y])
    box = np.array([(-half, -half), (half, -half), (half, half), (-half, half)])
    # both paths explicitly closed: an open Path has no last->first edge, and that edge
    # alone can be the one crossing the box (a real COSMOS-Web footprint was missed so).
    # Edge crossings, plus a vertex of either inside the other for full enclosure.
    poly_p = Path(np.vstack([poly, poly[:1]]), closed=True)
    box_p = Path(np.vstack([box, box[:1]]), closed=True)
    return bool(box_p.intersects_path(poly_p, filled=False)
                or poly_p.contains_points(box).any() or box_p.contains_points(poly).any())


def footprint_roots(obs, coord, field):
    """Exposure+detector roots (``jw01727009001_02101_00001_nrca3``) of the observations in
    `obs`, split by whether their footprint overlaps the `field` box around `coord`.

    Footprints come from MAST's JWST NIRCam keyword service, which lists the cal (not the
    uncal) files of each observation; a root names the same exposure on the same detector
    at every level. Returns (overlapping, all_listed) as sets."""
    from astroquery.mast import Mast
    nums = sorted({str(int(_OBS_RE.match(str(o)).group(1))) for o in obs['obs_id']})
    params = {'columns': 'filename,s_region',
              'filters': [{'paramName': 'program', 'values': [str(int(obs['proposal_id'][0]))]},
                          {'paramName': 'observtn', 'values': nums},
                          {'paramName': 'exp_type', 'values': ['NRC_IMAGE']}]}
    t = Mast.service_request('Mast.Jwst.Filtered.Nircam', params)
    inside, listed = set(), set()
    for r in t:
        name = str(r['filename'])
        if not name.endswith('_cal.fits') or not _DET_RE.search(name):
            continue
        root = name[:-len('_cal.fits')]
        listed.add(root)
        if _overlaps_box(r['s_region'], coord, field / 2):
            inside.add(root)
    return inside, listed


def select_by_footprint(prods, inside, listed):
    """Keep the products whose root overlaps the field, plus any MAST lists no footprint
    for (kept rather than silently dropped). Returns (kept table, n without footprint)."""
    keep, unknown = [], 0
    for i, f in enumerate(prods['productFilename']):
        root = str(f).rsplit('_', 1)[0]
        if root in inside:
            keep.append(i)
        elif root not in listed:
            keep.append(i)
            unknown += 1
    return prods[keep], unknown


def product_table(obs, level):
    """All products of `obs` at MAST level `level`, de-duplicated across observations.

    Also drops the MAST level-3 ``*_i2d`` of the same visit (we build our own) and, for
    UNCAL, nothing else -- every detector's file is wanted because the sort step decides.
    """
    from astroquery.mast import Observations
    prods = Observations.get_product_list(obs)
    sub = np.array([str(x) for x in prods['productSubGroupDescription']])
    prods = prods[sub == LEVELS[level]]
    # unique by filename: SW/LW observations of one visit list the same files
    _, idx = np.unique(np.array([str(f) for f in prods['productFilename']]), return_index=True)
    return prods[np.sort(idx)]


def download(prods, pool_dir, attempts=8, wait=60):
    """Fetch `prods` into `pool_dir` (flat, no mastDownload/ nesting), one file at a time
    with retries, and verify every file's size against MAST's `size` column.

    Why not one `download_products` call: a dropped connection mid-file (seen on the 8th
    380 MB B1938 uncal, 2026-10-01: ChunkedEncodingError, IncompleteRead) raises out of the
    whole batch and leaves a truncated file at the final path, which astroquery's cache
    then treats as done. Sizes are checked before and after, bad files are deleted and
    re-fetched, and a file that will not come after `attempts` tries fails the run loudly.
    Returns the local paths."""
    import time
    from astroquery.mast import Observations
    os.makedirs(pool_dir, exist_ok=True)
    paths = []
    n = len(prods)
    # the same exposure in another lens's pool of this sample (survey neighbours)
    sample_dir = os.path.dirname(os.path.dirname(os.path.abspath(pool_dir)))
    for i, row in enumerate(prods, 1):
        name = str(row['productFilename'])
        expected = int(row['size'])
        local = os.path.join(pool_dir, name)
        if os.path.exists(local) and os.path.getsize(local) == expected:
            paths.append(local)
            continue
        twin = next((t for t in glob.glob(os.path.join(sample_dir, '*', 'pool', name))
                     if os.path.getsize(t) == expected), None)
        if twin is not None:
            if os.path.exists(local):
                os.remove(local)
            os.link(twin, local)
            paths.append(local)
            print(f'    [{i}/{n}] {name} linked from {os.path.relpath(twin, sample_dir)}', flush=True)
            continue
        for attempt in range(attempts):
            if os.path.exists(local):
                os.remove(local)                     # partial or wrong size: start over
            try:
                m = Observations.download_products(prods[[i - 1]], download_dir=pool_dir,
                                                   flat=True, cache=False)
                ok = len(m) == 1 and str(m['Status'][0]) == 'COMPLETE' \
                    and os.path.exists(local) and os.path.getsize(local) == expected
            except Exception as exc:                 # network drop, MAST 5xx, ...
                ok = False
                print(f'    {name}: {exc.__class__.__name__} ({str(exc)[:80]})', flush=True)
            if ok:
                break
            got = os.path.getsize(local) if os.path.exists(local) else 0
            print(f'    [{i}/{n}] {name}: {got}/{expected} bytes; retry {attempt + 1}/{attempts} in {wait}s', flush=True)
            time.sleep(wait)
        else:
            raise RuntimeError(f'{name} did not download after {attempts} attempts')
        paths.append(local)
        print(f'    [{i}/{n}] {name} ok', flush=True)
    return paths


def effective_filter(hdr):
    """The science filter of a NIRCam exposure. FILTER is the filter wheel; when the PUPIL
    wheel holds a filter (F405N, F410M, ...) that is the band -- see the NIRCam filter
    table. For the wide filters this repo reduces PUPIL is CLEAR and FILTER is the band."""
    pupil = str(hdr.get('PUPIL', 'CLEAR')).upper()
    filt = str(hdr['FILTER']).upper()
    return filt if pupil in ('CLEAR', 'F162M', 'F164N') and not pupil.startswith('F4') else pupil


def sort_pool(pool_dir, lens_dir, level):
    """Hard-link every <level> file in the pool into <lens_dir>/<FILTER>/ by its header.

    Hard links, not copies (no second 80 GB) and not symlinks (jwst's datamodels resolve
    paths relative to the file; a symlink's dirname is the link's, which is what we want,
    but ``os.path.realpath`` in some steps follows it back to the pool). Returns
    {FILTER: n_files}."""
    counts = {}
    suffix = f'_{level}.fits'
    for name in sorted(os.listdir(pool_dir)):
        if not name.endswith(suffix) or not _DET_RE.search(name):
            continue
        src = os.path.join(pool_dir, name)
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            hdr = fits.getheader(src, 0)
        if str(hdr.get('EXP_TYPE', '')).upper() != 'NRC_IMAGE':
            continue
        filt = effective_filter(hdr)
        dst_dir = os.path.join(lens_dir, filt)
        os.makedirs(dst_dir, exist_ok=True)
        dst = os.path.join(dst_dir, name)
        if os.path.exists(dst):
            if os.path.samefile(src, dst):
                counts[filt] = counts.get(filt, 0) + 1
                continue
            os.remove(dst)
        os.link(src, dst)
        counts[filt] = counts.get(filt, 0) + 1
    return counts


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--lens', required=True)
    p.add_argument('--sample', type=lens_samples.sample_arg, default=None, help='default: the sample the lens is in')
    p.add_argument('--level', choices=LEVELS, default='uncal')
    p.add_argument('--filters', nargs='*', default=None,
                   help='restrict the MAST query to these filters (the pool still receives '
                        'every file those visits carry; see the module docstring)')
    p.add_argument('--field', type=float, default=None,
                   help='position-query samples only: side of the mosaic box (arcsec) a detector '
                        "file must overlap to be downloaded (default: the sample's mosaic_field, else "
                        f"{DEFAULT_FIELD}, as reduce_nircam.py; must cover the --field it is reduced with)")
    p.add_argument('--dry-run', action='store_true', help='query and list, download nothing')
    a = p.parse_args()

    sample = a.sample or lens_samples.sample_of(a.lens)
    lens_samples.entry(a.lens, sample)
    if a.field is None:
        a.field = lens_samples.mosaic_field(sample) or DEFAULT_FIELD
    lens_dir = os.path.join(ws_path, 'data', 'calibrated', sample, a.lens)
    pool_dir = os.path.join(lens_dir, 'pool')
    track = os.path.join(ws_path, 'info', 'provenance', 'lens_downloads.json')

    by_position = lens_samples.mast_query(sample) == 'position'
    if by_position:
        obs = with_retries(query_position, sample, a.lens, a.field, a.filters)
    else:
        obs = with_retries(query_observations, sample, a.lens, a.filters)
    print(f'=== {sample}/{a.lens}: {len(obs)} NIRCam/IMAGE observations in GO {lens_samples.proposal_id(sample)}'
          + (f' within the {a.field:.0f}" field' if by_position else ''))
    for r in obs:
        print(f"    {r['obs_id']}  {r['target_name']}  {r['filters']}  t_exptime={float(r['t_exptime']):.0f}s  {r['dataRights']}")
    if len(obs) == 0:
        print(f'=== NO DATA: {a.lens} has no NIRCam imaging in this program')
        info_json.update(track, sample, a.lens, a.level, None)
        return 0

    prods = with_retries(product_table, obs, a.level)
    selection = {}
    if by_position:
        inside, listed = with_retries(footprint_roots, obs, lens_samples.coord(a.lens, sample), a.field)
        n_all = len(prods)
        prods, unknown = select_by_footprint(prods, inside, listed)
        print(f'    footprint cut: {len(prods)} of {n_all} {LEVELS[a.level]} files overlap the '
              f'{a.field:.0f}" field ({unknown} kept with no MAST footprint)')
        selection = {'query': 'position', 'field_arcsec': a.field, 'n_files_in_obs': int(n_all),
                     'n_files_no_footprint': int(unknown)}
    size_gb = float(np.sum(prods['size'])) / 1e9
    print(f'    {len(prods)} {LEVELS[a.level]} files, {size_gb:.1f} GB -> {pool_dir}')
    if a.dry_run:
        return 0
    download(prods, pool_dir)
    counts = sort_pool(pool_dir, lens_dir, a.level)
    print('    sorted by filter:', ', '.join(f'{k}:{v}' for k, v in sorted(counts.items())))
    info_json.update(track, sample, a.lens, a.level, {
        'obs_ids': sorted(str(o) for o in obs['obs_id']),
        'n_files': int(len(prods)), 'size_gb': round(size_gb, 2), 'per_filter': counts, **selection})
    return 0


if __name__ == '__main__':
    sys.exit(main())
