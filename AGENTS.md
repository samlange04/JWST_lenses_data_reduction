# AGENTS.md

Guidance for any coding agent (and for humans) working in this repo. This file is the
**operational** reference: commands, layout, decisions, and the traps that silently produce
wrong products. Where a decision is stated as settled, a measurement was made and the choice
followed from it; the result is summarised here, so don't re-derive or re-litigate it without
new evidence. It is the JWST sibling of the AGENTS.md in
[HST_lenses_data_reduction](https://github.com/samlange04/HST_lenses_data_reduction) ("the HST
repo" below); where a decision was inherited from there it says so, and that file's
measurements are not restated here.

> **AGENTS.md documents intent, not always state.** Before running a batch campaign or
> reporting what is outstanding, verify against source — argparse defaults, what the
> runner actually passes, tracking JSONs vs what is on disk.

## Current state (2026-10-27)

Repo created 2026-10-01 from the HST repo's structure, PyAutoReduce's JWST path and the
jwst 3.0.0 docs. Program 8281 (B1938+666) became public at 03:16 UTC that day. Public on
GitHub since 2026-10-27, with the HST repo's dual licence (`LICENSE` MIT for code,
`LICENSE-DATA` CC BY 4.0 for `data/` and the `info/` records) and a `CITATION.cff`.
`README.md` is the user-facing description; keep its product facts in step with this file.
Stamps renamed 2026-10-26 (`data/cutouts/` → `data/stamps/`, `cutout_*` → `stamp<S>_*`,
`info/` split into `samples/`, `overrides/`, `provenance/`), the same rename as the HST repo.

| lens | sample | downloaded | reduced | stamps | PSF | masks + positions |
|---|---|---|---|---|---|---|
| SPT2147-50 | spt | uncal, 4 filters | F200W F277W F356W F444W | all 4 | see info/provenance/lens_psf.json | – |
| SPT0418-47 | spt | uncal, 6 filters | F115W F150W F200W F277W F356W F444W | all 6 | see info/provenance/lens_psf.json | – |
| B1938+666 | b1938 | uncal, 210 files / 79 GB | F115W F277W (2026-10-02, 8.5 h) | both | both, see info/provenance/lens_psf.json | both (2026-10-04) |

**The whole SPT sample reduced in one `run_reduce_all.sh spt` pass (2026-10-02 02:06): 10 ok,
0 failed.** Per band: SW (4 detectors × 2 dithers) 220–250 s, SW F200W of SPT2147 (24 frames)
690 s, LW 60 s — after the references were cached; the CRDS pull dominated the wall clock
(30 GB in all, a 6.3 GB dark per SW detector at ~30 min each). tweakreg relative shifts
were 1–44 mas on every band (fit RMSE 0.10–0.19", i.e. the finder's centroid scatter on
galaxies, not a WCS problem). Weight uniformity over every 12" stamp 0.08–0.13 (< 0.2).
0 bad pixels in any stamp.

**PSFs, all 12 bands empirical** (first built 2026-10-02; rebuilt 2026-10-03 with 81 px SW star
stamps so the pedestal annulus clears the wings, and 2026-10-04 with the modelling-kernel trim
at 3e-4 of peak). Current values from `info/provenance/lens_psf.json`:

| band | SPT0418-47 stars / FWHM / err frac | SPT2147-50 stars / FWHM / err frac | B1938+666 stars / FWHM / err frac |
|---|---|---|---|
| F115W | **3** / 0.060" / 0.029 | – | 8 / 0.055" / 0.021 |
| F150W | 6 / 0.067" / 0.016 | – | – |
| F200W | 5 / 0.073" / 0.011 | 9 / 0.075" / 0.010 | – |
| F277W | 6 / 0.120" / 0.018 | **3** / 0.132" / 0.021 | 12 / 0.121" / 0.012 |
| F356W | 6 / 0.148" / 0.012 | 8 / 0.150" / 0.019 | – |
| F444W | 7 / 0.169" / 0.008 | 10 / 0.170" / 0.024 | – |

FWHMs sit 11–50% above the JDox in-flight values (0.040/0.050/0.066/0.092/0.116/0.145"),
as a 2-dither resampled ePSF should; the largest excess is SPT0418-47 F115W. **The two 3-star
builds (SPT0418-47 F115W, SPT2147-50 F277W) are borderline**: they pass at `min_stars=3`.
The rebuilds brought SPT0418-47 F115W's bootstrap error from 25% (the 2026-10-02 build) to
2.9%, but a bootstrap over three stars says little about how far the kernel is from the true
PSF, so check `psf.png` before modelling. Options, in order: add include stars via
`info/overrides/psf_stars.json` (no such file yet) after looking at the mosaic; `--method
model` once stpsf-data is installed (not yet) and compare the model's FWHM to the one
measured here; raise `min_stars` to 4 so the auto tier falls back by itself.

**Residual diagonal striping is visible in the SW stamps' background (F115W, F150W, F200W;
not in LW).** Stripes run diagonally because the detector rows are rotated against the
North-up grid, so this is a detector-row effect — 1/f that `clean_flicker_noise` did not
fully remove, or amplifier offsets. It is at the noise level in a 12" stamp, but it is
exactly the correlated structure a pixelized source will absorb.

*Diagnosed on SPT0418-47 F150W (2026-10-02, afternoon).* Stamp metric: high-pass (25 px
median), mask sources and the lens (r < 110 px), rotate through every angle, rms of the row
medians. The banding peaks sharply at a rotation of 66°, matching the detector x axis on the
sky (65°): the stripes run along detector ROWS, the fast-read direction, so it is 1/f and
not a sky or mosaic artefact. Row-median rms along the stripes vs perpendicular (MJy/sr;
per-pixel high-passed rms 0.031 in every case):

| reduction | along | perp | excess banding (quadrature) |
|---|---|---|---|
| MAST rate (`--start rate`, no flicker step) | 0.0054 | 0.0030 | 0.0045 |
| standard (`clean_flicker_noise`, one fit per row) | 0.0041 | 0.0029 | 0.0029 |
| `--flicker-by-channel` (variant `bychan`) | 0.0043 | 0.0031 | 0.0030 |
| `--destripe` (variant `destriped`, TEMPLATES rate-level recipe) | 0.0039 | 0.0028 | 0.0027 |

