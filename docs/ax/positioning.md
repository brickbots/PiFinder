# Positioning in PiFinder

This document describes how PiFinder acquires, integrates, and distributes
position data (where the telescope is currently pointed). It focuses on the
two processes that produce the canonical "where am I pointing?" answer:

- `PiFinder/solver.py` — runs plate-solving on camera frames.
- `PiFinder/integrator.py` — fuses plate-solves with IMU dead-reckoning
  and publishes the result to the rest of the system.

For the canonical glossary of terms and data structures, see
[`positioning/CONTEXT.md`](./positioning/CONTEXT.md).

---

## 1. Process layout

The two positioning processes are spawned from `main.py` alongside the
camera, IMU, GPS, web, and UI processes. They communicate through:

- `shared_state` — a `SharedStateObj` proxy backed by a multiprocessing
  manager. Used for camera frames, IMU samples, GPS/time, configuration,
  and the published pointing solution.
- `solver_queue` — a one-way `multiprocessing.Queue` from solver to
  integrator carrying the most recent `solved` dictionary.
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

## 2. The `solved` dictionary

Both processes operate on a `solved` dict initialized by
`solver.get_initialized_solved_dict()`. This dict is the unit of
information that travels through `solver_queue` and is eventually stored
via `shared_state.set_solution()`. Its key fields are:

| Field | Meaning |
| --- | --- |
| `RA`, `Dec`, `Roll` | Current pointing in degrees. After a successful plate-solve these are the coordinates **at the target pixel** (not the camera center). The integrator may overwrite these with IMU dead-reckoned values. |
| `camera_solve.RA/Dec/Roll` | Pointing at the **camera center** from the most recent plate-solve. Never updated by the IMU. Used as the anchor for dead-reckoning. |
| `imu_quat` | The IMU quaternion sampled at the moment the camera exposure ended. Used as the IMU reference at the time of the last plate-solve. |
| `Alt`, `Az` | Topocentric altitude/azimuth, computed by the integrator from RA/Dec, GPS location, and current time. |
| `solve_source` | `"CAM"`, `"CAM_FAILED"`, or `"IMU"` — what produced the current RA/Dec. |
| `solve_time` | Wall-clock time the current solution was produced. |
| `cam_solve_time` | Wall-clock time of the most recent **camera** solve. |
| `last_solve_attempt` | The `exposure_end` of the most recently processed image. Used to skip frames the solver has already seen. |
| `last_solve_success` | The `exposure_end` of the most recent **successful** plate-solve. |
| `Matches`, `RMSE` | Diagnostics from tetra3: matched star count and residual. Used by auto-exposure even when the solve fails. |
| `constellation` | Three-letter constellation containing RA/Dec, filled by the integrator. |

The same dict shape is shared between the two processes, which makes the
integrator's job mostly merging and annotating, not transforming.

---

## 3. Acquisition: `solver.py`

The solver process owns one tight loop:

1. **Drain `align_command_queue`.** Three commands are handled:
   - `align_on_radec` — store an `align_ra`/`align_dec` target; subsequent
     plate-solves will pass `target_sky_coord` to tetra3 so we can read
     back the pixel where that sky coordinate lands.
   - `align_cancel` — clear the alignment target.
   - `reload_sqm_calibration` — rebuild the `SQMCalculator` (camera
     calibration may have changed).
2. **Rate-limit the loop** with `state_utils.sleep_for_framerate`.
3. **Fetch the latest frame metadata** from `shared_state.last_image_metadata()`.
   If `exposure_end` is older than `solved["last_solve_attempt"]`, the
   image is stale and the loop continues.
4. **Extract centroids.** The solver prefers `PFCedarDetectClient` (a
   subclass of `cedar_detect_client.CedarDetectClient` that talks to the
   `cedar-detect-server` over gRPC on port 50551, using POSIX shared
   memory when possible). On any gRPC failure, raises `CedarConnectionError`
   and falls back to `tetra3.get_centroids_from_image`.
5. **Solve with tetra3.** `t3.solve_from_centroids(...)` is called with:
   - the image dims `(512, 512)`,
   - `fov_estimate=12.0`, `fov_max_error=4.0`,
   - `target_pixel=shared_state.solve_pixel()` so tetra3 also reports the
     RA/Dec at the user's chosen pixel,
   - optional `target_sky_coord` when alignment is active.
6. **On success**, copy the camera-center coordinates into
   `solved["camera_solve"]`, then **replace** `solved["RA"/"Dec"]` with
   the `RA_target`/`Dec_target` values that correspond to the target
   pixel. Attach the `imu_quat` from `last_image_metadata["imu"]["quat"]`
   if available. Set `solve_time`, `cam_solve_time`, `last_solve_success`.
