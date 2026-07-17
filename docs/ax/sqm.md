# Sky Quality Meter (SQM) in PiFinder

PiFinder estimates sky surface brightness directly from the linear raw camera
background. A plate solve is not required. The normal product path is
deliberately zero-touch: after
the camera identifies itself, the built-in sensor profile supplies the
calibrated black level, passband transform, and SQM-L offset. A user does not
need flats, dark frames, or a calibration wizard to get a useful reading.

`SQM Correct` and the calibration wizard are optional refinements for a
particular session or device. They are not startup requirements and are never
run implicitly against an ordinary sky image.

## Accuracy demonstrated so far

The archive campaign validates the complete zero-touch estimator, not just
individual formulae. A radiometer-first replay using sparse,
solve-independent raw backgrounds produced:

| Sensor | Evidence | Out-of-box production result |
|---|---|---|
| imx462 | six clear plus two cloudy SQM-L reference sweeps | clear sweep errors −0.053 to +0.061 mag; MAE 0.052 mag |
| HQ/imx477 | two reviewed clear reference sweeps plus cloud/attenuation cases | clear sweep errors −0.144 and −0.034 mag; MAE 0.089 mag |
| imx296 | one moonlit reference sweep with strong vertical readout bands | error +0.061 mag after factory fit; frame precision and evidence are poor |

Across the nine factory-eligible sweeps, the production 12-frame rolling
radiometer has bias −0.008 mag, residual σ 0.068 mag, MAE 0.061 mag, and RMSE
0.068 mag. It published on all 800 archived raw frames in the replay, including
318 frames without usable stellar photometry. The reproducible report and
per-frame output are in
`support/dumps/analysis/20260717/latest_production_pipeline/`.

One visually cloud-free but dim HQ session with about one magnitude of
instrument throughput loss reads 0.88 mag too dark before stellar attenuation
compensation. It remains the stress case for the session-conditioned dew/optics
guard. `sweep_20251118_001616_183sqm` has confirmed thin passing cloud and is a
scene-continuity test, not a factory anchor. The elevated scatter in
`sweep_20260716_000844` and `sweep_20260714_232132` accompanies visible vertical
pointing shake rather than cloud.

`sweep_20251027_201439` is visibly cloud-affected and includes frames with no
visible stars (automated extraction finds one zero-centroid frame and 37/100
frames with fewer than six centroids). It is a useful failed-solve continuity
case, not a clear-sky calibration sweep. The archive contains only processed
PNGs for it, so it cannot quantitatively replay the raw radiometer path.
Reviewed conditions and factory-fit eligibility are recorded in
`support/dumps/sweeps/sqm_archive_quality.json`, beside the archived sweeps.
The archive evaluator loads that manifest from the supplied sweeps directory
and never fits an unlisted or disallowed sweep.

With one archived frame modeled per second, the 10-second stellar diagnostic
flagged cloud samples but produced no automatic optics-compensated publication:
the short sweeps did not establish the 12-sample clear-session baseline needed
to distinguish instrument attenuation safely. The black-level tracker also
currently refines only stellar photometry; it does not alter the published
radiometer pedestal. Neither feature improves the headline archive accuracy in
the current production wiring.

These are in-sample results under a light-pollution-dominated Ghent sky. The
factory constants include the local sky spectrum, so independent units and dark
airglow-dominated sites remain required validation.

## Runtime ownership and data flow

The solver process owns the steady-state measurement. The UI only reads the
latest state.

```text
camera capture
  ├─ 512×512 processed image ─► Cedar/tetra3 ─► pointing
  └─ raw matrix ─► sparse central background sample (every frame)
                                      │
                                      ▼
                       rolling radiometric median (new frame, ≤ once / 1 s)
                                      │
             ┌────────────────────────┴──────────────────────┐
             ▼                                               ▼
   SQMState.value/source=Radiometer                    sqm_details

successful solve ─► raw stellar aperture photometry (≤ once / 10 s)
                 ─► transmission/cloud/dew diagnostics only
```

The calculator is created lazily on the first solved frame. This matters: at
solver-process startup the camera process may not yet have published the real
sensor type. Lazy creation prevents the old race that applied imx296 constants
to imx462 or HQ frames.

The cheap camera-side reduction runs for every captured frame. The radiometric
value publishes after a new frame at most once per second;
expensive stellar photometry runs at most once every ten seconds. A failed solve
does not stop radiometric SQM updates.

