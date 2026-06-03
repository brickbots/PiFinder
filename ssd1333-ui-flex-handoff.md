# Handoff — Resolution-flexible UI for the 176×176 SSD1333 panel

**Status:** **Phase 0 + Phase 1 + Phase 2 COMPLETE and merged with the latest hardware work; the three hardware-validation bugs are now FIXED.** Phase 1 validated on the physical panel. Phase 2 (the deferred secondary / entry / SQM screens) implemented + validated by in-process render at 128 and 176 + `pytest -m "smoke or unit"`; ruff clean. **The three rendering/crash bugs the user found on hardware (carousel box clearance, help-screen crash, marking-menu overrun) are FIXED and re-validated this session — see the "Known bugs" section below.** Phase 2 itself (the screens listed in §5) is otherwise done and awaiting ruler/readability sign-off. **Hardware-test branch `origin/ssd1333_ui_hw_test` updated with the fixes — flash/pull to the Pi.**
**Branch:** `ssd1333_ui_hw_test` on `origin` (brickbots), **tip `2f14b843`**. Worktree local branch `worktree-ssd1333-ui-flex` is the same commit. This session also: merged `origin/new_hardware_features` (the buzzer-earcon "Sound" subsystem — `sound.py`, CLI, tests, `docs/adr/0008-sound-best-effort-delivery.md`) in via `900b9df5` (clean merge, `pytest -m "smoke or unit"` → 364 passed), and renumbered the UI ADR to **`docs/adr/0009-resolution-flexible-ui-hybrid.md`** (`2f14b843`) to clear the ADR-0008 collision (Sound keeps 0008). Commits this session: `7ed0cb61` Phase 2 · `900b9df5` NHF/Sound merge · `2f14b843` ADR renumber.
**Worktree:** `/Users/rich/Projects/Astronomy/PiFinder/.claude/worktrees/ssd1333-ui-flex`.
**Awaiting from the user:** ruler/readability sign-off on the physical panel — the 176 font sizes (§2.3) are a deliberate starting point and may be nudged. (Independent of the bug fixes below.)

---

## Known bugs — ALL THREE FIXED (commit below)

Found by the user validating Phase 2 **on the 176 panel**; **fixed and validated** this session — render-diffed at 128 **and** 176, exercised through the real `device.display()` path, `pytest -m "smoke or unit"` → 364 passed, ruff clean, mypy clean (only the pre-existing pandas/requests stub errors remain). The headless dummy device **does** assert on size, so #2 now reproduces/verifies headlessly through the display path; it slipped through Phase 2 only because the in-process render harness saves `m.screen` and never calls `device.display()`.

### Bug 1 — Carousel highlight box touched the line of text above — FIXED
- **Symptom:** the menu's selected-item highlight bracket intersected the text row immediately above it.
- **Where:** `python/PiFinder/ui/layout.py` → `carousel_layout()` (used by `UITextMenu`).
- **Root cause (measured):** the focus selection box top was `focus.y - pad`, landing **exactly** on the bottom of the row above — `box_top == row_above_bottom` (62 == 62 on 128; 85 == 85 on 176), a **0px gap**.
- **Fix applied:** the focus row now reserves its own slot (`height + 2*pad`) and is placed at `slot_y + pad`, mirroring `list_layout`. The box keeps `pad` around the glyph **and** a full `gap` of clearance from the neighbouring rows. Verified: top/bottom gap now 2px @128, 3px @176; box still encloses the focus text; 128 carousel unchanged in look.

