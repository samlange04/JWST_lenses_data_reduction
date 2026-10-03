#!/usr/bin/env python
"""
Build a per-lens, per-filter PSF from the i2d mosaic for strong-lens modelling.

    uv run python scripts/make_psf.py --lens SPT2147-50 --filt F444W

Port of the HST repo's make_psf.py. The empirical route (default) detects isolated field
stars in the full mosaic (DAOStarFinder on a Background2D-subtracted image, with the lens, the
no-coverage pixels and a frame-edge margin masked), gates them on peak S/N, fitted FWHM,
ellipticity, crowding and a flux floor, builds an oversampled photutils ePSF, validates it
(peak centred, wings clean), bins it to the mosaic scale, subtracts the wing pedestal and
writes:

    data/psf/<sample>/<lens>/<FILT>/psf_kernel.fits [+ psf_kernel_err.fits]  psf.png
    data/cutouts/<sample>/<lens>/<FILT>/cutout_psf.fits [+ cutout_psf_err.fits]

the second being the amplitude-trimmed modelling kernel beside the science stamp. With too
few usable stars (< --min-stars, default 3) or a poor empirical build, --method auto falls
back to the STPSF model at the lens's detector position (scripts/psf_models.py), rotated to
North-up through a contributing _cal file's WCS and broadened by the analytic drop box --
tagged PSFMETH='model_stpsf', PSFBROAD='analytic'. The PSF error map (bootstrap over stars,
jackknife below 6) is the empirical tier's only. Per-lens overrides live in
info/psf_stars.json (include/exclude stars, method, any tunable), as in the HST repo.

NIRCam specifics (vs HST): the SW bands at 0.03" are undersampled (FWHM 1.3-2.2 px), so the
per-filter psf_fwhm comes from the JDox PSF table scaled to the output pixel; there is no
mosaic-peak saturation gate (saturated cores are NaN holes in an i2d); there is one pass, so
the kernel is simply cutout_psf.fits.
"""

import argparse
import glob
import json
import os
import sys
import warnings

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.modeling import fitting, models
from astropy.nddata import NDData, block_reduce
from astropy.stats import sigma_clipped_stats
from astropy.table import Table
from astropy.visualization import (AsinhStretch, ImageNormalize, LinearStretch,
                                   LogStretch, PercentileInterval)
from astropy.wcs import WCS
from astropy.wcs.utils import proj_plane_pixel_scales
import astropy.units as u
from photutils.background import Background2D, MedianBackground
from photutils.centroids import centroid_com
from photutils.detection import DAOStarFinder
from photutils.psf import EPSFBuilder, extract_stars

ws_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ws_path, 'info'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lens_samples as mast_target_names
# Reuse the canonical product locator and the coordinate resolver rather than
# re-implementing the instrument-varying prefix/suffix globbing or the per-sample coords
# table lookup (SLACS in slacs_coords.py, BELLS GALLERY in gallery_coords.py). Importing
# make_cutouts is safe: its work is under __main__.
import psf_models
import info_json
import cutout_paths


# ── Per-instrument defaults ─────────────────────────────────────────────────────
# Keyed on a normalised instrument label (see instrument_key). WFPC2's drizzled primary
# header records DETECTOR=PC (the aperture, not the chip -- the lens is on WF3), so WFPC2
# is keyed on INSTRUME alone. Every value here is overridable by info/psf_stars.json and
# then by an explicit CLI flag; the drizzled pixel scale is read from the WCS, not stored.
_BASE = dict(
    threshold_scale=5.0,     # detection threshold = this x sigma-clipped background std
    min_stars=3,             # fewer usable stars than this -> model fallback
    kernel_size=31,          # odd size of the delivered image-scale kernel (pixels)
    lens_mask_radius=5.0,    # arcsec circle around the deflector, masked out of detection
    maxiters=15,             # EPSFBuilder iterations
    fwhm_tol_lo=0.75,        # per-candidate fitted FWHM must exceed this x psf_fwhm
    fwhm_tol_hi=1.4,         # ...and stay below this x psf_fwhm (rejects galaxies / CRs)
    max_ellip=0.15,          # reject elongated objects (edge-on galaxies, streaks)
    min_snr=30.0,            # absolute peak-S/N floor for a PSF-grade star. A 5-sigma
                             # DAO detection is not a PSF star: on star-poor fields the
                             # only round detections are ~5-sigma noise blobs (measured
                             # peak-S/N 4-6 on J0252 F606W) that build a pure-noise ePSF.
                             # This absolute gate drops them so the field goes to the
                             # model, while real stars (peak-S/N hundreds) are kept.
    flux_floor_frac=0.05,    # drop stars fainter than this x the brightest kept star:
                             # EPSFBuilder normalises each star by its flux, so a faint
                             # star's background noise is amplified into the ePSF wings.
    pedestal_bad=3.0e-3,     # empirical wing pedestal (median of the outer annulus / peak)
                             # above this -> poor build, fall back to the model. Chosen to
                             # pass every ACS/F555W empirical build (worst ~2.6e-4) and the
                             # good F160W builds (<=1.2e-3) while dropping bad ones (J0936
                             # 6.6e-3). See wing_stats / the hybrid gate in main().
    scatter_bad=3.0e-3,      # empirical wing scatter (std of the outer annulus / peak)
                             # above this -> poor build. Worst clean ACS ~2.0e-3; catches
                             # the noisy F160W builds (J0936 7.8e-3, J0946 6.6e-3).
    crowd_sep_frac=1.0,      # candidate-pair rejection radius, as a fraction of star_size
                             # (the extract_stars() stamp width). DAOStarFinder's own
                             # min_separation (below, ~0.5x star_size) only keeps it from
                             # double-detecting one blended peak; it does not know the
                             # downstream stamp size, so two accepted detections can still
                             # sit close enough for their star_size stamps to overlap and
                             # contaminate each other's wings. 1.0 = stamps never overlap.
)
# `fwhm` is the DAOStarFinder detection kernel; `psf_fwhm` is the true stellar PSF FWHM
# (pixels, at the drizzled scale) that the per-candidate shape cut selects around --
# distinct because detection tolerates a coarser kernel than the star/galaxy separation.
# oversample=2: SLACS fields yield only ~10-20 usable stars, so a 4x-oversampled ePSF
# has too many pixels per constraining star and comes out noisy. 2x is well-matched to
# these (near-)critically-sampled drizzled grids and much more robust; raise per lens via
# --oversample or info/psf_stars.json where a field is unusually star-rich.
_INSTR = {
    # NIRCam at the repo's output scales (SW 0.03", LW 0.06"; reduce_nircam.DEFAULT_SCALE).
    # psf_fwhm is the per-filter PSF FWHM in OUTPUT pixels (JDox NIRCam point-spread
    # functions: F115W 0.040", F150W 0.050", F200W 0.066", F277W 0.092", F356W 0.116",
    # F444W 0.145"); resolve_params picks the filter's value from _PSF_FWHM_ARCSEC below.
    # The SW bands are undersampled (1.3-2.2 px), so oversample=2 is the floor, not a
    # choice. star_size is set so the stamp spans ~2.4" at either scale (SW 81 px, LW
    # 41 px): subtract_pedestal reads its "background" from the outer quarter of the
    # stamp, and at 41 px SW that annulus (0.45-0.6") still holds real PSF wing light
    # (~3e-4 of peak per pixel), which was being subtracted -- the B1938+666 F115W kernel
    # came out with 2% of its flux in negative wings and 6% too much in the core
    # (2026-10-03). At 81 px the annulus sits at 0.9-1.2" and the pedestal is < 1e-4.
    'NIRCAM/SW': dict(fwhm=2.0, psf_fwhm=1.7, oversample=2, star_size=81, max_stars=25,
                      min_sep=25.0, sharplo=0.2, sharphi=1.0, roundlo=-0.7, roundhi=0.7),
    'NIRCAM/LW': dict(fwhm=2.2, psf_fwhm=2.0, oversample=2, star_size=41, max_stars=25,
                      min_sep=25.0, sharplo=0.2, sharphi=1.0, roundlo=-0.7, roundhi=0.7),
}
_PSF_FWHM_ARCSEC = {'F070W': 0.030, 'F090W': 0.034, 'F115W': 0.040, 'F150W': 0.050, 'F200W': 0.066,
                    'F277W': 0.092, 'F356W': 0.116, 'F444W': 0.145}

