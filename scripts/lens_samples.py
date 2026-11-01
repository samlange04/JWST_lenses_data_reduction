"""Lens samples: the one reader of ``info/samples/lens_samples.json``.

Mirrors ``mast_target_names.py`` in the HST repo, simplified for JWST: a JWST lens is
located in MAST by **proposal ID + target name**, not by a wildcard on an SDSS designation,
so there are no GAL-* quirks -- except in a survey program, whose targets are tiles: a
sample with ``"mast_query": "position"`` is located by proposal ID + position instead
(``download_nircam.query_position``). Each sample block carries the program it comes from, and each
lens carries what no FITS file does -- catalogue position (the mosaics' CRVAL and, unless a
measured ``deflector_ra``/``deflector_dec`` overrides it, the stamp centre) and the
redshifts that ``export_dataset.py`` writes into the modelling ``info.json``.

    b1938               JVAS B1938+666           GO 8281 (Vegetti)    F115W F277W
    spt                 SPT0418-47, SPT2147-50   GO 1355 (TEMPLATES)  F115W..F444W (SPT2147: F200W + LW)
    cowls_spectacular   17 COWLS II lenses       GO 1727 (COSMOS-Web) F115W F150W F277W F444W

Nothing else parses that file or keeps a second copy of a lens list. Output and directory
names always use the lens key (``B1938+666``, ``SPT0418-47``), never the MAST target name.

**Every lens in a sample is tried on every run.** A lens with no data in a requested
filter is a normal outcome (``NoMastData``): the script records ``null`` in the tracking
JSON and exits 0, so a runner can sweep a sample with a fixed filter list.
"""

import argparse
import difflib
import json
import os

_INFO_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'info')
SAMPLES_JSON = os.path.join(_INFO_DIR, 'samples', 'lens_samples.json')
PRIMARY_BAND_JSON = os.path.join(_INFO_DIR, 'provenance', 'lens_primary_band.json')

DEFAULT_SAMPLE = 'spt'

# NIRCam imaging filters this repo knows how to place on a detector. The short-wave
# channel (nrc[ab]1-4, 0.031"/pix) and long-wave channel (nrc[ab]long, 0.063"/pix) are
# exposed simultaneously, so one MAST observation's product list carries BOTH channels'
# files: download_nircam.py sorts them by the FITS FILTER/PUPIL cards, never by obs_id.
SW_FILTERS = ('F070W', 'F090W', 'F115W', 'F150W', 'F200W',
              'F140M', 'F162M', 'F182M', 'F210M')
LW_FILTERS = ('F277W', 'F356W', 'F444W',
              'F250M', 'F300M', 'F335M', 'F360M', 'F410M', 'F430M', 'F460M', 'F480M')
NATIVE_SCALE = {'SW': 0.031, 'LW': 0.063}       # arcsec/pix, NIRCam instrument handbook


class NoMastData(Exception):
    """Zero MAST observations for this lens+filter: an ordinary outcome, kept as its own
    type so a broad ``except Exception`` around the download cannot report an empty
    archive as a broken download."""


def channel(filt):
    """'SW' or 'LW' for a NIRCam filter name (any case). Raises for an unknown filter."""
    f = filt.upper()
    if f in SW_FILTERS:
        return 'SW'
    if f in LW_FILTERS:
        return 'LW'
    raise ValueError(f'{filt!r} is not a NIRCam imaging filter this repo knows '
                     f'(lens_samples.SW_FILTERS / LW_FILTERS)')


def canonical_filter(filt):
    """'f115W' -> 'F115W': the FITS/MAST spelling. Directory names use this too, unlike
    the HST repo's 'f814W' -- JWST filter names are upper-case everywhere else."""
    f = filt.upper()
    channel(f)
    return f


_cache = None


def _load():
    global _cache
    if _cache is None:
        with open(SAMPLES_JSON) as f:
            _cache = json.load(f)
    return _cache


def samples():
    return list(_load().keys())


def sample_arg(name):
    """argparse `type` for --sample: `name` if it is a defined sample, else an error naming the
    closest one. Without it a mistyped sample ('cowls-spectactular') reads as a real sample with
    no stamps, and a GUI reports "no stamps found" instead of the typo."""
    known = samples()
    if name in known:
        return name
    close = difflib.get_close_matches(name.replace('-', '_'), known, n=1, cutoff=0.5)
    raise argparse.ArgumentTypeError(f'unknown sample {name!r}'
                                     + (f" (did you mean '{close[0]}'?)" if close else '')
                                     + f'; defined samples: {", ".join(known)}')


def _sample(sample):
    data = _load()
    try:
        return data[sample]
    except KeyError:
        raise KeyError(f'Unknown sample {sample!r}. Defined samples: {", ".join(data)}. '
                       f'Add it to {SAMPLES_JSON} rather than hardcoding a lens list.') from None


def lenses(sample=DEFAULT_SAMPLE):
    return sorted(_sample(sample)['lenses'])


def proposal_id(sample):
    return str(_sample(sample)['proposal_id'])


def mast_query(sample):
    """How the sample's lenses are found in MAST: 'target' (proposal + target name, the
    default) or 'position' (proposal + position, for survey programs whose targets are
    tiles, e.g. COSMOS-Web's CWEBTILE-*)."""
    q = _sample(sample).get('mast_query', 'target')
    if q not in ('target', 'position'):
        raise ValueError(f'sample {sample!r}: mast_query must be "target" or "position", not {q!r}')
    return q