### Bug 2 — Help screen crashed on the 176 panel — FIXED
- **Symptom:** opening Help (marking-menu "HELP" / `__help_name__` screens) crashed.
- **Root cause (confirmed):** the help PNGs under `help/<name>/*.png` are all **128×128**. `base.py::help()` loads them + `make_red` (`ImageChops.multiply` returns an image sized to its **first** arg → 128×128, so `help()` itself does **not** raise); `menu_manager.py::update_screen()` then calls `device.display(image)`, and luma asserts the image matches the **device resolution (176×176)** → `AssertionError`.
- **Fix applied:** `help()` now normalizes each red frame onto a black `resX×resY` canvas (centred; thumbnailed down first if a frame is larger than the panel). Derived from `display_class.resX/resY`, not special-cased to 176. Verified by feeding every returned frame through `device.display()` on the 176 dummy (no raise) and confirming all frames are `resX×resY`.

### Bug 3 — Quick (marking) menu text overran the radial quarter bounds — FIXED
- **Symptom:** curved option text in the radial "quick menu" spilled outside its pie-slice quadrant on 176.
- **Root cause:** `menu_manager.py` called `render_marking_menu(..., radius=39)` with a **hardcoded 39** at **two** sites. `marking_menus.py` is otherwise resolution-aware, but a fixed radius kept the circle 128-sized while the curved label is laid in `fonts.large` (wider on 176) → text overran the slice.
- **Fix applied:** `MenuManager.__init__` now computes `self.marking_menu_radius = round(resX * 39 / 128)` once (39 @128, 54 @176) and both call sites use it. Verified: labels (HELP/SETTINGS/CHART/OBJECTS) fit the slices on 176; 128 unchanged (radius still 39).

### Follow-on: boot splash + console welcome image (two more foreign-sized-image sites) — FIXED
A sweep for *other* code paths that push a non-`self.screen` image to `device.display()` (the same class as Bug 2) found two more, both displaying the 128×128 `images/welcome.png`:
- **`splash.py`** (`pifinder_splash.service`, a **boot service** separate from the app) hardcoded `get_display("ssd1351")` + a 128 `welcome.png` + `rectangle([0,0,128,16])` → on real SSD1333 hardware it inits the **wrong controller**. **Fix:** detect the panel via `hardware_detect.detect_capabilities()` (rev-4 → `ssd1333`, else `ssd1351`, mirroring `main.py`), scale the welcome image to fill `resX×resY`, and span the banner across `resX` at a resolution-scaled height. No-op on 128.
- **`ui/console.py`** pasted the 128 `welcome.png` at `(0,0)` (top-left quadrant on 176; **cosmetic**, no crash). **Fix:** scale it to fill `resX×resY` so it stays full-bleed behind the boot console. No-op on 128.
- **Validated:** splash + console render at 128 and 176 and are accepted by `device.display()`; a full **Phase 2 crash-sweep** (16 screens through the real display path, one resolution per process) found **no genuine 176-only render crash** — every screen renders `resX×resY` and displays. `pytest -m "smoke or unit"` → 364 passed; ruff + mypy clean.

---

## 1. Goal

Adapt the PiFinder UI to a new larger display — the NHD **SSD1333, 176×176 px, 1.91″** — alongside the standard **SSD1351, 128×128, 1.5″**. On the new panel the user wants:
- UI elements **slightly larger** (measured by ruler),
- **slightly more content** per screen (e.g. more menu items),
- camera preview / align / chart to **just plot at the new resolution**.

Crucial physical fact: the two panels have **near-identical pixel density** (128px/1.5″ ≈ 121 ppi; 176px/1.91″ ≈ 130 ppi). So a glyph at the same pixel count looks ~the same physical size; "bigger by ruler" requires spending pixels on larger fonts. The 176 panel has ~1.34× the linear pixels to split between "bigger" and "more."

## 2. The plan — 5 locked decisions (from a /grill-with-docs session; now ADR 0009)