# Saturation: NIRCam saturated pixels are flagged in the ramp (DQ SATURATED -> DO_NOT_USE on
# full saturation) and come out of resample as NaN holes, which the shape gate rejects; a
# partially saturated star has its first groups used and a correct slope. No mosaic-peak
# gate is possible in MJy/sr without the per-frame exposure, so None (as for WFC3/IR).
_SATLEVEL = {'NIRCAM/SW': None, 'NIRCAM/LW': None}
SAT_PEAK_FRAC = 0.5


def saturation_peak(inst_key, sci_hdr, overrides):
    """Mosaic peak (per-second units) above which a candidate is saturated, or None."""
    if 'max_peak' in overrides:
        return overrides['max_peak']
    sat = overrides.get('satlevel', _SATLEVEL.get(inst_key))
    dexp = [v for k, v in sci_hdr.items() if k.startswith('D') and k.endswith('DEXP')]
    if not sat or not dexp:
        return None
    return SAT_PEAK_FRAC * float(sat) / max(float(v) for v in dexp)


def instrument_key(hdr):
    """Normalised instrument label for the defaults table.

    WFPC2's drizzled primary header carries DETECTOR=PC (the full-field aperture centres
    the target on WF3; DETECTOR names the aperture, not the chip), so key WFPC2 on
    INSTRUME alone. ACS/WFC3 use INSTRUME/DETECTOR.
    """
    ch = str(hdr.get('CHANNEL', '')).strip().upper()
    if ch in ('SHORT', 'LONG'):
        return 'NIRCAM/SW' if ch == 'SHORT' else 'NIRCAM/LW'
    filt = str(hdr.get('FILTER', '')).strip().upper()
    return f'NIRCAM/{lens_samples.channel(filt)}'


def resolve_params(inst_key, json_entry, cli):
    """Merge parameter sources: instrument defaults < JSON override < explicit CLI flag."""
    if inst_key not in _INSTR:
        raise KeyError(f'no PSF defaults for instrument {inst_key!r}; add it to _INSTR')
    params = {**_BASE, **_INSTR[inst_key]}
    filt = str(getattr(cli, 'filt', '')).upper()
    if filt in _PSF_FWHM_ARCSEC and getattr(cli, '_scale', None):
        params['psf_fwhm'] = max(1.2, _PSF_FWHM_ARCSEC[filt] / cli._scale)
    # JSON override: any key in params that the per-lens entry sets.
    for k in list(params):
        if k in json_entry:
            params[k] = json_entry[k]
    # CLI override: argparse leaves tunables as None unless the user passed them.
    for k in list(params):
        v = getattr(cli, k, None)
        if v is not None:
            params[k] = v
    return params


# ── Masking and star selection ──────────────────────────────────────────────────
def build_mask(shape, wht_data, wcs, catalogue_coord, scale_arcsec, lens_mask_radius,
               edge_margin):
    """Boolean mask of pixels excluded from star detection.

    Masks (a) a circle of `lens_mask_radius` arcsec around the deflector so the lens
    galaxy is never mistaken for a star, (b) zero-weight pixels (chip gaps / no coverage)
    from the drizzle WHT map, and (c) a frame-edge margin so extracted stamps stay in
    bounds. Replaces the notebook's hand-typed NaN rectangles.
    """
    ny, nx = shape
    mask = np.zeros(shape, dtype=bool)

    # (a) deflector circle
    px, py = wcs.world_to_pixel(catalogue_coord)
    r = lens_mask_radius / scale_arcsec
    yy, xx = np.ogrid[:ny, :nx]
    mask |= (xx - px) ** 2 + (yy - py) ** 2 <= r ** 2

    # (b) no-coverage pixels
    if wht_data is not None:
        mask |= ~np.isfinite(wht_data) | (wht_data <= 0)

    # (c) edge margin
    m = int(edge_margin)
    if m > 0:
        mask[:m, :] = True
        mask[-m:, :] = True
        mask[:, :m] = True
        mask[:, -m:] = True

    return mask


def reject_crowded(rows, min_separation):
    """Greedy-by-flux crowding cut: drop any candidate whose extract_stars() stamp would
    overlap an already-kept (brighter) one's stamp.

    `rows` must already be flux-sorted, brightest first (as select_stars sorts them), so
    the brightest of any close pair is always the one kept -- a fainter neighbour is
    dropped in favour of it rather than either being silently mixed into the ePSF. Distance
    is Euclidean, `min_separation` is normally `star_size` (see crowd_sep_frac): a Euclidean
    cut at the full stamp width is a conservative (not exact-square) non-overlap test, which
    is the right side to err on for a "don't contaminate the wings" gate.
    """
    kept = []
    for x, y, flux in rows:
        if all((x - kx) ** 2 + (y - ky) ** 2 >= min_separation ** 2 for kx, ky, _ in kept):
            kept.append((x, y, flux))
    return kept


def _in_any_box(x, y, boxes):
    for b in boxes:
        x0, x1, y0, y1 = b
        if x0 <= x <= x1 and y0 <= y <= y1:
            return True
    return False


