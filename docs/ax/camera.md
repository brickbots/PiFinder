# Camera architecture: exposure control

This document describes how PiFinder decides the camera exposure time —
the three exposure regimes, the two feedback controllers inside
solver-driven auto-exposure, and zero-match recovery.

It focuses on the runtime path in the camera process:

- `PiFinder/auto_exposure.py` — the controllers and recovery logic.
- `PiFinder/camera_interface.py` — `get_image_loop`, the capture loop that
  wires solve results and UI commands into the controllers.

Glossary: [`camera/CONTEXT.md`](./camera/CONTEXT.md). Decision record for
the recovery consolidation: [ADR 0010](../adr/0010-zero-match-recovery-single-ladder.md).

---

## 1. Data flow

```
solver process                          camera process (get_image_loop)
  tetra3 solve attempt                    capture frame
    └─ Matches (every attempt,              │
       success or failure) ──────────► shared_state.solution()
                                            │  new last_solve_attempt only
                                            ▼
                              ┌─ match-count controller (default)
                              │    └─ Matches == 0 → zero-match recovery
                              └─ background controller (SQM screen only)
                                   └─ reads processed 8-bit floor (10 ADU)
                                            │
                                            ▼
                                   set_camera_config(exposure, gain)

UI / main process ── command_queue ──► "set_exp:…", "set_gain:…",
                                       "set_ae_mode:…", "exp_up/dn/save", …
```

Feedback is naturally rate-limited: a controller runs only when a solve
result with a **new** `last_solve_attempt` timestamp appears
(`camera_interface.py`, the `_last_solve_time` check), and only for
solve sources `CAM` / `CAM_FAILED` — failed attempts feed the loop too,
because `Matches` is published on every attempt (see Positioning).

## 2. Exposure regimes

Exactly one of three authorities decides exposure at any moment:

| Regime | Entered by | Exposure decided by |
| --- | --- | --- |
| Solver-driven auto-exposure | `set_exp:auto` (menu "Auto", or restored from `camera_exp: "auto"` at startup) | match-count or background controller |
| Native auto-exposure | `set_exp:native` (daytime alignment only) | the camera driver |
| Manual exposure | `set_exp:<µs>` (menu), `exp_up` / `exp_dn` | the user |

Transitions worth knowing:

- **Daytime alignment** (`ui/align_daytime.py`) enters native AE on
  activation and restores the prior setting on exit (`set_exp:auto` or the
  saved manual value). On backends with no native AE (debug / non-Pi),
  the fallback is a fixed 1 ms daylight exposure
  (`DAYTIME_AE_FALLBACK_EXPOSURE`).
- **Any manual nudge wins**: `exp_up` / `exp_dn` silently drop both
  auto-exposure regimes. The new value is *not* persisted until
  `exp_save`, which also writes `camera_gain`.
- Selecting a manual value from the menu persists it to `camera_exp`
  immediately; selecting "Auto" persists the string `"auto"`.

## 3. Match-count controller

`ExposurePIDController` (`auto_exposure.py`). Steers exposure so the
solver keeps matching a healthy number of stars.

- **Target match count** 17, **deadband** ±5 (no adjustment within
  12–22 matches).
- **Asymmetric gains**: conservative descent when there are too many
  matches, aggressive ascent when too few — being too dark is the costly
  direction at night.
- **Rate limiting** applies only to decreases (`update_interval` 0.5 s);
  increases respond immediately.
- **Integral hygiene**: the integral resets when the error changes sign,
  and anti-windup backs out the integral contribution when the output
  clamps to `[min_exposure, max_exposure]` = [25 ms, 1 s].

## 4. Zero-match recovery

When a solve attempt produces zero `Matches`, the match-count controller
stops trusting its feedback signal and delegates to recovery
(`update()` → `_handle_zero_match` → `ZeroMatchRecovery`).

- **Trigger count** 2: recovery activates on the second consecutive
  zero-match attempt.
