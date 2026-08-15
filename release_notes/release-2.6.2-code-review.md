# PiFinder v2.6.2 — Pre-Release Code Review

Scope: `origin/release..origin/main` @ `6aad0645` — 23 commits, 68 files,
+5,088 / −1,976.

> **Status update, 2026-08-15.** Findings **1** and **2** have since been addressed:
> `version.txt` was bumped to 2.6.2 at `db065b60`, and **#620** removed the Focus
> screen's Quick Menu Exposure jump and replaced the transient exposure readout with a
> standing status bar. #620 **narrows finding 2 rather than closing it** — three routes
> still bury the Focus screen and strand the hold. The per-finding entries below are
> annotated; everything else stands as written and was reviewed against `6aad0645`. Eighteen commits are documentation; the reviewed code surface is
`PiFinder.optics` (new), `PiFinder.camera_profiles` (relocated), `solver.py`, `plot.py`,
`ui/preview.py`, `ui/callbacks.py`, `ui/menu_structure.py`, `ui/text_menu.py`,
`ui/align.py`, `state.py`, `api_extensions.py`, and the `sqm/` refactor.

**Method.** Three independent review agents with non-overlapping briefs — (a) optics /
camera profiles / solver / plot, (b) UI and shared state, (c) cross-cutting: SQM
refactor, i18n, upgrade path, build health. Each was instructed to try to *refute* its
own findings before reporting. Every finding below was then independently re-verified in
this session against the source, and several were re-derived numerically or executed.
Where the agents disagreed with each other or overstated a consequence, the version
below is the corrected one.

**Verdict: one blocker, one high-severity defect worth holding the cut for, and a set
of medium issues that are release-readiness rather than correctness.** The core optics
work is in good shape — the math is right, the zero-migration claim holds, and the
constants survived their move byte-identical. The problems are at the edges, and they
share a theme: **nothing ties the configured lens to the sensor actually in use**, and
the accepted risk in ADR 0027 was accepted on the strength of documentation that has
not been written.

---

## Findings

| # | Severity | Area | Summary |
|---|---|---|---|
| 1 | ~~Blocker~~ **fixed** | Release mechanics | `version.txt` still reads `2.6.1`; cutting as-is makes the release un-installable and invisible — **bumped at `db065b60`** |
| 2 | ~~High~~ **Medium** | Focus screen | The exposure hold leaks by ordinary routes, killing auto-exposure and zero-match recovery for the rest of the session — **#620 removed the ordinary route; three remain** |
| 3 | Medium | Optics | A stale `camera_lens` after an in-device Camera Type switch silently stops all solving, and the safety net does not fire |
| 4 | Medium | Docs | The Lens setting has no user documentation — the risk ADR 0027 accepted is unmitigated |
| 5 | Medium | Optics | The menu offers 25 mm on imx296 / imx462, which the shipped pattern database cannot solve |
| 6 | Medium | Chart | `frustum_box` derives the vertical extent from the width; on non-square displays it is wrong and can raise |
| 7 | Low | SQM tooling | Archive re-analysis scripts ignore the lens the archive now records |
| 8 | Low | Dev | `--camera debug` stops solving for any developer who has ever opened the Lens menu |
| 9 | Low | Optics | `CameraProfile` field defaults let a new profile produce a silently broken gate |
| 10 | Low | Optics | An unrecognised lens key falls back with nothing in the log |
| 11 | Low | Web API | Unsynchronised optical-train cache shared across waitress threads |
| 12 | Low | i18n | `"HOLD"` is unwrapped; the `AI-TRANSLATED` marker was displaced in es/fr |
| 13 | Info | — | ADR 0027's "within 0.02°" is really 0.0226°; `state.py` loads `Config()` twice |

---

### 1. ~~BLOCKER~~ FIXED — `version.txt` was still `2.6.1`; the release would have been invisible in the field

> **Resolved at `db065b60`:** `version.txt` on `main` now reads `2.6.2`. Verify
> end-to-end at **G4.1** that a real 2.6.1 device is actually *offered* the update —
> that is the behaviour this finding was about, not the file contents.