1. **Target:** render **176×176 edge-to-edge**, no safe area. The SSD1333 controller only addresses 176×176 (`ssd1333_device.py`: MUX 175, `_supported_dimensions()==[(176,176)]`).
2. **Mechanism = HYBRID:** derive **geometry** (item counts, line positions, text anchors, image scaling, scroll-bar edges) from font metrics + `resX/resY`; hand-tune a **small set of per-display knobs** (font sizes, `titlebar_height`, `menu_visible_items`). Minor (≤1–2px) drift on the existing 128 layout is **acceptable** — do NOT special-case 128 to reproduce exact pixels. *Recorded in `docs/adr/0009-resolution-flexible-ui-hybrid.md`.*
3. **Sizing = BALANCED:** 176 fonts `base 12 / bold 14 / small 10 / large 18 / huge 42`, `titlebar_height 20`, carousel **7→9** items. (Measured live: base h11/bold h13 @128 vs base h13/bold h15 @176; ~10% bigger by ruler, +2 rows.)
4. **Scope:** Phase 0 + Phase 1 done; **Phase 2 = the deferred entry / secondary / SQM screens (§5).**
5. **Validation:** 176 headless + pygame on the dev machine (screenshot iteration); the user does the final **ruler/readability sign-off on the physical prototype**.

## 3. What's DONE

### Phase 0 — display profiles + carousel (commit `d9e734ad`)
- **`displays.py`** — `DisplayBase.menu_visible_items = 7` (new knob; **must be ODD**). `Layout176` mixin (resolution, titlebar 20, fonts 12/14/10/18/42, items 9). `DisplaySSD1333(Layout176, DisplayBase)` (hardware, **`rotate=2`** — panel mounted 180°). `DisplayPygame_176` (`--display pg_176`, rotate 0). `DisplayHeadless176` (`--display headless_176`). `get_display` wired for both.
- **`ui/layout.py`** (NEW) — `carousel_layout(display_class)` for `UITextMenu`: per-row `(y, font, brightness, distance)`, focus `selection_box`, `text_x`/`check_x`. Reproduces the legacy 128 fisheye tiers and extends to 9 rows.
- **`ui/text_menu.py`** — `UITextMenu.update()` uses `carousel_layout()` instead of hardcoded positions.

### Phase 1 — "the screens you live in" (commit `4bf2daf9`)
All seven screens made resolution-flexible; rendered at 128 and 176 and diffed.
- **`ui/layout.py`** — added `list_layout()` (uniform-row sibling of `carousel_layout`) for `UIObjectList`: per-row `y`, focus selection box, text/marker indents, row/focus fonts. Legacy 128 within ~4px (focus y 66 vs 62); 9 rows on 176, focus dead-centre, no overlap (asserted by a geometry test).
- **`ui/object_list.py`** — `line_position`/`color_modifier`/selection-box/row-loop derive from `list_layout` + `menu_visible_items`; both brightness curves generated for N rows (exact legacy at 7, extended to 9). Sort-info `<3`/`2.0` → `center`/`center-1`.
- **`ui/base.py`** — title/FPS/icon/X/rotating-info y-offsets centre in `titlebar_height`; the `128 * …` GPS-pulse rate is now the named `GPS_ANIM_RATE` (animation speed, not geometry); `message()` default popup box centres on `resolution` (exact `(5,44,123,84)` on 128).
- **`ui/chart.py`** — RA/Dec text → `resY - base.height - 3`.
- **`ui/preview.py`** — resize→`(resX,resY)`; zoom crops a centred native-frame region (½ for 2×, ¼ for 4×) then scales (2×/4× at any res); reticle centre scales `target_pixel` from native space; zoom/info-overlay/star-selector positions derived. `CAMERA_NATIVE_RES = 512`.
- **`ui/align.py`** — initial `marker_position` and the `key_number` reticle reset scale via `CAMERA_NATIVE_RES` / `centerX,centerY` (was `/4` and `(64,64)`).
- **`ui/object_details.py`** — two-line pointing-status messages anchor off `resolution`+font; designator/type-const headers derive (exact 20/36 on 128); DESC `posy` follows the header. The az/alt `*2.2`/`*1.2` multipliers already track resY+huge.height — left as-is.
- **`ui/ui_utils.py`** — `TextLayouter` scrollbar derives `resX-1`/`resY-1` from `colors.red_image.size`. Dead `uparrow`/`downarrow` class-attrs left untouched.

