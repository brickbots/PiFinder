# SQM: radiometric zero point keyed to measured sky colour

ADR 0022 made the radiometer the published SQM source, calibrated by one
constant per sensor: `radiometric_zero_point`. Re-deriving that constant over
23 referenced imx462 sweeps spanning 17.5–20.9 mag skies, every attempt to fit
a single value disagreed with itself. The shipped `15.25` read about **0.10 mag
dark** at the light-polluted reference site and about **0.85 mag bright** at a
dark one. Averaging the two regimes produced a constant that was wrong at both
ends, and no amount of refitting fixed that, because the thing being fitted was
not a constant.

The cause is physical rather than statistical. The radiometer measures sky in
the **sensor's** passband; the reference meter measures **V**. The conversion
between them depends on the sky's *spectrum*: light pollution is sodium/LED and
green-weighted, airglow is grey and NIR-rich, and a bare Bayer sensor sees that
NIR while a V-band meter does not. Sky brightness is only a proxy for spectrum —
a bright airglow sky and a dim urban sky are not the same colour. **Sky colour
measures it directly**, and it is already in the frame: measured R/G runs
0.83–0.89 at the light-polluted site and 1.00–1.04 at the dark one.

| model for the zero point | residual sd |
|---|---|
| constant (previously shipped) | 0.337 |
| linear in sky brightness | 0.185 |
| **linear in measured sky colour (R/G)** | **0.079** |

## The decision

**The radiometric zero point is a function of measured sky colour, not a
constant.**

```text
effective_zero_point = radiometric_zero_point
                       + radiometric_colour_slope × (clamp(R/G) − radiometric_colour_pivot)
```

1. **`radiometric_colour_slope = 0` is a plain constant**, and is the default.
   Mono sensors have no colour to measure; a factory IR-cut sensor has
   essentially no NIR leak to correct. Both keep the previous behaviour exactly,
   so this change is scoped to the sensors whose physics calls for it — imx462
   and imx290 (`5.544` mag per unit R/G, pivot `0.85`).

2. **R/G is clamped to the calibrated range, never extrapolated.** The fit is
   evidence about the colours it saw (`0.83–1.04`) and nothing else. Both the
   raw and clamped ratios are recorded so an out-of-range site is visible in the
   archive rather than silently absorbed.

3. **The pivot is where the correction is zero**, chosen so a frame carrying no
   colour falls back to a sensible light-pollution-regime constant rather than
   to the fit's intercept. Mono sensors, and any frame whose mosaic phase cannot
   be trusted, take that path.

4. **`radiometric_zero_point` keeps meaning the profile constant.** The value
   actually applied is reported separately as
   `radiometric_zero_point_effective`, always present whether or not a
   correction was made, so archives stay comparable across this change.

5. **Mosaic phase is checked, not assumed.** Reading the red plane is more
   fragile than reading green, and the difference is not obvious: a 180°
   rotation maps the block `R G / G B` to `B G / G R`, so the two green sites
   are invariant while red and blue swap. An odd crop origin does the same.
   `crop_and_rotate` runs before the radiometer, so both are reachable from
   profile configuration alone. `_mosaic_phase_is_rggb` requires RGGB order (not
   merely "some Bayer format"), zero rotation, and even crop origins, and
   reports *no colour* rather than a wrong colour. A wrong R/G does not fail
   loudly — it returns a plausible number that is up to the clamp width wrong.

## Why this is not just a spare parameter

A free parameter always reduces in-sample scatter, so in-sample residuals cannot
justify one. Two things do.

**Leave-one-night-out cross-validation: MAE 0.247 → 0.108.** The load-bearing
row is holding out `20260720`, the only dark night. Trained on light-polluted
data alone, the colour model predicts an unseen regime at **0.312** against the
constant's **0.944**. It extrapolates rather than interpolating between fitted
points.

**The same fit on the HQ is rejected by cross-validation** (0.234 with colour vs
0.182 constant), and its colour slope measures **20× smaller** (+0.272 vs
+5.544). That is precisely what a NIR-leak term must do on a sensor with a
factory IR-cut filter. A model that won everywhere would be suspicious; one that
wins only where the physics predicts it should is a negative control, and it is
the strongest evidence here.

Against the archive, after the change:

| | before | after |
|---|---|---|
| imx462 median residual | −0.045 | **+0.005** |
| imx462 spread | −0.23 … **+1.08** | −0.18 … **+0.16** |
| the three dark-site sweeps | +0.76, +0.77, +1.08 | +0.16, −0.02, +0.005 |
| hq median residual | +0.181 | **+0.000** |

