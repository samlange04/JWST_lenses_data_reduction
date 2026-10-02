#!/usr/bin/env python
"""
NIRCam reduction for one lens + filter: uncal -> rate -> cal -> North-up mosaic at the lens.

    uv run python scripts/reduce_nircam.py --lens SPT2147-50 --filt F444W [--sample spt]

The JWST analogue of the HST repo's drizzle_*.py: one product per lens+filter, idempotent,
tracking JSONs updated at the end. Three jwst pipeline stages, each cached on disk so a
re-run only redoes what is missing:

    data/calibrated/<sample>/<lens>/<FILT>/*_uncal.fits    (download_nircam.py)
      -> Detector1Pipeline ->  data/stage1/<sample>/<lens>/<FILT>/*_rate.fits
      -> Image2Pipeline    ->  data/stage2/<sample>/<lens>/<FILT>/*_cal.fits
      -> Image3Pipeline    ->  data/mosaics/<sample>/<lens>/<FILT>/<lens>_<FILT>_i2d.fits  (+ .png)

--destripe (opt-in, variant `destriped`) adds, after the standard product exists:
      -> destripe_nircam   ->  data/stage1_destriped/.../*_rate.fits   (object mask from the
                               standard mosaic; TEMPLATES recipe, Rigby+25 s6.3)
      -> Image2Pipeline    ->  data/stage2_destriped/.../*_cal.fits
      -> Image3Pipeline    ->  data/mosaics_destriped/.../<lens>_<FILT>_i2d.fits
It is not the default because, measured on SPT0418-47 F150W, it does not reduce the banding
in the lens stamp: the residual 1/f after clean_flicker_noise is coherent over only ~100 px
along a row, so no row template estimated outside the lens mask predicts it (AGENTS.md,
*striping*). It does clean blank sky, which is what a background-limited use wants.

Non-default pipeline settings, and why (AGENTS.md has the long form):

  Detector1  jump.expand_large_events=True      snowball flagging (NIR detectors)
             clean_flicker_noise.skip=False     1/f striping removed on the ramp, with
                                                sources masked (n_sigma=2) -- off by default
                                                in jwst; the dominant correlated noise term
                                                in a NIRCam frame, and it is the lens's
                                                scales (10-100 px stripes) that it corrupts
  Image2     resample.skip=True                 per-exposure i2d previews are dead weight
  Image3     tweakreg: relative only by default (--tweakreg gaia adds the GAIADR3 tie;
               skip for a star-poor field). JWST's a-priori WCS is good to ~0.1" absolute
               and dithers within a visit are consistent to a few mas, so a failed tweakreg
               is logged and NOT fatal (jwst leaves the WCS alone and continues).
             skymatch.skymethod=global+match    one sky per mosaic, matched across dithers,
                                                subtracted by resample (stcal resample
                                                subtracts meta.background.level itself)
             outlier_detection: defaults        JWST's "CR pass": there is no separate no-CR
                                                product, jump + outlier_detection always run
             resample: pixfrac 1.0, square kernel, weight_type ivm, rotation 0 (North-up),
               crval = catalogue position, crpix = centre, pixel_scale SW 0.03" / LW 0.06"
               (--scale), output_shape from --field (arcsec, default 150) so every filter
               of a lens shares one tangent point and the SW/LW grids nest 2:1
             source_catalog.skip=True

--start rate|cal skips the earlier stages and reads MAST's own products from
data/calibrated/.../<FILT>/*_rate.fits (download_nircam.py --level rate); the mosaic then
goes to data/mosaics_mastrate/ so it can never be confused with the full reduction.
--flicker-by-channel (clean_flicker_noise.fit_by_channel, one 1/f fit per amplifier) is
likewise its own variant, `bychan`: data/stage1_bychan, stage2_bychan, mosaics_bychan.
Without that the flag would be a silent no-op on any band whose rate files already exist.

Units: everything stays in MJy/sr (the jwst convention; PHOTMJSR / PIXAR_SR in the header
convert to DN/s or Jy/pixel). PyAutoLens is unit-agnostic as long as data, noise and the
PSF normalisation agree, which make_cutouts.py guarantees.

CRDS: reference files download themselves on first use into data/reference_files/
(CRDS_PATH); the context used is recorded in info/lens_products.json. Pin one with
CRDS_CONTEXT=jwst_XXXX.pmap in the environment for a byte-reproducible re-run.

macOS: mmap_fits_write.install() runs before any pipeline stage (the HST repo's write-hang
workaround; the jwst datamodels save through astropy.io.fits too). Stages run one file at
a time; no multiprocessing (ramp_fit maximum_cores stays 'none').
"""
import argparse
import glob
import json
import os
import sys
import time
import warnings

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mmap_fits_write
mmap_fits_write.install()
import lens_samples
import info_json
import cutout_paths

