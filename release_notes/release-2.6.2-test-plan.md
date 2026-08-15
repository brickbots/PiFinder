# PiFinder v2.6.2 — Release Test Plan

Scope: everything on `main` that is not yet on `release` — 23 commits, 68 files,
+5,088 / −1,976 (Python: 32 files, +2,303 / −514; of which ~900 lines are new tests).

This plan is risk-ordered, not feature-ordered. Each gate has an owner, an explicit
pass criterion, and a note on what a failure blocks. Gates 1–3 must pass before the
`main` → `release` merge; gates 4–6 must pass before the update manifest is published.

**Status as of 2026-08-15** (`main` @ `6aad0645`): `release` is an ancestor of `main`,
so the cut is a **fast-forward** with no conflicts to resolve. `.github/` is
byte-identical between the two branches, so the release workflow that runs post-cut is
the one already exercised on `release`.

**Shape of this release, and what that means for testing.** Eighteen of the 23 commits
are documentation. The code surface is small — two features — but one of them sits
directly in the solver's hot path and changes the search window used for *every solve
by every user*. The testing effort should be weighted accordingly: this is not a
"docs release, ship it" cut. The single question that matters most is **does a
never-touched 2.6.1 device still solve exactly as it did**, and it has to be answered
on real hardware, because the thing that changed is a number derived from the sensor
the device reports at runtime.

---

## 0. Risk model

What actually changed, ranked by blast radius × likelihood of an undetected defect.

| # | Area | PRs | Blast radius | Why it's risky |
|---|---|---|---|---|
| R1 | Solver FOV gate now derived | #608, #609 | **All users, silent** | Every solve goes through a window that is now computed at runtime from the sensor the camera process reports, rather than a constant. A wrong derivation for any sensor means that sensor never solves — and tetra3 enforces the window twice, so the failure is total, not degraded. It also presents as an exposure problem, so it will be misdiagnosed. |
| R2 | Zero-migration lens default | #609 | **All upgrading users** | An install with no `camera_lens` key must resolve to the sensor's shipped lens. If that path raises, or picks the wrong lens, the device stops solving on update with no user action to explain it. |
| R3 | `CameraProfile` relocated out of `sqm/` | #609 | All users, silent | ~500 lines moved between modules, including the radiometric constants. A changed constant shifts everyone's SQM without failing; a missed importer breaks a process at startup. |
| R4 | Focus exposure hold lifecycle | #614 | All users, next-session | A hold that is not released leaves the camera at a fixed manual exposure for the rest of the session, degrading or killing solving. There is a **known** exit route that leaks it (see G2.12). |
| R5 | Debug camera relabelled `imx296` → `hq` | #609 | Developers, CI | If wrong, `-fh --camera debug` stops solving for every developer and every automated test that solves a frame. |
| R6 | Live lens re-read in the solver loop | #609 | All users | The train is resolved per frame from shared state. New shared-state reads inside the hot loop; a manager disconnect or a bad value must not wedge the loop. |
| R7 | Chart frustum + web chart API | #609 | Visual / web | Frustum shading now follows the derived value in two places. Cosmetic on the device, but the web chart API is a separate consumer that can fail independently. |
| R8 | Manual rewritten wholesale | #585–#600, #604, #607 | All users, **no code risk** | 13 pages rewritten. The risk is not breakage but *accuracy*: a rewrite can silently change meaning. #604 additionally reverses standing advice (EQ platforms → alt-az). |
| R9 | i18n | #609 | Non-English users | Four new msgids. One is machine-translated and unreviewed. Menu-index drift from a new menu entry has broken web remote tests in this project before. |
| R10 | SQM field width now derived | #609 | SQM users, silent | `radiometric_fov_degrees` was deleted as a stored constant. The claim is reproduction to within 0.03° (< 0.01 mag). If wrong, every SQM reading shifts and nothing fails. |

---

## 1. Pre-flight — repo housekeeping (before any testing)

- [ ] **P1.1 — Bump `version.txt` to `2.6.2` and commit it. This is a release blocker,
  not housekeeping.** `main` currently reads **`2.6.1`**, identical to `release`; the
  bump exists only as an uncommitted edit in the maintainer's working copy
  (`git diff origin/release..origin/main -- version.txt` is empty).
  `ui/software.py:245` fetches `release/version.txt` from GitHub and line 353 gates the
  update on `update_needed(self._software_version, self._release_version)`. If `release`
  ships 2.6.2 code with `2.6.1` in the file, **every existing device compares 2.6.1
  against 2.6.1, renders "No Update needed", and is never offered the update at all** —
  the release would be invisible in the field. Separately, the Software screen,
  `splash.py:49`, `server.py:216` and `api_extensions.py:851` would all report `2.6.1`
  for 2.6.2 code, misattributing every field bug report.
