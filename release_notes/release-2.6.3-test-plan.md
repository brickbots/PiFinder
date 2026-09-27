# PiFinder v2.6.3 — Release Test Plan

Scope: **everything since the v2.6.1 tag** — 52 commits on `main` @ `0f54d7fc`.
Python: 75 files, +8,188 / −829. The raw repo diffstat (~260k insertions) is dominated
by the rev4 KiCad hardware files, which carry no software risk. This plan covers the
full 2.6.1 → 2.6.3 delta, **folding in the internal-only 2.6.2**: the field population
is on 2.6.1, so everything 2.6.2 changed is still new to every user this release
reaches.

This plan is risk-ordered, not feature-ordered. Each gate has an owner, an explicit
pass criterion, and a note on what a failure blocks. Gates 1–3 must pass before the
`main` → `release` merge; gates 4–6 must pass before the update is offered.

It supersedes `release-2.6.2-test-plan.md`, which remains the reference for the
detailed rationale behind the optics/Focus items carried forward here, and whose
pre-release code review (`release-2.6.2-code-review.md`) still covers the optics work
in depth.

**Status as of 2026-08-25** (`main` @ `0f54d7fc`): **Gate 1 is green** — ruff lint and
format clean, mypy clean (153 files, fresh cache), **1,531 smoke+unit tests passing**,
docs build clean under `-nW`, i18n at 694 msgids × 4 catalogs with 0 untranslated and
all `.mo` files byte-identical to a fresh compile. Pre-flight P1.1–P1.6 verified below.

**Shape of this release, and what that means for testing.** Thirty-three of the 52
commits are documentation. The code splits into two tranches with different evidence
levels:

