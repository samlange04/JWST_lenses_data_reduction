#!/usr/bin/env python
"""
The injected PSF model against the real PSF stars, one by one: check it, calibrate it, and
measure its error.

    uv run python scripts/psf_star_check.py --lens SPT2147-50 --filt F444W   # one band
    uv run python scripts/psf_star_check.py --calibrate                      # charge diffusion
    uv run python scripts/psf_star_check.py --error-maps                     # model error maps
    bash scripts/run_psf_star_check_all.sh                                    # every band

Band mode. The band's PSF stars are make_psf.prepare_field's selection, the one the
empirical check uses. STPSF is injected at each star's own sky position into every cal frame
and resampled as the science was (make_psf_inject.injected_mosaic). Each real star therefore
has a noiseless twin at the same sub-pixel position, on the same frames, with the same ivm
weights, and nothing else differs. That makes it a like-for-like test of the model that no
ePSF build can give:
  * an ePSF reduction carries its own biases (block summing, smoothing, pedestal);
  * in the undersampled bands a bright star's resampled core is not the lens's (AGENTS.md *PSF*).
Per star it records:
  * the Gaussian FWHM of the real star and of its twin, and their ratio;
  * the peak fractions;
  * the twin's amplitude fit (real = a * twin + b in the core);
  * `extended`, set when the real star is more than EXTENDED_RATIO broader than its twin
    (a compact galaxy or a blend).
Crops of the real star, its twin and the ERR map go to data/psf/<s>/<l>/<F>/star_check.npz;
the summary goes to info/provenance/lens_psf_starcheck.json.

--calibrate. Pools every band's crops per filter (stars with real/twin FWHM within
EXTENDED_RATIO either way and peak S/N >= CAL_MIN_SNR). Each star's best extra Gaussian blur sigma_x minimises the core chi^2 of real = a * (twin * G)
+ b; the filter's sigma_x is the median over its stars, so the brightest star does not set it.
It then writes the next width per channel (charge diffusion is a detector property) to
info/overrides/psf_model_calibration.json, which psf_models.stpsf_detector_psf applies. The
first pass adds the residual in quadrature; later passes take the secant zero of the residual^2
against width^2 through the last two passes, logged in `iterations`. Re-run the band check
and --calibrate until the residual is ~1 mas.
STPSF's own widths (SW 0.0062", LW 0.018") are, in its words, placeholders "to be updated
based on comparisons with data and ePSFs". A blur on the resampled star stands in for one on
the detector, which holds while sigma_x is small next to the pixel; pass 2 (a re-run after
calibration) checks that the ratio comes out at 1.

--error-maps. Per filter, over the same stars after calibration, the per-pixel rms residual
of the flux-normalised real star about its twin, beyond its own noise (sigma-clipped mean of
r^2 - e^2), goes to data/psf/_model_error/<FILT>.fits; the integrated fraction goes to the
calibration JSON. make_psf.py ships it as the injected kernel's error map
(err_method 'model_vs_stars'). It is per filter, not per lens, and at the stars' sub-pixel
phases rather than the kernel's.
"""
import argparse
import glob
import io
import contextlib
import os
import sys
import time
import warnings

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import info_json
import lens_samples
import make_psf
import make_psf_inject
import psf_models

ws_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

EXTENDED_RATIO = 1.15        # real/twin FWHM above this: not a point source (= make_psf's gate)
CROP = {'SW': 41, 'LW': 31}  # star crops, output px (1.2" SW, 1.9" LW): the trimmed kernels' extent
FWHM_BOX = {'SW': 21, 'LW': 15}   # the FWHM fit's box (small, so neighbours stay out)
CAL_MIN_SNR = 100.0          # peak S/N of a star used for calibration and error maps
SIGMA_GRID_MAS = np.arange(0.0, 40.01, 1.0)
STPSF_DEFAULT_CD = {'SW': 0.0062, 'LW': 0.018}   # stpsf.constants, NIRCam (arcsec)


def ns(filt):
    a = argparse.Namespace(variant='', method='auto', filt=filt)
    for k in ('threshold_scale', 'fwhm', 'psf_fwhm', 'min_sep', 'crowd_sep_frac', 'lens_mask_radius',
              'max_stars', 'min_stars', 'star_size', 'oversample', 'kernel_size'):
        setattr(a, k, None)
    return a


def blur(img, sigma_px):
    """`img` convolved with a Gaussian of `sigma_px`, exactly, through its Fourier transfer
    function: scipy.ndimage.gaussian_filter truncates its kernel at 4 sigma and so does nothing
    at all below sigma ~0.13 px and only crudely below ~0.5 px, which a first calibration
    (2026-10-31) mistook for a blur of 0.33 px."""
    if sigma_px <= 0:
        return img
    ky = np.fft.fftfreq(img.shape[0])[:, None]
    kx = np.fft.fftfreq(img.shape[1])[None, :]
    return np.real(np.fft.ifft2(np.fft.fft2(img) * np.exp(-2 * np.pi ** 2 * sigma_px ** 2 * (kx ** 2 + ky ** 2))))


