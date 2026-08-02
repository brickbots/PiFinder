# Positioning in PiFinder

This document describes how PiFinder acquires, integrates, and distributes
position data (where the telescope is currently pointed). It focuses on the
two processes that produce the canonical "where am I pointing?" answer:

- `PiFinder/solver.py` — runs plate-solving on camera frames.
- `PiFinder/integrator.py` — fuses plate-solves with IMU dead-reckoning
  and publishes the result to the rest of the system.

For the canonical glossary of terms and data structures, see
[`positioning/CONTEXT.md`](./positioning/CONTEXT.md). The dataclass model
is defined in `PiFinder/types/positioning.py`; the vocabulary decision is
recorded in [`docs/adr/0001-positioning-vocabulary.md`](../adr/0001-positioning-vocabulary.md).

---

## 1. Process layout

The two positioning processes are spawned from `main.py` alongside the
camera, IMU, GPS, web, and UI processes. They communicate through:

- `shared_state` — a `SharedStateObj` proxy backed by a multiprocessing
  manager. Used for camera frames, IMU samples, GPS/time, configuration,
  and the published pointing solution.
- `solver_queue` — a one-way `multiprocessing.Queue` from solver to
  integrator carrying a `SolveResult` on every attempt.
- `align_command_queue` / `align_result_queue` — used by the alignment
  flow to request a plate-solve targeted at a particular RA/Dec and
  return the resulting pixel coordinates.
- `camera_image` — a shared PIL image of the latest captured frame.

```
   Camera ──► camera_image ──┐
                             │
                       ┌───► Solver ──► solver_queue ──► Integrator ──► shared_state.set_solution()
                       │                                       ▲
   IMU ──► shared_state.imu() ─────────────────────────────────┘

   shared_state.solution() is read by: UI, web server, position server (SkySafari), catalogs.
```

---

## 2. The `PointingEstimate` record

The canonical pointing record published via `shared_state.set_solution()`
is a **`PointingEstimate`** dataclass (`PiFinder/types/positioning.py`),
not a dict. It is built and owned by the integrator. The solver→integrator
message is a separate **`SolveResult`** (§3); both replaced the legacy
`solved` dict — see
[`docs/adr/0012-solver-integrator-message.md`](../adr/0012-solver-integrator-message.md).

At its heart is a **2 × 2 matrix** of pointings — two **axes** crossed with
two **states** — reached as `pointing.<axis>.<state>.<RA|Dec|Roll>`:

|                  | `solve` — plate-solve truth | `estimate` — current (may be IMU-progressed) |
|------------------|------------------------------|------------------------------------------------|
| **`camera`** — optical axis        | `pointing.camera.solve`  | `pointing.camera.estimate`  |
| **`aligned`** — eyepiece direction | `pointing.aligned.solve` | `pointing.aligned.estimate` |

Each cell is an `Optional[Pointing]` (RA/Dec/Roll in **degrees**, `None`
until the first successful solve). The other fields:

| Field | Meaning |
| --- | --- |
| `imu_anchor` | The IMU quaternion sampled at the moment the camera exposure ended. Paired with `pointing.camera.solve` as the dead-reckoning anchor. |
| `Alt`, `Az` | Topocentric altitude/azimuth, computed by the integrator from `pointing.aligned.estimate`, GPS location, and current time. |
| `solve_source` | A `SolveSource` enum: `CAMERA` (`"CAM"`), `CAMERA_FAILED` (`"CAM_FAILED"`), or `IMU`. Inherits `str`, so equality against the legacy string literals still works. |
| `solve_time` | Wall-clock time the current solution was produced (`time.time()`). |
| `cam_solve_time` | Wall-clock time of the most recent **camera** solve. |
| `last_solve_attempt` | The `exposure_end` of the most recently processed image. Used to skip frames the solver has already seen. |
| `last_solve_success` | The `exposure_end` of the most recent **successful** plate-solve. |
| `constellation` | Three-letter constellation containing `pointing.aligned.estimate`, filled by the integrator. |
| `diagnostics` | A `SolveDiagnostics` record: `Matches`, `RMSE`, `Prob`, `FOV`, `T_solve`, `T_extract`. Used by auto-exposure even when the solve fails. |
| `alignment` | An `AlignmentResult` (`x_target` / `y_target`): the pixel an active alignment request landed on. Cleared once consumed. |
| `matched_centroids`, `matched_stars` | Raw tetra3 matched-star outputs, carried so the SQM calibration UI can replay SQM calculations on cached frames. `None` on failures. |

