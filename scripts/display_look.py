"""
The repo's one image look (2026-11-02): the data / PSF / signal-to-noise panels of the dataset
subplots (make_dataset_subplots.py), i.e. the 'inferno' colormap with each panel's own
PercentileInterval(99.0) limits and AsinhStretch(0.1) -- the look the pipeline's stamp,
PSF and QC-grid PNGs already used.

Used by the mask GUIs (make_masks.py, make_arc_masks.py: al.Scribbler takes SCRIBBLER as its
`cmap`), the positions and extra-galaxy GUIs and their PNGs (make_positions.py), the arc-mask
QC PNG and the band overview. Signed residual panels (the isophote-subtracted views) stay on a
diverging red-blue map: a stretch onto inferno would hide which pixels are negative.

`shared_norm`/`normalised_with` give several panels ONE common stretch (the band overview's S/N
rows, where a per-panel stretch would hide the differences between bands).
Light on purpose (numpy + astropy only): the band overview and the GUIs import it.
"""
import numpy as np
from astropy.visualization import AsinhStretch, ImageNormalize, PercentileInterval

CMAP = 'inferno'
PERCENTILE = 99.0
ASINH_A = 0.1


def norm(values, pct=PERCENTILE, vmax=None):
    """The ImageNormalize for one panel: PercentileInterval(pct) limits over its finite pixels
    (`vmax`, in the data's units, overrides the upper one), AsinhStretch(ASINH_A)."""
    a = np.asarray(values, dtype=float)
    finite = a[np.isfinite(a)]
    if finite.size == 0:
        return ImageNormalize(vmin=0.0, vmax=1.0, stretch=AsinhStretch(ASINH_A))
    lo, hi = PercentileInterval(pct).get_limits(finite)
    if vmax is not None:
        hi = float(vmax)
    if not hi > lo:
        hi = lo + (abs(lo) or 1.0)
    return ImageNormalize(vmin=lo, vmax=hi, stretch=AsinhStretch(ASINH_A))


def normalised(values, exclude=None, vmax=None, pct=PERCENTILE):
    """`values` mapped onto [0, 1] (clipped) for imshow(..., cmap=CMAP, vmin=0, vmax=1).
    `exclude` (bool, True = hide) pixels are dropped from the percentile limits and shown at
    the floor, as are non-finite ones."""
    a = np.array(values, dtype=float)
    hide = ~np.isfinite(a)
    if exclude is not None:
        hide |= np.asarray(exclude, dtype=bool)
    a[hide] = np.nan
    out = np.clip(np.ma.filled(norm(a, pct=pct, vmax=vmax)(np.nan_to_num(a)), 0.0), 0.0, 1.0)
    out[hide] = 0.0
    return out


def shared_norm(arrays, pct=PERCENTILE):
    """One ImageNormalize whose limits are the PercentileInterval(pct) of the finite pixels of
    ALL the arrays combined, with AsinhStretch(ASINH_A) -- for panels that must be compared on a
    single stretch (the band overview shows every band's S/N on one shared stretch)."""
    vals = np.concatenate([np.asarray(a, dtype=float)[np.isfinite(a)] for a in arrays])
    if vals.size == 0:
        return ImageNormalize(vmin=0.0, vmax=1.0, stretch=AsinhStretch(ASINH_A))
    lo, hi = PercentileInterval(pct).get_limits(vals)
    if not hi > lo:
        hi = lo + (abs(lo) or 1.0)
    return ImageNormalize(vmin=lo, vmax=hi, stretch=AsinhStretch(ASINH_A))


def normalised_with(values, norm, exclude=None):
    """`values` mapped onto [0, 1] (clipped) with the given norm (e.g. shared_norm), for
    imshow(..., cmap=CMAP, vmin=0, vmax=1); `exclude` and non-finite pixels go to the floor,
    as in normalised."""
    a = np.array(values, dtype=float)
    hide = ~np.isfinite(a)
    if exclude is not None:
        hide |= np.asarray(exclude, dtype=bool)
    out = np.clip(np.ma.filled(norm(np.nan_to_num(a)), 0.0), 0.0, 1.0)
    out[hide] = 0.0
    return out


class ScribblerLook:
    """al.Scribbler's `cmap` hook: an object with `norm_from(array=...)` and `cmap_name` makes the
    Scribbler normalise EACH panel with that norm (its own limits) and draw it on that colormap,
    instead of its default median/MAD arcsinh on autoarray's colormap. NaN-safe, since the
    Scribbler passes the raw panel."""
    cmap_name = CMAP

    def norm_from(self, array):
        return norm(array)


SCRIBBLER = ScribblerLook()