ws_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULT_SCALE = {'SW': 0.03, 'LW': 0.06}       # arcsec/pix, output mosaic
DEFAULT_FIELD = 150.0                           # arcsec, output mosaic side
MIN_EXPTIME = 10.0                              # frames shorter than this are dropped


def setup_crds():
    ref_path = os.path.join(ws_path, 'data', 'reference_files')
    os.makedirs(ref_path, exist_ok=True)
    os.environ.setdefault('CRDS_PATH', ref_path)
    os.environ.setdefault('CRDS_SERVER_URL', 'https://jwst-crds.stsci.edu')
    # STPSF data (make_psf.py) lives beside it; harmless to set here for every script.
    os.environ.setdefault('STPSF_PATH', os.path.join(ref_path, 'stpsf-data'))


def crds_context():
    import crds
    try:
        return crds.get_default_context('jwst')
    except Exception as e:          # offline, or server unreachable: not fatal
        return f'unknown ({e.__class__.__name__})'


def sync_references(files, attempts=30, wait=300):
    """Download (and verify) every CRDS reference the given exposures need, BEFORE a
    pipeline stage touches them, retrying through server outages.

    Why a pre-sync: stpipe fetches references lazily inside the step and a single 502 from
    jwst-crds.stsci.edu (seen 2026-10-01, with a 4.4 GB dark left truncated on disk) kills a
    multi-hour run at a random point, and a truncated file in the cache is reused as-is.
    `crds sync --check-files --repair-files` verifies sizes against the server and re-fetches
    bad files, so a retry loop around it both waits out the outage and heals the cache.
    """
    import subprocess
    import crds
    from astropy.io import fits
    names = set()
    for f in files:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            hdr = dict(fits.getheader(f, 0))
        for attempt in range(attempts):
            try:
                refs = crds.getreferences(hdr, observatory='jwst', ignore_cache=False)
                break
            except Exception as exc:
                print(f'  CRDS bestrefs failed ({exc.__class__.__name__}: {str(exc)[:120]}); '
                      f'retry {attempt + 1}/{attempts} in {wait}s', flush=True)
                time.sleep(wait)
        else:
            raise RuntimeError('CRDS bestrefs kept failing; is jwst-crds.stsci.edu up?')
        names.update(os.path.basename(v) for v in refs.values() if isinstance(v, str) and v.endswith(('.fits', '.asdf', '.json')))
    names = sorted(names)
    print(f'  CRDS: {len(names)} reference files for {len(files)} exposures', flush=True)
    for attempt in range(attempts):
        proc = subprocess.run(['crds', 'sync', '--files', *names, '--check-files', '--repair-files'],
                              capture_output=True, text=True)
        bad = [l for l in (proc.stdout + proc.stderr).splitlines() if 'ERROR' in l]
        if proc.returncode == 0 and not bad:
            return names
        print(f'  CRDS sync: {len(bad)} error(s) (e.g. {bad[0][:140] if bad else proc.returncode}); '
              f'retry {attempt + 1}/{attempts} in {wait}s', flush=True)
        time.sleep(wait)
    raise RuntimeError('CRDS sync kept failing; is jwst-crds.stsci.edu up?')


def _stage_dir(kind, sample, lens, filt, variant=''):
    """data/<stage1|stage2|mosaics>[_<variant>]/<sample>/<lens>/<FILT> -- the variant tags
    the stage ROOT, so a variant reduction never shares a cache with the standard one."""
    tag = cutout_paths.variant_tag(variant)
    root = {'stage1': f'stage1{tag}', 'stage2': f'stage2{tag}',
            'mosaics': os.path.basename(cutout_paths.mosaics_root(ws_path, variant))}[kind]
    return os.path.join(ws_path, 'data', root, sample, lens, filt)


