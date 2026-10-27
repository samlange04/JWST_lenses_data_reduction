#!/usr/bin/env python
"""
Sample-nested tracking-JSON helpers shared by the drizzle and PSF scripts.

Every tracking JSON in info/ (lens_products.json, lens_exptime.json,
lens_instrument.json, lens_psf.json, lens_psf_injected.json, wfpc2_alignment.json,
psf_stars.json) is nested {sample: {lens: {key: value}}}, mirroring both
info/samples/lens_samples.json's own top-level-by-sample layout and the
data/<sample>/<lens>/<filt>/ directory convention every script already uses. Before
this module, the tracking JSONs were flat {lens: {...}} with no sample namespace --
harmless only because no lens name has ever collided across slacs_gold/slacs_other/
gallery; nesting by sample removes that latent trap and lets a JSON diff show which
sample changed.
"""
import json
import os

# Where each info/ file lives (2026-10-26): split by who writes it.
INFO_LAYOUT = {
    'samples': ('lens_samples.json',),
    'overrides': ('noise_corr_factors.json', 'psf_stars.json', 'lens_cr_params.json'),
    'provenance': ('lens_products.json', 'lens_instrument.json', 'lens_exptime.json',
                   'lens_stamp_qc.json', 'lens_masks.json', 'lens_arc_masks.json',
                   'lens_positions.json', 'lens_psf.json', 'lens_dataset_subplots.json',
                   'lens_downloads.json', 'lens_exports.json'),
}
_SUBFOLDER = {n: s for s, names in INFO_LAYOUT.items() for n in names}


def path(ws_path, name):
    """Absolute path of info file `name` in its subfolder (size variants of lens_stamp_qc
    go with it)."""
    sub = _SUBFOLDER.get(name) or ('provenance' if name.startswith('lens_stamp_qc') else None)
    if sub is None:
        raise KeyError(f'{name} is not a known info/ file (see info_json.INFO_LAYOUT)')
    return os.path.join(ws_path, 'info', sub, name)


def load(path):
    """Whole tracking JSON, or {} if it doesn't exist yet."""
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def update(path, sample, lens, key, value):
    """Merge {sample: {lens: {key: value}}} into `path`, sorted at every level."""
    data = load(path)
    sample_data = data.setdefault(sample, {})
    lens_entry = sample_data.setdefault(lens, {})
    lens_entry[key] = value
    sample_data[lens] = dict(sorted(lens_entry.items()))
    data[sample] = dict(sorted(sample_data.items()))
    with open(path, 'w') as f:
        json.dump(dict(sorted(data.items())), f, indent=4)


def entry(path, sample, lens, key, default=None):
    """Read {sample: {lens: {key: ...}}} from `path`, or `default` if any level
    is absent. The read-only counterpart to update(); used for per-lens override
    JSONs (e.g. info/overrides/lens_cr_params.json) that a script consults but never writes."""
    return load(path).get(sample, {}).get(lens, {}).get(key, default)
