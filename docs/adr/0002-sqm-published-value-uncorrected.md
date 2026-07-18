# Publish raw SQM, not the altitude-corrected value

`SQM.calculate()` returns both `sqm_final` (no extinction correction) and `sqm_altitude_corrected` (adds `0.28 · (airmass − 1)`). We publish `sqm_final` as `SQMState.value`; `sqm_altitude_corrected` is carried only in `details`. The 0.28 mag/airmass coefficient is an idealised V-band number, so under real atmospheric conditions the "corrected" value can deviate further from truth than the raw reading — an honest measurement is preferable to a confidently-wrong one. Users who need to compare across pointing altitudes can still read `sqm_altitude_corrected` from `details`.

When field altitude is unavailable, callers pass `None` and both
`extinction_for_altitude` and `sqm_altitude_corrected` remain absent. A missing
coordinate must not be represented as a fabricated 90° zenith observation.

## Consequences

- `shared_state.set_sqm(SQMState)` is **not** comparable across measurements taken at very different altitudes without consumer-side correction.
- Changing the published value to the corrected number would invalidate prior calibration runs and break any comparisons baselined on `sqm_final`.
- The glossary at [`docs/ax/sqm/CONTEXT.md`](../ax/sqm/CONTEXT.md) anchors the canonical meaning of bare "SQM" on this choice.
