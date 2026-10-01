"""Placeholder for the HST repo's automatic arc detector.

The HST detector builds a PSF-matched blue-minus-red colour image (F606W/F555W against F814W)
and keeps the blue excess in an annulus about theta_E -- SLACS sources are blue star-forming
galaxies behind red ellipticals. The JWST lenses here are the opposite case (dusty, red
sources: the SPT DSFGs and the B1938+666 z=2 source are brightest in the LW bands), so the
detector would need re-deriving with the sign flipped and a NIRCam PSF-matching step. Until
that is done, make_arc_masks.py --propose-from detect raises NotImplementedError; the other
proposal sources (another band's reviewed mask, or 'none') work as in the HST repo.
"""

DEFAULTS = dict(snr=3.5, peak=4.0, min_area=15, smooth=0.07, r_in=0.35, r_out=2.0, grow=2)


def propose(*args, **kwargs):
    raise NotImplementedError(
        'Automatic arc detection is not ported to JWST yet (see scripts/detect_arcs.py). '
        "Use --propose-from <band> or --propose-from none.")
