#!/usr/bin/env python
"""
Mark the centres of the EXTRA galaxies of a multi-galaxy lens: the galaxies besides the main
deflector whose mass (and light) a lens model has to include.

    uv run python scripts/make_extra_galaxies.py --sample cowls_spectacular            # multi_galaxy lenses
    uv run python scripts/make_extra_galaxies.py --sample cowls_spectacular --lens COSJ095955+021900 [--force]
    uv run python scripts/make_extra_galaxies.py --sample spt --lens SPT0418-47 --all    # any lens

The window is make_positions.py's (North up, East left; as-observed LEFT, isophote-subtracted
RIGHT; the mask GUIs' arcsinh stretch and colormap), on the lens's primary band. DOUBLE-CLICK
the centre of each extra galaxy (not the main lens) on either panel; each click snaps to the
brightest pixel within --snap-radius px (default 1), as positions do; 'z' undoes the last
click. Esc (or closing the window) finishes.

Writes, per band, `stamp<S>_extra_galaxies_centres.json` in the band's stamp dir: one
al.Grid2DIrregular of (y, x) arcsec from the stamp centre, autoarray's convention (+y toward row
0, i.e. SOUTH here; +x West), exactly the file autolens_workspace's multi-galaxy examples load
with `al.Grid2DIrregular(al.from_json(file_path=...))`. The other bands get the centres through
sky coordinates (make_positions.reproject_positions), so a band whose stamp centre differs by a
fraction of a pixel still gets the right pixels. export_dataset.py copies the file as
`extra_galaxies_centres.json`, and the band overview marks them (cyan x).

Which lenses: with no --lens, the sample's `multi_galaxy` lenses (lens_samples.json
`category`), or every lens with --all. A lens that already has the file on its primary band is
skipped unless --force. Clicking nothing writes nothing.

Contaminant-masked pixels are NOT blanked here (the positions GUI blanks them), so a masked
galaxy can still be clicked. Masking and an extra-galaxy centre do different things and combine
fine: the mask removes a galaxy's LIGHT from the fit, the centre puts its MASS into the model
(a faint satellite is often best both masked and given a mass). A centre on masked pixels is
reported, as information, not as an error.
Record: info/provenance/lens_extra_galaxies.json.
"""
import argparse
import datetime
import os
import sys
import warnings

import numpy as np
from astropy.io import fits

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import info_json
import lens_samples
import make_masks
import make_positions
import positions_io
import stamp_paths

import autolens as al

ws_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECORD_JSON = info_json.path(ws_path, 'lens_extra_galaxies.json')
SUFFIX = 'extra_galaxies_centres.json'


def centres_path(stamp_dir, prefix):
    return os.path.join(stamp_dir, f'{prefix}_{SUFFIX}')


def read_centres(stamp_dir, prefix):
    """[(y, x), ...] arcsec, or None when the band has no file."""
    p = centres_path(stamp_dir, prefix)
    if not os.path.exists(p):
        return None
    return [tuple(map(float, c)) for c in positions_io.flatten(positions_io.read_sets(p))]


def on_mask(centres, mask, pixel_scales):
    """The centres that land on a True pixel of `mask`."""
    out = []
    for (y, x) in centres:
        row, col = make_positions.arcsec_to_pixel(y, x, mask.shape, pixel_scales)
        r, c = int(round(row)), int(round(col))
        if 0 <= r < mask.shape[0] and 0 <= c < mask.shape[1] and mask[r, c]:
            out.append((y, x))
    return out


