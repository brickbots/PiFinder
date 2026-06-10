# The UI menu system

This document describes how PiFinder builds, navigates, and renders its
on-device user interface: the menu tree, the `UIModule` base class and
its concrete screens, the `MenuManager` that owns the navigation stack
and dispatches key presses, and the supporting concepts (preloading,
stateful modules, marking menus, the dynamic equipment menu). It closes
with a practical section on constructing `UIModule`s outside the running
app for a test harness.

The bulk of the system lives in `python/PiFinder/ui/`:
`base.py` (the `UIModule` base class), `menu_manager.py`
(`MenuManager`), `menu_structure.py` (the `pifinder_menu` tree),
`text_menu.py` (`UITextMenu`), plus one module per screen.

For the canonical glossary of terms, see [`ui/CONTEXT.md`](./ui/CONTEXT.md).

---

## 1. The big picture

```
   menu_structure.pifinder_menu   (one big nested dict literal)
        │  each node is a "menu item": {class, name, label, items, …}
        ▼
   MenuManager(__init__)                       PiFinder/ui/menu_manager.py:107
        │
        ├── dyn_menu_equipment(cfg)   ← splices telescope/eyepiece submenus in
        ├── preload_modules()         ← instantiates modules marked preload=True
        └── add_to_stack(pifinder_menu) ← root UITextMenu becomes stack[0]
                 │
                 ▼
   self.stack: list[UIModule]   (a navigation stack; top = active screen)
        │
        │  key events arrive from the keyboard/web process and are
        │  dispatched to the active module:
        │
   MenuManager.key_*  ──►  stack[-1].key_*       PiFinder/ui/menu_manager.py:342
        │
        ├── UITextMenu.key_right ──► add_to_stack(selected child item)
        ├── key_left            ──► remove_from_stack()  (pop, unless overridden)
        └── key_long_square     ──► marking menu overlay
                 │
                 ▼
   MenuManager.update()  ──►  stack[-1].update() ──► screen_update()
        │                                          PiFinder/ui/base.py:288
        └── update_screen(img) ──► display.device.display(img)
                                  + shared_state.set_screen(img)
                                  + shared_state.set_current_ui_state(serialize…)
```

Each `UIModule` owns a `PIL.Image` (`self.screen`) sized to the display
instance's `resolution` (128×128 on the SSD1351, 176×176 on the SSD1333)
that it draws into.
`MenuManager.update()` asks the active module to redraw, then pushes the
resulting image both to the physical display and onto `shared_state` so
the web/API layer can mirror it. The whole UI runs in the **main
process** (see `main.py`); other processes interact with it only through
`shared_state` and the `command_queues`.

---

## 2. The menu-item dict schema

`menu_structure.pifinder_menu` (`PiFinder/ui/menu_structure.py:34`) is a
single nested Python dict literal. Every node is a **menu item** — a
plain `dict`. There is no class for it; the schema is by convention. The
keys observed across the whole tree (counts from a grep over
`menu_structure.py`):

