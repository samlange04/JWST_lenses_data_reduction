"""Stamp paths and filenames, shared by every script (port of the HST repo's stamp_paths.py;
same contract, JWST vocabulary).

**One tree, the size in the filename (2026-10-26).** Every stamp lives in

    data/stamps/<sample>/<lens>/<FILT>/

and its filenames start `stamp<S>_`, where S is the stamp's nominal size in arcsec. Each lens
has one MODELLING size -- its `stamp_size` in info/samples/lens_samples.json, else
DEFAULT_SIZE (12") -- so B1938+666's stamps are `stamp7_*` and the SPT lenses' `stamp12_*`.
A re-cut at another size sits beside them as `stamp<S>_*` and cannot overwrite them; only the
modelling-size files are tracked (see .gitignore). Before 2026-10-26 the size picked the tree
(`data/cutouts/` vs `data/cutouts_<S>arcsec/`) and the files were all `cutout_*`.

    stamp7_sci.fits / stamp7_noise.fits   science image and 1-sigma noise
    stamp7.png                            3-panel QC render (gitignored)
    stamp7_mask.fits                      contaminant mask (hand-drawn)
    stamp7_mask_arcs.fits                 optional arc mask
    stamp7_positions.json                 lensed-image positions (hand-marked)
    stamp7_dataset.png                    sci/noise/PSF/mask QC panel
    psf.fits / psf_err.fits               the band's PSF, no size and no prefix

`size=None` everywhere below means "the lens's modelling size", resolved from the band dir's
<sample>/<lens> path components through lens_samples.py.

**One stamp per (sample, lens, filter, size), and the filename says which reduction it is.**
`variant` keys an alternate *reduction* at the mosaic layer and tags the sci/noise stamps:

    standard (uncal -> our Detector1/Image2/Image3)   data/mosaics/           stamp7_sci.fits
    mastrate (MAST's rate files -> our Image2/Image3) data/mosaics_mastrate/  stamp7_mastrate_sci.fits
    mastcal  (MAST's cal files -> our Image3)         data/mosaics_mastcal/   stamp7_mastcal_sci.fits
    bychan   (standard, but clean_flicker_noise fits   data/mosaics_bychan/    stamp7_bychan_sci.fits
              1/f per amplifier: --flicker-by-channel; stage1/2 go to data/stage{1,2}_bychan/)
    destriped (standard rates put through the rate-level TEMPLATES destripe of
              destripe_nircam.py, object mask from the standard mosaic; opt-in, see
              AGENTS.md *striping* for why it is not the default)
                                                      data/mosaics_destriped/ stamp7_destriped_sci.fits

Only the sci/noise stamps and their PNG are tagged. Masks, arc masks and positions keep the
bare `stamp<S>` prefix and the PSF is plain `psf.fits`: they describe the band's *grid*,
identical across reductions (same output WCS), so they are shared and can move between
branches on their own. A dir holding two reductions' stamps makes `find_stamp` raise
AmbiguousStampError rather than pick -- the loud failure we want (the HST repo lost a
reduction to a silent branch merge before adopting this).

JWST has no separate CR / no-CR pass (jump + outlier_detection always run), so unlike the
HST repo there is no pass tag at all.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DEFAULT_SIZE = 12.0            # arcsec; the modelling stamp of a lens with no stamp_size
VARIANT_COMPONENTS = ('mastrate', 'mastcal', 'bychan', 'destriped')
STAMP_KINDS = ('sci', 'noise')
PSF_FILES = {'psf': 'psf.fits', 'psf_err': 'psf_err.fits'}


def size_label(size):
    """'12' for 12.0, '7' for 7.0 -- the size as it appears in names."""
    return f'{float(size):g}'


def modelling_size(lens, sample=None):
    """The lens's modelling-stamp side in arcsec: its lens_samples.json stamp_size, else
    DEFAULT_SIZE. A lens the roster does not know (a scratch dir) gets DEFAULT_SIZE."""
    import lens_samples
    try:
        return float(lens_samples.stamp_size(lens, sample) or DEFAULT_SIZE)
    except (KeyError, ValueError, SystemExit):
        return DEFAULT_SIZE


def _band_identity(stamp_dir):
    """(sample, lens) from a data/stamps/<sample>/<lens>/<FILT> dir."""
    lens_dir = os.path.dirname(os.path.normpath(stamp_dir))
    return os.path.basename(os.path.dirname(lens_dir)), os.path.basename(lens_dir)


def resolve_size(stamp_dir, size=None):
    """`size`, or the modelling size of the lens whose band dir this is when size is None."""
    if size is not None:
        return float(size)
    sample, lens = _band_identity(stamp_dir)
    return modelling_size(lens, sample)


def stamp_prefix(size):
    """'stamp7', 'stamp12' -- the prefix of a stamp at `size` and of everything drawn on it."""
    return f'stamp{size_label(size)}'


def psf_name(kind='psf'):
    return PSF_FILES[kind]


def size_tag(size):
    """'' for a lens's modelling size (pass None), else '_<S>arcsec'. Keys the size-dependent
    things that are not stamps: the QC-grid tree and the stamp-QC JSON."""
    return '' if size is None else f'_{size_label(size)}arcsec'


def variant_tag(variant):
    return f'_{variant}' if variant else ''


def _is_variant(tag):
    return tag == '' or tag in VARIANT_COMPONENTS


def stamp_name(prefix, kind, variant=''):
    """'stamp7_mastrate_sci.fits' / 'stamp12_noise.fits'."""
    return f'{prefix}{variant_tag(variant)}_{kind}.fits'


def stamp_png_name(prefix, variant=''):
    return f'{prefix}{variant_tag(variant)}.png'


class AmbiguousStampError(RuntimeError):
    """More than one reduction's stamp sits in a band dir -- see the module docstring."""


