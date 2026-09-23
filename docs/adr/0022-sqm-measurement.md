# SQM: how PiFinder measures and publishes sky brightness

This is the decision record for the SQM estimator, end to end. Its parts are
not independent: the pedestal, the zero point and the frame's own geometry each
set the scale of the published magnitude, so a decision about one is only
legible beside the others.

The vocabulary these decisions use lives in
[`../ax/sqm/CONTEXT.md`](../ax/sqm/CONTEXT.md); the measured accuracy and the
runtime wiring live in [`../ax/sqm.md`](../ax/sqm.md). This file holds the
decisions and, more importantly, the alternatives that were tried and failed.

---

## 1. What gets published

`SQM.calculate()` returns both `sqm_final`, with no extinction correction, and
`sqm_altitude_corrected`, which adds `0.28 × (airmass − 1)`. **`sqm_final` is
published as `SQMState.value`.** The corrected figure is carried only in
`details`.

The 0.28 mag/airmass coefficient is an idealised V-band number, so under real
conditions the "corrected" value can sit further from truth than the raw
reading. An honest measurement beats a confidently wrong one.

When field altitude is unavailable, callers pass `None` and both
`extinction_for_altitude` and `sqm_altitude_corrected` are absent. A missing
coordinate must never be represented as a fabricated 90° zenith observation.

**Consequences.** `shared_state.set_sqm(SQMState)` is *not* comparable across
measurements taken at very different altitudes without consumer-side
correction. Changing the published value to the corrected number would
invalidate prior calibration runs and break any comparison baselined on
`sqm_final`.

---

## 2. Where the value comes from: the radiometer, not the stars

**`SQMState.value` is derived from the diffuse raw-sensor background**, exposure
time, angular scale, detector pedestal and a per-sensor radiometric zero point.
It does not use the current frame's stellar zero point and does not require a
plate solve. Its state source is `Radiometer`.

```text
sqm = effective_zero_point
      + 2.5 log10(exposure_seconds)
      − 2.5 log10((sky − pedestal) / arcsec²_per_pixel)
```

The camera process reduces every raw matrix to a sparse central-median sample
while the matrix is still local. The solver collects those cheap scalars and
publishes their rolling median at most once per second and only after a new
frame. Aperture photometry runs at most once every ten seconds and only after a
solve.

**Stellar photometry is an independent transmission diagnostic, not the
published value.** Cloud changes the scene and is not corrected out of the
radiometric reading. A recent session-conditioned stellar deficit that is *not*
classified as cloud may correct instrument-side attenuation such as dew; a
factory prior alone cannot enable that correction.

**Consequences.** SQM keeps updating through failed solves and star-poor or
cloudy frames. Normal startup needs no flat, dark or user calibration. Factory
profiles own a radiometric zero point and a field width. Solver resolution and
SQM availability are decoupled.

---

## 3. Frame properties are read from the frame, not assumed

Three of the four inputs above come from the frame. The fourth, the zero point,
is a calibration constant. The reduction is therefore only as good as the
assumption that the frame in hand has the same **shape** and the same
**scaling** as the frames the zero point was fitted on. Two of those properties
were assumed rather than read, and both were silently violated.

### 3.1 Extent

`arcsec²_per_pixel = (field_width_degrees × 3600)² / pixels_per_side²`, where
`pixels_per_side` is the photometry image's height. That is correct only when
the frame height spans `field_width_degrees`.

Three extents are in circulation and only one is safe to measure. The live
camera path hands over the **crop**. Exposure sweeps archive the **whole
sensor**, so every replay meets that one. The solve image is a third, and
[ADR 0027](0027-fov-gate-derived-from-optical-train.md) already warns about it:
`OpticalTrain.fov_degrees` is the edge-to-edge angular width of *the crop*,
derived from `profile.crop_size` and the lens's effective focal length, and
`plate_scale_arcsec` notes that the solve image and the crop "differ by the
downscale factor, and confusing them silently" is the hazard.

The field width and the frame must therefore describe the same pixels. A
1080-row IMX462 frame measured against a field width describing the 980-row crop
credits every pixel with too little sky and reads `5 log10(1080/980)` = 0.211
mag bright.

**Decision.** `collect_radiometer_sample` reduces its input with
`profile.ensure_cropped()` before measuring anything. That is a no-op on the
crop the live path already hands it, so published values do not move; it makes
every offline replay measure what production measures by routing through the
ordinary crop rather than a second implementation of it.

