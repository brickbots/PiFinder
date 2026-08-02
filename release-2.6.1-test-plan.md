# PiFinder v2.6.1 — Release Test Plan

Scope: everything on `main` that is not yet on `release` — 50 commits, 238 files,
+21,830 / −3,297 (Python: 131 files, +17,082 / −2,095).

This plan is risk-ordered, not feature-ordered. Each gate has an owner, an explicit
pass criterion, and a note on what a failure blocks. Gates 1–3 must pass before the
`main` → `release` merge; gates 4–6 must pass before the update manifest is published.

---

## 0. Risk model

What actually changed, ranked by blast radius × likelihood of an undetected defect.

| # | Area | PRs | Blast radius | Why it's risky |
|---|---|---|---|---|
| R1 | Solver / cedar shared memory | #548, #542, #543 | **All users** | Two solve-path regressions shipped inside 2.6.0-era work and weren't caught for weeks. The fix touches the recovery path that only runs when something has already gone wrong. |
| R2 | SQM rebuilt end-to-end | #532, #544 | All users (screen), silent | ~1,600 lines of new photometry. Values on a new scale; a wrong constant looks like a plausible reading. |
| R3 | Focus screen rewrite | #531 | **All users, first night** | Replaces the primary "why won't it solve" tool. Failure mode is a screen that looks fine and reads wrong. |
| R4 | Filter cache + observed identity | #526, #528 | All users, **data-visible** | Retroactively changes what your logs mean. A stale-cache bug shows objects that shouldn't be there (or hides ones that should). |
| R5 | Rev4 enablement | #498, #530, #539, #541, #549, #556, SSD1333 | rev4 only; **can power off the device** | Large new surface. Blind-floor shutdown and the bring-up power hold are deliberate power-off paths. Rev3 must be provably unaffected. |
| R6 | Upgrade path | #548 migration, #539 config aliasing | All updating users | A migration that half-runs, or an unaliased `screen_direction`, bricks the boot. |
| R7 | GPS parsing | #524 | All users | Byte-offset fixes verified on M8 only; M9/M10 path is spec + unit tests. |
| R8 | Timezone / manual entry | #508, #512 | Users without GPS lock | Shared-state datetime semantics changed for every consumer. |
| R9 | Web interface | #529, #536 | Web users | Both were user-reported 500s / silent failures. |
| R10 | Observing list import | #510, #527 | List users | Lenient parsing — new ways to silently import garbage. |
| R11 | Chart markers | #513 | All users | New per-solve query path; cost and correctness both new. |
| R12 | NixOS migration | #521, #523, #517 | Migrating users only | Destructive by nature. |

---

## 1. Pre-flight — repo housekeeping (before any testing)

These are known and will bite at merge time.

- [ ] **P1.1 — Resolve the four `main` → `release` merge conflicts.** `git merge-tree --write-tree origin/release origin/main` reports:
  - `docs/source/quick_start.rst` and `docs/source/troubleshooting.rst` — #546 (main) vs #547 (release) are the *same* focus-technique docs applied twice. Take `main`'s version; it also carries the #531 Focus rewrite that release doesn't have.
  - `.github/scripts/update_manifest.py` — #537 (main) vs #538 (release), add/add of the same `built_at` change.
  - `.github/workflows/nixos-pr-build.yml` — #493 (main) vs #495 (release), add/add of the same label-gated builder.
- [x] **P1.2 — ADR 0020 three-way collision resolved.** `0020-soc-as-runtime-fraction.md` keeps the number (most-referenced *and* earliest, 2026-07-17; ADR 0021 amends it and cites `ADR 0020` bare three times, so the battery pair stays contiguous). The two latecomers moved to the lowest globally-free slots, in creation order: `0024-sqm-raw-green-photometry-redesign.md` (was 2026-07-18) and `0025-filter-freshness-staleness-promotion.md` (was 2026-07-23). Six inbound references updated (`sqm/sqm.py`, `tests/test_catalog_filter_cache.py`, `tests/test_observed_identity.py`, `docs/ax/catalog.md` ×2, `docs/ax/catalog/CONTEXT.md`); 140 affected tests pass.
  - **Left alone, flag only:** `0024-sqm-raw-green` now sorts *after* `0022-sqm-radiometer-first`, which describes the later decision. Fixing the order means renumbering 0022 → 0025 too, churning a non-colliding ADR. Say the word if you'd rather have the SQM pair read in order.
  - **Separate, pre-existing collision:** `origin/worktree-object-image-download-docs` carries `0018-one-object-image-per-object.md`, colliding with `main`'s `0018-civil-datetime-stored-utc-aware.md`. Not part of this release; it'll need resolving when that branch merges. Lowest free slot is now 0026.
