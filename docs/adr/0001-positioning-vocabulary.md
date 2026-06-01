# Positioning vocabulary: `pointing.<axis>.<state>`

The positioning system tracks pointing as a 2 × 2 matrix — two **axes** (`camera`, `aligned`) and two **states** (`solve` from the latest plate-solve, `estimate` from IMU dead-reckoning forward) — accessed as `pointing.<axis>.<state>.<RA|Dec|Roll>`. In prose, bare "pointing" means `pointing.aligned.estimate`. The `(Y, X)` pixel produced by alignment is named `target_pixel` (displacing the legacy `solve_pixel`).

`aligned` was chosen over `scope` because "scope" is heavily overloaded (telescope, eyepiece, finder, optical), while `aligned` carries the meaning that this axis is derived by taking the `camera` solve and applying the alignment offset — i.e. it names both the axis and the process that produces it.

## Consequences

- `PiFinder/types/positioning.py` field names `target_pixel` and `camera_center` will be renamed to `aligned` and `camera`; the legacy `solved` dict key `camera_solve` and the config key `solve_pixel` follow on the same rename pass.
- The companion glossary lives at [`docs/ax/positioning/CONTEXT.md`](../ax/positioning/CONTEXT.md); cross-reference for current code-vs-language status during the migration.