- **The 2.6.2 tranche** (lens/FOV #608/#609, Focus hold #614/#620, docs) has had
  internal field use since the 2.6.2 cut, plus the full 2.6.2 review. Its hardware
  gates below are *carried, not re-derived* — they were written for a public release
  that never happened, and the public release is now.
- **The post-2.6.2 tranche** (self-heal #624/#625/#628, Nearby #622, observed cache
  #623, unknown train #632, chart readout #633, web validation #571, GPS row #635,
  Stellarium #621) has bench evidence where noted but **no release field time at all**.

The two questions that matter most: **does a never-touched 2.6.1 device still solve
exactly as it did**, and **does a rev4 12 mm unit — the configuration that paused
2.6.2 — now fix itself**. Both have to be answered on real hardware.

---

## 0. Release mechanics — read before cutting

This cut is **not** a fast-forward, unlike 2.6.1 and the internal 2.6.2. State of the
branches:

- `release` = the 2.6.2 cut (`db065b60`) **plus `b485e3be`**, which reverted
  `version.txt` to `2.6.1` — "Pausing 2.6.2 updates until migration for rev4 lensing
  can be sorted". That revert is what has kept every field device from being offered
  2.6.2. It is the only commit on `release` that is not on `main`.
- `main` = 15 commits past the 2.6.2 cut, `version.txt` reading `2.6.3` since
  `bea898ed`.

**The merge.** Merging `main` into `release` conflicts on exactly one file,
`version.txt` (release says 2.6.1, main says 2.6.3) — verified with `git merge-tree`.
Resolve to **2.6.3**. After that resolution the merge tree is **byte-identical to
`main`'s tree** (the pause commit touched nothing else), so testing `main` *is*
testing the cut, same as a fast-forward. Do not rebase or force-push `release` to
"clean up" the pause commit; it is honest history and the merge erases nothing.

**The un-pause criterion.** `b485e3be`'s stated reason is the rev4 lensing problem:
2.6.2 derives the FOV gate from an assumed 16 mm lens, and rev4 units that shipped
with a 12 mm and no configuration saying so stop solving on update. The fix on `main`
is lens self-heal (ADR 0029, #624/#625/#628) — **no migration**, the device measures
its own lens and writes it after three agreeing solves. Therefore: **Gate 3's rev4
12 mm validation is the specific evidence that justifies lifting the pause.** If G3
cannot be run, the pause has no business being lifted, whatever the other gates say.

**Who gets offered what.** `ui/software.py` fetches `release/version.txt` and gates
the update on `update_needed(local, release)`. Once `release` reads 2.6.3:

- **2.6.1 field devices** (the population) are offered 2.6.3. This is the release.
- **2.6.2 internal devices** are offered 2.6.3. Confirm at G4.2 that the 2.6.2 → 2.6.3
  comparison actually opens the gate — these units exist even if no field device took
  2.6.2 during the brief pre-pause window.
- Until the cut, `release/version.txt` still reads 2.6.1 and nobody is offered
  anything. The pause holds by default, which is the right failure mode.

---

## 1. Risk model

What actually changed since v2.6.1, ranked by blast radius × likelihood of an
undetected defect.

| # | Area | PRs | Blast radius | Why it's risky |
|---|---|---|---|---|
| R1 | Solver FOV gate derived from the optical train | #608, #609 | **All users, silent** | Every solve goes through a window computed at runtime from the sensor. A wrong derivation means that sensor never solves; tetra3 enforces the window twice, so failure is total and presents as an exposure problem. |
| R2 | Gate width follows lens confidence + self-heal | #624, #625, #628 | All users; **rev4 12 mm units especially** | The un-pause reason. A never-stated install now gets a *widened* window and the device writes `camera_lens` autonomously after three agreeing solves — the first autonomous config write in the product. A wrong write tightens the window around a lie and the device cannot measure its way out. Mitigations: write-once, never over a statement, never for unmatched glass. |
| R3 | Position server rewrite for Stellarium | #621 | **All SkySafari users** | `pos_server.py` grew ~290 changed lines and now speaks two dialects through shared framing. SkySafari is long-shipped behaviour; a desync (e.g. an unexpected `:Q#` reply) breaks the most-used external integration. Protocol-level tests exist; **no live-app verification is banked yet.** |
| R4 | Web server form handling rewrite | #571 | All web users | `server.py` +441 lines. The failure that motivated it was silent, but the new risk is inverted: over-strict validation rejecting *valid* input locks users out of saving equipment at all. |
| R5 | Focus exposure hold lifecycle | #614, #620 | All users, next-session | A leaked hold pins the camera at manual exposure **and stops zero-match recovery** while Settings still reads "Auto". #620 removed the likeliest route in; three burying routes remain. |
| R6 | Nearby re-rank + 200 cap | #622 | All users | Ranking order changes for everyone (that is the fix). The cap and the cursor-tracking rewrite are new behaviour on the draw path while slewing. |
| R7 | Observed-objects cache bulk query | #623 | Users with logs | A wrong mapping silently mislabels what you have observed; nothing fails. |
| R8 | Chart center-object readout | #633 | Chart users, default **On** | New per-frame work on the chart draw path, on by default. A perf regression shows as chart stutter on a Pi, not on a dev machine. |
| R9 | GPS comms row | #635 | All users | New queue traffic from all three GPS backends (rate-capped 20 Hz) and a new shared-state field drained by the main loop. |
| R10 | Unknown optical train | #632 | Developers, CI — **plus one code path for real cameras** | `optical_train_known()` defaults True; the solver/integrator now branch on it. A real camera taking the wrong branch loses its gate silently. |
| R11 | `CameraProfile` relocation, SQM field width derived | #609 | SQM users, silent | A changed constant shifts every reading without failing. Claim: reproduction within 0.03° (< 0.01 mag). |
| R12 | Manual rewritten wholesale + support corrections | #585–#604, #607 | All users, no code risk | A rewrite can silently change meaning; #604 *reverses* standing advice (EQ platforms → alt-az). |
| R13 | i18n | #609, #633, #571 | Non-English users | 23 new msgids since 2.6.1. **Two new menu entries** (Lens in Settings → Advanced, Center Object in Settings → Chart) shift menu indexes — index drift broke three remote tests in the 2.6.1 cycle. |
| R14 | Restart on lens change | #625 | Menu users | Changing the lens now restarts the PiFinder (tetra3's pattern cache cannot be invalidated). A restart from a menu callback is a new code path. |

---

## 2. Pre-flight — repo housekeeping (verified 2026-08-25)

- [x] **P2.1 — `version.txt` reads `2.6.3` on `main`** (`bea898ed`). Skipping 2.6.2
  publicly is deliberate: 2.6.2 exists on internal devices, and reusing the number
  would make "which 2.6.2" ambiguous forever. `update_needed` must open the gate from
  both 2.6.1 and 2.6.2 (G4.1, G4.2).
- [x] **P2.2 — Merge shape verified.** `git merge-tree origin/release origin/main`
  conflicts on `version.txt` only; the resolved tree equals `main`'s. See §0.
- [x] **P2.3 — `.github/` is byte-identical** between `release` and `main`. The
  release workflow that runs post-cut is the one already exercised.
- [x] **P2.4 — ADR ledger clean on `main`.** 0027–0033 all assigned, no duplicates.
  0030 (nearby) and 0033 (equipment validation) were both renumbered at merge under
  the standing most-referenced-keeps-the-number rule. Reservations went stale twice
  during this cycle — **recompute the free slot at merge time; never trust a
  written-down earmark.** (#502 still carries the old 0018 collision; not this
  release.)
- [x] **P2.5 — i18n release pass.** 23 new msgids since v2.6.1 (`Lens`, `12mm`,
  `16mm`, `25mm`, `Center Object`, and 18 web-validation strings), taking every
  catalog 671 → **694 msgids, 0 untranslated, 0 fuzzy**, no msgid removed. All four
  `.mo` files byte-identical to a fresh `pybabel compile` (verified in a clean
  worktree). Carried residuals, unchanged from the 2.6.2 plan: `Lens` is tagged
  AI-translated pending human review; `"HOLD"` on Focus → Stats is unwrapped alongside
  the equally-unwrapped `"AUTO"`/`"MANUAL"`; the displaced `AI-TRANSLATED` comment in
  es/fr still leaves `GPS Settings` off the human-review queue.
- [x] **P2.6 — Config surface, amended since the 2.6.2 plan.** Two deliberate changes,
  no migration:
  - `default_config.json` gains exactly one key: `"chart_center_object": "On"` (#633).
    A 2.6.1 config without it resolves to On via the defaults fallthrough — confirm at
    G2.40 that the readout appears on an untouched upgrade.
  - **Self-heal may write `camera_lens`** into a config that has never stated one —
    at most once, only after three agreeing solves, never over a user statement, and
    never from an unknown optical train (#632). This is designed behaviour, not a
    migration; G2.3 changes meaning accordingly (absence is expected *until the device
    has measured*, not forever).
  - No `requirements*`, `pyproject.toml` or `noxfile.py` changes since v2.6.1 beyond
    what 2.6.2 already carried; nothing new to stage on the image.

---

## 3. Gate 1 — Automated (CI, ~15 min)

Run on `main` directly — the resolved merge tree equals `main` (P2.2), so there is no
separate merge result to test.

```bash
cd python/
source .venv/bin/activate
git submodule update --init PiFinder/tetra3   # mypy + solver tests need this
nox -s lint
nox -s format
nox -s type_hints
nox -s smoke_tests
nox -s unit_tests
python -m sphinx -nW -b html ../docs/source <out>
```

**Green on `main` @ `0f54d7fc`** (macOS dev venv, Python 3.9, 2026-08-25), clean
worktree, submodule freshly initialised.

- [x] **G1.1** Ruff lint clean; format check clean (267 files).
- [x] **G1.2** MyPy clean — 153 source files, fresh `.mypy_cache`.
- [x] **G1.3** `pytest -m "smoke or unit"` — **1,531 passed, 0 failures**, 490
  deselected. (Was 1,238 at the 2.6.2 cut; the post-2.6.2 tranche added ~290.) A
  materially lower count means test collection broke somewhere.
- [x] **G1.4** New suites confirmed **running, not skipping** — beyond the 2.6.2-era
  optics/Focus suites: `test_pos_server.py` (both dialects), `test_chart_center_object.py`,
  `test_camera_interface.py`, `test_status_gps_comms.py`, `test_gps_ubx_parser.py` /
  `test_gps_ubx_dispatch.py` additions, `test_equipment_validation.py`,
  `test_server_equipment_forms.py`, `test_server_gps_update.py`,
  `test_config_equipment_load.py`, and the `test_lens_self_heal.py` /
  `test_optics_solving.py` additions. `test_optics_solving.py` pushes real
  `test_images/` frames through tetra3 — **verify it did not skip**; if the submodule
  is missing it silently disappears and R10 goes untested.
- [x] **G1.5** Docs build clean — `-nW`, 0 warnings, "build succeeded".

**Blocks:** everything. **Re-run if anything further lands on `main` before the cut.**

---

## 4. Gate 2 — Bench, standard hardware (the population that upgrades)

**The most important gate.** Run on a real unit updated in place from 2.6.1. Indoors
is fine for most of it; use `Tools → Test Mode` for a solvable frame.

The organising question: *does a device nobody has touched behave identically —
except where these notes say it changes?*

### The derived FOV gate and self-heal (R1, R2) — highest priority

Items G2.1–G2.10 carry from the 2.6.2 plan with self-heal amendments.

- [ ] **G2.1** Update from 2.6.1 **without opening the Lens menu**. Confirm the device
  solves. This is the zero-migration path and the one almost every user takes.
- [ ] **G2.2** Check the log for the `Optical train:` line. It must name your sensor,
  say **`assumed`** (not `stated`) before self-heal has run, and carry a gate matching
  the release-notes table — for a never-stated imx296/imx462 that is the **widened
  union window** (ADR 0029), not ±15%. Record the fitted FOV tetra3 reports; a fitted
  value near the edge of the gate rather than the centre is the early warning that the
  derivation is off for your sensor.
- [ ] **G2.3** **Self-heal on the shipped lens.** On a unit with the factory 16 mm
  (or HQ 25 mm) and no stored lens: after three consecutive agreeing solves,
  `camera_lens` appears in `~/PiFinder_data/config.json` naming the lens actually
  fitted, the log line flips `assumed` → `stated`, and the Lens menu shows it checked.
  Confirm the write happens **once** — no rewrite on subsequent solves or reboots.
- [ ] **G2.4** Compare solve rate against 2.6.1 on the same test frame, same
  conditions, **after** self-heal has promoted (so the gate is ±15%, the tight case).
  A measurable drop — not a total failure, a drop — is the signature of a derivation
  that is slightly off. **Subtlest failure mode in the release.**
- [ ] **G2.5** Open `Settings → Advanced → Lens`. Before promotion: the resolved
  default shown as checked with no config entry (not simply the first item — 12 mm is
  first, so a bug here looks like "12mm is checked"). After promotion: the measured
  lens checked.
- [ ] **G2.6** Select the *correct* lens explicitly. **The device restarts** (#625 —
  new since the 2.6.2 plan, which expected an in-place transition). Confirm the
  restart happens, completes cleanly, and solving resumes with `stated` in the log.
- [ ] **G2.7** Select a **wrong** lens. After the restart, solving must stop — and
  **self-heal must not rescue it** (it never overwrites a statement). Confirm the log
  names the stated-but-wrong train. Select the right lens again: restart, solving
  resumes.
- [ ] **G2.8** With no lens ever stated, confirm solving works through the widened
  window **immediately on first boot** — promotion must not be a precondition for
  solving, only for the tight gate.
- [ ] **G2.9** Select **25 mm on an imx296 or imx462**. Confirm the solver logs the
  explicit "outside the solver database range: no frame can solve" error and the
  device does not crash, wedge, or thrash. *(Menu offers it; shipped database cannot
  serve it; see §8.)*
- [ ] **G2.10** Power-cycle with a non-default lens stored. It must survive the
  restart and be picked up by the solver on the first frame.

### Focus screen exposure hold (R5)

Carried unchanged from the 2.6.2 plan (G2.11–G2.18 there, including the burying-route
leak matrix G2.12 a–e and the status-bar checks G2.12b). Run them all; the summary:

- [ ] **G2.20** Entry freezes the settled exposure (off-ladder values included);
  Stats reads `HOLD`; UP/DOWN step the 0.025 s – 1 s ladder and **hold at the ends
  rather than wrap** (the underlying commands apply no clamp — the bound exists only
  in the new code).
- [ ] **G2.21** The standing status bar renders in Stars/Single/Image (arrows
  included — Unicode arrows draw nothing in this font), Image omits the zoom hint,
  Stats has no bar, no star tile is clipped. Check a 176 px panel as well as 128 px if
  available.
- [ ] **G2.22** **The leak matrix.** Leave Focus by each burying route — long-RIGHT to
  object details, POWER button then back out, and an incoming SkySafari/Stellarium
  push (involuntary!) — and confirm the known leak: auto-exposure stays off while
  Settings reads "Auto". Confirm LEFT (the ordinary route) releases the hold, and
  re-selecting Auto in Settings → Camera Exp recovers a leaked session. **The lease
  fix is still outstanding; #620 narrowed the leak, it did not close it. Do not let
  this gate be read as "fixed".**
- [ ] **G2.23** `camera_exp` in config unchanged after a session of nudging; leaving
  Focus normally hands control back to auto within ~35 s.

### Nearby and the observed cache (R6, R7)

- [ ] **G2.30** Nearby sort against a planetarium cross-check: point somewhere off the
  celestial equator (high declination is where the old swapped-axis bug was loudest),
  and confirm the top handful of Nearby results are genuinely the nearest objects on
  the sky. The order **will differ from 2.6.1** — that is the fix, not a regression.
- [ ] **G2.31** Slew steadily and watch the Nearby list re-rank. The top row follows
  the pointing while the cursor sits on it; once scrolled down, the cursor pins to the
  selected object through re-ranks; scrolling back to the top re-arms tracking. No
  stutter on the chart while this happens (the re-rank is on the frame budget).
- [ ] **G2.32** Long-DOWN to the bottom of a Nearby list: it stops at 200 entries,
  the cursor parks on the last row, and **RIGHT on that row opens details** (the
  IndexError fix). The header still reports the catalog's full size.
- [ ] **G2.33** Cross the meridian (RA wrap) and work near the pole; confirm no
  visible re-rank storms or stalls (the old trigger fired continuously in a band
  around the meridian — pure cost, so only observable as load).
- [ ] **G2.34** Chart nearby-DSO markers: confirm objects visibly in the field carry
  markers — at high declination especially. A missing marker was the silent half of
  the swapped-axis bug.
- [ ] **G2.35** On a device with a long observing log: opening Object Details is fast
  (no rebuild stall), and observed checkmarks are correct across *all* catalog names
  of a logged object (log an object under one designation, confirm it shows observed
  under its cross-designations).
- [ ] **G2.36** Remote web interface: open an object **from a Nearby-sorted list** and
  confirm the object-details view populates (it was silently blank on this path).

### Chart center-object readout (R8)

- [ ] **G2.40** On an untouched upgrade, the readout **appears by default**: bottom of
  the chart, designator + first cross-name, marquee when long, arrow glyph shown.
- [ ] **G2.41** RIGHT opens the named object's details; LEFT returns to the chart.
  With the readout **Off** (`Settings → Chart → Center Object`), the line is gone and
  RIGHT is inert, exactly as 2.6.1.
- [ ] **G2.42** Slew slowly between two comparably-near objects: the readout must hold
  its choice rather than flapping (stickiness), and must never name an object outside
  the visible screen.
- [ ] **G2.43** Chart frame rate on the Pi with the readout on: the marquee animates
  smoothly and the chart does not stutter versus readout-off. (The strip repaints
  per frame from a cached backdrop; the projection is batched — this checks both
  survived contact with real hardware.)
- [ ] **G2.44** No solve yet / blank field: readout blank, RIGHT inert, no crash.

### GPS MSG row (R9)

- [ ] **G2.50** STATUS screen shows the `GPS MSG` row. With a healthy receiver the
  event name churns and the age sits near zero, **and does not read a constant
  offset** (the cross-process monotonic bug presented as a steady ~4 s staleness —
  stamp-at-drain is the fix; confirm it held on the Pi).
- [ ] **G2.51** Unplug/disconnect the GPS (or kill gpsd): the name freezes and the age
  climbs. Reconnect: it recovers.
- [ ] **G2.52** If a UBX receiver is on the bench: confirm `?NNNN`-style markers for
  unregistered message classes appear rather than nothing (a u-blox M9/M10 emits
  dialects the parser does not decode — the row is how that now shows). `?CKSUM`
  requires corrupted bytes; do not chase it if it does not occur naturally.
- [ ] **G2.53** Confirm both backends: GPSD and UBX direct. The fake GPS covers the
  third in `-fh` runs.
- [ ] **G2.54** Leave the unit running an hour: no queue growth, no STATUS screen
  slowdown (the 20 Hz cap is the guard; this is the check that it engaged).

### Everything else (carried)

- [ ] **G2.60** SQM: reading before/after update under stable conditions moves less
  than ~0.05 mag (claim is < 0.01); calibration state survives; field width follows a
  lens change after the restart.
- [ ] **G2.61** Chart frustum + align screens follow the derived FOV; zoom scales.
- [ ] **G2.62** Menu navigation around **both** new entries — Lens in
  `Settings → Advanced`, Center Object in `Settings → Chart`: neighbours above and
  below still open what their labels say.
- [ ] **G2.63** Full boot → GPS lock → solve → object details → push-to, nothing
  configured — the ordinary path, end to end.
- [ ] **G2.64** Camera Type switch with a lens explicitly stored: the stale
  `camera_lens` carries onto the new sensor and can stop solving with nothing in the
  log (2.6.2 review finding 3 — **still open**). Confirm behaviour and file the
  one-line `switch_cam_*` fix if it bites.
- [ ] **G2.65** Developer path: `-fh --camera debug` **with a lens stated in the dev
  config** solves (the #632 fix — this was broken for any developer who had opened the
  Lens menu), and self-heal writes **nothing** to config from debug frames, with the
  unknown-train line in the log. Also confirm a real camera still logs a gate
  (`optical_train_known` defaulting True is what protects it — this is R10's
  real-hardware half, covered incidentally by every other G2 item, but read the log
  once deliberately).

---

## 5. Gate 3 — Real lens swap and the rev4 12 mm (the un-pause gate)

Everything above tests declarations and defaults. This gate tests the two things the
release exists to enable, and **G3.1–G3.3 are the evidence that justifies lifting the
2.6.2 pause** (§0).

- [ ] **G3.1** **The pause scenario, forward.** A rev4 imx462 with a factory 12 mm
  lens and no `camera_lens` in config, updated 2.6.1 → 2.6.3: it must keep solving
  through the widened window from the first frame, then promote to the 12 mm after
  three agreeing solves — config written once, menu shows 12mm, log flips to
  `stated`, gate tightens to ±15%. *(Bench evidence exists from #628 development on
  the board that surfaced the bug; this item is the release-build confirmation.)*
- [ ] **G3.2** **The pause scenario, rescue.** A unit that took the internal 2.6.2 and
  is currently *not solving* (12 mm glass, assumed 16 mm): update to 2.6.3 and confirm
  it recovers unattended — this is the population the pause protected, rescued rather
  than avoided.
- [ ] **G3.3** Swap 12 mm ↔ 16 mm on one board, both directions, stating each
  correctly in the menu: solves both ways, fitted FOV lands near the derived value
  (12.44° / 10.40° on imx462).
- [ ] **G3.4** Declare the 12 mm while the 16 mm is fitted and vice versa: both
  directions stop solving; recovery is correcting the menu (self-heal must **not**
  intervene over a statement).
- [ ] **G3.5** SQM with the 12 mm fitted: record against a reference meter if
  available. Its zero point is still the 16 mm's and the f-number is a conservative
  assumption — the residual of #612; the reading is expected to be off, and this
  observation is what closes it.

**Blocks:** G3.1/G3.2 block the un-pause, and therefore the release. If no 12 mm unit
is available, say so in the release notes explicitly and decide the pause question
with eyes open rather than by omission.

---

## 6. Gate 4 — Upgrade paths and fresh install

- [ ] **G4.1** Update a real 2.6.1 device in place. Confirm the update **is offered at
  all** once `release` carries 2.6.3, then that it boots, solves, and the Status
  screen reads **2.6.3**.
- [ ] **G4.2** Update a 2.6.2 internal device the same way. `update_needed(2.6.2,
  2.6.3)` must open the gate — this population exists even if it never left the
  house.
- [ ] **G4.3** Confirm config is not rewritten on update and gains no new keys **until
  self-heal legitimately writes `camera_lens`** (P2.6). `chart_center_object` must
  *not* be written — it resolves from defaults.
- [ ] **G4.4** Fresh install from the published image: boot, configure, solve.
- [ ] **G4.5** Update a device with non-default `camera_type` (HQ): resolves to 25 mm
  and solves.
- [ ] **G4.6** Hand-edit `camera_lens` to garbage (`"18mm"`) and restart: degrades
  sensibly, boots, Lens menu opens. Hand-edit `camera_type` to an unknown sensor:
  Lens menu still opens.

---

## 7. Gate 5 — Under the stars

- [ ] **G5.1** A full night on standard hardware, shipped lens, nothing reconfigured.
  Solve rate indistinguishable from 2.6.1. **This is the real R1 test** — a bench
  frame exercises one field; the gate is a window.
- [ ] **G5.2** Solve across altitudes and star densities — sparse near the pole, dense
  in the Milky Way. The tightened post-promotion gate has the most to lose where
  matches are already marginal.
- [ ] **G5.3** A real focus session start to finish: HFD moves only when the lens
  turns; solving recovers to normal rate within a minute of leaving the screen.
- [ ] **G5.4** Nearby in real use: slew, pick, push-to. The ranked objects are the
  ones actually near the pointing, at every part of the sky visited.
- [ ] **G5.5** The chart readout across a session: names track the slew, marquee
  legible in the dark, RIGHT-to-details flow feels right at the eyepiece.
- [ ] **G5.6** SQM across a full night against a 2.6.1 night at the same site if one
  is on record.
- [ ] **G5.7** Self-heal's "first clear night" story on any never-stated unit present:
  it should be promoted by the end of the night without anyone touching the menu.

---

## 8. Gate 6 — Web, API, and planetarium protocol

- [ ] **G6.1** Selenium suite. **Check specifically for menu-index drift** — *two* new
  menu entries this release (Lens, Center Object); index drift broke three remote
  tests in the 2.6.1 cycle. Any test navigating by index is a candidate.
- [ ] **G6.2** `/api/current-selection` reports the center object when the readout is
  on, and `null` when it is off (not the last-picked object — the tracker must clear).
- [ ] **G6.3** Web chart renders with the frustum following the derived FOV; chart API
  reflects a lens change after its restart.
- [ ] **G6.4** **Web equipment forms, happy path first** (R4's inverted risk): add,
  edit and delete an eyepiece and an instrument with ordinary valid values in en-US —
  everything saves and survives a reload. Then the rejects: decimal comma, blank
  name, out-of-range values — each re-renders the form with a message and the typed
  values, in the browser's language (spot-check one non-English locale). Confirm a
  fractional aperture (279.4 mm) round-trips config load (#291).
- [ ] **G6.5** `/gps/update` with a decimal-comma coordinate: a clean validation
  message, not a 500 (this exact input was the G6.2 finding in the 2.6.1 validation
  pass). A bad clock entry must not half-apply a position.
- [ ] **G6.6** DeepskyLog import with a file containing unreadable records: good
  records land, bad ones are skipped and counted, none written through.
- [ ] **G6.7** **SkySafari live regression** (R3): connect the real app; position
  readout tracks, goto pushes to the observing list, connect/disconnect cycles clean.
  Run it *after* a Stellarium session against the same server instance to catch
  state bleeding between dialects (per-connection reset is the designed guard).
- [ ] **G6.8** **Stellarium live** (R3 — **no hardware evidence banked**): Stellarium
  desktop *and* Mobile Plus if available, Meade LX200 compatible at port 4030.
  Position marker tracks; select-and-push lands the object in the observing list;
  the site/clock it sends on connect does **not** change the PiFinder's location or
  time (GPS stays authoritative). Confirm a pushed object's details screen does not
  mislabel the source.
- [ ] **G6.9** Remote virtual keypad on the Focus screen: UP/DOWN reach the exposure
  hold the same as hardware keys.

---

## 9. Known gaps and accepted risk

Carried or new, each a decision, not just a note.

1. **A mis-stated lens still means no solves and no self-rescue** — self-heal writes
   into an absence, never over a statement (ADR 0029). *Now mitigated as designed:*
   the troubleshooting path shipped (#613 done) and the log names stated vs assumed.
2. **Changing the physical lens after promotion deadlocks** like any stated lens —
   and newly reaches people who never opened the menu. The cure (re-open the gate on
   sustained zero matches with adequate centroids) is #611, not this release.
3. **A Camera Type switch does not clear the stored lens** (G2.64, review finding 3).
   Still a one-line fix in `switch_cam_*`; still not done.
4. **25 mm on imx296/imx462 is offered but cannot solve** (database floor). The menu
   does not say so.
5. **The 12 mm is partly calibrated**: focal length measured (13.04 mm, single
   sample); SQM zero point and f-number still the 16 mm's / assumed (#612 residual).
6. **The Focus exposure hold still leaks when the screen is buried** (G2.22): three
   routes, one involuntary. The lease fix is the outstanding close; #620 only removed
   the likeliest route.
7. **A Nearby list stops silently at 200**; the RA sort is implemented but not
   selectable from the Quick Menu.
8. **Stellarium is protocol-verified, not field-verified** until G6.8 runs. The
   SkySafari-protecting gates (ACK-conditional `:Q#`, per-connection reset) are the
   specific things to distrust until then.
9. **The center-object readout shows catalog designations** ("M 45 Cr 42", not
   "Pleiades") — shared convention with the object lists, recorded as a naming
   decision still open, not a bug.
10. **The manual rewrite is verified by review, not execution**; #604 reverses
    standing EQ-platform advice users may have followed.

---

## 10. Prior review

The three-agent pre-release code review from the 2.6.2 cycle
(`release-2.6.2-code-review.md`) remains the deep reference for the optics work.
Status of its findings as of this plan: **1 fixed** (version gate — now 2.6.3),
**2 narrowed, open** (Focus hold leak → G2.22), **3 open** (stale lens on camera
switch → G2.64), **4 fixed** (#613 shipped the lens troubleshooting docs), **5–6
accepted** (§9.4, frustum on 320×240), **7 open** (SQM archive scripts ignore the
recorded lens — fix before anyone runs #612's sweep), **8 fixed** (#632), **9–13 as
recorded**. The post-2.6.2 tranche (#621, #622, #623, #624, #571, #632, #633, #635)
was reviewed per-PR rather than by a dedicated release review; its riskiest surfaces
are gated at G3 and G6.7/G6.8 above.

---

## 11. Sign-off

| Gate | Owner | Date | Result |
|---|---|---|---|
| Pre-flight (§2) | Claude | 2026-08-25 | ✅ verified |
| G1 — Automated | Claude | 2026-08-25 | ✅ green @ `0f54d7fc` |
| G2 — Bench, standard hardware | | | |
| G3 — Lens swap + rev4 12 mm (un-pause) | | | |
| G4 — Upgrade paths | | | |
| G5 — Under the stars | | | |
| G6 — Web, API, planetarium | | | |

**Un-pause justified by G3:** ______________  **Cut authorised by:** ______________  **Date:** ____________