- [x] **P1.2 — Cut is a fast-forward.** `git merge-base --is-ancestor origin/release
  origin/main` succeeds. No merge commit, no conflict resolution, and no separate merge
  result to test — testing `main` *is* testing the cut.
- [x] **P1.3 — `.github/` is byte-identical** between `release` and `main`. The release
  workflow is the one already exercised.
- [x] **P1.4 — ADR collision resolved.** #608 and #606 both landed a `0027` a day apart.
  Resolved by #616 under the standing rules: the FOV gate keeps 0027 (most-referenced —
  ten bare `docs/adr/0027` mentions across seven source files plus two test modules),
  tracked black level moved to 0028. Three inbound references updated.
  - **Still outstanding, not this release:** #571 (`fix/equipment-input-validation`)
    carries a third `0027-equipment-measurements-are-validated-floats.md` and should
    take **0029** at merge. #502 still carries the older `0018` collision.
- [x] **P1.5 — i18n release pass verified.** Exactly four new msgids (`Lens`, `12mm`,
  `16mm`, `25mm`), taking every catalog 671 → **675 msgids, 0 untranslated, 0 fuzzy**,
  with no msgid removed. All four are wrapped in `_()` at `menu_structure.py`
  1078/1087/1091/1095, and all four `.mo` files are **byte-identical to a fresh
  compile** — no stale binaries. `Lens` is tagged `AI-TRANSLATED (claude): needs human
  review`; the three lens labels are numerals and identical across languages.
  *(`messages.pot` is gitignored in this repo — the check was scoped to the tracked
  `.po` diff rather than a full babel extract.)*
  - **Two cosmetic residuals, not blockers:** in es and fr the standalone
    `# AI-TRANSLATED` comment that preceded `GPS Settings` was displaced onto the newly
    inserted `Lens` entry (which carries its own copy), so `GPS Settings` silently drops
    off the human-review queue in those two catalogs. And `"HOLD"` on the Focus → Stats
    screen is not wrapped for translation — though the adjacent `"AUTO"` / `"MANUAL"`
    are equally unwrapped and already ship that way, so fixing all three together is the
    clean call rather than treating this as a 2.6.2 regression.
- [x] **P1.6 — No migration is required, and that is by construction.** No config-schema
  migration is added; the only `MIGRATION_*` constants in the tree belong to the
  unrelated NixOS OS migration (`sys_utils.py:480-481`), untouched in this range.
  `default_config.json` is **unchanged** and deliberately carries no `camera_lens` key.
  The new key is optional by design: `Config.get_option` falls through `_config_dict` →
  `_default_config_dict` → `None`, and `optics.resolve_lens(profile, None)` then returns
  `get_lens(profile.default_lens_key)`. `text_menu.py` was patched so that a stored
  `None` plus a `value_callback` keeps the resolved default rather than snapping to
  `items[0]` — which is what stops a 2.6.1 config from displaying "12mm". No
  `requirements*`, `pyproject.toml` or `noxfile.py` changes, so there is nothing new to
  stage on the image.

---

## 2. Gate 1 — Automated (CI, ~15 min)

Run on `main` directly — the cut is a fast-forward, so there is no separate merge
result.

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

**Gate 1 is green on `main` @ `6aad0645`** (macOS dev venv, Python 3.9, 2026-08-15).
Run twice — once in the maintainer's checkout and once in a clean worktree rooted on
`origin/main` with the `tetra3` submodule freshly initialised — with identical results.

- [x] **G1.1** Ruff lint + format clean.
- [x] **G1.2** MyPy clean. Needs the `tetra3` submodule initialised; a stale
  `.mypy_cache` reports a phantom error, so clear it if the count disagrees.
- [x] **G1.3** `pytest -m "smoke or unit"` — **1,229 passed, 0 failures**, 472
  deselected (the non-smoke/unit markers). Reproduced exactly on a clean tree. A
  materially lower count means test collection broke somewhere.
