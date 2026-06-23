# A failed plate-solve preserves the estimate; never reverts to "no solve" once anchored

On a `FailedSolve`, the integrator keeps the `estimate` cells (`pointing.camera.estimate`, `pointing.aligned.estimate`) intact rather than clearing them. Once the system has an anchor (has solved at least once), the last IMU-progressed pointing remains the published answer and `solve_state` stays true; the IMU advance keeps progressing it. "No solve" therefore only appears before the first successful solve.

## Context

The earlier design cleared the `estimate` cells on every failed solve "so consumers stop reading a stale camera pointing," relying on the IMU dead-reckoning step — which runs immediately after — to re-fill them. But the integrator publishes the failed-solve state *unconditionally* (to feed auto-exposure `Matches=0` on every attempt), and the IMU advance only fires when motion exceeds `IMU_MOVED_ANG_THRESHOLD` (the deadband). So whenever a solve failed while the PiFinder was held steady, the published estimate was the *cleared* one: `has_pointing()` → False → `solve_state` False → the UI flipped to "no solve" and stayed there until the next successful solve or a larger nudge. This was observed and reported on PR #429.

The clearing also contradicted the project's own glossary, whose example dialogue already said the integrator "keeps producing `pointing.aligned.estimate` from IMU dead-reckoning" across failures.

## Decision

- `_apply_failed_solve` preserves the `estimate` cells (and `estimate_time`); it only refreshes `diagnostics`, `last_solve_attempt` / `last_solve_success`, and sets `solve_source=CAMERA_FAILED`.
- The unconditional failed-solve publish stays (auto-exposure reads `solve_source`, `diagnostics.Matches`, and `last_solve_attempt` straight from `shared_state.solution()`), but it now carries the preserved pointing, so `solve_state` does not drop.
- "No solve" (`solve_state` False) is reserved for the genuinely-unanchored state: before the first successful solve.

## Considered options

- **Keep clearing, but always dead-reckon from the anchor on failure (ignore the deadband for the re-fill)** — rejected: more machinery for a result indistinguishable below the deadband (the anchor-dead-reckoned value differs from the preserved value by < 0.06°).
- **Debounce in the UI (show "no solve" only after N misses)** — rejected: masks the symptom in one consumer while the integrator keeps publishing no-pointing states to web, SkySafari, and the position server.

## Consequences

- A long run of failed solves while stationary keeps showing the last pointing with `solve_source=CAMERA_FAILED`. `RA`/`Dec` stay correct (the IMU is the authority on motion: deadband = not moved); `Alt`/`Az` are only recomputed on the IMU-advance / successful-solve publish, so they can lag during such a streak. Accepted as a minor, transient trade-off.
- Genuine "I'm lost" signalling on IMU failure (lost calibration, sensor dropout) is **not** handled here — it is an IMU-health concern, deliberately out of scope.
- Reverses the "clear the estimate cells on failure" detail documented alongside [ADR-0012](./0012-solver-integrator-message.md); the glossary and the `_apply_failed_solve` / `FailedSolve` docstrings were updated to match.
