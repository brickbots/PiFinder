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

**Saved exposure**:
The exposure regime the user last chose and the camera boots into: either a fixed exposure time or auto. Distinct from the exposure actually in effect, which under solver-driven auto-exposure is wherever the controller has currently settled.
_Avoid_: `camera_exp` (the config key — a storage location, not the concept).

**Exposure hold**:
A screen taking the exposure for the duration of a visit: it enters manual exposure at the exposure already in effect, leaves the saved exposure untouched, and hands the previous regime back on exit. A hold is **transient** — it is never persisted, so it survives only as long as the screen is open, and it is not a fourth regime (the camera is in manual exposure throughout).

Screens hold the exposure when a moving exposure would corrupt what the user is there to judge or measure: the Focus screen (defocus starves the solver of matches, so auto-exposure would walk the exposure — and with it the focus indicator and which stars appear — while the user is reading a change in focus out of those same frames), and SQM calibration (its frames are photometric measurements).
_Avoid_: freezing/locking exposure (the exposure still changes when the user asks), temporary manual exposure.

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

### Frame extents

Two regions of the sensor are in play at once, and confusing them is the
standing hazard in this area. Always say which one you mean.

**Full-sensor frame**:
Every pixel the sensor delivers, uncropped. Written by `capture_raw_file()` —
always, with no option to write anything narrower — and archived by the
exposure sweep capture as `*_rawfull_*.tiff`. Nothing measures it: it exists so
the margins are on disk for later analysis, because a margin not captured is
gone for good.
_Avoid_: raw frame (unqualified — the crop is equally raw).

**Crop**:
The centred square region of the sensor. This is what `cam_raw()` holds, what
SQM photometry measures, and what each sweep frame's `raw_stats` covers. The
crop is a plain slice of the full-sensor frame, so
`CameraProfile.ensure_cropped()` recovers it exactly from an archived
full-sensor frame — that equivalence is what lets full-sensor sweeps reproduce
every number the cropped-era archive produced.

The asymmetry inside a single sweep frame is deliberate and worth stating
plainly: **the TIFF is full-sensor, its `raw_stats` are crop-only.** Those
statistics are the black-level-versus-temperature series, and the vignetted
margins would shift every mean and percentile, ending comparability with sweeps
taken before the archive went full-sensor. New records carry
`raw_stats.extent: "crop"` and `sweep_metadata.json` carries
`camera.raw_frame_extent: "full_sensor"`, so an archive states which is which
instead of relying on anyone remembering.

### Optics

What the camera *sees* is set by two independent things: the sensor it detects
at startup, and the lens screwed onto it, which nothing can detect. Keeping
them separate — and naming their combination — is what lets field of view be
derived instead of hard-coded.

**Lens**:
The finder's camera lens (M12 mount). Always the *finder* lens — never the
user's telescope or eyepiece, which are [Equipment](../equipment/CONTEXT.md)
vocabulary and have their own focal lengths. Not detectable *directly* — no
lens reports its focal length — but not unknowable either: once a frame
solves, the **fitted FOV** measures the whole train, and the lens is what is
left after dividing out the sensor. Whether the device is entitled to act on
that measurement depends on whether the lens is **stated** or **assumed**.
_Avoid_: "the lens" unqualified in any prose that also discusses telescope
optics; objective (that is the telescope's).

**Stated lens**:
A lens recorded in the `camera_lens` config key — a claim that *this* glass is
physically fitted. The claim is authoritative: it narrows the FOV gate around
the one field of view it implies, and nothing overrides it, so a wrong
statement still means no solves (that is [ADR
0027](../../adr/0027-fov-gate-derived-from-optical-train.md)'s deliberate
consequence, not a regression). Written by the user from the Lens menu, or
once by the device itself from a fitted FOV it is confident about — but never
from a fitted FOV measured under an **unknown optical train**, which measures
a recording rather than this device.
_Avoid_: configured lens (true of a self-healed value too, so it does not
distinguish), selected lens, user lens.

**Assumed lens**:
The camera profile's fallback (`default_lens_key`), used when no lens is
stated. Not a claim about the hardware — an admission that nobody has said,
which is the ordinary condition of an install predating the setting. Because
there is nothing to trust, the FOV gate widens to cover *every* lens that
sensor has shipped with rather than centring on the fallback. An assumed lens
is a temporary state: the first confident solve turns it into a stated one —
unless the train is **unknown**, in which case no solve ever ends the
assumption, because none of them measured this device.
_Avoid_: default lens (reads as a preference rather than an absence of
information), unset lens (the field of view is never unset — some lens is
always assumed).

**Nominal focal length**:
The focal length printed on the lens barrel — what the user reads and picks
from a menu. The label, not the measurement.
_Avoid_: focal length (unqualified — always say which of the two you mean).

**Effective focal length**:
The focal length the lens actually behaves as, measured on-sky. It is what
every derived value is computed from. The shipped "16 mm" lens measures
~15.6 mm, consistently across two independently calibrated sensors — so
nominal and effective are routinely different, and only one of them is
correct to compute with.
_Avoid_: true focal length, actual focal length (say effective).

**Pixel pitch**:
The sensor's physical pixel spacing in µm. With the **crop** width it gives
the imaged extent in mm, which with the effective focal length gives field of
view. A property of the sensor, so it belongs on the camera profile.
_Avoid_: pixel size (ambiguous with the pixel's active area).

**Optical train**:
The (camera profile, lens) pair. The unit that determines field of view, plate
scale and the solver's FOV gate — none of which are properties of the sensor
or the lens alone. The sensor half is detected, the lens half is configured,
and the pair is resolved wherever a derived value is needed.
_Avoid_: optical configuration ("configuration" already names the physical
build variants — see [Positioning](../positioning/CONTEXT.md) *screen
direction*), camera setup, imaging train.

**Unknown optical train**:
The state of a camera whose frames did not come through this device's optics
at all — today only the debug camera, which replays archived frames. The
device's train still resolves to *something* (the debug camera declares the
sensor its frames were shot on), but that train describes the machine, not
the frames, so two things follow: nothing about the device may be **asserted**
about the frames — the solver is handed no FOV gate rather than a derived one
— and nothing about the device may be **inferred** from them, so a fitted FOV
cannot promote an **assumed lens** to a **stated** one. This is the third rung
of the confidence ladder the FOV gate's width follows: stated → ±15%, assumed
→ the union over the sensor's shipped lenses, unknown → no gate at all (see
[ADR 0029](../../adr/0029-fov-gate-width-follows-lens-confidence.md)).
Deliberately *not* a blanket "everything derived goes dark": the **frustum**
still answers what the configured camera would image, which is a question
about the device and stays meaningful while a recording is being replayed.
_Avoid_: debug FOV, no FOV (the frames have one — nobody here knows it),
unknown lens (the lens resolves normally; it is the pairing that means
nothing), fake camera.

