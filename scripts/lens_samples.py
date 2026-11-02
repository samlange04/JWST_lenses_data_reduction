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
    """The one sample `lens` is in, or None. A lens in two samples is a roster error (every
    tool finds a lens's sample this way), so it raises rather than picking one."""
    hits = [name for name, block in _load().items() if lens in block['lenses']]
    if len(hits) > 1:
        raise ValueError(f'{lens!r} is in more than one sample ({", ".join(hits)}) in {SAMPLES_JSON}')
    return hits[0] if hits else None


def resolve_sample(parser, args, required=False, default=None):
    """The sample a script works on, from its parsed `args` (`args.sample`, `args.lens`: one
    name or a list), so --sample is never needed alongside --lens (2026-11-02).

      * --lens given: the sample is the one the lens is in (lens_samples.json; a lens is in one
        sample only). An unknown lens is an error naming the closest one; --sample, if also
        given, must agree; lenses from different samples are an error.
      * no --lens: --sample, else `default` (the script's old default sample; None for "every
        sample"), or an error when `required`.

    Errors go through `parser.error`, so they print the usage line and exit 2. The result is
    also written back to `args.sample`."""
    names = args.lens if isinstance(args.lens, (list, tuple)) else ([args.lens] if args.lens else [])
    sample = args.sample
    if names:
        found = {}
        for lens in names:
            s = sample_of(lens)
            if s is None:
                every = [l for b in _load().values() for l in b['lenses']]
                close = difflib.get_close_matches(lens, every, n=1, cutoff=0.6)
                parser.error(f'unknown lens {lens!r}' + (f" (did you mean '{close[0]}'?)" if close else '')
                             + f'; it is in no sample of {SAMPLES_JSON}')
            found[lens] = s
        if sample is not None:
            wrong = [f'{l} is in {s!r}' for l, s in found.items() if s != sample]
            if wrong:
                parser.error(f'{"; ".join(wrong)}, not --sample {sample!r} (leave --sample out: it '
                             f'is found from --lens)')
        elif len(set(found.values())) > 1:
            parser.error('the lenses are in different samples ('
                         + ', '.join(f'{l}: {s}' for l, s in found.items()) + '); run one sample at a time')
        else:
            sample = next(iter(found.values()))
    elif sample is None:
        if required:
            parser.error('give --lens, or --sample for every lens of a sample')
        sample = default
    args.sample = sample
    return sample


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


def set_best_band_visual(lens, band, note, sample=None):
    """Record the band chosen BY EYE for `lens` as `best_band_visual` in lens_samples.json
    (choose_best_band.py), with a note saying how. Visual inspection only: not necessarily the
    band with the highest arc S/N (that is `best_band_arc_snr` in lens_primary_band.json). The
    file is rewritten in its own format (4-space JSON, non-ASCII kept), so a choice is an
    ordinary one-line diff."""
    global _cache
    sample = sample or sample_of(lens)
    with open(SAMPLES_JSON) as f:
        data = json.load(f)
    e = data[sample]['lenses'][lens]
    e['best_band_visual'] = canonical_filter(band)
    e['best_band_visual_note'] = note
    with open(SAMPLES_JSON, 'w') as f:
        f.write(json.dumps(data, indent=4, ensure_ascii=False) + '\n')
    _cache = None


def categories(sample):
    """The sample's lens categories (`lens_categories`), in order, or [] for a flat sample. A
    categorised sample's stamps live in data/stamps/<sample>/<category>/<lens>/ (stamp_paths)."""
    return list(_sample(sample).get('lens_categories') or [])


def category(lens, sample=None):
    """The lens's category (`category`; default the sample's first), or None for a flat sample."""
    sample = sample or sample_of(lens)
    cats = categories(sample)
    if not cats:
        return None
    c = entry(lens, sample).get('category') or cats[0]
    if c not in cats:
        raise ValueError(f'{lens}: category {c!r} is not one of {sample}\'s lens_categories {cats}')
    return c