def _fit_stamp_shape(data, x, y, psf_fwhm):
    """Fit a 2D Gaussian to a small window around (x, y); return (fwhm, ellip, centered).

    Measured on a window ~6 PSF-widths across: wide enough that a resolved galaxy's
    extended light inflates its fitted FWHM (and so fails the upper bound), which an
    11-pixel window around a compact nucleus does not. `centered` guards against the fit
    locking onto an off-centre companion. Returns None if the fit fails or the window
    falls off the frame.
    """
    win = max(15, int(round(6 * psf_fwhm)) | 1)   # odd
    half = win // 2
    ix, iy = int(round(x)), int(round(y))
    ny, nx = data.shape
    if not (half <= ix < nx - half and half <= iy < ny - half):
        return None
    stamp = data[iy - half:iy + half + 1, ix - half:ix + half + 1].astype(float)
    stamp = stamp - np.median(stamp)          # local background
    yy, xx = np.mgrid[:win, :win]
    g0 = models.Gaussian2D(amplitude=max(stamp[half, half], 1e-6),
                           x_mean=half, y_mean=half,
                           x_stddev=psf_fwhm / 2.355, y_stddev=psf_fwhm / 2.355)
    try:
        fit = fitting.TRFLSQFitter()(g0, xx, yy, stamp, maxiter=200)
    except Exception:
        return None
    sx, sy = abs(fit.x_stddev.value), abs(fit.y_stddev.value)
    if not (np.isfinite(sx) and np.isfinite(sy)) or (sx + sy) <= 0:
        return None
    fwhm = 2.0 * np.sqrt(2.0 * np.log(2.0)) * np.sqrt(sx * sy)
    ellip = abs(sx - sy) / (sx + sy)
    centered = (abs(fit.x_mean.value - half) < 2.0 and abs(fit.y_mean.value - half) < 2.0)
    return fwhm, ellip, centered


def select_stars(data, mask, params, overrides, star_size):
    """Detect and filter isolated field stars; return an (x, y) table plus a QA dict.

    Detection uses DAOStarFinder with a background-sigma threshold and per-instrument
    sharpness/roundness/min_separation cuts. Because SLACS fields are galaxy-rich and the
    brightest objects are usually galaxies (flux-ranking alone picks them), each candidate
    that clears the bounds/mask/exclusion filters is then Gaussian-fit and kept only if its
    FWHM sits near the true stellar PSF FWHM (`psf_fwhm`) with low ellipticity and a
    centred fit -- this is what actually separates stars from galaxies, diffraction
    streaks and cosmic rays. Survivors are ranked by flux and the brightest `max_stars`
    kept.

    `overrides` (from info/psf_stars.json) is applied last: `exclude` points/boxes remove
    detected stars, `include` points force extra positions in.
    """
    hsize = (star_size - 1) // 2
    mean, median, std = sigma_clipped_stats(data, mask=mask, sigma=3.0)
    threshold = params['threshold_scale'] * std
    psf_fwhm = params['psf_fwhm']

    finder = DAOStarFinder(
        threshold=threshold, fwhm=params['fwhm'],
        sharplo=params['sharplo'], sharphi=params['sharphi'],
        roundlo=params['roundlo'], roundhi=params['roundhi'],
        min_separation=params['min_sep'], exclude_border=True)
    sources = finder(data - median, mask=mask)

    qa = {'n_detected': 0 if sources is None else len(sources), 'n_crowded_rejected': 0,
          'n_saturated_rejected': 0}
    max_peak = params.get('max_peak')
    if sources is None or len(sources) == 0:
        rows = []
    else:
        ny, nx = data.shape
        exclude_pts = overrides.get('exclude', [])
        exclude_boxes = [b for b in exclude_pts if len(b) == 4]
        exclude_points = [b for b in exclude_pts if len(b) == 2]
        tol = params['fwhm'] * 2.0
        lo, hi = params['fwhm_tol_lo'] * psf_fwhm, params['fwhm_tol_hi'] * psf_fwhm
        min_peak = params['min_snr'] * std

        rows = []
        for s in sources:
            x, y = float(s['x_centroid']), float(s['y_centroid'])
            ix, iy = int(round(x)), int(round(y))
            # bounds: full stamp must be inside the frame
            if not (hsize < x < nx - 1 - hsize and hsize < y < ny - 1 - hsize):
                continue
            # stamp must not overlap the mask (lens galaxy / chip gap / edge)
            sub = mask[iy - hsize:iy + hsize + 1, ix - hsize:ix + hsize + 1]
            if sub.any():
                continue
            # per-lens exclusions
            if _in_any_box(x, y, exclude_boxes):
                continue
            if any((x - ex) ** 2 + (y - ey) ** 2 <= tol ** 2 for ex, ey in exclude_points):
                continue
            # absolute peak-S/N: reject faint noise blobs before the shape fit
            peak = float(data[iy - 2:iy + 3, ix - 2:ix + 3].max())
            if peak < min_peak:
                continue
            # saturated in at least one frame (see _SATLEVEL): never a PSF star
            if max_peak is not None and peak > max_peak:
                qa['n_saturated_rejected'] += 1
                continue
            # star/galaxy separation by fitted shape
            shape = _fit_stamp_shape(data, x, y, psf_fwhm)
            if shape is None:
                continue
            fwhm_i, ellip_i, centered = shape
            if not (lo <= fwhm_i <= hi and ellip_i <= params['max_ellip'] and centered):
                continue
            rows.append((x, y, float(s['flux'])))

        rows.sort(key=lambda r: r[2], reverse=True)
        if rows:
            floor = params['flux_floor_frac'] * rows[0][2]
            rows = [r for r in rows if r[2] >= floor]
        n_before_crowd = len(rows)
        crowd_sep = params['crowd_sep_frac'] * star_size
        rows = reject_crowded(rows, crowd_sep)
        qa['n_crowded_rejected'] = n_before_crowd - len(rows)
        rows = rows[:int(params['max_stars'])]

    qa['n_auto'] = len(rows)

    # Forced include positions (bypass detection, still bounds-checked).
    ny, nx = data.shape
    n_incl = 0
    for pt in overrides.get('include', []):
        x, y = float(pt[0]), float(pt[1])
        if hsize < x < nx - 1 - hsize and hsize < y < ny - 1 - hsize:
            rows.append((x, y, np.nan))
            n_incl += 1
    qa['n_included'] = n_incl

    tbl = Table()
    tbl['x'] = [r[0] for r in rows]
    tbl['y'] = [r[1] for r in rows]
    return tbl, qa


# ── ePSF build and kernel extraction ────────────────────────────────────────────
def build_epsf(data, stars_tbl, star_size, oversample, maxiters):
    """Extract star stamps and build an oversampled ePSF. Returns (epsf, fitted_stars)."""
    nddata = NDData(data=data)
    stars = extract_stars(nddata, stars_tbl, size=star_size)
    builder = EPSFBuilder(oversampling=oversample, maxiters=maxiters,
                          progress_bar=False)
    epsf, fitted_stars = builder(stars)
    return epsf, stars, fitted_stars