So the ramp-level step removes about a third of the banding amplitude, the per-amplifier
fit adds nothing, and the TEMPLATES destripe (`scripts/destripe_nircam.py`: object mask from
the standard mosaic propagated through each frame's gwcs OR a per-frame high-pass mask,
amplifier offsets, then one median per row per 512-column amplifier; Rigby+25 §6.3,
`rigby2025templates`) adds nothing at the lens either, though it does clean blank sky
(blank 12" stamps 39" from the lens: along/perp ratio 1.49 → 1.05, 1.71 → 1.33).

**Why nothing row-based can fix the lens stamp.** The autocorrelation of a high-passed B4
rate frame along the row is 0.13 at 1 px, 0.05 at 32 px, 0.02 at 128 px and zero by 256 px:
the residual after the ramp step is high-frequency 1/f, coherent over ~100 px (3"), not a
512-px stripe. A row template estimated outside the lens mask therefore does not predict
the noise under it — tested directly: with a 400-px box hidden from the template, the
per-amplifier template makes the box WORSE (0.0044 → 0.0073 DN/s few-row rms: it adds its
own ~0.002 DN/s of row-coherent noise) and a full-row template changes nothing (0.0042).
jwst's `fit_method='fft'` (NSClean) would address these frequencies but is NIRSpec-only in
jwst 3.0. A running median along the row (window ≲ 129 px) does remove it on blank sky but
would subtract the lens galaxy's unmasked wings near the mask edge (halo SB at the 2σ mask
edge ≈ 0.02 DN/s, several times the 1/f) — do not do this without a model-based mask.

**Consequence: the residual is correlated noise at ~6% of the per-pixel sigma with a 3"
correlation length along the detector row, and it has to be carried in the noise model, not
removed.** Done 2026-10-04 as a scale-matched `NOISECOR` (SW 1.30, LW 1.03 at 0.2") with
the full block-ratio curve exported — see *Noise*. A pixelized source fit should still
expect to absorb some of it in the sky-dominated part of the mask; on the ring the Poisson
noise is ~10x the sky sigma and the 1/f is irrelevant. `--destripe` stays available as a variant for background-
limited uses. The rate-level pedestal removes only amplifier DIFFERENCES (the common level
is sky and must stay for the flat field). `--flicker-by-channel` and `--destripe` route to
their own `_bychan` / `_destriped` stage1/stage2/mosaic trees (the flag used to be a silent
no-op on existing rate files). The measurement scripts were not kept; port the
rotate-and-row-median scan into `scripts/` if the metric is needed again.

**First verified product — SPT2147-50 F444W (2026-10-01 23:15):** 2 uncal → Detector1
23 s + 16 s → Image2 → Image3 21 s → `spt2147-50_f444w_i2d.fits`, 2500² px at 0.060"/px,
CD = diag(−1, 1) (North-up), CRVAL at the catalogue position, `BUNIT=MJy/sr`,
`PHOTMJSR=0.365`, `PIXAR_SR=8.46e-14`, `PIXFRAC=1.0`, `PXSCLRT=0.95`, `CRDS_CTX=jwst_1584.pmap`,
`CAL_VER=3.0.0`. tweakreg relative fit: 72 matches, shift 16 mas, so the a-priori WCS was
already good. skymatch: 0.230 MJy/sr sky, subtracted at resample. The 12" stamp (200² px) is
fully covered, 0 bad pixels, and shows the ring + lens galaxy exactly as in Lange+25. Blank-sky
robust std 0.011 vs median ERR 0.015 MJy/sr: per-pixel scatter BELOW the noise map, as
resampling predicts — judge the map by block sums (`measure_corr_factor.py`), not per pixel.
Empirical PSF: 281 detections → 10 PSF-grade stars, FWHM 2.83 px = 0.170" (JDox 0.145"
nominal; a resampled, 2-dither ePSF is expected broader), 41 px kernel trimmed to 25 px,
bootstrap PSF error fraction 2.4e-2. The six-spike NIRCam pattern is visible in the log
panel of `data/psf/spt/SPT2147-50/F444W/psf.png`. `export_dataset.py` on this band
produced the PyAutoLens dataset layout with `pixel_scale 0.06` and the redshifts.

**Day-one outages and the fixes they forced:** jwst-crds.stsci.edu returned 502/504 then
timed out for ~2 h (MAST stayed up), killing the first run mid-Detector1 and leaving a
truncated 4.4 GB dark in the cache → `reduce_nircam.sync_references` (pre-sync with
`crds sync --check-files --repair-files`, 30 × 300 s retries). MAST dropped a connection
mid-file on the 8th B1938 uncal (IncompleteRead), which astroquery's batch call raised out
of and then would have treated the truncated file as cached → `download_nircam.download`
fetches one file at a time, checks size against MAST's catalogue, deletes and retries.
Both are the HST repo's "silently wrong product" class: a truncated reference or exposure
produces no error downstream.

## Environment

**uv-managed**, like the HST repo: `pyproject.toml` + `uv.lock` + `.python-version` are
tracked, `.venv` is not.

**This repo is NIRCam reduction only.** Science analysis and non-JWST data (lens modelling,
ground-based follow-up) belong in a downstream project, not here. Downstream code may read
the stamp tree, the Image3 mosaics and the `info/*.json` files, and import
`scripts/stamp_paths.py`, so treat those paths and that module's API as an interface:
don't move or rename them casually.

```bash
uv sync                                               # one-time, or after a .venv wipe
uv run python scripts/<script>.py --lens <LENS> --filt <FILTER>
```

