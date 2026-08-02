# PiFinder v2.6.1 Release Notes

A substantial point release built on field feedback from v2.6.0: a rebuilt Focus screen that shows you the actual stars, a self-calibrating Sky Quality Meter that finally holds steady through a night, chart markers for the objects around you, full software enablement for rev4 hardware (battery, sound, power button, 176px display), and a fix for a bug that silently killed plate solving on any unit you'd ever SSH'd into.

## ⚠️ After You Update

- **SQM readings are on a new scale.** The Sky Quality Meter was rebuilt around raw-sensor photometry with per-frame black-level tracking. Values are no longer comparable with readings logged under v2.6.0 or earlier. The SQM screen will also show as **uncalibrated** after updating — the calibration file is now keyed to the camera rather than the processed image. A wizard run is no longer required to get a reading, but re-running `SQM → CALIB` (long-press for the marking menu) restores the per-camera dark-current refinement.
- **Observed status is now a property of the object, not the listing.** Logging M 31 marks NGC 224 observed, and your existing log history is applied retroactively. Expect an "Observed: No" list to visibly shrink on first use, sibling rows to gain checkmarks, and a sibling's details to show the combined log count. This is intended.
- **Set Time/Date now needs a location fix first.** Manual time is interpreted in the observer's timezone, which only exists once a location is known. The screen still opens; it shows "Set location first" and you back out with LEFT.
- **Some labels changed.** The Type filter now uses the same labels as the object-detail screen (`P. Nebula` → `Planetary`, `Double Str` → `Double star`, `Cluster/Neb` → `Cluster + Neb`, …). On the Status screen, `GPS LST` is now `GPS LCK` (last GPS lock — it was being misread as Local Sidereal Time). The SQM marking menu reads `CALIB` and `SWEEP` (was `CAL` / `CORRECT`).
- **A one-time system migration runs on update** (`v2.6.1`), adding a `RemoveIPC=no` drop-in for systemd-logind. See the shared-memory fix below for why.
- **If you're running a rev4 board with a pre-release config**, the `v4_left` / `v4_right` / `v4_straight` screen-direction values are automatically migrated to `rev4_*`. No action needed.

## New Features

### Rev4 Hardware Enablement (#498, #530, #539)
Full software support for the fourth-revision PiFinder board, all gated on runtime hardware detection so **rev3 and dev boards are unaffected**:

- **Battery telemetry** — BQ25895 charger read over I²C, with a title-bar battery icon (level buckets plus a charging bolt) and an idempotent fast-charge configuration re-asserted on every poll.
- **Sound** — an earcon subsystem on the rev4 passive buzzer, with a new `Settings → User Pref → Volume` setting (Off, 1–5). Delivery is best-effort and latest-wins, so audio never blocks the UI.
- **Power button** — a dedicated power key that opens a shutdown confirmation; a second press confirms, and the shutdown earcon plays before the GPIO14 power latch fires.
- **SSD1333 176×176 display** — rotation fixes, a resolution-flexible boot splash, and the 5-column rev4 keypad matrix with its directional cluster.
- **New build variants** in `Settings → Advanced → PiFinder Type`: **AS Heart**, **Rev4 Left**, **Rev4 Right**, and **Rev4 Straight**, joining AS Bloom. Each carries the IMU-to-camera frame constants for that mounting, derived with a new visual `imu2cam` tool and pinned to the production tables by test.

### Low-Battery Safety (#541, #549)
On battery-equipped hardware, PiFinder now warns and then shuts itself down cleanly rather than running blind into an SD-corrupting hard power cut. Advisory popups (plus an earcon) fire once at **10%** and once at **5%** state of charge, and when the charger's ADC goes blind at ~3.5 V for four consecutive polls on battery, PiFinder shows a final warning and performs an orderly software shutdown. Warnings latch for the whole discharge — only plugging in a charger re-arms them — so ADC quantisation noise near the flat knee of the discharge curve can't re-fire them (field logs showed the first implementation firing ~90 times a run). The state-of-charge curve was re-anchored on bench discharge data with 0% at the shutdown point.

### Rebuilt Focus Screen (#531)
The Focus screen now finds the **four brightest stars** in the frame and shows each magnified in its own quadrant, holding its quadrant as the image shifts under your hand. Tiles are raw camera pixels — crop and nearest-neighbour enlargement only, no sharpening or contrast tricks — so what you see is honestly how tight your stars are. The **HFD** readout sits at the center with a 10-second trace along the divider, and **SQUARE** cycles four views:

- **Stars** — the four magnified tiles
- **Single** — the brightest star alone at double magnification
- **Image** — the full camera frame
- **Stats** — HFD with an FWHM estimate, detected-star count, exposure, gain, and a raw histogram

**+/−** adjusts magnification between 4x and 16x, and a badly defocused star automatically gets a wider view so its donut isn't clipped. None of this needs a plate solve, so it works however far out of focus you start.

### Self-Calibrating Sky Quality Meter (#532, #544, #560, #561)
The SQM wandered 0.7–2.4 magnitudes within a night as auto-exposure moved, and shifted with focus and sensor swaps. It was rebuilt end to end:

- **Radiometer-first publication** — the published value now comes from the raw diffuse sky background, exposure, and a per-sensor radiometric zero point. It **no longer needs a plate solve**, so it keeps updating through failed solves and star-poor or cloudy frames.
- **Raw photometry** — measurement moved off the clipped 8-bit processed image onto the linear raw frame (Bayer green, or the mono frame). Plate solving is untouched.
- **Tracked black level** — a per-session estimator joint-fits the true black level from the auto-exposure stream, replacing a static pedestal constant that never matched the sensor.
- **A zero point that follows the sky's colour** — the radiometer measures sky in the *sensor's* passband while a reference meter measures V, and converting between them depends on the sky's spectrum: light pollution is sodium/LED and green-weighted, airglow is grey and NIR-rich. One constant per camera was therefore wrong at one end of the range or the other — the shipped value read ~0.1 mag dark at a light-polluted site and ~0.85 mag bright at a dark one. On bare sensors (imx462/imx290) the zero point is now a measured function of the frame's own red/green ratio, clamped to the calibrated range rather than extrapolated. Mono sensors and the IR-cut HQ keep a plain constant, both refit.
- **Colour and wing corrections** — a per-sensor B−V colour term (sensors without an IR-cut over-flux red stars) and a measured aperture wing correction that tracks how the star halo grows with dew and seeing.
- **Scale-aware geometry** — photometry radii are now expressed in the photometry image's pixel pitch, which fixes the imx296 (whose full-res frame put the aperture inside the star profile and left the wing estimator permanently inert).
- **Calibration wizard fixes** — captures now gate on the sensor's *actual* reported exposure with a re-capture on stale frames, and discard optical-black clamp-settle frames after each exposure change.

Stability, measured across 19 referenced exposure sweeps on four devices: within-sweep swing went from 0.7–2.4 mag to a 0.07–0.22 standard deviation, and focus sensitivity from large to 0.03 mag. Absolute accuracy against hand-held reference meters, re-derived over the full 23-sweep imx462 archive: median residual +0.005 mag with the spread collapsing from −0.23…+1.08 to −0.18…+0.16, and leave-one-night-out cross-validated error 0.247 → 0.108. The HQ's refit constant lands on a median of +0.000.

Some of the calibration is still thin, and says so in the code: the imx462 colour model's dark-site anchor is a single night, the imx296 rests on four sweeps from one observer, and the imx290 constants are mirrored from the imx462 with no sweeps of its own. Reference-meter comparisons from more sites and sensors are the thing that improves this — the `SQM → SWEEP` archive is what those refits are derived from.

### Chart Markers: Target Cross and Nearby Objects (#513)
The chart's target cross had lost all its callers in an earlier refactor and never drew; nearby catalog objects were never plotted at all, so a fresh session with no observing list loaded showed a bare chart. Both are fixed:

- The **last object you opened in details** is marked with a bright cross, labelled with its designator when on-screen and replaced by a rim arrow when it drifts off. The cross stays bright even with DSO Display turned off.
- **Nearby deep-sky objects** that pass your active filters are now plotted, with a **zoom-scaled magnitude limit** (mag 11 at 5° FOV to mag 7 at 60°) so the field reveals fainter objects as you zoom in and never crowds when you zoom out. Capped at the brightest 20, deduped against observing-list markers.