7. **SQM update.** When the solve produced `matched_centroids`,
   `update_sqm()` runs `SQMCalculator.calculate` on the same frame and
   stores the result (plus the noise-floor) into `shared_state`. SQM is
   gated to once every `SQM_CALCULATION_INTERVAL_SECONDS` (5 s).
8. **Handle alignment hits.** If a target_sky_coord was active and tetra3
   returned `x_target`/`y_target`, the pixel coordinates are pushed back
   on `align_result_queue` as `["aligned", (y, x)]`.
9. **Failures** clear `RA`/`Dec`/`Matches` but **still push** the dict to
   `solver_queue`. This is required so the integrator (and downstream
   auto-exposure) can react to repeated failed solves.

The solver only knows about the camera. It never reads or updates the
IMU directly — it only forwards the `imu_quat` that the camera process
already stamped onto the frame.

---

## 4. Integration: `integrator.py`

The integrator's job is to produce a continuous pointing estimate even
when plate-solves are sparse or fail. It runs another tight loop.

### 4.1 State held across iterations

- `solved` — the current published-style dict.
- `last_image_solve` — a deep copy of the most recent **successful**
  plate-solve. Used as the anchor for IMU dead-reckoning and as the
  recovery state after failed solves.
- `imu_dead_reckoning` — an `ImuDeadReckoning` instance constructed with
  the configured `screen_direction`. This object holds the
  camera-to-IMU transform learned from the latest plate-solve.
- `last_solve_time` — the `solve_time` of the most recent push to shared
  state, used to suppress duplicates.

### 4.2 Per-iteration flow

1. **Try to read one solve** from `solver_queue` (non-blocking).
2. **If a camera solve arrived:**
   - Seed `solved` from `last_image_solve` (not from `shared_state`,
     which may contain accumulated IMU drift).
   - Copy `Matches`, `RMSE`, `last_solve_attempt`, `last_solve_success`
     unconditionally so auto-exposure sees them even on failure.
   - If `RA is not None`: merge the entire dict, mark
     `solve_source = "CAM"`, deep-copy into `last_image_solve`, call
     `update_plate_solve_and_imu()` to teach `ImuDeadReckoning` the new
     camera-to-IMU alignment, and set `pointing_updated = True`.
   - If the solve failed: mark `solve_source = "CAM_FAILED"`, blank the
     constellation, and push immediately so consumers see `Matches=0`.
3. **If no camera solve was applied and `ImuDeadReckoning.is_initialized()`:**
   read `shared_state.imu()` and call `update_imu()`. That function:
   - Compares the new IMU quaternion against `last_image_solve["imu_quat"]`.
   - If the angular delta is below `IMU_MOVED_ANG_THRESHOLD` (0.06°),
     does nothing (we have not actually moved).
   - Otherwise calls `imu_dead_reckoning.predict(q_x2imu)` to get a fresh
     `RaDecRoll`, writes it into `solved["RA"/"Dec"/"Roll"]`, sets
     `solve_time = time.time()` and `solve_source = "IMU"`.
4. **Annotate and publish.** When pointing was updated and `solve_time`
   advanced past `last_solve_time`:
   - Fill `constellation` from `calc_utils.sf_utils.radec_to_constellation`.
   - Compute `Alt`, `Az` from RA/Dec + GPS location + current datetime.
     (Marked TODO: not strictly needed in EQ mode.)
   - Call `shared_state.set_solution(solved)` and
     `shared_state.set_solve_state(True)`.

### 4.3 Why the integrator copies from `last_image_solve` instead of `shared_state`

`shared_state.solution()` is the IMU-tracked pointing, which drifts
between camera solves. If the integrator used it as the base for each
new camera solve, drift would be folded into successive plate-solves'
metadata. Using the deep-copied `last_image_solve` keeps each new solve
anchored to known-good camera data and resets the IMU dead-reckoning
chain.

---

## 5. Camera-to-telescope alignment

The plate-solver knows where the **camera** is pointing. What the user
cares about is where the **eyepiece** is pointing. Those two
sight-lines are not the same — the finder camera is offset from the
optical axis of the main scope. The job of the alignment subsystem is
to learn one number: which pixel in the 512×512 camera image
corresponds to the center of the eyepiece view. That pixel is called
the **solve pixel**, stored in `shared_state` as `solve_pixel` and
persisted in `Config` under `"solve_pixel"`. Default `(256, 256)`
(image center) means "no offset known yet."

### 5.1 How `solve_pixel` is used during normal operation

`solve_pixel` is read **on every solve**, not just during alignment:

```python
solution = t3.solve_from_centroids(
    ...,
    target_pixel=shared_state.solve_pixel(),
    ...,
)
```

tetra3, given `target_pixel`, returns both the RA/Dec at the camera
center **and** the RA/Dec at that pixel as `RA_target`/`Dec_target`.
The solver then:

1. Copies the camera-center RA/Dec into `solved["camera_solve"]`
   (preserved for IMU dead-reckoning — the IMU calibration is anchored
   to the camera's optical axis, not the eyepiece).
2. **Overwrites** `solved["RA"/"Dec"]` with `RA_target`/`Dec_target`.

That overwrite is what makes `solved["RA"/"Dec"]` reflect the eyepiece
direction. Every downstream consumer (UI, web, SkySafari) sees the
eyepiece pointing, never the camera pointing.

### 5.2 The alignment flow (round trip)

1. **User picks a known target** in the catalog UI (e.g. a bright
   star), and centers it in the eyepiece. They trigger "align on this."
2. **`ui/align.py::align_on_radec(...)`** is the orchestrator. It:
   - Drains any stale messages from `align_result_queue`.
   - Posts `["align_on_radec", ra, dec]` on `align_command_queue`.
   - Polls `align_result_queue` for up to 2 s. On timeout it posts
     `["align_cancel", ra, dec]` and reports "Align Timeout."
3. **`solver.py`** picks up the command at the top of its loop, stores
   `align_ra` / `align_dec`, and on the next plate-solve passes
   `target_sky_coord=[[align_ra, align_dec]]` to tetra3. tetra3 then
   reports `x_target` / `y_target` — the pixel where that sky
   coordinate lands in the current frame.
4. **Solver pushes the result back** on `align_result_queue` as
   `["aligned", (y_target, x_target)]` and clears `align_ra`/`align_dec`
   so subsequent solves go back to normal.
5. **`align_on_radec`** receives the pixel and commits it:
   ```python
   shared_state.set_solve_pixel(target_pixel)
   config_object.set_option("solve_pixel", target_pixel)
   ```
   `shared_state` makes it effective immediately; `Config` makes it
   survive a restart.

### 5.3 Coordinate conventions and reset

- `solve_pixel` is stored as `(Y, X)` in camera-image space (512×512).
- `shared_state.solve_pixel(screen_space=True)` returns `(X, Y)`
  rescaled to display space (128×128 = camera/4) for UI overlays.
  (No UI currently consumes this form — the Focus-screen reticle that
  did was removed; the accessor remains for future overlays.)
- Resetting alignment in the UI calls
  `shared_state.set_solve_pixel((256, 256))` and writes the same value
  to `Config` — i.e. recenter the eyepiece pixel on the image center.

### 5.4 Why alignment doesn't disturb IMU tracking

The IMU is rigidly attached to the camera, not the eyepiece. The
camera-to-IMU transform learned by `ImuDeadReckoning.solve(pointing, q_x2imu)`
must therefore be expressed in terms of the **camera center**, which
is why the integrator passes `solved["camera_solve"]` (not
`solved["RA"/"Dec"]`) into `update_plate_solve_and_imu()`. Changing
`solve_pixel` shifts the published `solved["RA"/"Dec"]` but leaves
`camera_solve` untouched, so the IMU model is unaffected.

---

## 6. Distribution

Once `shared_state.set_solution(solved)` is called, downstream consumers
read the dict by polling `shared_state.solution()`:

- **UI** (`PiFinder/ui/*`) — chart, telrad, catalog pages.
- **Web server** (`PiFinder/server.py`) — `/api/current-selection`,
  status table, SkySafari proxy pages.
- **Position server** (`PiFinder/pos_server.py`) — serves the LX200-style
  telescope protocol to SkySafari and other planetarium apps.
- **Catalogs** — use RA/Dec (and `Alt`/`Az` when available) to compute
  visibility and "near me" lists.

`shared_state.set_solve_state(bool)` is a separate, lighter signal that
tells consumers whether a current solution exists (used by the UI to
show the "no solve" indicator).

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
  dict onto `solver_queue`. Auto-exposure depends on `Matches` being
  updated whether or not the plate-solve succeeded.

---

## 8. Glossary

The canonical glossary lives at [`positioning/CONTEXT.md`](./positioning/CONTEXT.md).
Use those terms when reading, writing, and discussing code in this area.

Note in particular: the dataclass model in `PiFinder/types/positioning.py`
supersedes the legacy `solved` dict described above. The canonical access
shape is `pointing.<axis>.<state>.<RA|Dec|Roll>` — see also
[`docs/adr/0001-positioning-vocabulary.md`](../adr/0001-positioning-vocabulary.md).
