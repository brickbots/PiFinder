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
The base class for every screen (`ui/base.py`). Owns a 128x128 `self.screen` PIL image, the `key_*` handlers, the lifecycle hooks, and the display-mode cycle. The bare word "module" in this context means a `UIModule` subclass or instance.
_Avoid_: screen class, widget, view, page.

**Screen**:
Either the `self.screen` PIL image a module draws into, or, loosely, the module currently shown. Prefer "the active module" for the latter to avoid ambiguity.
_Avoid_: canvas, frame (a "frame" is a camera image).

**UITextMenu**:
The general scrolling-list module (`ui/text_menu.py`). The root menu and every submenu are `UITextMenu` instances; it handles single/multi selection and writes `config_option`s.
_Avoid_: list module, text list.

**display_class**:
The constructor argument carrying a `DisplayBase` **instance** (not a class, despite the name) — the source of `device`, `colors`, `fonts`, and `resolution`. `DisplayHeadless` is the no-hardware variant.
_Avoid_: display, screen driver (in code-arg context).

**Lifecycle hooks** (`active` / `inactive` / `update` / `screen_update`):
`active`/`inactive` fire when a module reaches / leaves the top of the stack; `update` is the per-frame redraw a module overrides; `screen_update` draws the title bar and finalises the frame.
_Avoid_: on_show / on_hide, render (use `update`/`screen_update`).

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
The four-direction radial overlay (`MarkingMenu`) drawn over the current screen, toggled by long-press of square. Each direction is a `MarkingMenuOption`.
_Avoid_: radial menu, context menu, pie menu (the rendering is a pie, but the concept is "marking menu").

**Marking-menu option** (`MarkingMenuOption`):
One slice of a marking menu: a `label` plus a `callback`, a nested `MarkingMenu`, or a `menu_jump`. The `up` slice defaults to HELP.
_Avoid_: marking item, menu button.

**Marking-menu stack**:
`MenuManager.marking_menu_stack` — the stack of currently-open (possibly nested) marking menus. Non-empty means the UI is in marking-menu mode and direction keys select options instead of reaching the active module.
_Avoid_: overlay stack.

### Dynamic menus

**Dynamic equipment menu**:
The telescope/eyepiece submenus built at runtime by `dyn_menu_equipment(cfg)` from `cfg.equipment`, spliced into the menu item labelled `equipment`. The only part of the menu tree built from user data rather than authored statically.
_Avoid_: equipment list, generated menu.

### UI state

**UIState**:
The small mutable object (`state.py`) holding UI-process state — observing list, recent objects, target, message/hint timeouts, FPS flag. Installed on `shared_state` via `set_ui_state`; every module reads `shared_state.ui_state()`.
_Avoid_: ui config, session state.

**Published UI state** (`serialize_current_ui_state`):
The dict `MenuManager` writes to `shared_state.set_current_ui_state(...)` each redraw — `ui_type`, `title`, marking-menu options, and the active module's own `serialize_ui_state()`. This is what `/api/current-selection` reflects.
_Avoid_: api state, ui snapshot.

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
