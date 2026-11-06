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
ignore, and roughly where the multiple images are. This repository produces that for 20
lenses from three JWST programs.

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
| `templates` | SPT0418-47 | ERS 1355 TEMPLATES (PI Rigby) | F115W, F150W, F200W, F277W, F356W, F444W | 0.263 / 4.22 |
| `templates` | SPT2147-50 | ERS 1355 TEMPLATES (PI Rigby) | F200W, F277W, F356W, F444W | 0.845 / 3.76 |
| `cowls-mahler` | the 17 "spectacular" COWLS lenses of Mahler et al. (2025), `COSJ095914+021219` … `COSJ100121+022740` | GO 1727 COSMOS-Web (PIs Kartaltepe & Casey) | F115W, F150W, F277W, F444W (2–4 exposures of 258 s per filter at the lens) | per lens in `lens_samples.json`: 11 spectroscopic and 5 photometric lens redshifts, 3 spectroscopic source redshifts |

That is 80 lens-and-filter images in total (12 + 68 COWLS). A filter name gives its approximate central
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

The SPT and COWLS stamps cover 12″ × 12″ of sky. B1938+666's cover 6.96″ × 6.96″, because its Einstein
ring is only ~0.9″ across and a 12″ stamp was a third detector streaks and unrelated galaxies.
Every stamp is centred on the lens's measured centre, its light peak (`deflector_ra`/`deflector_dec`
in `info/samples/lens_samples.json`), to within 0.04″, and a lens's SW and LW pixels nest exactly 2 : 1.

## Using the finished products

Each lens and filter has one folder, `data/stamps/<sample>/<lens>/<filter>/`, for example
`data/stamps/b1938/B1938+666/F115W/`. The COWLS lenses add a level for their category,
`data/stamps/cowls-mahler/<category>/<lens>/<filter>/`:
- `prime`: the sample's best lenses (none chosen yet);
- `multi_galaxy`: more than one galaxy's mass has to be modelled, such as a second lens or a
  galaxy close enough to the arcs to perturb them;
- `limited`: no spectroscopic redshift for the lens, the source, or both;
- `complex`: the lens and source redshifts are both spectroscopic.

The exported `info.json` names the category (`lens_category`). The files in each folder are:

