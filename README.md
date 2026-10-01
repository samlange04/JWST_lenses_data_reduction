# JWST lens image reduction

Downloads NIRCam exposures from MAST and reduces them with the `jwst` pipeline into
North-up mosaics + modelling stamps for gravitational lenses. One product per **lens +
filter**. The sibling of
[HST_lenses_data_reduction](https://github.com/samlange04/HST_lenses_data_reduction): same
layout, same stamp conventions, same tracking JSONs, JWST instead of AstroDrizzle.

> This README is the operator's quick-start. `AGENTS.md` is the deep reference — every
> non-obvious decision and the trap it avoids. When the doc and the code disagree, trust
> the code.

## Lenses

| sample | program | lens | NIRCam filters | z_l / z_s |
|---|---|---|---|---|
| `b1938` | GO 8281 (Vegetti) | B1938+666 | F115W F277W (21 dithers, ~24 h each) | 0.881 / 2.059 |
| `spt` | GO 1355 TEMPLATES (Rigby) | SPT0418-47 | F115W F150W F200W F277W F356W F444W | 0.263 / 4.22 |
| `spt` | GO 1355 TEMPLATES (Rigby) | SPT2147-50 | F200W F277W F356W F444W | 0.845 / 3.76 |

NIRCam only. TEMPLATES also has MIRI imaging and NIRSpec/MIRI IFU of both SPT lenses;
they are deliberately not reduced here (see AGENTS.md).

## Setup

```bash
uv sync                                  # one-time; downloads the pinned CPython itself
uv run python scripts/<script>.py --lens <LENS> --filt <FILTER>
```

CRDS reference files download themselves on first use into `data/reference_files/`
(tens of GB for NIRCam). The STPSF data files (model-PSF fallback only) go in
`data/reference_files/stpsf-data/`.

## The pipeline, end to end

```bash
uv run python scripts/download_nircam.py --lens SPT2147-50            # MAST uncal -> pool, sorted by filter
uv run python scripts/reduce_nircam.py   --lens SPT2147-50 --filt F444W   # Detector1 -> Image2 -> Image3 mosaic
uv run python scripts/make_cutouts.py    --lens SPT2147-50 --filt F444W   # 12" stamp + noise map + PNG
uv run python scripts/make_psf.py        --lens SPT2147-50 --filt F444W   # empirical ePSF (STPSF fallback)
uv run python scripts/make_masks.py      --lens SPT2147-50                # GUI: paint contaminants to remove
uv run python scripts/make_positions.py  --lens SPT2147-50                # GUI: mark multiple images
uv run python scripts/export_dataset.py  --lens SPT2147-50 --dest ../../git_repos/pyauto/z_projects/SPT_rerun/hpc/data
```

Whole samples: `bash scripts/run_reduce_all.sh spt`, `run_cutouts_all.sh spt`,
`run_psf_all.sh spt`. Runners log to `data/run_logs/` and count ok / no data / FAILED.
Scripts are idempotent: downloaded files, rate/cal products and a finished mosaic are all
skipped on a re-run (`--force` rebuilds a mosaic).

## Directory layout

```
data/
  calibrated/<sample>/<lens>/pool/      every MAST file of the lens's visits (uncal by default)
  calibrated/<sample>/<lens>/<FILT>/    hard links into the pool, sorted by header FILTER
  stage1/<sample>/<lens>/<FILT>/        *_rate.fits   (our Detector1: snowballs + 1/f cleaned)
  stage2/<sample>/<lens>/<FILT>/        *_cal.fits    (our Image2)
  mosaics[_<variant>]/<sample>/<lens>/<FILT>/  <lens>_<filt>_i2d.fits + png  (our Image3)
  cutouts/<sample>/<lens>/<FILT>/       THE science tree (git-tracked): cutout_{sci,noise}.fits,
                                        cutout_psf.fits, cutout_mask.fits, cutout_positions.json, PNGs
  psf/<sample>/<lens>/<FILT>/           archival full PSF kernel + QA plot
  qc/<sample>/                          grids tiling the stamps (make_qc_grids.py)
  reference_files/                      CRDS cache (+ stpsf-data/)
  run_logs/
info/
  lens_samples.json       programs, lenses, coordinates, redshifts -- the single source of truth
  lens_downloads.json lens_products.json lens_exptime.json lens_instrument.json   auto-updated
  lens_cutout_qc.json lens_psf.json lens_masks.json lens_positions.json ...        provenance
  noise_corr_factors.json psf_stars.json                                           hand-edited
```

## Products

Stamps are 12" square at 0.03"/px (SW: 400 px) or 0.06"/px (LW: 200 px), North-up, every
filter of a lens sharing one tangent point at the catalogue position so the SW and LW grids
nest 2:1. Units are MJy/sr (the jwst convention; `PHOTMJSR`/`PIXAR_SR` in the header
convert). The noise map is the i2d `ERR` times a measured inflation factor
(`info/noise_corr_factors.json`, 1.0 until measured), with 1e8 where there is no data.
