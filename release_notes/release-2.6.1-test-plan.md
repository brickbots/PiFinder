# PiFinder v2.6.1 — Release Test Plan

Scope: everything on `main` that is not yet on `release` — 58 commits, 242 files,
+26,012 / −5,692 (Python: 135 files, +18,467 / −2,125).

This plan is risk-ordered, not feature-ordered. Each gate has an owner, an explicit
pass criterion, and a note on what a failure blocks. Gates 1–3 must pass before the
`main` → `release` merge; gates 4–6 must pass before the update manifest is published.

**Status as of 2026-07-31** (`main` @ `e87abe49`): pre-flight is clear and Gate 1 is
green. `release` is now an ancestor of `main`, so the cut is a fast-forward with no
conflicts to resolve. The open work is all hardware and sky: G2–G6.

---

## 0. Risk model

What actually changed, ranked by blast radius × likelihood of an undetected defect.

| # | Area | PRs | Blast radius | Why it's risky |
|---|---|---|---|---|
| R1 | Solver / cedar shared memory | #548, #542, #543 | **All users** | Two solve-path regressions shipped inside 2.6.0-era work and weren't caught for weeks. The fix touches the recovery path that only runs when something has already gone wrong. |
| R2 | SQM rebuilt end-to-end | #532, #544, #560, #561 | All users (screen), silent | ~2,800 lines of new photometry. Values on a new scale; a wrong constant looks like a plausible reading. #560 went further than the deferred refit: on bare sensors the published zero point is now a function of the frame's own R/G, so a mis-read Bayer phase biases everyone's SQM without failing. |
| R3 | Focus screen rewrite | #531 | **All users, first night** | Replaces the primary "why won't it solve" tool. Failure mode is a screen that looks fine and reads wrong. |
| R4 | Filter cache + observed identity | #526, #528 | All users, **data-visible** | Retroactively changes what your logs mean. A stale-cache bug shows objects that shouldn't be there (or hides ones that should). |
| R5 | Rev4 enablement | #498, #530, #539, #541, #549, #556, SSD1333 | rev4 only; **can power off the device** | Large new surface. Blind-floor shutdown and the bring-up power hold are deliberate power-off paths. Rev3 must be provably unaffected. |
| R6 | Upgrade path | #548 migration, #539 config aliasing | All updating users | A migration that half-runs, or an unaliased `screen_direction`, bricks the boot. |
| R7 | GPS parsing | #524, #563 | All users | Byte-offset fixes verified on M8 only; M9/M10 path is spec + unit tests. #563 replaced #524's NAV-SAT latch with a 5 s freshness window, so which message source feeds the counts is now time-dependent. |
| R8 | Timezone / manual entry | #508, #512, #563 | Users without GPS lock | Shared-state datetime semantics changed for every consumer. #563 also settles an unresolvable timezone to UTC at `set_location`, which every reader of `Location.timezone` now depends on. |
| R9 | Web interface | #529, #536 | Web users | Both were user-reported 500s / silent failures. |
| R10 | Observing list import | #510, #527 | List users | Lenient parsing — new ways to silently import garbage. |
| R11 | Chart markers | #513 | All users | New per-solve query path; cost and correctness both new. |
| R12 | NixOS migration | #521, #523, #517 | Migrating users only | Destructive by nature. |
| R13 | i18n catalogs | #562 | Non-English users | Full extract/update/compile pass plus 24 newly machine-translated strings per language, and `zh` newly reachable at all. A bad string is cosmetic; a bad *layout* clips a screen. |

---

## 1. Pre-flight — repo housekeeping (before any testing)

**All five pre-flight items are now closed.** Detail below for the record.

- [x] **P1.1 — `main` → `release` merge conflicts resolved.** `e7c16603` merged `release`
  into `main`, taking `main`'s side on the duplicated focus-technique docs (#546 vs #547)
  and reconciling the two add/add CI conflicts (#537/#538 `built_at`, #493/#495 label-gated
  builder). `git merge-tree --write-tree origin/release origin/main` is now clean, and
  `release` is an ancestor of `main` — **the cut is a fast-forward**, not a merge. `.github/`
  is byte-identical between the two branches, so the release workflow that runs post-cut is
  the one already exercised on `release`.