def _rootname(path):
    """'jw01355024001_05101_00001_nrcb1' from any stage's filename."""
    base = os.path.basename(path)
    return base.rsplit('_', 1)[0]


def _exptime(path):
    from astropy.io import fits
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        h = fits.getheader(path, 0)
    return float(h.get('EFFEXPTM', h.get('EXPTIME', 0.0)))


def run_detector1(uncal_files, out_dir, flicker_by_channel):
    """Detector1 on each uncal that has no rate yet. Returns the rate paths."""
    from jwst.pipeline import Detector1Pipeline
    os.makedirs(out_dir, exist_ok=True)
    rates = []
    for i, f in enumerate(uncal_files, 1):
        rate = os.path.join(out_dir, _rootname(f) + '_rate.fits')
        if os.path.exists(rate):
            rates.append(rate)
            continue
        t0 = time.time()
        print(f'  [stage1 {i}/{len(uncal_files)}] {os.path.basename(f)}', flush=True)
        Detector1Pipeline.call(
            f, output_dir=out_dir, save_results=True,
            steps={
                'jump': {'expand_large_events': True},
                'clean_flicker_noise': {'skip': False, 'fit_by_channel': flicker_by_channel},
                # rateints are only wanted for time-series; one integration here anyway
            })
        if not os.path.exists(rate):
            raise RuntimeError(f'Detector1 produced no {rate}')
        print(f'      {time.time() - t0:.0f}s', flush=True)
        rates.append(rate)
    return rates


def run_image2(rate_files, out_dir):
    from jwst.pipeline import Image2Pipeline
    os.makedirs(out_dir, exist_ok=True)
    cals = []
    for i, f in enumerate(rate_files, 1):
        cal = os.path.join(out_dir, _rootname(f) + '_cal.fits')
        if os.path.exists(cal):
            cals.append(cal)
            continue
        t0 = time.time()
        print(f'  [stage2 {i}/{len(rate_files)}] {os.path.basename(f)}', flush=True)
        Image2Pipeline.call(f, output_dir=out_dir, save_results=True,
                            steps={'resample': {'skip': True}})
        if not os.path.exists(cal):
            raise RuntimeError(f'Image2 produced no {cal}')
        print(f'      {time.time() - t0:.0f}s', flush=True)
        cals.append(cal)
    return cals


def write_asn(cal_files, product_name, out_dir):
    from jwst.associations import asn_from_list
    from jwst.associations.lib.rules_level3_base import DMS_Level3_Base
    asn = asn_from_list.asn_from_list([os.path.abspath(f) for f in cal_files],
                                      rule=DMS_Level3_Base, product_name=product_name)
    path = os.path.join(out_dir, f'{product_name}_asn.json')
    _, serialized = asn.dump(format='json')
    with open(path, 'w') as fh:
        fh.write(serialized)
    return path


def run_image3(cal_files, out_dir, product_name, coord, scale, field, tweakreg_mode):
    from jwst.pipeline import Image3Pipeline
    os.makedirs(out_dir, exist_ok=True)
    asn_path = write_asn(cal_files, product_name, out_dir)
    n = int(round(field / scale))
    n += n % 2                         # even side: crpix at a pixel corner... keep it simple
    tweak = {'skip': True} if tweakreg_mode == 'skip' else {}
    if tweakreg_mode == 'gaia':
        tweak = {'abs_refcat': 'GAIADR3'}
    steps = {
        'tweakreg': tweak,
        'skymatch': {'skymethod': 'global+match', 'subtract': False},
        'outlier_detection': {},
        'resample': {
            'pixfrac': 1.0, 'kernel': 'square', 'weight_type': 'ivm', 'fillval': 'NAN',
            'rotation': 0.0, 'pixel_scale': float(scale),
            'crval': [float(coord.ra.deg), float(coord.dec.deg)],
            'crpix': [(n - 1) / 2.0, (n - 1) / 2.0],
            'output_shape': [n, n],
            'in_memory': False,
        },
        'source_catalog': {'skip': True},
    }
    t0 = time.time()
    print(f'  [stage3] {len(cal_files)} cal -> {product_name}_i2d.fits  '
          f'({n}x{n} px at {scale}"/px, tweakreg={tweakreg_mode})', flush=True)
    Image3Pipeline.call(asn_path, output_dir=out_dir, save_results=True, in_memory=False,
                        steps=steps)
    i2d = os.path.join(out_dir, f'{product_name}_i2d.fits')
    if not os.path.exists(i2d):
        raise RuntimeError(f'Image3 produced no {i2d}')
    print(f'      {time.time() - t0:.0f}s', flush=True)
    return i2d