### Docs (commit `4bf2daf9`)
- `docs/ax/ui/CONTEXT.md` — `self.screen` now described as `resolution`-sized; new canonical **"carousel"** term.
- `docs/ax/ui.md` — §1 made resolution-based.
- `docs/adr/0009-resolution-flexible-ui-hybrid.md` — the hybrid mechanism + A/B/C trade-off.

## 4. The layout toolkit you'll reuse in Phase 2

**Read these two functions first — `ui/layout.py`.** The whole pattern lives there: a helper takes the `display_class` (a `DisplayBase` **instance**) and returns derived geometry. Screens then read, instead of literals:
- `self.display_class.resX` / `.resY` / `.centerX` / `.centerY` / `.fov_res` / `.titlebar_height`
- font metrics: `self.fonts.{small,base,bold,large,huge,icon_bold_large}.height` / `.width` / `.line_length`
- `CAMERA_NATIVE_RES = 512` (in `preview.py`/`align.py`) for camera-space → display-space scaling.
- `self.clear_screen()` (base.py) already clears using `resX/resY` — screens doing `draw.rectangle((0,0,128,128))` should just call it.

**Recommended first Phase-2 step — add two shared helpers to `layout.py`** so the secondary screens don't each grow their own magic numbers:
1. **Stacked text rows** — `rows_below_titlebar(display_class, font=base, gap=…)` returning row y-positions and `max_visible = (resY - titlebar_height) // (font.height + gap)`. Covers `console`, `status`, `gpsstatus`, `equipment`, `software`, `location_list`, `log` menu rows.
2. **Centred box row** — `center_box_row(display_class, box_widths, spacing, y, height)` returning the x of each box (centres `sum(widths)+spacing*(n-1)` on `resX`). Covers `timeentry`, `dateentry`, `locationentry`, `sqm_correction`, and is the basis for `textentry`'s keypad grid.