- [ ] **P1.3 — Decide the SQM band-offset refit.** #544's cross-device validation measured a **constant** residual on two sensors that its own PR deliberately left out: `imx296` −0.43 (refit `sqm_band_offset` −0.22 → **+0.21**) and `hq` +0.17 (refit 0.60 → **0.43**). `main` still ships the pre-refit values. **Either land the refit before the cut, or ship knowing imx296 reads ~0.4 mag low and HQ ~0.2 mag high against a reference meter.** This is a one-line-per-profile change in `python/PiFinder/sqm/camera_profiles.py`.
- [ ] **P1.4 — Commit the version bump.** `version.txt` (2.6.0 → 2.6.1) is currently an uncommitted working-tree change.
- [ ] **P1.5 — i18n check.** Four `.po` catalogs gained strings in #541 by hand rather than via `nox -s babel`. Confirm `Volume`, `Off`, and the two low-battery strings are present and compiled in de/es/fr/zh, and that #517's "No release found" string is wrapped. (Per project practice: scope to the tracked `.po` diff; `messages.pot` is gitignored.)

---

## 2. Gate 1 — Automated (CI, ~15 min)

Run on the merge result, not on `main` alone.

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

- [ ] **G1.1** Ruff lint + format clean.
- [ ] **G1.2** MyPy clean (needs the `tetra3` submodule initialised).
- [x] **G1.3** `pytest -m "smoke or unit"` — **1,100 passed, 0 failures** on `main` @ `8c813f94` (macOS dev venv, Python 3.9, 17 s). A materially lower count means test collection broke somewhere. *Note: #531 and #556 each reported local failures (comet/Skyfield and `TestPedestalOverride` respectively) on contributor machines with newer NumPy/Skyfield; neither reproduces here. Re-run on the merge result.*
- [ ] **G1.4** Spot-check that the new suites actually ran and aren't all skipping: `test_solver_cedar_client.py`, `test_sqm.py`, `test_focus_preview.py`, `test_catalog_filter_cache.py`, `test_observed_identity.py`, `test_battery_low_battery.py`, `test_bringup.py`, `test_nixos_migration_wifi.py`, `test_gps_ubx_parser.py`.
- [ ] **G1.5** Docs build: `sphinx-build -nW -b html docs/source <out>` clean (nitpicky, warnings-as-errors).

**Blocks:** everything.

---

## 3. Gate 2 — Bench, rev3 hardware (the population that upgrades)

**This is the most important gate.** Almost every user of 2.6.1 will be on rev3, and
almost every new line of code in this release was written for rev4. The question this
gate answers is: *is rev3 provably unaffected?*

Run on a real rev3 unit, updated in place from 2.6.0 (see Gate 4 for the upgrade
itself). Indoors is fine for most of it; use `Tools → Test Mode` for a solvable frame.

### Solver / shared memory (R1) — highest priority

- [ ] **G2.1** Boot, confirm solving on the test image, then **SSH in and log out**. Solving must continue. Re-check 60 s later. *This is the #548 regression; before the fix, solving dies permanently at logout.*
- [ ] **G2.2** `grep -c "cedar_detect_image" ~/PiFinder_data/logs/pifinder.log` after G2.1 — expect no runaway repetition (2.6.0 produced ~28,000/night).
- [ ] **G2.3** Confirm the drop-in landed: `cat /etc/systemd/logind.conf.d/pifinder-removeipc.conf` → `RemoveIPC=no`.
- [ ] **G2.4** Kill `cedar-detect-server` mid-session; confirm the solver recovers when it comes back (self-healing from 2.6.0 still works).
- [ ] **G2.5** `Tools → Test Mode` toggles: Focus and Align (Day) must pin to the disk test image, and the solver must solve it. Toggle off — live captures return. *#543 restored this; verify both directions.*