### 3.2 Scaling: the analogue gain, not the reported digital gain

Raw pixels scale with the **analogue gain**, which the sensor applies before
the ADC. The driver cannot deliver every requested gain: a request of 30 on the
IMX462 delivers 29.51209…, 22 on the HQ delivers 21.78723…, 15 on the IMX296
delivers 14.96235…. Each value is exact and repeatable for a given request, on
both the stock Raspberry Pi OS stack and the NixOS stack.

**Decision.** The sample records the reported `AnalogueGain`, and
`radiometric_sqm` divides the corrected signal by
`reported / CameraProfile.calibration_analogue_gain`. The calibration value is
the gain the sensor delivered on the sweeps that fitted the zero point, stored
as the exact float the driver reports. A frame at that gain, and a frame that
reports no gain, both produce the value they produced before. `None`, the
default, turns the correction off.

Today no archived frame runs at a gain other than its profile's, and nothing in
PiFinder sends the camera's `set_gain` command. The correction is therefore a
no-op on every archived frame, which the replay confirms bit for bit. It exists
so that a changed gain request, whether from that command, a profile edit or a
different gain table, cannot silently shift the published value by
`2.5 log10` of the gain ratio.

**The stored constant must be the exact reported float.** A rounded value
(29.5121) makes every ratio 0.999997. On the IMX296 archive the sky sits about
1 ADU above the pedestal, and that ratio moves samples across the resolution
limit, which shifted single published values by up to 0.92 mag in the replay.
A test pins each constant to a float32.

Every consumer that reads `background_per_pixel` directly has to normalise
first, not only the magnitude conversion. `analogue_gain_ratio` is public for
that reason, and the black-level tracker (§4.1) is its other caller.

**The reported `DigitalGain` is recorded by the camera and deliberately not
used.** The IPA adds it to make up the shortfall between the requested and the
delivered analogue gain, so its base value is exactly that ratio: 1.01653 on
the IMX462, 1.00977 on the HQ, 1.00252 on the IMX296. The Raspberry Pi libcamera
fork on the stock image also divides it by the lowest colour gain. The ISP
applies it after the raw stream. A same-unit test confirms this: on the two
units whose reported gain changes from frame to frame inside a sweep, a fit of
`background = P0 + a·t·gain^k` gives **k = 0.20 ± 0.07** over ten sweeps, where
a gain in the raw array would give 1. A one-frame offset between metadata and
pixels does not raise it. See §7 for the correction that was tried and removed.

### 3.3 What is still assumed

The zero point and the field width. They remain the next thing to check when a
unit disagrees with a meter.

---

## 4. The pedestal

The size of the published magnitude depends directly on getting the subtracted
pedestal right, and it is the part of the estimator that has been rebuilt most
often. Precedence today, highest first:

1. an explicit `pedestal_override`;
2. a **leased tracked black level** (§4.1);
3. an optional user calibration's bias offset;
4. the profile `bias_offset`.

### 4.1 The tracked black level supersedes any stored bias

A stored bias term, whether from the profile or from the optional calibration
wizard, is measured once and then trusted indefinitely. That assumption is wrong
about the hardware: the optical-black clamp pins raw black to a target that
**moves with sensor state**, temperature being the suspect. On the 2026-07-18 IMX296 reference sweeps the delivered black
level was 55.9–56.3 ADU, while the device's own wizard said 58 and the profile
constant said 60. Both over-subtracted.

A few ADU is not harmless. Against a bright city background it is negligible; at
dark-site signal levels a 2–4 ADU over-subtraction produces a **−0.9 to −1.5
mag/decade** SQM-versus-exposure slope, and it kills short exposures outright,
because `sky − pedestal` goes non-positive and the frame is discarded as
`background_not_resolved_above_pedestal`. Night-to-night wander alone is worth
0.2–0.4 mag at a dark site.

**Decision.** `BlackLevelTracker` fits the pedestal as the intercept of sky
background against exposure over the running session, and supersedes both the
profile constant and any wizard-measured bias offset once its fit is **leased**.
The lease gates on the fit's standard error and deviation band; unleased, the
pedestal falls back to the stored constant. It needs no lens cap and no dark
frame, conditions from radiometer samples on every fresh frame rather than from
the 10-second stellar diagnostics, and so converges in minutes and keeps working
through failed solves.

