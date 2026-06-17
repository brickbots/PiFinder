# PiFinder v2.6.0 Release Notes

This is one of the largest PiFinder releases ever: a completely new IMU tracking engine with equatorial-mount support, daytime alignment, a quantitative focus aid, catalog image overlays, a rewritten web interface, and major speedups across startup, the chart, and the integrator.

## ⚠️ After You Update

A few one-time actions are needed after installing v2.6.0:

- **Re-run camera/telescope alignment.** The alignment storage format changed (`solve_pixel` → `target_pixel`) and existing alignments are not migrated. Use `Start → Align` under the stars, or the new `Start → Align (Day)` screen in daylight.
- **The first boot after updating is slow** while PiFinder rebuilds its catalog cache and star-chart cache. Every boot after that is dramatically faster than before (see Performance below).
- **If you used T9 search**, re-select it: the old "T9 Search" toggle was replaced by `Settings → User Pref → Search Input` (Multi-Tap / T9). The setting defaults back to Multi-Tap.
- **Changing the UI language** now also translates the web interface (DE/ES/FR), but the web side only switches after a restart.

## New Features

### Equatorial Mount Support & New IMU Tracking Engine (#338, #388, #421)
PiFinder's IMU dead-reckoning was rewritten from the ground up using quaternions in the equatorial frame. The practical wins: **IMU tracking between plate solves now works on equatorial mounts** (set `Settings → Mount Type → Equatorial`), and the **PiFinder no longer needs to be mounted upright** — any mounting angle works as long as the camera points where the scope points. The old "classic" integrator has been removed; the new engine is now the only path. The solver also now attempts to solve every frame instead of skipping frames where the IMU detected motion, so position re-acquisition after a slew is faster.

### Daytime Alignment (#456)
A new `Start → Align (Day)` screen lets you align the camera to your telescope in daylight — no plate solve needed. Center a distant object (a treetop or chimney — far enough away to match night focus) in your eyepiece, then use the keypad corner keys (7/9/1/3) to zero in on that object in the live full-brightness camera view, with single-pixel fine tuning at the end. It writes the same alignment as the night-time solve-based flow, so the two are interchangeable.

### Focus-Quality Indicator (#449)
The Focus screen now shows a quantitative focus aid: a large **HFD readout** (Half-Flux Diameter of the brightest stars, in pixels — lower is sharper) plus a scrolling **V-curve** with a best-focus marker over a rolling 10-second window, along with exposure and star counts. It uses its own star detector tuned to handle big defocused donuts, so it works even when the image is far too defocused to plate-solve. SQUARE toggles the focus strip; the old BG Sub / Gamma display modes and the focus-screen reticle were removed. The display stretch was also reworked to stop frame-to-frame brightness pumping.

### Catalog Image Overlays & Structured Object Sizes (#393, #468)
Object sizes across all catalogs are now structured data (dimensions + position angle) instead of free-form strings, and the object-details survey images gain two overlays: **NSEW cardinal-direction labels** at the field edge, and an **object-size outline** (an ellipse drawn from the cataloged dimensions and position angle) showing the object's full extent — handy when only the bright core is visible in the eyepiece. Both are rotation- and mirror-aware and can be toggled under the new `Settings → Image...` menu.

### Eyepiece-View Image Orientation (#440)
Each telescope's "Flip image" / "Flop image" settings (web Equipment page) are now actually applied to the object-details survey image, so it can match your eyepiece view — including mirror-reversed star-diagonal views. The shipped "Generic Dobsonian" profile had an incorrect flop default; this is fixed and a config migration repairs existing user configs automatically.

