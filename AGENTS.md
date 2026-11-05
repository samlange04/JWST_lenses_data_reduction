# AGENTS.md

Guidance for any coding agent (and for humans) working in this repo. This file is the
**operational** reference: commands, layout, decisions, and the traps that silently produce
wrong products. Where a decision is stated as settled, a measurement was made and the choice
followed from it; the result is summarised here, so don't re-derive or re-litigate it without
new evidence. It is the JWST sibling of the AGENTS.md in
[HST_lenses_data_reduction](https://github.com/samlange04/HST_lenses_data_reduction) ("the HST
repo" below); where a decision was inherited from there it says so, and that file's
measurements are not restated here.

> **[`STATUS.md`](STATUS.md) is the to-do picture:** where every sample stands, the open
> decisions on individual lenses, and the next steps. Update it when a step is done.

> **AGENTS.md documents intent, not always state.** Before running a batch campaign or
> reporting what is outstanding, verify against source — argparse defaults, what the
> runner actually passes, tracking JSONs vs what is on disk.

## Current state (2026-11-02)

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
| 17 COWLS II lenses | cowls_spectacular | uncal at a 90" field, 802 files / 38 GB | F115W F150W F277W F444W, all 68 bands (2026-10-29, ~11 h incl. 43 GB of new CRDS darks; Image3 re-run 2026-10-30 for tweakreg, ~1 h at 4 in parallel) | all 68, 12" (re-cut 2026-11-01 on measured lens centres; COSJ095955+021900 2026-11-02) | STPSF injected per lens (rebuilt 2026-11-02 on the measured centres) | all 17 (2026-11-02; COSJ095920+015851 positions deliberately empty); extra-galaxy centres for the 3 `multi_galaxy` lenses |

**COWLS added 2026-10-29** (`cowls_spectacular`, the 17 COWLS II lenses, GO 1727
COSMOS-Web): the first survey-program sample, located by position and cut by detector
footprint (*Download*), reduced on 90" mosaics with pruned intermediates for disk
(*Reduction*). Verified on COSJ100013+023424 F444W: 7 detector files from two tiles,
tweakreg 145–162 sources per frame (but that first reduction aligned nothing; fixed and re-run 2026-10-30, see *Reduction*), 1030.7 s at the lens (4 × 257.7 s), the lens and arc at the
mosaic centre. The full batch then ran 12:31–23:40: 68 bands ok, every
exposure time at the lens equal to the footprint survey (COSJ100018+022138 SW 773 s, COSJ100024+015334 LW 515 s, COSJ100028+021928 SW 258 s),
no rate/rateints/crf left; kept on disk 38 GB uncal + 88 GB cal + 10 GB mosaics. Two downloads
died in a network outage at the MAST query, which had no retry; `with_retries` now wraps every
query, and a second `run_reduce_all.sh` pass picked them up. **Disk on macOS:** Time Machine's
hourly local snapshots keep pruned or deleted files' blocks until they are purged, so `df`
falls faster than the kept size suggests; macOS purges them under pressure.
Stamps cut 2026-10-30 at the default 12", with their own measured noise factors (*Noise*).
**COSJ095917+015424 sits ~2" from COSMOS-Web's southern edge:** its lens is covered,
but 16% of each SW and 30% of each LW stamp is off the survey (noise 1e8, `n_bad` in
`lens_stamp_qc.json`); every other COWLS stamp has 0–4 bad pixels.

**The whole SPT sample reduced in one `run_reduce_all.sh spt` pass (2026-10-02 02:06): 10 ok,
0 failed.** Per band: SW (4 detectors × 2 dithers) 220–250 s, SW F200W of SPT2147 (24 frames)
690 s, LW 60 s — after the references were cached; the CRDS pull dominated the wall clock
(30 GB in all, a 6.3 GB dark per SW detector at ~30 min each). tweakreg relative shifts
were 1–44 mas on every band (fit RMSE 0.10–0.19", i.e. the finder's centroid scatter on
galaxies, not a WCS problem). Weight uniformity over every 12" stamp 0.08–0.13 (< 0.2).
0 bad pixels in any stamp.

**PSFs: STPSF injected at the lens, all 80 bands (rebuilt 2026-10-31; *PSF*).** They were
empirical before: the SPT and B1938 bands from 2026-10-02, the COWLS bands pooled over the sample
from 2026-10-30. Then an audit found four biases in the star-built kernels and one problem no star
kernel can avoid in the undersampled bands. The model's charge diffusion is calibrated on 243
stars. Model FWHM / PSF stars / the empirical check's FWHM, from `info/provenance/lens_psf.json`:

| band | SPT0418-47 | SPT2147-50 | B1938+666 |
|---|---|---|---|
| F115W | 0.059" / 4 / 0.052" | – | 0.059" / 9 / 0.051" |
| F150W | 0.065" / 5 / 0.065" | – | – |
| F200W | 0.076" / 5 / 0.069" | 0.076" / 9 / 0.075" | – |
| F277W | 0.131" / 7 / 0.123" | 0.132" / 8 / 0.136" | 0.131" / 11 / 0.127" |
| F356W | 0.147" / 6 / 0.142" | 0.147" / 8 / 0.144" | – |
| F444W | 0.166" / 7 / 0.166" | 0.166" / 8 / 0.164" | – |

The checks run narrower than the model in the undersampled bands for the reason the model ships
(*PSF*, finding 4); in F444W they agree to 1%. Error maps combine the model-vs-star residual per
filter with the band's sub-pixel-phase scatter (error fraction 0.008–0.037). The old "two PSFs rest on three stars" caveat is
gone: no shipped PSF rests on its field's stars.

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
is set by `psf_models.py` at import (and by `setup_crds()`); STPSF downloads the files there on
first use (352 MB). Before 2026-10-30 only `setup_crds()` set it, which `make_psf.py` never
calls, so the first model build put them in STPSF's own default data directory, outside the repo. A build that never needs the
model tier never needs them.

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
make_psf.py         STPSF injected at the lens -> psf.fits (+ the field-star ePSF as its check)
make_psf_inject.py  STPSF into every cal frame + tweakreg/resample as the science -> the kernel
psf_star_check.py   each PSF star vs its injected twin -> charge-diffusion calibration, model error map
measure_lens_centres.py the lens core per band (LW-anchored) -> deflector_ra/dec, which make_stamps centres on
choose_best_band.py     GUI over the band overview: choose each lens's best band by eye -> best_band_visual
choose_primary_band.py  arc S/N per band, discounted below 5 PSF widths across theta_E -> each lens's primary band
make_masks.py / make_arc_masks.py / make_positions.py   GUIs, one draw per band (primary first), broadcast by WCS
make_extra_galaxies.py  GUI: the extra galaxies' centres of a multi_galaxy lens -> stamp<S>_extra_galaxies_centres.json
make_dataset_subplots.py / make_qc_grids.py              QC
make_band_overview.py   every band of a lens side by side (isophote-subtracted; + masks, extra-galaxy centres, primary band) -> <lens>/stamp<S>_bands.png
export_dataset.py   -> <dest>/<lens>/<FILT>/{data,noise_map,psf}.fits + info.json [+ mask, positions]
set_lens_category.py    put a lens in its sample's category (COWLS: prime / multi_galaxy) and move its stamp dir
```

**NIRCam only.** TEMPLATES also took MIRI imaging
(F560W–F2100W, 0.11"/px) and NIRSpec G395M + MIRI MRS IFU cubes of both SPT lenses; GO
8281 is NIRCam only. If MIRI is ever wanted: the pool download already fetches only
`NRC_IMAGE` exposures (`download_nircam.sort_pool` filters on `EXP_TYPE`), so a MIRI path
needs its own `instrument_name='MIRI/IMAGE'` query and a `mirimage` branch in the sort.
PyAutoReduce has no MIRI support either.

## Lens samples (`info/samples/lens_samples.json`, read only by `scripts/lens_samples.py`)

**Only a spectroscopic redshift is a confirmed redshift (2026-11-02).** A photometric one may
be shown or exported, but always labelled.
- Every redshift in `lens_samples.json` carries `redshift_lens_kind` / `redshift_source_kind`,
  starting `spec` or `photo-z` and naming its source. `lens_samples.redshift_kinds` raises on a
  redshift without one.
- Figures print redshifts through `lens_samples.redshift_text` ('0.577 (photo-z)').
- `export_dataset.py` writes `redshift_*_kind` ('spectroscopic' | 'photometric') and
  `redshift_*_ref` beside each value.
- SPT and B1938+666 are spectroscopic throughout. SPT lenses: optical/NIR spectroscopy (Rotermund
  et al. in prep, as tabulated by Spilker+16); SPT sources: CO (Weiß+13). B1938+666: Keck lens
  spectrum (Tonry & Kochanek 2000), CO from the source (Riechers+11).

**`--lens` never needs `--sample` (2026-11-02).** A lens is in exactly one sample (`sample_of`
raises otherwise), so every script finds it through `lens_samples.resolve_sample(parser, args)`
right after parsing.
- An unknown lens is an error naming the closest match.
- A `--sample` that contradicts the lens is an error.
- Without `--lens`, each script keeps its old behaviour: the GUIs default to `spt`, the
  sample-wide tools require `--sample`, and the overview and primary-band tools run every sample.
- New scripts call `resolve_sample` too, rather than `a.sample or sample_of(a.lens)`.

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
| `cowls_spectacular` | 1727 COSMOS-Web, PI Kartaltepe & Casey, Cycle 1 | the 17 COWLS II lenses | by position, tiles `CWEBTILE-*` | F115W+F277W, F150W+F444W, SHALLOW4 5 grp × 1 int, 258 s per exposure. **Exposures over the lens: 4 per filter for C E F I L M O Q; J 3 SW / 4 LW; K 4 SW / 2 LW; 2 for A B D G H P; N 1 SW / 2 LW** (MAST footprints, 2026-10-29) |

**`cowls_spectacular` (added 2026-10-29)** is COWLS II's Table 1 (Mahler et al. 2025, MNRAS
544, L8): the 17 "spectacular" lenses, the top tier of the COSMOS-Web Lens Survey; lens keys
are the COWLS IDs, `cowls_letter` the paper's A–Q. `ra`/`dec` are the COSMOS-Web catalogue
positions OF THE LENS GALAXY (Shuntov+24), so unlike an APT coordinate they need no
`deflector_ra`. `theta_e` is COWLS I's PyAutoLens value, for orientation. Redshifts carry
their source in `redshift_*_kind` (DESI spec, COSMOS-Web photo-z, van der Wel+13);
COSJ100119+014849 has no lens redshift and only COSJ100018+022138, COSJ100024+015334 and
COSJ100024+021749 have source redshifts, so the rest export `null`. Spectroscopic: 11 lens
redshifts and all 3 source redshifts, so both are spectroscopic only for COSJ100018+022138 and
COSJ100024+021749. The other 5 lens redshifts are photometric (COSJ095917+015424,
COSJ095955+021900, COSJ100013+023424, COSJ100024+015334, COSJ100025+015245). Depth at the
lens is set by where it falls in the COSMOS-Web dither pattern, not by the tile: COSJ100028+021928's SW
stamp rests on ONE exposure, so Image3's outlier detection has nothing to compare and its
cosmic rays are caught by `jump` alone — look at it before trusting faint SW structure.
Every lens has all four filters. Only GO 1727 is downloaded: other JWST programs that image
the COSMOS field are not part of this sample.

**Coverage edges cross most COWLS lenses; a step in the noise map there is real depth, not a bad
combination (2026-11-02).**
- In 14 of 17 lenses, the number of exposures per pixel (the i2d `CON` bitmask) changes within
  ~2θ_E of the lens. SW and LW edges differ, since the detectors' footprints do.
- On COSJ095953+023319 F444W a 2|4-exposure edge runs within ~0.1" of the lens core. Image 0
  lies on the 2-exposure side; the lens and the other images lie on the 4-exposure side.
  - The noise map steps by 1.47x across it, against the expected sqrt(2).
  - Blank-sky scatter / noise map is 0.65 and 0.66 on the two sides, so the map is right on both.
  - The sky does not step in LW (F444W 0.0122 vs 0.0127; F277W 0.0181 vs 0.0189).
  - F115W shows a small sky offset, 0.053 vs 0.059 MJy/sr (about 0.2 of the per-pixel sigma).
- The fit takes the depth from the noise map. The PSF kernel is built for the lens's own frames
  (*PSF*), so an image on the other side of an edge sees a slightly different resampled PSF:
  ~1.5% in F444W, more in SW.
- Scratch check: `diagnostics/coverage_step.py LENS` (frames per pixel, noise vs scatter, sky per
  side).

Coordinates: APT fixed-target positions (B1938+666 19:38:25.28 +66:48:52.9; SPT0418-47
04:18:39.68 −47:51:52.7; SPT2147-50 21:47:19.01 −50:35:54.5), which agree with the MAST
`s_ra/s_dec`. Redshifts: B1938 z_l 0.881 / z_s 2.059 (APT, Tonry & Kochanek 2000, Riechers
2011); SPT from Lange et al. 2025 §2 (Weiss+13, Reuter+20; the lens redshifts are spectroscopic, Spilker+16 Table 1). Published θ_E: SPT0418 1.207"
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

**Survey programs: by position, cut by detector footprint** (`"mast_query": "position"` in the
sample block; `cowls_spectacular`, 2026-10-29). COSMOS-Web's targets are tiles
(`CWEBTILE-0-4`), and one visit is ~10 arcmin² of which a lens needs one detector or two, so
target name is useless and "the whole visit" is 4× too much. `query_position` takes every
NIRCam/IMAGE observation of the program within the mosaic field's half-diagonal; then
`footprint_roots` reads each detector file's `s_region` from MAST's JWST NIRCam keyword
service (`Mast.Jwst.Filtered.Nircam`, which lists **cal** files only — a root like
`jw01727009001_02101_00001_nrca3` names the same exposure+detector at every level) and keeps
the uncal files whose footprint overlaps the `--field` box (default: the sample's
`mosaic_field`, else 150", the same default `reduce_nircam.py` takes; download at least the
field you will reduce at). A file MAST gives no footprint for is
kept and counted (`n_files_no_footprint`). The `MastMissions(mission='jwst')` region search is
NOT a substitute: it returns one row per exposure with one representative detector, and drops
exposures. Neighbouring lenses share exposures, so a file already in another lens's pool of the
same sample is hard-linked from there, and `reduce_nircam.py` likewise links a rate or cal a
neighbour already made (`_link_from_neighbour`; never in the `_destriped` trees, whose rates
carry the lens's own object mask). Sizes for `cowls_spectacular` (2026-10-29): 1487 unique
detector files / 75 GB uncal at a 150" field, 802 / 40 GB at 90". The overlap test closes
both polygons explicitly (`_overlaps_box`): matplotlib's `intersects_path` on an open Path
skips the last→first edge, which dropped a lens-covering F444W exposure on the first try. MAST position queries occasionally hang with no CPU for
>10 min; kill and re-run (the download is idempotent).

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

**Per-sample field and pruning (`cowls_spectacular`, 2026-10-29).** A sample may set
`mosaic_field` (arcsec; `--field` defaults to it, and so does `download_nircam.py`) and
`prune_intermediates`. Why: a pipelined exposure costs ~290 MB of stage products (rate 84,
rateints 84, cal 118 MB) against ~50 MB of 5-group uncal, plus a ~120 MB Image3 `crf` per input
per lens, which put COWLS at 150" at ~420 GB with 248 GB free. So COWLS mosaics are 90" and,
with pruning on, each rate/rateints is deleted once its cal exists and the `crf` files once
the mosaic exists: the kept state is uncal + cal (~130 GB for the 17 lenses). A pruned band is
not re-run through Detector1 when its cal is there (`run_detector1(cal_dir=...)`); `--destripe`
re-makes the rates it needs. 90" is ~2.25 arcmin² per lens for `make_psf.py`'s stars and for
tweakreg (`measure_corr_factor.py`'s ±30" region fits).

**COWLS tweakreg: LW lens-first, SW from LW (2026-10-30; all 68 bands re-run from the kept cal
files).** The first reduction aligned nothing. With jwst's default `expand_refcat=False`, tweakwcs
takes the first group in FILE ORDER as the sole reference: on COSJ100013+023424 F444W a neighbouring tile's
frame (obs 007), against which every lens-covering group found 0–1 matches (`minobj=15`), so no
frame moved, while `cal_step.tweakreg` still said COMPLETE. `expand_refcat=True` alone was not
enough: it starts from the best-overlapping pair anywhere in the 90" field, which on COSJ095914+021219 F444W
was a neighbouring visit that the lens frames matched with only 4 sources. Two sample settings fix it
(`info/samples/lens_samples.json`, read by `lens_samples.py`):

- `tweakreg_lens_first`: the cal files covering the deflector lead the association
  (`reduce_nircam.lens_first_order`), and tweakreg runs with `expand_refcat=True,
  enforce_user_order=True`. The lens frames therefore align to each other first, and the
  neighbours join the growing reference. On LW (34 bands): 198 groups aligned, 48 failed, and
  every lens-covering group aligned except COSJ100018+022138's obs 053 exposure 1 (3 matches in both LW bands,
  so it stays a-priori). Fit RMSE 0.03–0.20" (5–95%). Offsets 8 mas median, 27 at the 90th
  percentile, 50 max. The lens frames of one band moved 2–42 mas relative to each other (median 19).
- `tweakreg_sw_from_lw`: SW is not fitted. Each SW frame takes the offset tweakreg gave its own
  exposure's LW frames (SW and LW are exposed together through one pointing):
  - `apply_offsets` moves copies of the cal files by `shift_wcs`, exact to 0.001 mas across the
    detector, and Image3 runs with tweakreg skipped;
  - an exposure with no LW offset stays a-priori (0–1 frames per band);
  - why: fitted on their own, the SHALLOW4 SW frames gave RMSE 0.2–0.4" on 10–50 matches, and their
    shifts disagreed with the same exposures' LW shifts by a median 22 mas (max 113) over 204
    exposures. On COSJ100024+015334 one visit's four F150W dithers came out up to 125 mas apart.

Each band's `lens_products.json` record carries `tweak_offsets_mas` ({rootname: [dRA cos dec,
dDec]}: LW measured from the crf files before pruning, equal to tweakreg's own XSH/YSH to 0.01 mas;
SW the offsets applied), `tweakreg` (`relative`, or `from_lw` for SW) and `tweakreg_lens_first`.
`run_image3` prints tweakreg's per-group outcome (reference, matches, shift, RMSE) into the band's
log, which stpipe otherwise does not: a tweakreg that aligns nothing looks complete.
`make_psf_inject.py` reproduces both routes (re-fits LW, applies the recorded offsets to SW).

`lens_exptime.json` is the exposure time AT THE LENS: EFFEXPTM once per exposure over the cal
files whose `S_REGION` covers the deflector (`exptime_at`), since a survey mosaic also holds
neighbouring tiles' exposures that never see it. Identical to the old per-exposure sum on every
SPT and B1938 band (checked 2026-10-29).

### Non-default pipeline settings, and why

| stage | setting | why |
|---|---|---|
| Detector1 | `jump.expand_large_events=True` | snowball flagging for NIR detectors. The CRDS `pars-jumpstep` file turns it on for NIRCam anyway; set explicitly so a context change cannot turn it off silently |
| Detector1 | `clean_flicker_noise.skip=False` | **1/f striping removed on the ramp**, with sources masked at 2σ (`fit_method=median`, Willott's image1overf algorithm, `background_method=median`). Skipped by default in jwst 3.0.0 (JDox *1/f noise*). It is the dominant correlated-noise term in a NIRCam frame and its scale (10–100 px stripes) is exactly the lens's. `--flicker-by-channel` adds a per-amplifier fit. **JDox caveat: a factor-10 gain for 2–3-group ramps, but "for very long ramps it can make things worse"** — compare a stamp with and without (`--start rate` gives the without, cheaply) before trusting it on B1938's 8-group MEDIUM8 data |
| Image2 | `resample.skip=True` | per-exposure i2d previews are dead weight |
| Image3 | `tweakreg`: relative only by default | aligns the dithers to each other (IRAFStarFinder; CRDS `pars-tweakregstep` for NIRCam: `minobj=15`, `fitgeometry=shift`, `searchrad=2`). A sample may set `tweakreg_lens_first` / `tweakreg_sw_from_lw` (COWLS; see above). `--tweakreg gaia` adds `abs_refcat=GAIADR3`; `skip` for a field where it finds too few sources. **A failed tweakreg is not fatal**: jwst logs it and keeps the a-priori WCS, which for JWST is good to ~0.1" absolute and to mas relative within a visit — nothing like WFPC2. TEMPLATES found Gaia alignment broke SW/LW registration (jwst issue 7993) and ended up aligning SW to a Gaia-tied F277W catalogue per module |
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
- **The HST repo's empirical PSF tier has the binning bias, not fixed there** (*PSF*, finding
  1: ACS/WFC +8–21% FWHM). The same goes for the pedestal subtraction, and the galaxy gate needs a
  resampled-model reference there too.
- **COSJ100028+021928 F115W's empirical check is broken** (a single SW exposure); the shipped
  model is unaffected.
- **Tweakreg on the other samples** is unchanged. They were not hit by the file-order trap: the
  injection re-runs show SPT frames moving 0–45 mas and B1938+666 F115W's lens frames 0–20 mas.
  Their records have no `tweak_offsets_mas` until they are re-run.
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

**Every lens has a measured centre since 2026-11-01 (`measure_lens_centres.py`).** The other
catalogue positions miss the lens too, by 20–50 mas typically and by ~0.4" for SPT2147-50 (its
APT coordinate: 359 mas W, 178 mas S of the core), COSJ095917+015424 and COSJ095920+015851, then
0.15" for COSJ095953+023319 and COSJ100013+023424. The miss is the catalogue's error plus our
mosaics' absolute astrometry (relative alignment only).
- **How it is measured.** Per band, the core is the brightest 1-px-smoothed pixel within 0.5",
  parabola-refined. The LW bands, where the lens's old stars dominate, anchor it; every band
  within 60 mas of the LW median votes, and the deflector is the median of the voters.
- **Why the LW anchor.** In COSJ100025+015245's SW bands the lensed images peak 0.46" from the
  lens, and COSJ100119+014849's SW peaks sit 60–100 mas off, so both use LW alone.
- **Why not a centroid.** A 0.15" flux-weighted centroid iterated from the stamp centre creeps
  toward asymmetric light and stops short of a core 0.4" away (SPT2147-50: −194 mas against −359).
- **The result.** The voting bands agree to 5–20 mas. B1938+666 keeps its hand-measured centre.
  `deflector_ra/dec/note` are written for the 19 others, and all 78 SPT and COWLS stamps were
  re-cut; each lens now sits within 39 mas of its stamp centre (the LW snap).
- **Masks moved with the stamps.** The COWLS F444W masks drawn by then were moved by the grid's
  whole-pixel shift (0 to (−3, +6) LW px), with newly exposed edge pixels copying the edge. Every
  masked sky position was checked to stay masked, and `lens_masks.json` records the shift
  (`recut_2026_11_01`).
- **Do not use `reproject_mask_bool` for this.** Its nearest-neighbour WCS map drops masked
  pixels on the stamp border (a 0-px shift lost 45–160 px).
- **The primary bands were re-measured** on the centred stamps. Four changed: SPT2147-50 and
  COSJ095917+015424 to F444W, COSJ100047+015023 to F277W, and COSJ100028+021928 became
  measurable (F444W). The old stamps and masks are in
  `diagnostics/recut_backup_20261101/` (gitignored).
- **A catalogue position can sit on the wrong object: COSJ095955+021900 (2026-11-02).** Its
  COWLS II Table 1 position lies on a lens-coloured knot. The lens is a galaxy 0.99" NE of it
  (+0.27" E, +1.03" N of ra/dec), 9x brighter in F277W, and COWLS II Fig. 2 (panel G) centres on
  that galaxy. The 0.5" search took the knot, and the band overview's isophote fit then failed in
  every band. Two changes:
  - `measure_lens_centres.py` now refuses to write a lens with a peak ≥ 3x brighter than the
    chosen core within 2.5" in an LW band. Only COSJ095955+021900 trips it. `--near DE,DN`
    (arcsec from ra/dec) centres the search on the real lens.
  - The stamps were re-cut on the new centre. The F277W mask moved by the exact whole-pixel shift
    of (−5, +15) LW px. The lens then went to `multi_galaxy` and that mask was deleted, to be
    redrawn (a copy is in `diagnostics/recentre_backup_20261102/`, gitignored).

**Lens categories (`cowls_spectacular`, 2026-11-02).** A sample may list `lens_categories` in
`lens_samples.json`, and each of its lenses then carries `category` (+ `category_note`). Its
stamps live one level deeper, in `data/stamps/<sample>/<category>/<lens>/`.
- COWLS: `prime` has one deflector, with its neighbours masked as contaminants. `multi_galaxy`
  means more than one galaxy's mass has to be modelled: a second lens, or a perturber near the arcs.
- `multi_galaxy` lenses (2026-11-02):
  - COSJ100119+014849: the round galaxy 1.7" SE is a second lens, 0.56" from the ring.
  - COSJ095955+021900: a group-scale lens (θ_E 2.11"). An elongated galaxy 3.9" SE, about 1.3"
    from the arc, has 0.30x the lens's F444W light, with colours within 0.25 mag of the lens's.
    There are also a compact galaxy 1.15" E (inside the ring, 0.10x) and another 2.6" N (0.11x).
    Light ratios are in r < 0.25" apertures.
  - COSJ100013+023424: two compact sources inside the ring (θ_E 1.45") carry the lens's colours to
    ~0.2 mag. One is bright, 0.65" S, a second nucleus or merging companion; the other is a knot
    0.85" NE. The lensed arc (E) and its candidate counter-image (0.58" WSW) are bright only in
    F277W and F444W.
- **Extra-galaxy centres** (`make_extra_galaxies.py`): for each `multi_galaxy` lens, click the
  centre of every galaxy besides the main deflector on its primary band, in the positions GUI.
  - Clicks snap to the brightest pixel.
  - The result goes to every band as `stamp<S>_extra_galaxies_centres.json`, reprojected through
    sky coordinates. It is one `al.Grid2DIrregular` of autoarray (y, x) arcsec (+y South, +x West),
    the file autolens_workspace's multi-galaxy examples load.
  - The record is `lens_extra_galaxies.json`, which also gives the centres as (East, North).
  - `export_dataset.py` ships the file as `extra_galaxies_centres.json`. The band overview marks
    the centres with a cyan x.
  - Masked pixels are outlined, not blanked, so a masked galaxy can still be clicked.
  - The mask and a centre do different things: the mask removes a galaxy's LIGHT from the fit,
    the centre adds its MASS to the model. A faint satellite near the arcs is often best both
    masked and given a centre (COSJ100013+023424's NE knot, 2026-11-02).
- **Every tool reaches a lens through `stamp_paths.lens_stamp_dir` / `stamp_dir` / `band_dirs`.**
  Never join `<sample>/<lens>` by hand, and never glob `<sample>/*/*`, or a categorised lens
  silently drops out of the sweep. `band_dirs` lists lenses from the roster, so both layouts are found.
- `set_lens_category.py` changes a lens's category and moves its whole dir with `os.rename`.
- `export_dataset.py` writes `lens_category` into `info.json`, and keeps the `<dest>/<lens>/` layout flat.
- Only the stamp tree is categorised. The mosaics, PSF and stage trees stay flat.

### Noise

`stamp<S>_noise.fits` = i2d `ERR` × `NOISECOR`, float64, 1e8 where SCI is NaN, ERR is non-finite
or ≤ 0, or WHT is 0 (those pixels get sci = 0). `ERR` = sqrt(VAR_POISSON + VAR_RNOISE +
VAR_FLAT), each variance resampled with the science weights — the total per-pixel sigma
including source Poisson noise, "read, not constructed". `NOISECOR` comes from
`info/overrides/noise_corr_factors.json` (`factors` keyed `NIRCAM/SW`, `NIRCAM/LW` or a filter;
`lens_overrides[sample][lens][FILT]`), source recorded as `NOISECRS`, the block scale it was
read at as `NOISESCL`, and the 1/f correlation length it does NOT cover as `NOISECRL`.
**`factors` applies only to the samples in `factors_samples` (`spt`, where it was measured);**
any other sample takes `sample_factors[sample]` (same keys) or per-lens `lens_overrides`, and
`make_stamps.py` refuses a sample with neither (2026-10-29, when `cowls_spectacular` arrived
with SHALLOW4 5-group ramps — see the readout-pattern warning below). For a new sample: cut
with `--corr-factor 1.0`, measure, add `sample_factors`, re-cut. **COWLS, measured 2026-10-30
on all 68 stamps (`measure_corr_factor.py --out ..._cowls_spectacular.json`), per FILTER:
F115W 1.25, F150W 1.22, F277W 1.03, F444W 0.95 at 0.2"** (16–84% ranges ±0.02). Per filter
because F277W > F444W in all 17 lenses and F115W > F150W in 16 of 17, a split larger than the
scatter; no dependence on depth (COSJ100028+021928's one SW exposure measures like the 4-exposure lenses).
Curves in `sample_factors.cowls_spectacular.block_ratio_curve`. Re-measured after the 2026-10-30
Image3 re-run (*Reduction*): F115W 1.25, F150W 1.21, F277W 1.03, F444W 0.95. That is unchanged
within the scatter, so the factors were kept. The channel medians come from
interpolating each stamp's block-ratio curve to the scales and taking the median, which
reproduces the SPT `factors` to 0.01.

**Correlated noise — measured 2026-10-04 (`measure_corr_factor.py`, all 12 stamps,
`diagnostics/corr_factor/`).** Current factors: **SW 1.30, LW 1.03 at 0.2"**, plus lens
overrides **B1938+666 F115W 0.94, F277W 1.12** (the split-dither test below). How they were chosen, and why not the HST recipe:

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

## PSF (`scripts/make_psf.py`, `scripts/make_psf_inject.py`, `scripts/psf_star_check.py`, `scripts/psf_models.py`)

```bash
uv run python scripts/make_psf.py --lens SPT2147-50 --filt F444W [--method auto|model|empirical]
bash scripts/run_psf_all.sh spt
uv run python scripts/psf_star_check.py --lens SPT2147-50 --filt F444W   # model vs real stars
bash scripts/run_psf_star_check_all.sh 4                                  # every band, 4 at a time
uv run python scripts/psf_star_check.py --calibrate | --error-maps
```

**The shipped PSF is STPSF injected at the lens (since 2026-10-31; every one of the 80 bands).**
`--method auto` (the default) and `model` ship `PSFMETH=inject_stpsf`, `PSFBROAD=injection`: the
model PSF put into every cal frame and resampled exactly as the science was (*Model tier* below).
STPSF's charge diffusion is calibrated against the real stars (*Calibration*), and the error map
is the measured model-vs-star residual (*Error map*). Beside it the empirical ePSF from the field
stars is built as a check and stored as `psf_kernel_empirical.fits`, compared in the record's
`empirical_check` (FWHM, encircled energy within 1/2/3/5 px, core L1 to the model).

Fallbacks:
- `--method empirical` ships the ePSF, with a bootstrap/jackknife error map.
- `auto` falls back to the ePSF if the injection fails.
- With too few stars as well, it falls back to STPSF at one detector with the analytic drop box
  (`model_stpsf`). That box is too narrow: SPT2147-50 F444W 0.154", against 0.164" injected.

Why the model and not the stars: the audit below. In short:
- the ePSF reduction had four biases, now fixed (*Empirical tier*);
- one problem cannot be fixed in a star-built kernel at all. In the undersampled bands a bright
  star's resampled core is not what a faint arc's is (finding 4). The model, injected at the lens
  with the lens's own frames and weights, is.

Products:
- `data/psf/<s>/<l>/<F>/psf_kernel.fits` (+`_err`, `psf.png`, `psf_kernel_empirical.fits`);
- `data/stamps/<s>/<l>/<F>/psf.fits` (+`psf_err.fits`), the amplitude-trimmed modelling kernel,
  cut at 3e-4 of peak.

Overrides go in `info/overrides/psf_stars.json`. The trim threshold is unchanged, but the trimmed
sizes grew (SW 33–43 px, LW 31–41 px; F444W keeps its full 41 px): the noiseless model keeps the
real wings that the old pedestal subtraction cut off.

Rebuilt 2026-10-31, and on 2026-11-01 with the phase-scatter error term and the 20 short-grid
bands re-done (*Model tier*). The 78 SPT and COWLS bands were rebuilt again on 2026-11-02, because
the injection grid is centred on the lens and every lens centre had been re-measured (*Stamps*;
COSJ095955+021900's by 0.99"). FWHMs moved by a median −0.1%, −3.6% to +1.5%; the largest was
COSJ100012+022015 F277W, 0.135" → 0.130". B1938+666's hand-measured centre did not move, so its
two bands were not rebuilt. FWHM ranges by filter (lenses differ by their dithers and depth):

| filter | bands | FWHM | | filter | bands | FWHM |
|---|---|---|---|---|---|---|
| F115W | 19 | 0.058–0.061" | | F277W | 20 | 0.129–0.133" |
| F150W | 18 | 0.065–0.067" | | F356W | 2 | 0.146–0.147" |
| F200W | 2 | 0.076" | | F444W | 19 | 0.165–0.166" |

Against the previous shipped PSFs (empirical, or COWLS pooled), new/old FWHM:
- the undersampled bands broadened: COWLS F115W +9 to +16%, F277W +1 to +8%; B1938+666 +8%;
- the well-sampled ones narrowed by 1–2%: F444W, F356W, and the few-star SPT SW builds.

**Model tier** (`make_psf_inject.py`; the HST repo's route, which it made canonical there):
- tweakreg is re-run on the band's real cal frames, in the recorded order (the rootnames in
  `lens_products.json`). It goes through an Image3Pipeline built from `reduce_nircam.image3_steps`
  and the CRDS parameter references, so the injected frames carry the science WCS corrections. A
  `from_lw` SW band instead gets its recorded `tweak_offsets_mas` applied, as the science did.
  Each frame's shift is recorded as `tweak_shift_mas` (SPT 0–45 mas). COWLS keeps its cal files,
  so pruning costs nothing here.
- Each frame's SCI is zeroed (NaN stays NaN) and STPSF `OVERDIST` is added: 4× oversampled, with
  distortion, charge diffusion and IPC included (IPC rightly, since Detector1 skips the ipc step
  for NIRCam). It is pixel-integrated and sampled at each star's sub-pixel phase. ERR, DQ and the
  variances are untouched, so the ivm weights are the science ones. One STPSF per frame, with the
  measured OPD by date.
- **A 5×5 grid of stars** sits around the deflector, 1.5 kernels apart, each on an output-pixel
  centre. It is resampled with the science parameters onto a sub-grid of the science grid (same
  crval/scale/rotation, crpix moved by whole pixels; checked to 1e-3 px for every star). The kernel
  is the MEAN of the stars that lie wholly on exactly the frames the lens does.
- **At least 12 stars (`MIN_PHASE_STARS`).** Near detector edges few grid stars share the lens's
  frames: before 2026-11-01, 20 of 80 kernels averaged 1–11 stars, and 7 of them (COSJ095950+022057,
  COSJ100018+022138 and COSJ100024+015334 in SW, and all of COSJ100024+015334) were a SINGLE star, i.e. one phase. Now passes follow with the whole grid
  shifted by 1–3 output pixels (`PHASE_SHIFTS`) until 12 stars are averaged. Each pass puts the star
  at the lens at a new phase on every detector while keeping it on the lens's frames; it is accepted
  whatever its coverage, as the lens star always was, since the lens itself can sit near a detector
  edge (COSJ100024+015334: 12 passes). `n_stars`/`n_passes` are recorded per band. The bands that already had
  12 stars are bit-identical.
- Why a grid: with 2–4 dithers an undersampled star's resampled shape depends on its sub-pixel
  phase on the detectors. Single injected stars a pixel or two apart on SPT0418-47 F115W gave
  Gaussian FWHMs of 0.049–0.064", so one star is one random phase. LW F444W varies by only ±1.5%.
- skymatch and outlier_detection are not run (no sky, no cosmic rays). Runtime is 15–70 s per
  band, ~5 min for B1938+666 F277W (42 frames, on-disk library) and ~35 min for F115W (168 frames).
- STPSF fetches each frame's measured OPD from MAST, and that query has no timeout of its own: one
  stalled read hung a B1938 build for 20 min with no CPU. `stpsf_detector_psf` now bounds each read
  (`OPD_TIMEOUT` = 120 s) and retries 3 times before falling back to the default OPD, which it
  records as `opd: default`.
- `make_psf_inject.py --lens L --filt F` alone writes `psf_kernel_injected.fits` and
  `info/provenance/lens_psf_injected.json`, touching neither `psf.fits` nor `lens_psf.json`. Those
  records are from 2026-10-30, before the calibration, so they carry STPSF's default charge
  diffusion; the shipped injections are in `lens_psf.json` (`model_info.injection`).

**Calibration: STPSF's charge diffusion against the stars (`psf_star_check.py`, 2026-10-31).**
The method:
- Every band's PSF stars (the empirical tier's selection) get a noiseless twin: STPSF injected at
  the star's own sky position into the same cal frames, so it sits at the same sub-pixel phase
  with the same frames and ivm weights (`make_psf_inject.injected_mosaic`).
- Per star, the record holds real and twin FWHM, peak fractions, the core fit real = a·twin + b,
  and an `extended` flag (real more than 15% broader). Records in
  `info/provenance/lens_psf_starcheck.json`; crops in `data/psf/<s>/<l>/<F>/star_check.npz`.
- `--calibrate` takes each star (peak S/N ≥ 100, real/twin within ±15%) and finds the extra
  Gaussian blur of its twin that minimises the core χ²; the median per channel is the result.
- STPSF's NIRCam widths (SW 0.0062", LW 0.018") are, in its own words, placeholders "to be
  updated based on comparisons with data and ePSFs".
- The blur is applied to the resampled star, standing in for one on the detector, so the
  calibration iterates: re-run the stars, re-calibrate, and take the secant zero of residual²
  against width² (the `iterations` log in `info/overrides/psf_model_calibration.json`).

Three passes, 243 stars:

| channel | pass 1 residual | after pass 1 | pass 2 residual | after pass 2 | pass 3 residual | applied |
|---|---|---|---|---|---|---|
| SW | 4.3 mas | 7.5 mas | 2.8 mas | 8.36 mas | 0.7 mas | **8.4 mas** |
| LW | 7.9 mas | 19.7 mas | 4.4 mas | 20.37 mas | 1.7 mas | **20.5 mas** |

That is an extra 0.13–0.14 detector px in both channels, consistent with a detector-level blur.
Per filter: SW 2.9/4.4/5.6 mas (F115W/F150W/F200W), LW 7.6–8.3 mas, all inside each other's
16–84% ranges, so one width per channel. After calibration the genuine stars' real/twin FWHM is
1.003 (F115W), 1.003 (F150W), 1.007 (F200W), 1.016 (F277W), 1.011 (F356W) and 1.008 (F444W),
medians with standard errors 0.003–0.008. Before it was 1.014–1.032.

The trap that cost one wrong answer: scipy's `gaussian_filter` truncates its kernel at 4σ, so it
does nothing below σ ≈ 0.13 px and is crude below ≈ 0.5 px. The first calibration therefore "found"
0.33 px, the first σ that moved anything. `psf_star_check.blur` is an exact Fourier-space Gaussian.

**Error map: two terms, in quadrature (`err_method` `model_vs_stars+phase`).**
- **Model vs stars** (`psf_star_check.py --error-maps`): per filter, the per-pixel rms of the
  flux-normalised real star about its twin, beyond its own ERR (sigma-clipped mean of r² − e², the
  calibration's stars), in `data/psf/_model_error/<FILT>.fits`. Integrated: F115W 0.021, F150W
  0.013, F200W 0.012, F277W 0.013, F356W 0.012, F444W 0.005. It is the same map for every lens of a
  filter, at the stars' sub-pixel phases, 41 px SW / 31 px LW and zero beyond.
- **Sub-pixel phase** (since 2026-11-01): per band, the per-pixel std of the injected stars about
  the kernel. The kernel is their mean, the PSF of extended emission. A COMPACT source, a bright lens
  core, sees one phase's PSF, which scatters about the mean by this much. The term is
  largest where a lens has the fewest dithers. Integrated, median per filter (range):
  F115W 0.022 (0.006–0.031), F150W 0.015 (0.007–0.020), F200W 0.009, F277W 0.017 (0.007–0.028),
  F356W 0.013, F444W 0.008 (0.006–0.013). The total error fraction is 0.008–0.037. For the arcs it is an over-estimate, since they average it away.
- `err_terms_frac` in `lens_psf.json` records each term's integrated fraction.

**Lens light vs arcs: one kernel (2026-11-01, `diagnostics/psf_closure/lens_light_test.py`).**
The question: does a bright, compact lens core need a different PSF from the faint, extended arcs?
- Two effects could make it so: the ivm weights (finding 4), and the sub-pixel phase.
- **The weights do not.** Across all 80 bands the WHT at the lens peak is a median 0.99 of the
  1–3" annulus around it, so lens cores are not in the saturating-star regime and are resampled
  as the arcs are. A few LW bands dip to 0.23–0.7 (SPT0418-47 F277W 0.23, SPT2147-50 LW ~0.7,
  COSJ100024+015334 LW 0.6, COSJ095914+021219 F277W 0.7), where one frame's core pixels look flagged by jump or
  outlier detection.
- **The test, for the phase.** A Sérsic lens galaxy (n = 4, R_e = 0.5", q = 0.8) is injected into
  the real frames at the 3×3 central grid positions: rendered on a 4× detector grid, convolved with
  STPSF's pixel-integrated ePSF, and resampled as the science. It is then fitted as PyAutoLens
  would (the Sérsic on the output pixels, 8× oversampled, convolved with a kernel; amplitude, R_e
  and n free), with noise at the real lens core's peak S/N. The score is the central 5×5 max
  |residual|, median over the 9 positions:

  | band | core S/N | shipped kernel | the point star at that exact position | empirical |
  |---|---|---|---|---|
  | SPT2147-50 F200W | 58 | 1.2σ | 0.9σ | 1.3σ |
  | SPT0418-47 F115W | 129 | 5.0σ | 3.1σ | 12.7σ |
  | SPT0418-47 F444W | 180 | 4.6σ | 3.2σ | 8.1σ |
  | COSJ100121+022740 F150W | 181 | 3.5σ | 2.8σ | 13.0σ |
  | COSJ100121+022740 F444W | 251 | 5.6σ | 4.0σ | 6.3σ |
  | B1938+666 F277W | 1393 | 16.9σ | 14.9σ | 94σ |

What the test shows:
- **The star-built PSF is worse for the lens light too.** Its χ² within 0.5" is 3–80× the model's;
  its narrowing in the undersampled bands hurts the core as well.
- **A position-specific kernel helps the core only by 10–40%**, and it would be wrong for the arcs.
- **No single kernel removes the floor at high S/N** (15σ on B1938+666 F277W even at the exact
  position). An undersampled, resampled image is not a convolution: each point of the core has its
  own phase on each detector. The exact fix is the modelling side's, fitting the individual
  exposures each with its detector PSF (STPSF, calibrated here). More dithers would also help.
- **So one kernel, the model's**, plus the phase term in its error map, which tells a modelling
  code how far a compact component's PSF can sit from it.

The truth in this test is STPSF-made, so the empirical column also pays for the model-vs-star gap
(1–2% in FWHM).

**Empirical tier (the check, and `--method empirical`).** The HST repo's ePSF machinery:
- stars from the full mosaic (lens masked to 5", no-coverage and edge masked), gated on peak
  S/N ≥ 30, fitted FWHM, ellipticity ≤ 0.15, crowding and a 5% flux floor;
- photutils `EPSFBuilder` at oversample 2, then validation;
- a bootstrap/jackknife error map.

NIRCam differences: the `_INSTR` keys are `NIRCAM/SW` / `NIRCAM/LW`; the SW bands are
undersampled (1.3–2.2 px FWHM), so oversample 2 is the floor; there is no mosaic-peak saturation
gate (a saturated core is a NaN hole, which the shape fit rejects); and there is one pass, so no
`psf`. The fixes of 2026-10-31, against the audit's findings:
- **Point sampling** (finding 1). `oversampled_to_kernel(integrated=True)` takes every 2nd ePSF
  sample through the core: the ePSF is already pixel-integrated, and block-summing integrated it
  twice. `integrated=False` (a raw optical PSF: the analytic model) still block-sums. It is
  identical to the scratch point-sampling the closure test validated.
- **The FWHM gate is against the resampled model** (finding 2). `psf_fwhm` is now
  `_GATE_FWHM_ARCSEC`: `_fit_stamp_shape`'s FWHM of the calibrated injected kernel (F115W 0.058,
  F150W 0.064, F200W 0.075, F277W 0.129, F356W 0.145, F444W 0.164"), with
  `fwhm_tol_hi` 1.4 → 1.15.
  - The old bound, 1.4 × the JDox FWHM, cut both ways. It admitted compact galaxies 1.25–1.40×
    the model in F444W, yet at 0.129" in F277W it equalled the resampled FWHM, so it was rejecting
    genuine F277W stars (SPT2147-50 F277W: 3 stars before, 8 now).
  - After the change, 8 of 297 selected stars are extended (10 of 296 at pass 1), against 14 of
    105 before.
- **Pedestal in excess of the model's wing** (finding 5). `subtract_pedestal(kernel, reference)`
  removes only the outer-annulus median above the model kernel's own. On the closure data, EE
  within 10 px is 0.9431 against 0.9434 true (the old way gave 0.98). Model kernels, being
  noiseless, are not pedestal-subtracted.

The empirical checks on the bands with ≥ 6 stars agree with the model to core L1 0.07–0.19, as the
closure test's noise level predicts. Two exceptions:
- **In undersampled bands the ePSF is narrower than the model**, as finding 4 predicts: B1938+666
  F115W 0.051" vs 0.059"; SPT0418-47 F277W 0.124" vs 0.131".
- **COSJ100028+021928 F115W gives a broken ePSF** (L1 1.47). Its SW rests on one exposure,
  whose cosmic rays only `jump` caught.

**The audit that led here (2026-10-30; scratch scripts in `diagnostics/psf_closure/`, the numbers
here).** It covered 15 bands with more than 5 stars, with three tests:
- (a) one ePSF block-summed and point-sampled, against the injected grid kernel;
- (b) closure: STPSF injected at the real stars' positions, the shipped ePSF build run on that
  mosaic, the truth being the same stars on output-pixel centres;
- (c) star by star against twins.

The findings:
1. **The block sum was biased broad.**
   - Closure: +1.8 to +6.2% FWHM (+16.4% B1938+666 F115W); point-sampled −4.8 to +4.7%, median 0.
     Core L1 to the truth: block 0.18–0.44, point 0.02–0.19.
   - Synthetic noiseless stars: +3.3% (F444W), +14.7% (F115W) block-summed, against +0.2% and +3.5%
     point-sampled (the SW rest is EPSFBuilder's quartic smoothing).
   - **The HST repo has the same code and the same bias, NOT fixed there** (scratch test, 10 bands):
     ACS/WFC +8–21% on real bands (synthetic +11.6%), WFC3/UVIS +12–14% (+7.5%), WFC3/IR 1–3%.
2. **Compact galaxies passed the star selection.** 14 of 105 stars were 15–40% broader than the
   model, 11 of them in four COWLS F444W fields. EPSFBuilder weights every star equally by flux, so
   per-lens COWLS F444W ePSFs came out at 0.170–0.185" against 0.165".
3. **Genuine stars were 2–3% broader than uncalibrated STPSF:** LW 1.02, SW 1.03 (now calibrated
   out).
4. **In undersampled bands, bright stars do not see the resampling a faint arc does.**
   - A star that saturates early in a ramp has a large VAR_RNOISE in its core. Its ivm weight there
     is 10–1000× below the field's and differs per frame, so the resample takes the core mostly from
     one frame.
   - SPT0418-47 F277W: core WHT 41–6000 against ~5e4 at the lens.
   - Injected FWHM: 0.104–0.114" at the field stars, 0.125–0.134" at the lens, 0.122–0.133" at the
     same stars with uniform weights.
   - The lens kernel sits above the stars' closure truth by +11% (SPT0418-47 F277W), +14%
     (B1938+666 F277W), +22% (B1938+666 F115W), +2–5% (SPT SW), ≤ 1.5% (F444W).
   - This narrowing and finding 1 partly cancelled in the old kernels.
5. **`subtract_pedestal` removed real wing light:** ~4% of the flux on a noiseless kernel (F444W EE
   within 10 px 0.943 → 0.98).
6. **COWLS tweakreg was not the F115W problem.** Re-aligning moved the pooled PSFs by ≤ 0.001".

**Pooled empirical PSF (`--pool --sample S --filt F`)**: a check on the per-lens models for a
survey sample whose fields are each star-poor (COWLS: 0–11 PSF stars per 90" field). It shipped
COWLS's PSFs from 2026-10-30 to 2026-10-31; it now writes only
`data/psf/<sample>/_pooled/<FILT>/` and `info/provenance/lens_psf_pooled.json`, no stamp dir.
- The sample shares filter, readout, output grid and two telescope rolls (PA_V3 107° and 293°,
  186° apart, under which the diffraction pattern nearly maps onto itself).
- `pooled_field` prepares each lens's mosaic as a single build does and drops a star already taken
  from a neighbouring mosaic (0.3"). It tiles the background-subtracted cutouts onto one synthetic
  image at their sub-pixel offsets, so `build_epsf` runs unchanged.
- COWLS on 2026-10-31: F115W 0.051", F150W 0.064", F277W 0.126", F444W 0.162" (F444W 61 stars, 9
  fewer than before the galaxy gate). Per-lens models: 0.058–0.062, 0.065–0.068, 0.129–0.135 and
  0.164–0.167". The undersampled-band gap is finding 4 again.
- `--output` is a true scratch mode (until 2026-10-30 it still overwrote the band's `psf.fits` and
  `lens_psf.json` record).

## Masks, arc masks, positions, QC (`make_masks.py`, `make_arc_masks.py`, `make_positions.py`, `make_dataset_subplots.py`, `make_qc_grids.py`)

Verbatim ports of the HST scripts (2026-10-01) with three mechanical changes: the sample
module is `lens_samples`, the band order (below), and the provenance JSONs record `variant`
(from the stamp's `REDUCVAR`) instead of `bcfill`. Their docstrings and `--help` still quote HST examples (`f814W`,
`slacs_gold`) and a `--pass` flag that is accepted and ignored (`stamp_paths.find_prefix`
always answers `stamp<S>` for the lens's modelling size). The semantics are unchanged and matter:

- **Each lens has a PRIMARY band** (`choose_primary_band.py`, 2026-11-01). It is drawn first
  (every other band starts from its mask), positions are clicked on it, it seeds the arc-mask
  proposals, and it is the band to model first. `lens_samples.primary_band(lens)` resolves it:
  - **`visual`**: `best_band_visual` (+ `best_band_visual_note`) on the lens in `lens_samples.json`,
    chosen by eye in `choose_best_band.py`, always wins. The name says what it is: a visual
    inspection, not necessarily the band with the highest arc S/N.
  - **`arc_snr`**: `best_band_arc_snr`, the script's measurement;
  - otherwise the fixed fallback `_BAND_PRIORITY` (F444W > F356W > F277W > … > F115W), which
    alone picked the wrong band for 13 of 20 lenses.

  **What the script measures.** On each band's modelling stamp it takes the lens light as the
  azimuthal median profile, interpolated in log-log across the ring annulus
  (|r − θ_E| < max(0.25 θ_E, FWHM, 0.15")). The arc S/N is the SIGNED residual sum in that annulus
  over its noise, so an elliptical lens's quadrupole cancels, with the band's contaminant mask
  applied. The score is that S/N × min(1, θ_E / (5 FWHM)): resolution counts only while the ring
  spans fewer than 5 PSF widths (SW resolves θ_E down to 0.33", F444W only to 0.83").

  **Why not redshift.** The lens light peaks near rest 1.6 µm, but the arc's colour is the
  source's: 14 of 17 COWLS sources have no redshift, and COSJ100119+014849 has no lens redshift
  (and 5 of the 16 lens redshifts are only photometric). Measured, the
  bands do not follow z_l: COSJ100012+022015, COSJ100121+022740 and COSJ100024+021749 all sit at
  z_l ≈ 0.37, yet COSJ100024+021749 is best in F150W and the other two
  in F277W.

  **The 2026-11-01 suggestions:**
  - F444W: SPT0418-47, COSJ095953+023319, COSJ100024+015334, COSJ100025+015245,
    COSJ100047+015023, COSJ100119+014849;
  - F356W: SPT2147-50;
  - F277W: B1938+666, COSJ095917+015424, COSJ095920+015851, COSJ095921+020638,
    COSJ095950+022057, COSJ095955+021900, COSJ100012+022015, COSJ100018+022138,
    COSJ100121+022740;
  - F150W: COSJ100024+021749;
  - none: COSJ095914+021219, COSJ100013+023424, COSJ100028+021928. No band reaches arc S/N 15 there; their arcs are too faint against the
    lens-profile error, so set `best_band_visual` by eye. (The re-cut on measured centres made
    COSJ100028+021928 measurable, F444W; see *Stamps*.)

  **The choice is the reviewer's: `choose_best_band.py --sample S [--unreviewed]`** (2026-11-01;
  `best_band_visual` since 2026-11-02, before which the key was `primary_band`).
  For each lens it opens the band overview with every band's arc S/N and score; click a column
  or press 1–N, and Enter writes `best_band_visual` (with a note) and refreshes the
  records and PNG (`choose_primary_band.record`). The measured suggestion only pre-selects. It
  was wrong on B1938+666 and COSJ100018+022138, and after the re-cut its arc S/N for compact
  lenses drops sharply (COSJ095920+015851 632 → 22), so it is a guide.

  **Visual** choices (`best_band_visual`; by 2026-11-02 every COWLS lens has one, chosen in the
  GUI), among them, overriding the measurement:
  - COSJ095914+021219 F277W and COSJ100013+023424 F444W, which were unmeasurable;
  - B1938+666 F115W over the measured F277W. Its 0.03" pixels and sharper PSF matter more on a
    0.45" ring than F277W's S/N.
  - COSJ100018+022138 F150W over the measured F277W.

  The measurement is biased red for bright, compact lenses (θ_E ≲ 0.6": COSJ095917+015424, COSJ095920+015851,
  B1938+666), where
  lens light leaks into the annulus; check those in the GUI.

  **Where it ships.** Every band's scores and the resolved choice are in
  `info/provenance/lens_primary_band.json`. A copy travels with the stamps as
  `data/stamps/<sample>/<lens>/primary_band.json`, and `export_dataset.py` writes `primary_band`,
  `primary_band_source`, `best_band_visual` and `is_primary_band` into each band's `info.json`.
  The records carry `best_band_visual` and `best_band_arc_snr` separately, so a downstream user
  sees both. θ_E for SPT and B1938+666 is now in
  `lens_samples.json` too (`theta_e`, `theta_e_ref`).
- **Per-lens band overview** (`make_band_overview.py`, 2026-11-01): `data/stamps/<sample>/<lens>/
  stamp<S>_bands.png`, tracked. Columns are the bands in wavelength order. The rows are the full
  stamp, a zoom on the lens, and the zoom with the lens light removed by an ISOPHOTE model
  (`isophote_model.py`, as the positions GUI; smoothed, red-blue, red = light the model lacks,
  masked pixels blank). Its colour range is set outside the central 0.2", whose cusp the inner
  isophotes cannot follow. The other panels have their own stretch in the repo's one look
  (`display_look.py`, the dataset subplots' inferno + 99% asinh), North up, East left.
  Overlaid: the contaminant mask outline, the extra-galaxy centres and θ_E; the primary band is
  starred. Image positions are NOT drawn (2026-11-02): each band's `*_positions.png` shows them.
  - The zooms, the θ_E circle and the isophote model are centred on the lens's measured
    centre (`deflector_ra/dec`) at its exact sub-pixel position. The stamps are cut on it,
    snapped to the LW grid, so it is ≤ 39 mas from the stamp centre; the header prints the
    residual.
  - autogalaxy's `radial_median_subtract` (the mask GUI's) profiles about the array centre, a pixel
    corner here, so even a half-pixel offset leaves a dipole. `radial_subtract` takes the
    sub-pixel centre instead.
  - It is not called a "mosaic", which means the Image3 product here.
  - `make_masks.py`, `make_extra_galaxies.py` and `choose_primary_band.py`
    re-render it after writing, once per changed lens at the END of the run (best-effort, never
    fatal). A stamp re-cut does not, so re-run the script after one.
  - **It renders on a plain `matplotlib.figure.Figure`, never pyplot, and must not call
    `matplotlib.use`.** Until 2026-11-01 it called `matplotlib.use('Agg')` at import. The mask
    GUI imported it after the first mask it wrote, which switched the process to Agg, so every
    later Scribbler window flashed up and returned unanswered (a "skip"). Each per-lens re-render
    also ran isophote fits between one GUI and the next.
  - The isophote fit covers the zoom only (to its corners), with step 0.2 and 15 iterations per
    isophote: ~9 s per lens, against 19 s.
  - Positions are autoarray (y, x), with y toward row 0, which is South in these stamps, so they
    plot at (−x, −y) on North/East axes. Checked against `make_positions.py`'s own North-down
    overlay on B1938+666.
  - ~0.1–0.9 MB per lens per render.
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
  '2' black = erase** (was green/red); `--stretch/--asinh-a/--vmin-percent/--vmax-percent`
  are gone from `make_masks.py`, `make_arc_masks.py` and (2026-11-02) `make_positions.py`,
  whose `--vmax-value` stays. The proposal is a black-on-white contour rather than a 1 px
  burned-in line; the contaminant edge in `make_arc_masks.py` is 'x's from autoarray's
  `derive_grid.edge` (recoloured cyan here, as black vanishes on inferno), which also runs
  along the stamp border; `--cross-size` defaults to the Scribbler's own (1.5% of the shorter
  side, ≥3 px).
- **One image look everywhere (2026-11-02, `scripts/display_look.py`)**: the dataset subplots'
  data / PSF / S/N panels, i.e. `inferno` with each panel's own `PercentileInterval(99)` +
  `AsinhStretch(0.1)`.
  - The mask GUIs pass `display_look.SCRIBBLER` as the Scribbler's `cmap`: an object with
    `norm_from(array=)` + `cmap_name`, which the Scribbler applies per panel.
  - The positions / extra-galaxy GUIs and their PNGs, the arc-mask QC PNG and the band overview's
    as-observed rows all use `display_look.normalised`, as does the dataset subplot itself.
  - Signed residuals (the isophote-subtracted panels) stay red-blue.
  - Before this, the Scribbler showed its median/MAD `arcsinh_stretch` on autoarray's colormap,
    the positions GUI a percentile asinh on `jet`, and the overview gray.
  `reproject_mask_bool` is deliberately kept over `al.mask_2d_regridded_from`: ours
  transfers through the two bands' header WCS, upstream's by pixel scale + origin only.
- One draw per band; the next band starts from a reviewed proposal reprojected by WCS.
  Here the SW→LW reprojection is a 2:1 regrid, like the HST f160W case.
- Positions are marked once on the best band and broadcast pixel→sky→pixel; an empty file
  means "decided: none".
- **Ported from the HST repo, 2026-11-01** (its uncommitted positions work of that day: `isophote_model.py`,
  `positions_io.py`, `make_positions.py`, `make_arc_masks.py`):
  - **Isophote display.** The positions GUI and its overlay PNG show the band as observed and
    with the lens removed by an ISOPHOTE model (photutils `Ellipse`, ellipticity and PA free with
    radius, centre fixed, masked pixels excluded), smoothed on a red-blue map. A radial median
    leaves a quadrupole on every elliptical lens. `--subtract isophote|radial|none`; the old
    `--(no-)subtract-radial` still maps onto it. It is a finding aid, not photometry: it absorbs a
    little of an arc lying along an isophote. Here `isophote_subtract(refine_centre=False)` also
    lets the band overview keep the measured lens centre: the HST default refines it with a 0.3"
    centroid, which creeps toward a ring inside that window.
  - **Position sets.** Number keys 1–9 in the GUI switch the source being marked, one set per
    source (double source planes, distinct sources), and Esc finishes. `z` (or Backspace)
    undoes the last click (2026-11-02).
  - **The snap is our own since 2026-11-02 (`make_positions.snap_click`).**
    - It moves a double-click to the brightest pixel (true flux) within a disc of
      `--snap-radius` px (default 1; 0 = none; `--search-box-size` is the old name).
    - `al.Clicker`'s snap first rounded the click to a pixel CORNER on these even-sided stamps,
      then searched an asymmetric box (−b … b−1). With the old default of 2 it moved the first
      COWLS clicks 0.5–2.5 px, up to 0.15" in LW.
    - The record key is now `snap_radius_px`.
  - **After Esc nothing slow runs in the GUI process.** The per-band `_positions.png` overlays
    (an isophote fit each: ~7 s an SW band, ~2.5 s LW) and the band overview are drawn at the
    end of the run, in one detached process (`make_positions.background_renders`, log in
    `data/run_logs/positions_renders_*`). Drawn inline, they kept the closed window frozen for
    ~20 s per lens.
    - `positions_io.write_sets` writes ONE set exactly as before, a single `Grid2DIrregular`, so
      every existing file and reader is unchanged. Two or more sets are autoconf's list type,
      which `al.from_json` returns as a list.
    - `positions_io.read_sets` always returns a list of sets.
    - `lens_positions.json` keeps the flattened `positions_arcsec` and adds `n_sets` /
      `positions_arcsec_by_set` for a multi-set lens.
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
- **Every GUI and QC plot is North up, East left (2026-11-02)**, like the band overview. Before
  that the GUIs showed row 0 at the top, which is North down, a vertical mirror of the sky.
  - Rows run South → North and columns East → West in every stamp.
  - The Scribbler is built with `block=False`, its pixel y axis is set increasing upward
    (`make_masks.north_up_pixels`), and then it is started.
  - The positions panels invert their autoarray-y axis and label the ticks East/North
    (`make_positions.north_up`). Clicks and saved positions are still autoarray (y, x).
  - The arc-mask QC PNG draws with `origin='lower'`.
  - The dataset subplot is drawn from top-to-bottom flipped copies of the four products: flipping
    autolens's imshow origin would mirror its own overlays.
  - None of this changes a saved mask or position.
  - Quote offsets as ΔRA/ΔDec.
  - **No pyplot after a Scribbler.** `al.Scribbler.start()` calls `plt.ion()`, so any later
    pyplot figure in that process flashes up as a blank window.
    - The dataset subplots of the bands a mask run wrote (`make_masks.PENDING_SUBPLOTS`) are drawn
      by the same detached process as the band overviews (`rerender_overviews(..., subplots)`).
    - The arc-mask QC PNG is drawn on a plain `Figure`.
- **Headless GUI tests:** `al.Scribbler` defaults to `backend='TkAgg'` (ignoring `MPLBACKEND`)
  and, unless `block=False`, opens its window and blocks INSIDE `__init__`. A test needs
  `backend='Agg', block=False` and no `start()`, or it opens a real window and hangs.
- `make_qc_grids.py` is the HST `make_mosaics.py`, renamed because "mosaic" here means the
  Image3 product; it writes `data/qc/<sample>/`.

**First JWST use: B1938+666, 2026-10-04**, with the HST-port GUIs (before the native-Scribbler
rewrite). `make_positions.py` marked A and B on F277W and broadcast them to F115W;
`make_masks.py` drew the contaminant masks (F115W 27 515 px, F277W 6 854 px, provenance in
`info/provenance/lens_masks.json`); `make_dataset_subplots.py` rendered both bands. `make_arc_masks.py` has
still never run on a JWST stamp (`make_qc_grids.py` first ran 2026-11-02, cleanly): expect small breakages (header cards,
the `--pass` plumbing) on first use and fix them in place. The native-Scribbler rewrite was
verified headless first (`backend='Agg'`, synthetic stamps, strokes injected through
`add_circle_to_scribble`). It has been used for real since, on all the COWLS masks.

## Export to the modelling project (`scripts/export_dataset.py`)

```bash
uv run python scripts/export_dataset.py --lens SPT2147-50 --dest <modelling-project>/data [--mask-radius 3.0]
```

Copies each band's stamp, noise map and PSF to `<dest>/<lens>/<FILT>/{data,noise_map,psf}.fits`,
the contaminant mask as `mask_extra_galaxies.fits`, the positions as `positions.json` and the
extra-galaxy centres as `extra_galaxies_centres.json` when they exist, and writes `info.json` with `pixel_scale`, `mask_radius`, the redshifts, the
lens's primary band (`primary_band`, `primary_band_source`, `best_band_visual`, `is_primary_band`; *Masks*) and the
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
  stamps/<sample>/[<cat>/]<lens>/<FILT>/  THE science tree, every size side by side (stamp<S>_*; only each
                                          lens's modelling size is tracked; stamp<S>.png and *_positions.png
                                          are gitignored QC renders, rebuilt by the scripts). <cat> only for a
                                          sample with lens_categories (COWLS: prime, multi_galaxy; see *Stamps*)
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

Exercised 2026-10-29: the position query + footprint cut of `download_nircam.py`, the
per-sample `mosaic_field`/`prune_intermediates`, neighbour hard-linking of pool files, and
`exptime_at` (identical to the old sums on every SPT/B1938 band).

Exercised 2026-10-30: the STPSF model tier of `make_psf.py`, the pooled empirical tier,
`make_psf_inject.py` (24 bands standalone, including both B1938+666 bands and the `from_lw` SW
route; through `make_psf.py --method model --output` on COSJ095920+015851 F444W; see *PSF*), and the COWLS
tweakreg settings `tweakreg_lens_first` / `tweakreg_sw_from_lw` (all 68 bands).
Exercised 2026-10-31: the injected tier as the shipped PSF on all 80 bands, `--method empirical`,
`--pool` as a check, and `psf_star_check.py` (three passes over all 80 bands, `--calibrate`,
`--error-maps`).

Not yet exercised: `make_arc_masks.py`, `--tweakreg gaia`. (`make_qc_grids.py` ran on
`cowls_spectacular` F444W on 2026-11-02 to test the category layout; its output was not kept.) Stubs: `detect_arcs.py`.
Exercised since: `measure_corr_factor.py` (12 stamps, 2026-10-04), `--start rate` and
`--flicker-by-channel` (SPT0418-47 F150W, 2026-10-02), `destripe_nircam.py`, and
`make_masks.py`, `make_positions.py` and `make_dataset_subplots.py` on B1938+666 (2026-10-04,
the HST-port GUIs; the native-Scribbler rewrite is verified headless only, see *Masks*).
