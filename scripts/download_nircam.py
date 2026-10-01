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

Idempotent: files already in the pool are skipped by astroquery (``cache=True``) and the
sort re-links everything, so re-running after a partial download is safe. Tracking:
``info/lens_downloads.json`` records, per lens, the level, the obs IDs, and the per-filter
file counts; ``null`` for a filter means MAST had nothing.
"""
import argparse
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
    for i, row in enumerate(prods, 1):
        name = str(row['productFilename'])
        expected = int(row['size'])
        local = os.path.join(pool_dir, name)
        if os.path.exists(local) and os.path.getsize(local) == expected:
            paths.append(local)
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
    p.add_argument('--sample', default=None, help='default: the sample the lens is in')
    p.add_argument('--level', choices=LEVELS, default='uncal')
    p.add_argument('--filters', nargs='*', default=None,
                   help='restrict the MAST query to these filters (the pool still receives '
                        'every file those visits carry; see the module docstring)')
    p.add_argument('--dry-run', action='store_true', help='query and list, download nothing')
    a = p.parse_args()

    sample = a.sample or lens_samples.sample_of(a.lens)
    lens_samples.entry(a.lens, sample)
    lens_dir = os.path.join(ws_path, 'data', 'calibrated', sample, a.lens)
    pool_dir = os.path.join(lens_dir, 'pool')
    track = os.path.join(ws_path, 'info', 'lens_downloads.json')

    obs = query_observations(sample, a.lens, a.filters)
    print(f'=== {sample}/{a.lens}: {len(obs)} NIRCam/IMAGE observations in GO {lens_samples.proposal_id(sample)}')
    for r in obs:
        print(f"    {r['obs_id']}  {r['filters']}  t_exptime={float(r['t_exptime']):.0f}s  {r['dataRights']}")
    if len(obs) == 0:
        print(f'=== NO DATA: {a.lens} has no NIRCam imaging in this program')
        info_json.update(track, sample, a.lens, a.level, None)
        return 0

    prods = product_table(obs, a.level)
    size_gb = float(np.sum(prods['size'])) / 1e9
    print(f'    {len(prods)} {LEVELS[a.level]} files, {size_gb:.1f} GB -> {pool_dir}')
    if a.dry_run:
        return 0
    download(prods, pool_dir)
    counts = sort_pool(pool_dir, lens_dir, a.level)
    print('    sorted by filter:', ', '.join(f'{k}:{v}' for k, v in sorted(counts.items())))
    info_json.update(track, sample, a.lens, a.level, {
        'obs_ids': sorted(str(o) for o in obs['obs_id']),
        'n_files': int(len(prods)), 'size_gb': round(size_gb, 2), 'per_filter': counts})
    return 0


if __name__ == '__main__':
    sys.exit(main())