### Focus screen (R3)

- [ ] **G2.6** Open `Start → Focus`. Four star tiles populate; the same stars hold their quadrants as the image shifts.
- [ ] **G2.7** **SQUARE** cycles Stars → Single → Image → Stats and wraps. No crash, no blank frame, title bar intact in every view.
- [ ] **G2.8** **+/−** moves magnification across the full 4x–16x range without clipping edge stars or exceeding the sensor frame.
- [ ] **G2.9** Deliberately defocus hard: tiles widen automatically, HFD shows `?.?` rather than a wrong number or a crash, and recovers as focus improves.
- [ ] **G2.10** Real focus sweep with the lens: HFD falls to a minimum and rises again, and the 10 s trace matches. **Record the minimum HFD and compare with the value 2.6.0 reported on the same optics** — a large discrepancy means the new detector is mis-scaled.
- [ ] **G2.11** Stats view: FWHM, star count, exposure, gain, and histogram all populate and update.
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

- [ ] **G2.21** Open an object's details, then the chart: a bright cross marks it, labelled with its designator.
- [ ] **G2.22** Steer away until it's off-field: the label goes, a rim arrow points to it.
- [ ] **G2.23** Set `Chart... → DSO Display` to 0: **the target cross must stay bright** while the nearby markers vanish.
- [ ] **G2.24** Zoom in and out: fainter objects appear as you zoom in, only the brightest survive at 60°, and the field never crowds.
- [ ] **G2.25** Load an observing list: its markers and the nearby markers don't double-draw the same object.
- [ ] **G2.26** Watch the chart FPS across a slew — the nearby-object index must not be rebuilding per frame.

### SQM (R2)

- [ ] **G2.27** Open SQM. A value appears **without a plate solve** (cover the lens or point at the ceiling) — this is the radiometer-first path.
- [ ] **G2.28** The screen shows as **uncalibrated** after the update (expected — the calibration filename changed). Run `SQM → CALIB`; the wizard completes, ~30–40 s longer than in 2.6.0 (clamp-settle discards), and the screen then shows calibrated.
- [ ] **G2.29** `SQM → SWEEP` runs the diagnostic exposure sweep to completion and writes its archive.
- [ ] **G2.30** Confirm the marking menu reads `CALIB` / `SWEEP`.

### Everything else on rev3

- [ ] **G2.31** Status screen shows `GPS LCK` (not `GPS LST`), and `LCL TM` / `UTC TM` **differ** by your UTC offset. *In 2.6.0 they were identical after manual entry.*
- [ ] **G2.32** With no location fix, `Tools → Place & Time → Set Time/Date` opens and shows "Set location first"; LEFT backs out. Digits do nothing. Then set a location — with the screen still open, the entry boxes must appear **live**.
- [ ] **G2.33** With a fix, set a time and date; both are accepted, and the chained date screen pre-fills the correct day (not ±24 h).
- [ ] **G2.34** **No battery icon in the title bar and no sounds.** Confirm neither a Battery nor a Sound process appears in the startup log. Note that `Settings → User Pref → Volume` is present unconditionally — verify it is harmless on rev3 (settable, no audible effect, no crash).
- [ ] **G2.35** Confirm the display brightness range is unchanged on the SSD1351 (the three-axis rework is SSD1333-only).

**Blocks:** the release. Any failure here affects the majority of users.

---

## 4. Gate 3 — Bench, rev4 hardware

Needs a real rev4 board. If none is available, see §8 — the rev4 features must then be
explicitly declared untested in the release notes.