def _crop_centered(arr, out, cx, cy):
    """Crop `arr` to (out, out) centred on integer (cx, cy), zero-padding if needed."""
    half = out // 2
    ny, nx = arr.shape
    y0, x0 = int(round(cy)) - half, int(round(cx)) - half
    result = np.zeros((out, out), dtype=float)
    sy0, sx0 = max(0, y0), max(0, x0)
    sy1, sx1 = min(ny, y0 + out), min(nx, x0 + out)
    result[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0] = arr[sy0:sy1, sx0:sx1]
    return result


def validate_epsf(epsf_data, oversample):
    """True if the ePSF looks like a real PSF (finite, positive core peaked near centre).

    With too few or faint stars EPSFBuilder can diverge and drift the peak to a corner
    (seen on a 3-star WFPC2 field). Catching that here lets the caller fall back to the
    model rather than crop an empty region into a garbage kernel.
    """
    arr = np.asarray(epsf_data, dtype=float)
    if not np.all(np.isfinite(arr)) or arr.max() <= 0:
        return False
    ny, nx = arr.shape
    py, px = np.unravel_index(np.argmax(arr), arr.shape)
    # the peak must land within a few image pixels of the centre
    tol = max(4 * oversample, oversample + 2)
    if not (abs(px - nx // 2) <= tol and abs(py - ny // 2) <= tol):
        return False
    # the core must stand well above the ePSF's own outskirt noise (a pure-noise ePSF
    # from junk detections has peak/std of only a few); measure std on the outer frame.
    r = max(ny, nx) // 4
    edge = np.concatenate([arr[:r].ravel(), arr[-r:].ravel(),
                           arr[:, :r].ravel(), arr[:, -r:].ravel()])
    std = np.std(edge)
    return std <= 0 or arr.max() / std >= 15.0


def oversampled_to_kernel(epsf_data, oversample, kernel_size):
    """Bin the oversampled ePSF down to an image-scale, unit-sum, odd kernel.

    Centres on the ePSF core, crops to kernel_size x oversample so the block reduction
    lands an integer number of output pixels, sums each oversample x oversample block
    (flux-conserving for a convolution kernel), then renormalises to unit sum. Falls back
    from a centroid to the peak, then to the geometric centre, if a step is degenerate.
    """
    arr = np.asarray(epsf_data, dtype=float)
    ny, nx = arr.shape
    # locate the core: centroid of a window around the peak, guarding non-finite results
    py, px = np.unravel_index(np.argmax(arr), arr.shape)
    win = max(oversample * 5, 9)
    y0, x0 = max(0, py - win // 2), max(0, px - win // 2)
    # photutils centroid_com returns (x, y) -- COLUMN first. Unpacking it as (y, x) transposes
    # the sub-pixel offset, so the crop below recentres by (dx, dy) instead of (dy, dx) and
    # leaves the kernel off its own array centre by an antisymmetric residual (dy = -dx).
    # That was the bug behind kernels sitting up to 1.7px off centre; measured repo-wide the
    # residual offsets were anticorrelated at -0.76, which is that transposition's signature.
    cx0, cy0 = centroid_com(arr[y0:y0 + win, x0:x0 + win])
    cx, cy = x0 + cx0, y0 + cy0
    if not (np.isfinite(cx) and np.isfinite(cy)):
        cx, cy = float(px), float(py)

    n = kernel_size * oversample
    for centre in ((cx, cy), (float(px), float(py)), (nx / 2.0, ny / 2.0)):
        sub = _crop_centered(arr, n, *centre)
        kernel = block_reduce(sub, oversample, func=np.sum)
        if kernel.sum() > 0:
            return kernel / kernel.sum()
    raise ValueError('ePSF integrates to <= 0 at every candidate centre; '
                     'cannot normalise a kernel from it')


def trim_kernel_to_amplitude(kernel, threshold=3e-4, min_half=3):
    """Crop a full image-scale kernel to the radius where the azimuthally-averaged PSF
    drops below `threshold` x peak, then renormalise to unit sum.

    This is the amplitude-based extent that matters for a *convolution* kernel: it keeps
    the PSF out to where it still spreads flux above ~this fraction of the peak. It is
    deliberately NOT an enclosed-energy cut -- EE is area-weighted and, being an integral
    of the noisy empirical wing, under-sizes (a 95% EE cut truncates while the PSF is still
    ~1% of peak; see the info/ PSF handbooks and the psf.png log panel). Band-adaptive by
    construction: broad PSFs (F160W, F606W) keep more pixels than the sharp ACS core.
    Returns (odd, centred, unit-sum kernel, its size).
    """
    arr = np.asarray(kernel, float)
    ny, nx = arr.shape
    cy, cx = ny // 2, nx // 2
    yy, xx = np.mgrid[:ny, :nx]
    rint = np.round(np.hypot(xx - cx, yy - cy)).astype(int)
    peak = arr[cy, cx] if arr[cy, cx] > 0 else float(arr.max())
    prof = np.array([arr[rint == k].mean() if (rint == k).any() else 0.0
                     for k in range(rint.max() + 1)])          # azimuthal mean per radius
    below = np.where(prof < threshold * peak)[0]
    half = int(below[0]) if len(below) else int(rint.max())
    half = min(max(min_half, half), cy, cx)                    # never exceed the full kernel
    sub = arr[cy - half:cy + half + 1, cx - half:cx + half + 1]
    s = sub.sum()
    return (sub / s if s > 0 else sub), 2 * half + 1


def wing_stats(kernel, inner_frac=0.75):
    """(pedestal_frac, scatter_frac): median and std of the kernel's outer annulus over the
    central peak. The annulus is radius in [inner_frac*half, half] of the full kernel; a
    healthy ePSF wing sits near zero there. Gates poor empirical builds and quantifies the
    residual background the pedestal subtraction removes.
    """
    arr = np.asarray(kernel, float)
    ny, nx = arr.shape
    cy, cx = ny // 2, nx // 2
    yy, xx = np.mgrid[:ny, :nx]
    rint = np.round(np.hypot(xx - cx, yy - cy)).astype(int)
    peak = arr[cy, cx] if arr[cy, cx] > 0 else float(arr.max())
    half = min(cy, cx)
    ann = (rint >= int(inner_frac * half)) & (rint <= half)
    if not ann.any() or peak <= 0:
        return 0.0, 0.0
    return float(np.median(arr[ann]) / peak), float(arr[ann].std() / peak)


def subtract_pedestal(kernel):
    """Remove the ePSF's residual flat background (median of the outer annulus) and
    renormalise to unit sum. Returns (kernel, pedestal_frac).

    EPSFBuilder leaves a small DC floor in the ePSF wings. Left in, a ~1e-3-of-peak pedestal
    across the kernel becomes several percent of the (renormalised) flux as a spurious
    uniform background -- and it stops trim_kernel_to_amplitude from ever crossing the
    amplitude threshold, so the trimmed kernel caps at the full size. This is a near no-op
    for clean builds (ACS ~1e-4) and matters for oversampled bands (F160W empirical ~1e-3,
    the WFPC2 F606W DB ePSF ~1e-3). Applied to every kernel regardless of method.
    """
    arr = np.asarray(kernel, float)
    ny, nx = arr.shape
    cy, cx = ny // 2, nx // 2
    yy, xx = np.mgrid[:ny, :nx]
    rint = np.round(np.hypot(xx - cx, yy - cy)).astype(int)
    peak = arr[cy, cx] if arr[cy, cx] > 0 else float(arr.max())
    half = min(cy, cx)
    ann = (rint >= int(0.75 * half)) & (rint <= half)
    ped = float(np.median(arr[ann])) if ann.any() else 0.0
    out = arr - ped
    s = out.sum()
    if s > 0:
        out = out / s
    return out, (float(ped / peak) if peak > 0 else 0.0)


# ── Empirical PSF uncertainty (bootstrap / jackknife over the star sample) ────────
# The empirical ePSF is built from a handful of field stars (often 3-20, sometimes as few as
# 3), which makes the kernel a point estimate with real, un-propagated uncertainty. We
# estimate a per-pixel PSF error map by resampling the star sample and rebuilding the ePSF:
# bootstrap-with-replacement where there are enough stars, leave-one-out jackknife where there
# are too few for bootstrap to be non-degenerate. Empirical tier only -- the model/injected
# tiers have their own (deferred) error budget. See the PSF uncertainty note in AGENTS.md.
JACKKNIFE_MAX_STARS = 6   # < this, bootstrap draws collapse onto 1-2 stars; use jackknife


def _kernel_from_epsf(epsf_data, oversample, star_size):
    """One ensemble member: oversampled ePSF -> the same full image-scale, pedestal-
    subtracted, unit-sum kernel the primary build produces (oversampled_to_kernel +
    subtract_pedestal), so members are directly comparable to psf_kernel.fits."""
    kernel = oversampled_to_kernel(epsf_data, oversample, star_size)
    kernel, _ = subtract_pedestal(kernel)
    return kernel


def build_epsf_ensemble(data, stars_tbl, star_size, oversample, maxiters, n_boot, rng=None):
    """Resample the star sample and rebuild the ePSF per draw for a PSF-uncertainty estimate.

    len(stars_tbl) >= JACKKNIFE_MAX_STARS: bootstrap-with-replacement, `n_boot` draws.
    Fewer: leave-one-out jackknife (n draws), since bootstrap draws degenerate at tiny N.
    Each draw runs the exact primary build (build_epsf) and is validate_epsf-gated; a
    diverged/failed draw is discarded. Returns (kernels, method, n_valid) where `kernels` is a
    list of full image-scale unit-sum kernels (the same post-processing the primary gets).
    """
    rng = rng if rng is not None else np.random.default_rng(0)
    n = len(stars_tbl)
    if n < JACKKNIFE_MAX_STARS:
        method = 'jackknife'
        index_sets = [[j for j in range(n) if j != i] for i in range(n)]
    else:
        method = 'bootstrap'
        index_sets = [rng.integers(0, n, size=n).tolist() for _ in range(n_boot)]

    kernels = []
    for idx in index_sets:
        if not idx:
            continue
        try:
            epsf, _, _ = build_epsf(data, stars_tbl[idx], star_size, oversample, maxiters)
            cand = np.asarray(epsf.data, dtype=float)
            if validate_epsf(cand, oversample):
                kernels.append(_kernel_from_epsf(cand, oversample, star_size))
        except Exception:
            continue                       # a degenerate resample is dropped, not fatal
    return kernels, method, len(kernels)


def _fwhm_spread(kernels, method):
    """Standard error of the per-member kernel FWHM, matching the ensemble estimator
    (jackknife leave-one-out vs bootstrap replicate std). None if < 2 finite FWHMs."""
    fw = np.array([f for f in (measure_fwhm(k) for k in kernels) if f is not None],
                  dtype=float)
    if len(fw) < 2:
        return None
    if method == 'jackknife':
        return float(np.sqrt((len(fw) - 1) / len(fw) * np.sum((fw - fw.mean()) ** 2)))
    return float(fw.std(ddof=1))


def psf_error_map(kernels, method, trim_half):
    """Per-pixel PSF uncertainty from an ensemble of unit-sum kernels.

    Members are co-registered (each re-centred by oversampled_to_kernel) and unit-sum, so the
    spread is already in the kernel's own amplitude units -- NOT renormalised. Bootstrap: the
    standard error is the replicate std, sqrt(SS/(B-1)). Jackknife: the leave-one-out standard
    error sqrt((n-1)/n . SS). Returns (err_full, err_trim, err_frac, fwhm_err): err_trim is
    err_full cropped to the primary kernel's trim window (same `trim_half`, not a fresh
    amplitude cut) so it matches cutout_[cr_]psf.fits pixel-for-pixel; err_frac =
    sqrt(sum(err_full**2)) (integrated relative PSF uncertainty; the kernels sum to 1).
    """
    stack = np.stack(kernels, axis=0)
    m = stack.shape[0]
    ss = np.sum((stack - stack.mean(axis=0)) ** 2, axis=0)
    if method == 'jackknife':
        err_full = np.sqrt((m - 1) / m * ss)
    else:
        err_full = np.sqrt(ss / (m - 1))
    ny, nx = err_full.shape
    cy, cx = ny // 2, nx // 2
    err_trim = err_full[cy - trim_half:cy + trim_half + 1, cx - trim_half:cx + trim_half + 1]
    err_frac = float(np.sqrt(np.sum(err_full ** 2)))
    return err_full, err_trim, err_frac, _fwhm_spread(kernels, method)


def representative_input_cd(inst_key, lens, filt, sample):
    """2x2 CD (deg/detector-pixel) of a contributing exposure, in the detector frame a model
    ePSF lives in -- so a detector-frame model PSF can be rotated into the North-up drizzle
    frame (psf_models._northup_M). Empirical ePSFs need no CD (built from the North-up mosaic).

    WFPC2: the extracted WF3 file under data/drizzle_files (single WF3 chip; carries the
    correct per-visit roll for split-visit products, keyed by the suffixed `filt`). WFC3/IR:
    the calibrated FLT SCI. ACS/WFC: the calibrated FLC first SCI (fallback only -- the
    focus-diverse path reads per-exposure CDs itself). None if none is found.
    """
    def cd_of(hdr):
        if 'CD1_1' not in hdr:
            return None
        return np.array([[hdr['CD1_1'], hdr['CD1_2']],
                         [hdr['CD2_1'], hdr['CD2_2']]], float)

    def first_sci_cd(path):
        with fits.open(path) as h:
            for hd in h:
                if hd.header.get('EXTNAME') == 'SCI':
                    cd = cd_of(hd.header)
                    if cd is not None:
                        return cd
        return None

    if inst_key == 'WFPC2':
        dd = os.path.join(ws_path, 'data', 'drizzle_files', sample, lens, filt)
        cands = [f for f in sorted(glob.glob(os.path.join(dd, 'wf3_*flt.fits')))
                 if all(t not in os.path.basename(f) for t in ('ivm', 'd2im', 'hlet'))]
        for f in cands:
            cd = first_sci_cd(f)
            if cd is not None:
                return cd
        return None

    pat = {'WFC3/IR': '*flt.fits', 'ACS/WFC': '*flc.fits',
           'WFC3/UVIS': '*flc.fits'}.get(inst_key)
    if pat is None:
        return None
    cd_dir = os.path.join(ws_path, 'data', 'calibrated', sample, lens, filt)
    for f in sorted(glob.glob(os.path.join(cd_dir, pat))):
        cd = first_sci_cd(f)
        if cd is not None:
            return cd
    return None


def measure_fwhm(kernel):
    """Approximate FWHM (pixels) of a kernel via a 2D Gaussian fit; None on failure."""
    try:
        ny, nx = kernel.shape
        yy, xx = np.mgrid[:ny, :nx]
        g0 = models.Gaussian2D(amplitude=kernel.max(), x_mean=nx // 2, y_mean=ny // 2,
                               x_stddev=1.5, y_stddev=1.5)
        fit = fitting.TRFLSQFitter()(g0, xx, yy, kernel)
        s = 0.5 * (abs(fit.x_stddev.value) + abs(fit.y_stddev.value))
        return float(2.0 * np.sqrt(2.0 * np.log(2.0)) * s)
    except Exception as exc:
        print(f'  WARNING: FWHM fit failed ({exc}); recording null')
        return None


# ── Outputs ─────────────────────────────────────────────────────────────────────
def write_fits(data, header, path):
    fits.PrimaryHDU(data=data.astype(np.float32), header=header).writeto(path,
                                                                         overwrite=True)
    print(f'  wrote {path}  shape={data.shape}')


def plot_psf(kernel, epsf_data, star_stamps, scale_arcsec, fwhm_pix, output_path, title):
    """QA panel: selected-star montage, the image-scale kernel on linear *and* log
    stretch (core vs faint wings), and its radial profile."""
    fig = plt.figure(figsize=(20, 5.5))
    gs = fig.add_gridspec(1, 4, width_ratios=[1.2, 1, 1, 1])

    # (1) montage of the extracted star stamps
    ax0 = fig.add_subplot(gs[0])
    n = len(star_stamps)
    if n:
        ncol = int(np.ceil(np.sqrt(n)))
        nrow = int(np.ceil(n / ncol))
        h, w = star_stamps[0].shape
        montage = np.full((nrow * h, ncol * w), np.nan)
        for i, st in enumerate(star_stamps):
            r, c = divmod(i, ncol)
            montage[r * h:(r + 1) * h, c * w:(c + 1) * w] = st
        finite = montage[np.isfinite(montage)]
        vmin, vmax = PercentileInterval(99.0).get_limits(finite)
        norm = ImageNormalize(vmin=vmin, vmax=vmax, stretch=AsinhStretch(0.1))
        ax0.imshow(montage, norm=norm, origin='upper', cmap='inferno')
    ax0.set_title(f'selected stars (n={n})')
    ax0.set_xticks([]); ax0.set_yticks([])

    # (2) the delivered image-scale kernel -- linear stretch (shows the core)
    ax1 = fig.add_subplot(gs[1])
    peak = float(kernel.max())
    norm_lin = ImageNormalize(vmin=0.0, vmax=peak, stretch=LinearStretch())
    im1 = ax1.imshow(kernel, norm=norm_lin, origin='upper', cmap='inferno')
    ttl = 'psf_kernel (linear)'
    if fwhm_pix is not None:
        ttl += f'  FWHM {fwhm_pix:.2f}px={fwhm_pix * scale_arcsec:.3f}"'
    ax1.set_title(ttl)
    ax1.set_xlabel('pixels')
    fig.colorbar(im1, ax=ax1, fraction=0.046, pad=0.04)

    # (3) same kernel -- log stretch (shows the faint wings)
    ax_log = fig.add_subplot(gs[2])
    norm_log = ImageNormalize(vmin=peak * 1e-4, vmax=peak, stretch=LogStretch())
    im_log = ax_log.imshow(kernel, norm=norm_log, origin='upper', cmap='inferno')
    ax_log.set_title('psf_kernel (log, 1e-4..1)')
    ax_log.set_xlabel('pixels')
    fig.colorbar(im_log, ax=ax_log, fraction=0.046, pad=0.04)

    # (4) radial profile of the kernel
    ax2 = fig.add_subplot(gs[3])
    ny, nx = kernel.shape
    yy, xx = np.mgrid[:ny, :nx]
    rr = np.sqrt((xx - nx // 2) ** 2 + (yy - ny // 2) ** 2).ravel()
    order = np.argsort(rr)
    ax2.plot(rr[order] * scale_arcsec, kernel.ravel()[order], '.', ms=3, color='C1')
    ax2.set_yscale('symlog', linthresh=kernel.max() * 1e-3)
    ax2.set_xlabel('radius (arcsec)')
    ax2.set_ylabel('kernel value')
    ax2.set_title('radial profile')
    ax2.grid(alpha=0.3)

    fig.suptitle(title)
    fig.tight_layout()
    fig.savefig(output_path, dpi=120, bbox_inches='tight')
    plt.close(fig)
    print(f'  wrote {output_path}')


def lens_products_rootnames(sample, lens, filt_key):
    """Exposure rootnames that reached the drizzle for (lens, filt), from lens_products.json.

    Used by the ACS focus-diverse ePSF model to retrieve a focus-matched ePSF per exposure.
    Returns [] if the file or entry is absent.
    """
    data = info_json.load(os.path.join(ws_path, 'info', 'lens_products.json'))
    val = data.get(sample, {}).get(lens, {}).get(filt_key)
    return list(val) if val else []


# ── Main ────────────────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--lens', required=True)
    p.add_argument('--filt', required=True)
    p.add_argument('--sample', default=None)
    p.add_argument('--variant', default='', choices=('',) + cutout_paths.VARIANT_COMPONENTS,
                   help="which reduction's mosaic to build from (default standard)")
    p.add_argument('--method', choices=['auto', 'empirical', 'model'], default='auto',
                   help="'auto' (default) builds an empirical ePSF and falls back to the "
                        "STPSF model only when usable stars < --min-stars; 'empirical' "
                        "forces the star build (fails if too few); 'model' forces STPSF.")
    p.add_argument('--trim-threshold', dest='trim_threshold', type=float, default=3e-4,
                   help="amplitude fraction of peak at which the trimmed modelling kernel "
                        "(cutout_psf.fits) is cut. Default 3e-4 -- an amplitude criterion; 1e-3 kept only "
                        "95% of the F115W flux (user's call, 2026-10-04).")
    p.add_argument('--n-boot', dest='n_boot', type=int, default=None,
                   help='bootstrap resamples for the empirical PSF error map (default 100; '
                        'jackknife below %d stars).' % JACKKNIFE_MAX_STARS)
    p.add_argument('--no-psf-err', dest='no_psf_err', action='store_true', default=False)
    for name in ('threshold_scale', 'fwhm', 'psf_fwhm', 'min_sep', 'crowd_sep_frac', 'lens_mask_radius'):
        p.add_argument('--' + name.replace('_', '-'), dest=name, type=float, default=None)
    for name in ('max_stars', 'min_stars', 'star_size', 'oversample', 'kernel_size'):
        p.add_argument('--' + name.replace('_', '-'), dest=name, type=int, default=None)
    p.add_argument('--output', default=None, help='output dir, default data/psf/<sample>/<lens>/<FILT>')
    a = p.parse_args()

    sample = a.sample or mast_target_names.sample_of(a.lens)
    filt = mast_target_names.canonical_filter(a.filt)
    a.filt = filt
    mdir = cutout_paths.mosaic_dir(ws_path, sample, a.lens, filt, a.variant)
    i2d = cutout_paths.find_i2d(mdir)
    output_dir = a.output or os.path.join(ws_path, 'data', 'psf', sample, a.lens, filt)
    psf_json = os.path.join(ws_path, 'info', 'lens_psf.json')
    if i2d is None:
        print(f'=== NO DATA: {a.lens} {filt} (no i2d in {mdir})')
        info_json.update(psf_json, sample, a.lens, filt, None)
        sys.exit(0)
    os.makedirs(output_dir, exist_ok=True)
    overrides = info_json.load(os.path.join(ws_path, 'info', 'psf_stars.json')).get(sample, {}).get(a.lens, {}).get(filt, {})

    print(f'{a.lens} {filt}  [{os.path.basename(i2d)}]')
    with fits.open(i2d) as hdul:
        phdr = hdul[0].header
        sci_hdr = hdul['SCI'].header
        sci_data = np.array(hdul['SCI'].data, dtype=float)
        wht_data = np.array(hdul['WHT'].data, dtype=float)
    hdr = sci_hdr.copy()
    for k in ('CHANNEL', 'FILTER', 'INSTRUME', 'DETECTOR', 'PIXFRAC'):
        if k in phdr and k not in hdr:
            hdr[k] = phdr[k]
    hdr['FILTER'] = filt
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        wcs = WCS(sci_hdr)
    inst_key = instrument_key(hdr)
    scale = proj_plane_pixel_scales(wcs.celestial)[0] * 3600.0
    a._scale = scale
    print(f'  instrument: {inst_key}   pixel scale: {scale:.4f}"/pix')

    method = overrides['method'] if (a.method == 'auto' and 'method' in overrides) else a.method
    params = resolve_params(inst_key, overrides, a)
    params['max_peak'] = saturation_peak(inst_key, hdr, overrides)
    star_size = int(params['star_size']) | 1
    oversample = int(params['oversample'])
    kernel_size = int(params['kernel_size']) | 1
    catalogue_coord = mast_target_names.coord(a.lens, sample)

    # NaN (no coverage) pixels break DAOStarFinder / Background2D: zero them and mask them.
    nan_mask = ~np.isfinite(sci_data)
    sci_data = np.where(nan_mask, 0.0, sci_data)
    mask = build_mask(sci_data.shape, wht_data, wcs, catalogue_coord, scale,
                      params['lens_mask_radius'], edge_margin=(star_size - 1) // 2) | nan_mask
    box = max(32, min(sci_data.shape) // 40)
    try:
        bkg = Background2D(sci_data, box, coverage_mask=mask, exclude_percentile=90.0,
                          bkg_estimator=MedianBackground()).background
        data = sci_data - bkg
    except Exception as exc:
        print(f'  WARNING: Background2D failed ({exc}); using median subtraction')
        _, med, _ = sigma_clipped_stats(sci_data, mask=mask, sigma=3.0)
        data = sci_data - med

    stars_tbl, qa = select_stars(data, mask, params, overrides, star_size)
    n_stars = len(stars_tbl)
    print(f'  stars: {qa["n_detected"]} detected -> {qa["n_auto"]} auto-kept'
          f' + {qa["n_included"]} forced = {n_stars}'
          f' ({qa["n_crowded_rejected"]} dropped as crowded, {qa["n_saturated_rejected"]} saturated)')

    too_few = n_stars < params['min_stars']
    use_model = (method == 'model') or (method == 'auto' and too_few)
    if method == 'empirical' and too_few:
        raise SystemExit(f'ERROR: only {n_stars} usable stars for {a.lens} {filt} '
                         f'(need >= {params["min_stars"]}). Loosen cuts, add include stars to '
                         f'info/psf_stars.json, or use --method model.')
    star_stamps, method_used, epsf_data, model_info = [], None, None, {}
    if not use_model:
        print(f'  method: EMPIRICAL  oversample={oversample} star_size={star_size}')
        epsf, stars, fitted = build_epsf(data, stars_tbl, star_size, oversample, params['maxiters'])
        cand = np.asarray(epsf.data, dtype=float)
        if validate_epsf(cand, oversample):
            k_prov = oversampled_to_kernel(cand, oversample, star_size)
            ped_frac, scat_frac = wing_stats(k_prov)
            poor = ped_frac > params['pedestal_bad'] or scat_frac > params['scatter_bad']
            if poor and method == 'auto':
                print(f'  WARNING: empirical ePSF wings poor (pedestal={ped_frac:.1e}, '
                      f'scatter={scat_frac:.1e}); falling back to the STPSF model')
                use_model = True
            else:
                if poor:
                    print(f'  WARNING: keeping forced-empirical ePSF despite poor wings '
                          f'(pedestal={ped_frac:.1e}, scatter={scat_frac:.1e})')
                epsf_data = cand
                star_stamps = [np.asarray(s.data, dtype=float) for s in stars]
                method_used = 'empirical'
        elif method == 'empirical':
            raise SystemExit(f'ERROR: the empirical ePSF for {a.lens} {filt} diverged ({n_stars} stars).')
        else:
            print(f'  WARNING: empirical ePSF diverged with {n_stars} stars; falling back to STPSF')
            use_model = True

    broadened_box = None
    if method_used is None:
        tag = 'forced' if method == 'model' else (f'{n_stars} stars < {params["min_stars"]}' if too_few else 'empirical failed')
        print(f'  method: MODEL (STPSF)  [{tag}]')
        try:
            epsf_data, model_info = psf_models.model_psf(sample, a.lens, filt, oversample=oversample,
                                                         size=star_size, out_scale=scale)
        except ImportError as exc:
            raise SystemExit(f'ERROR: STPSF unavailable ({exc}). Set STPSF_PATH to the stpsf-data '
                             f'directory (data/reference_files/stpsf-data) -- see psf_models.py.')
        method_used = 'model_stpsf'
        print(f'    {model_info}')

    kernel = oversampled_to_kernel(epsf_data, oversample, star_size)
    if method_used == 'model_stpsf':
        # STPSF omits the resample step's drop broadening: apply the analytic box (see
        # psf_models.analytic_drop_broaden; the injection route is the honest fix).
        native = mast_target_names.NATIVE_SCALE[inst_key.split('/')[1]]
        n_frames = int(phdr.get('NDRIZIM', hdr.get('NDRIZIM', 1)) or 1)
        kernel, broadened_box = psf_models.analytic_drop_broaden(kernel, float(hdr.get('PIXFRAC', 1.0)),
                                                                 native, scale, n_frames=n_frames)
        print(f'  analytic drop broadening: box {broadened_box:.2f} px ({n_frames} frames)')
    kernel, pedestal_frac = subtract_pedestal(kernel)
    if abs(pedestal_frac) >= 1e-4:
        print(f'  pedestal removed: {pedestal_frac:.2e} of peak')
    trimmed, trim_size = trim_kernel_to_amplitude(kernel, a.trim_threshold)
    fwhm_pix = measure_fwhm(kernel)
    if fwhm_pix is not None:
        print(f'  kernel FWHM: {fwhm_pix:.2f} px = {fwhm_pix * scale:.3f}"')
    print(f'  full kernel {kernel.shape[0]}px -> trimmed {trim_size}px (amplitude<{a.trim_threshold:g} of peak)')

    err_full = err_trim = err_frac = fwhm_err = err_method = n_boot_valid = err_source = None
    do_psf_err = not a.no_psf_err and overrides.get('psf_err', True)
    trim_half = (trim_size - 1) // 2
    if do_psf_err and method_used == 'empirical' and n_stars >= 2:
        n_boot = a.n_boot if a.n_boot is not None else int(overrides.get('n_boot', 100))
        mode = 'jackknife' if n_stars < JACKKNIFE_MAX_STARS else f'bootstrap x{n_boot}'
        print(f'  PSF uncertainty: resampling {n_stars} stars ({mode}) ...')
        kernels, err_method, n_boot_valid = build_epsf_ensemble(
            data, stars_tbl, star_size, oversample, params['maxiters'], n_boot)
        err_source = 'stars'
        if n_boot_valid >= 2:
            err_full, err_trim, err_frac, fwhm_err = psf_error_map(kernels, err_method, trim_half)
            print(f'    {err_method}: {n_boot_valid} valid members, PSF error fraction {err_frac:.2e}'
                  + (f', FWHM err {fwhm_err:.3f}px' if fwhm_err is not None else ''))
        else:
            print(f'    WARNING: only {n_boot_valid} valid ensemble member(s); no PSF error map written')
            err_method = err_source = None

    khdr = fits.Header()
    khdr['PSFMETH'] = (method_used, 'empirical ePSF or STPSF model')
    khdr['PSFNSTAR'] = (n_stars, 'stars used (0 for model)')
    khdr['PSFOVSMP'] = (oversample, 'ePSF build oversampling factor')
    khdr['PSFPXSCL'] = (round(scale, 5), 'kernel pixel scale (arcsec)')
    khdr['PSFFWHM'] = (round(fwhm_pix, 4) if fwhm_pix is not None else 0.0, 'fitted kernel FWHM (pixels)')
    khdr['PSFLENS'] = (a.lens, 'lens')
    khdr['PSFFILT'] = (filt, 'filter')
    khdr['PSFKIND'] = ('full', 'full ePSF footprint (trimmed copy in the cutout dir)')
    khdr['PSFPED'] = (round(pedestal_frac, 6), 'ePSF-wing pedestal removed (fraction of peak)')
    khdr['PSFVAR'] = (a.variant or 'standard', 'reduction variant the PSF was built from')
    if method_used == 'model_stpsf':
        khdr['PSFBROAD'] = ('analytic', 'drop broadening: analytic box (not injection)')
        khdr['PSFBOX'] = (round(broadened_box, 4), 'drop box width, output px')
        khdr['PSFOPD'] = (str(model_info.get('opd')), 'STPSF OPD used')
        khdr['PSFDET'] = (str(model_info.get('detector')), 'STPSF detector')
    write_fits(kernel, khdr, os.path.join(output_dir, 'psf_kernel.fits'))
    plot_psf(kernel, epsf_data, star_stamps, scale, fwhm_pix, os.path.join(output_dir, 'psf.png'),
             title=f'{a.lens}  {filt}  [{method_used}]  ({n_stars} stars)')

    cutouts_dir = cutout_paths.psf_cutout_dir(ws_path, sample, a.lens, filt)
    os.makedirs(cutouts_dir, exist_ok=True)
    prefix = cutout_paths.PREFIX
    thdr = khdr.copy()
    thdr['PSFKIND'] = ('trimmed', 'amplitude-trimmed modelling kernel')
    thdr['PSFTRIM'] = (a.trim_threshold, 'azimuthal PSF < this x peak sets the radius')
    write_fits(trimmed, thdr, os.path.join(cutouts_dir, f'{prefix}_psf.fits'))
    if err_full is not None:
        for base, kind, arr, dest in ((khdr, 'full_err', err_full, os.path.join(output_dir, 'psf_kernel_err.fits')),
                                      (thdr, 'trimmed_err', err_trim, os.path.join(cutouts_dir, f'{prefix}_psf_err.fits'))):
            ehdr = base.copy()
            ehdr['PSFKIND'] = (kind, 'per-pixel PSF std (ensemble)')
            ehdr['PSFERR'] = (err_method, 'bootstrap or jackknife ensemble method')
            ehdr['PSFESRC'] = (err_source, 'ensemble source')
            ehdr['PSFNVALD'] = (n_boot_valid, 'valid ensemble members')
            ehdr['PSFEFRAC'] = (round(err_frac, 8), 'integrated PSF error fraction')
            write_fits(arr, ehdr, dest)

    info_json.update(psf_json, sample, a.lens, filt, {
        'method': method_used, 'n_stars': n_stars, 'n_crowded_rejected': qa['n_crowded_rejected'],
        'fwhm_pix': round(fwhm_pix, 4) if fwhm_pix is not None else None,
        'fwhm_arcsec': round(fwhm_pix * scale, 4) if fwhm_pix is not None else None,
        'oversample': oversample, 'kernel_size': int(kernel.shape[0]), 'cutout_kernel_size': int(trim_size),
        'trim_threshold': a.trim_threshold, 'pedestal_frac': round(pedestal_frac, 6),
        'fwhm_pix_err': round(fwhm_err, 4) if fwhm_err is not None else None,
        'psf_err_frac': round(err_frac, 8) if err_frac is not None else None,
        'err_method': err_method, 'err_source': err_source, 'n_boot_valid': n_boot_valid,
        'variant': a.variant or 'standard', 'broadening': 'analytic' if broadened_box else None,
        'model_info': model_info or None,
    })
    print('  done')


if __name__ == '__main__':
    main()
