# Sky Quality Meter (SQM) in PiFinder

PiFinder estimates sky surface brightness from the same solved camera frames
used for pointing. The normal product path is deliberately zero-touch: after
the camera identifies itself, the built-in sensor profile supplies the
calibrated black level, passband transform, and SQM-L offset. A user does not
need flats, dark frames, or a calibration wizard to get a useful reading.

`SQM Correct` and the calibration wizard are optional refinements for a
particular session or device. They are not startup requirements and are never
run implicitly against an ordinary sky image.

## Accuracy demonstrated so far

The archive campaign validates the complete estimator, not just individual
formulae:

| Sensor | Evidence | Out-of-box result |
|---|---|---|
| imx462 | six clear SQM-L reference sweeps over multiple nights | cross-sweep residual σ ≈ 0.05 mag; typical error within ±0.1 mag |
| HQ/imx477 | three independent clear reference readings over eight months | residuals within about ±0.2 mag |
| imx296 | one moonlit reference sweep (SQM-L 17.8–17.9) | approximately ±0.2 mag; evidence is data-poor |

The final no-calibration regression replayed 540 archive frames from 11 clear
reference sweeps. Relative to the unmodified deepchart base, sweep-median MAE
improved from 0.084 to 0.081 mag and RMSE from 0.119 to 0.117 mag. By sensor,
imx462's six sweep medians have 0.050 mag residual scatter and 0.038 mag MAE
(range −0.018 to +0.131); HQ has 0.161 mag MAE, with the known sparse/suspect
references reaching −0.207 and +0.241; the single imx296 sweep is −0.021 mag.
No offset was fit during this replay and user calibration files were disabled.

These are in-sample results under a light-pollution-dominated Ghent sky. The
sensor offsets include the local sky spectrum, so dark airglow-dominated sites
may need a different offset. Bright cloud is a known physical limitation:
stars are attenuated above much of the city glow, so star-calibrated SQM reads
roughly 0.4–0.7 mag too bright. `CloudEstimator` detects the zero-point deficit
and reports it, but does not silently alter the published value.

## Runtime ownership and data flow

The solver process owns the steady-state measurement. The UI only reads the
latest state.

```text
camera capture
  ├─ 512×512 processed image ─► Cedar centroids + tetra3 solution
  └─ cropped raw sensor frame ─► raw mono / averaged Bayer-green photometry
                                      │
solution centroids ─► scale + undo display rotation
                                      │
                                      ▼
                                 SQM.calculate
                                      │
             ┌────────────────────────┼──────────────────────┐
             ▼                        ▼                      ▼
       SQMState.value           sqm_details          Wing/Cloud history
             │
             ▼
           SQM UI
```

The calculator is created lazily on the first solved frame. This matters: at
solver-process startup the camera process may not yet have published the real
sensor type. Lazy creation prevents the old race that applied imx296 constants
to imx462 or HQ frames.

SQM runs at most once every five seconds. A failed solve or failed photometric
measurement leaves the previous reading in place and retries on a later solve.

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

## Photometric reduction

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

The sky term is the median of the cleaned per-star annulus backgrounds. A
six-sweep A/B against a full-frame, source-masked median was a wash:
cross-sweep residual σ changed from 0.046 to 0.042 mag and median frame scatter
from 0.137 to 0.135 mag. The global median read 0.01–0.05 mag darker because it
included vignetted corners. Local annuli stay in production because they
sample the field near the same stars that determine the zero point, cost less,
and are the estimator against which the offsets were calibrated.

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

After converting background ADU per pixel to ADU per square arcsecond:

```text
sqm_sensor = mzero − 2.5 log10((sky − pedestal) / arcsec²_per_pixel)
sqm_final  = sqm_sensor + camera_profile.sqm_band_offset
```

The sensor offset maps the camera passband to the SQM-L scale under the
calibration sky regime. Current defaults are imx462/imx290 `+0.53`, HQ `+0.60`,
and imx296 `−0.22` mag; they are coupled to the current Gaia/colour, wing, and
local-annulus estimator.

`sqm_final` is the published reading. It intentionally has no atmospheric
altitude correction. When a real altitude is available, details also contain
`sqm_altitude_corrected = sqm_final + 0.28 × (airmass − 1)`. When altitude is
unavailable, PiFinder passes `None`; it no longer labels the field as a fake
90° zenith measurement.

`CloudEstimator` tracks the exposure-normalized stellar zero point. A deficit
from its recent clear-transmission baseline produces `cloud_extinction`,
`cloud_flag`, and an informational `sqm_cloud_corrected`. The main reading is
not silently changed.

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
- Bright clouds violate the simple “same attenuation for stars and sky” model.
- Flats can characterize vignetting for research, but normal operation must
  remain accurate without asking the user to take one.

See [`sqm/CONTEXT.md`](./sqm/CONTEXT.md) for canonical terminology and
[`docs/adr/0002-sqm-published-value-uncorrected.md`](../adr/0002-sqm-published-value-uncorrected.md)
for the published-value decision.
