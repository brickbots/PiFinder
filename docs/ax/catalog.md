# The catalog system

This document describes how PiFinder loads, organizes, filters, searches,
and updates astronomical catalogs at runtime. The bulk of the system
lives in `PiFinder/catalogs.py`, with supporting types in
`PiFinder/catalog_base.py`, `PiFinder/composite_object.py` and
`PiFinder/object_sequence.py`. The on-disk layers are the SQLite DB
(`PiFinder/db/objects_db.py`) and the catalog arrays made from it
(`PiFinder/catalog_arrays.py`).

For the canonical glossary of terms and data structures, see
[`catalog/CONTEXT.md`](./catalog/CONTEXT.md).

---

## 1. The big picture

At a high level:

```
   SQLite (astro_data/pifinder_objects.db)
        │
        ▼
   catalog_arrays.build()        (in CI: nixos/pkgs/catalog-arrays.nix;
        │                          else on first start, into the cache dir)
        ▼
   catalog arrays: one directory per DB catalog
        │   numpy columns (.npy) + UTF-8 text blobs + meta.json
        ▼
   CatalogBuilder.build()
        │
        ├── DB catalogs:  ArrayCatalog per directory (memory-mapped columns,
        │                  logged array from the observations DB)
        │
        ├── dynamic catalogs:  PlanetCatalog (TimerMixin, every ~5 min)
        │                       CometCatalog (similar)
        │
        └─► Catalogs object (single instance shared across the app)
                 │
                 ├── CatalogFilter (one shared instance set on every catalog)
                 ├── T9 / text search over the text blobs
                 └── Lists of objects are ObjectSequences: (source, row)
                     per position, a CompositeObject only on read
```

The `Catalogs` instance is the runtime API for the rest of PiFinder
(menus, charting, web). The integrator/solver layer doesn't touch
catalogs directly — they live in the main UI process.

The DB catalogs hold about 151,000 catalog listings. The UI process
keeps no Python object per listing. It makes a `CompositeObject` only
for a row that code reads, for example a row on screen. See
[ADR 0043](../adr/0043-catalogs-as-numpy-columns-built-in-ci.md) and
step 2 of [`ui-performance-plan.md`](../../ui-performance-plan.md).

---

## 2. The data model

### 2.1 `CompositeObject`

`composite_object.CompositeObject` is the unit of everything the UI
displays. It's a dataclass that merges three things:

- A row from the SQLite `catalog_objects` table — `id`, `catalog_code`,
  `sequence`, `description`.
- The corresponding row from the `objects` table referenced by
  `object_id` — `ra`, `dec`, `obj_type`, `const`, `size`,
  `surface_brightness`, raw `mag` JSON.
- Derived/auxiliary data — `names` (list of strings), `mag`
  (`MagnitudeObject`), `mag_str` (display string), `logged` (derived
  from the observations DB per sky object: any log entry under any of
  the object's listings counts, keyed by `object_id`; virtual objects
  key on their own listing — see ADR 0025),
  `last_filtered_time`/`last_filtered_result` (the last filter verdict;
  object details dims the designator of an object that the filter
  rejects).

For a DB listing, `ArrayCatalog.row(i)` makes the object from the
catalog arrays (§2.5). For planets, comets and observing-list objects,
the catalog makes the object once and holds it.

Two `CompositeObject`s are equal iff their `object_id`s match. That
means the same underlying object referenced by multiple catalogs (e.g.
M 31 ≡ NGC 224) will hash identically; this matters for set membership
but **not** for catalog iteration, which uses lists keyed by
`(catalog_code, sequence)`. Two reads of the same array row can give
two different Python objects (§2.5), so code compares objects with
`==`, never with `is`.

`display_name` returns the first name for planets (`PL`) and
coordinate objects (`OBS`), otherwise `"<catalog_code> <sequence>"`,
e.g. `"NGC 7000"`.

### 2.2 `MagnitudeObject`

Every `CompositeObject.mag` is a `MagnitudeObject` wrapping a list of
magnitudes (visual, photographic, combined-pair for doubles, etc.).

