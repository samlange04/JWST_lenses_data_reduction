"""Model-tier PSFs for NIRCam: STPSF at the lens's detector position, rotated into the
North-up output grid, plus the cheap analytic drizzle broadening. Port of the HST repo's
psf_models.py geometry (`_northup_M`, `_resample_centered`, `analytic_drop_broaden`) with
STPSF in place of the STDPSF grids.

The empirical ePSF built from the mosaic's own stars (make_psf.py) is the preferred tier,
exactly as in the HST repo: it is already the resampled, North-up PSF the data carry. This
module is the FALLBACK for star-poor fields, and the same two caveats apply as for HST:

  * STPSF gives a detector-frame PSF (its diffraction spikes follow the telescope roll), so
    it must be rotated through the exposure's CD matrix into the North-up grid -- done here
    from one contributing _cal file's FITS-approximated WCS (assign_wcs writes a SIP
    approximation into the cal header, good to ~0.01 px over a detector).
  * It omits the resampling broadening (drop size pixfrac x native / output px). The honest
    fix is injection into the cal frames and a re-run of resample (the HST repo's
    make_psf_inject.py; the JWST `spike` package does the same); until that is ported,
    `analytic_drop_broaden` is applied and the kernel is tagged PSFBROAD='analytic'.

STPSF needs its data files: STPSF_PATH is pointed at data/reference_files/stpsf-data by
reduce_nircam.setup_crds(); download them once with `stpsf.utils.download_data()` or from
https://stpsf.readthedocs.io/en/latest/installation.html (make_psf.py prints the hint).
The measured telescope wavefront for the observation date is loaded when the OPD server is
reachable (`load_wss_opd_by_date`), else STPSF's default OPD is used and PSFOPD says so.
"""
import os
import sys
import warnings

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lens_samples

ws_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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
    import stpsf
    rep = representative_cal(sample, lens, filt)
    if rep is None:
        raise RuntimeError(f'no stage2 cal file containing {lens} for {filt}; run reduce_nircam.py first')
    cal_path, phdr, sci_hdr, w, (x, y) = rep
    cd = w.wcs.cd if w.wcs.has_cd() else w.pixel_scale_matrix
    ch = lens_samples.channel(filt)
    det_scale = lens_samples.NATIVE_SCALE[ch]

    nrc = stpsf.NIRCam()
    nrc.filter = filt
    nrc.detector = str(phdr['DETECTOR']).upper().replace('LONG', '5')
    nrc.detector_position = (x, y)
    opd = 'default'
    date = phdr.get('DATE-BEG', phdr.get('DATE-OBS'))
    if date:
        try:
            nrc.load_wss_opd_by_date(date, choice='closest', verbose=False)
            opd = f'wss:{date}'
        except Exception as exc:
            print(f'  WARNING: measured OPD unavailable ({exc.__class__.__name__}); default OPD used')
    fov_pix = int(np.ceil(size * out_scale / det_scale * fov_pad)) | 1
    stpsf_os = 4
    psf = nrc.calc_psf(oversample=stpsf_os, fov_pixels=fov_pix)
    # OVERDIST: oversampled, distorted, charge diffusion included, before IPC (IPC is only
    # applied in the detector-sampled DET_DIST).
    src = np.asarray(psf['OVERDIST'].data, float)
    stamp = resample_centered(src, det_scale / stpsf_os, out_scale, oversample, size,
                              cd_detector=cd, det_scale=det_scale)
    info = dict(cal=os.path.basename(cal_path), detector=nrc.detector, detector_position=[x, y],
                opd=opd, stpsf_version=stpsf.__version__, stpsf_oversample=stpsf_os, fov_pixels=fov_pix)
    return stamp, info
