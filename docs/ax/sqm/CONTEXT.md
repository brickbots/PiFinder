# SQM (Sky Quality Meter)

Canonical language for PiFinder's solve-independent sky-brightness measurement.
The architecture and validation evidence live in [`../sqm.md`](../sqm.md).

## Product intent

**Zero-touch SQM**:
Normal operation selects the built-in profile from the detected sensor and
starts measuring without flats, darks, or a calibration file. Optional Correct
and Calibration flows refine a unit or session; they do not establish basic
functionality.

**SQM**:
The published PiFinder sky surface brightness in mag/arcsec². Higher means a
darker sky. It is empirically calibrated to an SQM-L scale but is not claimed
to have an identical spectral or angular response.

**`SQMState`**:
Latest published `value`, `source`, and `last_update` in shared state. The UI
reads this state and does not calculate photometry.

**Radiometric SQM**:
The published fixed-calibration measurement from diffuse raw background,
exposure, pedestal, factory field width, and `radiometric_zero_point`.

**Stellar SQM (`sqm_star_calibrated`)**:
The former per-frame stellar-zero-point result. Retained as a transmission and
regression diagnostic; never the production primary or no-solve fallback.

**`sqm_altitude_corrected`**:
Optional comparison value `sqm_final + 0.28 × (airmass − 1)`. It is present
only when a real field altitude is known. It is never the primary reading.

## Images and coordinates

**Solve image**:
The processed 512×512 image used by Cedar and tetra3. It can be display-rotated.

**Raw photometry image**:
The linear cropped raw mono frame, or the mean of both Bayer-green sites. Star
flux and sky background are measured here, not on the processed solve image.

**Derotation**:
Mapping solve-image `(y, x)` centroids back to the orientation of the stored
raw frame using `solve_image_rotation`. Required before raw photometry.

**Centroid scale**:
Raw-photometry side length divided by 512. Both matched and all-detected
centroids must be scaled by it before use on the raw image.

## Stellar photometry

**Aperture**:
Circular radius-5-pixel region whose sky-subtracted sum is stellar flux.

**Annulus**:
The local sky ring from radius 10 through 18 pixels. Radius 10 is wing-safe on
the archive; the former 6–14 ring was contaminated by HQ PSF wings.

**Detected-source exclusion**:
Every Cedar centroid is masked out of every relevant annulus with an
aperture-radius disk. A 3σ clip catches unreported sources.

**Saturation threshold**:
`0.70 × (2^bit_depth − 1)` on raw photometry. The conservative limit rejects
stars in the sensor's nonlinear shoulder before hard clipping.

**Reference magnitude**:
Bare sensors use Gaia G with a BP−RP trim. HQ uses Hipparcos/Johnson V because
its factory IR-cut passband is closer to V. Missing Gaia data falls back to V.

**Fixed magnitude band**:
Catalog magnitudes 3.5–6.5. When at least five stars are available, only this
population votes on the frame zero point, preventing exposure-dependent
population drift.

**Photometric zero point (`mzero`)**:
Median of `reference_mag + 2.5 log10(star_flux)` over the selected population,
after a 3-MAD outlier rejection. Readings outside the fixed magnitude band do
not vote merely because a longer exposure detects them.

**MAD rejection**:
Three robust standard deviations (`1.4826 × MAD`) around the selected
population's median. Removes isolated catalog, colour, blend, or residual
nonlinearity failures; it does not replace the magnitude band.

**Wing correction (`mzero_correction`)**:
Rolling additive `−2.5 log10(f)`, where `f` is the aperture's enclosed stellar
flux fraction measured from a median-stacked curve of growth.

**`WingEstimator`**:
Conditions on several frames of bright unsaturated stars. Returns zero before
conditioning and naturally converges to zero for wingless optics. Do not
replace it with a per-star wing-boundary search; that approach integrated sky
noise and invented missing flux.

## Sky and detector model

**Local sky**:
Median cleaned annulus value for one matched star.

**Radiometer sample**:
Sparse central median reduced in the camera process on every raw frame. It
excludes the outer ten percent and records MAD, quadrant gradient, exposure,
timestamp, sequence, and native green/mono pixel scale.

**Stellar sky background**:
Median of local annulus skies, used only by stellar diagnostics.

**Bias offset**:
Static mean detector signal at minimum exposure, in raw ADU. Comes from the
built-in sensor profile unless an optional per-device calibration overrides it.

**Mean dark signal**:
`calibrated_dark_current_rate × exposure_seconds`. A mean exposure-dependent
signal, not an RMS noise term. Factory profile rates are unverified engineering
estimates and remain diagnostic until optional per-device calibration measures
the rate.

