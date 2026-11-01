#!/usr/bin/env python
"""
Choose each lens's PRIMARY band: the one where a lensed image's position is best defined. The
mask and arc-mask GUIs draw it first (every other band starts from its mask), positions are
clicked on it, and it is the band to model first.

    uv run python scripts/choose_primary_band.py                    # every sample
    uv run python scripts/choose_primary_band.py --sample cowls_spectacular [--lens LENS]

A fixed order cannot do this. It used to be F444W > F356W > F277W > ... > F115W, but the best
band depends on the lens and source spectra: the lens light is old stars peaking near rest
1.6 um, and the arc is whatever the source is. Most sources have no redshift (14 of the 17
COWLS ones, and COSJ100119+014849 has no lens redshift either), so the colour is measured, not inferred.
It also depends on how well the band's PSF resolves the Einstein ring.

Per band, on the modelling stamp:
  * the lens light is the azimuthal median profile of the stamp, interpolated in log-log
    across the ring annulus |r - theta_E| < w (w = max(0.25 theta_E, the PSF FWHM, 0.15"));
  * arc S/N = the SIGNED sum of the residual in that annulus over its noise in quadrature,
    with the band's contaminant mask applied if it has one. Signed, so that the quadrupole an
    elliptical lens leaves about a circular profile cancels;
  * score = arc S/N x min(1, theta_E / (R0 x FWHM)), R0 = 5: a clicked position's precision
    goes as FWHM / S/N while the ring is under-resolved; once theta_E spans R0 PSF widths,
    more resolution no longer helps, and S/N alone decides.
The suggestion is the best score. None if no band reaches MIN_ARC_SNR: the arcs are then too
faint against the error of the lens-light profile, as on COSJ095914+021219, COSJ100013+023424
and COSJ100028+021928 (2026-11-01). It is
also biased toward the red bands for bright, compact lenses (theta_E < ~0.6"), where lens light
leaks into the annulus.

So the suggestion is a default, not a verdict. Set `primary_band` on the lens in
info/samples/lens_samples.json after looking at the GUIs; it always wins, and re-running this
script records it. lens_samples.primary_band() resolves reviewed > measured > none (the GUIs
then fall back to their fixed order).

Writes:
  * info/provenance/lens_primary_band.json: per lens, the suggestion, the resolved choice and
    its source, theta_E, and every band's arc S/N, FWHM and score;
  * data/stamps/<sample>/<lens>/primary_band.json: the resolved choice, so it travels with the
    lens's stamps.
export_dataset.py writes `primary_band`, `primary_band_source` and `is_primary_band` into each
band's info.json.
"""
import argparse
import glob
import json
import os
import sys
import warnings

import numpy as np
from astropy.io import fits

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import info_json
import lens_samples
import make_band_overview
import stamp_paths

ws_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

R0 = 5.0               # theta_E >= R0 PSF FWHMs: resolution no longer limits the position
MIN_ARC_SNR = 15.0     # below this in every band the measurement is the lens-profile error
JDOX_FWHM = {'F070W': 0.030, 'F090W': 0.034, 'F115W': 0.040, 'F150W': 0.050, 'F200W': 0.066,
             'F277W': 0.092, 'F356W': 0.116, 'F444W': 0.145}   # fallback without a PSF record


def arc_snr(sci, noise, scale, theta_e, fwhm, mask=None):
    """Signed arc S/N in the ring annulus after subtracting the interpolated lens profile."""
    n = sci.shape[0]
    yy, xx = np.mgrid[:n, :n]
    r = np.hypot(xx - (n - 1) / 2, yy - (n - 1) / 2) * scale
    good = np.isfinite(sci) & (noise > 0) & (noise < 1e7)
    if mask is not None:
        good &= ~mask
    w = max(0.25 * theta_e, fwhm, 0.15)
    edges = np.arange(0.0, r.max() + scale, scale)
    rc = 0.5 * (edges[1:] + edges[:-1])
    prof = np.full(len(rc), np.nan)
    for k, (a, b) in enumerate(zip(edges[:-1], edges[1:])):
        sel = good & (r >= a) & (r < b)
        if sel.any():
            prof[k] = np.median(sci[sel])
    ok = np.isfinite(prof) & (prof > 0) & (np.abs(rc - theta_e) >= w)
    if ok.sum() < 3:
        return None
    lens = np.exp(np.interp(np.log(np.maximum(r, scale / 2)), np.log(rc[ok]), np.log(prof[ok])))
    ann = good & (np.abs(r - theta_e) < w)
    if not ann.any():
        return None
    return float((sci - lens)[ann].sum() / np.sqrt((noise[ann] ** 2).sum()))