| Key | Type | Meaning |
| --- | --- | --- |
| `name` | `str` | Display label for the item (wrapped in `_()` for i18n). Also overrides the module's `self.title` — `base.py:151`. |
| `class` | `Type[UIModule]` | The `UIModule` subclass to instantiate when this item is opened. The root and every submenu use `UITextMenu`; leaf screens use `UIChart`, `UIObjectList`, etc. |
| `select` | `"single" \| "multi"` | For `UITextMenu` only: single-choice vs multi-select (checkbox) list — read at `text_menu.py:30`. |
| `items` | `list[dict]` | Child menu items. Presence of `items` makes a node a submenu. |
| `value` | any | The config/selection value this item carries (e.g. a catalog code `"NGC"`, or an equipment object). Read by `UITextMenu` and `UIObjectList`. |
| `label` | `str` | Stable, unique identifier used by `find_menu_by_label` / `jump_to_label` (`menu_manager.py:38`, `:224`). Not all items have one. |
| `config_option` | `str` | Dotted config key this item edits (e.g. `"filter.object_types"`, `"equipment.active_telescope"`). Selecting writes through `Config` and, for `filter.*`, mirrors onto `catalogs.catalog_filter` — `text_menu.py:50`, `:199`. |
| `objects` | `str` | For `UIObjectList`: which object source to show — `"catalogs.filtered"`, `"catalog"` (use `value` as the catalog code), `"recent"`, or `"custom"` (use `object_list`) — `object_list.py:182`. |
| `callback` | callable | Called with the current module instead of opening a class (`text_menu.py:181`). Used for action items. |
| `pre_callback` / `post_callback` | callable | Run before `add_to_stack` / after a selection commits — `text_menu.py:193`, `:268`. |
| `value_callback` | callable | Computes the initially-selected value(s) for the list — `text_menu.py:43`. |
| `name_suffix_callback` | callable | Computes a dynamic suffix appended to an item's display name each redraw — `text_menu.py:120`. |
| `custom_callback` | callable | Used by entry screens (date/time/location/radec) — read in those constructors. |
| `start_index` | `int` | Initial cursor position for a `UITextMenu` — `text_menu.py:28`. |
| `stateful` | `bool` | If true, the instantiated module is cached on the item dict as `item["state"]` and reused next time — `menu_manager.py:211`. |
| `preload` | `bool` | If true, the module is instantiated eagerly at startup by `preload_modules` — `menu_manager.py:166`. Implies it is also reused (its instance is stored as `item["state"]`). |

Two more keys are written **at runtime**, not authored:

- `item["state"]` — the cached module instance for stateful/preloaded
  items (`menu_manager.py:173`, `:212`).
- `item["foo"] = "Bar"` — a harmless marker `collect_preloads` stamps on
  every visited node during its tree walk (`menu_manager.py:26`).

Some leaf items are constructed at runtime rather than authored in the
tree — e.g. `key_long_right` builds an `object_details` item on the fly
with `class`, `object`, `object_list`, `label`
(`menu_manager.py:401`). So `object`/`object_list` are also valid
item-definition keys even though they don't appear in the static tree.

### 2.1 The whole item dict becomes `item_definition`

When `MenuManager` instantiates a module it passes the entire item dict
as the `item_definition` constructor argument (`menu_manager.py:205`).
So every key above is available to the module as
`self.item_definition[...]`. This is the primary configuration channel
for a screen: `UIObjectList` reads `item_definition["objects"]`,
`UIObjectDetails` reads `item_definition["object"]`, `UITextMenu` reads
`item_definition["items"]` / `["select"]` / `["config_option"]`, and so
on.

---

## 3. The `UIModule` base class

`UIModule` (`PiFinder/ui/base.py:91`) is the base for every screen.

### 3.1 Constructor — dependency injection

```python
def __init__(
    self,
    display_class,          # a DisplayBase instance (NOT a class, despite the name)
    camera_image,           # shared 512x512 PIL RGB image (camera frame)
    shared_state,           # SharedStateObj (or its manager proxy)
    command_queues,         # dict[str, Queue] for talking to other processes
    config_object,          # Config
    catalogs,               # Catalogs
    item_definition={},     # the menu-item dict (see §2)
    add_to_stack=None,      # MenuManager.add_to_stack
    remove_from_stack=None, # MenuManager.remove_from_stack
    jump_to_label=None,     # MenuManager.jump_to_label
):
```
(`base.py:114`)

Key things the constructor does:

- `assert shared_state is not None` (`base.py:127`) — **shared_state is
  mandatory**; everything else has a default or is tolerant of `None`.
- Pulls render primitives off `display_class`: `self.display =
  display_class.device`, `self.colors`, `self.fonts`,
  `self.display_class.resolution` (`base.py:130`, `:145`, `:147`).
  Despite the parameter name, `display_class` is an **instance** of a
  `DisplayBase` subclass, not the type.
- `self.ui_state = shared_state.ui_state()` (`base.py:134`) — so a
  `UIState` must have been installed on `shared_state` via
  `set_ui_state` first, or this returns `None` and later
  `ui_state.message_timeout()` calls blow up.
- Allocates `self.screen = Image.new("RGB", resolution)` and a
  `self.draw` over it (`base.py:145`).