### Observing List Import: CSV and Stellarium 2.0 (#510, #527)
- **CSV is now genuinely importable from other tools.** Headers are matched case-insensitively through an alias table (`name`, `ra`/`ra_deg`, `dec`/`de`, `mag`/`magnitude`/`vmag`, …) in any column order, and coordinates parse as decimal degrees, `HH:MM:SS`, or sexagesimal. A decimal RA is degrees unless the header names hours (`RA_h`). Previously only PiFinder's own exact export format loaded — anything else silently imported as nameless objects at RA 0 / Dec 0.
- **Stellarium 2.0 lists import.** Current Stellarium builds export a new schema (lists nested under `observingLists`, whitespace-free RA strings, display-string object types); these silently produced an empty list. Both 1.0 and 2.0 now work, and object types that PiFinder doesn't recognise are coerced to `?` so they can't vanish behind the Type filter.

### Bench Bring-Up Tool (#550, #551, #552, #556)
`python -m PiFinder.bringup` validates a freshly assembled board in one command, without booting the application — no catalogs, solver, camera, or menu system, so it runs on a card with nothing configured. It drives the screen, keypad backlight, and buzzer, interrogates the IMU and charger, and scans every populated switch in the keypad matrix. Checks are typed by what actually proves them — *probed*, *exercised*, or *witnessed* — and only the first two can gate the exit status, because a program cannot know whether sound came out of a buzzer. A pre-flight pass checks card provisioning first, so a misprovisioned image is never diagnosed as a bad board.

Holding the power switch for one second ends the run and asks the OS for a clean shutdown — the same gesture the finished unit uses for the same switch, so a builder at a bench with no terminal in sight never has to pull power on a mounted filesystem. A tap still just registers the closure for the switch check, and the power cell fills a bar over the second so the boundary is visible and an accidental hold can be released.

## Improvements