- [x] **G1.4** New suites confirmed **running, not skipping** — `test_optics.py`,
  `test_optics_solving.py`, `test_plot_frustum.py`, `test_lens_menu_callback.py`, plus
  the additions to `test_focus_preview.py` and `test_sqm.py`. `test_optics_solving.py`
  is the one that pushes real `test_images/` frames through tetra3, so **verify it did
  not skip** — if the submodule is missing it silently disappears and the debug-camera
  relabel (R5) goes untested.
- [x] **G1.5** Docs build clean — `python -m sphinx -nW -b html docs/source <out>`
  exits 0, "build succeeded", **0 warnings**, 18 sources. `conf.py` sets no
  `suppress_warnings` or `nitpick_ignore`, so a clean `-n -W` build is meaningful
  rather than muted. `sqm.rst` is wired into the `index.rst` toctree after `equipment`,
  all three new `images/sqm/*.png` are present, and the new `:ref:` targets in
  `user_guide.rst` resolve. *(Needs `pip install -r docs/source/requirements.txt`;
  `sphinxcontrib-mermaid` and `sphinx_rtd_theme` are not in the app venv by default.)*

**Blocks:** everything. **Re-run G1.1–G1.5 if anything further lands on `main` before
the cut** — in particular after the `version.txt` bump (P1.1).

---

## 3. Gate 2 — Bench, standard hardware (the population that upgrades)

**This is the most important gate.** Run on a real unit updated in place from 2.6.1.
Indoors is fine for most of it; use `Tools → Test Mode` for a solvable frame.

The organising question: *does a device nobody has touched behave identically?*

### The derived FOV gate (R1, R2) — highest priority

- [ ] **G2.1** Update from 2.6.1 **without opening the Lens menu**. Confirm the device
  solves. This is the zero-migration path and the one almost every user takes.
- [ ] **G2.2** Check the log for the `Optical train:` line. It must name your actual
  sensor, the shipped lens (16 mm on imx296/imx462, 25 mm on HQ), and a field of view
  matching the table in the release notes. **Record the fitted FOV tetra3 reports and
  compare it with the derived value** — #609 measured 10.20° fitted against 10.33°
  derived on the debug train. A fitted value near the edge of the gate rather than the
  centre is the early warning that the derivation is off for your sensor.
- [ ] **G2.3** Confirm `camera_lens` is **still absent** from `~/PiFinder_data/config.json`
  after a full session in which the Lens menu was never used. The default must be
  resolved, not written.
- [ ] **G2.4** Compare solve rate against 2.6.1 on the same test frame, same conditions.
  The new gate is *tighter* than the old one (±15% vs an effective ±33%), so a
  measurable drop in solve rate — not a total failure, a drop — is the signature of a
  derivation that is slightly off. **This is the subtlest failure mode in the release
  and the one most likely to escape.**
- [ ] **G2.5** Open `Settings → Advanced → Lens`. The correct lens must be shown as
  checked, with no config entry present. Confirm it is the resolved lens and not simply
  the first item in the list — 12 mm is first, so a bug here looks like "12mm is
  checked".
- [ ] **G2.6** Select the *correct* lens explicitly (the one already in force). Solving
  must continue uninterrupted, and `camera_lens` now appears in config.
- [ ] **G2.7** Select a **wrong** lens. Solving must stop **immediately, without a
  restart** — this is the designed behaviour and confirms the live re-read works.
  Select the right one again: solving must resume, again with no restart. Time both
  transitions; they should land within a frame or two.
- [ ] **G2.8** With a wrong lens selected, confirm the log carries the resolved-train
  line naming it. This is the only diagnostic a support thread will have.
- [ ] **G2.9** Select **25 mm on an imx296 or imx462**. Confirm the solver logs the
  explicit "FOV gate … lies outside the solver database's … range: no frame can solve"
  error. Confirm the device does not crash, wedge, or thrash — it should simply not
  solve. *(This is a combination the menu offers but the shipped pattern database cannot
  serve; see §8.)*
- [ ] **G2.10** Power-cycle with a non-default lens stored. It must survive the restart
  and be picked up by the solver on the first frame.

### Focus screen exposure hold (R4)

- [ ] **G2.11** Open Focus under Auto exposure. Stats must read `HOLD` with the exposure
  the controller had settled on — including an off-ladder value, not snapped to a menu
  rung. Confirm the value flashes top-left on entry.
