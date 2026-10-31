"""Model-tier PSFs for NIRCam: STPSF at the lens's detector position, rotated into the
North-up output grid, plus the cheap analytic drizzle broadening. Port of the HST repo's
psf_models.py geometry (`_northup_M`, `_resample_centered`, `analytic_drop_broaden`) with
STPSF in place of the STDPSF grids.

Since 2026-10-31 the shipped PSF is STPSF injected into the cal frames at the lens and resampled
as the science (make_psf_inject.py; the HST repo's canonical route, and what the JWST `spike`
package does), with the charge diffusion calibrated against the real stars (psf_star_check.py;
charge_diffusion_sigma below). stpsf_detector_psf is the PSF it injects. The rest of this
module, the analytic tier, is the fallback for a failed injection, and has two caveats:

  * STPSF gives a detector-frame PSF (its diffraction spikes follow the telescope roll), so
    it must be rotated through the exposure's CD matrix into the North-up grid -- done here
    from one contributing _cal file's FITS-approximated WCS (assign_wcs writes a SIP
    approximation into the cal header, good to ~0.01 px over a detector).
  * It omits the resampling broadening (drop size pixfrac x native / output px), which
    `analytic_drop_broaden` approximates (PSFBROAD='analytic'): too narrow, SPT2147-50 F444W
    0.154" against 0.164" injected.

STPSF needs its data files: STPSF_PATH is pointed at data/reference_files/stpsf-data here,
at import (a shell export wins). Until 2026-10-30 only reduce_nircam.setup_crds() set it, which
make_psf.py never calls, so STPSF downloaded into its own default directory, outside the repo.
Download them once with `stpsf.utils.download_data()` or from
https://stpsf.readthedocs.io/en/latest/installation.html (make_psf.py prints the hint).
The measured telescope wavefront for the observation date is loaded when the OPD server is
reachable (`load_wss_opd_by_date`), else STPSF's default OPD is used and PSFOPD says so.
"""
import json
import os
import sys
import warnings

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lens_samples

ws_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('STPSF_PATH', os.path.join(ws_path, 'data', 'reference_files', 'stpsf-data'))


def _northup_M(cd_det, out_scale, oversample, pix_per_src):
    """2x2 map: output-subpixel index offset [i(col); j(row)] -> source-pixel offset
    [dcol; drow], taking a detector-frame PSF into the North-up output grid (CD_out =
    diag(-s, s), matching every resampled product with rotation=0)."""
    s = out_scale / 3600.0
    cd_out = np.array([[-s, 0.0], [0.0, s]])
    return pix_per_src * (np.linalg.inv(np.asarray(cd_det, float)) @ cd_out) / oversample


def _grid_from_M(cx, cy, M, n):
    offs = np.arange(n) - (n - 1) / 2.0
    I, J = np.meshgrid(offs, offs)
    return cx + M[0, 0] * I + M[0, 1] * J, cy + M[1, 0] * I + M[1, 1] * J


