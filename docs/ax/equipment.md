# Equipment in PiFinder

This document describes how PiFinder models the user's optical gear —
their telescopes and eyepieces — and how the **active** telescope and
eyepiece feed the rest of the system: magnification, true field of view,
and the orientation of the object-detail survey image. It focuses on:

- `PiFinder/equipment.py` — the `Telescope`, `Eyepiece`, and `Equipment`
  dataclasses, active-selection state, optical calculations, and the
  `active_telescope_image_orientation()` helper.
- `PiFinder/config.py` — how the `equipment` section is loaded, validated,
  and persisted.
- `PiFinder/cat_images.py` — where flip/flop and the baseline rotation are
  actually applied to the object image.

For the canonical glossary of terms (telescope, active telescope, flip,
flop, parity, baseline rotation, TFOV/AFOV), see
[`equipment/CONTEXT.md`](./equipment/CONTEXT.md). The object-image
orientation decision is recorded in
[`../adr/0003-object-image-orientation.md`](../adr/0003-object-image-orientation.md).

---

## 1. Overview and ownership

The Equipment context owns three things:

1. **The records** — the list of configured telescopes and the list of
   configured eyepieces.
2. **The active selection** — which one telescope and which one eyepiece
   are currently in use (each may be `None`).
3. **The derived optics** — magnification and true field of view, computed
   on demand from the active telescope + active eyepiece, plus the
   flip/flop flags that orient the object image.

There is exactly one `Equipment` instance per config, reached at runtime
as `config_object.equipment`. It is constructed by `Config` at load time
(`config.py`) and persisted back under the `equipment` key. Equipment does
**not** own the object image itself (that belongs to Catalog) nor the
solve **roll** it consumes (that belongs to Positioning); it only supplies
the orientation and scale inputs the object-detail screen needs.

---

## 2. Data model

All three records are dataclasses in `PiFinder/equipment.py`. Only
`Equipment` is `@dataclass_json`, which gives it `from_dict` / `to_dict`
for round-tripping through `config.json`; the nested `Telescope` /
`Eyepiece` lists serialise through it.

### 2.1 `Telescope` (`equipment.py:19`)

| Field | Type | Meaning |
| --- | --- | --- |
| `make` | str | Manufacturer, free text. |
| `name` | str | Model / instrument name. |
| `aperture_mm` | int | Clear aperture in mm. |
| `focal_length_mm` | int | Focal length in mm. Numerator of `calc_magnification()`. |
| `obstruction_perc` | float | Central obstruction as a percentage (0 for a refractor). Informational; not used by the optics calcs here. |
| `mount_type` | str | `"alt/az"` or `"equatorial"`. |
| `flip_image` | bool | Top-to-bottom (vertical) mirror of the object image. See §6. |
| `flop_image` | bool | Left-to-right (horizontal) mirror of the object image. See §6. |
| `reverse_arrow_a` | bool | Inverts one push-to chart arrow axis. Orients *arrows*, never the *image*. |
| `reverse_arrow_b` | bool | Inverts the other push-to chart arrow axis. |

`flip`/`flop` and `reverse_arrow_*` are independent concerns — see §6 and
the glossary's "Flagged ambiguities."

### 2.2 `Eyepiece` (`equipment.py:7`)

| Field | Type | Meaning |
| --- | --- | --- |
| `make` | str | Manufacturer, free text. |
| `name` | str | Model name. |
| `focal_length_mm` | float | Focal length in mm. Denominator of `calc_magnification()`; also the eyepiece sort key. |
| `afov` | int | Apparent field of view (AFOV) in degrees — a property of the eyepiece alone. |
| `field_stop` | float | Field-stop diameter in mm; default `0`. When non-zero it gives a more accurate TFOV (see §5). |

`Eyepiece.__str__` renders as `"{focal_length_mm}mm {name}"`, which is the
string the object-detail screen burns into the image as the eyepiece label.

### 2.3 `Equipment` (`equipment.py:33`)

| Field | Type | Meaning |
| --- | --- | --- |
| `telescopes` | `list[Telescope]` | All configured telescopes, in insertion order. |
| `eyepieces` | `list[Eyepiece]` | All configured eyepieces, **kept sorted by `focal_length_mm`** (see §2.4). |
| `active_telescope_index` | int | Index into `telescopes`; default `-1`. |
| `active_eyepiece_index` | int | Index into `eyepieces`; default `-1`. |

### 2.4 Eyepiece sorting

`__post_init__` calls `sort_eyepieces()`, and every mutator
(`add_eyepiece`, `remove_eyepiece`, `update_eyepiece`) re-sorts. Sorting is
by `focal_length_mm` ascending. Because the active eyepiece is stored as an
*index*, a naïve sort would silently re-point it at a different eyepiece;
`sort_eyepieces()` avoids this by capturing the active `Eyepiece` object
before the sort and re-deriving its index afterward (resetting to `-1` if
it can no longer be found). Telescopes are **not** sorted — their indices
are stable in insertion order.

