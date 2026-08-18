# Context Map

PiFinder is a multi-process Raspberry Pi finder/plate-solver. These contexts each own a distinct slice of the runtime and have their own vocabulary.

## Contexts

- [Catalog](./docs/ax/catalog/CONTEXT.md) — loads, filters, searches astronomical catalogs (M, NGC, IC, WDS, planets, comets) for the UI.
- [Positioning](./docs/ax/positioning/CONTEXT.md) — acquires telescope pointing via plate-solving and IMU dead-reckoning; publishes the canonical "where am I looking?" answer.
- [SQM](./docs/ax/sqm/CONTEXT.md) — estimates sky brightness in mag/arcsec² from solved frames; also produces the noise-floor signal auto-exposure consumes.
- [Equipment](./docs/ax/equipment/CONTEXT.md) — models the user's telescopes and eyepieces; supplies the active optics that drive magnification, true field of view, and object-image orientation.
- [UI](./docs/ax/ui/CONTEXT.md) — the on-device menu system: menu tree, screen modules, the navigation stack and key dispatch, marking menus.
- [Camera](./docs/ax/camera/CONTEXT.md) — captures frames and decides exposure: the three exposure regimes, the auto-exposure controllers, and zero-match recovery.
- [Battery](./docs/ax/battery/CONTEXT.md) — reads battery voltage and charge state from the rev-4 BQ25895 charger and publishes `BatteryState`; read-only telemetry, gated on hardware presence.
- [Sound](./docs/ax/sound/CONTEXT.md) — turns named events into short **earcons** on the rev-4 passive buzzer (hardware PWM ch0, GPIO12); best-effort, fire-and-forget feedback, gated on hardware presence.
- [Display](./docs/ax/display/CONTEXT.md) — how panels turn rendered pixels into light: each panel's brightness axes, the dimming policy (knee curve), and the camera-as-photometer bench rig that measures panel flux. Runtime policy + bench tooling.
- [NixOS](./docs/ax/nixos/CONTEXT.md) — how a NixOS PiFinder is built, published, and updated over the air: the Attic cache, the stable/beta/unstable channels, and the on-device upgrade flow. Cross-cutting infrastructure, not a runtime slice.
- [Bring-up](./docs/ax/bringup/CONTEXT.md) — first power-on validation of a freshly assembled board: the checks a builder runs at the bench and which of them can be machine-verified. Bench tooling, not a runtime slice.

## Relationships