- [ ] **G2.12** **The leak test.** Enter Focus, then leave by the exotic route:
  long-RIGHT to recent objects, then long-LEFT to the top menu. Then watch the exposure
  for 60 s. **A known lifecycle gap means the hold is expected to remain engaged by this
  route** (`add_to_stack` skips `inactive()` for non-stateful modules; the SQM screen and
  daytime align have the same gap today). Confirm the scope of the leak: does auto
  exposure resume, and does solving continue? Then re-enter and leave Focus normally and
  confirm the hold is released. **Decide before the cut whether this ships as documented
  behaviour or blocks.** It is pre-existing in character but newly reachable on the
  screen users visit most on their first night.
- [ ] **G2.13** UP/DOWN step along the ladder 0.025 s … 1 s. Confirm both ends **hold
  rather than wrap** — five UPs from 0.1 s must stop at 1 s. The underlying `exp_up` /
  `exp_dn` commands apply no clamp at all, so this bound exists only in the new code.
- [ ] **G2.14** `+` and `-` still change magnification, not exposure. This is shipped,
  documented behaviour from #531 and must not have moved.
- [ ] **G2.15** Confirm `camera_exp` in `config.json` is **unchanged** after a session of
  nudging the exposure up to 1 s and back.
- [ ] **G2.16** Leave Focus normally with a manual value set. Within ~35 s and with no
  input, auto exposure must move it — proving control was genuinely handed back.
- [ ] **G2.17** Back out of Focus with LEFT. `inactive()` is called twice on this route
  (once directly, once from `remove_from_stack`); confirm the double call is harmless.
- [ ] **G2.18** Open the Quick Menu over the Focus screen and dismiss it. Confirm the
  hold is neither leaked nor prematurely released.

### SQM (R3, R10)

- [ ] **G2.19** Record an SQM reading under stable conditions on 2.6.1, update, and read
  again under the same conditions. The claim is movement under 0.01 mag. **Anything
  larger than ~0.05 mag means the derived field width does not reproduce the deleted
  constant** and should block.
- [ ] **G2.20** Confirm the SQM screen still shows as calibrated if it was before — the
  calibration file is keyed to the camera and this release does not touch that keying.
- [ ] **G2.21** Change the lens and confirm the SQM field width follows on the next
  frame, not the next boot.

### Everything else

- [ ] **G2.22** Chart frustum shading renders and matches the field of view for the
  configured train. Zoom in and out; confirm it scales.
- [ ] **G2.23** Align screen (day and night) opens, and its frustum overlay follows the
  derived value.
- [ ] **G2.24** Menu navigation around the new Lens entry: the entries either side of it
  in `Settings → Advanced` still open correctly. A new entry shifts every index below it.
- [ ] **G2.25** Full boot → GPS lock → solve → object details → push-to, with nothing
  configured, to confirm no regression in the ordinary path.

---

## 4. Gate 3 — Real lens swap (the feature's actual purpose)

Everything above tests the *declaration*. This gate tests the thing the release exists
to enable. Needs a physically different lens.

- [ ] **G3.1** Fit a 12 mm lens to an imx296 or imx462. Declare it in the menu. Confirm
  it solves. **On 2.6.1 the imx296 + 12 mm combination could not solve at all** (17.8°,
  outside the old `[8.0, 16.0]` window) — this is the headline capability and it has to
  be demonstrated on real hardware, not re-projected frames.
- [ ] **G3.2** With the 12 mm physically fitted, confirm the fitted FOV tetra3 reports
  lands near the derived 17.78° (imx296) or 13.51° (imx462).
- [ ] **G3.3** Declare the 12 mm while the 16 mm is fitted, and vice versa. Confirm both
  directions stop solving, and that recovering is simply a matter of correcting the menu.