**Two processes, two ownership rules.** The solver holds *no* long-lived
state: it builds a `SolveResult` per attempt and pushes it. The
integrator owns *the* long-lived `PointingEstimate` — the `solve`
cells on it are the dead-reckoning anchor, advanced only on a successful
solve and preserved across failures.

---

## 3. Acquisition: `solver.py`

The solver process owns one tight loop:

1. **Drain `align_command_queue`.** Three dataclass commands are handled
   by `isinstance()` dispatch:
   - `AlignOnRaDec(ra, dec)` — store an `align_ra`/`align_dec` target;
     subsequent plate-solves pass `target_sky_coord` to tetra3 so we can
     read back the pixel where that sky coordinate lands.
   - `AlignCancel()` — clear the alignment target.
   - `ReloadSqmCalibration()` — rebuild the `SQMCalculator` (camera
     calibration may have changed).
2. **Rate-limit the loop** with `state_utils.sleep_for_framerate`.
3. **Fetch the latest frame metadata** from `shared_state.last_image_metadata()`.
   If `exposure_end` is not newer than `last_solve_attempt`, the image is
   stale and the loop continues.
4. **Extract centroids.** The solver prefers `PFCedarDetectClient` (a
   subclass of `cedar_detect_client.CedarDetectClient` that talks to the
   `cedar-detect-server` over gRPC on port 50551, using POSIX shared
   memory when possible). On any gRPC failure it raises
   `CedarConnectionError` and falls back to
   `tetra3.get_centroids_from_image`.
5. **Solve with tetra3.** `t3.solve_from_centroids(...)` is called with:
   - the image dims `(512, 512)`,
   - `fov_estimate=12.0`, `fov_max_error=4.0`,
   - `target_pixel=shared_state.target_pixel()` so tetra3 also reports the
     RA/Dec at the user's chosen pixel (as `RA_target`/`Dec_target`),
   - optional `target_sky_coord` when alignment is active.
6. **On success**, `_build_successful_solve()` folds the tetra3 `solution`
   dict into a `SuccessfulSolve` message carrying flat per-axis
   solve-truth:
   - `camera` ← `solution["RA"/"Dec"/"Roll"]` (the camera optical centre).
   - `aligned` ← `solution["RA_target"/"Dec_target"]`, falling back to the
     camera RA/Dec when no target offset is present.
   - `imu_anchor` ← `last_image_metadata["imu"]["quat"]` when available.
   - `solve_time` ← `time.time()`; `last_solve_success` ← the frame's
     `exposure_end`; `diagnostics` ← tetra3 metrics.
   The message carries no `solve`/`estimate` split — the integrator fans
   `camera`/`aligned` into both cells of each axis and advances only the
   `estimate` cells later.
7. **SQM update.** When the solve produced `matched_centroids`,
   `update_sqm()` runs `SQMCalculator.calculate` on the same frame and
   stores the result (plus the noise-floor) into `shared_state`. SQM is
   gated to once every `SQM_CALCULATION_INTERVAL_SECONDS` (5 s). See
   [SQM](./sqm/CONTEXT.md).
8. **Handle alignment hits.** If a `target_sky_coord` was active and the
   estimate's `alignment.is_set()`, the pixel is pushed back on
   `align_result_queue` as an `AlignedResult(y_target, x_target)`, the
   alignment target is cleared, and `alignment` is reset on the estimate
   before it is published.
9. **Failures** build a `_build_failed_solve()` — a `FailedSolve` carrying
   `diagnostics.Matches=0` and timing only, no pointing — and **still
   push** it to `solver_queue`. This is required so the integrator (and
   downstream auto-exposure) can react to repeated failed solves.

The solver only knows about the camera. It never reads or updates the
IMU directly — it only forwards the `imu_anchor` quaternion that the
camera process already stamped onto the frame.