- Sets up the **display-mode cycle**: `self._display_mode_cycle =
  cycle(self._display_mode_list)` and `self.display_mode = next(...)`
  (`base.py:142`). The class attribute `_display_mode_list` defaults to
  `[None]` (`base.py:111`); subclasses override it (e.g. `UIGPSStatus`
  uses `["large", "detailed"]`, `gpsstatus.py:37`).
- `self.title = item_definition.get("name", self.title)` — the
  menu-item `name` becomes the title-bar text (`base.py:151`).
- Builds a `RotatingInfoDisplay` (`base.py:164`) that alternates
  constellation/SQM in the title bar; it reads `shared_state.solution()`
  and `shared_state.sqm()`.

### 3.2 Lifecycle methods

- `active()` / `inactive()` (`base.py:166`, `:173`) — called by
  `MenuManager` when a module becomes the top of the stack / is covered
  or popped. Base implementations are no-ops; subclasses override (e.g.
  to start/stop camera streaming via `command_queues`).
- `update(force=False)` (`base.py:208`) — the per-frame redraw hook.
  Subclasses draw into `self.screen` then call `self.screen_update()`.
  Base `update` just calls `screen_update()`.
- `screen_update(title_bar=True, button_hints=True)` (`base.py:288`) —
  draws the title bar (title, FPS, GPS/cam/IMU status icons, rotating
  info) on top of `self.screen`. Reads `shared_state.imu()`,
  `solve_state()`, `solution()`, `altaz_ready()`. Returns early if a
  message popup is still showing (`ui_state.message_timeout()`).
- `clear_screen()` / `message(...)` (`base.py:219`, `:233`) — helpers;
  `message` draws a transient popup and sets a timeout on `ui_state`.
- `help()` (`base.py:180`) — returns a list of help images loaded from
  `utils.pifinder_dir / "help" / __help_name__ / N.png`, or `None` if
  `__help_name__` is empty. Triggered from the marking menu.

### 3.3 The `key_*` methods

The base defines the full keypad surface (`base.py:393`–`:431`); the
manager dispatches to whichever the active module implements:

| Method | Default behaviour |
| --- | --- |
| `key_number(number)` | no-op |
| `key_plus()` / `key_minus()` | no-op |
| `key_square()` | `cycle_display_mode()` then `update()` — `base.py:402` |
| `key_up()` / `key_down()` / `key_right()` | no-op |
| `key_left()` | returns `True` → tells `MenuManager` to pop this module off the stack. Return `False` to stay (`base.py:424`). |
| `key_long_up/down/right()` | no-op |

`cycle_display_mode()` (`base.py:385`) advances `self.display_mode`
through `_display_mode_list`. `key_square` is wired to it by default, so
"the square button cycles display modes" unless a subclass overrides
`key_square`.

Note: there is **no** `key_long_left` or `key_long_square` on the base
module — those are handled entirely by `MenuManager` (return-to-root and
marking-menu toggle respectively).

### 3.4 `marking_menu`

`self.marking_menu` (class attribute default `None`, `base.py:112`) is an
optional `MarkingMenu` dataclass (`marking_menus.py:33`) describing the
four-direction radial overlay for this screen. Subclasses set it in their
constructor (e.g. `UIChart` gives it a "Settings" jump, `chart.py:43`).

### 3.5 `serialize_ui_state`

Optional. If a module defines `serialize_ui_state()`, `MenuManager`
calls it to enrich the published UI-state dict (`menu_manager.py:573`).
`UITextMenu` implements it (current index, item, selection)
(`text_menu.py:279`). This is what the `/api/current-selection` endpoint
ultimately reflects.

---

## 4. `MenuManager`

`MenuManager` (`PiFinder/ui/menu_manager.py:107`) is constructed once in
`main.py:524` and owns the live UI.

### 4.1 The stack model

`self.stack: list[UIModule]` is the navigation stack
(`menu_manager.py:129`). The element at index `0` is the root menu; the
element at `-1` is the **active module** that receives keys and gets
redrawn. The constructor seeds it with `add_to_stack(pifinder_menu)`
(`menu_manager.py:130`).