def set_category(lens, cat, note=None, sample=None):
    """Record `lens`'s category (+ `category_note`) in lens_samples.json. The stamp dir is moved
    by set_lens_category.py, not here."""
    global _cache
    sample = sample or sample_of(lens)
    if cat not in categories(sample):
        raise ValueError(f'{cat!r} is not one of {sample}\'s lens_categories {categories(sample)}')
    with open(SAMPLES_JSON) as f:
        data = json.load(f)
    e = data[sample]['lenses'][lens]
    e['category'] = cat
    if note:
        e['category_note'] = note
    with open(SAMPLES_JSON, 'w') as f:
        f.write(json.dumps(data, indent=4, ensure_ascii=False) + '\n')
    _cache = None


def theta_e(lens, sample=None):
    """The lens's Einstein radius in arcsec (`theta_e`; published or COWLS I), or None."""
    v = entry(lens, sample).get('theta_e')
    return None if v is None else float(v)


def primary_band(lens, sample=None):
    """(band, source): the lens's PRIMARY band -- the one the mask and arc-mask GUIs draw first
    (the other bands start from its mask), the one positions are clicked on, and the one to
    model first. `source` says where it came from:
      'visual'   `best_band_visual` in lens_samples.json, chosen by eye with choose_best_band.py
                 (always wins). A visual inspection, not necessarily the highest arc S/N;
      'arc_snr'  `best_band_arc_snr`, choose_primary_band.py's measurement in lens_primary_band.json
                 (arc S/N in the ring annulus, discounted where the PSF under-resolves theta_E);
      (None, None) when neither exists, and callers fall back to their fixed band order."""
    e = entry(lens, sample)
    if e.get('best_band_visual'):
        return canonical_filter(e['best_band_visual']), 'visual'
    sample = sample or sample_of(lens)
    try:
        with open(PRIMARY_BAND_JSON) as f:
            rec = json.load(f).get(sample, {}).get(lens, {})
    except FileNotFoundError:
        rec = {}
    if rec.get('best_band_arc_snr'):
        return rec['best_band_arc_snr'], 'arc_snr'
    return None, None


def redshifts(lens, sample=None):
    """(z_lens, z_source), None where unknown. SPECTROSCOPIC AND PHOTOMETRIC ALIKE: anything that
    shows or exports a redshift must also say which it is (redshift_kinds / redshift_text)."""
    e = entry(lens, sample)
    return e['redshift_lens'], e['redshift_source']


def redshift_kind_of(kind_text):
    """'spectroscopic' or 'photometric' from a `redshift_*_kind` string ('spec (...)',
    'photo-z (...)'), else None."""
    k = (kind_text or '').strip().lower()
    if k.startswith('spec'):
        return 'spectroscopic'
    if k.startswith('photo'):
        return 'photometric'
    return None


def redshift_kinds(lens, sample=None):
    """(kind_lens, kind_source): 'spectroscopic', 'photometric', or None (no redshift).

    Only a SPECTROSCOPIC redshift is a confirmed redshift in this repo (2026-11-02). A
    photometric one may be shown or exported, but always labelled as photometric. Every
    redshift in lens_samples.json carries its `redshift_*_kind` (a source and a method);
    one without a kind is an error, not silently 'confirmed'."""
    e = entry(lens, sample)
    out = []
    for w in ('lens', 'source'):
        z, k = e.get(f'redshift_{w}'), e.get(f'redshift_{w}_kind')
        if z is None:
            out.append(None)
            continue
        kind = redshift_kind_of(k)
        if kind is None:
            raise ValueError(f'{lens}: redshift_{w} {z} has no recognisable redshift_{w}_kind ({k!r}); '
                             f'it must start with "spec" or "photo-z"')
        out.append(kind)
    return tuple(out)


def redshift_text(z, kind, fmt='{:g}'):
    """A redshift for display, as precise as recorded: '0.881' (spectroscopic), '0.577 (photo-z)'
    (photometric), '?' (none)."""
    if z is None:
        return '?'
    return fmt.format(z) + ('' if kind == 'spectroscopic' else ' (photo-z)')


if __name__ == '__main__':
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
