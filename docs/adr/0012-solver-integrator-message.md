# Solver→integrator message is a `SolveResult`, not a `PointingEstimate`

The solver puts a dedicated `SolveResult` DTO on `solver_queue` — a union of `SuccessfulSolve` and `FailedSolve`, dispatched by `isinstance()`. The integrator alone owns the long-lived `PointingEstimate`, building it by applying a `SolveResult` onto its instance. This splits the *transport message* (what the solver produces from one tetra3 attempt) from the *published aggregate* (the canonical "where are we pointing?" record), which had been conflated into a single type.

## Context

[ADR-0001](./0001-positioning-vocabulary.md) introduced `PointingEstimate` and the 2 × 2 `pointing.<axis>.<state>` matrix, replacing the legacy `solved` dict. In that pass the solver also built the `PointingEstimate` directly and pushed it on `solver_queue`. That overloaded `PointingEstimate` with two roles:

- The solver produces **solve-truth only** — it has no `estimate` concept (no IMU progression happens there) — yet was forced to populate the `estimate` cells equal to `solve` and build a full `PointingMatrix`.
- A failed solve built a **hollow** `PointingEstimate` (empty matrix, no anchor) that wasn't an estimate of anything.
- The integrator never trusted the snapshot wholesale anyway — it cherry-picked ~11 fields on success and 3 on failure.

## Decision

- `SolveResult = Union[SuccessfulSolve, FailedSolve]`, defined in `PiFinder/types/positioning.py`. The integrator dispatches on `isinstance()`, mirroring the existing `SolverCommand` / `AlignResponse` unions in the same module.
- `SuccessfulSolve` carries **flat** `camera` / `aligned` `Pointing`s (no `solve`/`estimate` split), an `Optional` `imu_anchor`, a single `solve_time`, `SolveDiagnostics`, `AlignmentResult`, and the matched-star arrays.
- `FailedSolve` carries only `SolveDiagnostics` (`Matches=0`) and `last_solve_attempt` / `last_solve_success`.
- The integrator maps `SolveResult` → `PointingEstimate` in `_apply_successful_solve` / `_apply_failed_solve`. `PointingEstimate` has **no** knowledge of `SolveResult` (no `from_solve_result()` / `apply()` method) — symmetric with the rule that `ImuDeadReckoning` never imports `PointingEstimate`.
- `solve_source` stays an **aggregate-only** field. The message type is the success/failure discriminant; `CAMERA` / `CAMERA_FAILED` / `IMU` survive as published states on `PointingEstimate`.

## Considered options

- **Keep `PointingEstimate` as the queue message** (status quo) — rejected: preserves the dual-role overload and the hollow failed estimate.
- **Pass a raw dict** — rejected: regresses ADR-0001's removal of the `solved` dict and drops type-checking on the one hop that most needs it.
- **One `SolveResult` with a `succeeded: bool` discriminant and `Optional` fields** — rejected: re-creates the "everything's Optional, hope you checked" hollow object the refactor exists to remove. Two types make illegal states unrepresentable and match the module's existing `isinstance`-dispatch idiom.

## Consequences

- `solver_queue` no longer carries `PointingEstimate`; the glossary entry and `positioning.md` were updated to match.
- The fan-out from one `Pointing` to both `solve` and `estimate` cells, and the preserve-on-failure anchor policy, live solely in the integrator — the single owner of the aggregate.
- Tests that previously re-implemented the integrator loop body inline (e.g. the failed-solve branch) can call `_apply_failed_solve` directly, so they guard the production path.
