#!/usr/bin/env python
"""
NIRCam reduction for one lens + filter: uncal -> rate -> cal -> North-up mosaic at the lens.

    uv run python scripts/reduce_nircam.py --lens SPT2147-50 --filt F444W [--sample templates]

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
               A sample may set tweakreg_lens_first and tweakreg_sw_from_lw (COWLS): the
               lens frames are aligned first, and the SW frames take the tweakreg offset of
               their own exposure's LW frames (fitted on LW only); see lens_samples.
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
PSF normalisation agree, which make_stamps.py guarantees.

CRDS: reference files download themselves on first use into data/reference_files/
(CRDS_PATH); the context used is recorded in info/provenance/lens_products.json. Pin one with
CRDS_CONTEXT=jwst_XXXX.pmap in the environment for a byte-reproducible re-run.

macOS: mmap_fits_write.install() runs before any pipeline stage (the HST repo's write-hang
workaround; the jwst datamodels save through astropy.io.fits too). Stages run one file at
a time; no multiprocessing (ramp_fit maximum_cores stays 'none').
"""
import argparse
import glob
import logging
import os
import shutil
import sys
import time
import warnings

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mmap_fits_write
mmap_fits_write.install()
import lens_samples
import info_json
import stamp_paths

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
    tag = stamp_paths.variant_tag(variant)
    root = {'stage1': f'stage1{tag}', 'stage2': f'stage2{tag}',
            'mosaics': os.path.basename(stamp_paths.mosaics_root(ws_path, variant))}[kind]
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


def _link_from_neighbour(path):
    """Hard-link `path` (a rate or cal in data/<stage>/<sample>/<lens>/<FILT>/) from another
    lens of the same sample, stage tree and filter that already made it. Survey neighbours
    (COSMOS-Web lenses a few arcmin apart) share exposures, and neither Detector1 nor Image2
    depends on the lens. True if linked. Never in a destriped tree: those rates carry an
    object mask taken from the lens's own mosaic."""
    filt_dir = os.path.dirname(path)
    sample_dir = os.path.dirname(os.path.dirname(filt_dir))
    if os.path.basename(os.path.dirname(sample_dir)).endswith('_destriped'):
        return False
    pattern = os.path.join(sample_dir, '*', os.path.basename(filt_dir), os.path.basename(path))
    for twin in glob.glob(pattern):
        if not os.path.samefile(os.path.dirname(twin), filt_dir):
            os.link(twin, path)
            print(f'      {os.path.basename(path)} linked from {os.path.relpath(twin, sample_dir)}', flush=True)
            return True
    return False


def run_detector1(uncal_files, out_dir, flicker_by_channel, cal_dir=None):
    """Detector1 on each uncal that has no rate yet. Returns the rate paths.

    With `cal_dir` (a pruned sample, whose rates are deleted once calibrated), an uncal
    whose cal is already there, or at a neighbour's, is not re-run: its rate path is
    returned although the file is gone, and run_image2 skips it on the cal."""
    from jwst.pipeline import Detector1Pipeline
    os.makedirs(out_dir, exist_ok=True)
    rates = []
    for i, f in enumerate(uncal_files, 1):
        rate = os.path.join(out_dir, _rootname(f) + '_rate.fits')
        if cal_dir is not None:
            cal = os.path.join(cal_dir, _rootname(f) + '_cal.fits')
            os.makedirs(cal_dir, exist_ok=True)
            if os.path.exists(cal) or _link_from_neighbour(cal):
                rates.append(rate)
                continue
        if os.path.exists(rate) or _link_from_neighbour(rate):
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


def prune_rates(rate_files, cal_dir):
    """Delete each rate (and rateints) whose cal exists: a pruned sample keeps uncal + cal."""
    for r in rate_files:
        if os.path.exists(os.path.join(cal_dir, _rootname(r) + '_cal.fits')):
            for f in (r, r.replace('_rate.fits', '_rateints.fits')):
                if os.path.exists(f):
                    os.remove(f)


