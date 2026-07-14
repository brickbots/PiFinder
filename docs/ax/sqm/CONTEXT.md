# SQM (Sky Quality Meter)

The SQM context estimates sky brightness in magnitudes per square arcsecond from solved camera frames, and produces a "noise floor" ADU level that auto-exposure consumes. Lives entirely in the solver process at runtime; the UI is read-only.

> Companion architecture doc: [`../sqm.md`](../sqm.md).

## Language

### Measurements

**SQM**:
The PiFinder sky-brightness measurement, in magnitudes per square arcsecond. A photometric reduction from a single plate-solved frame, not a hardware-meter reading. Higher values mean darker skies.
_Avoid_: sky brightness number, mag-arcsec (qualify with the dataclass when relevant).

**`SQMState`**:
The published dataclass carrying the latest measurement (`value`, `source`, `last_update`). Lives in `SharedStateObj`; read by the SQM UI.
_Avoid_: SQM value (that's the float inside), sqm reading.

**`sqm_final`** (a.k.a. raw SQM):
The SQM number returned from `SQM.calculate()` **without** the altitude extinction correction. **Intentionally** the published value (`SQMState.value`) — the 0.28 mag/airmass coefficient is an idealised V-band number, so a `sqm_altitude_corrected` that's wrong in the wrong direction is worse than an honest raw reading. Bare "SQM" means this.
_Avoid_: corrected SQM (it's the uncorrected one).

**`sqm_altitude_corrected`**:
The SQM number after adding `0.28 · (airmass − 1)`. Carried in `details`, never in `SQMState.value`. Useful for comparing measurements taken at different pointing altitudes, but only as accurate as the idealised extinction coefficient — see `sqm_final` for the rationale that this is not the primary value.
_Avoid_: extinction-corrected (be explicit about altitude), corrected SQM (ambiguous).

**`mag/arcsec²`**:
The astronomical surface-brightness unit. Reference scale: 21–22 dark, 18–19 suburban, 16–17 bright city.
_Avoid_: mpsas (in code).

### Photometry

**Aperture**:
Circular pixel region around a star centroid where flux is summed. Default radius 5 px.
_Avoid_: star window, ROI.

**Annulus**:
Ring around each star (default inner 6 px, outer 14 px) used to measure the *local* sky background. Per-star local annuli — not a single global sky measurement.
_Avoid_: background ring, sky ring.

**Photometric zero point** (`mzero`):
Per-frame conversion constant between ADU flux and apparent magnitude: `mag = mzero − 2.5 · log10(flux_ADU)`. Flux-weighted mean over the matched stars.
_Avoid_: zero-point, calibration constant.

**Saturation threshold**:
Pixel value above which a star's aperture is excluded from `mzero`. Default 250 ADU for 8-bit processed frames; on the raw-green path it is set to `0.95 · (2^bit_depth − 1)` for the sensor's true bit depth.
_Avoid_: clipping threshold, max pixel.

**B−V**:
A star's Johnson blue-minus-visual color index, looked up per matched star from `hip_main.dat` keyed by HIP number (the `matched_catID` of a solve). Positive = red star, negative/near-zero = blue star. Missing values are `nan` and skip the color correction for that star.
_Avoid_: colour, B minus V without the star (be explicit it's per-star).

**Color coefficient** (`T`, `CameraProfile.color_coefficient`):
Per-sensor slope mapping B−V to a magnitude shift, because the sensor's real passband is not Johnson V. `T = 0.8` for bare color sensors (imx462/imx290 — the near-IR leak over-fluxes red stars); `T = 0` for IR-cut sensors (hq) and the unmeasured imx296 placeholder. A property of the optics + sensor, not the sky.
_Avoid_: color term (that's the whole correction, not the coefficient), CI slope.

**PSF wings** (wing loss):
The broad halo of a star image outside the photometry aperture — a property of the lens, not the sky. On PiFinder optics the r=5 px aperture misses ~25–38% of a star's total flux, biasing `mzero` low and SQM bright by 0.3–0.5 mag. The dominant absolute-scale error; corrected by the wing correction below.
_Avoid_: seeing halo (it's the lens, not the atmosphere), defocus (wings persist in focus).

**Wing boundary**:
The radius where a star's radial ring profile stops declining — wings end, true sky begins. Found per star by growing rings outward and cutting at the first ring with no significant further drop (slope-cutoff). Sky is measured beyond it, total star flux inside it.
_Avoid_: aperture cutoff, star edge.

**Enclosed fraction** (`f`):
Fraction of a star's total flux (out to the wing boundary) captured inside the photometry aperture. Per-frame sample = median over the bright, unsaturated, uncrowded matched stars.
_Avoid_: flux ratio, aperture efficiency.

**Wing correction** (`mzero_correction`):
The additive `-2.5·log10(f)` applied to `mzero`, from `WingEstimator`. **Measure/smooth/apply split**: `f` is measured only on frames that can support it (bright stars, SNR-gated), smoothed in a rolling window, and the smoothed correction applied to every frame. Measuring per-frame is forbidden — wings sink below noise at short exposures, which re-introduces exposure dependence (validated on sweeps).
_Avoid_: aperture correction (fine informally, but the code term is mzero_correction), zero-point offset (that's the rejected per-sensor constant — see ADR).

**`WingEstimator`**:
The rolling estimator in `sqm/wings.py` implementing the above; sibling of `PedestalEstimator` in design. Fed each SQM cycle with the photometry image + matched centroids; conditioned after `min_samples` frames; `correction()` returns 0 until then.
_Avoid_: halo estimator, PSF estimator.

**Effective magnitude**:
A matched star's catalog V transformed into this sensor's passband: `V − T · (B−V)`. Fed into the `mzero` fit in place of raw V. **Sign**: red stars (B−V > 0) become *brighter* through a NIR-leaky passband, so their effective magnitude is *smaller* — hence the minus sign. This is the **color term**, the same passband matching a hardware SQM-L meter's fixed spectral response applies; it is an instrumental correction, distinct from the atmospheric `sqm_altitude_corrected` (see ADR-0002 — the "publish uncorrected" argument is about the atmosphere, not this).
_Avoid_: corrected magnitude (ambiguous), green magnitude (that's a channel, not a transform).

**Per-star arrays**:
The bulky diagnostic arrays `star_centroids`, `star_mags`, `star_fluxes`, `star_local_backgrounds`, `star_mzeros` returned in `details` by `SQM.calculate()`. **Stripped** before `shared_state.set_sqm_details()` to keep proxy traffic small.
_Avoid_: star data, debug arrays.

### Atmospheric correction

**Airmass**:
Atmospheric path length relative to zenith, via Pickering (2002): `airmass(h) = 1 / sin(h + 244 / (165 + 47·h^1.1))` with `h` in degrees. More accurate near the horizon than `1/sin(h)`.
_Avoid_: secant z, optical depth.

**Extinction**:
Atmospheric attenuation per unit airmass. PiFinder uses 0.28 mag/airmass (V-band). Reported via `extinction_for_altitude` and folded into `sqm_altitude_corrected`.
_Avoid_: atmospheric loss.

### Noise model

**Black level**:
The static ADU floor a pixel reports at zero light — the sensor's quiescent output, applied so counts never clip at zero (Sony IMX sensors expose it as a "black level" register). Exposure-independent. This is the quantity **subtracted** from the measured sky background before the magnitude conversion. Matches standard imaging/photometry usage, where black level, bias, and (static) pedestal are the same floor. Sourced two ways: the per-frame joint-fit estimate `P0` (see `PedestalEstimator`), or the static `bias_offset` fallback.
_Avoid_: dark level, DC offset (overloaded), pedestal without qualifying that it means this static floor.

**Bias offset**:
The **static** black level as a fixed per-sensor constant: `CameraProfile.bias_offset`. The fallback source of the black level when no per-frame estimate is available; refinable via calibration JSON or zero-second samples. Same physical quantity as black level, named for its config field.
_Avoid_: bias, pedestal.

**`P0`** (joint-fit black level):
The intercept of `background = P0 + rate · exposure_sec` fit by `PedestalEstimator` over the auto-exposure stream. `P0` is the black level measured empirically per session; the fitted `rate` is the dark-current contribution and is **discarded**, not subtracted. Used as `pedestal_override` into `SQM.calculate()`.
_Avoid_: pedestal (P0 is the static floor, not an exposure-dependent total).

**Pedestal**:
In PiFinder code (`pedestal.py`, the `pedestal` / `pedestal_override` variables) this names the **static black level** that gets subtracted — i.e. `P0` or the `bias_offset` fallback. This follows mainstream imaging usage (pedestal = static floor). It does **not** include a dark-current term: dark current is fit as the slope and thrown away. When precision matters, prefer "black level".
_Avoid_: using "pedestal" for `bias_offset + dark_current` — that sum is never the subtracted quantity.

> Worked example: auto-exposure yields samples `(0.5 s → 240 ADU)`, `(2.0 s → 246 ADU)`, `(8.0 s → 270 ADU)`. The joint fit gives `rate ≈ 4 ADU/s` and intercept `P0 ≈ 238 ADU` — the black level. SQM subtracts `238` at **every** exposure; the `rate · exposure` sky/dark accumulation is exactly what SQM is measuring and must not be subtracted.

**Read noise**:
Random per-pixel noise from the ADC. Constant w.r.t. exposure. `CameraProfile.read_noise_adu`.
_Avoid_: ADC noise.

**Dark current**:
Thermal electrons per second per pixel. `CameraProfile.dark_current_rate` (ADU/s at ~20 °C). Scaled by `exposure_sec` to a per-frame contribution.
_Avoid_: thermal noise (it isn't noise — it's signal).

**Noise floor**:
The **published** ADU value (`shared_state.set_noise_floor()`) below which we treat pixel values as "empty sky + sensor noise" rather than real signal. Lower bound for sky background; the minimum acceptable background for the Camera context's background controller. When someone says "the noise floor" without qualifier, this is what they mean — never one of the intermediate quantities inside `NoiseFloorEstimator`.
_Avoid_: dark level, baseline, raw noise floor (use a qualifier — see below).

**Measured noise floor**:
Intermediate inside `NoiseFloorEstimator`: `np.percentile(image, 5.0)` of the current frame. Use the qualifier when this is what you mean — the bare "noise floor" refers to the published value.

**Smoothed noise floor**:
Intermediate: `np.median(dark_pixel_history)` once history ≥ 5 samples. Replaces the raw measurement once enough history has accumulated.

**Theoretical noise floor**:
Intermediate: `bias_offset + read_noise + dark_current_rate · exposure_sec`. Physics-based prediction, no image involved.

**Conservative noise floor**:
Intermediate: `min(smoothed_measurement, theoretical)` clamped to `≥ bias_offset`. The pre-validation candidate that becomes the published noise floor once `_validate_estimate` passes.

**`NoiseFloorEstimator`**:
The class that fuses a per-frame 5th-percentile measurement with a physics-based theoretical floor (`bias_offset + read_noise + dark_current_rate · exposure_sec`), choosing the more conservative value and smoothing with a 20-deep history.
_Avoid_: floor estimator, noise estimator.

**`CameraProfile`**:
Per-sensor record holding noise constants (`read_noise_adu`, `dark_current_rate`, `bias_offset`) plus hardware config (`format`, `raw_size`, `analog_gain`, …). Looked up by camera type (e.g. `imx296_processed`).
_Avoid_: sensor profile, camera config.

### Calibration

**Calibration JSON**:
Persistent calibration file at `~/PiFinder_data/sqm_calibration_<camera_type>.json` holding `bias_offset`, `read_noise`, `dark_current_rate`, `camera_type`, `timestamp`. Overrides the matching `CameraProfile` fields.
_Avoid_: cal file, sqm config.

**Zero-second sample**:
A single 0-second exposure used to measure `bias_offset` and `read_noise_adu` directly (no sky signal, no dark current). `NoiseFloorEstimator` periodically sets `request_zero_sec_sample=True` in `details` so the camera process can capture one. Runtime concept.
_Avoid_: dark frame (astrophotography sense — see ambiguities), zero sample.

**Dark sequence**:
A *series* of frames captured by the calibration wizard at increasing exposures. Used to fit `dark_signal = bias_offset + read_noise + dark_current_rate · exposure_sec` and extract those three constants. Wizard concept, multi-frame, multi-exposure. The frames are **not** stacked into a master dark — only the fitted constants are kept.
_Avoid_: dark frames (the astrophotography sense expects a master output; that's not what this produces), dark stack (stacking implies combining into one master, which doesn't happen here), darks.

**Sky frame**:
Capture-time term in the calibration wizard for the on-sky frames used to validate the resulting SQM number.
_Avoid_: light frame.

**Calibration wizard**:
The UI flow in `ui/sqm_calibration.py` that captures the dark sequence and sky frames, fits the three noise constants, writes the calibration JSON, and sends `["reload_sqm_calibration"]` on `align_command_queue` so the solver rebuilds its `SQMCalculator`.
_Avoid_: setup wizard.

### Distribution

**`shared_state.set_sqm(SQMState)`**:
The publication call. Read by `UISQM.update()` on the SQM screen. UI does not call `SQM.calculate()`.
_Avoid_: publish SQM, push SQM.

**`shared_state.set_sqm_details(dict)`**:
Publishes the diagnostic dict (with per-star arrays stripped). Consumed by the UI for advanced views and by the calibration wizard.
_Avoid_: set details.

**`shared_state.set_noise_floor(float)`**:
Publishes the latest noise floor. Read by the camera process and forwarded into the background controller (`ExposureSNRController.update(..., noise_floor=...)`) — see the [Camera context](../camera/CONTEXT.md).
_Avoid_: set floor.

### Timing

**`SQM_CALCULATION_INTERVAL_SECONDS`**:
Minimum wall-clock interval between SQM calculations in the solver loop. Default 5.0 s — the single knob bounding SQM cost.
_Avoid_: SQM interval, cadence.

**`reload_sqm_calibration`**:
The literal command string posted on `align_command_queue` by the calibration wizard. Causes the solver to rebuild its `SQMCalculator` from the freshest calibration JSON.
_Avoid_: refresh calibration, reload sqm.

### Boundary terms

- **`align_command_queue`** is owned by [Positioning](../positioning/CONTEXT.md); SQM uses it only to receive `reload_sqm_calibration`.
- **Matched centroids / FOV** come from tetra3 via the solver (Positioning); SQM is a downstream consumer of every successful solve.
- **`shared_state`** is part of the system-wide shared state — defined in Positioning.

## Flagged ambiguities

- **"Noise floor"** (bare) — the *published* ADU value (`shared_state.set_noise_floor()`). For the intermediates inside `NoiseFloorEstimator`, force a qualifier: **measured**, **smoothed**, **theoretical**, **conservative**. Bare "noise floor" never means an intermediate.
- **"Dark frame" (astrophotography sense)** is NOT used here. In astrophotography, a "dark frame" is one lens-capped exposure (often combined into a master dark) — readers may import that mental model. PiFinder has two distinct concepts instead: **dark sequence** (multi-frame, multi-exposure, wizard-time, used to fit noise constants — never stacked into a master), and **zero-second sample** (single 0-s exposure, runtime, refreshes `bias_offset` / `read_noise_adu`). Don't say "dark frame".
- **"SQM"** — without qualifier means the published `SQMState.value` (i.e. `sqm_final`, no extinction correction). The altitude-corrected number is `sqm_altitude_corrected` in details.
- **"Black level" / "pedestal" / "bias offset"** — all name the same **static** ADU floor that SQM subtracts, matching standard imaging usage. Prefer **black level** for the physical quantity, **bias offset** for the `CameraProfile` constant, and **`P0`** for the per-frame joint-fit estimate. "Pedestal" in the code means this static floor, **not** `bias_offset + dark_current`. Dark current is fit as the joint-fit slope and discarded, never added to the subtracted term.

## Example dialogue

> **Dev:** Why is SQM not updating right after a solve?
>
> **Domain:** Solver only enters the SQM block on solves that produced `matched_centroids`, and even then only once per `SQM_CALCULATION_INTERVAL_SECONDS` (5 s default). If `FOV` is missing or background is unphysical, `calculate()` returns `(None, {})` and the clock isn't advanced — next solve retries.
>
> **Dev:** What does the camera process care about?
>
> **Domain:** Just the noise floor. `set_noise_floor()` is the only line of communication. The background controller uses it as the minimum acceptable background — change SQM's interval gate and that auto-exposure signal changes cadence too.