---

## 3. Config persistence and lifecycle

This is the area most likely to surprise: the shipped equipment defaults
are **not** written into a user's config until something triggers a save.

### 3.1 Load (`config.py:48`)

`Config.load_config()` reads `~/PiFinder_data/config.json` (if present) and
always reads the repo-root `default_config.json` into
`self._default_config_dict`. It then builds `self.equipment`:

- `eq_config = self.get_option("equipment")`. For the `equipment` key this
  falls through to the **default** lookup path
  (`_config_dict.get(option, _default_config_dict.get(option))`), so a user
  who has never saved equipment gets the shipped template
  (Generic Dobsonian + three Plössls) every boot.
- If the resolved `eq_config` is `None` (no defaults either — "something is
  very wrong"), Equipment is built empty: `Equipment(telescopes=[], eyepieces=[])`.
- Otherwise the section is validated (§3.3) and
  `Equipment.from_dict(eq_config)` builds the object.

### 3.2 When a save is actually triggered — the freeze nuance

`save_equipment()` (`config.py:88`) is the *only* writer of the `equipment`
key; it serialises `self.equipment.to_dict()` and calls `set_option`, which
ultimately `dump_config()`s the whole `_config_dict` to disk.

Critically, **`save_equipment()` runs only on an explicit equipment
action**:

- Selecting an active telescope or eyepiece — `set_option("equipment.active_telescope", ...)`
  / `set_option("equipment.active_eyepiece", ...)` (`config.py:110`) — which
  updates the active index *and* calls `save_equipment()`.
- Add / edit / delete of a telescope or eyepiece via the web UI, each of
  which calls `cfg.save_equipment()` explicitly (`server.py`).

Until one of those happens, the `equipment` key is **absent** from the
user's `config.json`, and PiFinder re-reads the default template at every
boot. The moment any of the above fires, the *entire current* equipment
state — defaults included — is **frozen** into the user's config and the
default template stops being consulted for equipment.

This freeze is the mechanism behind the historical bad-default gotcha in
§8: a user who selected an active telescope while the shipped default still
carried `flop_image = true` froze that wrong value into their config, where
fixing `default_config.json` alone can no longer reach it.

### 3.3 Active-index validation (`config.py:61`)

Before constructing the dataclass, `load_config` repairs a few states:

- Empty `telescopes` / `eyepieces` lists are replaced with the default
  template's lists (so an empty config never yields zero gear).
- If `active_telescope_index` is `>= len(telescopes)` it is reset to `0`;
  same for `active_eyepiece_index` vs `eyepieces`. This guards against a
  stored index that points past a now-shorter list. Note this only catches
  *over*-range indices; an explicit `-1` ("nothing selected") is preserved.

---

## 4. Active selection

`active_telescope` / `active_eyepiece` (`equipment.py:47`/`54`) are
properties that index into the lists and **return `None`** on `IndexError`
or `TypeError`. `None` is the canonical "nothing selected" value and every
consumer is expected to handle it (the optics calcs return `-1`, the
orientation helper returns `(False, False)`, the on-device UI prints
"No telescope selected").

Selection happens through two front-ends, both of which converge on the
same `set_active_*` / save path:

### 4.1 On-device menu

`UIEquipment` (`ui/equipment.py`) is the Equipment status screen. It shows
the active telescope name, the active eyepiece, and — when both are set —
the computed magnification and TFOV, then offers two sub-items
("Telescope...", "Eyepiece..."). Selecting either jumps to a dynamically
built `UITextMenu`.

Those text menus are assembled by `dyn_menu_equipment(cfg)`
(`ui/menu_manager.py:60`), called once from `MenuManager.__init__`
(`menu_manager.py:144`). It finds the `equipment` menu node and populates it
with one item per telescope and one per eyepiece, tagging the menus with
`config_option` `"equipment.active_telescope"` / `"equipment.active_eyepiece"`.
When the user picks an item, the menu framework calls
`set_option("equipment.active_telescope", <Telescope>)`, which routes
through `Equipment.set_active_telescope()` (storing the index via
`self.telescopes.index(telescope)`) and saves. Because the menu is built
once at startup, telescopes/eyepieces added later in the same session are
not reflected until the next boot.

`cycle_eyepieces(direction)` (`equipment.py:100`) provides wrap-around
stepping through eyepieces (e.g. from a marking-menu/shortcut), advancing or
retreating the active index and clamping by wrapping to the other end.

### 4.2 Web UI

`/equipment/set_active_instrument/<id>` and
`/equipment/set_active_eyepiece/<id>` (`server.py:576`/`593`) call
`set_active_telescope` / `set_active_eyepiece` with the list element at that
index, then `cfg.save_equipment()`. See §7.

---

## 5. Optical calculations

Both calcs live on `Equipment` and default to the active selections when no
explicit telescope/eyepiece is passed; both return `-1` when either is
`None`.

### 5.1 Magnification (`calc_magnification`, `equipment.py:110`)

```
magnification = telescope.focal_length_mm / eyepiece.focal_length_mm
```

### 5.2 True field of view (`calc_tfov`, `equipment.py:132`)

TFOV uses the field-stop formula when available, else falls back to AFOV /
magnification:

```
if eyepiece.field_stop == 0:
    tfov = eyepiece.afov / magnification          # AFOV / magnification
else:
    tfov = eyepiece.field_stop / telescope.focal_length_mm * 57.2958   # degrees
```

(`57.2958` is `180/π`, converting the field-stop ratio to degrees.)

### 5.3 Where the optics are consumed

`ui/object_details.py` (around line 311) is the principal consumer. Each
time it builds the object image it reads:

- `magnification = config_object.equipment.calc_magnification()`
- `config_object.equipment.calc_tfov()` as the `fov` argument

and passes them into `cat_images.get_display_image(...)`. TFOV drives the
crop/scale: `get_display_image` computes `fov_size = int(1024 * fov / 2)`
and crops the source survey image to that box before resizing to the
display. Magnification and the eyepiece string (`str(active_eyepiece)`) are
burned into the image as overlay text. The same magnification/TFOV are
shown numerically on the `UIEquipment` status screen.

---

## 6. Object-image orientation

This is where the active telescope's flip/flop flags become live. The
whole transform happens in `cat_images._orient_image()` (`cat_images.py:22`),
called by `get_display_image()` (`cat_images.py:86`).

### 6.1 The transform

```python
image_rotate = 180
if roll is not None:
    image_rotate += roll
return_image = return_image.rotate(image_rotate)          # baseline rotation

if flip_image:
    return_image = return_image.transpose(Image.FLIP_TOP_BOTTOM)   # flip
if flop_image:
    return_image = return_image.transpose(Image.FLIP_LEFT_RIGHT)   # flop
```

- **Baseline rotation** — a fixed `180°` combined with the live solve
  **roll** (owned by Positioning). On its own this is correct for the
  common non-mirrored view (Newtonian / straight refractor: even parity).
- **flip** then **flop** are applied **after** the rotation, each as a
  single-axis mirror (`flip` = top-to-bottom, `flop` = left-to-right).
  Mirroring *after* the rotation is the physically correct order: a mirror
  reverses the apparent sense of roll, exactly as a real star-diagonal
  eyepiece does. Applying them before the rotation would leave mirrored
  telescopes rotating the wrong way during live solves. Full rationale and
  the rejected alternatives are in
  [ADR 0003](../adr/0003-object-image-orientation.md).

The **parity model** governs which flags to set: count reflections, not
refractor-vs-reflector. Even reflections (Newtonian, straight refractor) →
rotated, non-mirrored → both flags off. Odd reflections (anything with a
star diagonal) → mirrored → exactly one flag set; which one depends on how
the diagonal is clocked.

### 6.2 The data path

```
active telescope (Telescope.flip_image / .flop_image)
   └─ Equipment.active_telescope_image_orientation()  → (flip, flop)
        └─ ui/object_details.py (~L311)  reads (flip, flop) + roll + magnification + TFOV
             └─ cat_images.get_display_image(..., flip_image=, flop_image=)
                  └─ cat_images._orient_image(image, roll, flip, flop)
```

`active_telescope_image_orientation()` (`equipment.py:61`) returns
`(telescope.flip_image, telescope.flop_image)` for the active telescope and
**`(False, False)` when no telescope is active** — so with nothing selected
the object image gets only the baseline rotation, unchanged from legacy
behavior.

### 6.3 Explicit non-scope

Flip/flop are applied **only** to the object-detail survey image. They do
**not** affect:

- the **live camera preview** (oriented by the physical optics, owned by
  the camera/preview UI), and
- the push-to chart arrows — `reverse_arrow_a` / `reverse_arrow_b` are a
  separate, independent concern that orients *arrows*, never the *image*.

---

## 7. Web UI / CRUD and DeepskyLog import

The web server (`server.py`) provides full CRUD over telescopes
("instruments") and eyepieces, rendered by `views/equipment.html` (the
list/table page) and `views/edit_instrument.html` / `views/edit_eyepiece.html`
(the forms). All routes are auth-protected.

| Route | Action |
| --- | --- |
| `GET /equipment` | List telescopes + eyepieces, show active radios, import button. |
| `GET /equipment/set_active_instrument/<id>` | Set active telescope, save. |
| `GET /equipment/set_active_eyepiece/<id>` | Set active eyepiece, save. |
| `GET /equipment/edit_instrument/<id>` | Edit form (id `< 0` = add new, blank `Telescope`). |
| `POST /equipment/add_instrument/<id>` | Create or update a telescope, save. |
| `GET /equipment/delete_instrument/<id>` | Remove a telescope, save. |
| `GET /equipment/edit_eyepiece/<id>` | Edit form (id `< 0` = add new). |
| `POST /equipment/add_eyepiece/<id>` | Create or update an eyepiece, save. |
| `GET /equipment/delete_eyepiece/<id>` | Remove an eyepiece, save. |
| `POST /equipment/import_from_deepskylog` | Bulk import from DeepskyLog (see below). |

The instrument form (`edit_instrument.html`) exposes the orientation flags
directly as checkboxes — labelled "Flip image (upside down)" and
"Flop image (left right)" — plus "Reverse Arrow A/B". The POST handler
(`server.py:788`) reads them as `bool(request.form.get("flip"))` /
`bool(request.form.get("flop"))` and the matching arrow fields. The list
table (`equipment.html`) shows the `Flip` / `Flop` / `Reverse Arrow A/B`
boolean columns per instrument.

Note the routes operate on a freshly constructed `config.Config()` per
request and `save_equipment()` immediately, so edits land in the persisted
config right away — but the on-device menus (built once at startup, §4.1)
won't show added gear until the next reboot; the add handlers surface a
"restart your PiFinder to use" message accordingly.

### 7.1 DeepskyLog import (`server.py:610`)

`POST /equipment/import_from_deepskylog` takes a DeepskyLog username, then
uses the `pydeepskylog` client to pull that user's instruments and
eyepieces:

- For each instrument (skipping the naked-eye `type == 0`), it builds a
  `Telescope` mapping DeepskyLog fields (diameter → `aperture_mm`,
  `diameter * fd` → `focal_length_mm`, mount-type name, and crucially
  `flip_image` / `flop_image` straight from DeepskyLog). `reverse_arrow_*`
  default to `False`. HTML entities in names are unescaped.
- Eyepieces map `focalLength`, `apparentFOV` → `afov`, and `field_stop_mm`.
- Each new record is appended only if not already present (dedup via
  `list.index(...)` raising `ValueError`), then `save_equipment()`.

The list page's import modal warns the operation may replace existing gear;
in the current handler new items are appended/deduped rather than wiped.

---

## 8. Gotchas

- **The historical bad `flop_image = true` Dobsonian default.** Early builds
  shipped a "Generic Dobsonian" with `flop_image = true`, which is wrong —
  a Newtonian is even parity and needs neither flag. `default_config.json`
  is now corrected (the shipped Dobsonian has `flip_image: false`,
  `flop_image: false`). But because the default template is *frozen* into a
  user's config the first time they select active gear (§3.2), fixing the
  default alone cannot repair already-persisted configs; per ADR 0003 those
  are repaired by a post-update migration via `pifinder_post_update.sh`. That
  repair ships as `migration_source/v2.6.0.sh` (version-gated by the
  `…/migrations/v2.6.0` marker), which invokes
  `PiFinder/migrations/v2_6_0_dob_flop.py` to clear `flop_image` on any
  persisted copy of the bad default. The match is a conservative
  full-signature one (`make`/`name`/`aperture_mm`/`focal_length_mm`/`mount_type`
  plus `flip==false && flop==true`), so it only touches the untouched shipped
  default and is idempotent. If a Dob's object image still looks mirrored —
  e.g. the user customized the record enough that it no longer matches the
  signature — clearing `flop` on that telescope fixes it.

- **flip vs flop axis confusion.** flip = **top-to-bottom** (vertical)
  mirror (`Image.FLIP_TOP_BOTTOM`); flop = **left-to-right** (horizontal)
  mirror (`Image.FLIP_LEFT_RIGHT`). Never say "mirror" or "flip" without
  naming the axis. The web form labels ("upside down" / "left right") match
  this.

- **flip/flop are not arrow reversal.** They orient the *object image*;
  `reverse_arrow_*` orient the push-to *chart arrows*. Different concerns —
  don't conflate them when reading or editing the `Telescope` fields.

- **"Scope" terminology.** Avoid "scope" entirely (ADR 0001 / glossary):
  say **telescope** for the instrument and **active telescope** for the
  selected one. Note the web layer and DeepskyLog code use "instrument" for
  the same record (`Telescope`); treat it as a UI synonym, not a new term.

---

## 9. Glossary

The canonical glossary lives at [`equipment/CONTEXT.md`](./equipment/CONTEXT.md).
Use those terms when reading, writing, and discussing code in this area —
in particular **telescope** (never "scope"), **active telescope**, **flip**
(top-to-bottom mirror) vs **flop** (left-to-right mirror), **parity**,
**baseline rotation**, and **TFOV** vs **AFOV**.