def covers(cal_file, coord):
    """True if the cal file's footprint (SCI S_REGION) covers `coord`; a frame with no
    S_REGION is assumed to."""
    from astropy.io import fits
    import download_nircam
    s_region = fits.getheader(cal_file, 'SCI').get('S_REGION')
    return not s_region or download_nircam._overlaps_box(s_region, coord, 0.01)


def lens_first_order(cal_files, coord):
    """The cal files with those covering `coord` first (each part in name order): the order
    tweakreg aligns them in when the sample sets tweakreg_lens_first."""
    return sorted(cal_files, key=lambda f: (not covers(f, coord), os.path.basename(f)))


def exptime_at(cal_files, coord):
    """Exposure time AT THE LENS: EFFEXPTM summed once per exposure (rootname minus the
    detector suffix, so a lens on a detector edge is not counted twice) over the cal files
    whose footprint (SCI S_REGION) covers `coord`. A survey mosaic also holds neighbouring
    tiles' exposures that never see the lens; a frame with no S_REGION is counted."""
    per_exposure = {}
    for f in cal_files:
        if not covers(f, coord):
            continue
        per_exposure[_rootname(f).rsplit('_', 1)[0]] = _exptime(f)
    return float(sum(per_exposure.values()))


def run_image2(rate_files, out_dir):
    from jwst.pipeline import Image2Pipeline
    os.makedirs(out_dir, exist_ok=True)
    cals = []
    for i, f in enumerate(rate_files, 1):
        cal = os.path.join(out_dir, _rootname(f) + '_cal.fits')
        if os.path.exists(cal) or _link_from_neighbour(cal):
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


def mosaic_side(field, scale):
    """Output mosaic side in pixels: even, so crpix (the catalogue position) is a pixel corner."""
    n = int(round(field / scale))
    return n + n % 2