The fit is against **gain-scaled** exposure. The analogue gain of §3.2
multiplies the sky signal but not the pedestal, so
`background = P0 + ratio · rate · t`. A window that mixes gains is a set of
lines with a shared intercept and different slopes, and fitting them as one
line moves the intercept, which is the published pedestal. `add_sample` takes
the ratio and regresses against `ratio · exposure`. Anything else that fits a
line through raw background, such as an offline refit, owes the same scaling.

### 4.2 The reported black level is not another source

Frames from a unit with an unpatched stack report `SensorBlackLevels` of 240.0
where the IMX462 profile assumes 238.0, which looks like a fourth pedestal
source worth 0.204 mag. It is not, and the distinction matters because the
"fix" would have been to trust a number that is wrong.

A sweep steps exposure about 40× at a fixed sky, so its background is a straight
line, `pedestal + rate × t`. The intercept is the pedestal in raw ADU, measured
from the pixels with no constant involved:

| Sweep | Fitted pedestal | Reported `SensorBlackLevels` | Profile |
|---|---:|---:|---:|
| markcasazza 20260912_021411 | 238.78 | 240.00 | 238.0 |
| markcasazza 20260912_072553 | 238.73 | 240.00 | 238.0 |
| mr2 20260721_233525 | 237.86 | 239.09 | 238.0 |
| mr2 20260721_235303 | 238.11 | 239.41 | 238.0 |

The profile constant is right and the reported value is libcamera's static
tuning tuple, carrying no marker that would let a reader tell a measured black
level from a tuning default. Taking it anyway raises
that unit's own mean absolute error over the archive from 0.117 to 0.185, and on
the IMX296 sweeps the static 240.0 sits at or above the background, so the
radiometer publishes nothing at all on 0 of 80 frames.

The same table discharges §4.1's dark-site obligation: on the two clear
21.4–21.6 mag sweeps the tracker returns 238.65 and 238.62 against those
independent fits of 238.78 and 238.73, agreeing to about 0.1 ADU on a sky where
the error it corrects is not swamped by the background.

---

## 5. The zero point is keyed to measured sky colour

Re-deriving `radiometric_zero_point` over 23 referenced IMX462 sweeps spanning
17.5–20.9 mag skies, every attempt to fit a single value disagreed with itself.
The shipped 15.25 read about 0.10 mag **dark** at the light-polluted reference
site and about 0.85 mag **bright** at a dark one. Averaging produced a constant
wrong at both ends, because the thing being fitted was not a constant.

The cause is physical. The radiometer measures sky in the **sensor's** passband;
the reference meter measures **V**. The conversion depends on the sky's
*spectrum*: light pollution is sodium/LED and green-weighted, airglow is grey
and NIR-rich, and a bare Bayer sensor sees that NIR while a V-band meter does
not. Sky brightness is only a proxy for spectrum — a bright airglow sky and a
dim urban sky are not the same colour. Colour measures it directly, and is
already in the frame: measured R/G runs 0.83–0.89 at the light-polluted site and
1.00–1.04 at the dark one.

| model for the zero point | residual sd |
|---|---|
| a single constant | 0.337 |
| linear in sky brightness | 0.185 |
| **linear in measured sky colour (R/G)** | **0.079** |

**Decision.**

```text
effective_zero_point = radiometric_zero_point
                       + radiometric_colour_slope × (clamp(R/G) − radiometric_colour_pivot)
```

1. **A slope of 0 is a plain constant, and is the default.** Mono sensors have
   no colour to measure; a factory IR-cut sensor has essentially no NIR leak to
   correct. Both keep the previous behaviour exactly, so this is scoped to the
   sensors whose physics calls for it — IMX462 and IMX290, 5.544 mag per unit
   R/G, pivot 0.85.
2. **R/G is clamped to the calibrated range, never extrapolated.** The fit is
   evidence about the colours it saw, 0.83–1.04, and nothing else. Both raw and
   clamped ratios are recorded so an out-of-range site is visible in the archive
   rather than silently absorbed.
3. **The pivot is where the correction is zero**, chosen so a frame carrying no
   colour falls back to a sensible light-pollution constant rather than to the
   fit's intercept. Mono sensors, and any frame whose mosaic phase cannot be
   trusted, take that path.