- `filter_mag` — single float used by the filter. Computed as the mean
  of all entries that parse as floats; defaults to
  `UNKNOWN_MAG = 99` when nothing parses.
- `calc_two_mag_representation()` — returns `"-"` if unknown, `"X.X"` if
  one value, `"min/max"` for two-or-more, used as `mag_str` for display.
- Serialised to/from JSON in the DB via `to_json` / `from_json`.

The array builder uses the same `filter_mag` rule, by import, to fill
the `filter_mag` column.

### 2.3 Catalog arrays

`catalog_arrays.py` turns the objects DB into one directory per DB
catalog. Each directory holds one value per catalog listing, with rows
sorted by sequence:

| File | Type | Content |
| --- | --- | --- |
| `id.npy`, `object_id.npy`, `sequence.npy` | int32 | Listing id, sky object id, sequence. |
| `ra.npy`, `dec.npy`, `filter_mag.npy` | float64 | Position and filter magnitude. |
| `obj_type.npy`, `const.npy` | uint8 | Codes into the tables in `meta.json`. |
| `<field>.bin` + `<field>.off.npy` | UTF-8 blob + int64 offsets | Text fields (below). |

The text fields are `names` (a listing's names joined by `NAME_SEP`,
`"\x1f"`), `description`, `mag` and `size` (the DB's JSON text), `t9`
(the keypad digits of each name) and `lower` (the lower-case names).
The offset column has one more entry than there are rows. The text of
row `i` is the bytes from `off[i]` to `off[i + 1]`. In `t9` and `lower`,
each name ends with `NAME_SEP`, so a search match never spans two
names.

`meta.json` holds `FORMAT_VERSION`, the size and modification time of
the DB, the `obj_type` and `const` code tables, and the catalog table
(code, description, max sequence, row count).

`CatalogColumns` opens one catalog. It loads each column with
`np.load(mmap_mode="r")` and each blob with `np.memmap`. The pages come
from the file cache, so they do not add to the private RAM of the
process. `text(field, row)`, `names(row)` and `search(field, pattern)`
read the blobs.

The keypad maps also live in this module: `KEYPAD_DIGIT_TO_CHARS`,
`LETTER_TO_DIGIT_MAP` and `name_to_t9_digits()`.

### 2.4 `CatalogBase` and `Catalog`

`catalog_base.CatalogBase` holds an internal `__objects: List` plus two
position indices: `id_to_pos` and `sequence_to_pos`. Adding objects
appends, then re-sorts (by `sequence` by default), then rebuilds the
indices. `check_sequences()` asserts that no two objects in the catalog
share a sequence number — that invariant is checked on every
`add_object`/`add_objects` call.

`catalogs.Catalog` extends `CatalogBase` with:

- `catalog_filter` — pointer to the shared `CatalogFilter`.
- `filtered_objects` / `filtered_objects_seq` — the post-filter views.
- `as_sequence(filtered)` — the objects as an `ObjectSequence`.
- `get_status()` returning a `CatalogStatus(current, previous, data)`.
- `is_selected()` — whether this catalog appears in
  `catalog_filter.selected_catalogs`.

External code is expected to read through `get_objects()` (returns a
`ROArrayWrapper` — a read-only proxy that disallows assignment) or
`get_filtered_objects()`.

Planets, comets, and the in-memory objects of observing lists use a
plain `Catalog`. These objects change at runtime, so they cannot live
in read-only files.

### 2.5 `ArrayCatalog`

`catalogs.ArrayCatalog` is the `Catalog` subclass for each catalog in
the objects DB (21 catalogs today, M, NGC, IC, WDS and others). It
holds a `CatalogColumns` and keeps no `CompositeObject` per listing.

- `row(i)` makes the `CompositeObject` for row `i` from the columns and
  the runtime state. An LRU cache keeps the last `ROW_CACHE_SIZE = 5000`
  objects, so a row on screen stays the same object from frame to
  frame.
- `column(name)` gives a numpy array per field (see §2.6).
- `get_objects()` and `get_filtered_objects()` return `ObjectSequence`s.
- `get_object_by_sequence()` uses `searchsorted` on the sequence
  column. `get_object_by_id()` searches the `id` column.
- `add_object`, `add_objects` and `clear_objects` raise `TypeError`: the
  catalog is read-only.

The runtime state per listing lives next to the read-only columns:

- `logged` — a writable bool array, one value per row (§3).
- `verdict` — the filter result, a bool array (§4.1).
- the observing list descriptions — a dict by sequence. Every object
  made for a row gets the same dict, so the descriptions stay when the
  row cache drops the object.

### 2.6 `ObjectSequence`

`object_sequence.ObjectSequence` is a read-only list of
`CompositeObject`s over one or more sources. A source is an
`ArrayCatalog`, or a `ListSource` over a list of plain objects
(planets, comets, observing lists, search results of the list
catalogs). For each position the sequence stores only the source and
the row. It makes an object only for `seq[i]` or iteration.

- List behaviour for reading: `len`, `seq[i]`, `seq[a:b]`, iteration,
  `in`, and `==` against another sequence or a list.
- `index(obj)` gives the first position with the same `object_id`, as
  `list.index` does with `CompositeObject.__eq__`.
- `column(name)` gives the values for every position, in sequence
  order. The names are `ra`, `dec`, `filter_mag`, `object_id`,
  `sequence`, `obj_type`, `const`, `logged`, `catalog_code` and
  `listing_key`. `listing_key` is one int64 per catalog listing, made
  from the catalog code and the sequence. Equal keys mean the same
  listing, not only the same sky object.
- `take(positions)`, `mask(keep)` and `concat(parts)` give new
  sequences. They make no objects.
- `ObjectSequence.of(items)` wraps a list, or returns a sequence as it
  is.

Filtering, sorting, the nearby ranking and search work on columns and
give a new sequence. A list of 150,000 listings never becomes 150,000
Python objects.

### 2.7 `Catalogs`

A container that holds a `List[Catalog]` plus the singleton
`CatalogFilter`. It exposes:

- `filter_catalogs(catalogs=None)` — runs `filter_objects()` on the
  given catalogs, or on every catalog.
- `set_catalog_filter(filter)` — installs one filter object on every
  catalog so changes propagate uniformly.
- `select_catalogs / select_all / select_no` — manipulate the selected
  set on the shared filter.
- `get_catalogs(only_selected=True)` / `get_codes(...)` — collection
  accessors.
- `get_objects(only_selected=True, filtered=True)` — one
  `ObjectSequence` over the catalogs (`ObjectSequence.concat`).
- `get_catalog_by_code(code)` / `get_object(code, sequence)` — direct
  lookup.
- `mark_logged(obj)` — see §4.1.
- `search_by_text(s)` / `search_by_t9(digits)` — see §5.
- `iter_names()` — `(name, resolve)` for every name of every object, for
  the name index of observing lists (`obslist._build_name_index`).
  `resolve()` makes the object, so only a name that an entry uses makes
  an object.
- `add(catalog)` / `remove(code)` / `set(catalogs)` — mutate the
  collection.
- `__iter__` — yields only selected catalogs.

---

## 3. Building: `CatalogBuilder`

### 3.1 The arrays

The Nix derivation `nixos/pkgs/catalog-arrays.nix` runs
`python -m PiFinder.catalog_arrays build` in CI. Its only inputs are
the objects DB (`astro-data`) and the Python files that the builder
needs. A normal code change does not build the arrays again and adds no
new store path to download. `pifinder-src` links the result into the
source tree as `catalog_arrays`. The arrays use about 44 MB on disk.

`catalog_arrays.locate()` gives the directory to open:

1. The Nix arrays (`<pifinder_dir>/catalog_arrays`), when they match
   the DB.
2. Else the cache directory, `~/PiFinder_data/cache/catalog_arrays`.
   When it is missing or does not match the DB, `locate()` builds it
   first. On a device with Nix arrays that do not match, it also logs
   an error.

Arrays match the DB when `meta.json` has the current `FORMAT_VERSION`
and the size and modification time of the DB. `build()` writes into a
temporary directory and replaces the old directory only when the build
is complete. To build by hand:

```
python -m PiFinder.catalog_arrays build [--db PATH] [--out DIR]
```

### 3.2 `CatalogBuilder.build(shared_state)`

`CatalogBuilder.build(shared_state)` is called once during startup,
from the main process. It:

1. Calls `catalog_arrays.remove_old_pickle_cache()`, which deletes the
   old pickle cache directory (`~/PiFinder_data/cache/catalogs`) if it
   exists.
2. Calls `catalog_arrays.locate()` to find (or build) the arrays.
3. Opens `ObservationsDatabase` and loads its caches of observed object
   ids and observed listings.
4. Makes one `ArrayCatalog` per catalog in `meta.json`. The `logged`
   array of each catalog is
   `np.isin(object_id, observed_object_ids) | np.isin(sequence,
   observed sequences of this catalog)`. This is the same rule as
   `ObservationsDatabase.check_logged`.
5. Makes the `Catalogs` instance and adds two dynamic catalogs:
   `PlanetCatalog` (`PL`) and, via local import, `CometCatalog`.

Every DB catalog is complete when `build()` returns. There is no
background loader thread, and no message on `ui_queue` when loading
ends.

### 3.3 Cost

Opening the arrays takes about 90 ms on a PC. In a headless run on a
PC, the private RAM of the UI process (`RssAnon`) is about 152 MB. In the
same test, one `CompositeObject` per listing gives about 542 MB.

---

## 4. Filtering: `CatalogFilter`

A single `CatalogFilter` is shared across all `Catalog`s via
`Catalogs.set_catalog_filter(...)`. It maintains five filter parameters
plus a selected-catalogs set:

| Property | Type | Meaning |
| --- | --- | --- |
| `magnitude` | `float | None` | Maximum `filter_mag`. `None` disables. |
| `object_types` | `list[str] | None` | Allowed obj_type values (e.g. `["Gal", "Neb"]`). `None` or an empty list disables. |
| `altitude` | `int` | Minimum altitude in degrees. `-1` disables. Requires GPS lock to compute. |
| `observed` | `"Any" | "Yes" | "No"` | Match on `obj.logged`. |
| `constellations` | `list[str]` | Required `const` values. An empty list disables. |
| `selected_catalogs` | `set[str]` | Which catalogs are "on" in the UI. |

`CatalogFilter.verdicts(items)` evaluates the criteria on columns. The
items are a list of objects or an `ObjectSequence`. Each active
criterion is one numpy operation over all items. The altitude test uses
`FastAltAz.radec_to_alt_array` on the `ra` and `dec` columns. An object
without valid coordinates gets a NaN altitude, so it fails the altitude
test. `evaluate(items)` computes the alt/az state first and records
`last_filtered_time`. `apply(items)` returns the items that pass: an
`ObjectSequence` for an `ObjectSequence`, else a list. For a list,
`apply` also records `last_filtered_time` and `last_filtered_result` on
each object.

### 4.1 Dirty tracking

Filtering is the hot path — every menu redraw asks for filtered objects.
The cache is per catalog, keyed against `dirty_time`:

- Every setter calls `mark_dirty()`, bumping `dirty_time = time.time()`.
- `Catalog.filter_objects()` returns its cached `filtered_objects`
  outright while `catalog.last_filtered > dirty_time`. For a plain
  `Catalog`, any object-set mutation (`add_object`, `add_objects`,
  `clear_objects`) resets `last_filtered = 0`.
- When the cache is old, an `ArrayCatalog` evaluates the filter on all
  its rows and stores the result in its `verdict` array.
  `filtered_objects` is an `ObjectSequence` over the rows that pass
  (`np.flatnonzero(verdict)`). The objects in the row cache get the new
  `last_filtered_result`. A plain `Catalog` calls `apply()` on its
  object list.

There is no per-object cache layer: a catalog that filters again
evaluates every object. So if the filter has not changed since the last
sweep, a list open is O(catalogs) cache reads with no real predicate
work.

Two freshness triggers advance `dirty_time` besides the setters
([ADR 0025](../adr/0025-filter-freshness-staleness-promotion.md)):

- **Logging**: `Catalogs.mark_logged(obj)` sets `obj.logged`. For a
  non-negative `object_id` (M 31 / NGC 224), it also marks every
  listing of the sky object: `ArrayCatalog.set_logged(object_id)` sets
  the `logged` array with one array operation per catalog, and plain
  catalogs mark their sibling objects. It marks dirty when an observed
  criterion is active, so "Observed: No" lists drop the object on their
  next refresh. The refresh keeps the cursor on the selected object, or
  moves it to the old successor when the selection itself dropped out
  (`_next_target_index`, on the `listing_key` columns).
- **Staleness promotion**: with an altitude criterion active, verdicts
  age out as the sky rotates. `CatalogFilter.is_stale()` reports it
  (TTL `ALTITUDE_STALE_SECONDS = 600`, or alt/az becoming available —
  see 4.2); `Catalogs.filter_catalogs()` promotes it to a dirty bump,
  and `UIObjectList.update()` polls it so an open list refreshes in
  place.

### 4.2 Altitude requires GPS

`calc_fast_aa(shared_state)` builds a `FastAltAz` from the current
location/datetime, *if* `shared_state.altaz_ready()`. When the alt-az
calculator is missing, altitude is skipped (not rejected). This is why
the altitude filter "stops working" without GPS — the predicate is
simply not evaluated. The filter records whether alt/az was available
at the last sweep (`_last_filtered_altaz_ready`); a fix arriving later
makes `is_stale()` true, so the altitude predicate is applied on the
next refresh instead of everything staying "passed" all session.

### 4.3 Empty lists do not filter

For both `object_types` and `constellations`, an empty list and `None`
have the same effect: the criterion does not filter. `verdicts()` skips
a criterion whose value is empty. So a filter with every type unchecked
in the UI keeps all types. Callers that want "no objects" must not use
an empty list for this.

### 4.4 `load_from_config`

`CatalogFilter.load_from_config(cfg)` pulls the same five parameters
from `Config` under the `filter.*` namespace (`filter.magnitude`,
`filter.object_types`, …, `filter.selected_catalogs`). This is how the
filter is restored on app start.

---

## 5. Search

Both searches ignore the enabled catalogs and the filter. Both return
an `ObjectSequence`, in catalog order. There is no search cache.

### 5.1 Text search

`Catalogs.search_by_text(s)` does a lower-case substring match against
each name of each object.

- An `ArrayCatalog` searches its `lower` blob. `find_all` gives every
  match position in the blob with numpy. `searchsorted` on the offset
  column maps each position to its row. The result holds each row once.
- Planets and comets test the names of each object.

### 5.2 T9 (keypad) search

PiFinder's hardware keypad uses a non-standard digit-to-letter mapping
(`KEYPAD_DIGIT_TO_CHARS` in `catalog_arrays.py` — note `7→abc`,
`1→tuv`, `3→'-+/`, etc.). `name_to_t9_digits(name)` translates a name
with a `str.maketrans` table and drops characters that are not valid
keypad digits. Digits in a name map to themselves.
`Catalogs.search_by_t9(digits)` returns every object with a name whose
digit string contains the search digits:

- An `ArrayCatalog` searches its `t9` blob, in the same way as the
  `lower` blob in §5.1. The build step computes the blob with
  `name_to_t9_digits`.
- Planets and comets translate their names on each search.

---

## 6. Dynamic catalogs

### 6.1 `PlanetCatalog`

A `Catalog` subclass that:

- Uses `TimerMixin` to recompute positions on a background timer.
- Has two delay regimes: `DEFAULT_DELAY = 307` s (have GPS lock) and
  `WAITING_FOR_GPS_DELAY = 10` s (no lock yet). `time_delay_seconds`
  picks based on `self.initialized`.
- Reports state through `get_status()`: `NO_GPS` /
  `CALCULATING` / `READY`, with a previous-state field for transition
  detection by the UI.
- On the first tick with a GPS-locked datetime, calls
  `sf_utils.calc_planets(dt)` and creates a `CompositeObject` per
  planet (skipping the Sun) with `catalog_code="PL"`,
  `obj_type="Pla"`, and a single-name list. `VirtualIDManager`
  assigns each object a negative `object_id` (the DB uses positive
  ids; negative is the convention for in-memory-only objects).
- Subsequent ticks update each existing `CompositeObject` in place —
  new RA/Dec/mag/const — without recreating the catalog.

### 6.2 `CometCatalog`

Imported locally in `CatalogBuilder.build()` to avoid a circular
import. Same general pattern: dynamic, status-aware, registered as a
regular `Catalog` in the `Catalogs` collection.

### 6.3 `TimerMixin`

Provides `start_timer()` / `stop()` plus a `time_delay_seconds` that can
be either an int or a callable. Each fire schedules itself again via
`threading.Timer` and runs `do_timed_task` in a separate thread, so the
catalog method does not run on the timer thread directly — useful
because `do_timed_task` can take a noticeable amount of time
(`sf_utils.calc_planets` is not cheap).

### 6.4 `VirtualIDManager`

Static helper that hands out monotonically decreasing `object_id`
values for non-DB objects. Held under `virtual_id_lock` and persists
the low watermark in `virtual_id_low`. Without this, two dynamic
catalogs might mint identical negative IDs and break the
`CompositeObject.__eq__/__hash__` contract.

---

## 7. Distribution

The catalog system is consumed almost entirely inside the main UI
process. Typical consumer patterns:

- **Menu and chart screens** call `catalogs.get_objects(...)`,
  `catalogs.get_catalog_by_code(...)`, `catalog.get_filtered_objects()`,
  etc.
- **The object list screen** (`ui/object_list.py`) holds its items as
  `ObjectSequence`s (`_menu_items`, `_menu_items_sorted`). The RA sort
  is an `argsort` on the `ra` column. `scroll_to_sequence` searches the
  `sequence` column. Object details (`ui/object_details.py`) finds the
  position of the selected object with `ObjectSequence.index`.
- **Nearby** (`nearby.py`) de-duplicates on columns: one listing per
  sky object, M before NGC before the rest, the earliest listing among
  equal ranks, in order of first appearance. It builds the BallTree
  from the `ra`/`dec` columns. `get_closest_objects` returns an
  `ObjectSequence`, so only the results on screen become objects.
- **CatalogDesignator** (`catalogs.py`, near the bottom) holds the
  formatted input string for catalog-code selection — `"NGC----"`,
  `"M-13"`, etc., respecting a per-catalog width derived from
  `max_sequence`. It exposes `set_number`, `append_number`,
  `increment_number`/`decrement_number`, and `has_number`.
- **The filter UI** mutates `Catalogs.catalog_filter` via its
  properties (which mark it dirty); the next call to
  `Catalog.filter_objects()` re-runs the cached sweep.
- **The web server** uses the same `Catalogs` instance through the
  shared object model, exposing object data through `/api/...` routes.

Objects go to other processes as pickles through `UIState` (recent
list, target, observing list). `row(i)` makes a normal
`CompositeObject`, so these pickles contain the same dataclass for
array rows and for plain objects.

There is no separate "catalog state" published on `shared_state`; the
catalogs live in the main process and are shared with other processes
only via the lower-level DB queries (`ObservationsDatabase` write-back
of logged status, for example).

---

## 8. Lifecycle summary

1. CI builds the catalog arrays. Without them, the first start builds
   them into the cache directory.
2. `CatalogBuilder.build()` opens the arrays as `ArrayCatalog`s,
   computes their `logged` arrays, and attaches `PlanetCatalog` and
   `CometCatalog`.
3. `CatalogFilter` is constructed and hooked in via
   `set_catalog_filter`. `load_from_config(cfg)` restores user
   preferences.
4. Each UI refresh that needs filtered objects calls
   `catalog.filter_objects()` — cheap thanks to the dirty-time cache.
5. Screens read rows through `ObjectSequence`s. Only the rows that code
   reads become `CompositeObject`s.
6. Periodic timers update `PlanetCatalog` / `CometCatalog` positions.
7. On shutdown, `TimerMixin.stop()` calls cancel the timer threads.

---

## 9. Glossary

The canonical glossary lives at [`catalog/CONTEXT.md`](./catalog/CONTEXT.md).
Use those terms when reading, writing, and discussing code in this area.