**`version.txt`** — `git diff origin/release..origin/main -- version.txt` is empty. Both
branches read `2.6.1`. The bump to `2.6.2` exists **only as an uncommitted edit in the
maintainer's working copy**.

This is not merely a cosmetic version-string problem. `ui/software.py:245` fetches
`raw.githubusercontent.com/brickbots/PiFinder/release/version.txt` into
`_release_version`, and line 353 gates the update on
`update_needed(self._software_version.strip(), self._release_version.strip())`. If
`release` ships 2.6.2 code with `2.6.1` in the file, **every existing 2.6.1 device
compares `2.6.1` against `2.6.1`, renders "No Update needed", and `_go_for_update` is
never set — the update is never offered at all.**

Secondary: the Software screen, `splash.py:49`, `server.py:216` and
`api_extensions.py:851` would all report `2.6.1` for 2.6.2 code, misattributing every
field bug report for the life of the release.

**Fix:** commit the bump to `main` before the cut, then re-run Gate 1.

---

### 2. ~~HIGH~~ MEDIUM — The Focus screen's exposure hold leaks, and takes auto-exposure down with it

> **Narrowed by #620, not closed.** The Quick Menu Exposure jump — the one route an
> ordinary user was likely to take — is gone, and the transient top-left readout became a
> standing bottom status bar carrying the exposure and the UP/DOWN keys that replaced the
> jump. The marking menu was kept (blanking `left` rather than nulling the menu) because
> `MarkingMenu.up` defaults to HELP and this screen has help pages.
>
> **Routes b, c and d in the table below still leak**, and **d is involuntary**. The
> lease fix remains the real cure and is still outstanding — see the fix options at the
> end of this finding. Do not treat #620 as closing this.
>
> One deliberate consequence: the Focus screen can no longer persist an exposure at all.
> Saving now means `Settings → Camera Exp`, and the docs were updated to say so.

**`ui/preview.py:153-171`** (`inactive()`), enabled by
**`ui/menu_manager.py:190-218`** (`add_to_stack`) and **`:414-428`** (`key_long_left`).

`_begin_exposure_hold()` sends `set_exp_transient:<µs>`, which sets
`_auto_exposure_enabled = False` in the camera process (`camera_interface.py:558-573`).
The only things that ever set it back are the `set_exp:auto` command
(`camera_interface.py:523-533`) and camera-process startup. The release path is
`inactive()` and nothing else.

`add_to_stack` calls `inactive()` on the outgoing screen **only when the incoming item
carries a preloaded `state`**:

```python
if item.get("state") is not None:
    self.stack[-1].inactive()
    self.stack.append(item["state"])
else:
    self.stack.append(item["class"](...))
```

The Focus item (`menu_structure.py:50-53`) is neither `stateful` nor `preload`, so
anything pushed over it buries it silently. `key_long_left` then calls `inactive()` on
`self.stack[-1]` only and truncates the stack, discarding the buried Focus instance with
`_exposure_hold_active = True`.

**Consequence:** the camera stays pinned at a manual exposure for the rest of the
session. Solver-driven auto-exposure and zero-match recovery are both dead — recovery
only runs inside `if self._auto_exposure_enabled` at `camera_interface.py:430`. Settings
→ Camera Exp still shows **"Auto"** checked, so nothing surfaces it. Recovery requires
re-selecting Auto or rebooting.

**Why this is worse than PR #614 documented.** The PR characterises the leak as an
"exotic exit" — long-RIGHT to recent objects, then long-LEFT. But the Focus screen's
*own* Quick Menu carries an **Exposure** jump (`preview.py:134-141`,
`menu_jump="camera_exposure"`). Adjusting exposure from the focus screen is an entirely
ordinary thing to do while focusing, and:

| Route | Result |
|---|---|
| Focus → Quick Menu → **Exposure** → long-LEFT | **LEAK** — no camera command sent on exit |
| Focus → incoming object push (`pos_server` → `jump_to_label("recent")`) → long-LEFT | **LEAK** |
| Focus → POWER (`base.py:597` → `jump_to_label("shutdown")`) → long-LEFT | **LEAK** |
| Focus → long-RIGHT (object details) → long-LEFT | **LEAK** |
| Focus → LEFT (control) | Correct — `set_exp:auto` sent once, idempotent on the double `inactive()` |