**Pedestal**:
The mean detector signal subtracted from sky background. The validated
zero-touch path uses `bias_offset`; an optional measured calibration uses
`bias_offset + mean_dark_signal`. An explicit total `pedestal_override` wins.

**Read noise**:
Zero-mean RMS variation in raw ADU. Diagnostic uncertainty; never subtracted
from sky signal.

**Unresolved background**:
Sky background no more than 1 ADU above the pedestal. SQM returns no new value
with `background_not_resolved_above_pedestal`; it does not clamp.

**`NoiseFloorEstimator`**:
Owner of one copied, optionally calibrated camera profile. Reports
the applied `pedestal + read_noise` as a raw-ADU operational threshold and
retains low image percentiles and the unapplied factory dark-current model only
for diagnostics. It cannot infer a dark calibration from ordinary sky images.

**Shared camera noise floor**:
The camera's exposure controller operates on processed 8-bit pixels. A raw-ADU
SQM threshold must not be published into it; the units differ.

**`CameraProfile`**:
Per-sensor hardware, detector, catalog-band, colour, and SQM offset constants.
`get_camera_profile()` returns a copy so optional calibration never mutates
global defaults or another calculator.

**Radiometric zero point**:
Exposure-normalized diffuse-sky conversion already mapped to the SQM-L scale.
It is fixed per shipped sensor/optics profile and does not change with current
stellar transmission.

**Radiometric field width**:
Factory angular width used for square-arcsecond conversion when no solve exists.

## Passband and atmosphere

**Colour coefficient**:
Per-sensor trim mapping catalog colour into the camera's stellar passband.

**SQM band offset (`sqm_band_offset`)**:
Additive mapping from sensor-band sky brightness to the reference SQM-L scale
for the calibrated sky regime. It is coupled to the catalog transform, wing
model, and local-annulus background estimator.

**Airmass / altitude correction**:
Pickering (2002) airmass and `0.28 mag/airmass`. Comparison-only; unknown
altitude is `None`, never a fabricated 90°.

**Transmission deficit / cloud flag**:
Deficit of exposure-normalized stellar zero point relative to clear
transmission. Cloud is diagnostic and does not alter scene brightness.

**Optics attenuation correction**:
Recent stellar deficit classified as dew/dirty optics and subtracted from the
radiometric magnitude. It requires a session-conditioned clear baseline;
factory priors alone cannot activate it.

## Optional refinement

**SQM Correct** (removed 2026-07-18):
The former user-entered session offset against a reference meter. Removed: a
magnitude-additive knob silently absorbs ADU-space (brightness-dependent)
errors such as pedestal bias, masking the fault instead of fixing it. The
reference comparison lives on as data: a SWEEP run with a reference reading
records the difference in its metadata.

**Calibration JSON**:
Optional `~/PiFinder_data/sqm_calibration_<sensor>.json` override containing
bias, read noise, and dark-current rate. Absence is the normal zero-touch case.

**Calibration wizard**:
Optional service flow. Captures minimum-exposure bias frames, fits temporal
read noise and multi-exposure dark signal, optionally validates against exact
timestamp-paired sky solves, saves JSON, and sends typed
`ReloadSqmCalibration`. It does not produce or require flats or master darks.

**Zero-second request**:
An estimator capability for an explicitly managed caller. Disabled in normal
SQM because no runtime camera path services the request.

## Timing and distribution

**`SQM_CALCULATION_INTERVAL_SECONDS`**:
One-second minimum interval between new-frame-driven radiometric publications.
Camera-side radiometer collection runs on every captured frame. Sleep mode does
not publish without its normal periodic capture.

**`SQM_STELLAR_DIAGNOSTIC_INTERVAL_SECONDS`**:
Ten-second minimum interval between expensive solved stellar transmission
diagnostics.

**`ReloadSqmCalibration`**:
Typed solver command that discards the calculator and resets wing/cloud
history; the next solve reconstructs it from detected sensor plus optional
calibration JSON.

**Per-star arrays**:
Large diagnostic fields (`star_centroids`, `star_mags`, `star_fluxes`, local
backgrounds, individual mzeros). Removed before publishing shared details.

## Avoid these ambiguous phrases

- “Processed SQM pipeline” — production photometry is raw; only solving uses
  the processed image.
- “Needs calibration” — factory profiles are the normal path; qualify an
  optional per-device or session refinement.
- “Dark frame required” or “flat required” — neither is required in normal
  operation.
- “Corrected SQM” — say session-corrected, altitude-comparison, cloud estimate,
  or passband-mapped.
- “Adaptive dark calibration” — ordinary sky percentiles contain sky signal
  and are diagnostic only.
