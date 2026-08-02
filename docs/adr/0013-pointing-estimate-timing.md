# `PointingEstimate` timing is the measurement epoch, not the publish time

The published pointing carries one timing field, `estimate_time`, defined as the **measurement epoch** of the data behind the current estimate — the camera frame's `exposure_end` for a plate-solve, the IMU sample's `timestamp` for an IMU-progressed estimate — both on the same `time.time()` wall clock. It replaces the old `solve_time`, which was a *publish* timestamp (`time.time()` at the moment the integrator produced the value) and was also misnamed: it updated on IMU advances, where no plate-solve occurred.

## Context

[ADR-0001](./0001-positioning-vocabulary.md) reserved **"solve"** for the plate-solve event (the `solve` state is "never IMU-touched") and **"estimate"** for the current, possibly IMU-progressed value. The timing fields didn't follow that split:

- `solve_time` was stamped `time.time()` at solve completion (`solver.py`) and again at `time.time()` on every IMU advance (`integrator.py`). On the IMU path it wasn't even the data's publish time — it was "when the integrator got around to reading the sample," which lags the actual sample by the IMU → `shared_state` → integrator latency.
- `cam_solve_time` held the last plate-solve's wall-clock completion, and consumers detected "is the live value still the raw solve?" via the fragile `solve_time == cam_solve_time` equality — the same parallel-fact pattern that caused the `solve_state` "no solve" regression on this branch.
- The `SuccessfulSolve` message carried a `solve_time` distinct from `last_solve_attempt` / `last_solve_success` (both already the frame's `exposure_end`).

## Decision

- Rename `solve_time` → **`estimate_time`** on `PointingEstimate`, redefined as the **measurement epoch** of the current estimate: camera frame `exposure_end`, or IMU sample `timestamp`. `time.time() - estimate_time` is therefore a true "age of the fix" regardless of source.
- **"Solve" means plate-solve, always.** The IMU never produces a "solve"; it advances the *estimate*. No `*_solve_*` name may carry an IMU-derived value.
- Remove `cam_solve_time`: under epoch semantics it is value-identical to `last_solve_success`. "Is the live value the raw plate-solve?" is answered by `solve_source` (`is_camera_solve()`); "time since last solve" reads `last_solve_success`.
- Remove `SuccessfulSolve.solve_time`: redundant with the message's `last_solve_success` (the solved frame's `exposure_end`). The integrator sets `estimate_time = result.last_solve_success` on the camera path and `estimate_time = imu.timestamp` on the IMU path.
- The IMU sample stamps **its own** capture `timestamp` in the IMU process. This required migrating the `shared_state.imu()` dict to the `ImuSample` dataclass (which gains a `timestamp` field and a `to_dict()` for the JSON API).

## Considered options

- **Keep `solve_time` as publish time** — rejected: it conflates "when computed" with "what the value represents," and on the IMU path it's neither (it's the integrator's read latency). Telemetry and any future inter-sample interpolation want the measurement epoch.
- **Take the IMU-path fix literally (IMU = sample time, camera = solve-completion wall clock)** — rejected: `estimate_time` would then mean two different things depending on `solve_source`. Making the camera path use `exposure_end` keeps one meaning across both sources.
- **Keep `cam_solve_time` for the `cam_active` check** — rejected: a value-identical duplicate that can drift; `is_camera_solve()` already expresses the intent from a single source of truth.

## Consequences

- `estimate_time` mixes a camera-stamped timestamp and an IMU-stamped timestamp; correctness depends on both being the same `time.time()` clock. They are (camera: `camera_interface.py`; IMU: `imu_pi.py`).
- The `imu` field of `/api/status` and `/api/imu` changes from a stringified quaternion (the old `default=str` fallback) to a structured `ImuSample.to_dict()` — a strict improvement; no structured consumer read the old form. This unblocks the telemetry work flagged on PR #429.
- `move_start` / `move_end` (long marked TODO-remove, never read) are dropped in the `ImuSample` migration.
