# PiFinder v2.6.2 — Release Test Plan

Scope: everything on `main` that is not yet on `release` — 25 commits, 70 files,
+5,310 / −2,001 (Python: 32 files, +2,501 / −536; of which ~1,100 lines are new tests).

This plan is risk-ordered, not feature-ordered. Each gate has an owner, an explicit
pass criterion, and a note on what a failure blocks. Gates 1–3 must pass before the
`main` → `release` merge; gates 4–6 must pass before the update manifest is published.

**Status as of 2026-08-15** (`main` @ `db065b60`): `release` is an ancestor of `main`,
so the cut is a **fast-forward** with no conflicts to resolve. `.github/` is
byte-identical between the two branches, so the release workflow that runs post-cut is
the one already exercised on `release`. Gate 1 is green.

> **Both pre-cut blockers from the pre-release review (§9) are now resolved.**
> **(1)** `version.txt` reads **2.6.2** on `main` as of `db065b60` (**P1.1**).
> **(2)** #620 removed the Focus screen's Quick Menu Exposure jump, which was the
> ordinary route into the exposure-hold leak, and replaced the transient exposure
> readout with a standing status bar (**G2.12**). **This narrows the leak, it does not
> close it** — three routes still bury the screen, so G2.12 remains a real test item and
> the lease fix is still outstanding.
>
> Two cheap fixes remain recommended but unblocking: clearing `camera_lens` on a Camera
> Type switch (**G2.26**), and pulling in the docs-only #613 so that ADR 0027's accepted
> risk is actually mitigated (**§8.1**).

**Shape of this release, and what that means for testing.** Eighteen of the 25 commits
are documentation. The code surface is small — two features plus one fix — but one of
them sits
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
| R4 | Focus exposure hold lifecycle | #614, #620 | All users, next-session | A hold that is not released leaves the camera at a fixed manual exposure for the rest of the session **and stops zero-match recovery**, while Settings still reads "Auto". #620 removed the likeliest route in and reworked the on-screen readout into a standing status bar; three burying routes remain (see G2.12). New surface of its own: the bar changed tile geometry on every Focus view (G2.12b). |
| R5 | Debug camera relabelled `imx296` → `hq` | #609 | Developers, CI | If wrong, `-fh --camera debug` stops solving for every developer and every automated test that solves a frame. |
| R6 | Live lens re-read in the solver loop | #609 | All users | The train is resolved per frame from shared state. New shared-state reads inside the hot loop; a manager disconnect or a bad value must not wedge the loop. |
| R7 | Chart frustum + web chart API | #609 | Visual / web | Frustum shading now follows the derived value in two places. Cosmetic on the device, but the web chart API is a separate consumer that can fail independently. |
| R8 | Manual rewritten wholesale | #585–#600, #604, #607 | All users, **no code risk** | 13 pages rewritten. The risk is not breakage but *accuracy*: a rewrite can silently change meaning. #604 additionally reverses standing advice (EQ platforms → alt-az). |
| R9 | i18n | #609 | Non-English users | Four new msgids. One is machine-translated and unreviewed. Menu-index drift from a new menu entry has broken web remote tests in this project before. |
| R10 | SQM field width now derived | #609 | SQM users, silent | `radiometric_fov_degrees` was deleted as a stored constant. The claim is reproduction to within 0.03° (< 0.01 mag). If wrong, every SQM reading shifts and nothing fails. |

---

## 1. Pre-flight — repo housekeeping (before any testing)

- [x] **P1.1 — `version.txt` bumped to `2.6.2`** on `main` at `db065b60`. This was a
  release blocker, not housekeeping: `ui/software.py:245` fetches `release/version.txt`
  from GitHub and line 353 gates the update on `update_needed(self._software_version,
  self._release_version)`. Had `release` shipped 2.6.2 code with `2.6.1` in the file,
  **every existing device would have compared 2.6.1 against 2.6.1, rendered "No Update
  needed", and never been offered the update at all** — the release would have been
  invisible in the field. The Software screen, `splash.py:49`, `server.py:216` and
  `api_extensions.py:851` would also have misreported the version on every bug report.
  - **Re-run Gate 1 after this and any later commit**, and confirm on hardware at
    **G4.1** that the Status screen actually reads 2.6.2.
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