- **SSD1333 dimming range** (rev4 displays): the panel's two current registers bottom out about 20x brighter than a red night-vision display wants at a dark site. Brightness now uses the gray scale ceiling as a third axis, taking the dimmest setting from 0.106% of full to 0.005% — a 13,400:1 range over 253 distinct levels, with the full 31 shades preserved at any setting at or above 0.35%. Full brightness is held to 70% of available current, measured as the point where bright pixels stop blooming. The 128×128 SSD1351 is unaffected.
- **Object type codes are single-sourced** (#511): the Type filter menu is generated from `OBJ_TYPES` rather than a hand-maintained duplicate list, with a drift guard that also covers the shipped default filter selection and the docs table.
- **Filtered lists stay fresh** (#528): logging an object now drops it from an "Observed: No" list on the next refresh, altitude-filter verdicts age out as the sky rotates (600 s TTL), and the arrival of the first GPS fix triggers a refilter — closing the boot-time gap where pre-lock verdicts let everything through forever. A list left open refreshes in place, and the cursor stays on target across refreshes, falling to the next surviving object rather than jumping to the top.
- **Timezone handling made explicit** (#508): shared state now always stores a UTC-aware datetime, with separate `utc_datetime()` and `local_datetime()` accessors so consumers can't accidentally read one as the other. This fixes the Status screen showing identical UTC and local times after manual entry, and a manual date entry that could be pre-filled 24 hours off.
- **Chinese is now actually selectable** (#562): the in-app Language menu has offered Chinese for some time and the translation shipped complete, but `zh` was missing from the validated language list in `main.py` and from the web server's accept-language match, so `--lang zh` raised "Unknown language 'zh'" and the web UI could never be served in Chinese. All four catalogs (de, es, fr, zh) are now at full coverage — 671 strings, none untranslated, none fuzzy — including the new rev4, Volume, low-battery, migration and telemetry-replay strings. Wordings were checked against the real fonts and the 128px layout budget, which caught six overflows. Two caveats: much of the translation is machine-generated and tagged in the `.po` files as needing human review (native speakers very welcome), and Chinese marking-menu labels currently render as overlapping glyphs — a known renderer issue with CJK glyph widths, not a translation problem, and one whose fix changes menu geometry for every language.

## Performance

- **Object lists open instantly** (#526): opening any catalog list re-applied the filter across all ~151k objects even when you only wanted to view NGC's 7.8k — measured at ~0.58 s per open on a Pi, from 604,680 filter calls across four opens. Catalogs already filtered against the current criteria now return their cached list, taking repeat opens from ~0.58 s to microseconds. A changed filter parameter, a deferred background load, or a comet refresh all still force a full re-filter.

## Bug Fixes

- **Plate solving silently died after an SSH logout** (#548): systemd-logind's default `RemoveIPC=yes` deletes every POSIX shared-memory segment owned by the `pifinder` user the moment that user's last login session ends — and the PiFinder services hold no login session of their own. The solver's cedar-detect segment vanished, and the recovery path raised `FileNotFoundError` *before* disabling shared memory, so the designed inline-image fallback never engaged and **every subsequent solve failed until restart**. Device logs showed ~28,000 identical solver exceptions per night on two independent units. Fixed in three layers: the client now treats an already-gone segment as released (so even the frame that hits the error still gets centroids), fresh installs get a `RemoveIPC=no` drop-in, and existing units get the same drop-in via the `v2.6.1` migration.
- **Camera Test Mode did nothing** (#542, #543): a rename in the SQM work moved the test-mode flag's initialisation inside the capture loop (resetting it every frame) and deleted the command handler that toggled it, so `Tools → Test Mode` and console key 0 had no effect on Focus or Align (Day).
- **Shared-memory solving broken by a mismatched protobuf field** (#542): the same change passed a `reopen_shmem` field the checked-in cedar-detect bindings don't have, raising `ValueError` before any RPC — and because it wasn't a gRPC error, the inline fallback never engaged. Reverted to the known-working handoff.
- **DeepskyLog equipment import crashed** (#529): importing equipment containing any new eyepiece returned an Internal Server Error, and because the save came after the import loop, telescopes collected in the same request were lost too. A v2.5.1 → v2.6.0 regression from the Flask migration.
- **Web location entry failed in comma-decimal locales** (#536): typing `51,3` (or `51.3`) into the coordinate fields and clicking Save did nothing in much of Europe — a `type="number"` input returns an empty value for locale-mismatched text, so client-side validation cancelled the submit. Only integers saved. Inputs are now text with `inputmode="decimal"`, both separators normalise before validation, and the server tolerates a comma and returns a friendly message instead of a 500.
- **GPS satellite counts were wrong on every receiver generation** (#524, #563): on protVer < 15 receivers (NEO-6/7, early M8) the per-satellite fields were parsed one byte off, so satellite IDs were channel numbers and the "seen" count was inflated to near the full channel count — the mysterious `20/0`. On protVer ≥ 15 receivers (later M8, M9, M10) the used count stayed 0 forever because NAV-PVT's `numSV` was parsed but never surfaced. Live-verified against a real MAX-M8 against gpsd's own decode. A follow-up pass fixed three more ways the counts could go wrong: a single NAV-SAT message permanently silenced the NAV-SVINFO fallback for the life of the connection (now a 5 s freshness window, so SVINFO resumes if NAV-SAT stops), NAV-PVT/NAV-SOL could publish a used count with no seen count — the physically impossible `0/9` — and NAV-SVINFO counted "used" and "seen" over different populations, so used could exceed seen.
- **Polar Align guidance corrected** (#518): field reports reversed the original advice. Step 1 said to aim *well away* from the pole, but flexure — felt mostly in camera roll — grows with how much the PiFinder's attitude changes between captures, so moderate near-pole sweeps beat wide ones.
- **Manual time entry could localise against a bogus timezone** (#512, #563): the Set Time/Date screen now gates itself on a location fix and renders a notice instead, live — the entry boxes appear the instant a fix locks while the screen is open. A location whose timezone couldn't be resolved from its coordinates now settles to UTC at the source rather than being stored as nothing: previously the screen rendered but committing the time crashed, and the line that names the zone the digits are read against was silently dropped.
- **NixOS migration wifi never connected** (#521): the initramfs shell converter wrote SSIDs into NetworkManager keyfiles as hex byte lists, but NM's keyfile format only parses decimal — so every migrated device scanned for a network literally named `61;70;6f;…`. Keyfile generation moved to unit-tested Python running on Debian before reboot; the initramfs just copies the pre-staged files.
- **NixOS migration hardening** (#523): tarballs that can't fit in board RAM are rejected before boot configuration is touched, the previous boot configuration is restored automatically after any pre-format failure, formatting is treated as the explicit destructive boundary, and unexpected `set -e` exits surface as a visible migration failure instead of panicking the kernel.
- **SQM screen exposure display and calibration detection** (#544, and the calibration-path fix above).
- **SQM diagnostic sweeps were labelled one step behind** (#561): the exposure sweep flushed a fixed two frames after each change, but the IMX290/462 serves exactly three at the old exposure — so every sweep pair's processed image belonged to the *previous* step, and the radiometer sample recorded alongside it described that image rather than its label. A fixed count can't suit every sensor (the IMX477 emits half-exposure transitional frames instead), so the sweep now watches the driver's reported exposure and discards until it matches, with a cap and a warning if it never settles. Diagnostic archives only — the on-screen SQM was unaffected.

## Hardware & Case

- **Threaded lens holddown and lens-cap accessories** (`case/accessories/tethered_lens_cap/`), contributed for v2.5 kits: an M12×0.5 threaded holddown with loose and snug jam nuts for locking focus, PETG and TPU replacement lens caps, and a tethered TPU cap that folds back against the case so it can't be lost.
- **Meade LXD dovetail adapter** (`case/adapters/dovetail_meade_lxd.stl`), contributed by John Purdy — replaces the bottom half of the standard Vixen/Synta foot with an LXD-shoe profile.
- **Threaded camera holddown for v2.5** (`case/v2.5/v25_camera_holddown_threaded.stl`).
- The obsolete tall dovetail parts were removed from `case/accessories/`.

## Documentation

- **Focus screen rewritten** in the Quick Start, covering the four views, the magnified tiles, and the small-turn technique: the whole range from badly defocused to sharp is only a few lens turns, fair-to-good is under half a turn, and 1/8–1/4 turn at a time with a pause for vibration to settle is what actually works. Later-night touch-ups should be judged on the HFD readout, not the lagging camera icon (#546).
- **Polar Alignment: "Getting a good measurement"** — per-mount advice folded in from field reports. EQ mount: point the Dec axis 7–10° off the polar axis, sweep 30–45° in RA, use Roll Off. Platform: aim within ~5° of Polaris, keep Roll On. Realistic accuracy is 20–30 arcmin, down to ~10 with a very rigid connection. Plus: turn sidereal tracking off before starting, and lock *both* mount axes before touching the adjusters — a slipping RA clutch was the most common field failure (#518).
- **Chart markers and CSV import** documented in the user guide, including a full column reference, the three accepted coordinate forms, and how to keep your own coordinates for an object the catalog would otherwise resolve.
- **Observing-list format reference** expanded with nine worked CSV examples and a JSON schema for the native `.pifinder` format.
- Menu Map updated for the new Focus views and the rev4 build variants.

## Developer Improvements

- **New bounded contexts**: `docs/ax/battery/`, `docs/ax/sound/`, and `docs/ax/bringup/` glossaries, plus `docs/bq25895_design_notes.md`.
- **Thirteen new ADRs** covering read-only battery telemetry, the gpio-poweroff latch, best-effort sound delivery, battery fast-charge configuration, UTC-aware civil datetime storage, self-gating UI modules, SoC as a runtime fraction, blind-floor shutdown, the SQM redesign, radiometer-first publication, the sky-colour-keyed radiometric zero point, SSD1333 three-axis brightness, and filter freshness.
- **Import-safe keypad module** (#551): the matrix tables moved out of `keyboard_pi` (which imports `libinput` and `RPi.GPIO` at module scope) into `PiFinder.keypad`, with per-revision population maps derived from the keymap rather than hand-listed.
- **`imu2cam` derivation tool** (#530): a single-file visual tool for deriving per-variant IMU-to-camera frame constants in 3D, emitting the `(q_imu2cam, rotate_amount)` pair with human-checkable axis correspondences and a ready-made pytest block. Its presets are pinned to the production tables by test, so tool and code can't drift.
- **`-fb`/`--fakebattery`** (#535): `-fh` alone now emulates rev3 hardware (no battery process, no title-bar icon), keeping docs screenshots on the baseline UI; `-fb` opts into the fake rev4 battery monitor, which runs a full discharge lap including the low-battery warnings and blind-floor shutdown.
- **Battery runtime analysis tool** (`python/tools/battery_runtime_analysis.py`) for fitting the state-of-charge curve from bench discharge logs.
- **~450 new tests** (1,137 unit + smoke passing), including 60 covering the bring-up tool, 46 covering NetworkManager keyfile generation, 117 covering rev4 hardware logic, and field-data regression tests that replay real discharge telemetry through the low-battery warner.
- **The SQM calibration is re-derivable in-repo** (#560): `scripts/evaluate_radiometer_archive.py` now re-fits both the constant and colour models from the sweep archive and judges them by leave-one-night-out error rather than in-sample scatter, which a free parameter always wins. The whole radiometric model is recorded in sweep metadata, so an archived sweep is self-describing rather than needing a constant looked up by camera type.

---

**Version**: 2.6.0 → 2.6.1
**Commits**: 58
**Files changed**: 242 (+26,012 / −5,692); Python: 135 files (+18,467 / −2,125)