The ~1 mag dark-site error is gone and the light-polluted regime got *tighter*,
not traded away.

`scripts/evaluate_radiometer_archive.py` re-derives both models from the archive
and cross-validates them, so these claims can be reproduced or refuted rather
than taken on trust; `PiFinder/sqm/radiometric_fit.py` holds the fit and is unit
tested on synthetic sweeps with known answers.

### Clamping and the extrapolation claim

These are two different questions and they do not have the same answer. When
cross-validation holds out the only night of a given regime, clamping to the
*training* colour range pins the prediction at the edge of the fitted span, so
the model cannot extrapolate at all. The tool therefore reports both:
`colour_mae` (clamped — what shipping the model would actually have done) and
`colour_mae_unclamped` (whether the physical relation itself extrapolates), and
flags nights that fell outside the training range. The verdict is taken from the
clamped figure because that is the conservative one and the behaviour that
ships. The practical consequence: at a site *outside* `0.83–1.04`, the clamp
deliberately under-corrects rather than trusting the fit off its own end.

## Considered and rejected

- **Refit a single constant** (what this change was originally scoped to be).
  Tried first; it is what surfaced the problem. A constant cannot represent a
  quantity that takes two values, and the residual it leaves is not noise —
  it is structured by site.
- **Key the zero point to sky brightness** instead of colour. Better than a
  constant (sd 0.185 vs 0.337) and worse than colour (0.079), because brightness
  is only a proxy for spectrum. It also cannot extrapolate: a bright airglow sky
  would be corrected as though it were urban.
- **A colour term on every sensor.** Rejected by cross-validation on the HQ, and
  keeping it would have destroyed the negative control that makes the imx462
  result credible. The mono imx296 cannot use it at all.
- **Extrapolating the fit past its calibrated colour range.** A two-cluster fit
  with nothing between them constrains a line, not a physical law valid
  everywhere. Clamping under-corrects at the edges, which is the failure we
  prefer.
- **Measuring spectrum properly** (a filter, or a second sensor). Correct, and
  not available on hardware already in the field. R/G is what the existing
  sensor can report for free.

## Consequences

- Published SQM changes on imx462/imx290 and hq. Prior radiometric logs from
  those sensors are not directly comparable; `radiometric_zero_point_effective`
  in the archive is what makes future comparisons possible.
- **The dark-site anchor is one night (3 sweeps).** The cross-validation result
  is what makes the slope credible, not the sample size. A single systematic
  peculiar to that night — observer, meter, dew — maps directly onto the slope,
  because the slope is set by the lever arm between two colour clusters with
  essentially nothing in between. Treat `5.544` as provisional.
- **Sky colour is a proxy for spectrum, not a measurement of it.** Two different
  spectra with the same R/G are conflated. This is the model's known blind spot.
- **imx296 keeps a constant and is the weakest of the three.** It is mono, so it
  cannot use the colour model at all, and its calibration rests on 4 sweeps from
  one night and one observer. Its radiometric zero point is deliberately
  untouched here. A dark-site sweep from that camera is the single most useful
  thing anyone could add to the archive.
- Colour sensors that do not *use* the correction still record `background_red`
  and `background_green`. The HQ gets real values that its zero point ignores,
  which costs nothing and accumulates the data a future refit would need.
- Sweep metadata records the whole model, not just a constant, so a later refit
  can tell which model produced a given archive.

## Also settled here: the stellar band offsets

`sqm_band_offset` is read only by the stellar path, which is a diagnostic — the
published SQM comes from the radiometer — so these do not change what users see.
The values shipped before this change did not reproduce:

| profile | shipped | re-derived | evidence |
|---|---|---|---|
| imx296 | −0.22 | **−0.02** | 4 sweeps, residuals +0.13…+0.22 — tight |
| hq | 0.60 | **0.99** | 9 sweeps, 0.67 mag scatter → 0.99 ± 0.2 |
| imx462 | 0.53 | 0.514 | **control** — validates the replay method |

The HQ figure argues with the physics and is recorded as fitted, not physical.
The offset is nominally a passband term and the factory IR-cut implies ≈0, yet 0
puts the stellar SQM a full magnitude bright. Roughly a magnitude of the HQ
*stellar* chain is therefore unaccounted for and this constant is absorbing it.
Whoever finds the real error should refit rather than assume this number
transfers. Zeroing the median of a chain known to be broken also costs a
diagnostic signal, which is an accepted trade here only because the value is not
published.