These keep Phase 2 consistent with Phase 1 and with ADR 0009 (derive geometry, don't hand-place).

## 5. Phase 2 — the deferred screens  ← DONE

**Shipped** (all rendered at 128 + 176 and diffed):
- **`ui/layout.py`** — two new helpers: `rows_below_titlebar(display_class, font, gap, top_pad)` (stacked text rows + `max_visible`) and `center_box_row(display_class, box_widths, spacing, y, height)` (centred fixed-width box row). Both reproduce the 128 layout exactly and feed the screens below.
- **5A** `console` (derived scrollback window + rows; `GPS_ANIM_RATE`), `status` (`available_lines` derived; `clear_screen()`), `sqm` (resize/overlay → `resX/resY`; **dashboard rows fully re-anchored** off titlebar + font heights so the value/detail/legend block fills the panel).
- **5B** `equipment` (stacked info rows + bottom-anchored option block), `software` (font-derived info cadence + bottom-anchored message), `location_list` (action-menu cadence + helper fallback row), `log` (font-derived menu cadence + star pitch from glyph width), `sqm_calibration` / `sqm_sweep` (**all `_draw_*` states re-anchored**: headers off titlebar, body font-stepped, legends bottom-anchored, progress bar spans `resX`, char limit → `line_length`), `sqm_correction` (entry centred on `resX`, legend dims → `resX/resY`, vertical stack derived).
- **5C** `timeentry` / `dateentry` / `locationentry` (box dims from the bold glyph, centred via `center_box_row`, clears → `resX/resY`), `radec_entry` (`LayoutConfig` now computes from `display_class` — reproduces 128 exactly, scales to 176), `textentry` (**T9 keypad grid derived from `resX/resY`** — `key_w=(resX-2·text_x)//3`, `key_h` from remaining height).

**Scope notes:** `sqm.py`, `sqm_calibration`, `sqm_sweep`, and `sqm_correction` got **fuller vertical re-layout than the original narrow §5 scope** (which only listed the progress bar / resize / centring). Leaving the rest hard-coded would have stranded content in the top-left of the 176 panel and collided headers with the taller titlebar, so the body rows were re-anchored too — all low-risk arithmetic, render-validated at both sizes. `gpsstatus.py` and `numeric_entry.py` were already flexible — untouched. No per-display knob (`Layout176`) re-tuning was done; that follows the user's hardware sign-off.

---

### 5-original. Phase 2 work plan (historical — what the plan called for)

> Line numbers below are from a read-only scan of the current tree (Explore sweep). **Re-grep before editing — they drift.** Validate each screen with the in-process harness (§6) at `headless` and `headless_176`. Many of these screens are **not exercised by the smoke/unit suite**, so visual render is the real check.

Recurring fixes across most files: `self.width = 128` / `self.height = 128` instance attrs and `draw.rectangle((0,0,128,128))` screen clears → use `display_class.resX/resY` (or `self.clear_screen()`); `(x, y)` text anchors with a fixed `y` → stack from `titlebar_height` by `font.height + gap`; bottom-anchored option blocks → anchor up from `resY`.

### 5A. Easy — text / scrolling (mostly already partial)
- **`console.py`** — `UIConsole`. L112 `self.lines[-10-offset:][:10]` (10-line window) and L114 `(0, i*10 + 20)` (10px pitch, y=20). Derive window size = `(resY - titlebar_height)//(base.height+gap)`; row y = `titlebar_height + i*(base.height+gap)`. Already uses `resX`/`titlebar_height` elsewhere.
- **`status.py`** — `UIStatus`. L60 `available_lines=9`; L173 `rectangle([0,0,128,128])` → `clear_screen()`. `available_lines` = visible-rows formula above. Already uses `titlebar_height` and `fonts.base.line_length`.
- **`gpsstatus.py`** — `UIGPSStatus`. Mostly done (uses `resY`/`titlebar_height`). Optional polish: the `+16/+10/+18/+15` y-increments → font-height-based.
- **`sqm.py`** — `UISQM`. L55 `resize((128,128))` → `(resX,resY)`; L66 overlay `(0,0,128,128)` → `(resX,resY)`.

### 5B. Medium — menus with stacked rows + bottom-anchored options
- **`equipment.py`** — `UIEquipment`. L31-42 fixed y (20/35/50/70); L89 `titlebar_height+70`; `+18` spacing → stacked rows + a bottom-anchored option block.
- **`software.py`** — `UISoftware`. Multiple y=90-105 (bottom menu area) → anchor up from `resY` by `font.height`.
- **`location_list.py`** — `UILocationList` (extends `UITextMenu`). L177 `titlebar_height+20`; `+12/16/10` action-row spacing → stacked rows. (Note: the list itself rides on `UITextMenu`/`carousel_layout`, already done — this is just the action-menu overlay.)
- **`log.py`** — `UILog`. L125 `range(5)` stars at L130 `(i*15 + 20, y)` (15px star pitch — width-dependent); menu y-increments `+18/+14/+11`. Derive star pitch from `resX`/marker size; stack the menu rows. Already uses `resX`/`resY`/`titlebar_height` for the clear.
- **`sqm_calibration.py`** — `UISQMCalibration`. L307-323 progress bar `bar_x=10, bar_y=70, bar_width=108 (=128-20), bar_height=12` → `bar_width = resX - 2*margin`, y from a fraction of `resY` or `titlebar_height`-relative; L482 char limit `<=18` → `fonts.base.line_length`.
- **`sqm_correction.py`** — `UISQMCorrection`. L117 entry centring on `128`; L164 `legend.draw(screen_width=128, screen_height=128)` → use the **centred box row** helper + `resX/resY`.
- **`sqm_sweep.py`** — `UISQMSweep`. Needs a full read of its `_draw_*` methods (the scan only saw logic constants `total_images=20`, `estimated_duration=60`).
- **`radec_entry.py`** — `UIRadecEntry`. Needs a full read; it's a coordinate **form** like `dateentry` — fold into 5C.

### 5C. Hard — entry grids (do last, on top of the centred-box-row helper)
These centre fixed-width boxes on a 128 width and lay out a keypad/box grid; the math is width-coupled. Build the `center_box_row` helper (§4) first.
- **`textentry.py`** — `UITextEntry`. T9 keypad **3×4 grid**: L178 `key_size=(38,23)`, L180 `start=(text_x, 32)`, L183-184 grid math `(i%3)*(kw+pad)`, `(i//3)*(kh+pad)`; L93-94 `width/height=128`; L117 `text_x_end = 128 - text_x`; L394 clear `(0,0,128,128)`. **Hardest** — scale the key grid and spacing to `resX/resY`. Some good bits already: cursor from `fonts.bold`, `text_y = titlebar_height+2`.
- **`timeentry.py`** — `UITimeEntry`. 3 boxes HH:MM:SS: L42-49 `box_width=25, box_spacing=15`, centre on `width`; L117 separator `(10..width-10)`; L221 clear `(0,0,128,128)`.
- **`dateentry.py`** — `UIDateEntry`. YYYY-MM-DD boxes (38/25), spacing 10, centred; L139 clear `(0,0,128,128)`.
- **`locationentry.py`** — `UILocationEntry`. Coord boxes (50 / 32,28 / 28,28), spacing 12, centred; `width/height=128`.
- **`numeric_entry.py`** — reusable component (`NumericEntryField`/`EntryLegend`/`BlinkingCursor`). Mostly flexible; only `cursor_y_offset=4` is pixel-based. Touch only if a consumer needs it.

### Phase 2 sequencing suggestion
1. Add the two `layout.py` helpers (§4). 2. Sweep 5A (cheap wins, low risk). 3. 5B menus. 4. 5C entry grids last, reusing the box-row helper. Keep 128 within ~1–2px (ADR 0009); render-diff each at both sizes.

## 6. How to develop & validate

- **venv:** `/Users/rich/Projects/Astronomy/PiFinder/python/.venv/bin/python` (3.9.19, has luma). Worktrees have **no** venv — use this interpreter; run/chdir from the worktree's `python/` dir (relative `../fonts`, `../astro_data`).
- **Fastest loop — in-process render** (no app launch, resolution-agnostic):
  ```python
  import os, sys, builtins, queue
  builtins.__dict__.setdefault("_", lambda s: s)  # gettext stub; app installs it at boot
  os.chdir("<worktree>/python"); sys.path.insert(0, ".")
  from PiFinder.displays import get_display
  from PiFinder.state import SharedStateObj, UIState
  from PiFinder.config import Config
  from PiFinder.catalogs import Catalogs
  from PiFinder.ui.text_menu import UITextMenu
  disp = get_display("headless_176")
  ss = SharedStateObj(); ss.set_ui_state(UIState())
  qs = {k: queue.Queue() for k in ("camera","console","ui_queue","align_command","align_response","gps")}
  item_def = {"name":"Demo","select":"single","start_index":6,
              "items":[{"name":f"Item {i:02d}","value":i} for i in range(13)]}
  m = UITextMenu(disp, None, ss, qs, Config(), Catalogs([]), item_definition=item_def)
  m.update(); m.screen.save("/tmp/out.png")
  ```
  Then `Read` the PNG. Swap in `headless` (128) for the regression check.
- **Object/catalog screens** need a populated `Catalogs` **with a filter attached**, else `refresh_object_list` hits `catalog_filter.is_dirty()` on `None`:
  ```python
  from PiFinder.catalogs import CatalogBuilder, CatalogFilter
  cats = CatalogBuilder().build(ss, queue.Queue())
  f = CatalogFilter(shared_state=ss); f.load_from_config(Config()); cats.set_catalog_filter(f)
  objs = cats.get_objects(only_selected=False, filtered=False)[:40]
  # UIObjectList: item_definition={"objects":"custom","object_list":objs,"select":"single",...}
  ```
  ⚠️ **`UIObjectList` LOCATE mode calls `aim_degrees` → skyfield, which can block on a first-run ephemeris fetch.** For pure layout checks render **NAME / INFO** mode (`ol.current_mode = DisplayModes.NAME; ol.refresh(); ol.update()`).
- **chart/align** create `plot.Starfield(...)` in `__init__` (needs `hip_main.dat` — present here + in `~/PiFinder_data/cache/hip_main.pkl`). With `ss.set_solve_state(False)` they take the "No Solve Yet" branch (no network). **preview** needs a synthetic 512² `camera_image` + `ss.set_last_image_metadata({"exposure_end":1.0,"exposure_time":400000})`.
- **Full headless app:** `cd <worktree>/python && <venv> -m PiFinder.main -fh --camera debug --keyboard none --display headless_176 -x`, then GET `http://127.0.0.1:{80|8080}/api/screen`. (The `pifinder-remote` skill's `pf_remote.py` hardcodes `--display headless`/128 and is git-tracked — copy it elsewhere and patch to `headless_176` if you want its `press`/`screen` driver.)
- **On hardware:** `--display ssd1333` (uses `Layout176`, `rotate=2`).
- **Gate before commit:** `pytest -m "smoke or unit"`, `ruff check`, `ruff format`, `mypy` (note: several files carry `# mypy: ignore-errors`; pre-existing pandas/requests stub errors in `plot.py`/`comets.py` are not yours).

## 7. Gotchas

- **`rotate=2`** is correct for the real panel (mounted 180°). Keep emulator/headless at `rotate=0` so the dev preview reads upright.
- **`menu_visible_items` must be ODD** — the carousel/list focus sits on the symmetric centre line.
- **tetra3 submodule:** fresh worktrees need `git submodule update --init python/PiFinder/tetra3` (also required for mypy and for importing `preview.py`). See CLAUDE.md.
- **`_` (gettext)** is a runtime builtin installed at app boot; in-process harnesses must stub it (see §6).
- **Native camera frame is 512×512** (`SharedStateObj.target_pixel` docstring). `target_pixel(screen_space=True)` is hardcoded `/4` (128-space) — scale from raw native + `CAMERA_NATIVE_RES` in the UI instead (as `preview.py`/`align.py` now do).
- Don't chase pixel-exact 128 — ADR 0009 accepts ≤1–2px drift.

## 8. Branch / process notes

- **`ssd1333_ui_hw_test`** (brickbots `origin`) bundles `nhd_ssd1333` + `main` + the UI work + **all of `new_hardware_features`** (battery telemetry, power-button shutdown, hardware_detect, screen-rotation fix). It is the **hardware-test branch** — flash/pull it to the Pi. Tip is now `4bf2daf9` (Phase 1), fast-forwarded from `c9d2adf9`.
- Commits: `d9e734ad` Phase 0 (carousel) · `657baebc` NHF merge · `c9d2adf9` handoff · **`4bf2daf9` Phase 1 + docs + ADR**.
- The worktree local branch `worktree-ssd1333-ui-flex` points at the same `4bf2daf9`. Continue Phase 2 here and fast-forward `ssd1333_ui_hw_test` again when ready, OR — if the user wants a clean PR — split the UI commits onto a branch off `main` (UI work is independent of the NHF commits). **PRs target `main`** (per CLAUDE.md + project memory; ignore any auto-detected "release" default).
