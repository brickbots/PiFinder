# Camera

The Camera context owns image capture and exposure control in the camera process. Its central concern is auto-exposure: keeping the plate solver fed with solvable frames as sky conditions change.

> Companion architecture doc: [`../camera.md`](../camera.md).

## Language

### Exposure regimes

**Exposure regime**:
Which of three authorities decides the exposure time: **solver-driven auto-exposure**, **native auto-exposure**, or **manual exposure**. The camera is in exactly one regime at a time.
_Avoid_: exposure mode, AE mode ("mode" is overloaded — see flagged ambiguities).

**Solver-driven auto-exposure**:
The regime where exposure is chosen by feedback from plate-solve results. The camera process adjusts exposure after each new solve attempt.
_Avoid_: auto-exposure (unqualified, when native AE is in play — see below).

**Native auto-exposure**:
The regime where the camera driver's own auto-exposure decides, used only for daytime alignment. Entering it disables solver-driven auto-exposure so the two never fight.
_Avoid_: driver AE, daytime AE (it's the *use*, not the mechanism).

**Manual exposure**:
The regime where the user fixes the exposure time. Any manual adjustment (including nudging exposure up/down) drops the camera out of both auto-exposure regimes.

### Controllers

**Controller**:
The feedback loop inside solver-driven auto-exposure that turns the latest solve result into an exposure adjustment. Exactly one of two is active: the **match-count controller** (the default) or the **background controller**.
_Avoid_: mode (see flagged ambiguities), algorithm.

**Match-count controller**:
Drives exposure toward a target `Matches` count, adjusting gently downward and aggressively upward, and holding still inside a deadband around the target. Delegates to zero-match recovery when a solve attempt matches nothing.
_Avoid_: PID controller, PID mode (the code/wire name — it names the algorithm, not the job).

**Background controller**:
Drives the processed 8-bit frame's dark-pixel background above a processed-image floor (10 ADU by default), producing the longer, steadier exposures SQM measurement needs. Active only while the SQM screen is; ignores `Matches` entirely and has no zero-match recovery. The raw SQM pedestal is in different units and is not used here.
_Avoid_: SNR controller, SNR mode (the code/wire name — no signal-to-noise ratio is computed anywhere in it).

**Target match count**:
The `Matches` count the match-count controller steers toward.

**Deadband**:
The band around the target match count inside which the match-count controller makes no adjustment.

**Zero-match recovery**:
The escape hatch entered when a solve attempt matches nothing: the match-count controller stops trusting its feedback signal and walks the recovery ladder until matches return. Its responsibility is recovering from a **badly wrong exposure** (conditions changed faster than feedback control can track — dusk/dawn, slew into bright sky, returning from daytime alignment). It is explicitly **not** responsible for defocus (the focus indicator owns that), transient blockage (clouds, capped scope), or solver-side failures where exposure isn't the problem.
_Avoid_: zero-star handling (legacy code name — the trigger is zero `Matches`, not an empty sky; a star-filled frame can still match nothing).

**Recovery ladder**:
The ordered list of exposures zero-match recovery walks through, trying each rung a fixed number of times before advancing, wrapping around until matches return. The ordering is deliberate: start at the known-safe shipped default, climb to longer exposures first (too-dark dominates at night), then try short. The ladder floors at 200 ms — shorter exposures are unlikely to pick up enough stars to solve (see [ADR 0010](../../adr/0010-zero-match-recovery-single-ladder.md)).
_Avoid_: sweep (unqualified — see flagged ambiguities).

**Trigger count**:
The number of consecutive zero-match solve attempts required before recovery activates.

**Retired recovery strategies**:
Zero-match recovery was briefly a plugin point with four selectable strategies (Sweep, Exponential, Reset, Histogram) behind the Experimental "AE Algo" menu. [ADR 0010](../../adr/0010-zero-match-recovery-single-ladder.md) kept the Sweep ladder as the only behavior and removed the rest, the plugin seam, the menu, and the `auto_exposure_zero_star_handler` config key. Recovery is now the single concrete `ZeroMatchRecovery` class.
_Avoid_: AE algo, zero-star handler, handler, plugin.

### Cross-context terms

- **`Matches`** — defined in [Positioning](../positioning/CONTEXT.md): count of stars tetra3 matched in the most recent solve attempt, published on every attempt (success or failure) because auto-exposure depends on it. The feedback signal for solver-driven auto-exposure.
- **Processed-image floor** — the 8-bit ADU threshold stored in shared state and consumed here as the minimum acceptable background. It is distinct from the raw-sensor pedestal and read-noise diagnostics in [SQM](../sqm/CONTEXT.md).

## Flagged ambiguities

- **"Mode"** is overloaded in code: `_auto_exposure_mode` is the pid/snr controller split, while "auto-exposure mode enabled" in logs means the solver-driven regime is on, and the menu's "Auto" is a regime choice. In discussion, use **regime** for the three-way state and **controller** for the pid/snr split; avoid bare "mode".
- **"SNR"** appears throughout code and the SQM docs for the background controller (`set_ae_mode:snr`, `ExposureSNRController`, "SNR target"). No signal-to-noise ratio is computed — the mechanism is "background above noise floor". Say **background controller**; treat "SNR" as a wire-protocol/code artifact.
- **"Sweep"** still names the 100-frame diagnostic **exposure sweep capture** (saved to `captures/sweep_*` for offline analysis, via `generate_exposure_sweep`). Now that the sweeping recovery strategies are gone (ADR 0010), this is recovery-independent — qualify as "exposure sweep capture", and use "recovery ladder" for the recovery exposures.
- **"AE Algo"** was the Experimental menu label for selecting the zero-match recovery strategy; ADR 0010 removed it (recovery is now a single fixed behavior). It may still appear in stale translation catalogs.
- **"Zero-star"** is retired from the code — recovery uses "zero-match" throughout (`ZeroMatchRecovery`, `_zero_match_count`, `_handle_zero_match`). The name lingers only in the historical ADR 0010 title and old user configs. Always "zero-match" in discussion — the distinction is load-bearing (zero matches with a sky full of stars is a different failure than an empty frame, and only one of them is recovery's job).

## Example dialogue

> **Dev:** Why did exposure jump back to 0.4 s right after daytime alignment?
>
> **Domain:** Leaving daytime alignment hands the exposure regime back from native auto-exposure to solver-driven. A daylight exposure matches nothing at night, so after the trigger count the match-count controller delegates to zero-match recovery, and the recovery ladder starts at the known-safe default.
>
> **Dev:** And once stars match again?
>
> **Domain:** The first solve attempt with nonzero `Matches` exits recovery and returns control to the match-count controller, with its integrator cleared so the recovery excursion doesn't bias the next adjustment.
>
> **Dev:** Does the SQM screen change any of this?
>
> **Domain:** While it's active, the controller flips to the background controller — exposure tracks the noise floor instead of `Matches`, and there is no zero-match recovery at all. Leaving the screen flips back. None of that is persisted.
