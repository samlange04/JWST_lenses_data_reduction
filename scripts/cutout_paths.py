"""Stamp-size- and variant-keyed output paths, shared by every script (port of the HST
repo's cutout_paths.py; same contract, JWST vocabulary).

    12" (the default)   data/cutouts/<sample>/...        data/qc/<sample>/
                        info/lens_cutout_qc.json
    any other size S    data/cutouts_<S>arcsec/<sample>/ data/qc_<S>arcsec/<sample>/
                        info/lens_cutout_qc_<S>arcsec.json

Keying the tree on --size itself (not on a separate --output the caller must remember) is
deliberate: `make_cutouts.py --size 20` on its own then cannot clobber the 12" product set
that carries the hand-drawn masks.

**One stamp per (sample, lens, filter), and the stamp's filename says which reduction it is.**
`variant` keys an alternate *reduction* at the mosaic layer and tags the sci/noise stamps:

    standard (uncal -> our Detector1/Image2/Image3)   data/mosaics/          cutout_sci.fits
    mastrate (MAST's rate files -> our Image2/Image3) data/mosaics_mastrate/ cutout_mastrate_sci.fits
    mastcal  (MAST's cal files -> our Image3)         data/mosaics_mastcal/  cutout_mastcal_sci.fits
    bychan   (standard, but clean_flicker_noise fits   data/mosaics_bychan/   cutout_bychan_sci.fits
              1/f per amplifier: --flicker-by-channel; stage1/2 go to data/stage{1,2}_bychan/)
    destriped (standard rates put through the rate-level TEMPLATES destripe of
              destripe_nircam.py, object mask from the standard mosaic; opt-in, see
              AGENTS.md *striping* for why it is not the default)
                                                      data/mosaics_destriped/ cutout_destriped_sci.fits

Only the sci/noise stamps and their PNG are tagged. Masks, arc masks, positions and PSFs keep
the bare `cutout` prefix: they describe the band's *grid*, identical across reductions (same
output WCS), so they are shared and can move between branches on their own. A dir holding two
reductions' stamps makes `find_stamp` raise AmbiguousStampError rather than pick -- the loud
failure we want (the HST repo lost a reduction to a silent branch merge before adopting this).

JWST has no separate CR / no-CR pass (jump + outlier_detection always run), so there is a
single prefix, `cutout`; HST's `cutout_cr` does not exist here.
"""
import os

DEFAULT_SIZE = 12.0            # arcsec; the modelling stamp
PREFIX = 'cutout'
PREFIXES = (PREFIX,)           # HST had ('cutout_cr', 'cutout'); JWST has one pass
VARIANT_COMPONENTS = ('mastrate', 'mastcal', 'bychan', 'destriped')
STAMP_KINDS = ('sci', 'noise')


def size_tag(size):
    return '' if float(size) == DEFAULT_SIZE else f'_{float(size):g}arcsec'


def variant_tag(variant):
    return f'_{variant}' if variant else ''


def _is_variant(tag):
    return tag == '' or tag in VARIANT_COMPONENTS


def stamp_name(prefix, kind, variant=''):
    """'cutout_mastrate_sci.fits' / 'cutout_noise.fits'. `prefix` is always PREFIX here; it is
    an argument only so call sites match the HST repo's."""
    return f'{prefix}{variant_tag(variant)}_{kind}.fits'


def stamp_png_name(prefix, variant=''):
    return f'{prefix}{variant_tag(variant)}.png'


class AmbiguousStampError(RuntimeError):
    """More than one reduction's stamp sits in a cutout dir -- see the module docstring."""


def list_stamps(cutout_dir, prefix=PREFIX, kind='sci'):
    import glob
    found = {}
    for path in glob.glob(os.path.join(cutout_dir, f'{prefix}*_{kind}.fits')):
        middle = os.path.basename(path)[len(prefix):-len(f'_{kind}.fits')]
        if middle == '':
            found[''] = path
        elif middle.startswith('_') and _is_variant(middle[1:]):
            found[middle[1:]] = path
    return found