def process_lens(sample, lens, filt_dirs, requested_filt, force, search_box_size):
    filts = sorted(filt_dirs)
    band = make_masks.pick_display_filt(filts, requested_filt, lens, sample)
    if band is None:
        print(f'{lens}: --filt {requested_filt} not present (have {", ".join(filts)}), skipped')
        return False
    d = filt_dirs[band]
    prefix = make_masks.find_prefix(d, 'auto')
    if read_centres(d, prefix) is not None and not force:
        print(f'{lens}: extra-galaxy centres exist on {band}, skipped (--force to re-mark)')
        return False
    sci_path = stamp_paths.find_stamp(d, prefix, 'sci')
    hdr = fits.getheader(sci_path)
    ps = make_masks.pixel_scale_from_header(hdr)
    sci = al.Array2D.from_fits(file_path=sci_path, pixel_scales=ps).native
    base, _ = make_masks.load_display_base(d, prefix, 'snr', ps)
    mask_path = os.path.join(d, f'{prefix}_mask.fits')
    mask = np.asarray(fits.getdata(mask_path), dtype=bool) if os.path.exists(mask_path) else None

    print(f'\n{lens}  ({lens_samples.category(lens, sample) or "no category"})  marking on {band}')
    print('  DOUBLE-CLICK the centre of each EXTRA galaxy (not the main lens); Esc when done.')
    sets, _ = make_positions.mark_positions_gui(
        sci, ps, lens, band, search_box_size, display='snr', display_base=base,
        subtract='isophote', side_by_side=True, contaminants=None,
        prompt='DOUBLE-CLICK the centre of each EXTRA galaxy (not the main lens) on either panel; '
               'Esc (or close the window) when done')
    centres = [tuple(map(float, c)) for c in positions_io.flatten(sets)]
    if not centres:
        print(f'  no centres clicked: nothing written for {lens}')
        return False
    if mask is not None:
        for (y, x) in on_mask(centres, mask, ps):
            print(f'  note: centre ({y:+.3f}, {x:+.3f})" is under the contaminant mask: its light is masked '
                  f'and its mass will be modelled (fine for a faint satellite; unmask it to fit its light).')

    written = []
    for f in filts:
        bd = filt_dirs[f]
        bp = make_masks.find_prefix(bd, 'auto')
        if bp is None:
            continue
        bh = fits.getheader(stamp_paths.find_stamp(bd, bp, 'sci'))
        band_centres = centres if f == band else make_positions.reproject_positions(centres, hdr, bh)
        positions_io.write_sets([band_centres], centres_path(bd, bp))
        written.append(f)
    info_json.update(RECORD_JSON, sample, lens, 'extra_galaxies', {
        'marked_on': band, 'prefix': prefix, 'n': len(centres),
        'centres_arcsec_yx': [[round(y, 4), round(x, 4)] for y, x in centres],
        'centres_arcsec_east_north': [[round(-x, 4), round(-y, 4)] for y, x in centres],
        'bands': written, 'date': datetime.date.today().isoformat(),
        'convention': 'autoarray (y, x) arcsec from the stamp centre: +y South, +x West',
    })
    print(f'  {len(centres)} centre(s) -> {", ".join(written)} ({prefix}_{SUFFIX})')
    for y, x in centres:
        print(f'    {-x:+.2f}" E  {-y:+.2f}" N   (r = {np.hypot(x, y):.2f}")')
    return True


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--sample', type=lens_samples.sample_arg, default=None,
                   help='every lens of this sample (not needed with --lens: its sample is found)')
    p.add_argument('--lens', default=None)
    p.add_argument('--filt', default=None, help='band to mark on (default: the primary band)')
    p.add_argument('--all', action='store_true', help='every lens, not only the multi_galaxy ones')
    p.add_argument('--force', action='store_true', help='re-mark a lens that has centres')
    p.add_argument('--snap-radius', '--search-box-size', dest='search_box_size', type=int, default=1,
                   help='snap to the brightest pixel within this many px of the click (default 1; 0 = none)')
    a = p.parse_args()
    lens_samples.resolve_sample(p, a, required=True)
    warnings.simplefilter('ignore')
    if a.lens:
        lenses = [a.lens]
    elif a.all or not lens_samples.categories(a.sample):
        lenses = lens_samples.lenses(a.sample)
    else:
        lenses = [l for l in lens_samples.lenses(a.sample) if lens_samples.category(l, a.sample) == 'multi_galaxy']
        print(f'{len(lenses)} multi_galaxy lens(es): {", ".join(lenses) or "none"}')
    root = stamp_paths.stamps_root(ws_path)
    changed = []
    for lens in lenses:
        filt_dirs = {f: d for l, f, d in make_masks.discover_targets(root, a.sample, lens, None)}
        if not filt_dirs:
            print(f'{lens}: no stamps, skipped')
            continue
        if process_lens(a.sample, lens, filt_dirs, a.filt, a.force, a.search_box_size):
            changed.append(lens)
    make_masks.rerender_overviews(a.sample, changed)
    return 0


if __name__ == '__main__':
    sys.exit(main())