**Gate 1 is green on `main` @ `db065b60`** (macOS dev venv, Python 3.9, 2026-08-15),
re-run after #620 and the version bump. Run in clean worktrees rooted on `origin/main`
with the `tetra3` submodule freshly initialised, with reproducible results.

- [x] **G1.1** Ruff lint + format clean.
- [x] **G1.2** MyPy clean. Needs the `tetra3` submodule initialised; a stale
  `.mypy_cache` reports a phantom error, so clear it if the count disagrees.
- [x] **G1.3** `pytest -m "smoke or unit"` — **1,238 passed, 0 failures**, 472
  deselected (the non-smoke/unit markers). Reproduced exactly on a clean tree. (Was
  1,229 before #620, which added the Focus status-bar tests.) A materially lower count
  means test collection broke somewhere.
- [x] **G1.4** New suites confirmed **running, not skipping** — `test_optics.py`,
  `test_optics_solving.py`, `test_plot_frustum.py`, `test_lens_menu_callback.py`, plus
  the additions to `test_focus_preview.py` (now including the #620 status-bar and
  marking-menu tests) and `test_sqm.py`. `test_optics_solving.py`
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
- [ ] **G2.12** **The leak test — see review finding 2. Narrowed by #620, not closed.**
  The pre-release review confirmed, by driving the real `MenuManager`, that the exposure
  hold leaks whenever the Focus screen is *buried* rather than left with LEFT, and that
  the consequence is larger than #614 documented: `set_exp_transient` clears
  `_auto_exposure_enabled` in the camera process, and only `set_exp:auto` ever sets it
  back. A leaked hold therefore pins the camera at a manual exposure **and stops
  zero-match recovery for the rest of the session**, while Settings → Camera Exp still
  shows "Auto".
  #620 removed the Focus screen's Quick Menu Exposure jump, which was the one route an
  ordinary user was likely to take. The remaining routes are less likely but not
  hypothetical — and route **d** is *involuntary*, the user does nothing.
  Enter Focus, leave by each route, then watch the exposure for 60 s:
  - [x] **a.** Focus → Quick Menu → Exposure → long-LEFT. **Route removed by #620.**
        Instead confirm the Quick Menu on the Focus screen now offers **HELP only**, and
        that HELP still opens (nulling the menu would have taken the help with it).
  - [ ] **b.** Focus → long-RIGHT to object details → long-LEFT. *(Needs a non-empty
        recent list, so view an object first.)*
  - [ ] **c.** Focus → POWER button → long-LEFT (back out instead of confirming).
  - [ ] **d.** Focus open, push an object from SkySafari, then long-LEFT. **The user
        initiates nothing here** — `pos_server` calls `jump_to_label("recent")`.
  - [ ] **e.** Control: Focus → LEFT. This route is correct and must release the hold.
  For each leaking route, confirm the observable consequence: does auto exposure resume,
  does solving recover, and does Camera Exp still read "Auto"? Then confirm re-entering
  and leaving Focus with LEFT releases it, and that re-selecting Auto in Settings →
  Camera Exp recovers a leaked session.
  **Still outstanding:** the real fix is a self-expiring lease on the transient exposure,
  renewed per frame by the screen and dropped by the camera process on expiry (the
  black-level lease is the in-repo precedent). Making Focus `stateful` does **not** work
  — the `state` check in `add_to_stack` is on the pushed item, not the buried one.
  **Do not let #620 close this ticket.**

- [ ] **G2.12b** **The new Focus status bar (#620).** In **Stars**, **Single** and
  **Image**, a standing bar along the bottom shows the held exposure on the left and the
  keys on the right. Confirm:
  - [ ] The bar is present and readable, and the **arrows actually render** — Unicode
        arrows draw nothing in this font, so this is worth looking at rather than
        assuming.
  - [ ] The exposure in the bar tracks UP/DOWN immediately.
  - [ ] **Image** shows the exposure keys only, with no zoom hint (`+`/`-` do nothing
        there).
  - [ ] **Stats** has *no* bar, and still reports `HOLD` and the exposure itself.
  - [ ] No star tile is clipped or overdrawn by the bar — the rows are reserved out of
        the camera area, so the tiles should be slightly shorter, not covered.
  - [ ] Check on a 176px panel as well as 128px if one is available; the bar height is
        derived from panel resolution.
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
- [ ] **G2.26** **Camera Type switch with a lens explicitly stored (review finding 3).**
  Select a lens explicitly, then change `Settings → Advanced → Camera Type` and let the
  device reboot. Confirm what `camera_lens` reads afterwards. Nothing clears it today, so
  the old declaration is expected to carry onto the new sensor — and for a v3 → HQ swap
  the resulting gate `[14.55, 19.69]` **overlaps** the database range, so
  `_warn_if_outside_solver_database` does *not* fire and the log says nothing beyond a
  cheerful `Optical train: 16mm lens on hq`. Confirm whether solving stops, and whether
  anything at all surfaces why. The one-line fix is to clear `camera_lens` in the
  `switch_cam_*` callbacks.
- [ ] **G2.27** **Frustum on a 320×240 display, if one is in test (review finding 6).**
  On an `st7789` / `pg_320` display, open Align and step the chart FOV up to 60°.
  `frustum_box` derives its vertical extent from the width, so at ratios below 0.25 the
  box inverts and `ImageDraw.rectangle` raises `ValueError: y1 must be greater than or
  equal to y0`. **Pre-existing — `release` has the identical formula, and for shipped
  sensors 2.6.2 actually raises the threshold from 38° to ~55°** — so this is a
  confirm-and-file item, not a blocker. Square panels (128 / 176), which is the
  mainstream shipped hardware, are unaffected.

---

## 4. Gate 3 — Real lens swap (the feature's actual purpose)

Everything above tests the *declaration*. This gate tests the thing the release exists
to enable. Needs a physically different lens.

- [ ] **G3.1** Fit a 12 mm lens to an imx296 or imx462. Declare it in the menu. Confirm
  it solves. **On 2.6.1 the imx296 + 12 mm combination could not solve at all** (16.4°,
  outside the old `[8.0, 16.0]` window) — this is the headline capability and it has to
  be demonstrated on real hardware, not re-projected frames.
- [ ] **G3.2** With the 12 mm physically fitted, confirm the fitted FOV tetra3 reports
  lands near the derived 16.38° (imx296) or 12.44° (imx462).
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

- [ ] **G4.1** Update a real 2.6.1 device in place. Confirm the update **is offered at
  all**, then that it boots, solves, and reports `2.6.2` on the Status screen. This is
  the end-to-end proof of P1.1: that the version gate opened, not just that the code
  shipped.
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
   count. The mitigation is entirely diagnostic: a log line. **ADR 0027 accepts this risk
   on the explicit grounds that "the troubleshooting path documents cleanly" — and that
   documentation is not in this release.** `menu_map.rst` has no Lens entry,
   `user_guide.rst:967` still lists the once-configured settings as "PiFinder Type,
   Camera Type, and GPS Settings", and `troubleshooting.rst` has no lens/no-solve
   symptom. **#613 is filed, is docs-only, and would convert an unmitigated risk into the
   mitigated one the ADR assumed. Strongly consider pulling it into the cut** — it is
   incongruous for a release that rewrites the entire manual to ship its one new user
   setting undocumented.
   - **Additionally, the lens is not invalidated by a Camera Type switch** (G2.26), so a
     user can end up with a wrong lens without ever having mis-stated one.
2. **25 mm on imx296 / imx462 is offered but cannot solve.** Derived 8.26° and 6.26°
   against a pattern database built for `[10°, 30°]`. Verified directly against the
   shipped `default_database.npz` (`min_fov=10.0`, `max_fov=30.0`). The solver logs an
   explicit error. Not a shipped configuration, but the menu does not say so.
3. **The 12 mm lens is uncalibrated** (#612): nominal focal length standing in for a
   measurement, unmeasured SQM zero point, conservative f/2.0.
4. **The Focus screen's exposure hold still leaks when the screen is buried**, killing
   auto-exposure and zero-match recovery for the session (G2.12, review finding 2).
   Inherited from a pre-existing lifecycle gap that also affects SQM and daytime align —
   but the hold is what converts that dormant gap into a camera-state bug.
   **#620 removed the Quick Menu Exposure jump**, which was the one route an ordinary
   user was likely to take, so this is no longer a candidate blocker. It is now accepted
   risk with three routes left: long-RIGHT to object details, the power button, and an
   object push from SkySafari — **the last of which the user does not initiate**. Fixing
   the lifecycle centrally is unsafe because `dateentry`, `timeentry` and
   `locationentry` fire commit callbacks from `inactive()`; a self-expiring lease on the
   transient exposure closes every route without touching that asymmetry, and remains the
   outstanding fix.
   - Side effect of #620 worth stating plainly: **the Focus screen can no longer persist
     an exposure at all.** #614 designed the Quick Menu jump as "the one deliberate way
     to save a value" from that screen; saving now means `Settings → Camera Exp`. The
     docs were updated to redirect readers there.
5. **`Lens` is machine-translated in all four catalogs** and tagged as needing human
   review. The three numeral labels are language-independent. Low risk, but the standing
   unreviewed totals in these catalogs are large and predate this release.
6. **The manual was rewritten wholesale and re-verified by review, not by execution.**
   Thirteen pages. The build is clean and the style is checkable, but "the sentence still
   means what it meant" is a human judgement made once. #604's EQ-platform correction in
   particular *reverses* advice users may have already followed.

---

## 9. Pre-release code review — summary

Full report: **`release_notes/release-2.6.2-code-review.md`**. Three independent review
agents with non-overlapping briefs, every finding re-verified against source, several
re-derived numerically or executed.

| # | Severity | Summary | Gate |
|---|---|---|---|
| 1 | ~~**Blocker**~~ **FIXED** | `version.txt` still `2.6.1` — the update is never offered to any device. **Bumped at `db065b60`.** | P1.1 |
| 2 | ~~**High**~~ **Medium** | Focus exposure hold leaks; kills auto-exposure + zero-match recovery for the session. **#620 removed the ordinary route in; three burying routes remain.** | G2.12 |
| 3 | Medium | Stale `camera_lens` after a Camera Type switch stops solving; the warning does not fire | G2.26 |
| 4 | Medium | The Lens setting has no user documentation — ADR 0027's accepted risk is unmitigated | §8.1 |
| 5 | Medium | Menu offers 25 mm on imx296/imx462, which the shipped database cannot solve | G2.9 |
| 6 | Medium | `frustum_box` vertical extent derived from width; inverts and raises on 320×240 (**pre-existing**) | G2.27 |
| 7 | Low | SQM archive re-analysis scripts ignore the lens the archive now records | — |
| 8 | Low | `--camera debug` breaks for any developer who has opened the Lens menu | — |
| 9 | Low | `CameraProfile` field defaults let a new profile produce a silently broken gate | — |
| 10 | Low | An unrecognised lens key falls back with nothing in the log | — |
| 11 | Low | Unsynchronised optical-train cache across waitress threads | G6.2 |
| 12 | Low | `"HOLD"` unwrapped for i18n; `AI-TRANSLATED` marker displaced in es/fr | P1.5 |
| 13 | Info | ADR 0027's "within 0.02°" is really 0.0226°; `state.py` loads `Config()` twice | — |

**The review's positive result matters as much as the findings.** The optics math is
correct against tetra3's own FOV definition and the real capture pipeline; the
zero-migration path has no `KeyError` and reproduces the retired constants to under
0.005 mag; the relocated camera profiles carry **zero numeric change** to any radiometric
constant; all four shipped trains sit inside the pattern database; and the debug-camera
relabel is genuinely end-to-end tested against real frames. Findings 7–13 can all ship.

**Findings 1 and 2 are addressed** — 1 by the version bump at `db065b60`, 2 by #620,
which narrows rather than closes it. Findings 3 and 4 remain cheap and high value: 3 is a
one-line change in the `switch_cam_*` callbacks, 4 is pulling in the already-filed
docs-only #613. **Fix finding 7 before anyone runs the 12 mm sweep #612 asks for**, or
the refitted constants will carry a ≈ 0.56 mag systematic.

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