- `add_to_stack(item)` (`menu_manager.py:186`): if the item already has a
  cached `item["state"]` (stateful/preloaded), it reuses that instance;
  otherwise it instantiates `item["class"](...)` passing all the
  injected dependencies plus the item dict as `item_definition`. If the
  item is `stateful`, the new instance is cached on `item["state"]`. The
  previous top gets `inactive()`, the new top gets `active()`.
- `remove_from_stack()` (`menu_manager.py:155`): pops the top (never
  below length 1), calling `inactive()` on the popped module and
  `active()` on the newly exposed one. Drives the slide animation.

### 4.2 Key dispatch

Every `MenuManager.key_*` forwards to `self.stack[-1].key_*`
(`menu_manager.py:342`–`:481`), with three pre-emptions checked first:

1. **Help mode** — if `self.help_images is not None`, most keys exit help
   (`key_up`/`key_down` page through the help images instead).
2. **Marking-menu mode** — if `self.marking_menu_stack` is non-empty,
   direction keys select marking-menu options (`mm_select`) rather than
   reaching the module.
3. Otherwise the key reaches the active module.

`key_left` is special: the manager calls `stack[-1].key_left()` and only
pops the stack if it returns `True` (`menu_manager.py:440`) — this is how
a screen can intercept "back". `key_long_left` resets the stack to just
the root (`menu_manager.py:410`). `key_long_right` jumps to the most
recent object's detail screen (`menu_manager.py:396`).

### 4.3 The render loop

`MenuManager.update()` (`menu_manager.py:279`): bails if in help or
marking-menu mode, else calls `stack[-1].update()` and then
`update_screen(...)` with either the plain top image or a slide-animation
composite. `update_screen` (`menu_manager.py:323`) converts the image to
the device mode, **always** publishes `serialize_current_ui_state()` to
`shared_state.set_current_ui_state(...)`, and (unless a popup timeout is
active) calls `display_class.device.display(...)` and
`shared_state.set_screen(...)`.

### 4.4 `serialize_current_ui_state`

`menu_manager.py:517` builds the dict the API exposes: `ui_type` (the
class name of `stack[-1]`), `title`, marking-menu options if active, and
the module's own `serialize_ui_state()` output if it has one.

---

## 5. Preloading and stateful modules

- **Stateful** (`stateful: True`): the instance is cached on the item
  dict (`item["state"]`) the first time it's opened and reused
  thereafter, preserving its in-memory state across visits
  (`menu_manager.py:211`). Used for `UIChart` and `UIAlign`.
- **Preload** (`preload: True`): the module is instantiated *eagerly* at
  startup. `collect_preloads()` (`menu_manager.py:18`) walks the whole
  menu tree and returns every item with `preload == True`;
  `preload_modules()` (`menu_manager.py:166`) instantiates each and
  stores it on `item["state"]` — so a preloaded module is implicitly
  stateful too. The motivation is cost: `UIChart` and `UIAlign` both
  build a `plot.Starfield`, which parses the Hipparcos catalog (see
  §8) — doing that lazily on first open would stall the UI for over a
  second, so it's paid up front at boot.

In the current tree only `UIChart` and `UIAlign` carry
`stateful`/`preload` (`menu_structure.py:51`, `:64`).

### 5.1 Tree-walk helpers

`collect_preloads` and `find_menu_by_label` (`menu_manager.py:18`, `:38`)
share a DFS pattern over `pifinder_menu`. Note the quirk: for each node
they iterate its items and **`break` on the first child dict**, so the
walk descends through `items` lists (which are iterated with `extend`)
rather than scanning every dict-valued key. `find_menu_by_label` returns
the first item whose `label` matches; labels are expected to be unique.

---

## 6. Marking menus

A **marking menu** is a four-direction radial overlay (up/down/left/right
slices) drawn on top of the current screen. The data model is two
dataclasses in `marking_menus.py`: `MarkingMenu` (the four
`MarkingMenuOption`s) and `MarkingMenuOption` (`enabled`, `label`,
`selected`, `callback`, `menu_jump`). `up` defaults to a "HELP" option
(`marking_menus.py:38`).