4. **`radiometric_zero_point` keeps meaning the profile constant.** The value
   actually applied is reported as `radiometric_zero_point_effective`, always
   present whether or not a correction was made, so archives stay comparable.
5. **Mosaic phase is checked, not assumed.** Reading the red plane is more
   fragile than reading green, and the difference is not obvious: a 180°
   rotation maps `R G / G B` to `B G / G R`, so the two green sites are
   invariant while red and blue swap. An odd crop origin does the same.
   `_mosaic_phase_is_rggb` requires RGGB order (not merely "some Bayer format"),
   zero rotation and even crop origins, and reports *no colour* rather than a
   wrong colour. A wrong R/G does not fail loudly — it returns a plausible
   number that is up to the clamp width wrong.

**Why this is not just a spare parameter.** A free parameter always reduces
in-sample scatter, so in-sample residuals cannot justify one. Two things do.

*Leave-one-night-out cross-validation: MAE 0.247 → 0.108.* The load-bearing row
is holding out the only dark night. Trained on light-polluted data alone, the
colour model predicts an unseen regime at 0.312 against the constant's 0.944. It
extrapolates rather than interpolating between fitted points.

*The same fit on the HQ is rejected by cross-validation* (0.234 with colour vs
0.182 constant), and its colour slope measures 20× smaller, +0.272 vs +5.544.
That is precisely what a NIR-leak term must do on a sensor with a factory IR-cut
filter. A model that won everywhere would be suspicious; one that wins only
where the physics predicts it should is a negative control, and it is the
strongest evidence here.

| | before | after |
|---|---|---|
| imx462 median residual | −0.045 | **+0.005** |
| imx462 spread | −0.23 … **+1.08** | −0.18 … **+0.16** |
| the three dark-site sweeps | +0.76, +0.77, +1.08 | +0.16, −0.02, +0.005 |
| hq median residual | +0.181 | **+0.000** |

The ~1 mag dark-site error is gone and the light-polluted regime got *tighter*,
not traded away. `scripts/evaluate_radiometer_archive.py` re-derives and
cross-validates both models so these claims can be refuted rather than taken on
trust; `PiFinder/sqm/radiometric_fit.py` holds the fit and is unit tested on
synthetic sweeps with known answers.

**Clamping and extrapolation are two questions with different answers.** When
cross-validation holds out the only night of a regime, clamping to the
*training* colour range pins the prediction at the edge of the fitted span, so
the model cannot extrapolate at all. The tool reports both `colour_mae`
(clamped — what shipping would actually have done) and `colour_mae_unclamped`
(whether the physical relation itself extrapolates), and flags nights outside
the training range. The verdict is taken from the clamped figure because that is
conservative and is what ships. At a site outside 0.83–1.04 the clamp
deliberately under-corrects rather than trusting the fit off its own end.

---

## 6. Stellar photometry, the diagnostic path

The stellar chain is not what users see (§2). It is the transmission
diagnostic, and its design decisions still bind.

1. **Photometry on the raw green channel**, never the processed display image,
   whose clipping, 8-bit quantisation and resize break the flux linearity
   photometry needs. For Bayer sensors the green channel is the mean of the two
   green sites; solve centroids are scaled from the 512 px processed frame to
   green-frame pixels. If the raw frame is unavailable the SQM cycle is
   **skipped**, never computed on the processed image with the raw profile.
2. **Colour term** `V − T·(B−V)` per matched star, B−V from Hipparcos by HIP id.
   The catalog magnitude is Johnson V but the sensor passband is not: bare
   colour sensors leak NIR and over-flux red stars. `T` is per-sensor
   (`color_coefficient`): 0.8 measured on-sky for bare IMX462/IMX290, 0.0 for
   the HQ (factory IR-cut; measured −0.05 ≈ 0), 0.0 *placeholder* for the IMX296
   mono, unmeasured. This is an instrumental passband match, the same thing a
   hardware meter's fixed spectral response does, and is distinct from the
   atmospheric correction §1 keeps out of the published value.
3. **Wing correction** (`WingEstimator`). Curve-of-growth measurement showed the
   r=5 px aperture misses 25–38% of each star's flux in the lens-halo wings,
   biasing `mzero` low and SQM bright by 0.3–0.5 mag. The estimator finds each
   star's wing boundary by growing rings until the profile flattens, measures
   the aperture's enclosed fraction `f`, smooths `f` in a rolling window, and
   applies `−2.5 log10(f)` to `mzero` every frame. **The measure/smooth/apply
   split is load-bearing**: wings sink below the noise at short exposures, so a
   per-frame correction re-introduces exposure dependence — measured slopes up
   to −1.2 mag/dex and 3–6× worse scatter.