---

## 4. Integration: `integrator.py`

The integrator's job is to produce a continuous pointing estimate even
when plate-solves are sparse or fail. It runs another tight loop.

### 4.1 State held across iterations

- `estimate` — the **long-lived** `PointingEstimate`. Its `solve` cells
  plus `imu_anchor` are the dead-reckoning anchor; its `estimate` cells
  are what consumers read. Empty until the first successful solve.
- `idr` — a **single** `ImuDeadReckoning(screen_direction)` instance,
  handling both axes (see §4.4). Seeded from the (camera, aligned) pair
  at each successful solve.
- `last_solve_time` — the `solve_time` of the most recent push to shared
  state, used to suppress duplicate publishes.

### 4.2 Per-iteration flow

1. **Try to read one `SolveResult`** from `solver_queue` (non-blocking).
2. **If a `SuccessfulSolve` arrived** (`_apply_successful_solve`), dispatched
   by `isinstance`:
   - Fan the flat `camera`/`aligned` pointings into both the `solve` and
     `estimate` cells of each axis, and refresh `imu_anchor`, timing
     (`solve_time` and `cam_solve_time` both from the message's single
     `solve_time`), diagnostics, alignment, and the `matched_*` fields.
   - Reseed the dead-reckoner:
     `idr.solve(camera.as_radecroll(), aligned.as_radecroll(), imu_anchor)`.
   - Mark `solve_source = CAMERA` and set `pointing_updated = True`. (The
     publish in step 5 sets `solve_state` via `set_solution`.)
3. **If a `FailedSolve` arrived** (`_apply_failed_solve`):
   - **Preserve** the `solve` cells and `imu_anchor` (the anchor must
     survive so dead-reckoning continues), refresh `diagnostics` / timing /
     `solve_source = CAMERA_FAILED`, blank `constellation`, and **clear**
     the `estimate` cells.
   - Publish immediately with `set_solution(...)`; because the `estimate`
     cells were cleared, this derives `solve_state = False`, and
     auto-exposure sees `diagnostics.Matches=0`.
4. **If no camera solve was applied and `idr.is_initialized()` and we have
   an anchor** (`_advance_with_imu`):
   - Read `shared_state.imu()`.
   - If the angular delta from `imu_anchor` is below
     `IMU_MOVED_ANG_THRESHOLD` (0.06°), do nothing — we have not actually
     moved.
   - Otherwise call `idr.predict(q_x2imu)`, which returns both
     `(camera, aligned)` `RaDecRoll`s. Write them into
     `pointing.camera.estimate` and `pointing.aligned.estimate`, set
     `solve_time = time.time()` and `solve_source = IMU`.
5. **Annotate and publish.** When pointing was updated, `solve_time`
   advanced past `last_solve_time`, and `pointing.aligned.estimate` is
   populated:
   - Fill `constellation` from `pointing.aligned.estimate`.
   - Compute `Alt`, `Az` from `pointing.aligned.estimate` + GPS location +
     current datetime.
   - Call `shared_state.set_solution(deepcopy(estimate))`, which derives
     `solve_state = True` from the populated `aligned.estimate`.

### 4.3 Why the integrator preserves its own `solve` cells

The published `estimate` cells drift between camera solves (IMU
dead-reckoning). If the integrator re-derived its anchor from
`shared_state.solution()`, that drift would fold into successive solves'
metadata. It avoids this two ways: the **solver** builds each `SolveResult`
from the raw tetra3 result (no drift), and the **integrator** treats the
`solve` cells on its long-lived `PointingEstimate` as the single source
of anchor truth — replaced wholesale on a successful solve, preserved
untouched across failures.

### 4.4 The dual-axis dead-reckoner

A single `ImuDeadReckoning` instance handles both axes (it replaced an
earlier two-instance `idr_camera` / `idr_aligned` split). It stays a math
primitive: `RaDecRoll` in, `RaDecRoll` out; it never imports
`PointingEstimate`. The integrator does the `RaDecRoll ↔ Pointing`
bridging.