| File | What it is |
|---|---|
| `stamp<S>_sci.fits` | **The image.** Surface brightness per pixel, in MJy/sr (the JWST pipeline's unit; the `PHOTMJSR` and `PIXAR_SR` header keywords convert it). |
| `stamp<S>_noise.fits` | **The noise map**: the 1σ uncertainty of every pixel, in the same units as the image. Pixels with no data are set to 10⁸. |
| `psf.fits` | **The PSF** (point-spread function): how the telescope blurs a single point of light, on the same pixel grid and orientation as the image, normalised to sum to 1. A lens model convolves with this. |
| `psf_err.fits` | The per-pixel uncertainty of that PSF. |
| `stamp<S>_mask.fits` | **The mask**: 1 marks a pixel to *exclude* from a fit (nearby galaxies, stars, detector artefacts), 0 a pixel to use. The lens itself is never masked. Hand-drawn. |
| `stamp<S>_positions.json` | **Image positions**: where the multiple images of the lensed source are, hand-marked (see below). |
| `stamp<S>_extra_galaxies_centres.json` | **Extra-galaxy centres** (multi-galaxy lenses only): where the galaxies besides the main lens are, hand-marked, so a lens model can include their mass. (y, x) in arcsec from the stamp centre, autoarray's convention: +y is South, +x is West. |
| `stamp<S>_dataset.png` | A quick-look figure of the image, noise, PSF and mask together, North up and East left — the fastest way to check a lens. |

**All bands at once.** `data/stamps/<sample>/<lens>/stamp<S>_bands.png` shows every band of the
lens side by side, North up and East left:
- the full stamp, then a zoom on the lens, then that zoom with the lens light removed by a model of
  its elliptical isophotes (red: light the model lacks, i.e. arcs and lensed images);
- the contaminant masks, extra-galaxy centres and Einstein radius drawn on, where they exist;
- the primary band starred.

**Which band is best.** Each lens also has `data/stamps/<sample>/<lens>/primary_band.json`,
naming its **primary band**: the filter where the lensed images are best defined, so the one
to look at or model first.
- `best_band_visual` is the band chosen by eye from the band overview. It is a visual
  inspection, not necessarily the band with the highest arc signal-to-noise.
- `best_band_arc_snr` is that measurement: the arc's signal-to-noise in every band, discounted
  where the band's resolution is coarse for the size of the Einstein ring. The file lists every
  band's numbers.
- `primary_band` is the visual choice where there is one (`primary_band_source: visual`), else
  the measurement (`arc_snr`).
- The same is in `info/provenance/lens_primary_band.json` and in every exported `info.json`.

`<S>` is the stamp size in arcseconds: `stamp7_*` for B1938+666, `stamp12_*` for the SPT
and COWLS lenses. A stamp cut at another size (`make_stamps.py --size 20`) is written beside these as
`stamp20_*` and is not kept in git. The PSF has no size in its name because it does not depend
on the stamp size.

**Every band of every lens has a hand-drawn contaminant mask, and every lens has image
positions** — except COSJ095920+015851, where the positions file is deliberately empty.
COSJ100018+022138 has two position sets (two lensed sources), and the three `multi_galaxy`
COWLS lenses also carry extra-galaxy centres.

**Orientation.** North is towards increasing row number and West towards increasing column
number, so with Python's usual display (row 0 at the top) **North appears at the bottom and
East on the left**. That is a vertical flip of the way astronomical images are usually shown,
not a rotation. Every figure this repo makes (the band overview, the dataset and positions
plots, the masking and marking tools) is drawn North up, East left, with `origin='lower'` or
the equivalent. The FITS headers carry full sky coordinates (WCS) if you need them.

**Image positions** are stored in the format of the [PyAutoLens](https://github.com/PyAutoLabs/PyAutoLens)
lens-modelling software, which reads them directly. Each entry is a `(y, x)` offset in
arcseconds from the stamp centre. Following PyAutoLens's convention, +y points South and +x
points West. To get pixels: `row = row_centre − y / pixel_size` and
`col = col_centre + x / pixel_size`, where the centre of a 232-pixel stamp is 115.5.
B1938+666 has two marked images, A and B. A lens with more than one lensed source (for example
two source planes) has one set of positions per source: the file then holds a list of sets,
which `al.from_json` returns as a Python list. A file with one set is a single grid, as here.

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
  deeper data were measured separately by splitting its dithers in two. The COWLS lenses have
  their own, per filter: F115W ×1.25, F150W ×1.22, F277W ×1.03, F444W ×0.95. The full
  scale-dependence is in `info/overrides/noise_corr_factors.json` (`block_ratio_curve`). A model
  whose source pixels map onto larger patches of the image should rescale from it.
- **B1938+666's stamp is centred on the deflector, not on its catalogue coordinate.** The
  program's target coordinate sits 0.48″ East and 0.20″ South of the lens core. The measured
  centre is in `info/samples/lens_samples.json` (`deflector_ra`, `deflector_dec`), and every
  stamp records where it was cut (`CUTRA`, `CUTDEC`).
- **B1938+666's ring of clumps at 0.9–1.4″ is deliberately left unmasked.** Whether they are
  further lensed images or structure in the lens plane is not settled, so excluding them is a
  modelling choice, not something the contaminant mask decides.
- **SPT0418-47 sits on the NIRCam detector with the strongest "wisps"** (faint scattered-light
  patterns in the SW bands). They are not subtracted, so check the SW images before trusting
  a faint SW feature.
- **The PSFs are a calibrated model, not built from field stars** (`PSFMETH = inject_stpsf`).
  - Each is STPSF put into the lens's own exposures and resampled as the data were.
  - Real stars match it to 0.3–1.6% in FWHM, star by star.
  - Its error map (`psf_err.fits`) adds two measured terms: how far real stars scatter about
    the model (per filter), and how far a compact source's PSF can sit from it depending on
    where it lands within the pixels (per band). The second is the error a bright lens core
    sees, and it is an over-estimate for the extended arcs.
  - Why a model: in the undersampled bands (F115W–F200W, F277W) the bright stars a PSF would be
    built from are resampled differently from a faint arc, so a star-built PSF comes out up to
    10–20% too narrow. Field stars are too few in the COWLS fields anyway.
  - Details are in AGENTS.md (*PSF*).
- **COWLS depth varies from lens to lens**, because it depends on where each lens fell in
  COSMOS-Web's dither pattern: 2–4 exposures per filter, and COSJ100028+021928 has a single
  SW exposure, so its F115W/F150W cosmic rays were caught on the ramp alone. COSJ095917+015424
  sits at the survey's southern edge: its lens is covered, but part of its stamp is not
  (noise 10⁸ there).
- **Redshifts** for every lens are in `info/samples/lens_samples.json`, each with its source and
  method. Only a spectroscopic redshift counts as confirmed here. A photometric one is always
  labelled: "photo-z" on the figures, and `redshift_*_kind: "photometric"` in the exported
  `info.json`. A missing value is `null`. All B1938+666 and SPT redshifts are spectroscopic. For
  the COWLS lenses, both redshifts are spectroscopic only for COSJ100018+022138 and
  COSJ100024+021749.

[`AGENTS.md`](AGENTS.md) has the measurements behind each of these.

## How the reduction works

JWST does not deliver one finished picture. It records each exposure as a series of
non-destructive readouts (a *ramp*), takes several exposures shifted slightly between them
(*dithered*), and spreads them over several detectors. For every lens and filter the pipeline:

1. **Downloads** the raw ramps from the JWST archive (MAST) and the matching calibration
   files. A NIRCam visit records all of its filters at once, so the whole visit is fetched
   and sorted by filter. For the COSMOS-Web survey, whose archive targets are survey tiles
   rather than lenses, only the detector exposures that overlap each lens's field are fetched.
2. **Fits the ramps** with STScI's `jwst` pipeline, rejecting cosmic-ray hits and their
   "snowball" splashes, and removing the 1/f stripes on the ramp itself (a step the pipeline
   leaves off by default, and the reason this repository starts from the raw ramps).
3. **Calibrates** each exposure (flat field, photometric calibration).
4. **Combines the exposures** into one mosaic: aligns the dithers with each other, matches
   their sky levels, rejects remaining outliers, and resamples onto a common North-up grid
   centred on the lens, at 0.03″ (SW) and 0.06″ (LW).
5. **Cuts out** the stamp around the deflector and writes the noise map from the mosaic's
   propagated error, times the measured correction above.
6. **Models the PSF** at the lens.
   - STScI's STPSF model is put into every exposure at the lens and resampled exactly as the data
     were, so it carries the same blurring, orientation and exposure weighting.
   - Its one free detector parameter, the charge diffusion, is calibrated on 243 real stars, each
     compared with a model star injected at the same position.
   - A PSF built from the field stars is made beside it as a check.
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
`data/reference_files/` (about 80 GB for the SPT and B1938 data, 45 GB more for COWLS), and B1938+666's raw ramps alone are 79 GB. Reducing its two filters took 8.5 hours;
the 17 COWLS lenses (38 GB of ramps) took about 11. The STPSF data files (needed only for the
model-PSF fallback) go in `data/reference_files/stpsf-data/`.

**Reduce one lens in one filter**, e.g. SPT2147-50 in F444W:

```bash
uv run python scripts/download_nircam.py --lens SPT2147-50                 # raw ramps from MAST, sorted by filter
uv run python scripts/reduce_nircam.py   --lens SPT2147-50 --filt F444W    # ramps -> calibrated exposures -> mosaic
uv run python scripts/make_stamps.py     --lens SPT2147-50 --filt F444W    # stamp + noise map
uv run python scripts/make_psf.py        --lens SPT2147-50 --filt F444W    # injected STPSF PSF (field-star ePSF as its check)
uv run python scripts/make_masks.py      --lens SPT2147-50                 # GUI: paint contaminants to remove
uv run python scripts/make_positions.py  --lens SPT2147-50                 # GUI: mark the multiple images
```

Whole samples run with `bash scripts/run_reduce_all.sh <sample>`, `run_stamps_all.sh` and
`run_psf_all.sh`, which log to `data/run_logs/` and count ok / no data / failed. Every step
skips work already done, so a run can be resumed after an interruption (`--force` rebuilds a
mosaic). `scripts/choose_best_band.py` (a GUI over the band overview) chooses each lens's primary
band by eye, starting from the suggestion `scripts/choose_primary_band.py` measures; the mask and
position tools draw it first. `scripts/export_dataset.py --lens <lens> --dest <dir>` writes a lens
in the dataset layout a PyAutoLens modelling project loads (`data.fits`, `noise_map.fits`,
`psf.fits`, `info.json`, which names the primary band).

## Repository layout

```
data/stamps/<sample>/[<category>/]<lens>/<filter>/   the finished products (in git; COWLS has prime/, multi_galaxy/, limited/, complex/)
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
B1938+666, the TEMPLATES program (Rigby et al. 2025) for the SPT lenses, and COSMOS-Web
(Casey et al. 2023) and the COSMOS-Web Lens Survey (Nightingale et al. 2025; Mahler et al. 2025)
for the COWLS lenses. The redshifts come from Tonry & Kochanek (2000) and Riechers (2011) for
B1938+666, Weiß et al. (2013), Reuter et al. (2020) and Spilker et al. (2016) for the SPT lenses, and, for the COWLS
lenses, Mahler et al. (2025) Table 1 (from DESI, the COSMOS-Web catalogue of Shuntov et al.
2024, Shuntov et al. 2025, van der Wel et al. 2013 and Jin et al. 2024). Please acknowledge the JWST data, e.g. *"This
work is based on observations made with the NASA/ESA/CSA James Webb Space Telescope. The data
were obtained from the Mikulski Archive for Space Telescopes at the Space Telescope Science
Institute, which is operated by the Association of Universities for Research in Astronomy,
Inc., under NASA contract NAS 5-03127 for JWST. These observations are associated with
programs #1355, #1727 and #8281."*

The reduction is built on STScI's [`jwst` pipeline](https://jwst-pipeline.readthedocs.io) and
[STPSF](https://stpsf.readthedocs.io), [Astropy](https://www.astropy.org),
[photutils](https://photutils.readthedocs.io) and
[PyAutoLens](https://github.com/PyAutoLabs/PyAutoLens) (mask and position tools).