## Coordinate and image alignment

The processed solve image is display-rotated, while `cam_raw` is stored before
that display rotation. Production SQM therefore:

1. extracts mono raw data or averages the two Bayer-green sites;
2. scales 512 px solve centroids into the raw-photometry pixel grid; and
3. counter-rotates every matched and detected centroid using
   `solve_image_rotation`.

Skipping step 3 places star apertures on empty sky and causes errors of several
magnitudes. This mapping is covered by rotation tests for 0°, 90°, 180°, 270°,
and arbitrary rotations.

## Stellar diagnostic reduction

For each matched star:

```text
local sky = median(clean pixels in the 10–18 px annulus)
star flux = sum(5 px aperture) − local sky × aperture area
star zero point = reference magnitude + 2.5 log10(star flux)
```

All Cedar detections—not only catalog matches—are excluded from each annulus
with aperture-sized masks. A 3σ clip is a backstop for sources Cedar missed.
The inner radius is 10 px because archive growth curves demonstrated that the
old 6–14 px annulus contained HQ PSF-wing flux.

The stellar diagnostic's sky term is the median of cleaned per-star annulus
backgrounds. A
six-sweep A/B against a full-frame, source-masked median was a wash:
cross-sweep residual σ changed from 0.046 to 0.042 mag and median frame scatter
from 0.137 to 0.135 mag. The global median read 0.01–0.05 mag darker because it
included vignetted corners. Local annuli stay in production because they
sample the field near the same stars that determine the zero point, cost less,
and remain the estimator used for stellar throughput.

## Solve-independent radiometer reduction

While the raw matrix is still local to the camera process, PiFinder averages
the two Bayer-green sites (or keeps mono), excludes the outer ten percent, and
takes a median on a stride-four grid. Stars occupy far less than half of this
grid and therefore cannot move its median. Four quadrant medians record a cheap
gradient diagnostic. Only the small sample dictionary crosses process state.

Samples are converted to brightness individually and their recent median is
published. This preserves exposure changes rather than averaging raw ADU from
different exposures. Samples older than 15 seconds are discarded. In sleep
mode each periodic capture therefore starts a fresh estimate; no calibration
warm-up is required. Publication still needs a new frame, so this creates no
extra sleep wakeups.

### Performance and solver resolution

The reproducible archive benchmark is
`python/scripts/benchmark_sqm_pipeline.py`. On the development machine, the
camera-side collector costs 0.43 ms per IMX462 frame and 0.99 ms per HQ frame.
The equivalent green extraction plus full-frame median costs 1.83 and 4.38 ms.
Solved stellar diagnostics remain about 4.5 and 10 ms and run no more often
than every ten seconds. These are relative CPU checks; Pi hardware is
required for absolute power measurements.

The production solver remains on the processed 512×512 image. Across two
20-frame reference sweeps it solved 19/20 IMX462 and 18/20 HQ frames. Native
green solved fewer frames, while full Bayer centroid extraction cost roughly
3× (IMX462) to 7× (HQ) more and did not improve total success. Full-resolution
operation would also expand the shared image, UI/alignment coordinate space,
and Cedar workload. Radiometer availability therefore does not depend on
changing solver resolution.

## Exposure-stable zero point

Bare sensors use Gaia G with a small BP−RP trim; HQ, with its factory IR-cut
filter, uses Hipparcos/Johnson V. Stars without Gaia data fall back to V.

Only stars in a fixed catalog-magnitude band, currently 3.5–6.5, vote on the
frame zero point when at least five are available. This keeps the same stellar
population across the auto-exposure range. It removed the population-selection
drift measured when progressively fainter stars entered longer exposures.

The selected zero points are combined with a median. A 3-MAD rejection now
removes a remaining catalog, blend, or colour outlier before the median; it
does not replace or widen the fixed magnitude band.

## Aperture-wing correction

`WingEstimator` median-stacks sky-subtracted, aperture-normalized patches from
bright unsaturated matched stars. Its curve of growth measures the fraction
of stellar light enclosed by the 5 px aperture. The rolling correction
`−2.5 log10(f)` is added to the zero point.

The estimator returns zero until it has enough frames. On imx462 the measured
PSF is effectively enclosed (`f ≈ 1`); HQ can show focus-dependent wings
(`f ≈ 0.87–1`). This stacked method replaced a per-star boundary search that
integrated noise and invented 0.3–0.5 mag of missing flux.