Python **3.13** (not the HST repo's 3.12.13: `jwst` 3.0.0 needs ≥3.11, and the two repos
have separate envs anyway). Pinned: `jwst==3.0.0` (STScI Build 13.0, the ops version from
2026-09), `stpsf==2.2.0` (WebbPSF's successor). `astropy`, `numpy`, `photutils`, `scipy`,
`crds`, `astroquery`, `matplotlib`, `tqdm` float at ≥ the versions jwst 3.0.0 wants.
`autolens` (≥2026.10.7.1) is there for the GUI scripts (`al.Scribbler`) and the dataset
subplots; it resolved cleanly beside jwst (checked 2026-10-01). The floor is 2026.10.7.1
because the mask GUIs now rely on that release's `Scribbler` features (see *Masks*).

**The repo root is derived from `__file__`, never hard-coded** — every script sets
`ws_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`, runners take
`WS="$(dirname "$SD")"` off `BASH_SOURCE`. A move invalidates `.venv`: `rm -rf .venv && uv sync`.

**CRDS.** `reduce_nircam.setup_crds()` sets `CRDS_PATH=data/reference_files` and
`CRDS_SERVER_URL=https://jwst-crds.stsci.edu` (only if unset, so a shell export wins).
References download lazily on first use — the first Detector1 run pulls the NIRCam
reference set (tens of GB; readout-pattern-specific darks are the bulk). The context used
is recorded per product in `info/provenance/lens_products.json` (`crds_context`, from the i2d
`CRDS_CTX`). To pin: `export CRDS_CONTEXT=jwst_XXXX.pmap`. **Don't rely on
`crds.get_default_context()` offline** — it raises; the scripts catch it.

**STPSF data** (model-PSF fallback only): `STPSF_PATH=data/reference_files/stpsf-data`
is set by `setup_crds()`; download the tarball once per the STPSF install docs. A build
that never needs the model tier never needs it.

**macOS write-hang workaround (inherited, kept).** `scripts/mmap_fits_write.py` is the HST
repo's monkeypatch of `astropy.io.fits.file._array_to_file` (mmap+memcpy instead of
buffered `write()`), installed at import by `reduce_nircam.py`. The jwst datamodels save
through astropy.io.fits, so it applies; whether JWST writes ever trigger the kernel
lost-wakeup is unverified — the patch is byte-identical and free, so it stays. Stages run
one file at a time, no multiprocessing (`ramp_fit.maximum_cores` left at `none`), for the
same reason the HST drizzles use `num_cores=1`.

**Long batch runs: wait on the process, never on a file-timestamp poll** (`find -newermt`
can parse the same timestamp as local time in an interactive shell and as UTC in a script,
so a condition checked by hand may never come true where it runs). Runners here write a
final `=== ... done` line; chain on exit status.

## What this repo does

One product per lens + NIRCam filter: a North-up Image3 mosaic centred on the lens, a 12"
stamp with a sigma map, a PSF kernel, hand-drawn masks and image positions, and an export
in the PyAutoLens dataset layout (`data.fits / noise_map.fits / psf.fits / info.json`) that
a modelling project reads.

```
download_nircam.py  MAST uncal -> data/calibrated/<sample>/<lens>/pool/ -> hard-linked into <FILT>/
reduce_nircam.py    uncal -> Detector1 -> rate -> Image2 -> cal -> Image3 -> <lens>_<filt>_i2d.fits
destripe_nircam.py  rate-level TEMPLATES 1/f destripe (reduce_nircam.py --destripe, variant `destriped`; opt-in)
split_noise_test.py half-dither mosaics A, B -> A-B null image -> block-sum ratio vs ERR (deep fields' NOISECOR)
measure_corr_factor.py  blank-sky block-sum / ACF ratios on every stamp (shallow fields' NOISECOR)
make_stamps.py     i2d SCI/ERR/WHT -> stamp<S>_sci.fits, stamp<S>_noise.fits, stamp<S>.png
make_psf.py         i2d field stars -> ePSF -> psf.fits  (STPSF fallback)
make_masks.py / make_arc_masks.py / make_positions.py   GUIs, one draw per band, broadcast by WCS
make_dataset_subplots.py / make_qc_grids.py              QC
export_dataset.py   -> <dest>/<lens>/<FILT>/{data,noise_map,psf}.fits + info.json [+ mask, positions]
```