The agent reproduced the first two by driving the real `MenuManager` over a real
`UIPreview`; I re-verified the gating code and the camera-side flag independently. The
marking-menu Exposure jump already existed on `release` — **only the hold is new, which
is exactly what converts a dormant lifecycle gap into a camera-state bug.**

Compounding it: the `camera_exposure` menu (`menu_structure.py:916-958`) has no
`post_callback` on plain back-out, so a user who opens it and leaves without selecting
gets config saying `auto` while the camera is manual.

**Fix options.** Making Focus `stateful` does **not** work — the `state` check in
`add_to_stack` is on the *pushed* item, not the buried one. Either `add_to_stack` /
`key_long_left` must deactivate what they bury (which this project deliberately leaves
alone, because `dateentry` / `timeentry` / `locationentry` fire commit callbacks from
`inactive()`), or the hold must stop depending on `inactive()`. The repo already has the
right precedent for this exact shape: the **black-level lease**
(`tests/test_black_level_lease.py`). A leased transient exposure that the Focus screen
renews each frame and the camera process drops on expiry closes every route above at
once, without touching the load-bearing lifecycle asymmetry.

**Recommendation:** hold the cut for this, or ship the Focus exposure hold disabled. It
is on the screen users visit most on their first night, and its failure mode is a
degraded solver that nothing in the UI explains.

---

### 3. MEDIUM — A stale `camera_lens` after an in-device Camera Type switch silently stops solving

**`ui/callbacks.py:196-211`** (`switch_cam_imx477` / `_imx296` / `_imx462`) and
**`optics.py:170-180`** (`resolve_lens`).

The sensor half of the train is re-detected every boot. The lens half is a sticky config
value, and **nothing invalidates it** — I grepped every `camera_lens` reference; the only
writer is the menu's `post_callback`. The `switch_cam_*` callbacks rewrite the dtoverlay
and reboot but leave `camera_lens` untouched.

Trigger: a v3 user who has explicitly selected **16mm** later swaps to the v2 HQ camera
via Advanced → Camera Type (the HQ ships with the 25 mm). After reboot:

```
resolved:  hq + 16mm  ->  17.12°,  gate [14.55, 19.69]
actual:    hq + 25mm  ->  10.33°
```

Every frame is pruned before verification. Per ADR 0027 this is deliberate for a
*mis-stated* lens — but here the user never mis-stated anything; **the device's own menu
invalidated their earlier statement.**

The safety net does not fire. `_warn_if_outside_solver_database` (`solver.py:155-186`)
logs only when the gate has *no overlap* with the database's `[10.0, 30.0]`, and
`[14.55, 19.69]` overlaps. So the log shows a cheerful `Optical train: 16mm lens on hq…`
and nothing else, while the UI presents it as an exposure problem. The reverse direction
(HQ → v3 with a stale `25mm`) does warn, because that gate falls entirely below
`min_fov`.

**Fix:** clear `camera_lens` in the `switch_cam_*` callbacks — falling back to the new
sensor's `default_lens_key` is exactly right. Cheap and closes finding 8 too.

---

### 4. MEDIUM — The Lens setting has no user documentation

ADR 0027 accepts "a mis-stated lens means no solves, and we deliberately do not recover
from it" on the **explicit grounds** that *"the troubleshooting path documents cleanly"*
and *"'solves stopped after I changed the lens' is a documentation problem, not a code
path."*

That documentation is not in this release:

- `docs/source/menu_map.rst` lists Camera Type under Advanced (lines 210, 281) — **no
  Lens entry.**
- `docs/source/user_guide.rst:967` still says the once-configured settings are
  "PiFinder Type, Camera Type, and GPS Settings".
- `docs/source/troubleshooting.rst` has no lens/no-solve entry.