- **Positioning → Catalog**: Catalog reads RA/Dec/Alt/Az from `shared_state.solution()` to compute visibility and "near me" lists.
- **Positioning → SQM**: SQM is a side effect of every successful plate solve in the solver process; it reuses the tetra3 `matched_centroids` and the camera frame.
- **SQM / Camera units boundary**: SQM photometry and its pedestal diagnostics use raw sensor ADU. The Camera background controller measures processed 8-bit images and uses its separate shared 10 ADU floor; raw SQM thresholds must not cross that boundary.
- **Positioning → Camera**: `Matches` is published on every solve attempt (success or failure) as the feedback signal for solver-driven auto-exposure.
- **Camera → Positioning / SQM / UI (optical train)**: Camera owns the **optical train** — the detected sensor profile paired with the configured **lens**. Its derived **field of view** is the single source for Positioning's **FOV gate**, SQM's **radiometric field width**, and the chart's frustum shading. Each of those was previously an independent hard-coded constant, and they disagreed with each other and with the hardware. The sensor half is auto-detected and the lens half cannot be detected at all, so a mis-stated lens is a configuration error that surfaces as *no solves whatsoever* — deliberately not auto-corrected (see [ADR 0027](./docs/adr/0027-fov-gate-derived-from-optical-train.md)).
- **Camera → Positioning**: `SCREEN_ROTATE_AMOUNTS` (`camera_interface.py`) rotates every capture before the solver sees it; the post-rotation image defines Positioning's **camera frame**, so each entry is only valid paired with that variant's `q_imu2cam` — pairs are derived with the imu2cam tool and pinned together by `tests/test_imu2cam_tool_presets.py`.
- **Catalog ↔ Positioning**: Catalog supplies the `(RA, Dec)` target for the alignment flow that calibrates `solve_pixel` in Positioning.
- **Equipment → Catalog**: the active telescope's flip/flop flags and the active eyepiece's true field of view orient and scale the POSS/SDSS object image in `cat_images.get_display_image`.
- **Positioning → Equipment**: the object-image baseline rotation combines the active telescope's flip/flop with the live solve **roll** from `shared_state` (see [ADR 0003](./docs/adr/0003-object-image-orientation.md)).
- **Battery → UI**: STATUS (and web/API) display `BatteryState` from `shared_state.battery()` — *consumption is future work; this run is plumbing + tests only*.
- **Battery → system-wide**: `hardware_detect` probes the I²C bus at startup and publishes `HardwareCapabilities` into `shared_state`; the battery monitor process only runs when `has_bq25895` is detected (rev4). The same capabilities record is the source of truth for other rev-dependent decisions.
- **Sound → system-wide**: `hardware_detect` sets `has_buzzer` from the *same* rev4 marker (the charger probe — a bare GPIO buzzer can't be probed directly); the sound process only spawns when `has_buzzer`. On rev3/dev `sound_queue` is `None` and the producer helper no-ops.
- **UI → Sound**: keypresses and the volume menu in the main loop request earcons (`KEYPRESS`, `VOLUME_SAMPLE`); master volume is a `Config` setting (`sound_volume`) pushed to the player as `SetVolume`.
- **Sound → shutdown**: the shutdown chokepoint (`callbacks.shutdown`) plays `SHUTDOWN` and waits its catalog duration + margin **before** triggering the GPIO14 power latch (see [ADR 0007](./docs/adr/0007-gpio-poweroff-latch.md)), so the cue isn't cut off by power-down.

- **Bring-up → Battery / Sound / Positioning**: bring-up constructs those contexts' hardware seams *directly* (`BQ25895`, `BuzzerPWM`, `imu_pi.Imu`) instead of spawning their monitor processes — it is a single process with no `SharedStateObj`. It stays inside each context's rules: charger access is reads plus the sanctioned one-shot ADC trigger, never the fast-charge config write (ADR 0017), and earcons come from the Sound catalog rather than raw tones.
- **Display → UI**: the UI's brightness setting (level, 0-255) is Display vocabulary; `set_brightness` in the display drivers maps it to each panel's axes. The UI's tonal-range canary (the title-bar shade) constrains how far the dimming policy may cap rendered pixel values.
- **Display → Camera**: the photometer rig borrows the Camera context's sensor (lensless, fixed manual exposure) as its light meter and the SQM camera profiles for bias/crop constants — bench-only; at runtime the two contexts don't interact.
- **Display ↔ Bring-up**: both are (partly) bench tooling that drives panels below the UI layer; bring-up checks "does the panel light at all", Display characterizes how much light.
- **Bring-up → UI**: bring-up reuses the display drivers, fonts and layout helpers, but **not** `UIModule`, `MenuManager` or the menu tree — it draws its own frames and never joins the navigation stack. It reads the keypad as **switches** at their **matrix positions**, below the layer where UI's logical **keys**, `ALT_*` chords and `LNG_*` long presses are formed.
- **Bring-up ↛ `hardware_detect`**: unlike `main.py` and `splash.py`, bring-up does **not** derive its panel from the BQ25895 probe. Doing so would make a dead charger indistinguishable from a dead screen on exactly the boards it exists to diagnose.

Companion architecture docs live next to each `CONTEXT.md`:
- [`docs/ax/nixos.md`](./docs/ax/nixos.md)
- [`docs/ax/catalog.md`](./docs/ax/catalog.md)
- [`docs/ax/positioning.md`](./docs/ax/positioning.md)
- [`docs/ax/sqm.md`](./docs/ax/sqm.md)
- [`docs/ax/equipment.md`](./docs/ax/equipment.md)
- [`docs/ax/ui.md`](./docs/ax/ui.md)
- [`docs/ax/camera.md`](./docs/ax/camera.md)
- [`docs/ax/bringup.md`](./docs/ax/bringup.md)