- A long-press of square (`key_long_square`, `menu_manager.py:357`)
  pushes the active module's `self.marking_menu` onto
  `self.marking_menu_stack` and renders it; pressing again exits.
- While the marking menu is up, direction keys call `mm_select`
  (`menu_manager.py:483`): a `MarkingMenuOption` whose `callback` is
  itself a `MarkingMenu` opens a nested marking menu; `label == "HELP"`
  loads `self.help()`; `menu_jump` calls `jump_to_label`; a plain
  `callback` is invoked with `(marking_menu, option)`.
- `render_marking_menu` (`marking_menus.py:49`) draws the pie slices,
  curved labels and arrows over a dimmed copy of the screen captured into
  `self.marking_menu_bg`.

---

## 7. The dynamic equipment menu

`dyn_menu_equipment(cfg)` (`menu_manager.py:60`) is called once in the
`MenuManager` constructor (`menu_manager.py:144`). It mutates the static
tree at runtime: it finds the item labelled `"equipment"`
(`find_menu_by_label`), builds a `UITextMenu` submenu for telescopes and
one for eyepieces from `cfg.equipment.telescopes` /
`cfg.equipment.eyepieces`, and assigns them as that item's `items`. The
eyepiece/telescope submenus are single-select with
`config_option = "equipment.active_eyepiece"` /
`"equipment.active_telescope"`, so selecting one writes the active
equipment back to config. This is the only place the menu tree is built
from user data rather than being authored statically.

---

## 8. External / hardware / network dependencies per module

Most modules need only the injected dependencies (§3.1) and draw from
`shared_state`. The exceptions — modules with an extra data, file,
hardware, or network dependency at construct or update time — are:

| Module | File | Extra dependency |
| --- | --- | --- |
| `UIChart` | `chart.py:32` | Builds `plot.Starfield`, which loads the **Hipparcos** catalog and constellation lines (see §8.1). Heavy; this is why it's preloaded. |
| `UIAlign` | `align.py:89` | Same `plot.Starfield` (Hipparcos). Also drives alignment via `command_queues["align_command"/"align_response"]` and reads/writes `shared_state.set_solve_pixel`. |
| `UIObjectList` | `object_list.py:108` | Reads `catalogs` heavily (filtered/by-code lists). Loads marker PNGs from `PiFinder/markers/`. Constructor mutates the passed `item_definition` (`select`/`items`). |
| `UIObjectDetails` | `object_details.py:56`, `:77` | Requires `item_definition["object"]` and `["object_list"]`. Opens an `ObservationsDatabase` (SQLite, `~/PiFinder_data/observations.db`). Reads `catalogs`, `shared_state`. |
| `UILog` | `log.py:30`, `:44` | Requires `item_definition["object"]`. Opens `ObservationsDatabase`. |
| `UITextEntry` | `textentry.py:104` | In catalog-search mode opens `ObjectsDatabase` (the bundled `pifinder_objects.db`) and calls `catalogs.search_by_t9` / `search_by_text`. |
| `UISQM` | `sqm.py:54` | `update()` calls `self.camera_image.copy()` — needs a real `camera_image` (a `PIL.Image`, **not** `None`). Reads `shared_state.sqm()`, sends camera commands. |
| `UIPreview` | `preview.py:213` | Also `self.camera_image.copy()` — needs a real camera image; reads `shared_state.last_image_metadata()`. |
| `UISoftware` | `software.py:55`–`:74` | Constructor `open()`s `version.txt` and `wifi_status.txt` from `utils.pifinder_dir` (must exist). Update path does `requests.get(...)` to GitHub — network. |
| `UIStatus` | `status.py:47`, `:152` | `open()`s `wifi_status.txt` and `/sys/class/thermal/thermal_zone0/temp` (Linux/Pi-only file). |
| `UIGPSStatus` | `gpsstatus.py:58` | Sends to `command_queues["gps"]`; reads `shared_state.location()/sats()`. No data file, but the GPS process must be alive for live data. |
| `UIEquipment` | `equipment.py:5` | Imports `utils.get_sys_utils()` at module import (falls back to `sys_utils_fake` off-Pi). Reads `config_object.equipment`. |
| `UILocationList` | `location_list.py:46` | Reads/writes locations via `command_queues["gps"]`; expects `item_definition["items"]` populated with location values. |
| `UIConsole` | `console.py:43` | `Image.open()`s a welcome image from the markers/help assets; sends camera/debug commands. |
| `UISQMCalibration` / `UISQMCorrection` / `UISQMSweep` | `sqm_calibration.py:45`, `sqm_correction.py:35`, `sqm_sweep.py:33` | Not in the static menu tree — launched only via `UISQM`'s marking-menu callbacks. SQM tooling; needs camera + `shared_state` SQM data. |

