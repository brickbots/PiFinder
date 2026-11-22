# PiFinder v2.6.4 — Release Test Plan

Scope: **everything since the `v2.6.3` tag**, 38 commits on `main` @ `b709c6f5a`. The raw
diffstat (170 files, +22,360 / −1,878) is dominated by the catalog import, its source
tables and corrections, and the rebuilt `astro_data/pifinder_objects.db`. Runtime code
outside the import is small: about 900 added lines across the app.

This plan is risk-ordered, not feature-ordered. Each gate has an owner, a pass criterion,
and a note on what a failure blocks. Gates 1–3 must pass before the `main` → `release`
merge; gates 4–6 must pass before the update is offered. The process behind it is
`release_notes/RELEASE-PLAYBOOK.md`; this is the first plan written against it.

Items marked **(carried)** come from `release-2.6.3-test-plan.md` and are not re-derived
here. That plan remains the reference for why they exist.

**Status as of 2026-11-21** (`main` @ `66673d2a2`): Gate 1 green at `b709c6f5a` (G1.7 not run); since then only #706 landed, a change to `nixos_migration_init.sh` that no Gate 1 check covers. Gate 2 passed on a rev4 (G2.9 and G2.40 not run). Pre-flight below.

**Shape of this release, and what that means for testing.** Three kinds of change, with
different evidence:

