# Positioning

The Positioning context produces and publishes the canonical "where is the telescope pointed?" answer. Plate-solving (`solver.py`) and IMU dead-reckoning (`integrator.py`) cooperate to feed `shared_state.set_solution()`; every other process (UI, web, position server, catalogs) reads through `shared_state`.

> Companion architecture doc: [`../positioning.md`](../positioning.md).

## Language

### Core record

**`PointingEstimate`**:
The canonical "where are we pointing?" record. Owned by the integrator and published via `shared_state.set_solution()`. The integrator builds it by applying a `SolveResult` (see below) onto its long-lived instance — it does **not** travel on `solver_queue`. Holds a `PointingMatrix` (the four cells of the 2 × 2 matrix), the IMU anchor, Alt/Az, source/timing fields, `SolveDiagnostics`, and `AlignmentResult`. Defined in `PiFinder/types/positioning.py`.
_Avoid_: solved dict, pointing dict, solution record.

**`solve_source`** / **`SolveSource`**:
Tag on the record recording who produced the current pointing. New `SolveSource` enum: `CAMERA` (`"CAM"`), `CAMERA_FAILED` (`"CAM_FAILED"`), `IMU`. Enum inherits `str` so legacy string equality still works.
_Avoid_: origin, source.

**`solve_state`**:
Boolean flag on `shared_state` indicating whether *any* current pointing exists — the cheap-to-poll cache of `solution().has_pointing()`, kept as a bare bool so the UI need not round-trip the whole `PointingEstimate` across the manager proxy every frame. Written only by `set_solution` (which derives it from `has_pointing()`); never set independently.
_Avoid_: is_solved (for the flag's name). Note the value mirrors `PointingEstimate.has_pointing()` — that method is the source of truth; `solve_state` is its shared-state cache.

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
The unit triple `(RA, Dec, Roll)` in degrees. The leaf type at every cell of the matrix. Bridges to/from the radian `RaDecRoll` math form via the inverse pair `Pointing.as_radecroll()` (degrees → radians) and `Pointing.from_radecroll()` (radians → degrees). Both live on `Pointing` so the dependency only runs `positioning` → `coordinates`.
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
Radian-based, quaternion-aware coordinate dataclass in `PiFinder/types/coordinates.py`. Used by `ImuDeadReckoning`. `Pointing.as_radecroll()` bridges degrees → radians; `Pointing.from_radecroll()` bridges back radians → degrees. The radian form is confined to the dead-reckoning math; the published data model stays in degrees (`Pointing`).
_Avoid_: coords, position tuple, using `RaDecRoll` in the published model (the degrees/radians split at the math boundary is deliberate).

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

**`SolveResult`**:
The message the solver puts on `solver_queue` describing one plate-solve attempt. A union — `SolveResult = SuccessfulSolve | FailedSolve` — on which the integrator dispatches via `isinstance()` (mirroring `SolverCommand` / `AlignResponse`). It is a transport DTO, **not** the published record: only the integrator builds the canonical `PointingEstimate`, by applying a `SolveResult` onto its long-lived instance. Defined in `PiFinder/types/positioning.py`. See [`docs/adr/0012-solver-integrator-message.md`](../../adr/0012-solver-integrator-message.md).
_Avoid_: snapshot, solved dict, solution record.

**`SuccessfulSolve`**:
The `SolveResult` variant carrying solve-truth: **flat** `camera` and `aligned` `Pointing`s (no `solve`/`estimate` split — the solver never IMU-progresses), the IMU anchor (`Optional` — a solve can succeed on a frame with no IMU sample), `last_solve_attempt` / `last_solve_success` (the solved frame's `exposure_end`), `SolveDiagnostics`, `AlignmentResult`, and the matched-star arrays. The integrator fans `camera`/`aligned` into both the `solve` and `estimate` cells, reseeds the dead-reckoner, and promotes `last_solve_success` to `estimate_time` (there is no separate `solve_time` on the message).
_Avoid_: solved estimate, PointingEstimate (a `SuccessfulSolve` is not one).

**`FailedSolve`**:
The `SolveResult` variant for an attempt that produced no pointing: `SolveDiagnostics` (with `Matches=0`) plus `last_solve_attempt` / `last_solve_success`. Triggers the integrator to preserve its `solve` cells + anchor **and** its `estimate` cells, and set `solve_source=CAMERA_FAILED`. The estimate cells are **not** cleared: once anchored, the last (IMU-progressed) pointing stays published and `solve_state` stays true, while the IMU advance keeps progressing it. A failed solve only shows "no solve" before the first successful solve. See [ADR 0014](../../adr/0014-failed-solve-preserves-estimate.md).
_Avoid_: empty PointingEstimate, hollow estimate, clearing the estimate on failure (that caused the "reverts to no-solve while stationary" bug).

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

### Timing

**`estimate_time`**:
The measurement **epoch** of the data behind the *current* `estimate` — i.e. *when the reading this value is based on was captured*, not when the integrator computed or published it. For a camera estimate it is the frame's `exposure_end`; for an IMU-progressed estimate it is the IMU sample's `timestamp`. Both sit on the same `time.time()` wall clock, so `time.time() - estimate_time` is a true "age of the fix" regardless of source. Updated on **every** estimate — each plate-solve and each IMU advance. Right after a solve `estimate_time == last_solve_success`; between solves the IMU advances `estimate_time` to each sample's epoch while `last_solve_success` stays anchored.
_Avoid_: solve_time (legacy name — "solve" is reserved for plate-solve; this value is an *estimate*, often IMU-derived), cam_solve_time (removed), publish time, integration time. Whether the current estimate is the raw plate-solve or IMU-progressed is told by `solve_source` (`is_camera_solve()`), **not** by comparing timestamps.

### Civil time (date & clock)

**Civil datetime** (the `shared_state.datetime()` family):
The calendar date + wall-clock time used as the **astronomical epoch** — the "when" that turns RA/Dec into Alt/Az and drives planet/comet ephemerides. Sourced from the GPS process (a real fix) or from manual time/date entry, carried on `shared_state`. **Always stored timezone-aware in UTC**, normalised at the `set_datetime()` boundary (naive input ⇒ interpreted as UTC; aware input ⇒ converted to UTC). Distinct from **measurement epoch** (`estimate_time`, `time.time()` — see above): civil datetime answers "what is the sky doing now", measurement epoch answers "how old is this fix". See [ADR-0018](../../adr/0018-civil-datetime-stored-utc-aware.md).
_Avoid_: "the datetime" (ambiguous — say civil datetime, or name the accessor), treating `datetime().time()` as UTC without going through `utc_datetime()`, passing a naive datetime to `set_datetime()` (every caller must pass tz-aware).

**`utc_datetime()`** / **`local_datetime()`**:
The two explicit civil-datetime accessors on `shared_state`. `utc_datetime()` returns the instant in UTC; `local_datetime()` returns it in the active location's timezone (UTC fallback if none/invalid). Both derive from the same stored UTC instant, so they are one moment in two zones — never two different times. Prefer them over bare `datetime()` so the intended zone is on the page.
_Avoid_: reading bare `datetime()` for display (it returns UTC after normalisation but states no intent), calling the `utc_datetime()` value "local time".

### Integration

**Integrator** (the process):
The process that fuses fresh plate-solves with IMU samples and publishes the result. Single owner of the `solve`-state values (`pointing.camera.solve`, `pointing.aligned.solve`) and the `ImuDeadReckoning` instance.
_Avoid_: fuser, merger.

**Anchor**:
The IMU dead-reckoning reference: the pair of `pointing.camera.solve` (camera-axis truth from the latest plate-solve) and `imu_anchor` (the IMU quaternion sampled on the same frame). Owned by the integrator. Updated only on successful plate-solves; preserved across failed solves so dead-reckoning continues.
_Avoid_: last_image_solve (legacy name), last_solve (this is the *state* name on a `PointingAxis`, not a field), last_solution.

**Dead reckoning** (`ImuDeadReckoning`):
A **single** instance handles both axes. `solve(camera, aligned, q_x2imu)` captures, at each successful plate-solve, both the drifting reference frame `q_eq2x` (from the camera pointing + IMU sample) and the static `q_cam2aligned` rotation (from the camera↔aligned pair). `predict(q_x2imu)` then dead-reckons the camera pointing forward from the latest IMU sample and composes it with `q_cam2aligned`, returning **both** `(camera, aligned)` as `RaDecRoll`. A math primitive — `RaDecRoll` in, `RaDecRoll` out; it never imports `PointingEstimate`. Lives in `PiFinder/pointing_model/imu_dead_reckoning.py`.
_Avoid_: IMU tracking, prediction, two IDR instances (the old `idr_camera` / `idr_aligned` split was collapsed into one dual-axis instance).

**`q_cam2aligned`**:
The static rotation from the camera optical axis to the aligned (eyepiece) axis, captured by `ImuDeadReckoning.solve()` from the (camera, aligned) pair on each successful plate-solve and reapplied in `predict()`. Identity when no alignment offset is calibrated (target pixel at image centre). Replaced — not accumulated — on every solve.
_Avoid_: q_cam2scope (earlier working name), cam-to-scope offset.

**IMU**:
The BNO055 sensor that supplies orientation. Sampled by the IMU process; read by the integrator via `shared_state.imu()`.
_Avoid_: gyro, sensor.

**`ImuSample`**:
A single IMU orientation reading carried on `shared_state` (via `set_imu()` / `imu()`) and bundled into each camera frame's metadata. Holds the scalar-first `quat`, the BNO055 calibration `status`, a `moving` flag, and a `timestamp` (the sample epoch — see below). Defined in `PiFinder/types/positioning.py`; `is_calibrated()` is true at `status == 3`.
_Avoid_: imu dict (the legacy `{"quat", "status", "moving", ...}` form it replaces), the unused `move_start` / `move_end` keys (dropped).

**`timestamp`** (on `ImuSample`):
The wall-clock (`time.time()`) instant at which the IMU process sampled this orientation. The IMU-side input to `estimate_time` when the integrator dead-reckons from this sample. Distinct from the moment the integrator *reads* the sample (which lags it by the IMU → `shared_state` → integrator latency).
_Avoid_: read time, integration time.

**IMU quaternion** (`imu_quat`, `q_x2imu`):
Unit quaternion (scalar-first) describing the IMU's orientation in its world frame. The name `q_x2imu` reads as "transform from frame `x` to IMU frame."
_Avoid_: orientation, quaternion (qualify it).

**`IMU_MOVED_ANG_THRESHOLD`**:
Deadband (0.06° ≈ 1.05 mrad) below which IMU motion is treated as noise and no dead-reckoning update is published.
_Avoid_: jitter threshold, IMU noise.

**Screen direction** (`screen_direction`):
Configuration field that tells `ImuDeadReckoning` how the display/IMU is physically mounted relative to the optical axis. Used to bake in axis conventions on initialisation. Surfaced to users as the **PiFinder Type** setting (Settings → Advanced); the user docs call the physical build variants *configurations* (Left/Right/Straight/Flat). The setting's value list is wider than any one product generation — it includes legacy variants (Flat v2, AS Bloom) — so user docs must scope claims like "there are N configurations" to a generation (DIY v2.5 builds: Left/Right/Flat; assembled v3 units: Left/Right/Straight/Flat).
_Avoid_: orientation, mount direction.

### Alignment

**Camera-to-telescope alignment**:
The process of learning which camera pixel coincides with the centre of the eyepiece view. Outcome: an updated **target pixel**. From then on, every solve reports RA/Dec at that pixel as `pointing.aligned`. There are **two paths** to that outcome — *solve-based alignment* and *daytime (manual) alignment* — which differ only in how the target pixel is discovered; both write the same `Config["target_pixel"]` / `shared_state.set_target_pixel()`.
_Avoid_: telescope alignment, eyepiece alignment, scope alignment.

**Solve-based alignment**:
The default alignment path (`ui/align.py` `UIAlign` + `align_on_radec`): the user picks a star on the starfield chart, the solver plate-solves the live frame against that star's RA/Dec, and tetra3 reports the pixel where it landed (`AlignedResult` → target pixel). Requires a successful plate-solve, so it is a night-sky path.
_Avoid_: star alignment, chart alignment (describe it as solve-based).

**Daytime alignment** (manual alignment):
The manual alignment path (`ui/align_daytime.py` `UIAlignDaytime`): with the scope pointed at a distant **daytime** object centred in the eyepiece, the user looks at the live camera image and marks, by eye, the pixel showing that same object. That pixel **is** the target pixel — no plate-solve, no `align_command_queue` round-trip; the module writes `target_pixel` directly. The use case is daylight (no stars to solve); the mechanic is a manual pixel pick.
_Avoid_: daytime mode (it is an alignment, not a camera mode), visual alignment, manual solve (there is no solve).

**Alignment target** (`align_ra` / `align_dec`):
Local state in the solver process holding the user's chosen sky coordinate while an alignment request is pending. Cleared once the result is posted.
_Avoid_: aim target.

**`AlignOnRaDec`** / **`AlignCancel`**:
Dataclass commands on `align_command_queue`. `AlignOnRaDec(ra, dec)` arms alignment; `AlignCancel()` clears it (timeout/user cancel). The solver dispatches on `isinstance()`. `ReloadSqmCalibration` rides the same queue.
_Avoid_: `align_on_radec` / `align_cancel` (legacy tagged-list string tags — `align_on_radec` is now only the `ui/align.py` orchestrator function), align command, request alignment.

**`AlignedResult`**:
Dataclass response on `align_result_queue` carrying `(y_target, x_target)` — the pixel where the alignment target landed in the current frame. `as_target_pixel()` returns the canonical `(Y, X)`.
_Avoid_: `["aligned", (y, x)]` (legacy tagged-list form), align result, pixel result.

### Queues & shared state

**`shared_state`** (`SharedStateObj`):
Multiprocessing-manager proxy carrying configuration, IMU samples, GPS fixes, the latest image, the published `PointingEstimate` (via `set_solution()` / `solution()`), and the SQM/noise-floor state. Read by every process.
_Avoid_: state, global state.

**`solver_queue`**:
One-way `multiprocessing.Queue`, solver → integrator. Carries a `SolveResult` (a `SuccessfulSolve` or `FailedSolve`) on every attempt, success or failure.
_Avoid_: solve queue, pointing queue.

**`align_command_queue` / `align_result_queue`**:
Pair of queues running alignment commands into the solver and pixel results back to the UI.
_Avoid_: align queue (singular — there are two).

### Boundary terms

- **SQM** is computed inside the solver process but is a separate context — see [SQM](../sqm/CONTEXT.md).
- **`shared_state.solution()`** is consumed by Catalog to compute visibility — see [Catalog](../catalog/CONTEXT.md).
- **GPS / time** are owned by the GPS process; Positioning is a consumer. The civil datetime they publish on `shared_state` is timezone-aware UTC — see *Civil time* above and [ADR-0018](../../adr/0018-civil-datetime-stored-utc-aware.md).

## Flagged ambiguities

- **"Pointing"** (unqualified, lower-case in prose) — means `pointing.aligned.estimate`. The eyepiece direction as currently estimated. Always qualify when you mean any of the other three cells in the 2 × 2 matrix.
- **"`pointing`"** (the dataclass field) vs **"pointing"** (the prose word) — disambiguated by capitalisation / code-style. `PointingEstimate.pointing` is the top-level container holding the four cells; bare "pointing" in prose means `pointing.aligned.estimate`.
- **"Solver"** — the PiFinder *process*. The plate-solving *library* is "tetra3". Don't conflate.
- **"Target pixel"** vs the **`aligned`** axis — the *pixel* is `(Y, X)` in image space, produced by alignment; the *axis* is the RA/Dec direction at that pixel. Don't say "target pixel" when you mean the direction; don't say "aligned" when you mean the pixel.
- **"Solution"** — be specific: `shared_state.solution()` returns the latest published `PointingEstimate`. The latest plate-solve values are the `solve` state inside; the current values consumers see are the `estimate` state.
- **Legacy `solved` dict** — historical name for the pre-dataclass position record. Code now uses `PointingEstimate`; the term may appear in old commits and PR descriptions but should not appear in current code or prose.
- **"Solve" means plate-solve — always** — a "solve" is a camera plate-solve event or its resulting value (the `solve` state, `last_solve_attempt`, `last_solve_success`). It is **never** an IMU-derived value. The current value (which the IMU may have progressed) is the **estimate**, and its epoch is **`estimate_time`**, never "solve_time".
- **Removed legacy timing names** — `solve_time` was renamed to `estimate_time` (it is an estimate, not a solve, and is often IMU-derived). `cam_solve_time` was removed: under epoch semantics it was value-identical to `last_solve_success`, and the "is the live value still the raw camera solve?" question is answered by `solve_source` / `is_camera_solve()` rather than a `solve_time == cam_solve_time` timestamp comparison.
- **"Time"** — disambiguate **civil datetime** (the UTC calendar/clock epoch from GPS or manual entry, read via `utc_datetime()` / `local_datetime()`; the astronomical "now") from **measurement epoch** (`time.time()` instants like `estimate_time`; the "age of a fix" clock). Different clocks — never compare or assign across them. See [ADR-0018](../../adr/0018-civil-datetime-stored-utc-aware.md).
- **"GPS LST"** — removed: it read as Local Sidereal Time but meant *last GPS lock time*. The status field is now **GPS LKT** (lock-time). "LST", if it ever reappears, is Local Sidereal Time only.

## Example dialogue

> **Dev:** During alignment, why does the published RA/Dec not jump?
>
> **Domain:** Alignment only changes the **target pixel** (the `(Y, X)` coordinate). It doesn't touch `pointing.camera` in either state, so the IMU model — anchored on `pointing.camera.solve` plus `last_solve_imu` — is untouched. The next plate-solve computes a fresh `pointing.aligned.solve` at the new target pixel; the integrator then promotes it to `pointing.aligned.estimate` for downstream consumers.
>
> **Dev:** What if the solve fails right after alignment?
>
> **Domain:** The solver pushes a `FailedSolve`. The integrator preserves its `solve`-state cells (`pointing.camera.solve`, `pointing.aligned.solve`), the IMU anchor, **and** the `estimate` cells, and sets `solve_source=CAMERA_FAILED` on the published `PointingEstimate`. The last pointing stays published (so `solve_state` stays true) and the IMU advance keeps progressing it from dead-reckoning. Crucially the estimate is **not** cleared on failure: clearing it dropped to "no solve" whenever a solve failed while the IMU was in its deadband — see [ADR 0014](../../adr/0014-failed-solve-preserves-estimate.md). Auto-exposure still sees `diagnostics.Matches=0`, which is why the solver pushes on every attempt — success or failure.