The entry screens — `UIDateEntry` (`dateentry.py:14`), `UITimeEntry`
(`timeentry.py:16`), `UILocationEntry` (`locationentry.py:21`),
`UIRADecEntry` (`radec_entry.py:590`), `UINumericEntry`
(`numeric_entry.py`) — read optional `callback`/`custom_callback`/
coordinate keys from `item_definition` and otherwise need only the base
dependencies plus `shared_state` for the current date/time/location.

### 8.1 Hipparcos — the one thing that does NOT ship in the repo

`plot.Starfield.__init__` (`plot.py:88`) calls `_load_raw_stars()`
(`plot.py:28`), which reads `astro_data/hip_main.dat` (the Hipparcos
catalog, ~53 MB) via `skyfield.data.hipparcos.load_dataframe`, caching a
pickled DataFrame at `~/PiFinder_data/cache/hip_main.pkl`
(`plot.py:41`–`:67`).

**`hip_main.dat` is git-ignored and does NOT ship in the repo** (see
`python/.gitignore` — `astro_data/hip_main.dat`). It must be downloaded
or generated before `UIChart`/`UIAlign` can be constructed. By contrast,
the other data files `Starfield` and the catalogs need **do** ship and
are git-tracked:

- `astro_data/constellationship.fab` (`plot.py:115`) — constellation
  lines. Tracked.
- `astro_data/de421.bsp` — JPL ephemeris used via `sf_utils`. Tracked.
- `astro_data/pifinder_objects.db` — the catalog/objects SQLite DB.
  Tracked.

So a test harness that touches the chart/align screens must provide
`hip_main.dat` (or stub `plot.Starfield`); everything else the UI loads
is present in a fresh checkout. The path comes from
`utils.astro_data_dir`, which is relative to the process CWD
(`utils.py:11`–`:12`) — tests must run from `python/` (the same CWD the
app uses) or the relative `..`/`astro_data` lookups miss.

---

## 9. Constructing UIModules outside the running app (for tests)

A harness that wants to discover modules from `menu_structure`,
instantiate them, and exercise their `key_*` methods needs to supply the
ten constructor arguments from §3.1. Here is each one, how cheap it is to
build, and the gotchas.

### 9.1 `display_class` — cheap, headless

Use `PiFinder.displays.get_display("headless")`, which returns a
`DisplayHeadless` (`displays.py:164`). It renders to a luma `dummy`
device — no pygame, no SDL/X session, no SPI hardware — keeping the last
frame as a PIL image. This is exactly what the `pifinder-remote` skill
uses. `DisplayHeadless()` also builds `Colors` and `Fonts`, so
`display.colors` and `display.fonts` are ready. Despite the constructor
parameter being named `display_class`, you pass this **instance**, not
the class.

### 9.2 `shared_state` — can be built directly; manager proxy only needed cross-process

`SharedStateObj` (`state.py:258`) and `UIState` (`state.py:51`) are
**plain Python classes** — you can instantiate them directly:

```python
shared_state = SharedStateObj()
shared_state.set_ui_state(UIState())   # required — base.py:134 reads ui_state()
```

In the real app these are wrapped in a `multiprocessing.BaseManager`
proxy (`StateManager` in `main.py:133`–`:138`) **only so the object can
be shared across the camera/solver/GPS/web processes**. For an in-process
test harness that proxy is unnecessary — a direct `SharedStateObj()` is
both sufficient and faster. The one mandatory step is installing a
`UIState` via `set_ui_state`, because the `UIModule` constructor does
`self.ui_state = shared_state.ui_state()` and later code calls
`ui_state.message_timeout()`. (`shared_state` is the only argument the
base asserts non-None — `base.py:127`.)