def core_fit(r, t, e, rad, r_fit):
    """Weighted least squares real = a * twin + b within r_fit px: (a, b, chi2, n)."""
    m = (rad <= r_fit) & np.isfinite(r) & (e > 0)
    w = 1.0 / e[m] ** 2
    A = np.column_stack([t[m], np.ones(m.sum())])
    coef = np.linalg.lstsq(A * np.sqrt(w)[:, None], r[m] * np.sqrt(w), rcond=None)[0]
    chi2 = float(np.sum(w * (r[m] - A @ coef) ** 2))
    return float(coef[0]), float(coef[1]), chi2, int(m.sum())


def band(sample, lens, filt, charge_diffusion=None):
    from astropy.io import fits
    t0 = time.time()
    ch = lens_samples.channel(filt)
    with contextlib.redirect_stdout(io.StringIO()):
        fld = make_psf.prepare_field(sample, lens, filt, ns(filt))
    if fld is None:
        print(f'{lens} {filt}: no mosaic')
        return
    tbl, sc = fld['stars_tbl'], fld['scale']
    rec = dict(n_stars=len(tbl), scale=sc)
    if len(tbl) == 0:
        print(f'{lens} {filt}: no PSF stars')
        info_json.update(info_json.path(ws_path, 'lens_psf_starcheck.json'), sample, lens, filt, rec)
        return
    size = int(fld['params']['star_size']) | 1
    x, y = np.asarray(tbl['x'], float), np.asarray(tbl['y'], float)
    twin, _, inj = make_psf_inject.injected_mosaic(sample, lens, filt, fld['wcs'].pixel_to_world(x, y), size,
                                                   charge_diffusion=charge_diffusion)
    err = np.nan_to_num(np.asarray(fits.getdata(fld['i2d'], 'ERR'), float), nan=0.0)
    C, B = CROP[ch], FWHM_BOX[ch]
    yy, xx = np.mgrid[:C, :C]
    rad = np.hypot(xx - C // 2, yy - C // 2)
    r_fit = 3.0 * fld['params']['psf_fwhm']
    R, T, E, stars = [], [], [], []
    for xi, yi in zip(x, y):
        cx, cy = int(round(xi)), int(round(yi))
        r = make_psf._crop_centered(fld['data'], C, cx, cy)
        t = make_psf._crop_centered(twin, C, cx, cy)
        e = make_psf._crop_centered(err, C, cx, cy)
        a, b, chi2, npx = core_fit(r, t, e, rad, r_fit)
        rb, tb = (make_psf._crop_centered(v, B, C // 2, C // 2) for v in (r - b, t))
        fr, ft = make_psf.measure_fwhm(rb / rb.sum()), make_psf.measure_fwhm(tb / tb.sum())
        ratio = fr / ft if fr and ft else None
        peak_snr = float(np.max((r - b)[rad <= 1.5] / np.maximum(e[rad <= 1.5], 1e-30)))
        stars.append(dict(x=round(float(xi), 2), y=round(float(yi), 2), flux=round(a * float(t.sum()), 4),
                          peak_snr=round(peak_snr, 1), fwhm_real=round(fr * sc, 5) if fr else None,
                          fwhm_twin=round(ft * sc, 5) if ft else None,
                          ratio=round(ratio, 4) if ratio else None,
                          peak_frac_real=round(float((r - b).max() / max((r - b)[rad <= C // 2].sum(), 1e-30)), 4),
                          peak_frac_twin=round(float(t.max() / t[rad <= C // 2].sum()), 4),
                          chi2_per_px=round(chi2 / max(npx - 2, 1), 3),
                          extended=bool(ratio is not None and ratio > EXTENDED_RATIO)))
        R.append(r); T.append(t); E.append(e)
    cd = inj.get('charge_diffusion_sigma') or STPSF_DEFAULT_CD[ch]
    out = os.path.join(ws_path, 'data', 'psf', sample, lens, filt)
    os.makedirs(out, exist_ok=True)
    np.savez_compressed(os.path.join(out, 'star_check.npz'), real=np.array(R, np.float32), twin=np.array(T, np.float32),
                        err=np.array(E, np.float32), ratio=np.array([s['ratio'] or np.nan for s in stars]),
                        peak_snr=np.array([s['peak_snr'] for s in stars]),
                        extended=np.array([s['extended'] for s in stars]),
                        scale=sc, charge_diffusion=cd, r_fit=r_fit)
    pts = [s['ratio'] for s in stars if s['ratio'] and not s['extended']]
    rec.update(stars=stars, n_extended=sum(s['extended'] for s in stars), n_point=len(pts),
               median_ratio=round(float(np.median(pts)), 4) if pts else None,
               charge_diffusion_sigma=cd, stpsf_version=inj.get('stpsf_version'),
               seconds=round(time.time() - t0, 1))
    info_json.update(info_json.path(ws_path, 'lens_psf_starcheck.json'), sample, lens, filt, rec)
    print(f'{lens} {filt}: {len(stars)} stars ({rec["n_extended"]} extended), real/twin FWHM median '
          f'{rec["median_ratio"]} (charge diffusion {cd * 1e3:.1f} mas), {rec["seconds"]:.0f}s')


def load_checks(snr_min=CAL_MIN_SNR):
    """Every band's star_check.npz, pooled per filter: {filt: list of (r, t, e, scale, cd, r_fit)}
    for the non-extended stars with peak S/N >= snr_min."""
    out = {}
    for f in sorted(glob.glob(os.path.join(ws_path, 'data', 'psf', '*', '*', 'F*', 'star_check.npz'))):
        filt = os.path.basename(os.path.dirname(f))
        z = np.load(f)
        for i in range(len(z['real'])):
            # extended (a galaxy), or much NARROWER than its twin (a defect: lens B's F277W stars
            # at the survey edge come out at 0.59), or too faint to constrain the core
            if (z['extended'][i] or not np.isfinite(z['ratio'][i]) or z['ratio'][i] < 1 / EXTENDED_RATIO
                    or z['peak_snr'][i] < snr_min):
                continue
            out.setdefault(filt, []).append((z['real'][i].astype(float), z['twin'][i].astype(float),
                                             z['err'][i].astype(float), float(z['scale']),
                                             float(z['charge_diffusion']), float(z['r_fit'])))
    return out


def calibrate():
    cal = info_json.load(psf_models.CALIBRATION_JSON)
    cds, fits_, per_channel = {}, {}, {}
    for filt, stars in sorted(load_checks().items()):
        best = []
        for r, t, e, sc, cd, r_fit in stars:
            C = r.shape[0]
            yy, xx = np.mgrid[:C, :C]
            rad = np.hypot(xx - C // 2, yy - C // 2)
            chi = np.array([core_fit(r, blur(t, smas / 1e3 / sc), e, rad, r_fit)[2]
                            for smas in SIGMA_GRID_MAS])
            k = int(np.argmin(chi))
            b = SIGMA_GRID_MAS[k]
            if 0 < k < len(chi) - 1:             # parabolic refinement
                c0, c1, c2 = chi[k - 1], chi[k], chi[k + 1]
                b += 0.5 * (c0 - c2) / (c0 - 2 * c1 + c2) * (SIGMA_GRID_MAS[1] - SIGMA_GRID_MAS[0])
            best.append(b)
        best = np.array(best)
        med = float(np.median(best))
        cd_used = stars[0][4]
        new = float(np.hypot(cd_used, med / 1e3))
        per_channel.setdefault(lens_samples.channel(filt), (cd_used, []))[1].extend(best)
        fits_[filt] = dict(n_stars=len(stars), sigma_extra_mas=round(med, 2),
                           sigma_extra_16_84_mas=[round(float(v), 2) for v in np.percentile(best, [16, 84])],
                           sigma_extra_sem_mas=round(float(1.2533 * best.std(ddof=1) / np.sqrt(len(best))), 2)
                           if len(best) > 1 else None,
                           charge_diffusion_used=cd_used)
        print(f'{filt}: {len(stars)} stars, extra blur {med:.1f} mas (16-84% {np.percentile(best, 16):.1f}-'
              f'{np.percentile(best, 84):.1f}) -> charge diffusion {cd_used * 1e3:.1f} -> {new * 1e3:.1f} mas')
    # Charge diffusion is a detector property, and the fits say so: the extra blur is the same in
    # every filter of a channel and twice as large in LW, the ratio of the pixel pitches. So one
    # width per channel (the median over all its stars); the per-filter fits are the record.
    # The blur on the resampled star stands in for one on the detector only approximately, so the
    # calibration iterates: each pass's twins are made with the last width, and its residual blur
    # is logged in `iterations`. With one pass the residual adds in quadrature; with two or more
    # the next width is the secant zero of residual^2 against width^2 through the last two.
    hist = cal.get('iterations', {})
    for ch, (cd_used, best) in sorted(per_channel.items()):
        med = float(np.median(best))
        h = [it for it in hist.get(ch, []) if abs(it['charge_diffusion_used'] - cd_used) > 1e-7]
        h.append(dict(charge_diffusion_used=cd_used, sigma_extra_mas=round(med, 2), n_stars=len(best)))
        hist[ch] = h
        if len(h) >= 2:
            (c0, e0), (c1, e1) = [(it['charge_diffusion_used'] ** 2, (it['sigma_extra_mas'] / 1e3) ** 2) for it in h[-2:]]
            new = float(np.sqrt(c1 - e1 * (c1 - c0) / (e1 - e0))) if e1 != e0 else float(np.sqrt(c1 + e1))
        else:
            new = float(np.hypot(cd_used, med / 1e3))
        cds[ch] = round(new, 5)
        fits_[ch] = dict(n_stars=len(best), sigma_extra_mas=round(med, 2), charge_diffusion_used=cd_used,
                         sigma_extra_detector_px=round(med / 1e3 / lens_samples.NATIVE_SCALE[ch], 3))
        print(f'{ch}: {len(best)} stars, residual blur {med:.1f} mas = {fits_[ch]["sigma_extra_detector_px"]:.2f} '
              f'detector px at charge diffusion {cd_used * 1e3:.2f} mas -> {cds[ch] * 1e3:.2f} mas')
    cal['iterations'] = hist
    cal['charge_diffusion_sigma'] = cds
    cal['calibration_fit'] = fits_
    cal['_how'] = ('psf_star_check.py --calibrate: each real PSF star against its noiseless STPSF twin '
                   'injected at the same position into the same cal frames (non-extended stars, peak S/N >= '
                   f'{CAL_MIN_SNR:g}): per star the extra Gaussian blur of the twin that minimises the core '
                   'chi^2, the median over the filter\'s stars added in quadrature to the charge diffusion '
                   'the twins were made with.')
    with open(psf_models.CALIBRATION_JSON, 'w') as f:
        import json
        json.dump(cal, f, indent=4)
    print(f'wrote {psf_models.CALIBRATION_JSON}')


def error_maps():
    from astropy.io import fits
    from astropy.stats import sigma_clip
    cal = info_json.load(psf_models.CALIBRATION_JSON)
    os.makedirs(make_psf.MODEL_ERROR_DIR, exist_ok=True)
    errs = {}
    for filt, stars in sorted(load_checks().items()):
        res, var = [], []
        for r, t, e, sc, cd, r_fit in stars:
            C = r.shape[0]
            yy, xx = np.mgrid[:C, :C]
            rad = np.hypot(xx - C // 2, yy - C // 2)
            a, b, _, _ = core_fit(r, t, e, rad, r_fit)
            tot = t.sum()
            res.append(((r - b) / a - t) / tot)               # unit-sum kernel units
            var.append((e / (a * tot)) ** 2)
        res, var = np.array(res), np.array(var)
        sq = sigma_clip(res ** 2 - var, sigma=3.0, axis=0)
        em = np.sqrt(np.clip(np.ma.mean(sq, axis=0).filled(0.0), 0.0, None))
        hdr = fits.Header()
        hdr['PSFFILT'] = filt
        hdr['PSFERR'] = ('model_vs_stars', 'rms real-star residual about its injected twin')
        hdr['PSFNSTAR'] = (len(stars), 'stars (non-extended, peak S/N >= %g)' % CAL_MIN_SNR)
        fits.PrimaryHDU(em.astype(np.float32), hdr).writeto(os.path.join(make_psf.MODEL_ERROR_DIR, f'{filt}.fits'),
                                                            overwrite=True)
        errs[filt] = dict(n_stars=len(stars), err_frac=round(float(np.sqrt(np.sum(em ** 2))), 5))
        print(f'{filt}: {len(stars)} stars, model error fraction {errs[filt]["err_frac"]:.4f}')
    cal['model_error'] = errs
    with open(psf_models.CALIBRATION_JSON, 'w') as f:
        import json
        json.dump(cal, f, indent=4)
    print(f'wrote {psf_models.CALIBRATION_JSON} and {make_psf.MODEL_ERROR_DIR}/<FILT>.fits')


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--lens')
    p.add_argument('--filt')
    p.add_argument('--sample')
    p.add_argument('--charge-diffusion', default=None,
                   help="'default' for STPSF's own width, a value in arcsec, or none for the calibrated one")
    p.add_argument('--calibrate', action='store_true')
    p.add_argument('--error-maps', action='store_true')
    a = p.parse_args()
    warnings.simplefilter('ignore')
    if a.calibrate:
        return calibrate()
    if a.error_maps:
        return error_maps()
    if not (a.lens and a.filt):
        p.error('give --lens and --filt, or --calibrate / --error-maps')
    cd = a.charge_diffusion
    if cd not in (None, 'default'):
        cd = float(cd)
    band(a.sample or lens_samples.sample_of(a.lens), a.lens, lens_samples.canonical_filter(a.filt), cd)


if __name__ == '__main__':
    sys.exit(main())