The `docs/ax` and ADR side of #608 is thorough; the user-facing side was not written.
**#613 is filed for exactly this and is docs-only** — pulling it into the cut would
convert an unmitigated risk into the mitigated one the ADR assumed. There is a real irony
in a release whose other 18 commits rewrite the entire manual shipping its one new user
setting undocumented.

---

### 5. MEDIUM — The Lens menu offers combinations the shipped database cannot solve

**`ui/menu_structure.py:1072-1096`.** The menu is a static three-item list with no
per-sensor gating. Verified directly against the shipped
`python/PiFinder/tetra3/tetra3/data/default_database.npz` (`props_packed` → `min_fov =
10.0`, `max_fov = 30.0`):

| Sensor | 12 mm | 16 mm | 25 mm |
|---|---|---|---|
| imx296 | 17.78° | **13.71°** | **8.26° — cannot solve** |
| imx462 / imx290 | 13.51° | **10.40°** | **6.26° — cannot solve** |
| HQ | 22.16° | 17.12° | **10.33°** |

The solver does log the explicit "no frame can solve" error for these two, because their
gates fall entirely below `min_fov` — so this is the one place the safety net works as
designed. But the menu presents nine combinations as equally valid and two of them are
dead. Note this also contradicts #608's claim that `min_fov=10.0, max_fov=30.0` "already
spans every combination": it spans the four combinations the ADR validated, not the nine
the menu offers.

**Fix:** either gate the menu items by sensor, or note the constraint in the Lens menu
help and in the docs from finding 4.

---

### 6. MEDIUM — `frustum_box` derives the vertical extent from the width

**`plot.py:56-60`:**

```python
offset = (width - ratio * width) / 2
return (offset, offset, width - offset, height - offset)
```

The projection scale is uniform (`pixel_scale` at `plot.py:206-207` derives from
`render_size[0]` only), so a square camera field must map to a `ratio * width` **square**.
The returned box is `ratio*width` wide but `height − (width − ratio*width)` tall — a
constant 80 px shortfall on a 320×240 target.

Because `frustum_box` now gates **both** the shading and the `visible_stars` filter
(`plot.py:524-535`), the Align screen shades sky the camera can actually see and drops
legitimate alignment stars near the top and bottom of the field.

At low ratios the box becomes **inverted**, and that is not merely cosmetic — I executed
it:

```
320×240, imx296 @ 60° chart FOV: ratio 0.229 -> box (123.4, 123.4, 196.6, 116.6)
PIL 10.4.0 ImageDraw.rectangle -> ValueError: y1 must be greater than or equal to y0
```

The Align screen's `fov_list` is `[5, 10.2, 20, 30, 60]` (`ui/align.py:85`) and it draws
with shading on, so 60° is reachable. `st7789` (320×240) is a selectable display
(`displays.py:578`). The `visible_stars` filter `(y_pos > top) & (y_pos < bottom)` also
yields the empty set whenever the box inverts.