def plot_i2d(i2d, png):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from astropy.io import fits
    from astropy.visualization import AsinhStretch, ImageNormalize, PercentileInterval
    with fits.open(i2d) as h:
        sci = h['SCI'].data
        wht = h['WHT'].data
    fig, ax = plt.subplots(1, 2, figsize=(14, 7))
    good = np.isfinite(sci)
    norm = ImageNormalize(sci[good], interval=PercentileInterval(99.5), stretch=AsinhStretch(0.05))
    ax[0].imshow(sci, origin='lower', cmap='inferno', norm=norm)
    ax[0].set_title(os.path.basename(i2d))
    ax[1].imshow(wht, origin='lower', cmap='viridis')
    ax[1].set_title('WHT')
    for a in ax:
        a.set_xticks([]); a.set_yticks([])
    fig.tight_layout()
    fig.savefig(png, dpi=110)
    plt.close(fig)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--lens', required=True)
    p.add_argument('--filt', required=True, help='NIRCam filter, e.g. F444W')
    p.add_argument('--sample', default=None)
    p.add_argument('--start', choices=['uncal', 'rate', 'cal'], default='uncal',
                   help='uncal: full reduction (default). rate/cal: start from MAST products '
                        'in data/calibrated (download_nircam.py --level rate|cal); the '
                        'mosaic is then tagged mastrate/mastcal (cutout_paths)')
    p.add_argument('--scale', type=float, default=None,
                   help=f'output pixel scale, arcsec (default SW {DEFAULT_SCALE["SW"]}, '
                        f'LW {DEFAULT_SCALE["LW"]})')
    p.add_argument('--field', type=float, default=DEFAULT_FIELD,
                   help=f'output mosaic side, arcsec (default {DEFAULT_FIELD})')
    p.add_argument('--tweakreg', choices=['relative', 'gaia', 'skip'], default='relative')
    p.add_argument('--flicker-by-channel', action='store_true', default=False,
                   help='clean_flicker_noise.fit_by_channel=True (per-amplifier 1/f fit)')
    p.add_argument('--destripe', action='store_true', default=False,
                   help='variant `destriped`: rate-level TEMPLATES 1/f destripe, object mask '
                        'from the standard mosaic (which must exist or is built first)')
    p.add_argument('--force', action='store_true', help='rebuild the mosaic (stages 1-2 are kept)')
    a = p.parse_args()

    setup_crds()
    sample = a.sample or lens_samples.sample_of(a.lens)
    lens_samples.entry(a.lens, sample)
    filt = lens_samples.canonical_filter(a.filt)
    ch = lens_samples.channel(filt)
    scale = a.scale if a.scale is not None else DEFAULT_SCALE[ch]
    coord = lens_samples.coord(a.lens, sample)
    variant = {'uncal': '', 'rate': 'mastrate', 'cal': 'mastcal'}[a.start]
    if a.flicker_by_channel:
        if a.start != 'uncal':
            p.error('--flicker-by-channel only applies to --start uncal (Detector1)')
        variant = 'bychan'                      # own stage1/stage2/mosaic trees, never a no-op
    if a.destripe:
        if a.start != 'uncal' or a.flicker_by_channel:
            p.error('--destripe applies to the standard reduction only (--start uncal, no --flicker-by-channel)')
        variant = 'destriped'
    key = filt + cutout_paths.variant_tag(variant)   # tracking-JSON key: <FILT>[_<variant>]

    cal_dir = os.path.join(ws_path, 'data', 'calibrated', sample, a.lens, filt)
    inputs = sorted(glob.glob(os.path.join(cal_dir, f'*_{a.start}.fits')))
    print(f'=== {sample}/{a.lens} {filt} ({ch}): {len(inputs)} {a.start} files in {cal_dir}')
    products_json = os.path.join(ws_path, 'info', 'lens_products.json')
    if not inputs:
        print(f'=== NO DATA: run download_nircam.py --lens {a.lens} first, or MAST has no {filt}')
        info_json.update(products_json, sample, a.lens, key, None)
        return 0

    kept = [f for f in inputs if _exptime(f) > MIN_EXPTIME]
    if len(kept) < len(inputs):
        print(f'    dropped {len(inputs) - len(kept)} frames with EFFEXPTM <= {MIN_EXPTIME}s')

    mosaic_dir = _stage_dir('mosaics', sample, a.lens, filt, variant)
    product_name = f'{a.lens.replace("+", "p")}_{filt}'.lower()
    i2d = os.path.join(mosaic_dir, f'{product_name}_i2d.fits')
    if os.path.exists(i2d) and not a.force:
        print(f'=== exists, skipping: {i2d}  (--force to rebuild)')
        return 0

    sync_references(kept)
    base_variant = '' if a.destripe else variant      # the destripe starts from the standard stages
    if a.start == 'uncal':
        rates = run_detector1(kept, _stage_dir('stage1', sample, a.lens, filt, base_variant), a.flicker_by_channel)
        cals = run_image2(rates, _stage_dir('stage2', sample, a.lens, filt, base_variant))
    elif a.start == 'rate':
        rates = kept
        cals = run_image2(kept, _stage_dir('stage2', sample, a.lens, filt, variant))
    else:
        cals = kept

    destripe_stats = None
    if a.destripe:
        import destripe_nircam
        # the standard mosaic is the object-mask source; build it if it is not there yet
        std_dir = _stage_dir('mosaics', sample, a.lens, filt, '')
        i2d0 = os.path.join(std_dir, f'{product_name}_i2d.fits')
        if not os.path.exists(i2d0):
            i2d0 = run_image3(cals, std_dir, product_name, coord, scale, a.field, a.tweakreg)
            plot_i2d(i2d0, i2d0.replace('_i2d.fits', '_i2d.png'))
        rates, destripe_stats = destripe_nircam.destripe_frames(
            rates, cals, i2d0, _stage_dir('stage1', sample, a.lens, filt, variant))
        cals = run_image2(rates, _stage_dir('stage2', sample, a.lens, filt, variant))

    i2d = run_image3(cals, mosaic_dir, product_name, coord, scale, a.field, a.tweakreg)
    if a.destripe:
        from astropy.io import fits as _fits
        with _fits.open(i2d, mode='update') as h:
            h[0].header['S_DESTRP'] = ('COMPLETE', 'rate-level 1/f destripe (destripe_nircam.py)')
    plot_i2d(i2d, i2d.replace('_i2d.fits', '_i2d.png'))

    from astropy.io import fits
    hdr = fits.getheader(i2d, 0)
    sci_hdr = fits.getheader(i2d, 'SCI')
    rec = {
        'rootnames': [_rootname(f) for f in cals], 'n_frames': len(cals),
        'start': a.start, 'variant': variant, 'scale': scale, 'field_arcsec': a.field,
        'tweakreg': a.tweakreg, 'flicker_by_channel': a.flicker_by_channel,
        'destripe': bool(a.destripe),
        'destripe_mask': None if destripe_stats is None else destripe_stats['mask'],
        'jwst_version': hdr.get('CAL_VER'), 'crds_context': hdr.get('CRDS_CTX', crds_context()),
        'pixfrac': sci_hdr.get('PIXFRAC'), 'bunit': sci_hdr.get('BUNIT'),
        'photmjsr': sci_hdr.get('PHOTMJSR'), 'pixar_sr': sci_hdr.get('PIXAR_SR'),
        'i2d': os.path.relpath(i2d, ws_path),
    }
    info_json.update(products_json, sample, a.lens, key, rec)
    if not variant:                             # exptime / instrument are band properties
        # exposure time AT THE LENS: one detector per dither, so sum EFFEXPTM once per
        # exposure (rootname minus the detector suffix), not over every detector's frame
        per_exposure = {_rootname(f).rsplit('_', 1)[0]: _exptime(f) for f in cals}
        info_json.update(os.path.join(ws_path, 'info', 'lens_exptime.json'), sample, a.lens, key,
                         round(float(sum(per_exposure.values())), 1))
        info_json.update(os.path.join(ws_path, 'info', 'lens_instrument.json'), sample, a.lens, key,
                         f'NIRCAM/{ch}')
    print(f'=== done: {i2d}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