- [ ] **G3.1** `python -m PiFinder.bringup` on a freshly provisioned card: pre-flight reports i2c-1 and both PWM channels; SCREEN/BACKLIGHT/BUZZER emit; IMU and CHARGER report PASS; SWITCHES observes **every** populated matrix position. *Buzzer output is confirmed working on hardware given a correctly provisioned card — the open item is `pifinder_setup.sh`, which provisions only the single-channel `pwm` overlay, so a fresh install would report `pwm ch0 -> gpio12 NOT ROUTED` and be silent with no error. The setup-script fix is a deliberate follow-up, not part of 2.6.1.*
- [ ] **G3.2** ~~Confirm the rev4 population map~~ — **confirmed on hardware** (2026-07-30). `REV4_POPULATED` as shipped is correct; no further check needed.
- [ ] **G3.2a** Bring-up **power hold**: a tap of the power switch registers the closure for `SWITCHES` and nothing else; a hold fills the `PWR` bar over one second, plays the SHUTDOWN earcon, shows `SHUTTING DOWN`, and cleanly shuts the card down. Confirm `--no-power-shutdown` removes the gesture while a tap still counts. *#556 was not exercised on a board — the gesture shuts the machine down, so this is bench-only verification.*
- [ ] **G3.2b** Confirm `sudo shutdown now` works passwordless on the bring-up card. Without it the run reports the non-zero exit rather than swallowing it, but the builder would otherwise read `SHUTTING DOWN` on a board that is still up.
- [ ] **G3.3** Battery icon in the title bar tracks charge; plugging in the charger shows the bolt glyph.
- [ ] **G3.4** Earcons play; `Settings → User Pref → Volume` changes level audibly and `Off` silences them.
- [ ] **G3.5** Power button: first press opens the shutdown confirmation, second press confirms, shutdown earcon plays **before** the power latch fires, and the unit powers off.
- [ ] **G3.6** **`reboot` must come back up, not power off.** *ADR 0007 calls this out explicitly — the `gpio-poweroff` latch is the one change here that can leave a unit dead on a reboot.*
- [ ] **G3.7** SSD1333 display: boot splash renders at 176×176, no rotation artifacts, all screens laid out correctly.
- [ ] **G3.8** SSD1333 brightness: sweep the full UI range in a dark room. The dimmest setting must be genuinely dim (the point of the change) and the brightest must not bloom. Confirm no blanking mid-range, and that settings at or above 0.35% keep visible tonal range.
- [ ] **G3.9** Each of the five build variants (`AS Bloom`, `AS Heart`, `Rev4 Left/Right/Straight`) selected in `Settings → Advanced → PiFinder Type`: after the restart, IMU dead-reckoning must move the reticle in the **correct direction** for a physical nudge in each axis. *(#530's PR checkboxes record hardware verification as done; re-confirm at least the variant matching the test unit.)*
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
- [ ] **G5.5** SQM against a hand-held reference meter, if one is available, on each sensor you can test. Record the residual — this is the data that resolves P1.3.
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
| `sqm_band_offset` refit not applied (imx296 ~0.4 low, HQ ~0.2 high) | **Open decision — P1.3** | Land the refit, or document the offset in the release notes. |
| SQM absolute anchoring | Not established | Two nights read ~0.6 mag from reference for reasons stellar photometry can't see. A side-by-side campaign is the fix; not a blocker. |
| `imx290` SQM constants | Mirrored from imx462, no sweeps | Flag as provisional. |
| `imx296` SQM constants | Fit from a **single** moonlit sweep | Flag as provisional. |
| SOC_LUT knots | Provisional, pending pinned-load confirmation runs | Follow-up PR after the campaign; conservative enough to shut down safely. |
| GPS NAV-PVT / NAV-SAT path | Spec + unit tests only, no M9/M10 hardware | **G5.10** if a module can be found; otherwise ship and solicit field reports. |
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
| P1 Pre-flight | maintainer | none | 1 h | ☐ |
| G1 Automated | CI | none | 15 min | ☐ |
| G2 Bench rev3 | | rev3 unit + observation history | 3–4 h | ☐ |
| G3 Bench rev4 | | rev4 board + battery | 3 h + discharge run | ☐ |
| G4 Upgrade path | | 2.6.0 unit, spare card | 2 h | ☐ |
| G5 Under the stars | field tester | rev3 unit, clear night, SQM meter | 1 night | ☐ |
| G6 Web / API | | Selenium Grid | 1 h | ☐ |

**Release criteria:** P1, G1, G2, G4, G5 all green. G3 green *or* rev4 explicitly
declared untested in the release notes. G6 green *or* web changes reverted.

**Post-cut:** the NixOS release workflow, migration tarball, and manifest population
live only on `release` (#514, #515, #516, #519, #522) and have never run against this
content. Watch the first release build for the 2 GB RAM budget check (#522) — the
migration tarball has grown.
