# UI

The UI context owns PiFinder's on-device interface: the menu tree, the screen modules the user navigates, the navigation stack, key dispatch, and the radial marking menus. It runs entirely in the main process; other processes see the UI only through `shared_state` (the published screen image and UI-state dict) and the `command_queues`.

> Companion architecture doc: [`../ui.md`](../ui.md).

## Language

### Structure

**Menu item**:
A plain `dict` node in the menu tree describing one screen or submenu — its `class`, `name`, `label`, `items`, and configuration keys. There is no class for it; the schema is by convention (`menu_structure.py`).
_Avoid_: menu entry, node, menu option (a "menu option" is a marking-menu slice).

**Menu tree** (`pifinder_menu`):
The single nested dict literal in `menu_structure.py` that defines the whole static menu. Walked by `collect_preloads` / `find_menu_by_label`.
_Avoid_: menu structure (that's the module name), menu config.

**Submenu**:
A menu item that has an `items` list of child menu items. Almost always rendered by `UITextMenu`.
_Avoid_: folder, category.

**Label**:
The stable, unique string identifier on a menu item (`"equipment"`, `"recent"`, `"object_details"`). Used by `find_menu_by_label` and `jump_to_label` to navigate by name. Not the same as the user-visible `name`.
_Avoid_: id, key, tag.

**item_definition**:
The menu-item dict as seen from inside a module — `MenuManager` passes the whole dict as the `item_definition` constructor argument, so `self.item_definition[...]` is a module's primary configuration channel.
_Avoid_: item def, menu def, definition.

**config_option**:
The dotted `Config` key a menu item edits (`"filter.object_types"`, `"equipment.active_telescope"`). Selecting the item writes through `Config`; `filter.*` keys also mirror onto `catalogs.catalog_filter`.
_Avoid_: setting, config key (in prose), option.

### Modules

**UIModule**:
The base class for every screen (`ui/base.py`). Owns a `self.screen` PIL image sized to the display instance's `resolution` (128×128 on the SSD1351, 176×176 on the SSD1333), the `key_*` handlers, the lifecycle hooks, and the display-mode cycle. The bare word "module" in this context means a `UIModule` subclass or instance.
_Avoid_: screen class, widget, view, page.

**Screen**:
Either the `self.screen` PIL image a module draws into, or, loosely, the module currently shown. Prefer "the active module" for the latter to avoid ambiguity.
_Avoid_: canvas, frame (a "frame" is a camera image).

**UITextMenu**:
The general scrolling-list module (`ui/text_menu.py`). The root menu and every submenu are `UITextMenu` instances; it handles single/multi selection and writes `config_option`s.
_Avoid_: list module, text list.

**Carousel**:
The centre-magnified scrolling list a `UITextMenu` draws: the focus line (the selected item) sits at the vertical centre in the large font at full brightness, and neighbouring rows shrink and dim with distance (a "fisheye" falloff). `UIObjectList` uses a uniform-row variant (every row in the base font, the focus row in bold). Row geometry — count, positions, fonts, the focus selection box — is computed by `ui/layout.py` (`carousel_layout` / `list_layout`) from the display instance's `resolution`, `titlebar_height`, font metrics and the `menu_visible_items` knob, so the same code lays out on the 128 and 176 panels.
_Avoid_: fisheye menu (in code/glossary — describe it as the carousel), spinner, wheel.

**display_class**:
The constructor argument carrying a `DisplayBase` **instance** (not a class, despite the name) — the source of `device`, `colors`, `fonts`, and `resolution`. `DisplayHeadless` is the no-hardware variant.
_Avoid_: display, screen driver (in code-arg context).

**Lifecycle hooks** (`active` / `inactive` / `update` / `screen_update`):
`active`/`inactive` fire when a module reaches / leaves the top of the stack; `update` is the per-frame redraw a module overrides; `screen_update` draws the title bar and finalises the frame.
_Avoid_: on_show / on_hide, render (use `update`/`screen_update`).

**Self-gating module**:
A module that enforces its own runtime **precondition** rather than relying on the menu to block entry. It always opens; when the precondition is unmet it draws a "set X first" notice (via `UIModule.draw_gate_message`) instead of its normal UI, keeps its key handlers and exit callback inert, and lets the user **back out** with LEFT/Cancel. The precondition check is live (re-read each `update`). Example: `UITimeEntry`/`UIDateEntry` gate on a location fix. See [ADR 0019](../../adr/0019-ui-modules-self-gate-preconditions.md).
_Avoid_: gated menu item, hard block, disabled screen (the menu never refuses to open a self-gating module).

### Navigation

**MenuManager**:
The single object (`ui/menu_manager.py`) that owns the navigation stack, dispatches keys to the active module, runs the render loop, and serialises UI state for the API. Constructed once in `main.py`.
_Avoid_: navigator, router, controller.

**Stack** (the navigation stack):
`MenuManager.stack: list[UIModule]`. Index `0` is the root menu; index `-1` is the **active module**. Opening a screen pushes (`add_to_stack`); "back" pops (`remove_from_stack`).
_Avoid_: history, breadcrumb, navigation list.

**Active module**:
`stack[-1]` — the module that currently receives key presses and gets redrawn.
_Avoid_: current screen, focused module, top module.

**Key dispatch**:
The flow where `MenuManager.key_*` forwards a keypad event to `stack[-1].key_*`, after first checking for help mode and marking-menu mode.
_Avoid_: event routing, input handling.

**Keypad layout**:
The physical pad is **TKL / calculator style — `7 8 9` is the TOP row**, not phone style. The full grid (from `keyboard_pi.py`'s `keymap`) is:

```
7  8  9   (na)
4  5  6   PLUS
1  2  3   MINUS
   0      SQUARE
LEFT UP DOWN RIGHT
```

So when a module maps number keys to on-screen **2×2 screen quadrants**, the spatially-faithful corners are `7`=top-left, `9`=top-right, `1`=bottom-left, `3`=bottom-right (used by daytime alignment's quadrant picker). `SQUARE`+key sends the `ALT_*` variant; a long press sends the `LNG_*` variant (long-`SQUARE` opens the marking menu).
_Avoid_: assuming phone-style `1 2 3` on top — it is inverted.

**Power key** (`POWER_BTN` / `key_power`):
The dedicated hardware power button, dispatched as a normal keypad event in **key dispatch**. Its meaning is "open the shutdown confirmation": from any active module it jumps (`jump_to_label`) to the `shutdown` menu item. On that confirmation screen it doubles as **select** (behaves like the right key), so one press raises the confirmation and a second press confirms.
_Avoid_: power switch / off button (it does not cut power directly — it opens the normal shutdown menu), kill switch.

**Display mode**:
A per-module variant cycled by the square key via `cycle_display_mode()` over the class's `_display_mode_list` (default `[None]`; e.g. `UIGPSStatus` has `["large", "detailed"]`).
_Avoid_: view mode, layout, skin.

**jump_to_label**:
`MenuManager.jump_to_label(label)` — navigate directly to the menu item with that `label`, either by finding it in the tree or, for special cases like `recent`, by truncating the stack to an existing instance.
_Avoid_: goto, navigate_to.

### Preloading and reuse

**Preload** (`preload: True`):
Flag on a menu item that makes `MenuManager` instantiate the module eagerly at startup (`preload_modules`) rather than on first open — used for expensive modules (chart, align) whose construction would otherwise stall the UI. A preloaded module is implicitly stateful.
_Avoid_: eager load, prefetch.

**Stateful** (`stateful: True`):
Flag that makes the instantiated module be cached on its menu item as `item["state"]` and reused on subsequent opens, preserving in-memory state.
_Avoid_: cached, singleton, persistent.

### Marking menus

**Marking menu**:
The four-direction radial overlay (`MarkingMenu`) drawn over the current screen, toggled by long-press of square. Each direction is a `MarkingMenuOption`. In user-facing prose (user guide, on-device help) this is the **Quick Menu**; "marking menu" is the code/architecture term.
_Avoid_: radial menu, context menu, pie menu (the rendering is a pie, but the concept is "marking menu").

**Marking-menu option** (`MarkingMenuOption`):
One slice of a marking menu: a `label` plus a `callback`, a nested `MarkingMenu`, or a `menu_jump`. The `up` slice defaults to HELP.
_Avoid_: marking item, menu button.

**Marking-menu stack**:
`MenuManager.marking_menu_stack` — the stack of currently-open (possibly nested) marking menus. Non-empty means the UI is in marking-menu mode and direction keys select options instead of reaching the active module.
_Avoid_: overlay stack.

### Text entry

**Name Search**:
The Objects-menu feature for finding objects by name: `UITextEntry` in its search personality, re-querying the catalog collection as the user types. Which system interprets the number keys is the **search input method**.
_Avoid_: text search (reserve for the catalog-side algorithm), object search.

**Search input method** (`search_input_method`):
The user-selectable system that turns number-key presses into a Name Search query: **multi-tap** (the default) or **T9**. Chosen at Settings → User Pref → Search Input, jumpable from the Name Search marking menu. Applies to Name Search only — **free-text mode** is always multi-tap.
_Avoid_: input mode, text entry method, T9 search on/off (the retired boolean framing).

**Multi-tap**:
The default search input method: pressing a number key cycles through that key's characters (`7` → `7 a b c`…); pausing, or pressing a different key, commits the character and moves on. Produces a text query backed by the catalog context's **text search**. Spelled "multi-tap" in prose, "Multi-Tap" as the menu option.
_Avoid_: T9 (a long-standing misnomer for this system — T9 is the other one), multitap.

**T9** (as input method):
The opt-in search input method: each key press appends its digit — one press per letter — and the digit string is matched against object names translated to keypad digits, backed by the catalog context's **T9 search**. Matching uses PiFinder's own key layout (`7→abc`, `1→tuv`), not the standard phone layout.
_Avoid_: predictive text (it matches catalog names, not a language dictionary).

**Free-text mode** (`text_entry_mode`):
`UITextEntry`'s other personality: editing an arbitrary string (e.g. a location name) returned via callback, with no live search. Always multi-tap — T9 cannot apply because there is no name list to match against.
_Avoid_: text entry mode in prose (ambiguous with the screen's own name; the code flag is `text_entry_mode`).

### Dynamic menus

**Dynamic equipment menu**:
The telescope/eyepiece submenus built at runtime by `dyn_menu_equipment(cfg)` from `cfg.equipment`, spliced into the menu item labelled `equipment`. The only part of the menu tree built from user data rather than authored statically.
_Avoid_: equipment list, generated menu.

### UI state

**UIState**:
The small mutable object (`state.py`) holding UI-process state — observing list, recent objects, target, message/hint timeouts, FPS flag. Installed on `shared_state` via `set_ui_state`; every module reads `shared_state.ui_state()`.
_Avoid_: ui config, session state.

**Target** (`ui_state.target()`):
The most-recently **selected object**, mirrored into `UIState` by `UIObjectDetails` (`update_object_info`) so cross-screen consumers can mark it — the **chart** draws it as a full-brightness cross (+ off-screen pointer, and its designator label when on-screen), and telemetry records it. Distinct from the Catalog *selected object* (the live `UIObjectDetails` cursor, see [Catalog](../catalog/CONTEXT.md)): the target is the **persisted last selection**, surviving after you leave details. Not a push-to concept — it follows selection automatically.
_Avoid_: push-to target, goto target.

**Published UI state** (`serialize_current_ui_state`):
The dict `MenuManager` writes to `shared_state.set_current_ui_state(...)` each redraw — `ui_type`, `title`, marking-menu options, and the active module's own `serialize_ui_state()`. This is what `/api/current-selection` reflects.
_Avoid_: api state, ui snapshot.

### Focus indicator

The focus screen's quantitative focus-quality aid. Lives entirely inside `UIPreview` (the **Focus** menu item, titled "CAMERA") in the main process. Self-contained: it does its own star finding and measurement and shares no code with **SQM** photometry.

**HFD** (Half-Flux Diameter):
The focus-quality metric — the diameter (in pixels) of the circle enclosing half a star's background-subtracted flux: `2 · Σ(fluxᵢ·rᵢ) / Σ(fluxᵢ)` over aperture pixels. Lower = sharper. Chosen over FWHM because it stays stable and monotonic on saturated cores and broad defocused blobs, where a Gaussian fit fails.
_Avoid_: FWHM (a different, fit-based metric — not what we compute), star size, spot size, sharpness.

**Detected star**:
A blob the focus screen's own lightweight detector finds in the raw 512×512 frame, deliberately tuned to accept broad/defocused blobs. HFD is measured on blobs up to a ~50 px size cap; broader blobs remain available for visual magnification. The few brightest measurable stars are what HFD is measured on. Distinct from a **matched star** (the solver's tetra3 catalog match), which goes to zero when defocused.
_Avoid_: centroid (reserve for the solver/SQM sense), matched star, blob (in prose; fine informally).

**Focus HFD** (the reported value):
The **median** HFD over the four brightest measurable stars — steadier frame-to-frame than any single star and representative of the four focus tiles. When someone says "the HFD" on the focus screen, this is it.
_Avoid_: best HFD (that's the marker), single-star HFD.

**Focus tiles**:
The 2×2 view made by repacking the four brightest detected stars from anywhere in the camera frame. Each tile is centered on the star's background-subtracted flux centroid and enlarged with nearest-neighbour sampling; no display stretch or filtering changes the star pixels. After initial selection, stars retain their quadrant through brightness changes. Tracking matches the relative 2--4-star pattern under one shared image translation, so moving the image while adjusting focus does not reshuffle the tiles; a missing star is replaced by the brightest unused candidate. Missing stars leave black tiles. The current **focus HFD** is shown at the intersection, with the rolling 10-second HFD signal split around it along the middle divider. The recent signal range is centered on the divider and lower HFD appears below it; a minimum 1.0-HFD display span avoids magnifying tiny measurement noise. Missing measurements add no points, so existing samples recede with wall time; the next numeric measurement starts a fresh signal. No absolute good-focus threshold, guide, marker, or under-stroke is drawn.
_Avoid_: processed preview, enhanced stars, focus strip.

**Focus display mode**:
One of the four Focus-screen views cycled with short `square`, following the normal **display mode** convention: **Stars** (the four focus tiles and HFD history), **Single** (the brightest tracked star at twice the Stars magnification, with HFD and history on a translucent lower-third overlay), **Image** (the complete frame with the original per-frame autocontrast applied for display only), and **Stats** (HFD, supplementary area-equivalent FWHM, detected-star count, exposure mode/value, gain, and a log-scaled raw histogram). HFD, centroids, and the Stats histogram always use the unstretched raw frame. Every unavailable HFD readout is shown as `?.?`; no upper-limit sentinel is displayed.
_Avoid_: tab, page, focus-strip mode.

**Focus FWHM estimate**:
The median area-equivalent diameter of the pixels above half local maximum for the same four brightest measurable stars. It is supplementary diagnostics on the Stats display mode, not the focus-quality metric; HFD remains primary because it behaves better on saturated, broad, and donut-shaped stars.
_Avoid_: focus FWHM (when used as a replacement for HFD), fitted FWHM (there is no Gaussian fit).

**Adaptive focus zoom**:
The magnification used by the Stars and Single views. A compact star defaults to 10× relative to the former full-frame preview in Stars (a 26×26 native crop on square displays); Single maps that crop across the full panel, giving twice the apparent magnification. For a broad star the crop grows to include its detected extent plus margin, lowering effective magnification instead of clipping it. In the Stars and Single display modes, `+` and `-` adjust the nominal zoom from 4× to 16×. Short `square` cycles display modes.
_Avoid_: optical zoom, solver zoom.

## Boundary terms

- **`shared_state`** is read and written by the UI but **owned by Positioning**. See [Positioning](../positioning/CONTEXT.md). The UI publishes the screen image and UI-state dict onto it; it reads `solution()`, `imu()`, `sqm()`, `location()`, `altaz_ready()`.
- **`catalogs` / `CompositeObject` / `CatalogFilter`** belong to the **Catalog** context. See [Catalog](../catalog/CONTEXT.md). `UIObjectList`, `UIObjectDetails` and `UITextEntry` consume them.
- **`sqm()` / SQM tooling** belongs to the **SQM** context. See [SQM](../sqm/CONTEXT.md). `UISQM` and the calibration/correction/sweep modules surface it.
- **`command_queues`** are the inter-process channels (camera, gps, console, align, ui_queue). The UI only `.put()`s onto them; the consumers live in other processes.

## Flagged ambiguities

- **"display_class"** is a misnomer: the constructor argument is a `DisplayBase` **instance**, not a type. Keep the identifier name; in prose say "the display instance".
- **"Screen"** is overloaded — `self.screen` (a PIL image) vs. "the screen the user sees" (the active module). Prefer "active module" for the latter.
- **"Stack"** means the navigation stack (`MenuManager.stack`) unless qualified as the "marking-menu stack". They are independent.
- **"Selected"** in this context refers to the highlighted item in a `UITextMenu` cursor or a checked multi-select value. The Catalog context's "selected object" / "enabled catalog" distinctions are separate — see [Catalog](../catalog/CONTEXT.md).
- **"Label" vs "name"** — `label` is the stable internal identifier (for `jump_to_label`); `name` is the user-visible, translated display string. They are different keys on the same menu item.
- **"Preload" vs "stateful"** — preload is *when* (eagerly at boot); stateful is *whether reused* (cached on the item). Preload implies stateful, but a module can be stateful without being preloaded.

## Example dialogue

> **Dev:** I want a test that opens the chart screen and presses the square key a few times.
>
> **Domain:** The chart is a **UIModule** (`UIChart`) reached from a **menu item** in the **menu tree**. To construct it you supply the ten injected dependencies — most importantly a **display instance** (`get_display("headless")`) and a `shared_state` with a **UIState** installed. The chart is **preloaded** and **stateful**, so in the real app it's built once at boot and reused; in a test you can just call its `class` directly.
>
> **Dev:** Anything special about the chart?
>
> **Domain:** Yes — `UIChart` builds a `Starfield`, which loads the Hipparcos catalog from `hip_main.dat`. That file is git-ignored and doesn't ship, so provide it or stub `plot.Starfield`. The square key by default cycles the module's **display mode**, but `UIChart` doesn't override `key_square`, so it'll just cycle its (single) mode.
>
> **Dev:** And to test navigation between screens?
>
> **Domain:** Drive a real **MenuManager**. Its **stack** owns the open modules; `add_to_stack`/`remove_from_stack` push and pop. `key_right` on a **UITextMenu** opens the highlighted child; `key_left` pops back. The **active module** is always `stack[-1]`. The marking menu (long-square) lives on a separate **marking-menu stack** and intercepts direction keys when open.