def measure(sample, lens):
    te = lens_samples.theta_e(lens, sample)
    psf = info_json.load(info_json.path(ws_path, 'lens_psf.json')).get(sample, {}).get(lens, {})
    prefix = stamp_paths.stamp_prefix(stamp_paths.modelling_size(lens, sample))
    scores = {}
    for d in sorted(glob.glob(os.path.join(ws_path, 'data', 'stamps', sample, lens, 'F*'))):
        filt = os.path.basename(d)
        sci_f = stamp_paths.find_stamp(d, prefix, 'sci')
        noise_f = stamp_paths.find_stamp(d, prefix, 'noise')
        if not sci_f or not noise_f or te is None:
            continue
        hdr = fits.getheader(sci_f)
        scale = float(hdr.get('PIXSCALE') or (0.03 if lens_samples.channel(filt) == 'SW' else 0.06))
        sci = fits.getdata(sci_f).astype(float)
        noise = fits.getdata(noise_f).astype(float)
        mask_f = os.path.join(d, f'{prefix}_mask.fits')
        mask = fits.getdata(mask_f).astype(bool) if os.path.exists(mask_f) else None
        fwhm = (psf.get(filt) or {}).get('fwhm_arcsec') or JDOX_FWHM.get(filt)
        snr = arc_snr(sci, noise, scale, te, fwhm, mask)
        res = min(1.0, te / (R0 * fwhm))
        scores[filt] = dict(arc_snr=None if snr is None else round(snr, 2), psf_fwhm_arcsec=round(fwhm, 4),
                            resolution_factor=round(res, 3), score=None if snr is None else round(snr * res, 2),
                            contaminant_mask=mask is not None)
    valid = {f: v for f, v in scores.items() if v['score'] is not None}
    best = max(valid, key=lambda f: valid[f]['score']) if valid else None
    measurable = bool(valid) and max(v['arc_snr'] for v in valid.values()) >= MIN_ARC_SNR
    return dict(theta_e=te, scores=scores, suggested=best if measurable else None,
                measurable=measurable, min_arc_snr=MIN_ARC_SNR, r0=R0)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--sample', type=lens_samples.sample_arg, default=None, help='default: every sample')
    p.add_argument('--lens', default=None)
    a = p.parse_args()
    warnings.simplefilter('ignore')
    out_json = info_json.path(ws_path, 'lens_primary_band.json')
    samples = [a.sample] if a.sample else lens_samples.samples()
    for sample in samples:
        for lens in lens_samples.lenses(sample):
            if a.lens and lens != a.lens:
                continue
            rec = measure(sample, lens)
            if not rec['scores']:
                print(f'{lens}: no stamps (or no theta_e), skipped')
                continue
            # the measured suggestion goes in first, so primary_band() sees it
            for k, v in rec.items():
                info_json.update(out_json, sample, lens, k, v)
            band, source = lens_samples.primary_band(lens, sample)
            info_json.update(out_json, sample, lens, 'primary_band', band)
            info_json.update(out_json, sample, lens, 'primary_band_source', source)
            stamp_rec = dict(lens=lens, sample=sample, primary_band=band, primary_band_source=source,
                             suggested=rec['suggested'], theta_e=rec['theta_e'],
                             scores=rec['scores'], how='scripts/choose_primary_band.py (docstring)')
            with open(os.path.join(ws_path, 'data', 'stamps', sample, lens, 'primary_band.json'), 'w') as f:
                json.dump(stamp_rec, f, indent=4)
            make_band_overview.rerender(sample, lens)          # its star marks the primary band
            row = '  '.join(f'{f} {v["arc_snr"]}/{v["score"]}' for f, v in rec['scores'].items())
            flag = '' if rec['measurable'] else f'  [no band reaches arc S/N {MIN_ARC_SNR:g}: set primary_band by eye]'
            print(f'{lens:18s} theta_E {rec["theta_e"]:.2f}"  suggested {rec["suggested"]}  -> primary {band} ({source})'
                  f'{flag}\n    arc S/N/score: {row}')
    print(f'wrote {out_json} and data/stamps/<sample>/<lens>/primary_band.json')


if __name__ == '__main__':
    sys.exit(main())