Caveat: a few `SharedStateObj` reads start out empty by default —
`solution()` returns a fresh empty `PointingEstimate()` (`has_pointing()`
is `False` until the first solve), and `imu()`/`sqm()` return `None` —
which `screen_update` and several modules tolerate; but altaz-dependent
code paths stay inert without a GPS lock and datetime (`altaz_ready()` is
`False`).

### 9.3 `camera_image` — cheap PIL image (must be real for SQM/preview)

In the app this is a manager-shared `Image.new("RGB",(512,512))`
(`main.py:430`). For tests, a plain `PIL.Image.new("RGB",(512,512))` is
fine. It may be `None` for most modules, but `UISQM` and `UIPreview`
call `self.camera_image.copy()` in `update()`, so pass a real image if
exercising those.

### 9.4 `command_queues` — cheap dict of queues

A `dict` mapping `"camera" | "console" | "ui_queue" | "align_command" |
"align_response" | "gps"` to `queue.Queue` (or
`multiprocessing.Queue`) objects (`main.py:330`). For tests, plain
`queue.Queue()` instances work — nothing reads them back unless you also
run the consumer processes, but several modules `.put()` onto them in
`active()`/key handlers, so the keys must exist or you get a `KeyError`.

### 9.5 `config_object` — real `Config` is cheap

`Config()` (`PiFinder.config`) reads `default_config.json` plus the
user's `~/PiFinder_data/config.json`. Cheap; just instantiate it. It's
required for `equipment.*` and `filter.*` reads and for
`get_option(...)` calls in `screen_update`/animations.

### 9.6 `catalogs` — real `Catalogs` via `CatalogBuilder`, or empty

Two options:

- **Empty:** `Catalogs([])` (as `main.py:363` does for the boot console)
  — fine for modules that don't read catalog content (most menus, entry
  screens, chart, status). Note `UITextMenu`/object screens will show
  nothing.
- **Real:** `CatalogBuilder().build(shared_state, ui_queue)`
  (`main.py:514`; see the Catalog deep-dive). This reads the bundled
  `astro_data/pifinder_objects.db` (tracked) and is needed by
  `UIObjectList`/`UIObjectDetails`/`UITextEntry` search. It also wants a
  `CatalogFilter` installed (`main.py:517`) for filtering to work.

### 9.7 `item_definition` — the menu-item dict

Pass the node from `menu_structure` (or a hand-built dict). This is how a
module is configured — see §2.1. For object screens you must include the
runtime keys (`object`, `object_list`) that the static tree doesn't
carry. `UITextMenu` requires `items` and `select` to be present
(`text_menu.py:29`–`:30`), or its constructor raises `KeyError`.

### 9.8 `add_to_stack` / `remove_from_stack` / `jump_to_label` — optional callbacks

These default to `None` (`base.py:124`). A module only needs them if you
drive navigation key paths that push/pop the stack (e.g.
`UITextMenu.key_right` calls `self.add_to_stack(...)`). For exercising
in-screen keys you can leave them `None` or pass lambdas/mocks; to
exercise navigation, reuse a real `MenuManager`'s bound methods.

### 9.9 Putting it together

The lowest-friction harness reuses the real `MenuManager`: build the
headless display, a direct `SharedStateObj` + `UIState`, a `Config`, a
`Catalogs` (empty or built), the queue dict and a `camera_image`, then
construct `MenuManager(display, camera_image, shared_state,
command_queues, cfg, catalogs)`. The manager's `add_to_stack`/`update`
then exercise modules with correctly-wired callbacks. To touch a single
module in isolation, call its `class` directly with the same arguments
plus the chosen `item_definition`. The two hard constraints to remember
are: **install a `UIState`** before constructing any module, and
**provide `hip_main.dat`** (or stub `plot.Starfield`) before touching
`UIChart`/`UIAlign`.

---

## 10. Glossary

The canonical glossary lives at [`ui/CONTEXT.md`](./ui/CONTEXT.md). Use
those terms when reading, writing, and discussing code in this area.