**Two corrections to the agent reports, which both flagged this:** it is **not a 2.6.2
regression** — `origin/release:plot.py:387-398` has the identical formula — and one
agent's claim that #609 "makes the error more visible" is backwards. The shortfall is a
constant 80 px, so a larger box means a *smaller* relative error, and the inversion
threshold moves in the safe direction for every shipped sensor (old `9.5/fov < 0.25`
degenerates above 38°; imx296's `13.71/fov` not until 54.8°). What the refactor *did*
change is that the bug is now a named, tested function whose tests
(`test_plot_frustum.py`) use only `RENDER_SIZE = (128, 128)` — so it is locked in behind
green tests.

**Fix:** `off_x = (width - ratio*width)/2; off_y = (height - ratio*width)/2`, and add a
non-square case to `test_plot_frustum.py`. Square panels (128/176) — which is the
mainstream shipped hardware — are unaffected either way, so this need not block the cut.

---

### 7. LOW — Archive re-analysis scripts ignore the lens the archive now records

**`python/scripts/evaluate_radiometer_archive.py:120`** and
**`python/scripts/report_sqm_production_archive.py:142`** call
`radiometric_sqm(sample, profile)` / `accumulator.estimate(profile, now, …)` with no
`field_width_degrees`, so `radiometer.py:184-185` falls back to
`optical_train_for_profile(profile).fov_degrees` — the sensor's *shipped* lens —
regardless of what the sweep metadata says was fitted.

This release fixed the **writer** (`save_sweep_metadata` now records `lens`,
`lens_effective_focal_length_mm`, and a derived `radiometric_fov_degrees`) but not the
**readers**. The writer's own docstring says the omission "silently poisons the next
calibration".

Harmless today — every archived sweep is on a shipped lens, and derived-vs-retired
constants differ by < 0.005 mag. It bites the first 12 mm sweep analysed: reducing an
imx296 + 12 mm sweep at 13.71° instead of 17.78° is a **≈ −0.56 mag systematic**, folded
straight into any refitted `radiometric_zero_point`, which then ships to every user.
Given #612 asks for exactly that 12 mm sweep, this will be stepped on. Developer tooling
only, not shipped runtime.

---

### 8. LOW — `--camera debug` breaks for any developer who has opened the Lens menu

**`camera_debug.py:41`.** The relabel to `"Debug hq"` is correct and well-tested, but it
fixes only the *sensor* half. The lens half still comes from config:

```
--camera debug, camera_lens unset  -> gate [ 8.78, 11.88], frames 10.2°  SOLVES
--camera debug, camera_lens "16mm" -> gate [14.55, 19.69], frames 10.2°  NO SOLVE, no warning
```

Same root cause as finding 3, and the same fix helps. `test_optics_solving.py` does not
catch it because it calls `build_optical_train("hq")` with `lens_key=None` directly
rather than going through config. Affects the `pifinder-remote` skill and the
docs-screenshot workflow.

---

### 9. LOW — Profile field defaults let a new profile produce a silently broken gate

**`camera_profiles.py:52,58`.** `pixel_pitch_um` and `default_lens_key` are both required
for the derivation but default to `0.0` / `""`. A new profile that forgets the pitch
yields `fov_degrees == 0.0` and `solver_fov_params() == (0.0, 0.0)` — a device that never
solves, with no exception and no log line. `test_optics.py` pins `default_lens_key` via
`test_every_profile_names_a_registered_default_lens` but there is no equivalent for
`pixel_pitch_um`. A forgotten `default_lens_key` at least raises `ValueError: Unknown
lens: `.

---

### 10. LOW — An unrecognised lens key falls back with nothing in the log

**`optics.py:178-180`.** `resolve_camera_profile` logs a warning on an unknown sensor;
`resolve_lens` does not on an unknown lens. A hand-edited or downgraded config saying
`"18mm"` runs as 16 mm with nothing whatsoever in the log. Given ADR 0027 makes the log
*the* diagnosis path for this entire class of problem, the asymmetry matters.

---

### 11. LOW — Unsynchronised optical-train cache shared across waitress threads

**`api_extensions.py:31, 471-473`** with `OpticalTrainResolver.resolve` at
**`optics.py:284-291`** — an unsynchronised check-then-set. Two `/chart` requests
interleaving across a lens change (or the boot-time `imx296` → detected-sensor
transition) can leave `_key = A` with `_train = train_B`, so later requests for key A get
the wrong train until the key changes again: wrong frustum size and a wrong
`visible_stars` box. The comment at `:465-470` reasons carefully about waitress threading
for the adjacent `Starfield` object; the resolver next to it has the same exposure. Very
narrow window, web-chart-cosmetic impact.

---

### 12. LOW — i18n residuals

- **`ui/preview.py:648`** — `exposure_mode = "HOLD"` is not wrapped, so the Focus → Stats
  screen shows English "HOLD" in de/es/fr/zh. Mitigating: the adjacent `"AUTO"` /
  `"MANUAL"` at `:652` are equally unwrapped and already ship that way on `release`, so
  this is consistent with existing behaviour rather than a regression. Fixing all three
  together is the clean call.
- **`locale/es/…/messages.po`, `locale/fr/…/messages.po`** — the standalone
  `# AI-TRANSLATED (claude): needs human review` comment that preceded `GPS Settings` was
  displaced onto the newly inserted `Lens` entry (which carries its own copy), silently
  dropping `GPS Settings` off the human-review queue in those two catalogs. Review
  metadata only, zero runtime effect.

---

### 13. Informational

- **ADR 0027 slightly overstates its own result.** It claims 15.61 mm reproduces both
  calibrated widths "to within 0.02°". imx462 derives **10.4028** against the shipped
  **10.38** = **0.0226°**. Nothing fails — `test_optics.py`'s tolerance is 0.03° — but
  the ADR and the PR body should say 0.03°.
- **`state.py:304,308`** constructs `config.Config()` **twice** in
  `SharedStateObj.__init__` (once for `target_pixel`, once for `camera_lens`) — two full
  disk reads plus Equipment/Locations parsing in the manager process at boot. Hoist one
  local.

---

## What was verified as correct

This is the larger half of the review, and it matters as much as the findings.

**The optics math is right.** `fov = 2·atan((crop_width_px · pixel_pitch_µm / 1000) / 2 /
f_eff)`, degrees conversion correct, `atan2` arguments positive. It matches tetra3's own
definition — `fov_estimate` is the **horizontal** FOV of the image width
(`tetra3.py:1603`) — and it matches the real pipeline: `camera_pi.capture()` does
`profile.crop_and_rotate(raw)` then `.resize((512,512))`, so the crop width *is* the
solver image width. The crop is square for imx296 (1088²) and imx462/290 (980²); hq is
1516×1520, a 0.26 % anisotropy, far inside the gate. Effective focal length is the only
one used in arithmetic; nominal reaches only `menu_label`.

**No existing user's SQM moves.** Derived field widths against the three retired
per-sensor constants — recomputed independently in this session:

| Profile | Retired constant | Derived (shipped lens) | ΔSQM |
|---|---|---|---|
| imx296 | 13.71 | 13.7116 (16 mm) | +0.0003 mag |
| imx462 / imx290 | 10.38 | 10.4028 (16 mm) | +0.0048 mag |
| hq | 10.34 | 10.3284 (25 mm) | −0.0024 mag |

**Backward compatibility is clean — there is no KeyError path.** `camera_lens` is absent
from `default_config.json`, so `Config.get_option` returns `None` →
`resolve_lens(profile, None)` → `profile.default_lens_key`. An unknown lens key, an empty
string, a non-string, and an unknown *sensor* all fall back rather than raise. A 2.6.1
config boots and solves identically. No config migration is needed and none is added.
`text_menu.py:64-76` was patched so a stored `None` plus a `value_callback` keeps the
resolved default rather than snapping to `items[0]` — which is what stops a 2.6.1 config
from displaying "12mm"; the Lens menu is the **only** menu in the tree with both
`config_option` and `value_callback`, so that change has no other blast radius.

**The `camera_profiles` move is clean.** `sqm/camera_profiles.py` is a pure 26-line
re-export shim with no duplicated or diverged table. I confirmed by import that
`CAMERA_PROFILES`, `CameraProfile`, `get_camera_profile` and `detect_camera_type` are
`is`-identical through both paths. All six remaining old-path importers resolve. No
circular import. A full-text diff of the 466-line original against the 500-line
relocation shows **zero numeric change** to any radiometric constant — `bias_offset`,
`radiometric_zero_point`, `radiometric_colour_slope/pivot/range`, `clear_zero_point`,
`clear_sky_brightness`, `sqm_band_offset`, `color_coefficient`, gains and crops all
carried across unchanged. The only removal is `radiometric_fov_degrees`, which has zero
remaining attribute readers.

**All four shipped default trains sit inside the bundled pattern database.** imx296
13.71 → [11.65, 15.77]; imx462/290 10.40 → [8.84, 11.96]; hq 10.33 → [8.78, 11.88],
against `min_fov 10.0, max_fov 30.0`. The ±15 % gate is genuinely tighter than the
retired ±33 % and correctly centred where `12.0 ± 4.0` was not.

**The debug-camera relabel is right and end-to-end tested.** `test_optics_solving.py`
really solves both `test_images/` frames through tetra3 with the hq train, confirms the
fitted FOV (10.2°) is within 5 % of derived, and confirms the imx296 train rejects the
same centroids.

**Solver integration is defensively correct.** Resolution sits inside the same
`BrokenPipeError` / `ConnectionResetError` guard as the rest of the loop, logs once per
change (cached under the stated key, so an unknown sensor logs once, not per frame), and
`t3.database_properties` genuinely exists. No startup race:
`camera_interface.get_image_loop` calls `set_camera_type` before the first capture, and
the solver only resolves a train after `is_new_image`, so the pre-camera `imx296` default
is never used for a real frame.

**Shared state propagates correctly.** `camera_lens()` / `set_camera_lens()` are scalar
getter/setter *methods* on the `BaseManager`-proxied object — a proxied method call, not
a nested-container mutation, so it crosses process boundaries. No stale-state window:
`text_menu.py:187` writes config before `:251` fires `set_camera_lens`, and every
consumer re-resolves live (solver per frame, align per frame, camera per call, API per
request).

**Exposure clamping on the Focus screen is safe.** `FOCUS_EXPOSURE_LADDER` is pinned
equal to the Camera Exp menu values by test, `step_exposure` cannot leave the ladder, and
the AE controllers clamp to the same `[25_000, 1_000_000]` µs bounds. The genuinely
unclamped `exp_up` / `exp_dn` (×1.25 with no ceiling) is **not reachable** from the Focus
screen — only `ui/align_daytime.py:360-364` sends it, unchanged in this release.

**Menu index drift causes no breakage.** Lens lands at index 2 of Settings → Advanced;
only `GPS Settings` shifts 2 → 3. `tests/website/test_web_remote_settings.py:24`
explicitly excludes the Advanced submenu, no test hard-codes an index there, and the
`camera_lens` label does not collide. (Worth a spot-check anyway during G6.3 — index
drift broke three remote tests during the 2.6.1 cycle.)

**`frustum_box` fixed a latent `ZeroDivisionError`** for callers that pass no
`camera_fov` (`ui/chart.py`), which the old unconditional `9.5 / self.fov` would have hit.

**Build health.** `pytest -m "smoke or unit"` → **1,229 passed, 0 failures**, 472
deselected (**1,238 on `main` after #620**) — reproduced identically in the maintainer's checkout and in a clean worktree
rooted on `origin/main` with a freshly initialised `tetra3` submodule. Ruff and mypy
clean. Sphinx `-nW` build succeeds with **0 warnings** over 18 sources, with no
`suppress_warnings` or `nitpick_ignore` in `conf.py` to mute it. `sqm.rst` is wired into
the `index.rst` toctree and its three new images are present. i18n: 671 → 675 msgids, 0
untranslated, 0 fuzzy in all four catalogs, with every `.mo` byte-identical to a fresh
compile. ADR numbering is collision-free after #616, and all 16 cross-references to
0027/0028 resolve.

---

## Recommendation for the cut

**Must fix before the cut — both now done:**
1. ~~Commit the `version.txt` bump (finding 1).~~ **Done at `db065b60`.**
2. ~~Decide on the Focus exposure-hold leak (finding 2).~~ **#620 removed the ordinary
   route in and replaced it with a discoverable status bar.** This lowers the likelihood
   substantially and leaves the impact unchanged, so the leak moves from blocker to
   accepted risk. The lease fix is still the right long-term answer and should keep its
   own ticket.

**Should fix before the cut — cheap and high value:**
3. Clear `camera_lens` in the `switch_cam_*` callbacks (findings 3 and 8, one change).
4. Pull #613 in, or write the equivalent minimal Lens documentation (finding 4). The
   ADR's accepted risk is explicitly predicated on it.

**Can ship, fix after:** findings 5, 6, 7, 9, 10, 11, 12, 13. Note that finding 7 should
be fixed *before* anyone runs the 12 mm calibration sweep that #612 asks for, or the
resulting constants will be biased by ≈ 0.56 mag.