def image3_steps(coord, scale, field, tweakreg_mode, lens_first=False):
    """The Image3 step overrides of the science mosaic. make_psf_inject.py re-runs tweakreg and
    resample from this same dict, so an injected star is resampled exactly as the data were."""
    n = mosaic_side(field, scale)
    tweak = {'skip': True} if tweakreg_mode == 'skip' else {}
    if tweakreg_mode == 'gaia':
        tweak = {'abs_refcat': 'GAIADR3'}       # jwst sets expand_refcat itself for this
    elif tweakreg_mode == 'relative' and lens_first:
        # the caller puts the lens-covering frames first (lens_first_order)
        tweak = {'expand_refcat': True, 'enforce_user_order': True}
    return {
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


FRAME_CENTRE = 1023.5     # detector pixel at which a frame's WCS offset is measured and applied


def tweak_offsets(cal_files, out_dir):
    """{rootname: [dRA cos(dec), dDec] in mas}: each frame's tweakreg correction at its centre,
    from the crf files Image3 wrote beside the mosaic (crf WCS minus cal WCS). Frames without a
    crf are left out. tweakreg's NIRCam fit is a shift, i.e. one sky offset per exposure."""
    from stdatamodels.jwst import datamodels
    out = {}
    for f in cal_files:
        r = _rootname(f)
        crf = sorted(glob.glob(os.path.join(out_dir, f'{r}_*crf.fits')))
        if not crf:
            continue
        with datamodels.open(f) as a, datamodels.open(crf[0]) as b:
            ra0, dec0 = a.meta.wcs(FRAME_CENTRE, FRAME_CENTRE)
            ra1, dec1 = b.meta.wcs(FRAME_CENTRE, FRAME_CENTRE)
        out[r] = [round(float((ra1 - ra0) * np.cos(np.radians(dec0)) * 3.6e6), 2),
                  round(float((dec1 - dec0) * 3.6e6), 2)]
    return out


def shift_wcs(wcs, offset_mas, x=FRAME_CENTRE, y=FRAME_CENTRE):
    """`wcs` (a cal frame's gwcs) moved so pixel (x, y) lands `offset_mas` = [dRA cos(dec), dDec]
    from where it was. jwst's adjust_wcs takes telescope-frame rotations, not a sky offset, so
    the rotations are solved for numerically (two Newton steps; the result is good to < 0.01 mas)."""
    from jwst.tweakreg.utils import adjust_wcs
    ra0, dec0 = wcs(x, y)
    target = np.asarray(offset_mas, float)
    cosd = np.cos(np.radians(dec0))

    def off(p):
        ra, dec = adjust_wcs(wcs, delta_ra=p[0], delta_dec=p[1])(x, y)
        return np.array([(ra - ra0) * cosd * 3.6e6, (dec - dec0) * 3.6e6])

    h = 1e-5                                   # deg
    jac = np.column_stack([off([h, 0.0]) / h, off([0.0, h]) / h])
    p = np.linalg.solve(jac, target)
    p = p + np.linalg.solve(jac, target - off(p))
    return adjust_wcs(wcs, delta_ra=p[0], delta_dec=p[1])


def lw_exposure_offsets(sample, lens):
    """{exposure: [dRA cos(dec), dDec] mas}: the tweakreg offsets of the lens's LW bands
    (`tweak_offsets_mas` in lens_products.json), keyed by exposure (rootname minus detector)."""
    recs = info_json.load(os.path.join(ws_path, 'info', 'provenance', 'lens_products.json')).get(sample, {}).get(lens, {})
    out = {}
    for key, rec in recs.items():
        if rec and lens_samples.channel(key.split('_')[0]) == 'LW':
            for r, o in (rec.get('tweak_offsets_mas') or {}).items():
                out.setdefault(r.rsplit('_', 1)[0], o)
    return out


def apply_offsets(cal_files, offsets, work_dir):
    """Copies of `cal_files` in `work_dir`, each frame's WCS moved by its exposure's offset in
    `offsets` (lw_exposure_offsets); a frame whose exposure has none is copied unchanged (as LW
    leaves an exposure tweakreg could not align). Returns (paths, {rootname: offset or None})."""
    from stdatamodels.jwst import datamodels
    os.makedirs(work_dir, exist_ok=True)
    paths, applied = [], {}
    for f in cal_files:
        r = _rootname(f)
        o = offsets.get(r.rsplit('_', 1)[0])
        dst = os.path.join(work_dir, os.path.basename(f))
        if o is None:
            shutil.copy(f, dst)
        else:
            with datamodels.open(f) as m:
                m.meta.wcs = shift_wcs(m.meta.wcs, o)
                m.save(dst)
        paths.append(dst)
        applied[r] = o
    return paths, applied


class _TweakLog(logging.Handler):
    """Collects tweakreg's per-group outcome lines, which stpipe does not print here: a
    tweakreg that aligns nothing still marks every frame COMPLETE."""
    KEYS = ('as reference image', 'Found initial', 'Not enough matches', 'Computed ', 'XSH:', 'FIT RMSE')

    def __init__(self):
        super().__init__(logging.INFO)
        self.lines = []

    def emit(self, record):
        msg = record.getMessage()
        if any(k in msg for k in self.KEYS):
            self.lines.append(msg.strip())


def run_image3(cal_files, out_dir, product_name, coord, scale, field, tweakreg_mode, lens_first=False):
    from jwst.pipeline import Image3Pipeline
    os.makedirs(out_dir, exist_ok=True)
    asn_path = write_asn(cal_files, product_name, out_dir)
    n = mosaic_side(field, scale)
    steps = image3_steps(coord, scale, field, tweakreg_mode, lens_first)
    t0 = time.time()
    print(f'  [stage3] {len(cal_files)} cal -> {product_name}_i2d.fits  '
          f'({n}x{n} px at {scale}"/px, tweakreg={tweakreg_mode}'
          f'{", lens frames first" if lens_first else ""})', flush=True)
    tlog = _TweakLog()
    loggers = [logging.getLogger(name) for name in ('jwst.tweakreg', 'tweakwcs')]
    saved = [lg.level for lg in loggers]
    for lg in loggers:
        lg.addHandler(tlog)
        lg.setLevel(logging.INFO)
    try:
        Image3Pipeline.call(asn_path, output_dir=out_dir, save_results=True, in_memory=False,
                            steps=steps)
    finally:
        for lg, lvl in zip(loggers, saved):
            lg.removeHandler(tlog)
            lg.setLevel(lvl)
    for line in tlog.lines:
        print(f'      tweakreg: {line}', flush=True)
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
    p.add_argument('--sample', type=lens_samples.sample_arg, default=None)
    p.add_argument('--start', choices=['uncal', 'rate', 'cal'], default='uncal',
                   help='uncal: full reduction (default). rate/cal: start from MAST products '
                        'in data/calibrated (download_nircam.py --level rate|cal); the '
                        'mosaic is then tagged mastrate/mastcal (stamp_paths)')
    p.add_argument('--scale', type=float, default=None,
                   help=f'output pixel scale, arcsec (default SW {DEFAULT_SCALE["SW"]}, '
                        f'LW {DEFAULT_SCALE["LW"]})')
    p.add_argument('--field', type=float, default=None,
                   help=f"output mosaic side, arcsec (default: the sample's mosaic_field, else {DEFAULT_FIELD})")
    p.add_argument('--tweakreg', choices=['relative', 'gaia', 'skip'], default='relative')
    p.add_argument('--flicker-by-channel', action='store_true', default=False,
                   help='clean_flicker_noise.fit_by_channel=True (per-amplifier 1/f fit)')
    p.add_argument('--destripe', action='store_true', default=False,
                   help='variant `destriped`: rate-level TEMPLATES 1/f destripe, object mask '
                        'from the standard mosaic (which must exist or is built first)')
    p.add_argument('--force', action='store_true', help='rebuild the mosaic (stages 1-2 are kept)')
    a = p.parse_args()

    setup_crds()
    sample = lens_samples.resolve_sample(p, a)
    lens_samples.entry(a.lens, sample)
    filt = lens_samples.canonical_filter(a.filt)
    ch = lens_samples.channel(filt)
    scale = a.scale if a.scale is not None else DEFAULT_SCALE[ch]
    coord = lens_samples.coord(a.lens, sample)
    if a.field is None:
        a.field = lens_samples.mosaic_field(sample) or DEFAULT_FIELD
    prune = lens_samples.prune_intermediates(sample)
    lens_first = lens_samples.tweakreg_lens_first(sample)
    sw_from_lw = ch == 'SW' and a.tweakreg == 'relative' and lens_samples.tweakreg_sw_from_lw(sample)
    variant = {'uncal': '', 'rate': 'mastrate', 'cal': 'mastcal'}[a.start]
    if a.flicker_by_channel:
        if a.start != 'uncal':
            p.error('--flicker-by-channel only applies to --start uncal (Detector1)')
        variant = 'bychan'                      # own stage1/stage2/mosaic trees, never a no-op
    if a.destripe:
        if a.start != 'uncal' or a.flicker_by_channel:
            p.error('--destripe applies to the standard reduction only (--start uncal, no --flicker-by-channel)')
        variant = 'destriped'
    key = filt + stamp_paths.variant_tag(variant)   # tracking-JSON key: <FILT>[_<variant>]

    cal_dir = os.path.join(ws_path, 'data', 'calibrated', sample, a.lens, filt)
    inputs = sorted(glob.glob(os.path.join(cal_dir, f'*_{a.start}.fits')))
    print(f'=== {sample}/{a.lens} {filt} ({ch}): {len(inputs)} {a.start} files in {cal_dir}')
    products_json = os.path.join(ws_path, 'info', 'provenance', 'lens_products.json')
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
        stage2_dir = _stage_dir('stage2', sample, a.lens, filt, base_variant)
        # a destripe needs the standard rates, so a pruned sample re-makes them for it
        rates = run_detector1(kept, _stage_dir('stage1', sample, a.lens, filt, base_variant), a.flicker_by_channel,
                              cal_dir=stage2_dir if prune and not a.destripe else None)
        cals = run_image2(rates, stage2_dir)
        if prune and not a.destripe:
            prune_rates(rates, stage2_dir)
    elif a.start == 'rate':
        rates = kept
        cals = run_image2(kept, _stage_dir('stage2', sample, a.lens, filt, variant))
    else:
        cals = kept
    lens_at = lens_samples.deflector_coord(a.lens, sample) or coord
    if lens_first:
        cals = lens_first_order(cals, lens_at)

    destripe_stats = None
    if a.destripe:
        import destripe_nircam
        # the standard mosaic is the object-mask source; build it if it is not there yet
        std_dir = _stage_dir('mosaics', sample, a.lens, filt, '')
        i2d0 = os.path.join(std_dir, f'{product_name}_i2d.fits')
        if not os.path.exists(i2d0):
            i2d0 = run_image3(cals, std_dir, product_name, coord, scale, a.field, a.tweakreg, lens_first)
            plot_i2d(i2d0, i2d0.replace('_i2d.fits', '_i2d.png'))
        rates, destripe_stats = destripe_nircam.destripe_frames(
            rates, cals, i2d0, _stage_dir('stage1', sample, a.lens, filt, variant))
        cals = run_image2(rates, _stage_dir('stage2', sample, a.lens, filt, variant))
        if lens_first:
            cals = lens_first_order(cals, lens_at)

    tweak_mode, offsets = a.tweakreg, None
    if sw_from_lw:
        lw = lw_exposure_offsets(sample, a.lens)
        if not lw:
            raise SystemExit(f'ERROR: {sample} takes SW tweakreg offsets from LW (tweakreg_sw_from_lw), but '
                             f'{a.lens} has no LW band with tweak_offsets_mas: reduce its LW bands first')
        work_dir = os.path.join(mosaic_dir, '_lw_offsets')
        image3_in, offsets = apply_offsets(cals, lw, work_dir)
        tweak_mode = 'skip'
        n_none = sum(o is None for o in offsets.values())
        print(f'  SW WCS from LW tweakreg: {len(offsets) - n_none}/{len(offsets)} frames moved '
              f'({n_none} exposures with no LW offset kept a-priori)', flush=True)
        i2d = run_image3(image3_in, mosaic_dir, product_name, coord, scale, a.field, tweak_mode)
        shutil.rmtree(work_dir)
    else:
        i2d = run_image3(cals, mosaic_dir, product_name, coord, scale, a.field, a.tweakreg, lens_first)
        if a.tweakreg != 'skip':
            offsets = tweak_offsets(cals, mosaic_dir) or None
    if prune:
        for f in glob.glob(os.path.join(mosaic_dir, '*_crf.fits')):
            os.remove(f)
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
        'tweakreg': 'from_lw' if sw_from_lw else a.tweakreg, 'tweakreg_lens_first': lens_first and not sw_from_lw,
        'tweak_offsets_mas': offsets, 'flicker_by_channel': a.flicker_by_channel,
        'destripe': bool(a.destripe),
        'destripe_mask': None if destripe_stats is None else destripe_stats['mask'],
        'jwst_version': hdr.get('CAL_VER'), 'crds_context': hdr.get('CRDS_CTX', crds_context()),
        'pixfrac': sci_hdr.get('PIXFRAC'), 'bunit': sci_hdr.get('BUNIT'),
        'photmjsr': sci_hdr.get('PHOTMJSR'), 'pixar_sr': sci_hdr.get('PIXAR_SR'),
        'i2d': os.path.relpath(i2d, ws_path),
    }
    info_json.update(products_json, sample, a.lens, key, rec)
    if not variant:                             # exptime / instrument are band properties
        info_json.update(os.path.join(ws_path, 'info', 'provenance', 'lens_exptime.json'), sample, a.lens, key,
                         round(exptime_at(cals, lens_at), 1))
        info_json.update(os.path.join(ws_path, 'info', 'provenance', 'lens_instrument.json'), sample, a.lens, key,
                         f'NIRCAM/{ch}')
    print(f'=== done: {i2d}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