- [x] **P1.2 — ADR 0020 three-way collision resolved.** `0020-soc-as-runtime-fraction.md` keeps the number (most-referenced *and* earliest, 2026-07-17; ADR 0021 amends it and cites `ADR 0020` bare three times, so the battery pair stays contiguous). The two latecomers moved to the lowest globally-free slots, in creation order: `0024-sqm-raw-green-photometry-redesign.md` (was 2026-07-18) and `0025-filter-freshness-staleness-promotion.md` (was 2026-07-23). Six inbound references updated (`sqm/sqm.py`, `tests/test_catalog_filter_cache.py`, `tests/test_observed_identity.py`, `docs/ax/catalog.md` ×2, `docs/ax/catalog/CONTEXT.md`); 140 affected tests pass.
  - **Left alone, flag only:** `0024-sqm-raw-green` now sorts *after* `0022-sqm-radiometer-first`, which describes the later decision. Fixing the order means renumbering 0022 → 0025 too, churning a non-colliding ADR. Say the word if you'd rather have the SQM pair read in order.
  - **Separate, pre-existing collision:** PR #502 (`worktree-object-image-download-docs`) carries `0018-one-object-image-per-object.md`, colliding with `main`'s `0018-civil-datetime-stored-utc-aware.md`. Not part of this release; it'll need resolving when that branch merges. **ADR 0026 is now taken** (#560's sky-colour zero point), so the lowest free slot is **0027**.
- [x] **P1.3 — SQM band-offset refit: landed, and it grew.** Resolved by #560 — but not as P1.3 framed it. Re-deriving from the sweep archive found **neither of #544's quoted refit values reproduces**: the real figures are `imx296` −0.22 → **−0.02** and `hq` 0.60 → **0.99** (imx462, untouched by that refit, re-derives to +0.514 against its shipped +0.53, which is the control that says the method isn't a systematic of the replay). Those are the *stellar diagnostic* offsets.
  - The larger finding was on the published value: a **single** `radiometric_zero_point` per camera is wrong at one end of the sky-brightness range or the other, because the sensor↔V passband conversion depends on the sky's *spectrum*. On bare sensors the zero point is now linear in the frame's measured R/G (imx462/imx290: slope 5.544, pivot 0.85, clamped to 0.83–1.04); mono and IR-cut sensors keep a plain constant, refit (imx462/imx290 15.25 → 15.159, hq 14.79 → 14.971). ADR 0026 carries the evidence.
  - **What this moves rather than closes:** the release no longer ships a known ~0.4 mag imx296 error, but the accuracy claim now rests on a model whose dark-site anchor is one night. See §8 and **G5.5**.
- [x] **P1.4 — Version bump committed.** `2fbc5acc`; `version.txt` reads `2.6.1` on `main`, `2.6.0` on `release`.
- [x] **P1.5 — i18n release pass done.** #562 ran the full extract/update/compile. All four catalogs (de/es/fr/zh) are at **671 msgids, 0 untranslated, 0 fuzzy**, `.mo` files rebuilt and committed. It also fixed three unwrapped user-visible strings (`System Upgrade`, the telemetry replay/queue messages) and — separately — the fact that **`zh` was rejected by `main.py` and the web server despite shipping a complete translation**, so `--lang zh` raised "Unknown language 'zh'" and the web UI could never be Chinese.
  - **Residual, not a blocker:** #562 added 24 machine-translated entries per language, tagged `AI-TRANSLATED (claude): needs human review`. Wordings were checked against the real TTFs and the 128px layout budget (six overflows caught), so the risk is register, not clipping. Note the *standing* total is far larger and predates this release: **de 271, es 372, fr 440, zh 521** of 671 msgids carry that tag — zh is 78% unreviewed machine translation. Not a 2.6.1 regression and not a blocker, but it's the honest state of the catalogs, and zh is newly reachable this release. See **G2.36**.

---

## 2. Gate 1 — Automated (CI, ~15 min)

Run on the merge result, not on `main` alone. Since P1.1 that *is* `main` — the cut is a
fast-forward, so there is no separate merge result to test.

```bash
cd python/
source .venv/bin/activate
git submodule update --init PiFinder/tetra3   # mypy + solver tests need this
nox -s lint
nox -s format
nox -s type_hints
nox -s smoke_tests
nox -s unit_tests
```