- `solve(camera, aligned, q_x2imu)` captures two things at each successful
  plate-solve:
  - `q_eq2x` — the drifting reference frame, from the camera pointing and
    the IMU sample (`q_eq2cam · (q_x2imu · q_imu2cam)⁻¹`).
  - `q_cam2aligned` — the **static** rotation from the camera axis to the
    aligned (eyepiece) axis (`q_eq2cam⁻¹ · q_eq2aligned`). When no
    alignment offset is calibrated (target pixel at image centre),
    `aligned == camera`, so this is the identity. It is replaced — not
    accumulated — on every solve.
- `predict(q_x2imu)` dead-reckons the camera pointing forward
  (`q_eq2x · q_x2imu · q_imu2cam`) and composes it with `q_cam2aligned`
  to get the aligned pointing, returning **both** as a tuple. Returns
  `None` until `solve()` has produced a valid `q_eq2x`.

All angles inside the IDR are radians; degrees↔radians conversion lives at
`Pointing.as_radecroll()` and `RaDecRoll.get(deg=True)`.

`q_imu2cam` is a per-build-variant hardware constant, selected by **screen
direction** at construction. It is only valid paired with that variant's
`SCREEN_ROTATE_AMOUNTS` entry in `camera_interface.py`: the camera frame is
defined on the image *after* that software rotation, so the two constants
must be derived together. Derive or verify entries with the visual **imu2cam
tool** (`PiFinder/pointing_model/docs/imu2cam_tool.html`);
`tests/test_imu2cam_tool_presets.py` pins the tool's presets to both
production tables. The IMU chip placement on the UI board is per **board
revision** (rev4 boards mount it on the back side, flipped about the
board's long axis), so set the tool's board-revision control to match the
physical board — see the tool's header comment and the CONTEXT.md **Board
revision** entry.

---

## 5. Camera-to-telescope alignment

The plate-solver knows where the **camera** is pointing. What the user
cares about is where the **eyepiece** is pointing. Those two
sight-lines are not the same — the finder camera is offset from the
optical axis of the main scope. The job of the alignment subsystem is
to learn one number: which pixel in the 512×512 camera image
corresponds to the center of the eyepiece view. That pixel is called
the **target pixel**, stored in `shared_state` and persisted in `Config`
under `"target_pixel"`. Default `(256, 256)` (image center) means
"no offset known yet."

### 5.1 How the target pixel is used during normal operation

`target_pixel` is read **on every solve**, not just during alignment:

```python
solution = t3.solve_from_centroids(
    ...,
    target_pixel=shared_state.target_pixel(),
    ...,
)
```

tetra3, given `target_pixel`, returns both the RA/Dec at the camera
center **and** the RA/Dec at that pixel as `RA_target`/`Dec_target`.
`_build_successful_solve()` then:

1. Sets `camera` from the camera-center RA/Dec (preserved for IMU
   dead-reckoning — the IMU calibration is anchored to the camera's
   optical axis, not the eyepiece).
2. Sets `aligned` from `RA_target`/`Dec_target`.

The integrator later fans each into the `solve` and `estimate` cells;
that second assignment is what makes `pointing.aligned` reflect the
eyepiece direction. Every downstream consumer (UI, web, SkySafari) reads
`pointing.aligned.estimate`, never the camera pointing.

### 5.2 The alignment flow (round trip)

1. **User picks a known target** in the catalog UI (e.g. a bright
   star), centers it in the eyepiece, and triggers "align on this."
2. **`ui/align.py::align_on_radec(...)`** is the orchestrator. It:
   - Drains any stale messages from the `align_response` queue.
   - Posts `AlignOnRaDec(ra, dec)` on the `align_command` queue.
   - Polls for an `AlignedResult` for up to 2 s. On timeout it posts
     `AlignCancel()` and reports "Align Timeout."
3. **`solver.py`** picks up the command at the top of its loop, stores
   `align_ra` / `align_dec`, and on the next plate-solve passes
   `target_sky_coord=[[align_ra, align_dec]]` to tetra3. tetra3 then
   reports `x_target` / `y_target` — the pixel where that sky coordinate
   lands in the current frame.
4. **Solver pushes the result back** on `align_result_queue` as an
   `AlignedResult(y_target, x_target)` and clears `align_ra`/`align_dec`
   so subsequent solves go back to normal.
5. **`align_on_radec`** receives the result and commits it:
   ```python
   target_pixel = response.as_target_pixel()   # (Y, X)
   shared_state.set_target_pixel(target_pixel)
   config_object.set_option("target_pixel", target_pixel)
   ```
   `shared_state` makes it effective immediately; `Config` makes it
   survive a restart.

### 5.3 Coordinate conventions and reset

- `target_pixel` is stored as `(Y, X)` in camera-image space (512×512).
- `shared_state.target_pixel(screen_space=True)` returns `(X, Y)`
  rescaled to display space (128×128 = camera/4) for UI overlays.
  (No UI currently consumes this form — the Focus-screen reticle that
  did was removed; the accessor remains for future overlays.)
- Resetting alignment in the UI calls
  `shared_state.set_target_pixel((256, 256))` and writes the same value
  to `Config` — i.e. recenter the eyepiece pixel on the image center.

### 5.4 Why alignment doesn't disturb IMU tracking

The IMU is rigidly attached to the camera, not the eyepiece. The
reference frame the dead-reckoner learns (`q_eq2x`) is therefore anchored
on `pointing.camera.solve`, which is why `_apply_successful_solve()`
passes the **camera** pointing into `idr.solve(...)`. Changing the target
pixel shifts `pointing.aligned.*` but leaves `pointing.camera.*` (and the
`imu_anchor`) untouched, so `q_eq2x` is unaffected. The alignment offset
lives separately in `q_cam2aligned`, re-derived from the (camera, aligned)
pair on every solve.

---

## 6. Distribution

Once `shared_state.set_solution(estimate)` is called, downstream consumers
read the record by polling `shared_state.solution()` (which returns a
`PointingEstimate`):

- **UI** (`PiFinder/ui/*`) — chart, telrad, catalog pages.
- **Web server** (`PiFinder/server.py`) — `/api/current-selection`,
  status table, SkySafari proxy pages.
- **Position server** (`PiFinder/pos_server.py`) — serves the LX200-style
  telescope protocol to SkySafari and other planetarium apps.
- **Catalogs** — use `pointing.aligned.estimate` (and `Alt`/`Az` when
  available) to compute visibility and "near me" lists.

`shared_state.solve_state()` is a cheap-to-poll cache of
`solution().has_pointing()` — the bool tells consumers whether a current
pointing exists (used by the UI to show the "no solve" indicator) without
round-tripping the whole `PointingEstimate` across the manager proxy every
frame. It is written **only** by `set_solution`, which derives it from
`has_pointing()`, so the two can never drift.

---

## 7. Timing and freshness rules

A few subtle rules worth knowing when modifying either file:

- The solver uses `exposure_end` (from camera metadata) — not wall
  clock — to decide whether a frame is new. This means re-injected frames
  with old timestamps are correctly skipped.
- The integrator deduplicates pushes by comparing `solve_time` to its
  local `last_solve_time`. IMU updates therefore must advance
  `solve_time` to be published.
- `IMU_MOVED_ANG_THRESHOLD` (0.06°) is the deadband below which IMU
  motion is ignored. Setting it too low publishes noise; too high adds
  visible lag when slewing.
- On **every** solve attempt, success or failure, the solver pushes a
  `PointingEstimate` onto `solver_queue`. Auto-exposure depends on
  `diagnostics.Matches` being updated whether or not the plate-solve
  succeeded.

---

## 8. Glossary

The canonical glossary lives at [`positioning/CONTEXT.md`](./positioning/CONTEXT.md).
Use those terms when reading, writing, and discussing code in this area.

Note in particular: the dataclass model in `PiFinder/types/positioning.py`
is canonical. The access shape is `pointing.<axis>.<state>.<RA|Dec|Roll>`,
and bare "pointing" in prose means `pointing.aligned.estimate`. The legacy
`solved` dict it replaced may still appear in old commits and PR
descriptions — see also
[`docs/adr/0001-positioning-vocabulary.md`](../adr/0001-positioning-vocabulary.md).