4. **Robust mzero.** The zero point is the **median** of per-star zero points,
   not a flux-weighted mean, and stars peaking above 70% of full scale are
   excluded (CMOS response bends well before hard clip). A flux-weighted mean
   concentrates the vote in the brightest stars, exactly those prone to
   nonlinearity and colour-term extrapolation; B−V lookups are clamped to ≤1.2
   for the same reason. One near-saturated red giant dragged a night's SQM by
   0.5 mag under flux weighting; the median is unmoved — night-to-night spread
   0.63 → 0.06 mag on the IMX462 sweeps.
5. **Band offsets.** `sqm_band_offset` is read only by this path. Re-derived
   values: IMX296 −0.02 (was −0.22, 4 sweeps, tight), HQ 0.99 (was 0.60, 9
   sweeps, 0.67 mag scatter → 0.99 ± 0.2), IMX462 0.514 (was 0.53) as a control
   validating the replay method. **The HQ figure argues with the physics** and
   is recorded as fitted, not physical: the offset is nominally a passband term
   and the factory IR-cut implies ≈0, yet 0 puts the stellar SQM a full
   magnitude bright. Roughly a magnitude of the HQ *stellar* chain is
   unaccounted for and this constant is absorbing it. Whoever finds the real
   error should refit rather than assume this number transfers.


---

## 7. Considered and rejected

Gathered here because several of these were tried more than once, in different
parts of the estimator, and failed the same way each time.

**On the pedestal**

- *Trusting any reported black level without a measured-value marker.* §4.2.
- *A stored bias measured once.* §4.1. It cannot represent a quantity that
  drifts within a single session.
- *Re-running the calibration wizard more often.* Puts a lens cap, three minutes
  and a service flow in front of a value that drifts within a session, and
  contradicts the zero-touch product intent: normal operation must not require
  calibration.
- *Letting the user correct the residual by hand,* the removed `SQM Correct`
  setting. A magnitude-additive knob silently absorbs an ADU-space,
  brightness-dependent error, so it masks a pedestal fault instead of fixing it
  and produces a correction valid at exactly one sky brightness.
- *Estimating the pedestal from a low image percentile.* Ordinary sky pixels
  contain real sky light, so this biases the pedestal upward by a sky-dependent
  amount. `NoiseFloorEstimator` retains such percentiles as diagnostics only.

**On the zero point**

- *Refitting a single constant.* What §5 was originally scoped to be; trying it
  is what surfaced the problem. A constant cannot represent a quantity that
  takes two values, and its residual is structured by site, not noise.
- *Keying to sky brightness instead of colour.* Better than a constant (0.185 vs
  0.337) and worse than colour (0.079), because brightness is only a proxy for
  spectrum. It also cannot extrapolate: a bright airglow sky would be corrected
  as though it were urban.
- *A colour term on every sensor.* Rejected by cross-validation on the HQ, and
  keeping it would have destroyed the negative control that makes the IMX462
  result credible.
- *Extrapolating past the calibrated colour range.* A two-cluster fit with
  nothing between constrains a line, not a physical law. Clamping under-corrects
  at the edges, which is the failure we prefer.
- *Measuring spectrum properly,* with a filter or a second sensor. Correct, and
  not available on hardware already in the field.
- *A per-sensor additive magnitude offset against a reference meter.*
  Implemented, then removed. It rested on three hand-read meter points per
  sensor, and the residual it papered over turned out to be wing loss
  (correctable from data) plus night-to-night reference scatter (not a sensor
  property). A constant cannot represent either.

**On frame handling**

- *Cropping at every call site instead of inside the sample reduction.* Tried,
  as a docstring contract plus a CONTEXT entry. Three scripts, the live path and
  every future replay each had to remember it, and a rule with no enforcement
  point is not a rule. Inside the one function that reduces a frame it is
  unforgeable, and costs one size comparison per frame.
- *Refusing a full-sensor frame rather than reducing it.* Louder, and it would
  surface a mismatch immediately, but it makes every full-sensor sweep in the
  archive unreplayable, which is the opposite of what an archive is for.