- [ ] **G3.4** Note the SQM value with the 12 mm fitted. Its zero-point offset is
  **unmeasured** (#612) and its effective focal length is the nominal standing in for a
  measurement, so record the reading against a reference meter if one is available —
  that observation is what closes #612.

**Blocks:** the feature claim, not the release. If this gate cannot be run for lack of a
lens, say so explicitly in the release notes rather than implying the 12 mm path is
validated on hardware.

---

## 5. Gate 4 — Upgrade path and fresh install

- [ ] **G4.1** Update a real 2.6.1 device in place. Confirm it boots, solves, and reports
  `2.6.2` on the Status screen (**gated on P1.1**).
- [ ] **G4.2** Confirm `config.json` is not rewritten and gains no new keys on update.
- [ ] **G4.3** Fresh install from the published image: boot, configure, solve.
- [ ] **G4.4** Update a device that has a **non-default** `camera_type` stored (HQ).
  Confirm it resolves to the 25 mm and solves.
- [ ] **G4.5** Hand-edit `camera_lens` to a garbage value (`"18mm"`) and restart. Confirm
  the device degrades sensibly — it must not fail to boot. Then confirm the Lens menu
  still opens with a garbage value stored.
- [ ] **G4.6** Hand-edit `camera_type` to an unrecognised sensor and confirm the Lens
  menu still opens rather than raising while it is built.

---

## 6. Gate 5 — Under the stars

- [ ] **G5.1** A full night on standard hardware, shipped lens, nothing reconfigured.
  Solve rate and behaviour must be indistinguishable from 2.6.1. **This is the real R1
  test** — a bench test with a static test frame exercises one field, and the gate is a
  window.
- [ ] **G5.2** Solve across a range of altitudes and star densities, including a sparse
  field near the pole and a dense field in the Milky Way. The tightened gate has the most
  to lose where matches are already marginal.
- [ ] **G5.3** Use the Focus screen for a real focus session, start to finish, on a live
  sky. Confirm the hold does what it exists to do: the HFD readout must move only when
  you turn the lens.
- [ ] **G5.4** After focusing, leave the screen and confirm solving recovers to its
  normal rate within a minute.
- [ ] **G5.5** SQM across a full night, compared against a 2.6.1 night at the same site
  if one is on record.

---

## 7. Gate 6 — Web interface and API

- [ ] **G6.1** Web chart renders with the frustum overlay following the derived FOV.
- [ ] **G6.2** Chart API endpoint returns the derived field of view, and changes when the
  lens changes.
- [ ] **G6.3** Run the Selenium suite. **Check specifically for menu-index drift** — the
  new Lens entry shifts indices in `Settings → Advanced`, and index drift from a new menu
  entry broke three remote tests during the 2.6.1 cycle. Any test that navigates by index
  rather than by label is a candidate.
- [ ] **G6.4** Remote-control virtual keypad on the Focus screen: confirm UP/DOWN reach
  the exposure hold the same way the hardware keys do.

---

## 8. Known gaps and accepted risk

Carried into the release deliberately. Each needs a decision recorded, not just a note.

1. **A mis-stated lens produces no solves and no recovery.** Deliberate (ADR 0027), and
   the failure presents as an exposure problem because auto-exposure steers on match
   count. The mitigation is entirely diagnostic: a log line. **#613 (the troubleshooting
   docs) is filed but not in this release**, which means the release ships a new way to
   stop solving with no user-facing explanation of it. Consider whether #613 should be
   pulled in before the cut — it is a docs-only change.
2. **25 mm on imx296 / imx462 is offered but cannot solve.** Derived 8.26° and 6.26°
   against a pattern database built for `[10°, 30°]`. Verified directly against the
   shipped `default_database.npz` (`min_fov=10.0`, `max_fov=30.0`). The solver logs an
   explicit error. Not a shipped configuration, but the menu does not say so.
3. **The 12 mm lens is uncalibrated** (#612): nominal focal length standing in for a
   measurement, unmeasured SQM zero point, conservative f/2.0.
4. **The Focus screen's exposure hold leaks on an exotic exit route** (G2.12), inherited
   from a pre-existing lifecycle gap that also affects SQM and daytime align. Fixing it
   centrally is unsafe because `dateentry`, `timeentry` and `locationentry` fire commit
   callbacks from `inactive()`.
5. **`Lens` is machine-translated in all four catalogs** and tagged as needing human
   review. The three numeral labels are language-independent. Low risk, but the standing
   unreviewed totals in these catalogs are large and predate this release.
6. **The manual was rewritten wholesale and re-verified by review, not by execution.**
   Thirteen pages. The build is clean and the style is checkable, but "the sentence still
   means what it meant" is a human judgement made once. #604's EQ-platform correction in
   particular *reverses* advice users may have already followed.

---

## 9. Automated review findings

See `release_notes/release-2.6.2-code-review.md` for the full report from the review
pass, including the recorded test counts and docs-build result referenced by Gate 1.

---

## 10. Sign-off

| Gate | Owner | Date | Result |
|---|---|---|---|
| Pre-flight | | | |
| G1 — Automated | | | |
| G2 — Bench, standard hardware | | | |
| G3 — Real lens swap | | | |
| G4 — Upgrade path | | | |
| G5 — Under the stars | | | |
| G6 — Web and API | | | |

**Cut authorised by:** ______________  **Date:** ____________
