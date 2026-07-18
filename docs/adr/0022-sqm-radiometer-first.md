# Radiometer-first SQM with solve-independent publication

## Decision

`SQMState.value` is derived from diffuse raw-sensor background, exposure time,
factory angular scale, detector pedestal, and a fixed per-sensor radiometric
zero point. It does not use the current frame's stellar zero point and does not
require a plate solve. Its state source is `Radiometer`.

The camera process reduces every captured raw matrix to a sparse central-median
sample while the matrix is local. The solver collects these cheap scalar
samples and publishes their rolling median no more often than once per second
and only after a new frame. Expensive aperture photometry runs at most once
every ten seconds and only following a solve.

Stellar photometry is an independent transmission diagnostic. Cloud changes
the scene and is not corrected out of the radiometric reading. A recent
session-conditioned stellar deficit that is not classified as cloud may
correct instrument-side attenuation such as dew; a factory prior alone cannot
enable that correction.

The published value remains an uncorrected measurement at the current pointing;
the comparison-only altitude convention of ADR-0002 is unchanged.

## Consequences

- SQM continues updating through failed solves and star-poor/cloudy frames.
- Normal startup needs no flat, dark, or user calibration.
- Factory profiles now own a radiometric zero point and fixed field width.
- Solver resolution and SQM availability are decoupled.
- Current stellar SQM remains in diagnostics as `sqm_star_calibrated`; it is not
  a fallback primary calibrator.
- Sensor/lens production spread and dark-site passband behavior remain factory
  validation obligations.
