# Positioning

The Positioning context produces and publishes the canonical "where is the telescope pointed?" answer. Plate-solving (`solver.py`) and IMU dead-reckoning (`integrator.py`) cooperate to feed `shared_state.set_solution()`; every other process (UI, web, position server, catalogs) reads through `shared_state`.

> Companion architecture doc: [`../positioning.md`](../positioning.md).

## Language

### Core record

**`PointingEstimate`**:
The canonical "where are we pointing?" record. Travels through `solver_queue` and `shared_state.set_solution()`. Holds a `PointingMatrix` (the four cells of the 2 × 2 matrix), the IMU anchor, Alt/Az, source/timing fields, `SolveDiagnostics`, and `AlignmentResult`. Defined in `PiFinder/types/positioning.py`.
_Avoid_: solved dict, pointing dict, solution record.

**`solve_source`** / **`SolveSource`**:
Tag on the record recording who produced the current pointing. New `SolveSource` enum: `CAMERA` (`"CAM"`), `CAMERA_FAILED` (`"CAM_FAILED"`), `IMU`. Enum inherits `str` so legacy string equality still works.
_Avoid_: origin, source.

**`solve_state`**:
Boolean flag on `shared_state` indicating whether *any* current pointing solution exists. Separate from the `PointingEstimate` so the UI can poll cheaply.
_Avoid_: is_solved, has_pointing.

### Coordinates: the 2 × 2 matrix

The positioning system tracks **two axes** (the camera optical axis, and the aligned eyepiece direction), each in **two states** (the latest plate-solve value, and the current IMU-progressed estimate). The canonical access shape is `pointing.<axis>.<state>.<RA|Dec|Roll>`:

|                  | **`solve`** — plate-solve truth | **`estimate`** — current (may be IMU-progressed) |
|------------------|----------------------------------|----------------------------------------------------|
| **`camera`** — optical axis  | `pointing.camera.solve`  | `pointing.camera.estimate`   |
| **`aligned`** — eyepiece direction | `pointing.aligned.solve` | `pointing.aligned.estimate` |


**Camera axis** (`camera`):
The pointing at the camera's optical centre. The IMU dead-reckoning anchor is `pointing.camera.solve` paired with `last_solve_imu`. Never `aligned.*` — the IMU is rigidly attached to the camera, not the eyepiece.
_Avoid_: camera_center (legacy field name), optical axis pointing, image center.

**Aligned axis** (`aligned`):
The pointing at the calibrated eyepiece centre — i.e. RA/Dec at the **target pixel** (see below). What every downstream consumer ultimately reads.
_Avoid_: eyepiece pointing (fine in user-facing copy; in dev prose say "aligned"), target_pixel (that name is now reserved for the image-space pixel coordinate, not the RA/Dec — see below).

**Solve state** (`solve`):
The value produced by the latest plate-solve. Never touched by the IMU. `pointing.camera.solve` is the truth reference for IMU anchoring; `pointing.aligned.solve` is the truth reference for diagnostics and recovery.
_Avoid_: last_solve (legacy field name), truth, raw.