def find_stamp(cutout_dir, prefix=PREFIX, kind='sci', variant=None):
    """The one `cutout[_<variant>]_<kind>.fits` in cutout_dir, or None.

    With variant=None the band must carry exactly ONE reduction's stamp; two raise
    AmbiguousStampError. Pass `variant` to ask for a specific one."""
    stamps = list_stamps(cutout_dir, prefix, kind)
    if variant is not None:
        return stamps.get(variant)
    if len(stamps) > 1:
        names = ', '.join(os.path.basename(p) for _, p in sorted(stamps.items()))
        raise AmbiguousStampError(
            f'{cutout_dir}: {len(stamps)} {prefix}_{kind} stamps from different reductions '
            f'({names}). One stamp per band: remove the one that does not belong '
            f'(or re-cut with --force), then re-run.')
    return next(iter(stamps.values()), None)


def stamp_variant(path):
    base = os.path.basename(path)
    for kind in STAMP_KINDS:
        if base.startswith(PREFIX) and base.endswith(f'_{kind}.fits'):
            middle = base[len(PREFIX):-len(f'_{kind}.fits')]
            if middle == '':
                return ''
            if middle.startswith('_') and _is_variant(middle[1:]):
                return middle[1:]
    raise ValueError(f'{base} is not a stamp filename')


def find_prefix(cutout_dir, drizzle_pass='auto'):
    """'cutout' if this band has a sci stamp, else None. The HST repo chose between its CR and
    no-CR passes here; JWST has one pass, so `drizzle_pass` is accepted and ignored."""
    return PREFIX if find_stamp(cutout_dir, PREFIX, 'sci') is not None else None


def mosaics_root(ws_path, variant=''):
    """data/mosaics[_<variant>] -- the Image3 i2d tree (the HST repo's data/drizzled)."""
    return os.path.join(ws_path, 'data', f'mosaics{variant_tag(variant)}')


def mosaic_dir(ws_path, sample, lens, filt, variant=''):
    return os.path.join(mosaics_root(ws_path, variant), sample, lens, filt)


def find_i2d(mosaic_dir_):
    """The one *_i2d.fits in a mosaic dir, or None."""
    import glob
    hits = sorted(glob.glob(os.path.join(mosaic_dir_, '*_i2d.fits')))
    if len(hits) > 1:
        raise AmbiguousStampError(f'{mosaic_dir_}: {len(hits)} i2d files: {hits}')
    return hits[0] if hits else None


def cutouts_root(ws_path, size=DEFAULT_SIZE):
    return os.path.join(ws_path, 'data', f'cutouts{size_tag(size)}')


def qc_root(ws_path, size=DEFAULT_SIZE):
    """data/qc[_<S>arcsec] -- QC grids tiling the stamps (the HST repo's data/mosaics;
    renamed because 'mosaics' here means the Image3 products)."""
    return os.path.join(ws_path, 'data', f'qc{size_tag(size)}')


def qc_json_path(ws_path, size=DEFAULT_SIZE):
    return os.path.join(ws_path, 'info', f'lens_cutout_qc{size_tag(size)}.json')


def cutout_dir(ws_path, sample, lens, filt, size=DEFAULT_SIZE):
    return os.path.join(cutouts_root(ws_path, size), sample, lens, filt)


def psf_cutout_dir(ws_path, sample, lens, filt):
    """Where the band's PSF products (cutout_psf*.fits) live: always the DEFAULT_SIZE tree.
    The kernel is a property of the band, not of the stamp size."""
    return cutout_dir(ws_path, sample, lens, filt)


def gitignored(paths, ws_path=None):
    """The subset of `paths` .gitignore excludes (one batched `git check-ignore --stdin`);
    any failure returns the empty set so a guard can only narrow a run, never block it."""
    import subprocess
    paths = [os.path.abspath(p) for p in paths]
    if not paths:
        return set()
    root = ws_path or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        proc = subprocess.run(['git', '-C', root, 'check-ignore', '--stdin'],
                              input='\n'.join(paths), capture_output=True, text=True)
    except (OSError, ValueError):
        return set()
    if proc.returncode > 1:
        return set()
    return {os.path.abspath(line) for line in proc.stdout.splitlines() if line.strip()}
