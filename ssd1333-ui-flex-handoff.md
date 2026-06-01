# Handoff — Resolution-flexible UI for the 176×176 SSD1333 panel

**Status:** Phase 0 complete + Phase 1 carousel done & validated; rest of Phase 1 pending.
**Branch:** `ssd1333_ui_hw_test` on `origin` (brickbots), tip `657baebc`.
**Worktree:** `/Users/rich/Projects/Astronomy/PiFinder/.claude/worktrees/ssd1333-ui-flex` (local branch `worktree-ssd1333-ui-flex`).

---

## 1. Goal

Adapt the PiFinder UI to a new larger display — the NHD **SSD1333, 176×176 px, 1.91″** — alongside the standard **SSD1351, 128×128, 1.5″**. The user wants, on the new panel:
- UI elements **slightly larger** (measured by ruler), and
- **slightly more content** per screen (e.g. more menu items),
- camera preview / align / chart to **just plot at the new resolution**.

Crucial physical fact: the two panels have **near-identical pixel density** (128px/1.5″ ≈ 121 ppi; 176px/1.91″ ≈ 130 ppi). So a glyph at the same pixel count looks ~the same physical size; "bigger by ruler" requires spending pixels on larger fonts. The 176 panel has ~1.34× the linear pixels to split between "bigger" and "more."

## 2. The plan — 5 locked decisions (from a /grill-with-docs session)

1. **Target:** render **176×176 edge-to-edge**, no safe area. The SSD1333 controller only addresses 176×176 (see `ssd1333_device.py`: MUX 175, `_supported_dimensions()==[(176,176)]`). The user's earlier "172" was a typo.
2. **Mechanism = HYBRID:** derive **geometry** (item counts, line positions, text anchors, image scaling, scroll-bar edges) from font metrics + `resX/resY`; hand-tune a **small set of per-display knobs** (font sizes, `titlebar_height`, `menu_visible_items`). Minor (≤1–2px) drift on the existing 128 layout is **acceptable** — do NOT special-case 128 to reproduce exact pixels.
3. **Sizing = BALANCED:** 176 fonts `base 12 / bold 14 / small 10 / large 18 / huge 42`, `titlebar_height 20`, carousel **7→9** items. (Measured: base glyph 13px@176 vs 11px@128; 25 vs 21 chars/line — ~10% bigger by ruler, +2 rows.)
4. **Scope:** **Phase 0 + Phase 1 now**; defer entry screens, secondary screens, and SQM tooling to follow-ups.
5. **Validation:** 176 headless + pygame on the dev machine (screenshot iteration); the user does the final **ruler/readability sign-off on the physical prototype** — treat the chosen font sizes as a starting point they may nudge.

## 3. What's DONE (committed on the branch)

- **`python/PiFinder/displays.py`**
  - `DisplayBase.menu_visible_items = 7` (new knob; **must be ODD** — symmetric carousel).
  - New `Layout176` mixin (the shared 176 profile: resolution, titlebar 20, fonts 12/14/10/18/42, items 9).
  - `DisplaySSD1333(Layout176, DisplayBase)` — hardware, **`rotate=2`** (panel mounted 180°; came from new_hardware_features).
  - `DisplayPygame_176(Layout176, DisplayBase)` — emulator, `--display pg_176` (rotate 0, so the dev preview reads upright).
  - `DisplayHeadless176(Layout176, DisplayHeadless)` — `--display headless_176` (for API screenshots).
  - `get_display` wired for `pg_176` and `headless_176`. (`main.py --display <name>` is free-form; `pg_` prefix gates pygame input — both names route correctly, no main.py change needed.)