**Estimate state** (`estimate`):
The current value, equal to `solve` immediately after a plate-solve and progressed forward by IMU dead-reckoning between solves. This is what consumers read.
_Avoid_: current, IMU pointing (the IMU only progresses the estimate; saying "IMU pointing" obscures that it's still anchored on a plate-solve).

**Pointing** (`Pointing`):
The unit triple `(RA, Dec, Roll)` in degrees. The leaf type at every cell of the matrix. Bridge to radians via `Pointing.as_radecroll()`.
_Avoid_: pointing (lower-case, unqualified) — that means `pointing.aligned.estimate`. See below.

**`pointing`** (the dataclass field):
The top-level container on `PointingEstimate`. Holds the four cells of the matrix. Lower-case `pointing` in prose (no code-style markup) means `pointing.aligned.estimate`; capitalised / code-style `pointing.x` means the field itself.
_Avoid_: confusion with the prose word — context disambiguates by markup.

**Pointing** (lower-case, unqualified, in prose):
`pointing.aligned.estimate`. The aligned (eyepiece) direction as currently estimated. The default answer to "where is the telescope pointed?".
_Avoid_: scope direction, telescope direction (fine in user-facing copy; in dev prose say "pointing").

**Target pixel** (`target_pixel`):
The `(Y, X)` pixel in 512×512 camera-image space where the eyepiece centre is calibrated by the alignment system. This is the coordinate the alignment flow produces. Persisted as `Config["target_pixel"]` and read via `shared_state.target_pixel()`. Default `(256, 256)` means no offset known. Passed to tetra3 as its `target_pixel` argument on every solve.
_Avoid_: solve_pixel (legacy name), reticle pixel, aligned pixel (the *axis* is called aligned; the *pixel* is called target).

> Three names, three concepts, no overlap:
> - **Target pixel** = `(Y, X)` image-space coordinate from alignment (the *pixel*).
> - **Aligned** = the RA/Dec direction *at* the target pixel (the *axis*).
> - **`pointing.aligned.estimate`** = the current IMU-progressed value of that direction (the *value the user sees*).

**`RaDecRoll`**:
Radian-based, quaternion-aware coordinate dataclass in `PiFinder/types/coordinates.py`. Used by `ImuDeadReckoning`. `Pointing.as_radecroll()` bridges from degrees → radians.
_Avoid_: coords, position tuple.

### Acquisition

**Plate solve**:
Identifying which patch of sky an image shows by matching detected star centroids against a star-pattern catalog. PiFinder uses [tetra3](https://github.com/esa/tetra3).
_Avoid_: astrometric solve, blind solve.

**Centroid**:
Sub-pixel `(y, x)` coordinate of a star-like point source. Produced by `PFCedarDetectClient` (preferred) or `tetra3.get_centroids_from_image` (fallback).
_Avoid_: star pixel, point source.

**Matched centroid**:
A centroid that tetra3 was able to identify against a known star. `solution["matched_centroids"]` is required before SQM runs.
_Avoid_: identified star, recognized centroid.

**Cedar / cedar-detect**:
The separate gRPC service (`cedar-detect-server`, default `127.0.0.1:50551`) that does fast star detection. PiFinder talks to it via `PFCedarDetectClient`, optionally with POSIX shared-memory zero-copy.
_Avoid_: detector, star detector.

**Tetra3**:
The plate-solving library bundled under `python/PiFinder/tetra3/`. Uses `tetra3/data/default_database.npz`.
_Avoid_: solver (that name is overloaded — see below).

**Solver** (the process):
The PiFinder process owning `solver.py`. It drives the plate-solve loop and is the sole runtime caller of `SQM.calculate()`.
_Avoid_: tetra3 (the library is one thing the solver process uses; they are not synonyms).

### Diagnostics

**`Matches`**:
Count of stars tetra3 matched in the most recent solve attempt. Published on every attempt (success or failure) because auto-exposure depends on it.
_Avoid_: matched stars, hit count.

**`RMSE`**:
Tetra3 residual in pixels for the most recent solve. Diagnostic only.
_Avoid_: error, residual.

**`last_solve_attempt`**:
The `exposure_end` (camera-stamped timestamp) of the most recent frame the solver tried to solve. Used to skip frames it has already seen.
_Avoid_: last_try, last_solve_time (different field).

**`last_solve_success`**:
The `exposure_end` of the most recent **successful** plate-solve.
_Avoid_: last_ok.

### Integration

**Integrator** (the process):
The process that fuses fresh plate-solves with IMU samples and publishes the result. Single owner of the `solve`-state values (`pointing.camera.solve`, `pointing.aligned.solve`) and the `ImuDeadReckoning` instance.
_Avoid_: fuser, merger.

**Anchor**:
The IMU dead-reckoning reference: the pair of `pointing.camera.solve` (camera-axis truth from the latest plate-solve) and `imu_anchor` (the IMU quaternion sampled on the same frame). Owned by the integrator. Updated only on successful plate-solves; preserved across failed solves so dead-reckoning continues.
_Avoid_: last_image_solve (legacy name), last_solve (this is the *state* name on a `PointingAxis`, not a field), last_solution.

**Dead reckoning** (`ImuDeadReckoning`):
Given a known pointing at the moment of the last plate-solve and the IMU quaternion at that moment, project the current IMU quaternion forward to a fresh `RaDecRoll`. Lives in `PiFinder/pointing_model/imu_dead_reckoning.py`.
_Avoid_: IMU tracking, prediction.

**IMU**:
The BNO055 sensor that supplies orientation. Sampled by the IMU process; read by the integrator via `shared_state.imu()`.
_Avoid_: gyro, sensor.

**IMU quaternion** (`imu_quat`, `q_x2imu`):
Unit quaternion (scalar-first) describing the IMU's orientation in its world frame. The name `q_x2imu` reads as "transform from frame `x` to IMU frame."
_Avoid_: orientation, quaternion (qualify it).

**`IMU_MOVED_ANG_THRESHOLD`**:
Deadband (0.06° ≈ 1.05 mrad) below which IMU motion is treated as noise and no dead-reckoning update is published.
_Avoid_: jitter threshold, IMU noise.

**Screen direction** (`screen_direction`):
Configuration field that tells `ImuDeadReckoning` how the display/IMU is physically mounted relative to the optical axis. Used to bake in axis conventions on initialisation.
_Avoid_: orientation, mount direction.

### Alignment

**Camera-to-telescope alignment**:
The process of learning which camera pixel coincides with the centre of the eyepiece view. Outcome: an updated **target pixel**. From then on, every solve reports RA/Dec at that pixel as `pointing.aligned`.
_Avoid_: telescope alignment, eyepiece alignment, scope alignment.

**Alignment target** (`align_ra` / `align_dec`):
Local state in the solver process holding the user's chosen sky coordinate while an alignment request is pending. Cleared once the result is posted.
_Avoid_: aim target.

**`align_on_radec`**:
Command on `align_command_queue` carrying `(ra, dec)` that arms alignment. Cleared by the matching `align_cancel` (timeout/user cancel).
_Avoid_: align command, request alignment.

**`["aligned", (y, x)]`**:
Response on `align_result_queue` carrying the pixel coordinates where the alignment target lands in the current frame.
_Avoid_: align result, pixel result.

### Queues & shared state

**`shared_state`** (`SharedStateObj`):
Multiprocessing-manager proxy carrying configuration, IMU samples, GPS fixes, the latest image, the published `solved` dict, and the SQM/noise-floor state. Read by every process.
_Avoid_: state, global state.

**`solver_queue`**:
One-way `multiprocessing.Queue`, solver → integrator. Carries the `solved` dict on every attempt, success or failure.
_Avoid_: solve queue, pointing queue.

**`align_command_queue` / `align_result_queue`**:
Pair of queues running alignment commands into the solver and pixel results back to the UI.
_Avoid_: align queue (singular — there are two).

### Boundary terms

- **SQM** is computed inside the solver process but is a separate context — see [SQM](../sqm/CONTEXT.md).
- **`shared_state.solution()`** is consumed by Catalog to compute visibility — see [Catalog](../catalog/CONTEXT.md).
- **GPS / time** are owned by the GPS process; Positioning is a consumer.

## Flagged ambiguities

- **"Pointing"** (unqualified, lower-case in prose) — means `pointing.aligned.estimate`. The eyepiece direction as currently estimated. Always qualify when you mean any of the other three cells in the 2 × 2 matrix.
- **"`pointing`"** (the dataclass field) vs **"pointing"** (the prose word) — disambiguated by capitalisation / code-style. `PointingEstimate.pointing` is the top-level container holding the four cells; bare "pointing" in prose means `pointing.aligned.estimate`.
- **"Solver"** — the PiFinder *process*. The plate-solving *library* is "tetra3". Don't conflate.
- **"Target pixel"** vs the **`aligned`** axis — the *pixel* is `(Y, X)` in image space, produced by alignment; the *axis* is the RA/Dec direction at that pixel. Don't say "target pixel" when you mean the direction; don't say "aligned" when you mean the pixel.
- **"Solution"** — be specific: `shared_state.solution()` returns the latest published `PointingEstimate`. The latest plate-solve values are the `solve` state inside; the current values consumers see are the `estimate` state.
- **Legacy `solved` dict** — historical name for the pre-dataclass position record. Code now uses `PointingEstimate`; the term may appear in old commits and PR descriptions but should not appear in current code or prose.

## Example dialogue

> **Dev:** During alignment, why does the published RA/Dec not jump?
>
> **Domain:** Alignment only changes the **target pixel** (the `(Y, X)` coordinate). It doesn't touch `pointing.camera` in either state, so the IMU model — anchored on `pointing.camera.solve` plus `last_solve_imu` — is untouched. The next plate-solve computes a fresh `pointing.aligned.solve` at the new target pixel; the integrator then promotes it to `pointing.aligned.estimate` for downstream consumers.
>
> **Dev:** What if the solve fails right after alignment?
>
> **Domain:** The solver pushes a `PointingEstimate` with `solve_source=CAMERA_FAILED`. The `solve`-state cells (`pointing.camera.solve`, `pointing.aligned.solve`) and `last_solve_imu` are preserved, so the integrator keeps producing `pointing.aligned.estimate` from IMU dead-reckoning. Auto-exposure still sees `diagnostics.Matches=0`, which is why we push on every attempt — success or failure.