def list_stamps(stamp_dir, prefix, kind='sci'):
    import glob
    found = {}
    for path in glob.glob(os.path.join(stamp_dir, f'{prefix}*_{kind}.fits')):
        middle = os.path.basename(path)[len(prefix):-len(f'_{kind}.fits')]
        if middle == '':
            found[''] = path
        elif middle.startswith('_') and _is_variant(middle[1:]):
            found[middle[1:]] = path
    return found


def find_stamp(stamp_dir, prefix, kind='sci', variant=None):
    """The one `<prefix>[_<variant>]_<kind>.fits` in stamp_dir, or None.

    With variant=None the band must carry exactly ONE reduction's stamp; two raise
    AmbiguousStampError. Pass `variant` to ask for a specific one."""
    stamps = list_stamps(stamp_dir, prefix, kind)
    if variant is not None:
        return stamps.get(variant)
    if len(stamps) > 1:
        names = ', '.join(os.path.basename(p) for _, p in sorted(stamps.items()))
        raise AmbiguousStampError(
            f'{stamp_dir}: {len(stamps)} {prefix}_{kind} stamps from different reductions '
            f'({names}). One stamp per band: remove the one that does not belong '
            f'(or re-cut with --force), then re-run.')
    return next(iter(stamps.values()), None)


def stamp_variant(path):
    base = os.path.basename(path)
    for kind in STAMP_KINDS:
        if base.startswith('stamp') and base.endswith(f'_{kind}.fits'):
            tag = '_'.join(base[:-len(f'_{kind}.fits')].split('_')[1:])
            if _is_variant(tag):
                return tag
    raise ValueError(f'{base} is not a stamp filename')


def find_prefix(stamp_dir, drizzle_pass='auto', size=None):
    """'stamp<S>' if this band has a sci stamp at `size` (None: the lens's modelling size),
    else None. The HST repo chose between its CR and no-CR passes here; JWST has one pass,
    so `drizzle_pass` is accepted and ignored."""
    prefix = stamp_prefix(resolve_size(stamp_dir, size))
    return prefix if find_stamp(stamp_dir, prefix, 'sci') is not None else None


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


def stamps_root(ws_path):
    """data/stamps -- the one stamp tree, every size."""
    return os.path.join(ws_path, 'data', 'stamps')


def qc_root(ws_path, size=None):
    """data/qc[_<S>arcsec] -- QC grids tiling the stamps (the HST repo's data/mosaics;
    renamed because 'mosaics' here means the Image3 products). None: each lens's modelling
    size."""
    return os.path.join(ws_path, 'data', f'qc{size_tag(size)}')


def qc_json_path(ws_path, size=None):
    """info/provenance/lens_stamp_qc[_<S>arcsec].json; None: the modelling-size record."""
    return os.path.join(ws_path, 'info', 'provenance', f'lens_stamp_qc{size_tag(size)}.json')


def stamp_dir(ws_path, sample, lens, filt):
    return os.path.join(stamps_root(ws_path), sample, lens, filt)


# The PSF sits in the same band dir as every stamp size.
psf_stamp_dir = stamp_dir


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