**Gate 1 is green on `main` @ `e87abe49`** (macOS dev venv, Python 3.9, 2026-07-31).

- [x] **G1.1** Ruff lint + format clean — `All checks passed`, 246 files already formatted.
- [x] **G1.2** MyPy clean — `no issues found in 147 source files` (needs the `tetra3` submodule initialised; a stale `.mypy_cache` reports a phantom error, so clear it if the count disagrees).
- [x] **G1.3** `pytest -m "smoke or unit"` — **1,137 passed, 0 failures** (was 1,100 @ `8c813f94`; +37 from #560/#561/#563). A materially lower count means test collection broke somewhere. *Note: #531 and #556 each reported local failures (comet/Skyfield and `TestPedestalOverride` respectively) on contributor machines with newer NumPy/Skyfield; neither reproduces here.*
- [x] **G1.4** New suites confirmed running, not skipping — **349 passed, 0 skipped** across `test_solver_cedar_client.py`, `test_sqm.py`, `test_focus_preview.py`, `test_catalog_filter_cache.py`, `test_observed_identity.py`, `test_battery_low_battery.py`, `test_bringup.py`, `test_nixos_migration_wifi.py`, `test_gps_ubx_parser.py`, plus the new `test_radiometer.py`, `test_radiometric_fit.py`, `test_sweep_frame_record.py`, `test_gps_ubx_dispatch.py`, `test_time_date_gate.py`.
- [x] **G1.5** Docs build clean — `sphinx -nW -b html docs/source <out>` succeeds, 17 pages, no warnings. *(Needs `pip install -r docs/source/requirements.txt`; `sphinxcontrib-mermaid` and `sphinx_rtd_theme` are not in the app venv by default.)*

**Blocks:** everything. **Re-run G1.1–G1.5 if anything further lands on `main` before the cut.**

---

## 3. Gate 2 — Bench, rev3 hardware (the population that upgrades)

**This is the most important gate.** Almost every user of 2.6.1 will be on rev3, and
almost every new line of code in this release was written for rev4. The question this
gate answers is: *is rev3 provably unaffected?*

Run on a real rev3 unit, updated in place from 2.6.0 (see Gate 4 for the upgrade
itself). Indoors is fine for most of it; use `Tools → Test Mode` for a solvable frame.

### Solver / shared memory (R1) — highest priority

- [x] **G2.1** Boot, confirm solving on the test image, then **SSH in and log out**. Solving must continue. Re-check 60 s later. *This is the #548 regression; before the fix, solving dies permanently at logout.*
- [x] **G2.2** `grep -c "cedar_detect_image" ~/PiFinder_data/logs/pifinder.log` after G2.1 — expect no runaway repetition (2.6.0 produced ~28,000/night).
- [x] **G2.3** Confirm the drop-in landed: `cat /etc/systemd/logind.conf.d/pifinder-removeipc.conf` → `RemoveIPC=no`.
- [x] **G2.4** Kill `cedar-detect-server` mid-session; confirm the solver recovers when it comes back (self-healing from 2.6.0 still works).
- [x] **G2.5** `Tools → Test Mode` toggles: Focus and Align (Day) must pin to the disk test image, and the solver must solve it. Toggle off — live captures return. *#543 restored this; verify both directions.*

### Focus screen (R3)

- [x] **G2.6** Open `Start → Focus`. Four star tiles populate; the same stars hold their quadrants as the image shifts.
- [x] **G2.7** **SQUARE** cycles Stars → Single → Image → Stats and wraps. No crash, no blank frame, title bar intact in every view.
- [x] **G2.8** **+/−** moves magnification across the full 4x–16x range without clipping edge stars or exceeding the sensor frame.
- [ ] **G2.9** Deliberately defocus hard: tiles widen automatically, HFD shows `?.?` rather than a wrong number or a crash, and recovers as focus improves.
- [ ] **G2.10** Real focus sweep with the lens: HFD falls to a minimum and rises again, and the 10 s trace matches. **Record the minimum HFD and compare with the value 2.6.0 reported on the same optics** — a large discrepancy means the new detector is mis-scaled.
- [x] **G2.11** Stats view: FWHM, star count, exposure, gain, and histogram all populate and update.
- [ ] **G2.12** Long-press SQUARE opens the Quick Menu (Exposure) from every view.

### Filters and observed status (R4)

Use a unit with a **real observation history** — this test is meaningless on an empty DB. Back up `~/PiFinder_data/observations.db` first.

- [ ] **G2.13** Before updating, record the count of an "Observed: No" NGC list. After updating, the count should **drop** (sibling derivation) — and the objects that disappeared must be exactly those whose Messier/Collinder sibling was logged.
- [ ] **G2.14** A sibling listing (e.g. NGC 224 when M 31 is logged) shows the observed checkmark and its details show the combined log count.
- [ ] **G2.15** Log an object from an "Observed: No" list with the list open. It disappears on refresh **and the cursor lands on the next object**, not the top of the list.
- [ ] **G2.16** Log a planet. Confirm no *other* planet gains a checkmark (virtual objects keep per-listing identity).
- [ ] **G2.17** Set an altitude filter, leave the list open, and confirm it refreshes as the sky rotates (600 s TTL) rather than freezing.
- [ ] **G2.18** Cold boot with the altitude filter active: before GPS lock everything passes; **the moment the fix lands the list must refilter.** *This closed a real 2.6.0 gap where pre-lock verdicts stuck forever.*
- [ ] **G2.19** Timing: open the NGC list four times in a row. **Second and subsequent opens must be effectively instant** (#526 took this from ~0.58 s). Then change a filter parameter and confirm the next open re-filters correctly.
- [ ] **G2.20** Filter → Type: labels read `Planetary`, `Double star`, `Triple star`, `Cluster + Neb`, `Unkn`. Selections still apply correctly (the value codes are unchanged).

### Chart (R11)

- [x] **G2.21** Open an object's details, then the chart: a bright cross marks it, labelled with its designator.
- [x] **G2.22** Steer away until it's off-field: the label goes, a rim arrow points to it.
- [x] **G2.23** Set `Chart... → DSO Display` to 0: **the target cross must stay bright** while the nearby markers vanish.
- [x] **G2.24** Zoom in and out: fainter objects appear as you zoom in, only the brightest survive at 60°, and the field never crowds.
- [x] **G2.25** Load an observing list: its markers and the nearby markers don't double-draw the same object.
- [x] **G2.26** Watch the chart FPS across a slew — the nearby-object index must not be rebuilding per frame.

### SQM (R2)

- [ ] **G2.27** Open SQM. A value appears **without a plate solve** (cover the lens or point at the ceiling) — this is the radiometer-first path.
- [ ] **G2.28** The screen shows as **uncalibrated** after the update (expected — the calibration filename changed). Run `SQM → CALIB`; the wizard completes, ~30–40 s longer than in 2.6.0 (clamp-settle discards), and the screen then shows calibrated.
- [ ] **G2.29** `SQM → SWEEP` runs the diagnostic exposure sweep to completion and writes its archive. *New in #561:* each frame record must carry `settle_frames` (expect ~3 on an IMX290/462) and `sqm_details_frozen`, and the recorded `radiometer_sample` exposure must **match the frame's own label** rather than the previous sweep step. If the log shows "Exposure did not settle … after 8 frames", the sweep archive is untrustworthy on that sensor — capture the log.
- [ ] **G2.30** Confirm the marking menu reads `CALIB` / `SWEEP`.
- [ ] **G2.30a** *(#560, colour-keyed zero point — imx462/imx290 only.)* Confirm the published SQM still tracks sensibly across a real brightness range, and check the radiometer details in a sweep archive: `radiometric_zero_point_effective` is always present, and on a colour sensor `sky_red_over_green` / `sky_red_over_green_clamped` should appear too. **Their absence means the correction didn't apply** — the mosaic-phase guard rejected the frame, and the reading fell back to the profile constant. That fallback is the safe behaviour, but if it happens on every frame the colour model is doing nothing on that unit and the reading is off at a dark site. The failure mode here is a *plausible* value up to the clamp width wrong, so these fields are the only visible evidence.

### Everything else on rev3

- [x] **G2.31** Status screen shows `GPS LCK` (not `GPS LST`), and `LCL TM` / `UTC TM` **differ** by your UTC offset. *In 2.6.0 they were identical after manual entry.*
- [ ] **G2.32** With no location fix, `Tools → Place & Time → Set Time/Date` opens and shows "Set location first"; LEFT backs out. Digits do nothing. Then set a location — with the screen still open, the entry boxes must appear **live**.
- [ ] **G2.33** With a fix, set a time and date; both are accepted, and the chained date screen pre-fills the correct day (not ±24 h). The zone note under the digits must **name a timezone** — and on a location whose zone can't be resolved from its coordinates (mid-ocean, or a manually entered lat/lon in a gap), it must read `UTC` and **committing the time must not crash**. *#563: before the fix the screen rendered and the commit raised `UnknownTimeZoneError`.*
- [ ] **G2.33a** GPS satellite counts on the Status screen (#563): seen must never be **below** used — no `0/9` — and the counts must keep updating for the whole session. *Before the fix, one NAV-SAT message froze them for the life of the connection.* Leave it running long enough to be sure the numbers still move.
- [x] **G2.34** **No battery icon in the title bar and no sounds.** Confirm neither a Battery nor a Sound process appears in the startup log. Note that `Settings → User Pref → Volume` is present unconditionally — verify it is harmless on rev3 (settable, no audible effect, no crash).
- [x] **G2.35** Confirm the display brightness range is unchanged on the SSD1351 (the three-axis rework is SSD1333-only).
- [x] **G2.36** **Languages (#562).** Switch the UI through de, es, fr and **zh** — zh is newly reachable and has never been exercised in the app. Walk the screens that gained strings this release (Focus views, SQM, User Pref → Volume, Advanced → PiFinder Type, Software Update, low-battery popups) and check nothing clips or overflows on the 128px display. **Known and accepted:** Chinese marking-menu labels render as overlapping glyphs — a pre-existing renderer bug (`Font.width` derived from Latin `M`), not a catalog bug, and out of scope for the cut.

**Blocks:** the release. Any failure here affects the majority of users. G2.36 blocks only
the non-English experience — a clipping bug there is a `.po` fix, not a code change.

---

## 4. Gate 3 — Bench, rev4 hardware

Needs a real rev4 board. If none is available, see §8 — the rev4 features must then be
explicitly declared untested in the release notes.

- [x] **G3.1** `python -m PiFinder.bringup` on a freshly provisioned card: pre-flight reports i2c-1 and both PWM channels; SCREEN/BACKLIGHT/BUZZER emit; IMU and CHARGER report PASS; SWITCHES observes **every** populated matrix position. *Buzzer output is confirmed working on hardware given a correctly provisioned card — the open item is `pifinder_setup.sh`, which provisions only the single-channel `pwm` overlay, so a fresh install would report `pwm ch0 -> gpio12 NOT ROUTED` and be silent with no error. The setup-script fix is a deliberate follow-up, not part of 2.6.1.*
- [x] **G3.2** ~~Confirm the rev4 population map~~ — **confirmed on hardware** (2026-07-30). `REV4_POPULATED` as shipped is correct; no further check needed.
- [x] **G3.2a** Bring-up **power hold**: a tap of the power switch registers the closure for `SWITCHES` and nothing else; a hold fills the `PWR` bar over one second, plays the SHUTDOWN earcon, shows `SHUTTING DOWN`, and cleanly shuts the card down. Confirm `--no-power-shutdown` removes the gesture while a tap still counts. *#556 was not exercised on a board — the gesture shuts the machine down, so this is bench-only verification.*
- [x] **G3.2b** Confirm `sudo shutdown now` works passwordless on the bring-up card. Without it the run reports the non-zero exit rather than swallowing it, but the builder would otherwise read `SHUTTING DOWN` on a board that is still up.
- [rx **G3.3** Battery icon in the title bar tracks charge; plugging in the charger shows the bolt glyph.
- [x] **G3.4** Earcons play; `Settings → User Pref → Volume` changes level audibly and `Off` silences them.
- [x] **G3.5** Power button: first press opens the shutdown confirmation, second press confirms, shutdown earcon plays **before** the power latch fires, and the unit powers off.
- [x] **G3.6** **`reboot` must come back up, not power off.** *ADR 0007 calls this out explicitly — the `gpio-poweroff` latch is the one change here that can leave a unit dead on a reboot.*
- [x] **G3.7** SSD1333 display: boot splash renders at 176×176, no rotation artifacts, all screens laid out correctly.
- [x] **G3.8** SSD1333 brightness: sweep the full UI range in a dark room. The dimmest setting must be genuinely dim (the point of the change) and the brightest must not bloom. Confirm no blanking mid-range, and that settings at or above 0.35% keep visible tonal range.
- [x] **G3.9** Each of the five build variants (`AS Bloom`, `AS Heart`, `Rev4 Left/Right/Straight`) selected in `Settings → Advanced → PiFinder Type`: after the restart, IMU dead-reckoning must move the reticle in the **correct direction** for a physical nudge in each axis. *(#530's PR checkboxes record hardware verification as done; re-confirm at least the variant matching the test unit.)*
- [ ] **G3.10** **Low-battery, full discharge run.** Run the unit off battery to shutdown: exactly **one** 10% warning and **one** 5% warning (2.6.0-era code fired ~90 times), then the blind-floor final warning and a clean software shutdown. Verify the card is not corrupted afterward.
- [ ] **G3.11** Plug in the charger mid-discharge, then unplug: the warnings must re-arm for the next discharge, and only for a charger event.
- [ ] **G3.12** Confirm the low-battery shutdown never fires while on external power.

**Blocks:** any rev4 claim in the release notes. Does not block a rev3-only release.

---

## 5. Gate 4 — Upgrade path and fresh install

- [ ] **G4.1** **In-place update from 2.6.0 on a real unit.** The `v2.6.1` migration runs once, writes `/etc/systemd/logind.conf.d/pifinder-removeipc.conf`, `try-restart`s logind, and touches `~/PiFinder_data/migrations/v2.6.1`.
- [ ] **G4.2** Run the update **again**. The migration must not re-run (marker file present) and nothing must break.
- [ ] **G4.3** Update a unit with a **pre-release rev4 config** carrying `screen_direction: v4_left` (or `v4_right`/`v4_straight`). It must boot — the alias in `Config.load_config` is the only thing standing between those units and a `ValueError` crash in `ImuDeadReckoning`.
- [ ] **G4.4** Update a unit carrying every 2.6.0 setting you can set (equipment, filters, locations, observing lists, SQM calibration, telescope flip/flop). Nothing lost, nothing reset except the SQM calibration indicator.
- [ ] **G4.5** Fresh install from `pifinder_setup.sh` on rev3: confirm the `gpio-poweroff` overlay and serial-console removal are applied (they are unconditional, per ADR 0007) and that the unit still boots, still has working PWM keypad backlight, and that nothing depended on the serial console.
- [ ] **G4.6** Confirm existing observation logs are intact and the retroactive sibling derivation didn't mutate the database (log entries are still stored per `(catalog, sequence)`; only the derived cache changed).

**Blocks:** publishing the update manifest.

---

## 6. Gate 5 — Under the stars

Nothing above substitutes for this. Minimum: one clear night, one rev3 unit, one
observer who didn't write the code.

- [ ] **G5.1** **Cold-start to first solve, following the Quick Start as written.** Time it. The rewritten focus section is the release's biggest UX bet — if a competent user can't reach focus from the new instructions, that's a docs bug worth blocking on.
- [ ] **G5.2** Focus by HFD alone, then verify the solve confirms it. Check the small-turn technique described in the docs actually matches the screen's responsiveness.
- [ ] **G5.3** Full observing session ≥ 2 hours: push-to a dozen objects across the sky, log several, and confirm nothing degrades — solve rate, chart responsiveness, memory, CPU.
- [ ] **G5.4** **SQM through the night.** Take readings hourly and at several different auto-exposure levels. The value must **not** wander with exposure (2.6.0 swung 0.7–2.4 mag). Refocus mid-session and confirm the reading barely moves (target: ~0.03 mag).
- [ ] **G5.5** **SQM against a hand-held reference meter** — now the highest-value item in this gate. P1.3 is closed, but #560's zero point is a *model* fitted mostly on light-polluted nights with a single dark-site anchor, so this is the measurement that says whether it holds. Run `SQM → SWEEP` alongside the meter, record the reading pair, and keep the archive: `scripts/evaluate_radiometer_archive.py` re-derives and cross-validates both models from it. Most valuable, in order: **a dark site** (the model is extrapolating there off one night), **an imx296** (mono — can't use the colour model at all, and its constants come from four sweeps by one observer), and **an imx290** (constants mirrored from the imx462 with no sweeps of its own).
- [ ] **G5.6** SQM keeps updating through a cloud bank and through failed solves.
- [ ] **G5.7** Chart nearby markers under real sky: do they match what's actually there, and does the magnitude limit feel right at 5°, 20°, and 60°? *These endpoints were shipped as "starting values to tune on-device."*
- [ ] **G5.8** Polar Align following the **revised** guidance (near-pole aim, 30–45° RA sweep, Roll Off on an EQ mount): does it converge, and is the 20–30 arcmin accuracy claim honest?
- [ ] **G5.9** Observe with the target cross visible and confirm it tracks the last-viewed object as expected, not push-to.
- [ ] **G5.10** GPS: confirm the satellite counts on the Status screen are now plausible (`nSat`/`uSat`) rather than the old inflated `20/0`. **Test on an M9 or M10 module if one is available** — that path is verified against the spec and unit tests only.

**Blocks:** the release. This is a hardware product; a green CI run is not evidence.

---

## 7. Gate 6 — Web interface and API

Requires a Selenium Grid at `localhost:4444` (the suite self-skips without one, and
does **not** run in CI).

```bash
nox -s web_tests
```

- [ ] **G6.1** Full Selenium suite passes on desktop (1920×1080) and mobile (375×667) viewports.
- [ ] **G6.2** **Manual, in a comma-decimal browser locale** (set Chrome to e.g. German): add a location with `51,3` and with `51.3`. Both must save. Repeat on the edit form and the DMS fields. *The Selenium suite runs en-US and structurally cannot catch this — it's how #536 shipped.*
- [ ] **G6.3** DeepskyLog equipment import with a payload containing **new** eyepieces: they're added, sorted by focal length, and telescopes in the same request are saved too. Then re-import: no duplicates.
- [ ] **G6.4** `/api/` endpoints still respond (solve status, current selection, screen, camera image, key press), including the 503-with-explanation path before data is available.
- [ ] **G6.5** Confirm the remote-nav key sequences still match the menu layout — #492 fixed 16 tests that broke on menu index shifts, and this release adds `Volume` under User Pref and four PiFinder Type entries.

**Blocks:** the release for web users; not the on-device experience.

---

## 8. Known gaps and accepted risk

State these explicitly at sign-off rather than discovering them in the field.

| Gap | Status | Mitigation |
|---|---|---|
| `sqm_band_offset` refit | **Closed — P1.3.** Landed in #560, at values #544's text got wrong (imx296 −0.02, not +0.21; hq 0.99, not 0.43). | Done. |
| HQ band offset is fitted, not physical | The IR-cut implies ~0, yet 0 puts the stellar SQM ~1 mag bright, so 0.99 is absorbing an unaccounted-for magnitude somewhere in the HQ stellar chain. Sweep-to-sweep scatter 0.67 mag ⇒ treat as 0.99 ± 0.2. | Diagnostic path only — the published value doesn't use it. Documented in the profile comment; refit rather than transfer the number if the real error is found. |
| imx462 colour model's dark-site anchor | **A single night** (`20260720`). Cross-validation says it extrapolates rather than interpolates (0.944 → 0.312 held out), which is the reason to believe it, but one night is one night. | **G5.5** at a dark site. Ship-and-measure; the model degrades to roughly the old constant's behaviour at LP sites, so the downside is bounded. |
| SQM absolute anchoring | Materially better than at 2.6.0 — imx462 median +0.005 over 23 sweeps, hq +0.000 over 11 — but derived from two observers' sites. | Keep collecting reference pairs (**G5.5**); not a blocker. |
| `imx290` SQM constants | Mirrored from imx462 (incl. the colour slope), no sweeps of its own | Flag as provisional. |
| `imx296` SQM constants | Radiometric zero point untouched by #560; band offset from **4 sweeps, one night, one observer**. Mono, so it cannot use the colour model at all. | Flag as provisional. |
| Unreviewed machine translation across all four catalogs | Standing, pre-dates 2.6.1: **de 271 / es 372 / fr 440 / zh 521** of 671 msgids tagged `AI-TRANSLATED (claude): needs human review` (#562 added 24 of them). Layout was checked against real fonts, so the risk is register, not clipping. | **G2.36**; native-speaker passes as contributors are found. zh matters most — it's newly reachable this release and the least reviewed. |
| zh marking-menu glyphs overlap | Pre-existing renderer bug: `Font.width` is derived from Latin `M` (7px) while CJK glyphs advance 15px, so `char_angle` in `marking_menus.py` comes out ~2.3× too tight. Affects every already-shipped zh label. | Deliberately out of scope — the fix changes arc geometry for all languages. Note in the release notes if zh is promoted as newly working. |
| SOC_LUT knots | Provisional, pending pinned-load confirmation runs | Follow-up PR after the campaign; conservative enough to shut down safely. |
| GPS NAV-PVT / NAV-SAT path | Spec + unit tests only, no M9/M10 hardware. #563's freshness window and seen ≥ used floor are likewise unit-tested only. | **G5.10** and **G2.33a** if a module can be found; otherwise ship and solicit field reports. |
| SQM sweep exposure settle (#561) | Verified against the IMX290/462's three-frame behaviour; the IMX477 half-exposure transitional case is reasoned, not measured. | **G2.29** — check `settle_frames` and watch for the "did not settle" warning. Diagnostic archives only. |
| rev4 buzzer PWM routing | **Buzzer confirmed working on hardware** with a correctly provisioned card. `pifinder_setup.sh` still provisions only `pwm` (1-chan), not `pwm-2chan`, so a fresh install is silent with no error. | Maintainer is fixing the setup script and build instructions as a **follow-up after 2.6.1**. Note it in the release notes if fresh-install cards are cut from this release. |
| rev4 population map (18 vs 22 switches) | **Confirmed on hardware 2026-07-30** — `REV4_POPULATED` as shipped is correct. | Closed. |
| Bring-up power hold (#556) | Not exercised on a board (the gesture shuts the machine down) | **G3.2a/G3.2b**. |
| `serial-getty` mask targets `ttyAMA0` | Unconfirmed vs `ttyS0` on the target Pi model | **G4.5**. |
| Chart magnitude-limit endpoints and 0.75× FOV radius | Shipped as tuning starting values | **G5.7**; tune in a follow-up. |
| Selenium web suite not in CI | By design (needs external Grid) | **G6.1** run manually at release time. |

---

## 9. Sign-off

| Gate | Owner | Hardware needed | Est. | Status |
|---|---|---|---|---|
| P1 Pre-flight | maintainer | none | 1 h | ☑ **done** (2026-07-31) |
| G1 Automated | CI | none | 15 min | ☑ **green** @ `e87abe49` |
| G2 Bench rev3 | | rev3 unit + observation history | 3–4 h | ☐ |
| G3 Bench rev4 | | rev4 board + battery | 3 h + discharge run | ☐ |
| G4 Upgrade path | | 2.6.0 unit, spare card | 2 h | ☐ |
| G5 Under the stars | field tester | rev3 unit, clear night, SQM meter | 1 night | ☐ |
| G6 Web / API | | Selenium Grid | 1 h | ☐ |

**Release criteria:** P1, G1, G2, G4, G5 all green. G3 green *or* rev4 explicitly
declared untested in the release notes. G6 green *or* web changes reverted.

**Everything remaining needs hardware or sky.** No repo-side work stands between here
and the cut; the critical path is a rev3 bench pass (G2), an upgrade-from-2.6.0 run (G4),
and one clear night (G5).

**Post-cut:** the NixOS release workflow, migration tarball, and manifest population
(#514, #515, #516, #519, #522) have never run against this content. They are now identical
on both branches — `.github/` is byte-for-byte the same on `main` and `release` — so what
runs post-cut is what `release` already carries. Watch the first release build for the 2 GB
RAM budget check (#522); the migration tarball has grown. Note also that **PR #558 is open
against `main`** — it fixes the testable-PR builder checking out the default branch's
scripts instead of the PR's base. It touches only `nixos-pr-build.yml`, not `release.yml`,
so it neither blocks nor helps this cut, but merging it after the cut will be cleaner than
during.