- **Recovery ladder**: `[400, 800, 1000, 200]` ms — start at the
  known-safe shipped default, climb first (too-dark dominates at night),
  then one short rung. The ladder floors at 200 ms (ADR 0010): below
  that, a frame is unlikely to pick up enough stars to solve, even under
  a bright sky. Each rung is tried twice (two solve attempts), and the
  ladder wraps until matches return.
- **The floor is recovery's, not the controller's**: the match-count
  controller's clamp range (§3) still reaches down to 25 ms — a
  feedback-justified descent is fine; recovery's blind search below
  200 ms isn't.
- **Exit**: the first nonzero-`Matches` attempt deactivates recovery and
  resets the controller's integral and last-error so the excursion
  doesn't bias the next adjustment.

Recovery's responsibility is exactly one failure cause: **the exposure is
badly wrong** (dusk/dawn, slew into bright sky, returning from daytime
alignment). Defocus, transient blockage, and solver-side failures are
deliberately out of scope — see ADR 0010. That decision also removed the
three alternative strategies (Exponential, Reset, Histogram), the
`ZeroStarHandler` plugin seam, the `set_ae_handler` command, the
Experimental "AE Algo" menu, and the `auto_exposure_zero_star_handler`
config key. Recovery is now the single concrete `ZeroMatchRecovery` class;
stale `auto_exposure_zero_star_handler` values in a user's config are
ignored.

## 5. Background controller

`ExposureSNRController` (`auto_exposure.py` — "SNR" is a misnomer; see
the glossary). Used for SQM measurement, which wants longer, steadier
exposures than match-count control produces.

- Activated screen-scoped: `ui/sqm.py` sends `set_ae_mode:snr` in
  `active()` and `set_ae_mode:pid` in `inactive()`. The controller choice
  is never persisted.
- Feedback signal: the processed frame's 10th-percentile 8-bit ADU value
  ("dark pixel" background). The controller keeps it above the processed
  floor in `shared_state.noise_floor()` (10 ADU by default), with a +2 ADU
  margin. SQM photometry runs on raw sensor values, whose pedestal is in a
  different unit and is deliberately not published to this controller.
- Adjustments are multiplicative (×1.3 / ÷1.3) for stability; it ignores
  `Matches` entirely and has no zero-match recovery.

This is the consumer side of the SQM → Camera relationship in
`CONTEXT-MAP.md`.

## 6. Diagnostic exposure sweep capture

Unrelated to recovery despite the shared word "sweep":
`capture_exp_sweep` (triggered from the SQM tools UI) captures 100
RAW+processed image pairs across a logarithmic exposure range into
`~/PiFinder_data/captures/sweep_<timestamp>/` with GPS/location metadata,
for offline analysis. Auto-exposure is disabled for the duration.

## 7. Gotchas

- **Shipped default regime is solver-driven auto-exposure.**
  `default_config.json` ships `camera_exp: "auto"`, so auto-exposure —
  including all recovery machinery — runs out of the box. The recovery
  ladder starts at 400 ms (the previous fixed default), so the first-frame
  behavior is unchanged; from there feedback control takes over. Existing
  users keep whatever `camera_exp` their saved config holds (a manual µs
  value or `"auto"`); only fresh installs and config resets get the new
  default. (ADR 0010 deferred this regime choice; it was resolved in
  favor of `"auto"` once the floored single-ladder recovery made
  auto-exposure safe by default.)
- **The AE gate requires the match-count controller object even in
  background mode**: `get_image_loop` checks
  `_auto_exposure_enabled and _auto_exposure_pid` before dispatching to
  either controller.
- **Controller choice is screen-scoped, in-memory only.** A restart while
  the SQM screen was last active comes back in match-count mode.
- **Failed solves drive feedback.** `CAM_FAILED` results carry
  `Matches = 0` into the controller; that is what makes zero-match
  recovery possible at all, but it also means solver-side failures look
  identical to darkness from the camera's point of view.
- **Zero `Matches` ≠ empty frame.** A star-filled but unsolvable frame
  (defocus, motion, distortion) walks the same recovery path. By ADR 0010
  recovery does not try to fix those — expect ladder cycling until the
  underlying cause clears.