def mosaic_field(sample):
    """The sample's mosaic side in arcsec (``mosaic_field``), or None for reduce_nircam's
    default. download_nircam.py fetches exactly the detector files that overlap it."""
    v = _sample(sample).get('mosaic_field')
    return None if v is None else float(v)


def prune_intermediates(sample):
    """True if reduce_nircam.py should delete rate/rateints once a cal exists and the
    Image3 crf files once the mosaic exists (``prune_intermediates``; survey samples whose
    stage1/stage2 trees would not fit on disk)."""
    return bool(_sample(sample).get('prune_intermediates', False))


def tweakreg_lens_first(sample):
    """True if Image3's relative tweakreg should align the frames covering the lens first and
    grow the reference from them (``tweakreg_lens_first``: the lens-covering cal files lead the
    association, and tweakreg runs with ``expand_refcat=True, enforce_user_order=True``). By
    default tweakwcs takes the first group in file order as the sole reference; in a survey
    mosaic that can be a neighbouring tile's frame that barely overlaps the rest."""
    return bool(_sample(sample).get('tweakreg_lens_first', False))


def tweakreg_sw_from_lw(sample):
    """True if a SW band's frames should take the tweakreg offset of their own exposure's LW
    frames instead of being fitted (``tweakreg_sw_from_lw``; reduce_nircam.apply_offsets). SW and
    LW are exposed together through one pointing, and in shallow SW frames tweakreg's fit is
    noise."""
    return bool(_sample(sample).get('tweakreg_sw_from_lw', False))


def sample_of(lens):
    for name, block in _load().items():
        if lens in block['lenses']:
            return name
    return None


def entry(lens, sample=None):
    """The per-lens dict (mast_target, ra, dec, redshift_*). KeyError if unknown."""
    if sample is None:
        sample = sample_of(lens)
        if sample is None:
            raise KeyError(f'{lens!r} is in no sample in {SAMPLES_JSON}')
    try:
        return _sample(sample)['lenses'][lens]
    except KeyError:
        raise KeyError(f'{lens!r} is not in sample {sample!r} '
                       f'(has {", ".join(lenses(sample))})') from None


def mast_target(lens, sample=None):
    return entry(lens, sample).get('mast_target', lens)


def coord(lens, sample=None):
    """astropy SkyCoord of the catalogue position (ICRS, degrees)."""
    from astropy.coordinates import SkyCoord
    import astropy.units as u
    e = entry(lens, sample)
    return SkyCoord(e['ra'] * u.deg, e['dec'] * u.deg, frame='icrs')


def deflector_coord(lens, sample=None):
    """SkyCoord of the MEASURED deflector (``deflector_ra``/``deflector_dec``), or None.

    Measured by hand for B1938+666 (0.52" from its APT coordinate) and by
    measure_lens_centres.py for every other lens (2026-11-01; up to ~0.4" off). ``ra``/``dec``
    stay the mosaics' CRVAL, so they are not edited to match; make_stamps cuts the stamp here
    instead (``--center auto``)."""
    from astropy.coordinates import SkyCoord
    import astropy.units as u
    e = entry(lens, sample)
    if 'deflector_ra' not in e:
        return None
    return SkyCoord(e['deflector_ra'] * u.deg, e['deflector_dec'] * u.deg, frame='icrs')


def stamp_size(lens, sample=None):
    """The lens's modelling-stamp side in arcsec (``stamp_size``), or None for the default.

    For a lens the default 12" stamp does not suit (B1938+666: a 0.45" ring whose 12" stamp
    is a third bright neighbours and detector streaks). make_stamps.py cuts it at this size
    INTO THE DEFAULT TREE, so the tracked stamp, masks, positions and export need no --size."""
    return entry(lens, sample).get('stamp_size')


def theta_e(lens, sample=None):
    """The lens's Einstein radius in arcsec (`theta_e`; published or COWLS I), or None."""
    v = entry(lens, sample).get('theta_e')
    return None if v is None else float(v)


def primary_band(lens, sample=None):
    """(band, source): the lens's PRIMARY band -- the one the mask and arc-mask GUIs draw first
    (the other bands start from its mask), the one positions are clicked on, and the one to
    model first. `source` says where it came from:
      'reviewed'  `primary_band` in lens_samples.json, set by hand after looking (always wins);
      'measured'  the suggestion of choose_primary_band.py in lens_primary_band.json (the band
                  where a lensed image's position is best defined: arc S/N, discounted where
                  the band's PSF under-resolves theta_E);
      (None, None) when neither exists, and callers fall back to their fixed band order."""
    e = entry(lens, sample)
    if e.get('primary_band'):
        return canonical_filter(e['primary_band']), 'reviewed'
    sample = sample or sample_of(lens)
    try:
        with open(PRIMARY_BAND_JSON) as f:
            rec = json.load(f).get(sample, {}).get(lens, {})
    except FileNotFoundError:
        rec = {}
    if rec.get('suggested'):
        return rec['suggested'], 'measured'
    return None, None


def redshifts(lens, sample=None):
    e = entry(lens, sample)
    return e['redshift_lens'], e['redshift_source']


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(description='Print the lenses in a sample, one per line.')
    p.add_argument('sample', nargs='?', type=sample_arg, default=DEFAULT_SAMPLE)
    p.add_argument('--list', action='store_true', help='list sample names and sizes')
    p.add_argument('--print-sample', action='store_true',
                   help='print only the resolved sample name (for shell runners)')
    a = p.parse_args()
    if a.list:
        for s in samples():
            print(f'{s:18s} GO {proposal_id(s):6s} {len(lenses(s)):3d} lenses')
    elif a.print_sample:
        print(a.sample)
    else:
        for lens in lenses(a.sample):
            print(lens)
