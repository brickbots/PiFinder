# Sky Quality Meter (SQM) in PiFinder

This document describes how PiFinder estimates sky brightness in
magnitudes per square arcsecond, and how the same machinery produces a
secondary "noise floor" value that auto-exposure consumes.

It focuses on the runtime path that executes during normal solving:

- `PiFinder/sqm/sqm.py` — the `SQM` calculator (photometry + extinction).
- `PiFinder/sqm/noise_floor.py` — the `NoiseFloorEstimator` (camera physics + adaptive measurement).
- `PiFinder/sqm/camera_profiles.py` — per-sensor noise constants.
- `PiFinder/solver.py` — the only runtime caller of `SQM.calculate()`.

The UI side (`ui/sqm.py`, `ui/sqm_calibration.py`, `ui/sqm_correction.py`)
is summarized at the end. For the canonical glossary of terms and data
structures, see [`sqm/CONTEXT.md`](./sqm/CONTEXT.md).

---

## 1. Process layout

SQM is computed inside the **solver process** as a side effect of every
successful plate solve. It does not run anywhere else during normal
operation. The UI process only reads cached results.

```
   Camera ──► camera_image ──► Solver ──► SQM.calculate() (≤ once / 5 s)
                                    │
                                    ├──► shared_state.set_sqm(SQMState)
                                    ├──► shared_state.set_sqm_details(dict)
                                    └──► shared_state.set_noise_floor(float)

   shared_state.sqm()         ──► UI sqm.py
   shared_state.noise_floor() ──► camera_interface ──► auto_exposure (SNR target)
```

A second SQM call site lives inside the **calibration wizard**
(`ui/sqm_calibration.py`), which captures dedicated sky/dark frames and
runs `SQM.calculate()` against each. That code path is only active while
the user is on the calibration screen.

---

## 2. Data shapes

### 2.1 `SQMState` (`state.py:144`)

The published per-solve result. Lives in `SharedStateObj`:

| Field | Meaning |
| --- | --- |
| `value` | Sky brightness in mag/arcsec². Default `20.15` (typical dark sky). |
| `source` | `"None"`, `"Calculated"`, `"Manual"`, etc. |
| `last_update` | ISO-8601 timestamp of last calculation, or `None`. |

`shared_state.sqm()` returns this dataclass; `shared_state.set_sqm(...)`
replaces it. Two related setters live alongside:

- `set_sqm_details(dict)` — the diagnostic dict from `SQM.calculate()`
  (with the bulky per-star arrays stripped — see `solver.py:121`).
- `set_noise_floor(float)` — the latest ADU floor; consumed by
  auto-exposure (see §6).

### 2.2 `SQM.calculate()` return value

`(sqm_value, details)`:

- `sqm_value: Optional[float]` — magnitudes per arcsec² after photometric
  reduction. `None` if the solve had no matched stars, the FOV field was
  missing, or the background was unphysical.
- `details: dict` — diagnostics. The solver filters out
  `star_centroids`, `star_mags`, `star_fluxes`, `star_local_backgrounds`,
  and `star_mzeros` (the large per-star arrays) before publishing the
  rest via `set_sqm_details`. Keys retained include `mzero`, `mzero_std`,
  `background_per_pixel`, `pedestal`, `noise_floor_details`,
  `sqm_uncorrected`, `extinction_for_altitude`, `sqm_altitude_corrected`,
  and the aperture/annulus parameters used.

### 2.3 `CameraProfile` (`sqm/camera_profiles.py`)

Per-sensor noise constants used by `NoiseFloorEstimator`:

| Field | Meaning |
| --- | --- |
| `read_noise_adu` | Sensor read noise [ADU], constant w.r.t. exposure. |
| `dark_current_rate` | Thermal dark current rate [ADU/s] at ~20 °C. |
| `bias_offset` | Electronic pedestal [ADU]. Subtracted as part of pedestal. |
| `format`, `raw_size`, `analog_gain`, `bit_depth`, `crop_*`, `rotation_90` | Hardware config used by the camera process. |
| `typical_sky_background` | mag/arcsec² used as a sanity bound. |

Profiles are looked up by camera type (e.g. `imx296_processed`). Saved
calibration in `~/PiFinder_data/sqm_calibration_<camera_type>.json`
overrides `bias_offset`, `read_noise_adu`, and `dark_current_rate` when
loaded by `NoiseFloorEstimator.load_calibration()`.

---

## 3. The acquisition path: `solver.py`

The solver process owns the only steady-state caller. Two functions
matter:

### 3.1 `create_sqm_calculator(shared_state)`

Constructs an `SQM(camera_type=<camera>_processed)` once at process
startup, and again when an `align_command_queue` command of
`["reload_sqm_calibration"]` arrives — used by the calibration wizard
after it writes a new calibration JSON.

### 3.2 `update_sqm(...)`

Called from the solver loop on every successful tetra3 solve that
produced `matched_centroids` (see `solver.py:446`). The function:

1. **Reads `shared_state.sqm()`** and compares `last_update` to wall clock.
2. **Gates on `SQM_CALCULATION_INTERVAL_SECONDS` (5.0 s)** — if the last
   update is younger than 5 s, returns immediately. This is the single
   knob that bounds SQM cost from the solver's per-frame loop. (The
   solver loop itself is `~30 Hz` via `sleep_for_framerate`, so SQM
   fires at most once every ~150 solver iterations.)
3. **Calls `sqm_calculator.calculate(...)`** with:
   - `centroids` — all detected centroids (kept for compatibility; unused).
   - `solution` — the tetra3 solve dict (`FOV`, `matched_centroids`,
     `matched_stars` required).
   - `image_processed` — the 8-bit ISP-processed frame as a numpy array.
   - `exposure_sec`, `altitude_deg` — for noise scaling and extinction.
4. **Publishes results to `shared_state`** — `set_noise_floor`,
   `set_sqm_details` (filtered), and `set_sqm(SQMState(...))`.

Errors from `calculate()` are caught and logged; the solver loop is not
interrupted.

---

## 4. The math: `SQM.calculate()`

`SQM.calculate()` is a single pass over the matched stars. The full
formula it implements (from the class docstring) is:

```
For each matched star:
    local_bg = median(annulus pixels around star)
    star_flux = aperture_sum - local_bg × aperture_area
mzero = flux-weighted mean over stars of (catalog_mag + 2.5 · log10(star_flux))
sky_bg = median(all local_bg measurements)
SQM = mzero - 2.5 · log10((sky_bg - pedestal) / arcsec²/pixel) + extinction
```

Per-frame steps in order (see code paths in `sqm/sqm.py:315`):

1. **Field parameters** — `_calc_field_parameters(fov_degrees)` precomputes
   `arcsec_squared_per_pixel` from FOV and the fixed 512 × 512 frame size.
2. **Optional overlap exclusion** — `_detect_aperture_overlaps` is
   `O(N²)` in matched stars. **Disabled by default** (`correct_overlaps=False`).
3. **Noise floor estimation** — `NoiseFloorEstimator.estimate_noise_floor`
   runs a 5th-percentile measurement on the whole image, smoothed over
   the last 20 calls (see §5).
4. **Per-star photometry** — `_measure_star_flux_with_local_background`
   iterates over matched centroids. For each: extract a 2*outer_radius+1
   patch, build aperture and annulus masks via `np.ogrid`, take
   `np.median` of annulus pixels for local background, sum aperture
   pixels above background, exclude saturated stars (pixel ≥ 250 ADU
   anywhere in aperture). Returns `(star_fluxes, local_backgrounds,
   n_saturated)`. **This is the dominant per-call cost** — see §7.
5. **Sky background** — `np.median(local_backgrounds)` minus pedestal,
   clamped to ≥ 1.0 ADU.
6. **Photometric zero point** — `_calculate_mzero` does flux-weighted
   mean of per-star zero points; stars with non-positive flux are dropped.
7. **Magnitude conversion** — `sqm_uncorrected = mzero - 2.5 ·
   log10(background_flux_density)`.
8. **Extinction correction** — `_atmospheric_extinction(altitude_deg)`
   adds `0.28 · (airmass − 1)` using the Pickering (2002) airmass
   formula. The "main" `sqm_final` returned is **without** this
   correction; `sqm_altitude_corrected` is included in `details`.
9. **Diagnostics dict** — large; the solver filters out per-star arrays
   before publishing.

Default aperture parameters from the solver call site:
`aperture_radius=5`, `annulus_inner_radius=6`, `annulus_outer_radius=14`,
`saturation_threshold=250`, `correct_overlaps=False`.

---

## 5. Noise floor estimation: `NoiseFloorEstimator`

Lives in `sqm/noise_floor.py` and is owned by the `SQM` instance.

`estimate_noise_floor(image, exposure_sec, percentile=5.0)` per call:

1. **Measure** — `np.percentile(image, 5.0)` of the full frame.
   Appended to a 20-deep `deque` (`dark_pixel_history`).
2. **Theoretical floor** — `bias_offset + read_noise + dark_current_rate · exposure_sec`.
3. **Smooth** — once history ≥ 5, use `np.median` of the deque as the
   measurement; otherwise the raw current measurement.
4. **Choose conservative** — `min(measured, theoretical)`, but if the
   measurement is below `bias_offset` (physically impossible) fall back
   to theoretical. Floor is clamped to ≥ `bias_offset`.
5. **Validate** — `_validate_estimate` checks the floor isn't above 80 %
   of image median (would imply no stars detected) and isn't above
   `bias_offset + 20 · read_noise_adu`.
6. **Optional zero-second sample request** — every
   `zero_sec_interval` (300 s default) a flag is set in the details
   dict so the camera process can capture a 0-second exposure for
   recalibration. The hook is `update_with_zero_sec_sample()`. (Whether
   the camera process honors the flag is outside the SQM module.)

