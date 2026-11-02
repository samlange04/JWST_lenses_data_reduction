#!/usr/bin/env python
"""
Put a lens in one of its sample's categories, and move its stamp dir to match.

    uv run python scripts/set_lens_category.py --sample cowls_spectacular --lens COSJ100119+014849 \
        --category multi_galaxy --note "the round galaxy 1.7\" SE is a second lens"

A sample may set `lens_categories` in info/samples/lens_samples.json (cowls_spectacular: prime,
multi_galaxy; 2026-11-02). Its stamps then live in data/stamps/<sample>/<category>/<lens>/, and
each lens carries `category` (+ `category_note`). `prime`: one deflector; the neighbours are
masked as contaminants. `multi_galaxy`: more than one galaxy's mass has to be modelled (a second
lens, or a perturber close enough to the arcs). Every tool finds the lens through
stamp_paths.lens_stamp_dir / band_dirs, and export_dataset.py writes `lens_category` into each
band's info.json.

The whole lens dir moves (every band, every size, masks, positions, primary_band.json, the band
overview), with os.rename, so git sees a rename once the move is staged. Only the stamp tree is
categorised; the mosaic, PSF and stage trees stay data/<tree>/<sample>/<lens>/.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lens_samples
import stamp_paths

ws_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--sample', type=lens_samples.sample_arg, default=None,
                   help='every lens of this sample (not needed with --lens: its sample is found)')
    p.add_argument('--lens', required=True)
    p.add_argument('--category', required=True)
    p.add_argument('--note', default=None, help='why (category_note)')
    a = p.parse_args()
    lens_samples.resolve_sample(p, a, required=True)
    cats = lens_samples.categories(a.sample)
    if a.category not in cats:
        p.error(f'{a.sample} has lens_categories {cats or "none"}; {a.category!r} is not one of them')
    old = stamp_paths.lens_stamp_dir(ws_path, a.sample, a.lens)
    lens_samples.set_category(a.lens, a.category, a.note, a.sample)
    new = stamp_paths.lens_stamp_dir(ws_path, a.sample, a.lens)
    if old == new:
        print(f'{a.lens}: already {a.category}; note updated' if a.note else f'{a.lens}: already {a.category}')
        return 0
    if os.path.exists(new):
        sys.exit(f'{new} exists already; not moving {old} onto it')
    if os.path.isdir(old):
        os.makedirs(os.path.dirname(new), exist_ok=True)
        os.rename(old, new)
        print(f'{a.lens}: {a.category}; moved {os.path.relpath(old, ws_path)} -> {os.path.relpath(new, ws_path)}')
    else:
        print(f'{a.lens}: {a.category} (no stamp dir yet at {os.path.relpath(old, ws_path)})')
    return 0


if __name__ == '__main__':
    sys.exit(main())