def resample_centered(src, src_scale, out_scale, oversample, size, cd_detector=None, det_scale=None):
    """Cubic-resample a detector-frame `src` (arcsec/px `src_scale`) onto the make_psf grid:
    a (size*oversample)^2 stamp at out_scale/oversample arcsec/px, North-up when the
    exposure CD is given. Unit-sum."""
    from photutils.centroids import centroid_com
    from scipy.ndimage import map_coordinates
    src = np.asarray(src, dtype=float)
    ny, nx = src.shape
    py, px = np.unravel_index(np.argmax(src), src.shape)
    win = 15
    y0, x0 = max(0, py - win // 2), max(0, px - win // 2)
    cx, cy = centroid_com(src[y0:y0 + win, x0:x0 + win])     # (x, y): column first
    cx, cy = x0 + cx, y0 + cy
    if not (np.isfinite(cx) and np.isfinite(cy)):
        cx, cy = nx / 2.0, ny / 2.0
    n = size * oversample
    if cd_detector is not None and det_scale is not None:
        M = _northup_M(cd_detector, out_scale, oversample, pix_per_src=det_scale / src_scale)
        xx, yy = _grid_from_M(cx, cy, M, n)
    else:
        step = (out_scale / oversample) / src_scale
        offs = (np.arange(n) - (n - 1) / 2.0) * step
        xx, yy = np.meshgrid(cx + offs, cy + offs)
    stamp = map_coordinates(src, [yy.ravel(), xx.ravel()], order=3, mode='constant', cval=0.0).reshape(n, n)
    stamp = np.clip(stamp, 0.0, None)
    if stamp.sum() > 0:
        stamp /= stamp.sum()
    return stamp


def drop_convolve_box(kernel, box_width_pix):
    """Fourier convolution with an axis-aligned box of (fractional) width `box_width_pix`."""
    if box_width_pix <= 0:
        return np.asarray(kernel, dtype=float)
    kernel = np.asarray(kernel, dtype=float)
    ny, nx = kernel.shape
    fy = np.fft.fftfreq(ny)[:, None]
    fx = np.fft.rfftfreq(nx)[None, :]
    return np.fft.irfft2(np.fft.rfft2(kernel) * np.sinc(box_width_pix * fy) * np.sinc(box_width_pix * fx), s=kernel.shape)


def analytic_drop_broaden(kernel, pixfrac, native_scale, out_scale, n_frames=1):
    """Approximate the resample step's point-source broadening on a North-up, output-scale
    kernel: a drop box of pixfrac*native/out output px, shrunk by 1/sqrt(n_frames) for the
    dither-phase averaging (calibrated on HST re-drizzle injections to 0.01 px). Returns
    (broadened unit-sum kernel, box width used)."""
    box_width = (pixfrac * native_scale / out_scale) / np.sqrt(max(1, n_frames))
    out = np.clip(drop_convolve_box(kernel, box_width), 0.0, None)
    if out.sum() > 0:
        out /= out.sum()
    return out, box_width


def representative_cal(sample, lens, filt):
    """One contributing _cal.fits whose footprint contains the lens (the detector the lens
    fell on in that exposure), with its FITS-approx WCS. Returns (path, header, WCS) or None."""
    import glob
    from astropy.io import fits
    from astropy.wcs import WCS
    coord = lens_samples.coord(lens, sample)
    cal_dir = os.path.join(ws_path, 'data', 'stage2', sample, lens, filt)
    for f in sorted(glob.glob(os.path.join(cal_dir, '*_cal.fits'))):
        with fits.open(f) as h:
            hdr = h['SCI'].header
            phdr = h[0].header
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                w = WCS(hdr)
            x, y = w.world_to_pixel(coord)
            if 0 <= x < hdr['NAXIS1'] and 0 <= y < hdr['NAXIS2']:
                return f, phdr, hdr, w, (float(x), float(y))
    return None


def model_psf(sample, lens, filt, oversample, size, out_scale, fov_pad=1.5):
    """STPSF NIRCam PSF at the lens position in a representative exposure, as a
    (size*oversample)^2 North-up stamp at out_scale/oversample arcsec/px (make_psf's
    convention). Returns (stamp, info dict)."""
    rep = representative_cal(sample, lens, filt)
    if rep is None:
        raise RuntimeError(f'no stage2 cal file containing {lens} for {filt}; run reduce_nircam.py first')
    cal_path, phdr, sci_hdr, w, (x, y) = rep
    cd = w.wcs.cd if w.wcs.has_cd() else w.pixel_scale_matrix
    det_scale = lens_samples.NATIVE_SCALE[lens_samples.channel(filt)]
    fov_pix = int(np.ceil(size * out_scale / det_scale * fov_pad)) | 1
    src, info = stpsf_detector_psf(filt, phdr['DETECTOR'], x, y, phdr.get('DATE-BEG', phdr.get('DATE-OBS')), fov_pix)
    stamp = resample_centered(src, det_scale / info['stpsf_oversample'], out_scale, oversample, size,
                              cd_detector=cd, det_scale=det_scale)
    return stamp, dict(cal=os.path.basename(cal_path), **info)


STPSF_OVERSAMPLE = 4
OPD_TIMEOUT = 120      # s, per network read of the measured-OPD fetch
CALIBRATION_JSON = os.path.join(ws_path, 'info', 'overrides', 'psf_model_calibration.json')


def charge_diffusion_sigma(filt):
    """The calibrated STPSF charge-diffusion Gaussian sigma (arcsec) for `filt`, or None for
    STPSF's own default (NIRCam SW 0.0062", LW 0.018", which STPSF calls placeholders).
    Measured by psf_star_check.py --calibrate against real stars, each injected beside its
    twin, and kept in info/overrides/psf_model_calibration.json (`charge_diffusion_sigma`)."""
    if not os.path.exists(CALIBRATION_JSON):
        return None
    with open(CALIBRATION_JSON) as f:
        cal = json.load(f).get('charge_diffusion_sigma', {})
    v = cal.get(filt, cal.get(lens_samples.channel(filt)))
    return None if v is None else float(v)


def stpsf_detector_psf(filt, detector, x, y, date, fov_pixels, oversample=STPSF_OVERSAMPLE,
                       charge_diffusion=None):
    """STPSF's OVERDIST PSF for `detector` ('NRCB1', or the header's 'NRCBLONG') at detector
    pixel (x, y): (fov_pixels*oversample)^2, unit sum, the star at the array centre
    ((n-1)/2 in each axis, the centre of the central detector pixel; DET_DIST is exactly its
    oversample-block sum). Distortion, charge diffusion and IPC are included -- IPC rightly,
    since Detector1's ipc step is skipped for NIRCam, so the cal frames carry it. Charge
    diffusion is the calibrated width (charge_diffusion_sigma) unless `charge_diffusion` is
    given ('default' for STPSF's own). The measured OPD closest to `date` is used when the
    server is reachable. Returns (array, info)."""
    import stpsf
    nrc = stpsf.NIRCam()
    nrc.filter = filt
    cd = charge_diffusion_sigma(filt) if charge_diffusion is None else charge_diffusion
    if cd not in (None, 'default'):
        nrc.options['charge_diffusion_sigma'] = float(cd)
    nrc.detector = str(detector).upper().replace('LONG', '5')
    nrc.detector_position = (x, y)
    opd = 'default'
    if date:
        # the MAST query behind it has no timeout of its own: a stalled read hung a B1938 build
        # for 20 min with no CPU (2026-10-30), so bound it and retry before falling back
        import socket
        saved = socket.getdefaulttimeout()
        socket.setdefaulttimeout(OPD_TIMEOUT)
        try:
            for attempt in range(3):
                try:
                    nrc.load_wss_opd_by_date(str(date), choice='closest', verbose=False)
                    opd = f'wss:{date}'
                    break
                except Exception as exc:
                    print(f'  WARNING: measured OPD unavailable ({exc.__class__.__name__}), try {attempt + 1}/3')
        finally:
            socket.setdefaulttimeout(saved)
        if opd == 'default':
            print('  WARNING: default OPD used')
    psf = nrc.calc_psf(oversample=oversample, fov_pixels=fov_pixels)
    src = np.asarray(psf['OVERDIST'].data, float)
    info = dict(detector=nrc.detector, detector_position=[float(x), float(y)], opd=opd,
                stpsf_version=stpsf.__version__, stpsf_oversample=oversample, fov_pixels=fov_pixels,
                charge_diffusion_sigma=None if cd in (None, 'default') else float(cd))
    return src / src.sum(), info