Per-frame cost is one full-frame percentile + one full-frame median for
the validity check + small deque ops. On a 512×512 8-bit frame this is
small but not zero — see §7.

---

## 6. Distribution

`shared_state.set_sqm(SQMState)` is read by `UISQM.update()`
(`ui/sqm.py:77`), which renders the latest value on the SQM screen.
`UISQM` does **not** call `SQM.calculate()` — it only reads cached state
and runs its own `sleep_for_framerate(shared_state)` (~30 Hz).

`shared_state.set_noise_floor(float)` is read by the camera process
(`camera_interface.py:252`) and forwarded to
`auto_exposure.SNR_target_offset(noise_floor=...)` (`auto_exposure.py:728`)
to set the minimum acceptable background for SNR-based exposure control.

---

## 7. Cost characterization (where the time goes)

Driven entirely by the per-star loop in
`_measure_star_flux_with_local_background`. For each matched star
(typically 10–60 from tetra3):

- A `(2·14+1)² = 841`-pixel patch is sliced from the image.
- `np.ogrid` builds y/x grids on the patch coords (not pixel-indexed).
- Two boolean masks (aperture, annulus) at ~841 pixels each.
- `np.median(annulus_pixels)`, `np.max(aperture_pixels)`, `np.sum(...)`.

The work is Python-loop-bound (one `for cy, cx in centroids` iteration
per star, with several small numpy calls inside). Numpy call overhead
on tiny arrays dominates the wall-clock cost. With 30 matched stars and
the default 5/6/14 radii, a single `calculate()` typically lands in the
**tens of milliseconds** on Pi-class hardware. Multiplying through the
5-second interval gate gives a steady-state average load of well under
1 % of one core in the solver process.

This call **does not** block the UI process (a separate process), but
the underlying single-core Pi will schedule them on the same CPU, so a
heavy `calculate()` can transiently steal cycles from the UI loop. See
the profiling harness for empirical numbers on a given host.

---

## 8. Calibration flows

### 8.1 Persistent file

`~/PiFinder_data/sqm_calibration_<camera_type>.json` — JSON dict with
`bias_offset`, `read_noise`, `dark_current_rate`, `camera_type`,
`timestamp`. Loaded by `NoiseFloorEstimator.__init__` via
`load_calibration()`; written by `save_calibration()` and by the
calibration wizard.

### 8.2 The calibration UI (`ui/sqm_calibration.py`)

A multi-step wizard (`CalibrationState`) that:

1. Captures a series of **dark frames** at increasing exposures to
   measure `bias_offset`, `read_noise_adu`, and `dark_current_rate`.
2. Captures **sky frames** and runs `SQM.calculate()` on each
   (`sqm_calibration.py:816`) to validate the result.
3. Writes the calibration JSON.
4. Sends `["reload_sqm_calibration"]` on `align_command_queue` so the
   solver process picks up the new constants without restart.

The wizard uses several `time.sleep()` calls (e.g. `sqm_calibration.py:127`)
to wait for camera state changes; those affect the wizard screen only.

### 8.3 Correction UI (`ui/sqm_correction.py`)

Allows a user-supplied offset to apply to the measured SQM. Stores the
offset; does not trigger recalculation.

---

## 9. Timing and gating rules

A few invariants worth knowing when modifying the SQM path:

- **One calculation per ~5 s.** Driven by
  `SQM_CALCULATION_INTERVAL_SECONDS` and the `last_update` check in
  `update_sqm`. Lowering this constant proportionally increases solver
  CPU.
- **No SQM on a failed solve.** The solver only enters the SQM block if
  `"matched_centroids" in solution` (`solver.py:439`). Failed solves do
  not advance the SQM clock.
- **Centroid format.** `matched_centroids` are already in `(y, x)`
  order; `SQM.calculate()` does not swap them. Don't re-swap upstream.
- **Image format.** `image_processed` must be 8-bit (uint8). The
  saturation threshold of 250 assumes 8-bit dynamic range.
- **FOV must be present** in `solution` or `calculate()` returns
  `(None, {})` and the solver clock is *not* advanced (next solve will
  retry).
- **Noise floor smoothing** needs ≥ 5 calls (~25 s wall clock at the
  default interval) before the rolling median takes over from the raw
  per-call percentile. Until then, the floor estimate is jumpy.

---

## 10. Glossary

The canonical glossary lives at [`sqm/CONTEXT.md`](./sqm/CONTEXT.md).
Use those terms when reading, writing, and discussing code in this area.

In particular: bare "SQM" means the published `sqm_final` (no altitude
correction) — see [`docs/adr/0002-sqm-published-value-uncorrected.md`](../adr/0002-sqm-published-value-uncorrected.md)
for the rationale. The wizard-time **dark sequence** (multi-frame
multi-exposure, fits noise constants) is distinct from the runtime
**zero-second sample** (single 0-s exposure, refreshes
`bias_offset`/`read_noise_adu`).