## Detector baseline and failure policy

The physical calibrated mean detector pedestal is:

```text
pedestal = bias_offset + dark_current_rate × exposure_seconds
```

Out of the box, only `bias_offset` is subtracted. The built-in dark-current
rates are unverified engineering estimates, and applying the imx296 estimate
to the historical archive moved its median by +0.138 mag in the wrong
direction. Once the optional wizard measures a device's dark-current rate, its
mean exposure-dependent signal is included. This keeps factory behavior tied
to the validated sensor offsets while allowing a measured calibration to
refine it.

Read noise is zero-mean RMS uncertainty and is never subtracted as signal.
`NoiseFloorEstimator` retains a low image percentile only as a diagnostic;
ordinary sky pixels cannot provide an automatic dark calibration because they
contain real sky light. Periodic zero-exposure requests are disabled because
no runtime camera command path services them.

The default sensor profiles make this work without a calibration file. Profile
objects are copied per calculator, so an optional device calibration cannot
mutate process-global defaults or another calculator.

If the annulus background is no more than 1 ADU above the pedestal, SQM returns
no value with `failure_reason=background_not_resolved_above_pedestal`. It does
not clamp the background to 1 ADU and manufacture a plausible-looking number.

The raw detector threshold in `noise_floor_details` is not sent to the camera's
8-bit exposure controller: those values are in different units. The existing
processed-image background controller keeps its validated 8-bit threshold.

## Published value, altitude, passband, and cloud

After converting solve-independent background ADU per pixel to ADU per square
arcsecond using the factory field width:

```text
sqm = radiometric_zero_point
      + 2.5 log10(exposure_seconds)
      − 2.5 log10((sky − pedestal) / arcsec²_per_pixel)
```

The fixed zero point includes the passband mapping to the SQM-L scale. Current
defaults are imx462/imx290 `15.25`, HQ `14.79`, and imx296 `14.07`. Factory field
widths are 10.38°, 10.34°, and 13.71° respectively.

The radiometric value is the published reading and intentionally has no
atmospheric altitude correction. It measures the sky actually in the camera's
field rather than normalizing it to zenith.

`CloudEstimator` tracks the exposure-normalized stellar zero point independently
of the radiometer. Cloud is a property of the measured scene and is not
corrected away. After at least twelve clear session samples, a recent stellar
deficit classified as instrument-side attenuation can compensate dew or dirty
optics by subtracting that deficit from radiometric SQM. Factory priors alone
cannot enable this correction, and candidate frames do not erode the clear
baseline.

## Optional user refinement

### SQM Correct

The everyday refinement is a hand-held reference reading. PiFinder stores an
additive session correction and applies it to subsequent results. Removing it
returns immediately to the built-in profile.

### Calibration wizard

The service/diagnostic wizard is optional. It:

1. captures minimum-exposure, lens-capped bias frames;
2. estimates read noise from temporal pixel variance, not spatial fixed-pattern
   structure;
3. fits mean dark signal across multiple exposure times;
4. pairs each optional sky frame with the solve carrying that exact capture
   timestamp and runs the same raw/derotated/Gaia/wing path as production;
5. writes `~/PiFinder_data/sqm_calibration_<sensor>.json`; and
6. sends a typed `ReloadSqmCalibration` command.

Leaving the wizard restores the previous automatic or manual exposure mode.
No flat or master dark is produced or required.

## Important limits

- The instrument is empirically tied to an SQM-L scale, but its angular and
  spectral response is not identical to an SQM-L.
- Factory offsets are coupled to this estimator and the calibration sky
  spectrum; changing annuli, catalog band, wing model, or passband requires
  archive revalidation.
- HQ and especially imx296 need more independent reference nights.
- Cloud versus instrument attenuation at startup is not always identifiable;
  automatic optics compensation waits for a session clear baseline.
- Flats can characterize vignetting for research, but normal operation must
  remain accurate without asking the user to take one.

See [`sqm/CONTEXT.md`](./sqm/CONTEXT.md) for canonical terminology,
[`ADR-0022`](../adr/0022-sqm-radiometer-first.md) for radiometer-first ownership,
and [`ADR-0002`](../adr/0002-sqm-published-value-uncorrected.md) for the
no-altitude-correction decision.
