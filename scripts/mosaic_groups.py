"""Filter groups for the QC grids (make_qc_grids.py).

The HST repo grouped WFPC2 F606W with ACS F555W into one panel row; nothing like that is
needed for NIRCam, so there are no hard-coded groups and `groups_for_sample` always falls
back to one group per filter directory found on disk, in channel order (SW first).
"""
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lens_samples

SAMPLE_GROUPS = {}


def _order(filt):
    try:
        return (0, lens_samples.SW_FILTERS.index(filt))
    except ValueError:
        try:
            return (1, lens_samples.LW_FILTERS.index(filt))
        except ValueError:
            return (2, filt)


def groups_for_sample(sample, cutouts_dir):
    """{group_name: [filters]} -- one group per filter present under cutouts_dir/<lens>/."""
    if sample in SAMPLE_GROUPS:
        return SAMPLE_GROUPS[sample]
    filts = {os.path.basename(d) for d in glob.glob(os.path.join(cutouts_dir, '*', '*')) if os.path.isdir(d)}
    return {f: [f] for f in sorted(filts, key=_order)}