**Field of view**:
The angular width of the **crop**, in degrees — the edge-to-edge extent, not
the diagonal. Derived from the optical train. Every consumer that needs to
know how much sky a frame covers (the solver's FOV gate, SQM's solid angle,
the chart's frustum shading) derives it from the same place rather than
carrying its own constant.
_Avoid_: FOV of the sensor (a sensor has no field of view without a lens),
diagonal FOV (state it explicitly if you ever mean the diagonal).

**Plate scale**:
Angular size of one pixel, in arcsec. Stated against a named pixel grid —
the 512×512 solver image or the native crop — because the two differ by the
downscale factor and confusing them silently rescales any angle computed
from it.
_Avoid_: arcsec per pixel (unqualified — say which grid), resolution.

**Frustum**:
The box drawn on a chart marking the part of it the camera images — the
**field of view** of the current optical train, inside the chart's own zoom
level. It does two jobs at once: the chart outside it can be dimmed, and it
selects the stars the chart reports back, which is why the align screen only
offers alignment stars the camera can actually see. A chart is rendered with
a frustum only when the caller states a camera field of view; **no frustum**
is a real state (`plot.frustum_box` returns None), not a default box, because
there is no stand-in for a number that is a property of the hardware fitted
to that particular device.
_Avoid_: camera box, FOV box, "the frustrum" in prose (the misspelling
survives only in the `shade_frustrum` argument name); "visible stars" meaning
*stars on the chart* — with a frustum they are the stars inside it.

### Cross-context terms

- **`Matches`** — defined in [Positioning](../positioning/CONTEXT.md): count of stars tetra3 matched in the most recent solve attempt, published on every attempt (success or failure) because auto-exposure depends on it. The feedback signal for solver-driven auto-exposure.
- **Processed-image floor** — the 8-bit ADU threshold stored in shared state and consumed here as the minimum acceptable background. It is distinct from the raw-sensor pedestal and read-noise diagnostics in [SQM](../sqm/CONTEXT.md).
- **`SCREEN_ROTATE_AMOUNTS`** — owned here (`camera_interface.py`): the per-variant software rotation applied to each capture before it reaches the solver and preview, keyed by screen direction. The post-rotation image defines Positioning's **camera frame**, so each entry is only valid paired with that variant's `q_imu2cam` (defined in [Positioning](../positioning/CONTEXT.md)); pairs are derived with the imu2cam tool and pinned together by `tests/test_imu2cam_tool_presets.py`. It is also the source of the published **solve-image rotation** that SQM inverts to map solve-image centroids back onto the raw frame.

## Flagged ambiguities

- **"Focal length"** is owned by two contexts and means different hardware in each. [Equipment](../equipment/CONTEXT.md) uses it for the user's **telescope** and **eyepiece** (`Telescope.focal_length_mm`, `Eyepiece.focal_length_mm`, driving magnification and true field). Camera uses it for the **finder lens**. Never write it bare in prose that touches both — say *lens focal length* or *telescope focal length*. Within Camera, further qualify as **nominal** or **effective**: they differ by ~2.5% on the shipped lens, and only the effective one is correct to compute with.
- **"FOV"** appears as three different quantities. The **field of view** defined here is a property of the optical train. Tetra3's `fov_estimate` / `fov_max_error` are the solver's **FOV gate** (see [Positioning](../positioning/CONTEXT.md)) — inputs derived *from* the field of view, not synonyms for it. `SolveDiagnostics.FOV` is the value tetra3 **fitted** from the frame — an independent measurement that can be compared against the derived one. Say which you mean.
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
>
> **Dev:** And the Focus screen — the exposure it shows doesn't move at all.
>
> **Domain:** That's an exposure hold. It takes the exposure in effect on entry and stays there. Otherwise the very thing the user is on that screen to fix — defocus — starves the solver of matches, so the controller would keep adjusting, and eventually hand over to recovery, moving the focus indicator and the visible stars for reasons that have nothing to do with the lens the user just turned.
>
> **Dev:** So a badly wrong exposure just stays wrong there?
>
> **Domain:** Until the user steps it themselves, yes — that's the trade the hold makes. It's why the screen offers exposure steps at all, and why it reports the held exposure rather than the saved one.
