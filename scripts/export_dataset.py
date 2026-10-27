#!/usr/bin/env python
"""
Export one lens's bands in the PyAutoLens dataset layout a modelling project consumes.

    uv run python scripts/export_dataset.py --lens SPT2147-50 --dest <modelling-project>/data
    uv run python scripts/export_dataset.py --lens B1938+666 --dest <dir> [--filters F277W F115W]

Writes <dest>/<lens>/<FILT>/:

    data.fits                 stamp12_sci.fits            (MJy/sr, float32)
    noise_map.fits            stamp12_noise.fits          (sigma, 1e8 sentinel kept)
    psf.fits                  psf.fits            (odd, unit-sum)
    mask_extra_galaxies.fits  stamp12_mask.fits           (True = remove by noise-scaling; optional)
    positions.json            stamp12_positions.json      (al.Grid2DIrregular JSON; optional)
    info.json                 pixel_scale, mask_radius, redshift_lens, redshift_source,
                              plus provenance (i2d, variant, jwst version, noise factor)

This is the layout a PyAutoLens SLaM-style dataset loader expects (data/noise_map/psf +
info.json with pixel_scale and mask_radius; mask_extra_galaxies.fits and positions.json
optional). `mask_radius` (arcsec) comes from --mask-radius, default 3.0 -- a modelling
choice, so it is written here and nowhere else in this repo. Files are copied, never
linked, so the modelling project's `*.fits` gitignore and rsync behave. The hand-drawn
contaminant mask in this repo is True = excluded, which is exactly the "paint the pixels
to remove" polarity such a loader expects.
"""
import argparse
import json
import os
import shutil
import sys

from astropy.io import fits

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lens_samples
import stamp_paths
import info_json

ws_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def export_band(sample, lens, filt, dest, mask_radius, size):
    cdir = stamp_paths.stamp_dir(ws_path, sample, lens, filt)
    prefix = stamp_paths.find_prefix(cdir, size=size)
    if prefix is None:
        return None
    sci = stamp_paths.find_stamp(cdir, prefix, 'sci')
    noise = stamp_paths.find_stamp(cdir, prefix, 'noise')
    psf = os.path.join(stamp_paths.psf_stamp_dir(ws_path, sample, lens, filt), stamp_paths.psf_name())
    missing = [p for p in (sci, noise, psf) if not os.path.exists(p)]
    if missing:
        print(f'  {filt}: SKIPPED, missing {", ".join(os.path.basename(m) for m in missing)}')
        return None
    out = os.path.join(dest, lens, filt)
    os.makedirs(out, exist_ok=True)
    shutil.copyfile(sci, os.path.join(out, 'data.fits'))
    shutil.copyfile(noise, os.path.join(out, 'noise_map.fits'))
    shutil.copyfile(psf, os.path.join(out, 'psf.fits'))
    optional = {}
    mask = os.path.join(cdir, f'{prefix}_mask.fits')
    if os.path.exists(mask):
        shutil.copyfile(mask, os.path.join(out, 'mask_extra_galaxies.fits'))
        optional['mask_extra_galaxies'] = True
    pos = os.path.join(cdir, f'{prefix}_positions.json')
    if os.path.exists(pos):
        shutil.copyfile(pos, os.path.join(out, 'positions.json'))
        optional['positions'] = True
    hdr = fits.getheader(sci)
    nhdr = fits.getheader(noise)
    zl, zs = lens_samples.redshifts(lens, sample)
    info = {
        'pixel_scale': float(hdr['PIXSCALE']),
        'mask_radius': float(mask_radius),
        'redshift_lens': zl, 'redshift_source': zs,
        'bunit': hdr.get('BUNIT'), 'photmjsr': hdr.get('PHOTMJSR'), 'pixar_sr': hdr.get('PIXAR_SR'),
        'variant': hdr.get('REDUCVAR', 'standard'), 'jwst_version': hdr.get('CAL_VER'),
        'noise_corr_factor': nhdr.get('NOISECOR'), 'noise_corr_scale_arcsec': nhdr.get('NOISESCL'),
        'noise_correlation': info_json.load(os.path.join(ws_path, 'info', 'overrides', 'noise_corr_factors.json')).get('correlation'),
        'source_repo': 'JWST_lenses_data_reduction',
        'source_stamp': os.path.relpath(sci, ws_path), **optional,
    }
    with open(os.path.join(out, 'info.json'), 'w') as fh:
        json.dump(info, fh, indent=4)
    print(f'  {filt}: -> {out}  ({hdr["NAXIS1"]}x{hdr["NAXIS2"]} @ {info["pixel_scale"]}"/px'
          + (', mask' if 'mask_extra_galaxies' in optional else '') + (', positions' if 'positions' in optional else '') + ')')
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--lens', required=True)
    p.add_argument('--sample', default=None)
    p.add_argument('--dest', required=True, help='modelling project data root, e.g. <modelling-project>/data')
    p.add_argument('--filters', nargs='*', default=None, help='default: every band with a stamp')
    p.add_argument('--mask-radius', type=float, default=3.0, help='info.json mask_radius, arcsec')
    p.add_argument('--size', type=float, default=None,
                   help='stamp size to export (default: the lens\'s modelling size)')
    a = p.parse_args()
    sample = a.sample or lens_samples.sample_of(a.lens)
    dest = os.path.expanduser(a.dest)
    root = os.path.join(stamp_paths.stamps_root(ws_path), sample, a.lens)
    filts = [lens_samples.canonical_filter(f) for f in a.filters] if a.filters else \
        sorted(d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))) if os.path.isdir(root) else []
    print(f'=== export {sample}/{a.lens} -> {dest}')
    done = [f for f in filts if export_band(sample, a.lens, f, dest, a.mask_radius, a.size)]
    info_json.update(os.path.join(ws_path, 'info', 'provenance', 'lens_exports.json'), sample, a.lens, dest, done)
    print(f'=== {len(done)} band(s) exported')
    return 0


if __name__ == '__main__':
    sys.exit(main())
