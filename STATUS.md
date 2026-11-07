# Status and next steps (2026-11-05)

A snapshot of where the products stand and what is left to do. [`AGENTS.md`](AGENTS.md) holds the
detailed record and how-to: the measurements, decisions and traps. This file holds only the to-do
picture. Update it when a step is done.

## Where things stand

| sample | lenses | reduced + stamps | PSF | masks | positions | extra-galaxy centres | exported for modelling |
|---|---|---|---|---|---|---|---|
| `b1938` | B1938+666 | F115W, F277W | injected STPSF | both bands | A, B | – | yes (`mask_radius` not settled) |
| `templates` | SPT0418-47, SPT2147-50 | 6 + 4 bands | injected STPSF | all 10 bands | both lenses (SPT0418-47 two sets, SPT2147-50 one) | – | no |
| `cowls-mahler` | 17 (1 `prime`, 3 `multi_galaxy`, 10 `limited`, 3 `complex`) | 4 bands each, re-cut on measured lens centres | injected STPSF, rebuilt on those centres | all 68 bands | 16 lenses (COSJ095920+015851 deliberately none); COSJ100018+022138 in two sets | the 3 `multi_galaxy` lenses | no |

(Samples renamed 2026-11-06: `spt` → `templates`, `cowls_spectacular` → `cowls-mahler`; the
COWLS prime/multi_galaxy categories split into prime/multi_galaxy/limited/complex the same day.)

- **Every PSF is STPSF injected into the lens's own exposures** and resampled as the science was.
  Its charge diffusion is calibrated on 243 stars; the field-star ePSF is kept as a check
  (AGENTS.md *PSF*).
- **Only spectroscopic redshifts count as confirmed.** Photometric ones are labelled wherever
  they appear. COWLS: 14 spectroscopic and 3 photometric lens redshifts, 6 spectroscopic source
  redshifts (2026-11-07 literature completion; AGENTS.md *Lens samples*).
- **GUIs:** North up, East left, with one image look. Positions snap within 1 px and `z` undoes
  (AGENTS.md *Masks, arc masks, positions, QC*).
- **Every lens has a primary band chosen by eye** (`best_band_visual`; B1938+666 F115W, both SPT
  lenses F444W, every COWLS lens). Every band of every lens has a contaminant mask, and every
  lens except COSJ095920+015851 (deliberately) has image positions.

## Open decisions on individual lenses

These are judgement calls, recorded with the evidence so far.

- **COSJ095953+023319, position 2 (the SE blob, 1.13" E, 1.30" S).** It is kept as image 2 of
  set 1, but the evidence is against it being an image of the same source as images 0 and 1.
  - Its colours differ from theirs by ~1 mag in each of F115W−F150W, F150W−F277W and
    F277W−F444W, in model-free apertures.
  - Its long axis lies 58–74° from the tangential direction, i.e. roughly radial, in all four
    bands, while images 0 and 1 are tangential to within 8–21°.
  - The bright galaxy 2.45" W, stretched tangentially, does not fit as its counter-image either:
    the geometry would need θ_E ≈ 2.1", against 1.44".
  - Options: drop it, or move it to its own set (key 2) and let a model decide.
- **COSJ095953+023319, coverage edge.** In F444W a 2|4-exposure edge runs within ~0.1" of the
  lens core. Image 0 lies on the 2-exposure side.
  - The noise map is right; it is real depth.
  - The PSF kernel matches the 4-exposure side. Image 0's resampled PSF differs by ~1.5% in
    F444W, more in SW.
  - A second kernel for that side is possible if it matters (AGENTS.md *Lens samples*, coverage
    edges).
- **COSJ100119+014849.** Set 1 holds three images around the second lens. The edge-on disc's
  own faint arc, ~1.6" NE, has no counter-image found, so it has no positions. Keep it unmasked.
- **COSJ100013+023424.** Extra-galaxy centres sit on the S nucleus and the NE knot.
  - Light-scaled estimates put their Einstein radii at ~0.43" and ~0.22"; both perturb the
    images well above the position precision.
  - The faint blue source 1.5" WNW is masked.
- **B1938+666 `mask_radius`.** Not settled; the contaminant masks reach in to 1.5" deliberately.
  Choose it at export.

## Next steps

1. **Settle the open decisions above,** then export each lens:
   ```bash
   uv run python scripts/export_dataset.py --lens <LENS> --dest <modelling-project>/data [--mask-radius R]
   ```
   The export writes the data, noise map, PSF and `info.json` (redshifts with their kinds, lens
   category, primary band), plus the mask, positions and extra-galaxy centres where they exist.
2. **Optional PSF refinement:** a second injected kernel for images that sit across a coverage
   edge from their lens (COSJ095953+023319 image 0 first).
3. **Measurements owed** (AGENTS.md *Not done yet*):
   - the 1/f verification: a blank-sky ACF from a `--start rate` stamp against the default;
   - a scale-matched noise-factor rescale, once the source-pixel scale is fixed;
   - the wisps on B4/A3/A4/B3;
   - tweakreg offsets recorded for the SPT and B1938+666 bands, which need an Image3 re-run.
4. **Code never run on JWST data:** `make_arc_masks.py` (expect small breakages) and
   `detect_arcs.py` (a stub).
5. **The HST sibling repo** has the PSF biases that were fixed here: the block-summed ePSF, the
   galaxy gate against the wrong reference, and the over-wide pedestal (AGENTS.md *PSF*,
   findings 1, 2 and 5). Port the fixes there.