- **The catalog** (#697, carrying #671–#696). The largest change by far, and the one with
  the most evidence already: a reproducible build, `tests/test_catalog_data.py` against
  the committed database, and a 15-item on-device checklist that passed on a rev4 unit
  on 2026-11-19 with the final database (sha256 `474d0331…`). What it lacks is a run on
  anything other than rev4.
- **Settings and alignment** (#703, ADR 0047 and 0048). Small in lines, wide in reach:
  every settings save in every process now goes through one new merge-and-lock path.
  Three hardware checks passed on 2026-11-19. No upgrade from a real 2.6.3 configuration
  yet.
- **The NixOS migration** (#657). Ships closed, but seven presses of SQUARE on the
  Software screen reach it on the day 2.6.4 ships. It rewrites the SD card. Its
  contract with the NixOS line freezes when 2.6.4 ships (playbook, "Where the tracks
  meet"). QEMU end-to-end evidence exists from 2.6.3; **no migration from a 2.6.4 card
  on hardware yet.**

The three questions that matter most: **does a 2.6.3 unit come through the update with
its catalog, observations, settings and alignment intact**, **can a migration started
from a 2.6.4 card finish on both a Pi 4 and a rev4, and leave the rev4 able to power on,
reboot and power off**, and **does the catalog behave on the hardware that has not run it
yet** (rev3, the 128 px screen).

---

## 0. Release mechanics — read before cutting

**Two "2.6.3"s are in the field.** #639, #640 and five docs and hardware commits reached
`release` after the `v2.6.3` tag by out-of-cycle promotion, with no `version.txt` change
(`git log v2.6.3..origin/release --no-merges`: 11 commits). So a unit that reports 2.6.3
runs either the tag's tree or the later `release` tip. The difference that matters is
#640: the tag tracks the `python/tetra3` symlink, the tip does not. Gate 4 covers both.

**The merge.** `git merge-tree --write-tree origin/release origin/main` exits 0 and its
tree (`25bfddf9…`) equals `main`'s. Unlike 2.6.3 there is no `version.txt` conflict,
because `release` still reads 2.6.3. Testing `main` is testing the cut.

**`version.txt`.** Reads 2.6.3 on `main` today. The prep PR bumps it to 2.6.4. Confirm
the bump is **committed** on `main` before the merge (playbook trap 1).

**Who gets offered what.** Once `release/version.txt` reads 2.6.4, `update_needed` opens
for every 2.x unit below it: the 2.6.3 tag, the `release` tip (also "2.6.3"), 2.6.1, and
units stuck on 2.5.x by the symlink fault, which #640 now lets through. The migration gate
stays closed (`migration_gate.json`: both flags `false`), so no unit is offered the
migration through the public path.

**The `.github/` change at the cut.** Six workflow files differ between `release` and
`main` (#658, #686, #689). After the cut, the copy of `release.yml` on `release` is the
new one, which writes only `migration_v2_*`. **Until the cut, start "Release NixOS image"
with `--ref main` only.** The copy on `release` today writes `migration_url`, which 2.6.1
to 2.6.3 read; they then run their old ext4 migration on a btrfs tarball, and the card
does not boot. That happened to a test card in October.

**The migration contract freezes at the cut.** From the moment `release` carries 2.6.4,
units on it read the flag `nixos_migration`, the manifest keys `migration_v2_url` /
`migration_v2_sha256_url`, the channel order stable → beta → unstable, and one tarball
layout. Read `nixos/RELEASE.md` on `mrosseel/PiFinder:nixos` before the cut, not after.

---

## 1. Risk model

| # | Area | PRs | Blast radius | Why it's risky |
|---|---|---|---|---|
| R1 | Catalog database rebuild | #697 (#671–#696) | **All users** | Every sky object id changes and the catalog cache is rebuilt on first start (~2 min on rev4). Anything that held an id would break; the PR's audit says nothing outside the database does. Names, types, positions and filter magnitudes change for thousands of objects on purpose, so a wrong change does not fail, it just reads wrong. |
| R2 | Config saves merge under a lock | #703 (ADR 0048) | **All users, every process** | Every `set_option` in the UI, camera, web server and integrator now re-reads `config.json`, merges, and replaces the file under `flock`. A fault here loses settings, or blocks a save, everywhere. New hidden file `.config.json.lock` in `PiFinder_data`. |
| R3 | NixOS migration (Pi OS side) | #657, #658 | Anyone who presses SQUARE seven times on the Software screen | Destructive: converts the root to btrfs in place. Reachable on release day although the gate is closed. Lands on a beta that the cache deletes after 90 days. On 2026-10-09 a rev4 unit migrated from 2.6.3 cut its own power at first NixOS boot (serial output on GPIO14, the power-off line); a workaround passed boot, reboot and power-off, and the real fix is on the NixOS side. |
| R4 | Per-telescope alignment | #703 (ADR 0047) | Users with more than one telescope; **all users on upgrade** | No migration: unaligned telescopes fall back to the global `target_pixel`. A wrong fallback order moves every user's pointing on update. Bad stored points are dropped at load. |
| R5 | Update mechanics | #640 (ADR 0035) | **All in-place updaters** | The `python/tetra3` symlink goes from tracked (tag) to untracked. `git pull` deletes it; `pifinder_post_update.sh` must recreate it, or the solver does not start. The update now exits non-zero on a failed pull. |
| R6 | Power-off overlay gated to CM4 | #639 (ADR 0034) | Fresh images: rev4 and rev3 | rev4 must still cut power at `poweroff` and come back on `reboot`. rev3 must reach a dark halt. Only fresh images get the change. |
| R7 | 1.5" OLED at 20 MHz | #701 | rev3 and earlier with the SSD1351 | Fixes blank new panels; the frame-time cost on the chart while slewing is unmeasured. |
| R8 | SQM crop and analogue gain | #666 | SQM users, silent | A wrong constant shifts every reading without failing. Claim: no change at the calibration gain, which is the shipped gain. |
| R9 | Names view default per catalog | #696 | Catalog list users | Star catalogs open in NAME mode; SQUARE cycle starts from there. |
| R10 | Obs Lists picker layout | #704 | Observing-list users | Rewrote the picker's draw onto the shared menu layout. |
| R11 | Object details stepping | #678 | All users | Now steps by listing; relies on an `object_index` hand-off from the list. |
| R12 | i18n and menu indexes | #695, #657 | Non-English users; Selenium | `Named Stars` is a new entry in **two** Stars… menus (catalog list and filter). Menu-index drift has broken keypress-counting web tests twice. New migration screen strings. |

---

## 2. Pre-flight — repo housekeeping

Owner: coordinator (Claude), unless marked.

- [ ] **P2.1 — `version.txt` reads `2.6.4` on `main`, committed.** Not yet: the prep PR
  bumps it. Check after the prep PR merges, with `git show origin/main:version.txt`.
- [x] **P2.2 — Merge shape.** `git merge-tree --write-tree origin/release origin/main`
  exit 0; tree `25bfddf9…` equals `origin/main^{tree}`. No conflict. Re-check if anything
  lands on either branch before the cut.
- [x] **P2.3 — `.github/` diff known.** Six files differ: `release.yml`,
  `update_manifest.py`, `publish_manifest.sh` (#658), `nixos-pr-build.yml` (#686),
  `nox.yml` and `web-integration-tests.yml` (#689). All intended. See §0 for the
  `--ref main` rule until the cut.
- [x] **P2.4 — `migration_gate.json` on `main`**: `nixos_for_everyone: false`,
  `nixos_migration: false`. This is what ships.
- [ ] **P2.5 — ADR ledger.** New on `main` since the tag: 0034, 0035, 0046, 0047, 0048,
  plus the consolidated 0022 (0002, 0024, 0026, 0028 removed, numbers left unused). No
  duplicate numbers on `main` today. 0036–0045 are on the NixOS line: **recompute against
  the `nixos` branch at merge time.**
- [ ] **P2.6 — i18n pass.** New msgids since 2.6.3 include `Named Stars` and the
  migration screen strings (`Keeps obs + images`, `Plug in USB-C power`,
  `Keep power + WiFi on`, `Back`). The migration's step names ("Keeping your data" and
  the others) come from `nixos_migration_init.sh`, not `_()`, so they show in English in
  every language. All four catalogs at 0
  untranslated, 0 fuzzy, no msgid removed, each `.mo` byte-identical to a fresh
  `pybabel compile`. msgid count: **698 × 4** (694 at 2.6.3; 6 added, 2 now unused). Done in the prep PR:
  `Enter Local Time` was in the code but marked obsolete in every catalog, so 2.6.3 showed
  it in English; it is active again. Babel 2.16 needs `setuptools<81` in a fresh venv
  (`noxfile.py` pins it). Scope the diff to the tracked
  `.po` files; `messages.pot` is gitignored.
- [x] **P2.7 — Config surface.** `default_config.json` unchanged since `v2.6.3`: an
  untouched upgrade gains no keys. Two designed write changes, no migration:
  - an alignment now saves into the active telescope's record (`target_pixel` inside
    `equipment.telescopes[n]`), not the global key;
  - every save merges into the file on disk (ADR 0048), and creates
    `PiFinder_data/.config.json.lock`.
- [x] **P2.8 — No new migration script.** `migration_source/` gains nothing; `v2.1.0.sh`
  only loses its `ln -s` (#640). Nothing to register in `pifinder_post_update.sh`.
- [x] **P2.9 — Requirements.** `requirements.txt` unchanged. `requirements_dev.txt` adds
  `tomli` for Python < 3.11 (catalog import only; the device never runs it). Nothing new
  to stage on the image.
- [x] **P2.10 — `python/tetra3` is untracked.** `git ls-files python/tetra3` is empty.
  Never re-track it (ADR 0035).
- [ ] **P2.11 — Docs snapshot.** The prep PR adds `/en/v2.6.3/` to the "previous
  versions" note in `index.rst`, `user_guide.rst` and `quick_start.rst` (all three or
  none), and rewords the note per the playbook's one-time task. Owner: coordinator.
- [ ] **P2.12 — A beta newer than 90 days is in the manifest** with `migration_v2_*`
  keys and `available: true`. `v3.1.3-beta` was built 2026-11-11, so it expires around
  2027-02-09. Seven presses of SQUARE land on it. Owner: mrosseel.
- [ ] **P2.13 — Close issues that merged PRs fixed.** `Closes` keywords did not fire
  because `release` is the GitHub default branch: #318 and #408 (#696), #626 (ADR 0048),
  #661 if #696 settles it. Owner: Rich.

---

## 3. Gate 1 — Automated (CI, ~15 min)

Owner: coordinator (Claude). Run on `main` directly; the merge tree equals `main` (P2.2).

```bash
cd python/
source .venv/bin/activate
git submodule update --init PiFinder/tetra3   # mypy + solver tests need this
ln -sfn PiFinder/tetra3/tetra3 tetra3         # untracked since #640
rm -rf .mypy_cache
nox -s lint
nox -s format
nox -s type_hints
nox -s smoke_tests
nox -s unit_tests
python -m sphinx -nW -b html ../docs/source <out>
```

- [x] **G1.1** Ruff lint clean; format check clean (290 files).
- [x] **G1.2** MyPy clean, fresh cache (158 source files).
- [x] **G1.3** `pytest -m "smoke or unit"`: **2,421 passed (5 smoke + 2,416 unit), 0 failures** (1,531 at 2.6.3;
  #703 reported 2,344 unit tests on its branch). A materially lower count means collection
  broke.
- [x] **G1.4** New suites **running, not skipping**: `test_catalog_data.py` (reads the
  committed database: 22 catalogs, Nam 578, SaM 2,157, EGC 102),
  `test_catalog_matching.py`, `test_object_list_display_mode.py`,
  `test_object_details_scroll.py`, `test_obs_list_layout.py`,
  `test_target_pixel_per_telescope.py`, `test_target_pixel_wiring.py`,
  `test_config_persist.py`, the `test_radiometer.py` / `test_black_level.py` additions,
  and `test_software.py` (migration pre-flight, power check, progress screen).
  `test_optics_solving.py` must still run, not skip, which proves the tetra3 link is in
  place **(carried)**.
  Each suite was run on its own and passed. `test_black_level.py` has no marker, so
  neither nox session runs it (14 pass when run directly): a follow-up, not a blocker.
- [x] **G1.5** `nox -s ui_tests` passes and finishes inside the CI job limit (the comet
  retry hang, #684). 225 passed, 2 skipped, 1 min 47 s.
- [x] **G1.6** Docs build clean, `-nW`, 0 warnings. Page count: 20.
- [ ] **G1.7** Catalog build reproduces: `python -m PiFinder.catalog_imports.main` from
  a deleted database gives sha256 `474d0331…`. Optional if time is short; #697 did it
  twice with different hash seeds.

**Blocks:** everything. Re-run if anything further lands on `main` before the cut.

---

## 4. Gate 2 — Bench, standard hardware (the population that upgrades)

Owner: Rich. Run on a real unit updated in place from **2.6.3**, ideally a rev3 (rev4 has
the catalog evidence already). Indoors is fine; use `Tools → Test Mode` for a solvable
frame.

The organising question: *does a device nobody has touched behave the same, except where
the notes say it changes?*

### Catalog, first start and the cache (R1)

- [x] **G2.1** First start after the update: main menu in a normal time, then
  **Catalogs Fully Loaded** appears. Record both times on this unit (rev4 reference:
  13 s and about 1 min 55 s). Messier, NGC and IC work before the message.
- [x] **G2.2** Second start: no cache rebuild, no message delay beyond normal. Record the
  time to the main menu. **No second-start baseline exists yet.**
- [x] **G2.3** Power off during the cache rebuild (before the message). Next start
  rebuilds again and completes; nothing is corrupted.
- [x] **G2.4** An observation logged before the update still shows as observed, under
  its own designation and under the other entries of the same object (log M 103, see
  Col 14 marked).
- [x] **G2.5** A saved observing list from before the update loads with the same count
  of objects as on 2.6.3. One that names Collinder 399 opens the Coathanger.
- [x] **G2.6** Star lists (Named Stars, SAC Doubles, WDS, Planets) open in the names
  view; NGC and M open in the distance view; SQUARE cycles NAME → INFO → LOCATE → NAME.
- [x] **G2.7** In a list that holds both M 31 and NGC 224 (name search "great n", or All
  Filtered with M and NGC), UP/DOWN in object details visits each entry once and holds at
  the ends.
- [x] **G2.8** Jump-to-number with 5 and 6 digits in WDS (for example 131303).
- [ ] **G2.9** Catalog images still open for objects that have them (file names are by
  catalog code and sequence, unchanged).

### Settings and alignment (R2, R4)

- [x] **G2.20** On the updated 2.6.3 unit, before any alignment: pointing matches 2.6.3
  (the global `target_pixel` is the fallback). `config.json` has no `target_pixel` in any
  telescope record.
- [x] **G2.21** Align on telescope A. `config.json` gains `target_pixel` in A's record
  only; the global key is unchanged. Select B: B uses the old global point. Align on B,
  select A again: A's point is back. (#703's hardware check, repeated on the release
  build.)
- [x] **G2.22** The clobber fix: align, then leave **Align (Day)** with a manual
  exposure; restart; the alignment is still there. Same after choosing a manual value in
  **Camera Exp**.
- [x] **G2.23** Change settings from three places in one session (a menu setting, a
  manual exposure, an equipment edit on the web page), restart, and confirm all three
  survived. `config.json` keeps its owner (`pifinder`) and mode.
  `.config.json.lock` exists in `PiFinder_data`.
- [x] **G2.24** Edit `config.json` by hand over the network share while the PiFinder is
  off; boot; the edit is read. (Atomic replace swaps the file; check nothing about the
  share breaks.)
- [x] **G2.25** Hand-edit one telescope's `target_pixel` to garbage (`[9999, "x"]`) and
  restart: that telescope falls back to the global point, and the rest of the equipment
  list loads (not replaced by defaults). The warning ("Ignoring unusable alignment
  point") does not reach `~/PiFinder_data/pifinder.log` at the default log level: the
  `config` logger inherits the root level, `ERROR`, from `logconf_default.json`.
- [x] **G2.26** On a 2.6.3 unit that had self-healed its lens: `camera_lens` survives a
  menu change and a restart (#626).

### SQM, display and the rest (R7, R8, R10)

- [ ] **G2.40** SQM before and after the update, same conditions: moves less than
  ~0.05 mag (claim: no change at the calibration gain). With debug logging on, the
  delivered gain in the capture log matches the profile's `calibration_analogue_gain`.
- [x] **G2.41** Obs Lists picker at 128 px: same look as the Objects menu; a long name
  scrolls on the selected line; a folder opens.
- [x] **G2.42** Full boot → GPS lock → solve → object details → push-to, nothing
  configured **(carried)**.
- [x] **G2.43** Focus screen hold, LEFT releases it; the burying-route leak is unchanged
  **(carried, still open)**.

**Blocks:** the cut. G2.1–G2.5 and G2.20–G2.23 are the update the field takes.

**Result, 2026-11-20 (Rich):** passed on a rev4, on a new SD card written with the 2.6.3
image and updated by hand to `release-2.6.4-prep` (`git checkout`, then
`pifinder_post_update.sh`). The `python/tetra3` link was removed by the checkout and made
again by the script, as expected.

- **Times** (stopwatch from `systemctl restart` or `start`, so they include more than the
  app's own start). First start: 23 s to the main menu, Catalogs Fully Loaded at 2:18.
  Second start: 24 s, no message, Named Stars at once. Clean start with the cache deleted:
  20 s. The same rev4 on its usual card gave 13 s with almost the same code, so we do not
  count the difference as a regression. The app log has no "Menus" line, so it cannot
  give a baseline.
- **G2.3:** power cut during the rebuild. The next start rebuilt the cache (2:10); nothing
  was lost.
- **G2.4:** M 101, logged on 2.6.3, shows logged under M 101, NGC 5457 and Arp 26.
- **G2.22, before and after:** on 2.6.3 this card lost its alignment (no `target_pixel`
  in `config.json` after aligning and using the camera exposure). On 2.6.4 both
  telescopes' points survived a manual Camera Exp, an Align (Day) exposure change and a
  restart.
- **Not run:** G2.9 (a new card has no catalog images), G2.40 (no SQM reading on 2.6.3).

---

## 5. Gate 3 — Release-specific risk

Owner: Rich (hardware), with mrosseel for the NixOS side of G3.1–G3.6.

### The migration from a 2.6.4 card (R3)

Run on two units: **one Pi 4 (rev3)** and **one rev4 (CM4)**. Each starts from a card on
2.6.4 (`main` at the cut commit), WiFi in client mode, with an observation log, an
observing list, a non-default camera type where possible, and a changed access-point name.

- [x] **G3.1** On the Software screen, with the gate closed, confirm the screen offers
  nothing (or the normal "No Update needed"). Then press SQUARE seven times: the UPGRADE
  confirm screen appears with the newest beta from the manifest. **Cancel** returns with
  nothing changed.
- [x] **G3.2** rev4 only: on battery, the confirm screen shows **Plug in USB-C power** and
  offers only Cancel. Plug in USB-C: **Confirm** appears.
- [x] **G3.3** Pre-flight refusal: with WiFi in access-point mode, the screen names the
  cause (**WiFi must be in client mode**) and LEFT goes back.
- [ ] **G3.4** Run the migration to the end on both units. Progress screen: the bar
  shows only for steps with a measure; the elapsed time updates; the screen does not dim.
  Record the total time.
  On rev4, the card-conversion screens fill the 176 px panel the right way up. Before
  #706 they were drawn small and turned (the progress server started before it knew the
  panel type); the rev4 run of 2026-11-20 used the script without #706.
- [x] **G3.5** First NixOS boot on both units: camera type, hostname, AP name, password
  and SSH keys carried; observations and images present; the unit solves.
- [x] **G3.6** **rev4: power on, reboot, power off** after the migration, each at least
  twice. GPIO14 is the power-off line; one byte of serial output on it cuts the power.
  This failed on 2026-10-09 from 2.6.3; confirm the beta in the manifest carries the
  NixOS-side fix and does not need the `gpio=14=ip,pu` workaround.
- [ ] **G3.7** Failure path, on a spare card if one is available: pull WiFi during the
  download. The script reports FAILED, **LEFT** closes the progress screen, and the unit
  still boots Pi OS 2.6.4.

**Result, rev4 (CM4), 2026-11-20/21 (Rich):** from the Gate 2 card (2.6.4 candidate,
before #706) to **3.1.3-beta**.

- G3.1–G3.3 pass: SQUARE ×7 offers 3.1.3; on battery only Cancel; in access-point mode the
  Software screen says WiFi must be in client mode and SQUARE ×7 does not reach UPGRADE.
- G3.4 partly: the card converted and NixOS booted. The conversion screens were small and
  turned (fixed since by #706, not yet re-checked). The first-boot download ("DOWNLOADING
  NIXOS", `pifinder-first-boot`) is slow and its bar counts store paths, so it can stand
  still for minutes; it completed. Total time not measured.
- G3.5 pass: observations (M 101, also under NGC 5457 and Arp 26), the observing list, both
  telescopes and their points, the web edit, `camera_lens`, `camera_exp`, hostname, SSH host
  keys and both WiFi connections carried; Test Mode solves. **The AP name was the default,
  so its carry-over is not proven.**
- G3.6 pass: no power cut at first boot (the 2026-10-09 failure did not happen), and two
  reboots, two power-ons and two power-offs completed normally.

**Result, rev3 (Pi 4), 2026-11-21 (Rich):** from 2.6.4 (`release-2.6.4-prep`, with #706)
to **3.1.3-beta**, with a non-default hostname (`pifinder-test`), AP name (`PiFiAP`) and
camera (imx462). The card converted; the conversion screens drew correctly on 128 px.
**The newer 1.5" OLED is blank on NixOS:** 3.1.3-beta (2026-10-23) predates #701. The
`nixos` branch has #701 in `displays.py` since 2026-11-19, but `nixos/pkgs/boot-splash.c`
and `python/scripts/migration_progress.c` (on `main`, ships in 2.6.4) still drive the
SSD1351 at 40 MHz. Not a 2.6.4 blocker (gate closed, notes silent), but **the NixOS
release behind an opened gate must include #701 and a 20 MHz splash.** Reported to
mrosseel on Discord. Carry-over and power checks: see G3.5/G3.6 below this note when done.

**Still to do in this section:** a rev4 run with #706 for the conversion screens; G3.7.

**Blocks:** the cut. The migration is reachable on release day. If G3.4–G3.6 fail on
either unit, do not ship until the NixOS side is fixed or the seven-press path is closed
in 2.6.4.

### The catalog off rev4 (R1)

#697's on-device checklist (15 items, in the PR body) **passed on rev4 on 2026-11-19**
with the final database. It has not run anywhere else.

- [ ] **G3.10** Run the same 15-item checklist on a **rev3 unit with the 128 px screen**.
  Pay attention to the items that draw text: "Dhanuśarāgra" (Nam 88567) with the ś and ā
  drawn correctly, names-first rows in SAC Doubles and Named Stars, and the M 103 details
  line "NGC 581, Col 14, Lyn 44".
- [ ] **G3.11** First-start timing on the rev3 (G2.1): main menu time and the time to
  **Catalogs Fully Loaded**. Record the SD card too, since the rebuild reads the whole
  database.

### Per-telescope alignment from a real 2.6.3 configuration (R4)

- [ ] **G3.20** Copy a real 2.6.3 `config.json` with two or more telescopes and a
  non-centre global `target_pixel` onto a 2.6.4 unit (or update that unit in place).
  Boot: every telescope uses the global point; nothing is written to the telescope
  records until an alignment.
- [ ] **G3.21** Same file with `active_telescope_index` pointing at the second telescope:
  the active one stays active after a web-page delete of the first.

### The 20 MHz OLED on an older rev3 panel (R7)

- [ ] **G3.30** On a rev3 unit with an **older** 1.5" OLED (one that worked at 40 MHz):
  the screen starts, the splash shows, and the chart is readable.
- [ ] **G3.31** Chart frame rate with `--fps` while moving the scope, 20 MHz against
  40 MHz on the same unit. (Open item from #701.)
- [ ] **G3.32** If a new Waveshare panel is at hand: it starts at 20 MHz (was blank at
  40 MHz).

### Power-off on fresh images (R6)

- [ ] **G3.40** rev4, fresh 2.6.4 image: `gpio-poweroff` is in `/proc/device-tree`;
  `poweroff` cuts power; `reboot` comes back. (ADR 0007's acceptance check, re-run.)
- [ ] **G3.41** rev3, fresh 2.6.4 image: overlay absent; `poweroff` ends fully dark.

**Blocks:** G3.1–G3.7 and G3.10 block the cut. G3.30–G3.31 block the cut for rev3
owners: if an older panel misbehaves at 20 MHz, the fix for new panels breaks old ones.

---

## 6. Gate 4 — Upgrade paths and fresh install

Owner: Rich.

- [ ] **G4.1** **From the `v2.6.3` tag** (tracked symlink). In-app update is offered,
  completes, Status reads 2.6.4. `python/tetra3` is the relative link
  `PiFinder/tetra3/tetra3` and the solver starts.
- [ ] **G4.2** **From the later `release` tip** (still reports 2.6.3, already untracked).
  Same checks as G4.1.
- [ ] **G4.3** **From 2.6.1**, if units are still on it. Same checks; no 2.6.x migration
  script runs twice.
- [ ] **G4.4** **From a unit stuck on 2.5.x** (absolute symlink or plain `tetra3`
  folder), if one is available: the update now succeeds, the leftover is moved to
  `~/tetra3_old_<timestamp>`, and the unit reaches 2.6.4. (#640's sandbox evidence covers
  all four states; this is the hardware confirmation.)
- [ ] **G4.5** Failed update: block the network mid-update. The Software screen shows
  **Error on Upd**, not **Ok! Restarting**, and the unit still runs its old version.
- [ ] **G4.6** Config not rewritten on update and gains no keys (P2.7).
- [ ] **G4.7** Fresh install from the published 2.6.4 image on rev3 and rev4: boot,
  configure, solve. First start builds the catalog cache as in G2.1.
- [ ] **G4.8** Non-default `camera_type` (HQ) survives the update and solves
  **(carried)**.

**Blocks:** offering the update.

---

## 7. Gate 5 — Under the stars

Owner: Rich.

- [ ] **G5.1** A full night on standard hardware, updated from 2.6.3, nothing
  reconfigured. Solve rate and pointing as on 2.6.3.
- [ ] **G5.2** Two telescopes in one night: align on each, swap, and push-to on both
  without re-aligning.
- [ ] **G5.3** The catalog in real use: name search for an IAU name only Named Stars has
  (Miaplacidus, Naos or Pherkad, as the sky allows), push-to it, and check a merged star
  (Mizar) and a moved WDS listing lands where the eyepiece says.
- [ ] **G5.4** The magnitude filter at 6: bright doubles with faint companions (Procyon,
  Fomalhaut, as the sky allows) stay in the SAC Doubles list.
- [ ] **G5.5** SQM across the night against a 2.6.3 night at the same site, if one is on
  record **(carried)**.

**Blocks:** offering the update.

---

## 8. Gate 6 — Web, API, and planetarium protocol

Owner: coordinator (Claude) for G6.1–G6.3; Rich for G6.4.

Reset `language` to `en` in `~/PiFinder_data/config.json` before the web suite.

- [ ] **G6.1** Selenium suite. **Check for menu-index drift**: `Named Stars` is new in
  both Stars… menus. Any test that counts keypresses through Objects → By Catalog →
  Stars… or the filter's Stars… is a candidate.
- [ ] **G6.2** Web equipment: edit a telescope, its alignment survives; delete a
  telescope above the active one, the active one stays (#703). Select a different
  telescope on the web page, and the device's pointing follows (the `reload_config`
  path).
- [ ] **G6.3** `/api/current-selection` and the web object details show the new names
  (M 82 → Cigar Galaxy) and the joined listings.
- [ ] **G6.4** SkySafari push to the observing list and position readout
  **(carried)**; Stellarium live session if not banked in 2.6.3 **(carried)**.

**Blocks:** offering the update.

---

## 9. Known gaps and accepted risk

1. **The migration is reachable while the gate is closed.** Seven presses of SQUARE
   ignore the gate by design. It lands on a beta that expires 90 days after it was built.
   Accepted for 2.6.4 (playbook, "Decided for 2.6.4"); G3.1–G3.7 are the condition.
   The 2.6.4 release notes do not mention the migration at all, by Rich's decision
   (2026-11-19). Testers get their own instructions.
2. **With the gate open, a later 2.x cannot be offered in the app** to units on 2.6.4
   (the Software screen offers the migration before it reads `version.txt`). Read from
   code, not seen on a device. Close the gate before any 2.x hotfix.
3. **The rev3 power-off fix reaches fresh images only.** No fleet rewrite, by decision.
4. **The catalog has rev4 evidence only** until G3.10 runs.
5. **No second-start timing baseline** for the catalog cache (G2.2).
6. **The 20 MHz frame cost is unmeasured** until G3.31 runs.
7. **Barnard's six "a" nebulae are missing** (#665). A known gap in the new catalog.
8. **The web page's eyepiece delete** can still change the active eyepiece (found during
   #703, not filed).
9. **Carried from 2.6.3, still open:** the Focus exposure hold leak; a Camera Type switch
   does not clear the stored lens; the Nearby cap at 200 and the unselectable RA sort
   (#630); 25 mm on imx296/imx462 offered but cannot solve; the 12 mm partly calibrated
   (#612).

---

## 10. Prior review

Each PR in the range was reviewed on its own. The catalog work had an outside review
(mrosseel's fault lists on #670, fixed across #692, #693 and #697) and a findings run
that went from 1,374 to 1,131 findings against the old database. #666 had two review
rounds that each reversed a claim (digital gain → analogue gain; correction off where
unverified). No dedicated release review was run for this cut.

---

## 11. Sign-off

| Gate | Owner | Date | Result |
|---|---|---|---|
| Pre-flight (§2) | Claude / Rich / mrosseel | | |
| G1 — Automated | Claude | | |
| G2 — Bench, standard hardware | Rich | | |
| G3 — Migration, catalog off rev4, alignment, OLED, power-off | Rich, mrosseel | | |
| G4 — Upgrade paths | Rich | | |
| G5 — Under the stars | Rich | | |
| G6 — Web, API, planetarium | Claude, Rich | | |

**Migration gates (G3.1–G3.7) passed on Pi 4 and rev4:** ______________  **Cut authorised by:** ______________  **Date:** ____________