### Contrast Reserve (#336)
Object details now show a **contrast reserve** value — a prediction of how visible an object will be in *your* active telescope and eyepiece under *your* current sky brightness (from PiFinder's own SQM measurement). An interpretation ("Easy to see", "Difficult to see", …) joins the description, and a dedicated Contrast page was added to the SQUARE display cycle. Requires an active telescope and eyepiece.

### Chart Orientation Controls (#417, #444)
A new `Settings → Chart... → Coordinate Sys.` setting controls how the chart (and Align screen) is oriented: **Horizontal** (zenith-up, matches the naked-eye sky — the new default), **EQ (Auto)** (north-up or south-up by hemisphere), **EQ (North-up)**, or **EQ (South-up)**. The chart now always labels what's "up" ("Zenith up" / "NCP up" / "SCP up"), and when GPS isn't ready yet it falls back to NCP-up with a bright "!" prefix instead of silently reorienting later. The chart and alignment also now work before GPS lock.

### Manual Date & Location Entry (#402)
PiFinder is now fully usable without a GPS fix. `Tools → Place & Time` gains **Enter Coords** (latitude → longitude → altitude), improved **Load/Save Location** flows, and time entry now chains into a date-entry screen. Manually-set time is protected from being overwritten by GPS.

### SQM Enhancements (#374)
The experimental Sky Quality Meter got an accuracy and tooling overhaul: per-camera calibration (with an improved indoor calibration wizard), better extinction handling, saturated-star rejection, and a richer display showing star count, exposure, and a simplified Bortle class. A crash on opening the SQM screen was fixed.

### Lynga Open Cluster Catalog (#392)
The Lynga Catalogue of Open Cluster Data (5th edition) adds **1,151 open clusters** as a new built-in catalog ("Lynga Opn Cl", code `Lyn`), bringing the total to 21 catalogs.

### Real Planet Names (#390)
Planets now display by name — "Jupiter" instead of "PL 5" on the details screen, and 3-letter abbreviations (JUP, SAT, …) in object lists.

### Search Input Method (#464)
The confusing "T9 Search" on/off toggle is now an explicit choice at `Settings → User Pref → Search Input`: **Multi-Tap** (press a key repeatedly to cycle letters) or **T9** (one press per letter, matched against object names). The Name Search screen's Quick Menu jumps straight to the setting.

### New Web Interface (#331, #410, #418)
The built-in web interface was rewritten from Bottle to Flask + Jinja templates, served by Waitress:

- Web pages are now **translatable** (German, French, Spanish included).
- The **Logs page** now lets you pick a whole logging configuration (default / debug / webserver) or upload your own, then restarts with it — much easier to capture debug logs for bug reports (#410).
- A new **REST API** under `/api/` exposes solve status, location/time, current solution, visible stars, IMU/SQM readings, screen and camera images, and key-press control for external integrations (#418). Endpoints return HTTP 503 with an explanation when data isn't available yet. *Note: API endpoints are unauthenticated — anyone on your network can read state and send key presses.*
- A `/api/current-selection` endpoint and a full Selenium browser-test suite keep the pages tested.

### Resolution-Flexible UI & New Display Support (#452, #453, #454)
The entire on-device UI now renders at the display's native resolution from shared layout geometry instead of assuming 128×128. This adds support for a **176×176 SSD1333 OLED** (for upcoming hardware; selectable via `--display ssd1333`) while keeping the 128×128 SSD1351 pixel-equivalent. As part of this, SSD1351 brightness control was reworked to combine master brightness with per-channel contrast, giving a **noticeably dimmer low end** for better dark adaptation.

### Telemetry Recording & Replay (#411)
A new diagnostic system (`Settings → Experimental → Dev Tools → Telemetry`) can record IMU samples, every plate solve, and target changes to compact session files in `~/PiFinder_data/telemetry/`, then **replay** a session through the integrator with original timing — invaluable for reproducing and debugging field issues on the bench. Your location is stored in a separate sidecar file so sessions can be shared without revealing where you observe.

## Performance

- **~10x faster startup** (#425): the fully-built catalog is cached on disk after first boot — measured end-to-end startup went from ~117 s to ~10 s on a Pi.
- **Smoother chart and UI** (#424): a hidden 10 Hz cap on the UI loop was lifted and the chart render path de-pandas'd — chart updates measured 8.9 → 22.3 Hz; the UI now genuinely hits its ~30 FPS target.
- **16x faster integrator math** (#423): Alt/Az conversion and constellation lookup per integrator tick went from ~1840 µs to ~113 µs using pyerfa. This also *fixed two long-standing accuracy bugs*: the fast LST formula double-counted the fractional day, and atmospheric refraction was missing entirely.
- **Instant Chart/Align screen opening**: the Hipparcos star catalog parse (~1.4 s stall) is now cached.

## Bug Fixes

- **Globular clusters mis-typed as galaxies** (#445): NGC 7006, NGC 2808, NGC 5824, NGC 5834, and NGC 6864 (M 75) were typed as galaxies due to a Roman-numeral parsing ambiguity in the NGC/IC import. Objects database rebuilt.
- **Comet list self-heals** (#391): the periodic comet update now fully rebuilds the catalog, so a comet list initialized with a wrong clock (before GPS lock) corrects itself, and newly bright comets appear without a restart.
- **Malformed comet data tolerated** (#401): a few bad rows in the Minor Planet Center data no longer crash all comet calculations and empty the catalog.
- **Observed filter updates immediately** (#399): objects logged during the current session now show as observed without a restart.
- **Empty log files fixed** (#400): early-startup log messages from the main process are now reliably written to `pifinder.log`, and the web log viewer reads from the correct directory.
- **Stable object name ordering** (#409): multi-name objects (e.g. Bright Stars) no longer shuffle their names between boots; the primary name leads.
- **Filter edge cases** (#431, #432): an empty constellation/type filter now means "show everything" instead of rejecting everything, and zero matching objects no longer crashes the nearby-objects calculation.
- **Stale solve data cleared** (#427, #429): a failed plate solve no longer leaves stale camera-solve data visible; dead-reckoning now explicitly carries the pointing estimate across failed solves instead.
- **Observation logging crash** (#389): logging while the IMU integrator was active could crash on serializing quaternions.
- **Hostname changes update /etc/hosts** (#443, closes #125): renaming your PiFinder no longer breaks `sudo` with "unable to resolve host".
- **Keypad brightness applies immediately** (#430): changing `Settings → User Pref → Key Bright` takes effect the moment you select it.
- **Object-details crash on odd magnitudes** (#438): contrast reserve no longer crashes on double stars ("7.0/9.5"), asterisms, or objects without magnitudes.
- **Marking menus future-proofed** (#398): fixed a construct Python 3.11+ rejects, ahead of future OS upgrades.

## Internationalization

- Complete German, Spanish, French, and Chinese device-UI translations — all 439 strings, no gaps (#434). Translations are AI-generated and tagged for native-speaker review.
- The web interface ships with German, French, and Spanish translations (#331).

## Developer Improvements

- **Solver/Integrator refactor** (#420, #429): the solve pipeline now uses typed dataclasses (`PointingEstimate`, `SolveResult`) end-to-end, and the per-axis dead-reckoners were unified into `ImuDeadReckoning`.
- **Headless remote-control mode** (#435): run PiFinder with `--display headless`, drive it via the API, and stop it cleanly with `POST /api/stop` — plus a Claude Code skill for agent-driven UI testing.
- **UI smoke-test harness** (#438): constructs every screen and sweeps every key handler in CI.
- **Pygame keyboard input** (#397): intuitive keyboard bindings when running with a pygame window (Wayland-compatible).
- **Web test suite** (#331, #413): Selenium browser tests for all web pages, runnable from a GitHub Action.
- **Clean mypy** (#405): type annotations added across the codebase.
- **Agent-experience docs**: bounded-context glossaries (`docs/ax/`), architecture decision records (`docs/adr/`), and authoring skills for docs, i18n, and remote UI driving.

## Hardware & Documentation

- Updated v2.5 case dovetail parts (`dovetail_bottom.stl`, `dovetail_top.stl`); the separate left/right hard-stop variants were removed. Re-download STLs if printing a v2.5 case.
- Major documentation overhaul on pifinder.readthedocs.io: reorganized user guide with a new "Connecting to Your PiFinder" page, a lean-pass rewrite of the manual, a Menu Map of the whole menu system, an SD card swap guide, a Power & Charging section (including LiPo safety), a symptom-indexed Troubleshooting & FAQ, equipment flip/flop documentation, a complete JSON API reference, and Cedar Detect licensing clarification.

---

**Version**: 2.5.1 → 2.6.0
**Commits**: ~81
**Files changed**: ~302 (+171,934 / −7,831 lines, much of it catalog data, translations, and docs; Python code: 189 files, +30,239 / −6,683)