- **`python/PiFinder/ui/layout.py`** (NEW) — `carousel_layout(display_class)` returns per-row `(y, font, brightness, distance)`, the focus `selection_box`, and `text_x`/`check_x`. Reproduces the legacy 128 fisheye tiers (large/bold/base/base @ 256/192/128/96 by distance) and extends to 9 rows (distance ≥4 → small @ 64). Rows stack by font height + gap and the block is vertically centered below the title bar.
- **`python/PiFinder/ui/text_menu.py`** — `UITextMenu.update()` now uses `carousel_layout()` instead of the hardcoded `[0,13,25,40,60,76,89]` positions + `(-1,60,129,80)` box. (NHF's added `key_power()` method is untouched and coexists.)

**Validated** via in-process render at both sizes: 176 shows 9 items full-height with larger fonts and the fisheye preserved; 128 shows the legacy 7-item look (only the agreed sub-pixel drift). End-to-end headless launch at 176 also confirmed (`/api/screen` serves a real 176² frame).

## 4. Remaining Phase 1 work ("the screens you live in")

Line numbers below are from a pre-merge sweep. **NHF did NOT touch** `object_list.py`, `align.py`, `chart.py`, `preview.py`, `ui_utils.py`, `object_details.py`, so those are still accurate. **NHF DID touch `base.py`** — re-grep there.

1. **`ui/object_list.py` (UIObjectList — object browser, highest value).** Twin of UITextMenu but more involved:
   - `line_position(line_number, title_offset=20)` ≈ L478: `[0,13,25,42,60,76,89]+20` (cached). Used in *many* spots (status msgs L520/528/538/544, sort info L560/573, and the row loop).
   - `color_modifier(line_number, sort_order)` ≈ L470: **two** 7-element brightness curves — `NEAREST=[0.38,0.5,0.75,0.8,0.75,0.5,0.38]` (symmetric, peak center) vs `CATALOG_SEQUENCE=[1,0.75,0.75,0.5,0.5,0.38,0.38]` (peaks at TOP). **These differ from UITextMenu's tiers and must be preserved/extended to 9 rows per sort order.**
   - `get_line_font_color_pos()` ≈ L451 (focus uses **bold**, not large; rows otherwise base font → uniform-ish heights).
   - selection box `(-1,60,129,80)` ≈ L569.
   - **Approach:** add a uniform-row variant to `layout.py` (or extend `carousel_layout`) that returns N evenly-stacked positions for base-font rows + derived box; extend both `color_modifier` curves to N entries (interpolate/mirror). Verify against the two sort modes.

2. **`ui/base.py` (title bar).** Re-grep (NHF shifted lines). `resX*0.8 / 0.91 / 0.54` icon positions already proportional; fix the hardcoded y-offsets (`(6,1)` title/FPS, the `-2` icon y) and the `gps_anim = int(128 * ...)` animation that ties speed to 128 (use `resY`/`fov_res` or a res-independent constant). `titlebar_height` is already used.

3. **`ui/chart.py`.** RA/Dec text hardcoded at `(0,114)` ≈ L180/192 → `resY - fonts.base.height - margin`. Starfield/FOV reticle already parametric (use `fov_res`, `centerX/Y`).

4. **`ui/preview.py`.** `resize((128,128))` (L217) → `(resX,resY)`. Zoom crops from the **512×512 native frame**: `resize((256,256)); crop((64,64,192,192))` (L219-220, 2×) and `crop((192,192,320,320))` (L223, 4×) → parametrize so the zoom factor stays 2×/4× of `resX`. Star-selector boundary magic numbers (`>108`, `<38`) and text at `(126,…)` / `(75,112)` need deriving.

5. **`ui/align.py`.** `self.marker_position = (64,64)` ≈ L439 → `(centerX, centerY)`. `solve_pixel/4` ≈ L102 assumes 512→128; parametrize to `512→resX`. Starfield/reticle already parametric.

6. **`ui/object_details.py`.** Anchors use `resY` (good) but check the `*2.2` multiplier; pointing-instruction text hardcoded at `(10,70)`/`(10,90)` → derive.

7. **`ui/ui_utils.py`.** Scroll bar `xpos=127`, `endy=127` and arrow coords `[48,125,80,125]`/`[32,126,96,126]` → derive from `resX-1`/`resY-1`.

**Deferred (Phase 2+, not now):** `textentry.py`/`timeentry.py` (hardcoded `width=height=128`), `sqm*`, `console.py` polish, `equipment`, `status`, `gpsstatus`, `software`, `location_list`, `log`, entry screens.

## 5. Pending docs (this is a /grill-with-docs project — keep the glossary in sync)

Reference docs live under `docs/ax/`; the UI ones are `docs/ax/ui/CONTEXT.md` (glossary) and `docs/ax/ui.md` (architecture). Use the canonical terms (menu item, submenu, UIModule, UITextMenu, **active module**, **stack**, **display instance**). Apply these:
- `docs/ax/ui/CONTEXT.md` — **UIModule** entry still says "owns a **128x128** `self.screen`": change to *"a `self.screen` PIL image sized to the display instance's `resolution` (128×128 on the SSD1351, 176×176 on the SSD1333)."* And **add a new canonical term "carousel"** (the center-magnified scrolling list: large/bright focus line, neighbors shrinking and dimming; selected item = the focus line).
- `docs/ax/ui.md` — §1 (~L52) and §3.1 (~L150) repeat "128x128 `PIL.Image`" — make resolution-based.
- **Optional ADR** (was offered, user didn't explicitly accept): the hybrid mechanism (derive geometry + per-display knobs, accept minor 128 drift) is a fair ADR candidate — hard-ish to reverse, non-obvious, real A/B/C trade-off. See `docs/adr/` for format. Confirm with the user before writing.

## 6. How to develop & validate

- **venv:** `/Users/rich/Projects/Astronomy/PiFinder/python/.venv/bin/python` (3.9.19, has luma). Worktrees have **no** venv — use this interpreter and run/chdir from the worktree's `python/` dir (relative `../fonts`, `../astro_data` paths).
- **Fastest loop — in-process render** (no app launch, resolution-agnostic; from ui.md §9):
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
  Then `Read` the PNG. (Object screens need a real `Catalogs` and `item_definition["object"]`/`["object_list"]`; chart/align need `hip_main.dat`.)
- **Full headless app + nav screenshots:** the `pifinder-remote` skill drives the app over HTTP (`launch`/`press`/`screen`/`stop`), but its `launch` hardcodes `--display headless` (128) and the script is **git-tracked (don't edit it)**. To run at 176, copy `.claude/skills/pifinder-remote/scripts/pf_remote.py` to a scratch dir, change `"--display","headless"` → `"--display","headless_176"` (and optionally redirect its `/tmp` state/log paths), then run it with the venv python and `--repo <worktree>`. Or just launch the app yourself: `cd <worktree>/python && <venv> -m PiFinder.main -fh --camera debug --keyboard none --display headless_176 -x` and GET `http://127.0.0.1:{80|8080}/api/screen`.
- **On hardware:** `--display ssd1333` (uses the Layout176 profile, `rotate=2`).

## 7. Gotchas

- **`rotate=2`** is correct for the real panel (mounted 180°). Keep emulator/headless at `rotate=0` so the dev preview reads upright.
- **`hip_main.dat`** (Hipparcos, ~53MB, git-ignored) is needed because `UIChart`/`UIAlign` are **preloaded at boot**. Present in this worktree + the user cache `~/PiFinder_data/cache/hip_main.pkl`. A fresh checkout elsewhere needs it (or stub `plot.Starfield`).
- **tetra3 submodule:** fresh worktrees need `git submodule update --init python/PiFinder/tetra3` (also required for mypy). See CLAUDE.md.
- **`_` (gettext)** is a runtime builtin installed at app boot; in-process harnesses must stub it.
- Carousel is a **fisheye** — preserve the center-magnified styling; `menu_visible_items` must be odd.

## 8. Branch / process notes

- `ssd1333_ui_hw_test` = `nhd_ssd1333` + current `main` + my UI work + **all of `new_hardware_features`** (battery telemetry, power-button shutdown, hardware_detect, screen-rotation fix). Clean merge (NHF had already merged `nhd_ssd1333`, so the SSD1333 driver was identical; only reconciliation was `rotate=2`, already adopted).
- The user's working branch `nhd_ssd1333` (main checkout) does **not** have the UI changes — they're only on `ssd1333_ui_hw_test` / this worktree.
- **OPEN QUESTION for the user/next agent:** continue Phase 1 on `ssd1333_ui_hw_test` (bundled with new_hardware_features — convenient for hardware testing), or split the UI work onto its own branch off `main`/`nhd_ssd1333` for a clean eventual PR? **PRs target `main`** (per CLAUDE.md + project memory; ignore any auto-detected "release" default).
- Changes are committed; commit `d9e734ad` is the UI work, `657baebc` the NHF merge.