**NIRCam only.** TEMPLATES also took MIRI imaging
(F560W–F2100W, 0.11"/px) and NIRSpec G395M + MIRI MRS IFU cubes of both SPT lenses; GO
8281 is NIRCam only. If MIRI is ever wanted: the pool download already fetches only
`NRC_IMAGE` exposures (`download_nircam.sort_pool` filters on `EXP_TYPE`), so a MIRI path
needs its own `instrument_name='MIRI/IMAGE'` query and a `mirimage` branch in the sort.
PyAutoReduce has no MIRI support either.

## Lens samples (`info/samples/lens_samples.json`, read only by `scripts/lens_samples.py`)

A JWST lens is located in MAST by **proposal ID + target name** (not an `SDSS%` wildcard
as for SLACS), so each sample block carries `proposal_id` and each lens its `mast_target`,
catalogue `ra`/`dec` (the stamp centre and the mosaic tangent point) and `redshift_lens` /
`redshift_source` (written into the exported `info.json`; a modelling project that keeps its
own copy must keep them equal).

| sample | program | lens | MAST obs | NIRCam setup |
|---|---|---|---|---|
| `b1938` | 8281, PI Vegetti, Cycle 4 | B1938+666 | `jw08281-o001` | **Module ALL**, F115W+F277W, MEDIUM8 8 grp × 5 int, INTRAMODULE×3 + STANDARD×7 = 21 dithers, 87 934 s per filter, 2 visits (2025-09-20, 2025-09-29). 210 uncal / 79 GB |
| `spt` | 1355 TEMPLATES, PI Rigby, ERS | SPT0418-47 | `jw01355-o016` | Module B, F115W+F277W (SHALLOW2, 687 s), F150W+F356W (BRIGHT2, 344 s), F200W+F444W (BRIGHT2, 429 s), 2 dithers. Lens on **B4** (Cathey+24) |
| `spt` | 1355 | SPT2147-50 | `jw01355-o024` | Module B, F200W paired with each of F356W/F444W/F277W (F200W 1460 s total), 2 dithers per pair |

Coordinates: APT fixed-target positions (B1938+666 19:38:25.28 +66:48:52.9; SPT0418-47
04:18:39.68 −47:51:52.7; SPT2147-50 21:47:19.01 −50:35:54.5), which agree with the MAST
`s_ra/s_dec`. Redshifts: B1938 z_l 0.881 / z_s 2.059 (APT, Tonry & Kochanek 2000, Riechers
2011); SPT from Lange et al. 2025 §2 (Weiss+13, Reuter+20). Published θ_E: SPT0418 1.207"
(Cathey+24), SPT2147 1.195" (Spilker+16); B1938 ~0.45" (the radio ring).

**The B1938 target was placed in the "Module Gap"** (APT special requirement): the ring
sits near the gap between SW detectors, so across the 21 dithers it lands on different
SW chips (and is simultaneously on one LW chip per module). Consequences: the SW mosaic's
weight map is non-uniform right at the lens — check `WHTUNIF` on the F115W stamp — and the
empirical SW PSF is averaged over detectors (fine, it is what the data carry).

**B1938+666: the ring of clumps at r ≈ 0.9–1.4" is deliberately left unmasked** (outside the
0.45" Einstein ring; includes Lagattuta+12's arclets A/B). They may be lensed images or
lens-plane structure, which is not settled, so whether to exclude them is a modelling choice
(`mask_radius` at export, or a model-side mask), not something the contaminant mask decides.

**SPT0418 is on B4, the detector with the strongest NIRCam wisp** (JDox scattered-light
article). Wisps are ~10% of zodi at fixed detector position in F115W/F150W/F200W; the
pipeline does not remove them. Nothing is done about this yet — look at the SW mosaics
before trusting a faint SW arc, and if wisp residuals are visible, subtract the STScI V3
templates per exposure before Image3 (grizli `nircam_wisp_correction` does it).

## Download (`scripts/download_nircam.py`)

```bash
uv run python scripts/download_nircam.py --lens SPT2147-50 [--level uncal|rate|cal] [--dry-run]
```

**Pool, then sort — the trap this layout avoids.** A NIRCam MAST *observation* is one
filter, but its *product list* is every file of the visit: SW and LW are exposed
simultaneously, the visit's other SW filters share exposure IDs, and nothing in the
filename says which filter a file is. Asking MAST for "the F115W observation's UNCAL
files" therefore fetches all of F150W/F200W/F277W... too. So the whole visit is downloaded
once into `data/calibrated/<sample>/<lens>/pool/` (astroquery `flat=True, cache=True`, so
a re-run skips what is there) and each file is **hard-linked** into `<lens>/<FILT>/` by its
header `FILTER`/`PUPIL`/`DETECTOR` (`effective_filter`: PUPIL wins when it holds a filter,
which never happens for the wide bands here). Hard links, not copies (no second 80 GB) and
not symlinks. `info/provenance/lens_downloads.json` records obs IDs and per-filter file counts.

**Starting level: `uncal` (default), reduced here from the ramps.** Decided 2026-10-01 for
two reasons: (1) the 1/f-stripe removal that matters for a lens (`clean_flicker_noise`) is
a *Detector1* step on the ramp, off by default in jwst, so it is only available by
re-running Detector1 ourselves; (2) one jwst version and one CRDS context for every frame,
recorded, instead of whatever MAST's ops reprocessing of the day used (MAST's 8281 files
were processed 2026-07-27; TEMPLATES' public rate files date from 2022–23 and have been
reprocessed since). Cost: 79 GB uncal for B1938 instead of 18 GB rate, and Detector1 run
time (minutes per 5-integration MEDIUM8 file). `--level rate` + `reduce_nircam.py --start
rate` is the escape hatch; its mosaic is tagged `mastrate` end to end (`stamp_paths.py`) so
it can never be mistaken for the full reduction.

## Reduction (`scripts/reduce_nircam.py`)

```bash
uv run python scripts/reduce_nircam.py --lens SPT2147-50 --filt F444W \
    [--start uncal|rate|cal] [--scale 0.06] [--field 150] [--tweakreg relative|gaia|skip] \
    [--flicker-by-channel] [--force]
bash scripts/run_reduce_all.sh spt          # every lens, every filter in its pool
```

Three cached stages; a re-run only redoes what is missing (`--force` rebuilds the mosaic
only — delete `data/stage1/.../<FILT>` to redo Detector1):

```
data/calibrated/<s>/<l>/<F>/*_uncal.fits -> Detector1 -> data/stage1/<s>/<l>/<F>/*_rate.fits
                                          -> Image2    -> data/stage2/<s>/<l>/<F>/*_cal.fits
                                          -> Image3    -> data/mosaics/<s>/<l>/<F>/<lens>_<filt>_i2d.fits (+png)
```

### Non-default pipeline settings, and why

