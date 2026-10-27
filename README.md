# JWST lens image reduction

> **If you use this repository, please credit the repository
> ([github.com/samlange04/JWST_lenses_data_reduction](https://github.com/samlange04/JWST_lenses_data_reduction))
> and Samuel C. Lange (The Chinese University of Hong Kong).**

This repository turns James Webb Space Telescope (JWST) NIRCam archive images of **strong
gravitational lenses** into clean, ready-to-model image stamps. It is the sibling of
[HST_lenses_data_reduction](https://github.com/samlange04/HST_lenses_data_reduction), which
does the same for Hubble data, and it uses that repository's layout, file names and
conventions.

A strong lens is a massive foreground galaxy (the *deflector*) whose gravity bends the light
of a more distant galaxy (the *source*) behind it, so the source appears as arcs, a ring, or
two to four separate images around the deflector. Modelling those arcs measures how mass is
distributed in the deflector. A model needs more than a picture, though: it needs to know how
uncertain every pixel is, how blurred the telescope makes a point of light, which pixels to
ignore, and roughly where the multiple images are. This repository produces all of that, for
three lenses from two JWST programs.

**Most people only need the finished products in `data/stamps/`** — they are in git, so a
plain clone has them. Re-running the reduction is only needed to change how it was done.

**Recommended analysis tool: [PyAutoLens](https://github.com/PyAutoLabs/PyAutoLens)**, from
the [PyAutoLabs](https://github.com/PyAutoLabs) software family. The products are written in
the formats it reads directly (its masks, image positions and PSF kernels), and its own GUI
tools drew the masks and marked the positions.

## What's in the box

| Sample folder | Lens | JWST program | NIRCam filters | Lens / source redshift |
|---|---|---|---|---|
| `b1938` | B1938+666 | GO 8281 (PI Vegetti) | F115W, F277W (21 dithers, ~24 h per filter) | 0.881 / 2.059 |
| `spt` | SPT0418-47 | ERS 1355 TEMPLATES (PI Rigby) | F115W, F150W, F200W, F277W, F356W, F444W | 0.263 / 4.22 |
| `spt` | SPT2147-50 | ERS 1355 TEMPLATES (PI Rigby) | F200W, F277W, F356W, F444W | 0.845 / 3.76 |

That is 12 lens-and-filter images in total. A filter name gives its approximate central
wavelength in hundredths of a micron: F115W is centred near 1.15 μm and F444W near 4.4 μm,
so every band here is near- to mid-infrared. Seeing the same lens in several colours helps
tell the lensed source apart from the deflector; the two SPT sources are dusty and brightest
in the longest-wavelength bands.

NIRCam observes through two channels at once, which differ in pixel size, so the stamps do
too:

| Channel | Filters here | Pixel size | Stamp size in pixels |
|---|---|---|---|
| Short wavelength (SW) | F115W, F150W, F200W | 0.03″ (resampled from 0.031″) | 400 × 400 (B1938+666: 232 × 232) |
| Long wavelength (LW) | F277W, F356W, F444W | 0.06″ (resampled from 0.063″) | 200 × 200 (B1938+666: 116 × 116) |

The SPT stamps cover 12″ × 12″ of sky. B1938+666's cover 6.96″ × 6.96″, because its Einstein
ring is only ~0.9″ across and a 12″ stamp was a third detector streaks and unrelated galaxies.
Every stamp is centred on the lens, and a lens's SW and LW pixels nest exactly 2 : 1.

## Using the finished products

Each lens and filter has one folder, `data/stamps/<sample>/<lens>/<filter>/`, for example
`data/stamps/b1938/B1938+666/F115W/`. The files in it are:

| File | What it is |
|---|---|
| `stamp<S>_sci.fits` | **The image.** Surface brightness per pixel, in MJy/sr (the JWST pipeline's unit; the `PHOTMJSR` and `PIXAR_SR` header keywords convert it). |
| `stamp<S>_noise.fits` | **The noise map**: the 1σ uncertainty of every pixel, in the same units as the image. Pixels with no data are set to 10⁸. |
| `psf.fits` | **The PSF** (point-spread function): how the telescope blurs a single point of light, on the same pixel grid and orientation as the image, normalised to sum to 1. A lens model convolves with this. |
| `psf_err.fits` | The per-pixel uncertainty of that PSF. |
| `stamp<S>_mask.fits` | **The mask**: 1 marks a pixel to *exclude* from a fit (nearby galaxies, stars, detector artefacts), 0 a pixel to use. The lens itself is never masked. Hand-drawn. |
| `stamp<S>_positions.json` | **Image positions**: where the multiple images of the lensed source are, hand-marked (see below). |
| `stamp<S>_dataset.png` | A quick-look figure of the image, noise, PSF and mask together — the fastest way to check a lens. |

`<S>` is the stamp size in arcseconds: `stamp7_*` for B1938+666, `stamp12_*` for the SPT
lenses. A stamp cut at another size (`make_stamps.py --size 20`) is written beside these as
`stamp20_*` and is not kept in git. The PSF has no size in its name because it does not depend
on the stamp size.

**Masks and positions so far exist for B1938+666 only.** The SPT bands carry the image, noise
map and PSF; their masks and positions have not been drawn yet.

**Orientation.** North is towards increasing row number and West towards increasing column
number, so with Python's usual display (row 0 at the top) **North appears at the bottom and
East on the left**. That is a vertical flip of the way astronomical images are usually shown,
not a rotation. The FITS headers carry full sky coordinates (WCS) if you need them.

**Image positions** are stored in the format of the [PyAutoLens](https://github.com/PyAutoLabs/PyAutoLens)
lens-modelling software, which reads them directly. Each entry is a `(y, x)` offset in
arcseconds from the stamp centre. Following PyAutoLens's convention, +y points South and +x
points West. To get pixels: `row = row_centre − y / pixel_size` and
`col = col_centre + x / pixel_size`, where the centre of a 232-pixel stamp is 115.5.
B1938+666 has two marked images, A and B.

A minimal example in Python:

```python
from astropy.io import fits

band = "data/stamps/b1938/B1938+666/F115W/"
image = fits.getdata(band + "stamp7_sci.fits")
noise = fits.getdata(band + "stamp7_noise.fits")
psf   = fits.getdata(band + "psf.fits")
mask  = fits.getdata(band + "stamp7_mask.fits").astype(bool)   # True = exclude

signal_to_noise = image / noise
```

### Things worth knowing before you model

- **The noise maps already include a measured correction**, recorded in the `NOISECOR` header
  keyword. NIRCam frames carry residual "1/f" noise: faint stripes along the detector rows,
  left over after the pipeline's stripe removal and correlated over ~3″. No single factor can
  describe noise that grows with the size of the patch you sum over, so each map is scaled to
  be right for patches of 0.2″, roughly the image-plane footprint of one source pixel: SW ×1.30
  and LW ×1.03 for the SPT lenses, and F115W ×0.94 and F277W ×1.12 for B1938+666, whose much
  deeper data were measured separately by splitting its dithers in two. The full
  scale-dependence is in `info/overrides/noise_corr_factors.json` (`block_ratio_curve`). A model
  whose source pixels map onto larger patches of the image should rescale from it.
- **B1938+666's stamp is centred on the deflector, not on its catalogue coordinate.** The
  program's target coordinate sits 0.48″ East and 0.20″ South of the lens core. The measured
  centre is in `info/samples/lens_samples.json` (`deflector_ra`, `deflector_dec`), and every
  stamp records where it was cut (`CUTRA`, `CUTDEC`).
- **B1938+666's ring of clumps at 0.9–1.4″ is deliberately left unmasked.** Whether they are
  further lensed images or structure in the lens plane is not settled, so excluding them is a
  modelling choice, not something the contaminant mask decides.
- **Two PSFs rest on only three stars** (SPT0418-47 F115W and SPT2147-50 F277W). Their error
  maps say so; look at them before relying on those bands. Every other band has 5–12 stars.
- **SPT0418-47 sits on the NIRCam detector with the strongest "wisps"** (faint scattered-light
  patterns in the SW bands). They are not subtracted, so check the SW images before trusting
  a faint SW feature.
- **Redshifts** for every lens are in `info/samples/lens_samples.json`.

[`AGENTS.md`](AGENTS.md) has the measurements behind each of these.

## How the reduction works

JWST does not deliver one finished picture. It records each exposure as a series of
non-destructive readouts (a *ramp*), takes several exposures shifted slightly between them
(*dithered*), and spreads them over several detectors. For every lens and filter the pipeline:

1. **Downloads** the raw ramps from the JWST archive (MAST) and the matching calibration
   files. A NIRCam visit records all of its filters at once, so the whole visit is fetched
   and sorted by filter.
2. **Fits the ramps** with STScI's `jwst` pipeline, rejecting cosmic-ray hits and their
   "snowball" splashes, and removing the 1/f stripes on the ramp itself (a step the pipeline
   leaves off by default, and the reason this repository starts from the raw ramps).
3. **Calibrates** each exposure (flat field, photometric calibration).
4. **Combines the exposures** into one mosaic: aligns the dithers with each other, matches
   their sky levels, rejects remaining outliers, and resamples onto a common North-up grid
   centred on the lens, at 0.03″ (SW) and 0.06″ (LW).
5. **Cuts out** the stamp around the deflector and writes the noise map from the mosaic's
   propagated error, times the measured correction above.
6. **Measures the PSF** from stars in the same mosaic (STScI's STPSF model is the fallback
   where there are too few stars; no band needed it).
7. **Masks and marks** — the masks and image positions are drawn and clicked by hand in
   small interactive tools.

Every choice behind these steps — and the mistakes each one avoids — is documented in
[`AGENTS.md`](AGENTS.md). It is written as a technical reference (it is also the guide for
AI coding assistants working in this repository), so start here and go there for the detail.

## Re-running the reduction

You only need this to change how the data were processed, or to rebuild the large
intermediate files that are not stored in git.

**Setup.** Install [uv](https://docs.astral.sh/uv/), then from the repository folder:

```bash
uv sync
```

This installs the exact Python version and package versions the pipeline was run with, on
macOS or Linux, with nothing else to install. Run any script as `uv run python scripts/<name>.py`.

**Expect large downloads.** The calibration files download themselves on first use into
`data/reference_files/` (about 30 GB for NIRCam), and B1938+666's raw ramps alone are 79 GB.
Reducing its two filters took 8.5 hours. The STPSF data files (needed only for the
model-PSF fallback) go in `data/reference_files/stpsf-data/`.

**Reduce one lens in one filter**, e.g. SPT2147-50 in F444W:

```bash
uv run python scripts/download_nircam.py --lens SPT2147-50                 # raw ramps from MAST, sorted by filter
uv run python scripts/reduce_nircam.py   --lens SPT2147-50 --filt F444W    # ramps -> calibrated exposures -> mosaic
uv run python scripts/make_stamps.py     --lens SPT2147-50 --filt F444W    # stamp + noise map
uv run python scripts/make_psf.py        --lens SPT2147-50 --filt F444W    # empirical PSF (STPSF fallback)
uv run python scripts/make_masks.py      --lens SPT2147-50                 # GUI: paint contaminants to remove
uv run python scripts/make_positions.py  --lens SPT2147-50                 # GUI: mark the multiple images
```

Whole samples run with `bash scripts/run_reduce_all.sh <sample>`, `run_stamps_all.sh` and
`run_psf_all.sh`, which log to `data/run_logs/` and count ok / no data / failed. Every step
skips work already done, so a run can be resumed after an interruption (`--force` rebuilds a
mosaic). `scripts/export_dataset.py --lens <lens> --dest <dir>` writes a lens in the dataset
layout a PyAutoLens modelling project loads (`data.fits`, `noise_map.fits`, `psf.fits`,
`info.json`).

## Repository layout

```
data/stamps/<sample>/<lens>/<filter>/   the finished products (in git)
data/...                                 downloads and intermediate files (not in git, rebuildable)
info/samples/lens_samples.json           the lenses: programs, coordinates, redshifts, stamp sizes
info/overrides/                          hand-set values (the noise corrections)
info/provenance/                         a record of how every product was made (JSON)
scripts/                                 the pipeline
AGENTS.md                                full technical reference
```

`info/samples/lens_samples.json` is the master list of which lenses are in which sample.

## Credit and acknowledgements

If you use this repository, please credit the repository
([github.com/samlange04/JWST_lenses_data_reduction](https://github.com/samlange04/JWST_lenses_data_reduction))
and **Samuel C. Lange (The Chinese University of Hong Kong)**. GitHub's **"Cite this
repository"** button (right-hand sidebar, from `CITATION.cff`) gives a ready-made citation.

**Licences.** The code is under the [MIT License](LICENSE). The data products — everything
in `data/`, and the JSON records in `info/` — are under [CC BY 4.0](LICENSE-DATA): you may
share and adapt them for any purpose, as long as you give credit as above.

Please also credit the programs and papers for the lenses you use: GO 8281 (PI Vegetti) for
B1938+666, and the TEMPLATES program (Rigby et al. 2025) for the SPT lenses. The redshifts
come from Tonry & Kochanek (2000) and Riechers (2011) for B1938+666, and Weiß et al. (2013)
and Reuter et al. (2020) for the SPT lenses. Please acknowledge the JWST data, e.g. *"This
work is based on observations made with the NASA/ESA/CSA James Webb Space Telescope. The data
were obtained from the Mikulski Archive for Space Telescopes at the Space Telescope Science
Institute, which is operated by the Association of Universities for Research in Astronomy,
Inc., under NASA contract NAS 5-03127 for JWST. These observations are associated with
programs #1355 and #8281."*

The reduction is built on STScI's [`jwst` pipeline](https://jwst-pipeline.readthedocs.io) and
[STPSF](https://stpsf.readthedocs.io), [Astropy](https://www.astropy.org),
[photutils](https://photutils.readthedocs.io) and
[PyAutoLens](https://github.com/PyAutoLabs/PyAutoLens) (mask and position tools).