- *Dividing by the reported `DigitalGain`.* Implemented and removed. It rested
  on two units that differed by 0.213 mag against a gain ratio that predicts
  0.221, but those units had different lenses and skies, and the match was
  chance. The same-unit test in §3.2 gives k = 0.20 ± 0.07, not 1. On the one
  other unit whose gain varies it moved the median error the wrong way, from
  +0.167 to +0.207 mag.
- *Normalising a gain to 1.0 rather than to the calibration value.* It
  double-counts the gain the zero point already absorbed.
- *Refitting each zero point with the gain divided out.* Equivalent in the end
  and strictly worse to land: it moves every calibrated device's published value
  on the same commit that introduces the mechanism, so a regression in either
  cannot be told from the other.

**On stellar photometry**

- *An IR-cut filter in hardware.* Clobbers the NIR sensitivity plate-solving
  depends on, and thousands of devices are already in the field.
- *Per-frame adaptive apertures,* radius ∝ HFD. Wings extend far beyond any
  HFD-scaled radius and the correction becomes exposure-dependent.
- *Low-percentile or minimum annulus background.* Order statistics of a noisy
  sky sit below truth by a noise-dependent amount, and noise varies with
  exposure — measured slopes to −0.6 mag/dex. Median, or a mode estimator on
  large samples, is the only safe annulus statistic.
- *A faint-star cut in the mzero fit.* Pooled statistics show the faintest flux
  quartile reading −0.11 mag, identically on IMX462 and HQ, because a fixed-ADU
  annulus error eats a bigger fraction of a small flux. Cutting those stars was
  scanned across the 8-sweep ensemble and made every metric worse: the median
  already absorbs the tail, and shrinking a 10–20 star sample toward 3–5 costs
  more in median noise than the bias removal gains. **Don't re-invent this.**

---

## 8. Consequences and standing obligations

- §3 moves only full-sensor frames. Over all 66 referenced archive sweeps,
  every cropped dataset replays bit-identical, frame for frame. Archive mean
  absolute error falls from 0.251 to 0.230 mag.
- The one full-sensor unit (markcasazza, stock image, 21.3 to 21.6 mag site)
  still reads 0.59 mag bright on this branch, which has no airglow floor. With
  the floor, the same sweeps read 0.24 mag bright. That residue is not gain
  (§3.2) and not the pedestal (§4.2). Pointing altitude explains at most about
  0.1 mag. The unit's stellar zero point is 0.13 ± 0.08 mag higher than the
  reference unit's, so it collects more light, and that explains about half.
  A factory radiometric zero point cannot see unit-to-unit throughput, and the
  stellar correction of §2 only corrects attenuation, in one direction.
- §5 and §6 each changed the published scale, so SQM logs are not comparable
  across firmware that predates them. `radiometric_zero_point_effective` in the
  archive is what makes comparison possible at all.
- **A profile whose zero point is refitted must update
  `calibration_analogue_gain` in the same change**, or the new zero point will
  be normalised against the old gain.
- `sqm_details` carries `black_level_tracked`, `black_level_pedestal`,
  `black_level_stderr`, `analogue_gain` and `analogue_gain_ratio`, so an archive
  replay can tell which pedestal and which scaling a frame was published under.
  The flags reflect what publication actually used, not the raw last fit.
- The published pedestal can differ between two units with identical profiles
  and identical calibration files. That is intended behaviour, not drift.
- The calibration wizard's most valuable output is the dark-current rate, not
  the bias offset it leads with: that offset is superseded whenever the tracker
  is leased, and its read noise is diagnostic only.
- **The dark-site colour anchor is one night, 3 sweeps.** Cross-validation is
  what makes the 5.544 slope credible, not the sample size. A single systematic
  peculiar to that night — observer, meter, dew — maps directly onto the slope.
  Treat it as provisional.
- **Sky colour is a proxy for spectrum, not a measurement of it.** Two different
  spectra with the same R/G are conflated. This is the model's known blind spot.
- **IMX296 is the weakest of the three.** Mono, so it cannot use the colour
  model at all, and its calibration rests on 4 sweeps from one night and one
  observer. A dark-site sweep from that camera is the single most useful thing
  anyone could add to the archive. Its `color_coefficient` of 0.0 is likewise an
  unmeasured placeholder.
- Still outstanding: an independent dark site on the HQ and IMX296 profiles.