| stage | setting | why |
|---|---|---|
| Detector1 | `jump.expand_large_events=True` | snowball flagging for NIR detectors. The CRDS `pars-jumpstep` file turns it on for NIRCam anyway; set explicitly so a context change cannot turn it off silently |
| Detector1 | `clean_flicker_noise.skip=False` | **1/f striping removed on the ramp**, with sources masked at 2σ (`fit_method=median`, Willott's image1overf algorithm, `background_method=median`). Skipped by default in jwst 3.0.0 (JDox *1/f noise*). It is the dominant correlated-noise term in a NIRCam frame and its scale (10–100 px stripes) is exactly the lens's. `--flicker-by-channel` adds a per-amplifier fit. **JDox caveat: a factor-10 gain for 2–3-group ramps, but "for very long ramps it can make things worse"** — compare a stamp with and without (`--start rate` gives the without, cheaply) before trusting it on B1938's 8-group MEDIUM8 data |
| Image2 | `resample.skip=True` | per-exposure i2d previews are dead weight |
| Image3 | `tweakreg`: relative only by default | aligns the dithers to each other (IRAFStarFinder, `minobj=15`, `fitgeometry=rshift`). `--tweakreg gaia` adds `abs_refcat=GAIADR3`; `skip` for a field where it finds too few sources. **A failed tweakreg is not fatal**: jwst logs it and keeps the a-priori WCS, which for JWST is good to ~0.1" absolute and to mas relative within a visit — nothing like WFPC2. TEMPLATES found Gaia alignment broke SW/LW registration (jwst issue 7993) and ended up aligning SW to a Gaia-tied F277W catalogue per module |
| Image3 | `skymatch.skymethod=global+match`, `subtract=False` | one sky level per mosaic, matched across dithers. `subtract=False` is NOT "don't subtract": stcal's resample subtracts `meta.background.level` itself when `subtracted` is False (`stcal/resample/resample.py`, checked in the installed version). The mosaic is sky-subtracted |
| Image3 | `outlier_detection`: defaults | JWST's CR pass. There is no separate no-CR product: `jump` flags CRs on the ramp and `outlier_detection` catches the rest, so this repo has ONE pass and the stamp names carry none (`stamp<S>_*`; `drizzle_pass` is recorded as `single`) |
| Image3 | `resample`: `pixfrac=1.0`, `kernel=square`, `weight_type=ivm`, `fillval=NAN`, `rotation=0`, `crval=<catalogue>`, `crpix=<centre>`, `pixel_scale` SW **0.03"** / LW **0.06"**, `output_shape` from `--field` (150" default) | North-up, one tangent point per lens, SW/LW grids nested 2:1. Scales near native (0.031/0.063) at pixfrac 1.0 follow the HST repo's finding that pixfrac cannot change the noise a fit sees and that near-native scales keep the noise model clean; COWLS (Nightingale+25) and PyAutoReduce use the same 0.03/0.06 pair. `--scale 0.02` is the finer option JDox mentions for well-dithered data (B1938's 21 dithers qualify) — a measurement question, not settled |
| Image3 | `source_catalog.skip=True` | not needed |

`weight_type=ivm` means the i2d `WHT` is 1/VAR_RNOISE-weighted (read noise only), not the
total inverse variance — **never build the noise map from WHT here**; the `ERR` extension
is the propagated total sigma (see *Noise*). That is the opposite of the HST repo's
`final_wht_type=ERR` route and is why `make_stamps.py` reads `ERR`.

Units stay in **MJy/sr** (PyAutoReduce's choice too). `PHOTMJSR` (MJy/sr per DN/s) and
`PIXAR_SR` (sr per output pixel) in the i2d header convert: Jy/pixel = SCI × PIXAR_SR × 1e6;
DN/s = SCI / PHOTMJSR. PyAutoLens is unit-agnostic as long as data, noise and the PSF
normalisation agree.

Tracking JSONs updated per product: `lens_products.json` (rootnames, jwst version, CRDS
context, pixfrac, scale, PHOTMJSR/PIXAR_SR, i2d path), `lens_exptime.json` (sum per exposure, one detector per dither, of
EFFEXPTM), `lens_instrument.json` (`NIRCAM/SW` or `NIRCAM/LW`). No data → `null`, exit 0.

### Not done yet, and known to matter

- **Wisps** (SW, detectors B4/A3/A4/B3): see *Lens samples*. Not subtracted.
- **1/f verification**: `clean_flicker_noise` is on by default here on the strength of the
  JDox recommendation, not a measurement on these data. Owed: a blank-sky ACF of a stamp
  cut from `--start rate` (MAST's rate, no flicker step) vs the default.
- **Noise inflation factors** (`info/overrides/noise_corr_factors.json`): measured 2026-10-04, SW 1.30 /
  LW 1.03 at 0.2"; B1938+666 by the split-dither test, F115W 0.94 / F277W 1.12 (see *Noise*).
  Owed: a scale-matched rescale once the modelling project fixes its source-pixel scale.
- **Model PSF broadening by injection**: the STPSF tier uses the analytic drop box; the
  HST repo's injection route (`make_psf_inject.py`) is not ported.
- **Automatic arc detection** (`detect_arcs.py`) is a stub.

## Stamps (`scripts/make_stamps.py`)

```bash
uv run python scripts/make_stamps.py --lens SPT2147-50 --filt F444W [--size 12] [--center auto|catalogue|deflector|peak] [--variant mastrate]
bash scripts/run_stamps_all.sh spt [SIZE] [--variant V]
```

Writes `data/stamps/<sample>/<lens>/<FILT>/stamp<S>[_<variant>]_{sci,noise}.fits`
+ `stamp<S>[_<variant>].png`, where S is the stamp's nominal size in arcsec (`stamp7_*` for
B1938+666, `stamp12_*` for the SPT lenses; since 2026-10-26, before which every stamp was
`cutout_*` and the size picked the tree). Stamp = 12" (400 px SW, 200 px LW), unless the lens sets `stamp_size` in
`info/samples/lens_samples.json` (B1938+666: 7" → 232 / 116 px = 6.96", 2026-10-04; at 12" a third of
its stamp was two detector streaks and a galaxy group to mask, around a 0.45" ring).
**`stamp_size` is that lens's MODELLING size**: every tool's `--size` defaults to it
(`stamp_paths.modelling_size`), so its tracked stamp, masks, positions and export need no
`--size` anywhere. An explicit `--size` writes `stamp<S>_*` beside the modelling stamps, in the
same band dir, and only the modelling-size files are tracked: a lens given a new
`stamp_size` needs its own `!data/stamps/**/stamp<S>_*` line in `.gitignore`. Every stamp side is rounded to an
EVEN number of 0.06" LW pixels (`nested_shape`): the stamp centre sits on the pixel corner
the mosaics share, which an odd side would move by half a pixel (15 mas SW, 30 mas LW) and
split the bands' centres — hence 6.96", not 7.00". A re-size about the same centre is an exact
central crop, so positions (arcsec from the centre) carry over unchanged; masks, being
per-pixel, do not. Size and variant key the names through
`stamp_paths.py` exactly as in the HST repo: the size is in every stamp filename, a variant
tags the sci/noise names, masks and positions keep the bare `stamp<S>_` prefix, the PSF is
plain `psf.fits`, and
`find_stamp` raises `AmbiguousStampError` if two reductions' stamps share a dir. One stamp per
band; a second variant is refused without `--force`.

**Centre = the deflector, on the shared grid.** Every filter's mosaic has `crval` at the
catalogue coordinate and `rotation=0`, so cutting at the catalogue position gives stamps
co-registered across filters by construction. **But the catalogue position is not always the
galaxy: B1938+666's APT coordinate is 0.479" E, 0.201" S of the lens core** (both bands agree,
and field sources tie the bands to 11 mas, so it is the coordinate, not the astrometry). A
stamp that far off breaks everything that assumes the lens is at (0, 0): the radial-profile
display in `make_positions.py`, centred masks, `mask_radius` at export. So a lens can carry a
measured `deflector_ra`/`deflector_dec` (+ `deflector_note`) in `info/samples/lens_samples.json`, and
the default `--center auto` cuts there. `ra`/`dec` are NOT edited to match — they are the
mosaics' CRVAL, and changing them would only take effect on an Image3 re-run. The offset from
CRVAL is snapped to whole 0.06" LW pixels (= 2 SW pixels), so each band's stamp moves by whole
pixels of its own grid and the SW/LW stamps stay nested about one sky point (verified: stamp
centres identical to 0 mas, pixels an exact shift of the catalogue-centred stamp); the lens
then sits ≤ 0.03" per axis from (0, 0) (B1938: 22 mas). `--center peak` is per band, so it
does NOT keep the bands co-registered, and where a ring outshines its lens (B1938 F277W) it
finds the ring. Whichever is used lands in the header (`CUTCENT`, `CUTRA`, `CUTDEC` = the
actual stamp centre) and in `info/provenance/lens_stamp_qc.json`. B1938 was re-cut this way 2026-10-04;
PSFs and NOISECOR are unaffected (neither depends on the stamp centre).

### Noise

`stamp<S>_noise.fits` = i2d `ERR` × `NOISECOR`, float64, 1e8 where SCI is NaN, ERR is non-finite
or ≤ 0, or WHT is 0 (those pixels get sci = 0). `ERR` = sqrt(VAR_POISSON + VAR_RNOISE +
VAR_FLAT), each variance resampled with the science weights — the total per-pixel sigma
including source Poisson noise, "read, not constructed". `NOISECOR` comes from
`info/overrides/noise_corr_factors.json` (`factors` keyed `NIRCAM/SW`, `NIRCAM/LW` or a filter;
`lens_overrides[sample][lens][FILT]`), source recorded as `NOISECRS`, the block scale it was
read at as `NOISESCL`, and the 1/f correlation length it does NOT cover as `NOISECRL`.

**Correlated noise — measured 2026-10-04 (`measure_corr_factor.py`, all 12 stamps,
`diagnostics/corr_factor/`).** Current factors: **SW 1.30, LW 1.03 at 0.2"**, plus a lens
override **B1938+666 F277W 1.5**. How they were chosen, and why not the HST recipe:

- Drizzle itself behaves: per-pixel C(0) = 0.45–0.55 in every SPT band (pixfrac 1,
  native→output 0.031→0.03 and 0.063→0.06 halve the per-pixel variance), and the
  drop-window ACF factor the HST repo applied comes out SW 1.17, LW 1.22 — an ERR deficit
  of the same size the HST repo saw.
- But that 1-px-window factor is blind to the residual 1/f (*striping* above: 6% of sigma,
  coherent over ~3" along detector rows). The blank-sky block-sum ratio shows it: it never
  plateaus (SW 1.04 at 0.1", 1.30 at 0.2", 2.0 at 0.5", 3.5 at 1", 9 at 3"; LW 0.83, 1.03,
  1.36, 1.85, 3.8). The full curves are in the JSON (`block_ratio_curve`) and are exported
  to the modelling project's `info.json` as `noise_correlation`.
- The applied factor is the block ratio at **0.2"**, roughly the image-plane footprint of a
  source pixel at these resolutions. This is a convention, not a plateau: a modelling run
  whose source pixels map to a coarser image-plane scale (high magnification, coarse
  pixelization — SPT0418-47 is μ ≈ 30) should rescale from the curve. The factor is a
  scalar: it encodes neither the anisotropy nor the scale dependence. autoarray 2026.9.27
  accepts a dense `noise_covariance_matrix` for parametric fits only; the inversion ignores
  it, so there is no consumer for the full structure yet (and a 3" SW mask is 31k px).
- **B1938+666 cannot be measured this way** (at 88 ks the 60" blank-sky region is dominated by
  unmasked faint galaxies, star halos and diffraction spikes: C(0) 12 and 103), so it has its
  own test, `split_noise_test.py`: the 21 dithers split into two interleaved halves (every
  detector of a dither together), each run through Image3 as the standard product is, and
  the difference A − B — pure noise with this dataset's own correlation structure, every
  astrophysical feature cancelled — measured against sqrt(ERR_A² + ERR_B²). This is the
  method for any deep or crowded field. Result (2026-10-04, 12" stamp region, 0.2"):
  **F115W 0.94, F277W 1.12**, applied as lens overrides. The curves (JSON `split_test`):

  | B1938+666 | per px | 0.1" | 0.2" | 0.3" | 0.5" | 1" |
  |---|---|---|---|---|---|---|
  | F115W | 0.75 | 0.74 | 0.94 | 1.03 | 1.28 | 1.75 |
  | F277W | 1.04 | 1.00 | 1.12 | 1.13 | 1.25 | 1.56 |

  Two things worth knowing. The F277W `ERR` IS low per pixel (ratio 1.04 where drizzle alone
  gives 0.7; the single-cal-frame test gave 1.46), but it cancels against the drizzle
  correlation by 0.2", so no per-pixel correction is applied; why the 8-group × 5-integration
  LW rate ERR is low per pixel is still open but no longer matters for the noise map. And the
  SW factor is far below the SPT channel's 1.30 because the 1/f is relatively weaker in
  MEDIUM8 8-group × 5-integration ramps than in TEMPLATES' 2–3-group BRIGHT2/SHALLOW2
  exposures (Rigby+25 §7.2 says as much) and the per-frame ERR has no deficit (1.07). The
  provisional values used earlier that day (channel 1.30 and an override of 1.5 from
  multiplying two measurements) were wrong by 40% and 35%: do not borrow factors across
  samples with different readout patterns.

Casertano's R for the drop/scale pair is stamped as `CASR` for information — it corrects
an image-estimated rms, not an ERR map, and must not be compared to `NOISECOR`.

## PSF (`scripts/make_psf.py`, `scripts/psf_models.py`)

```bash
uv run python scripts/make_psf.py --lens SPT2147-50 --filt F444W [--method auto|empirical|model]
bash scripts/run_psf_all.sh spt
```

The HST repo's empirical ePSF machinery, verbatim where it is instrument-agnostic: stars
from the full mosaic (lens masked to 5", no-coverage and edge masked), gates on peak S/N ≥
30, fitted FWHM within [0.75, 1.4] × the filter's PSF FWHM, ellipticity ≤ 0.15, crowding,
a 5% flux floor; photutils `EPSFBuilder` at oversample 2; validation; wing pedestal
subtraction; amplitude trim at 3e-4 of peak for the modelling kernel (1e-3 enclosed only 95%
of the F115W flux and overweighted the core; 3e-4 encloses 98% at 39 px = 1.17" SW); bootstrap/jackknife
error map. Products: `data/psf/<s>/<l>/<F>/psf_kernel.fits` (+`_err`, `psf.png`) and
`data/stamps/<s>/<l>/<F>/psf.fits` (+`_err`). Overrides in `info/overrides/psf_stars.json`.

NIRCam differences: `_INSTR` keys are `NIRCAM/SW` / `NIRCAM/LW`; the per-filter PSF FWHM
(JDox: F115W 0.040", F150W 0.050", F200W 0.066", F277W 0.092", F356W 0.116", F444W 0.145")
is scaled to the output pixel, so the SW bands are **undersampled** (1.3–2.2 px) and
oversample 2 is the floor; no mosaic-peak saturation gate (a saturated core is a NaN hole,
which the shape fit rejects); one pass, so no `psf`.

**Model tier = STPSF** at the lens's position on a contributing `_cal` detector
(`psf_models.model_psf`: `OVERDIST` output at 4× oversampling, measured OPD by date when the
server is reachable, rotated to North-up through the cal file's SIP-approximated CD matrix
with the HST repo's `_northup_M`, then the analytic drop-box broadening). Tagged
`PSFMETH=model_stpsf`, `PSFBROAD=analytic`. The HST repo found model PSFs unbroadened by the
resampling mismatched the data until injected and re-drizzled; the analytic box is its
calibrated stand-in (0.01 px on the HST test), not the real thing. For a 2'-field lens with
few stars this tier may be what you get for the SW bands — check `info/provenance/lens_psf.json`.

## Masks, arc masks, positions, QC (`make_masks.py`, `make_arc_masks.py`, `make_positions.py`, `make_dataset_subplots.py`, `make_qc_grids.py`)

Verbatim ports of the HST scripts (2026-10-01) with three mechanical changes: the sample
module is `lens_samples`, `_BAND_PRIORITY = ['F444W', 'F356W', 'F277W', 'F200W', 'F150W',
'F115W']` (the LW bands carry the dusty sources' signal — Lange+25 modelled F444W as the
highest-S/N band), and the provenance JSONs record `variant` (from the stamp's `REDUCVAR`)
instead of `bcfill`. Their docstrings and `--help` still quote HST examples (`f814W`,
`slacs_gold`) and a `--pass` flag that is accepted and ignored (`stamp_paths.find_prefix`
always answers `stamp<S>` for the lens's modelling size). The semantics are unchanged and matter:

- Masks are `al.Mask2D` convention, **True = excluded**; `make_masks.py` paints what to
  remove, `make_arc_masks.py` paints what to keep and saves it inverted.
- **The mask GUIs are native `al.Scribbler` (2026-10-08, autolens 2026.10.7.1).** The HST
  port hand-built everything the Scribbler lacked: a `_GuardedScribbler` subclass (motion
  guard, `draw_idle`, ×1.4 brush resize, 1 px floor, class-attribute title hack), an
  hstacked two-panel composite with a NaN gutter plus `fold_panels` to read it back, a
  burned-in proposal outline, overlay callables for position crosses and the contaminant
  edge, and its own percentile+asinh `stretched_display`. All of that is upstream now and
  the local copies are gone: `make_masks.draw_mask_gui` passes the raw S/N (or signal)
  `Array2D` with `proposal=`, `subtract_radial=`, `side_by_side=`, `panel_gap=6`,
  `positions=` (list of (y, x) arcsec), `mask_overlay=` (an `al.Mask2D`) and `title=`, and
  reads back `get_scribble_masks()` ('1' = add, '2' = erase) and `mask_from()`
  (`(proposal | added) & ~erased`). Consequences to know: brushes are **'1' white = add,
  '2' black = erase** (was green/red); the display stretch is the Scribbler's median/MAD
  arcsinh, so `--stretch/--asinh-a/--vmin-percent/--vmax-percent` are gone from
  `make_masks.py` and `make_arc_masks.py` (they survive in `make_positions.py`, whose
  Clicker panels are plain axes, and `make_masks._STRETCHES`/`stretched_display` stay for
  it); the proposal is a black-on-white contour rather than a 1 px burned-in line; the
  contaminant edge in `make_arc_masks.py` is black 'x's from autoarray's `derive_grid.edge`,
  which also runs along the stamp border; `--cross-size` defaults to the Scribbler's own
  (1.5% of the shorter side, ≥3 px); the arc QC PNG uses the same
  `display_util.radial_median_subtract` + `arcsinh_stretch` as the GUI's left panel.
  `reproject_mask_bool` is deliberately kept over `al.mask_2d_regridded_from`: ours
  transfers through the two bands' header WCS, upstream's by pixel scale + origin only.
- One draw per band; the next band starts from a reviewed proposal reprojected by WCS.
  Here the SW→LW reprojection is a 2:1 regrid, like the HST f160W case.
- Positions are marked once on the best band and broadcast pixel→sky→pixel; an empty file
  means "decided: none".
- **The band-registration check is field sources, not the deflector** (`band_tie`, 2026-10-04).
  It used to centroid the brightest object near each stamp's centre; on B1938 (stamps 0.5" off
  the lens, ring brighter than the lens in F277W) that found the lens core in F115W and the top
  of the ring in F277W and reported a 281 mas MISREGISTERED warning for bands that tie to
  11 mas. Now: compact sources > 2.5" from the centre, centroided in the same 0.24" sky window
  in both bands, median offset (≥ 3 sources). The SPT stamps hold 0 such sources at their
  depth, so there it falls back to the lens core, both bands iterated from the SAME sky point
  (the stamp centre), labelled `lens core (fallback)` — which is only right when the stamp is
  centred on the lens. Recorded as `band_tie_{mas,px,scatter_mas,n_sources,method}` in
  `info/provenance/lens_positions.json`.
- GUI orientation: North down, East left on screen (row 0 at the top). Quote offsets as
  ΔRA/ΔDec or (col, row).
- `make_qc_grids.py` is the HST `make_mosaics.py`, renamed because "mosaic" here means the
  Image3 product; it writes `data/qc/<sample>/`.

**First JWST use: B1938+666, 2026-10-04**, with the HST-port GUIs (before the native-Scribbler
rewrite). `make_positions.py` marked A and B on F277W and broadcast them to F115W;
`make_masks.py` drew the contaminant masks (F115W 27 515 px, F277W 6 854 px, provenance in
`info/provenance/lens_masks.json`); `make_dataset_subplots.py` rendered both bands. `make_arc_masks.py` and
`make_qc_grids.py` have still never run on a JWST stamp: expect small breakages (header cards,
the `--pass` plumbing) on first use and fix them in place. The native-Scribbler rewrite was
verified headless only (`backend='Agg'`, synthetic stamps, strokes injected through
`add_circle_to_scribble`); the first real TkAgg run is still to come.

## Export to the modelling project (`scripts/export_dataset.py`)

```bash
uv run python scripts/export_dataset.py --lens SPT2147-50 --dest <modelling-project>/data [--mask-radius 3.0]
```

Copies each band's stamp, noise map and PSF to `<dest>/<lens>/<FILT>/{data,noise_map,psf}.fits`,
the contaminant mask as `mask_extra_galaxies.fits` and the positions as `positions.json` when
they exist, and writes `info.json` with `pixel_scale`, `mask_radius`, the redshifts and the
provenance (i2d path, variant, jwst version, `NOISECOR`). This is the layout a PyAutoLens
SLaM-style dataset loader expects (`data`/`noise_map`/`psf` + `info.json`; mask and positions
optional). `mask_radius` is a modelling choice and lives only here.
`info/provenance/lens_exports.json` records what went where on this machine; it holds absolute local
paths, so it is gitignored.

## Data flow and directory layout

```
data/
  calibrated/<sample>/<lens>/pool/        MAST files, flat (uncal by default)
  calibrated/<sample>/<lens>/<FILT>/      hard links into pool/, by header FILTER
  stage1/  stage2/                        our rate / cal products
  mosaics[_<variant>]/<sample>/<lens>/<FILT>/   <lens>_<filt>_{asn.json,i2d.fits,i2d.png} + Image3 by-products
  stamps/<sample>/<lens>/<FILT>/          THE science tree, every size side by side (stamp<S>_*; only each
                                          lens's modelling size is tracked; stamp<S>.png and *_positions.png
                                          are gitignored QC renders, rebuilt by the scripts)
  psf/<sample>/<lens>/<FILT>/             archival kernels + psf.png
  qc[_<S>arcsec]/<sample>/                stamp grids
  reference_files/                        CRDS cache, stpsf-data/
  run_logs/
info/   samples/lens_samples.json (hand) · overrides/noise_corr_factors.json, psf_stars.json (hand; no psf_stars.json yet) ·
        provenance/ (the rest, written by the scripts; info_json.path() resolves a name)
```

Everything under `data/` is gitignored except `stamps/` and `qc/`; `diagnostics/`,
`output/`, `local/` are ignored (see `.gitignore` and `diagnostics/README.md`). Tracking JSONs
are `{sample: {lens: {FILT: ...}}}` through `info_json.py`, as in the HST repo. Product-dir
names are the FITS spelling, `F444W` (the HST repo's `f814W` casing is not used).

## What is verified and what is a port (2026-10-01)

Verified by running: `download_nircam.py` (SPT2147-50: 30 uncal, sorted F200W 24 / F277W
2 / F356W 2 / F444W 2); `uv sync` with jwst 3.0.0 + stpsf 2.2.0 + autolens; the jwst step
specs quoted above (`ResampleStep.spec`, `TweakRegStep.spec`, `CleanFlickerNoiseStep.spec`,
`JumpStep.spec`); stcal's sky subtraction at resample time.

Verified end to end on SPT2147-50 F444W (see *Current state*): `reduce_nircam.py`
(all three stages, with the CRDS pre-sync), `make_stamps.py`, `make_psf.py` empirical tier
(two photutils-3.0 fixes: `x_centroid`/`y_centroid` column names, a missing import),
`export_dataset.py`, `run_reduce_all.sh`. `make_dataset_subplots.py` runs and correctly
refuses a band with no mask yet.

Not yet exercised: the STPSF model tier of `make_psf.py` (needs stpsf-data),
`make_arc_masks.py`, `make_qc_grids.py`, `--tweakreg gaia`. Stubs: `detect_arcs.py`.
Exercised since: `measure_corr_factor.py` (12 stamps, 2026-10-04), `--start rate` and
`--flicker-by-channel` (SPT0418-47 F150W, 2026-10-02), `destripe_nircam.py`, and
`make_masks.py`, `make_positions.py` and `make_dataset_subplots.py` on B1938+666 (2026-10-04,
the HST-port GUIs; the native-Scribbler rewrite is verified headless only, see *Masks*).
