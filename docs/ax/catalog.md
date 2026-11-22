# The catalog system

This document describes how PiFinder loads, organizes, filters, searches,
and updates astronomical catalogs at runtime. The bulk of the system
lives in `PiFinder/catalogs.py`, with supporting types in
`PiFinder/catalog_base.py`, `PiFinder/composite_object.py` and
`PiFinder/object_sequence.py`. The on-disk layers are the SQLite DB
(`PiFinder/db/objects_db.py`) and the catalog arrays made from it
(`PiFinder/catalog_arrays.py`). Section 9 covers the offline **catalog
import** in `PiFinder/catalog_imports/`, which builds that SQLite file
from the sources in `astro_data/`.

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

- `filter_mag` — single float used by the filter. The brightest (the
  smallest) of the entries that parse as floats, so a double filters by
  its primary and a variable by its maximum (Rich's choice, 2026-11; a
  mean hid SAC's Vega, [0.6, 9.5], behind a 5.05 filter magnitude);
  defaults to `UNKNOWN_MAG = 99` when nothing parses. `from_json`
  recomputes it from the magnitudes and ignores the stored value, so a
  database built under the old rule filters by the new one.
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

## 9. Building the database: the catalog import

`astro_data/pifinder_objects.db` is a build artifact. `main()` in
`catalog_imports/main.py` drops every table and rebuilds the file from
the **sources** in `astro_data/`. The import runs on a developer's
machine; a device never runs it, and ships the committed file instead.

To rebuild it, initialise the solver submodule and its symlink once per
checkout (see `CLAUDE.md`), then, from `python/` with the Python 3.9
virtualenv active:

```bash
python -m PiFinder.catalog_imports.main
```

It takes no arguments (`-x` logs at debug level, `-l` also logs to a
file in the working directory) and writes `astro_data/pifinder_objects.db`
in place, wherever it is run from. The build takes under a minute and is
reproducible: two builds with different `PYTHONHASHSEED` values are
byte-identical, as long as both start from the same file. The import
drops and recreates the tables inside the existing file, so SQLite's
header counters carry on from whatever was there, and a second build on
top of the first differs from it in those bytes alone. To try a change
without committing the data (9.7), copy the result out and restore the
tracked file with `git checkout -- astro_data/pifinder_objects.db`
before the next build.

The committed database is a build of the import this section describes.
The designation allowlist, the match guard (9.3) and precedence (9.1)
are in `catalog_imports/catalog_import_utils.py`, the star cross-match
(9.3) in `catalog_imports/star_identity.py`, the supplementary sources
(9.4) in `catalog_imports/supplementary_sources.py`, and the correction
pass (9.5) in `catalog_imports/corrections.py`. The decision record is
[ADR 0046](../adr/0046-catalog-corrections-cited-checked-applied-last.md).

### 9.1 Pipeline

```
   sources (astro_data/)
        │
        ▼
   loaders, in CATALOG_LOADERS order            (main.py)
        │   each listing: parse its akas → match guard →
        │   join an existing sky object, or mint a new one
        ▼
   post-processing                               (POST_PROCESSING_FUNCTIONS)
        │   type normalisation, the hand-built Messier objects,
        │   the Messier names
        ▼
   star identity: Hipparcos cross-match, merge by HIP   (star_identity.py)
        │   (`hip` corrections apply here, before the identifier rules;
        │   each star's HIP is recorded in STAR_HIPS)
        ▼
   supplementary sources                         (SUPPLEMENTARY_SOURCES)
        │   Hipparcos values → WGSN names → Bica sizes → RC3 magnitudes
        ▼
   correction pass                               (astro_data/corrections/*.toml)
        ▼
   resolve_object_images → finalise (WAL checkpoint, DELETE journal)
```

Each stage has the last word over the stages before it. Loader order
matters: a loader can only join sky objects that earlier loaders created
(so Sharpless loads before Caldwell, whose C 9 is Sh2 155). The Named
Stars loader (`Nam`) loads last: its listings join no sky object at
insert, and the star-identity stage joins each to its star by HIP number,
where the lowest id survives, so a star another catalog lists keeps that
catalog's sky object.

When a loader joins a sky object an earlier loader created, it may only
fill what is empty — never replace — with two named exceptions:

| field | rule |
|---|---|
| magnitude, size | fill if the sky object has none (`filter_mag == 99`, no extents) |
| magnitude, size, from a group listing | **fill nothing**: a listing whose akas resolve to more than one sky object (TAAS's "2237;2244") gives the group's values, not the member's it joins |
| magnitude of a globular | **Harris replaces**: it is the reference for Milky Way globulars, and every Harris listing is one |
| type | the first loader's stands; **EGC sets `Gb`** — a cluster on PiFinder's globular list is a globular |
| position | the first loader's stands (for a star identified by HIP, Hipparcos replaces it later, 9.4) |

`NewCatalogObject.fill_joined_object` applies the table; the exceptions
are `MAGNITUDE_REPLACED_BY` and `TYPE_SET_BY`, keyed by the joining
listing's catalog code, and still apply to a group listing. A new exception belongs in this table and
there, not in a loader's `if`.

Because the first value wins, loader order also decides which source
fills a field that several leave to later loaders. Collinder, Sharpless
and Caldwell all join some NGC objects Steinicke left without a
magnitude or size, and no order of the three gets every value right:

| sky object | Col | Sh2 | C | right (the audit) | needs |
|---|---|---|---|---|---|
| NGC 6885 = C 37, magnitude | 8.1 | — | 5.9 | about 5.9 | C before Col |
| NGC 2467, size | 15′ | 45′ | — | about 8–16′ | Col before Sh2 |
| NGC 1931, size | 4′ | 7′ | — | about 4′ | Col before Sh2 |
| C 9 joins Sh2 155 at all | | | | | Sh2 before C |

The import loads Collinder, then Sharpless, then Caldwell, so C 37's
magnitude is a correction of Collinder's value. Anyone reordering these
loaders moves the rows above.

### 9.2 Where a fix goes

When the database holds a wrong value, the fix goes in exactly one place:

| the cause | the fix |
|---|---|
| a loader misreads its source | fix the loader |
| a published source is wrong, and one better reference covers more than a handful of objects by a stable key | a **supplementary source** (9.4) |
| a published source is wrong for one object, and no rule or reference can produce the value | a **correction** (9.5) |
| a **curated source** (EGC, `bright_stars.csv`, `messier_names.dat`) is wrong or incomplete | edit the file |

A published source is never edited, even to fix it: it stays as its
publisher released it, so an updated release can be dropped in.

### 9.3 Matching

A listing's akas join it to an existing sky object only if both hold:

1. **The aka parses as a designation of a PiFinder catalog.** Prefixes
   are an allowlist (`CATALOG_CODE_ALIASES`, `parse_designation`), so a
   double-star discoverer code — `h 301`, `A 58`, `B 53` — never joins
   Herschel 400, Abell or Barnard. Matching on a whitespace-stripped
   lowercase key is what put ν Aur's names on NGC 4245 (#668). The
   allowlist governs every lookup, spaced or not: `listing_named` is the
   one question `ObjectFinder` and the correction pass's checks ask, so
   "B53" and "h99" name no listing.
2. **The match guard passes** (`match_guard`). The types must be
   compatible, read from the loaders' own type strings before type
   normalisation:
   - a **star** type is `*`, `D*` or `**`, perhaps with a trailing `?`
     (`D*?`);
   - an **unknown** type (`?`, `-`, empty) is compatible with either
     kind, and so is a **star group** (`***`, Steinicke's `*3` and `*4`),
     which cluster catalogs and double-star lists both list: Lyngå's
     open cluster Lyn 921 is M 73, Steinicke's `*4`;
   - every other type (`Gx`, `OC`, `Ast`, `C+N`, "Open Cluster"…) is a
     non-star.

   A star joins only a star, a non-star only a non-star, and either
   joins, or is joined by, an unknown type or a star group. And the
   listing must lie within 30′ of the sky object
   (great-circle distance between the two positions), or within the
   object's major axis if that is larger.

The akas are tried in source order: the first that resolves to a sky
object and passes the guard decides which sky object the listing joins.
A rejected match leaves the listing as a sky object of its own — the
right outcome for a double star whose discoverer code once matched a
galaxy — unless a later aka passes. Each rejection is logged, and the
import ends with a count. Rejections do not fail the import.

**Only akas that resolve to the listing's sky object are stored as its
names.** A designation of a PiFinder catalog that resolves to another
sky object is not a name of this one, so the Double Cluster's "869;884"
leaves NGC 884's number off NGC 869. One that resolves to nothing names
something PiFinder doesn't hold: dropped from a joined sky object (Arp's
NGC 1097A is a companion beside NGC 1097), kept on a sky object the
listing mints (Arp 79 is NGC 5490C). Every other aka — a common name,
another catalog's number (UGC, SIMEIS) — is stored. An aka the sky
object already has is stored again under the new listing's origin; the
device drops repeated names when it loads them.

**Lettered components, for Arp only.** Arp names an interacting pair by
its components ("NGC 4676A", "NGC 4676B"), but also a companion beside
its main galaxy ("NGC 1097A", listed with NGC 1097). The Arp loader opts
in (`lettered_components`) to reading a lettered aka as a designation:
the A component resolves to its number's sky object when the listing
does not also name the number itself, and any other letter resolves to
nothing. PiFinder's NGC 4676 is Steinicke's A row, so Arp 242 joins it;
Arp 79's NGC 5490C, a galaxy of its own 4.8′ from NGC 5490, does not. A
source can mean either by the letter, so every other loader keeps the
strict default, where "NGC 4676A" is a plain name.

**A loader writes its source's designations out before they are akas.**
The allowlist reads "NGC 581", not the "581 (M103)" of `collinder.txt`,
which would stay a plain name and leave Col 14 a second sky object beside
M 103. So the Collinder loader reads its two name columns
(`collinder_names`):

- `collinder.txt`'s "NGC/Other Cat." holds a designation, often with a
  second one in parentheses: "581 (M103)" is "NGC 581" and "M 103",
  "IC4725 (M25)" is "IC 4725" and "M 25", "Tr.9" is "Trumpler 9". A part of
  an NGC object ("2384a") is the name "NGC 2384a", which joins nothing.
- A cross-reference that the source marks wrong ("(incorrectly) 3247")
  gives no aka, so it can never join. Nor does a placeholder ("nl"), the
  Flamsteed numbers of a cluster's stars ("4-5 Vul."), or text in
  parentheses that is not one designation ("(Mel 72 per A/H)").
- `collinder2.txt`'s "Other names" is a comma-separated list, and each
  item is a name: Col 399 is "Al Sufi's Cluster", "Brocchi's Cluster" and
  "Coathanger".

**Stars are identified by Hipparcos number.** The star-identity stage
cross-matches every sky object that carries a listing of a star catalog
(Str, SaM, SaR, TLK, RDS, WDS) to `hip_main.dat`, and merges the sky
objects that match one HIP number into one, whatever catalogs list them:
Mizar is one sky object. **A match is made only where it is reliably
right — by position, or by an exact identifier the listing shares with
Hipparcos or WDS — and a star the rules miss is matched by a `hip`
correction** (Rich's principle, 2026-10). A wrong match cannot be undone
and would give a listing another star's values, while a miss costs one
line in a corrections file. A listing with no match stays its own sky
object.

- **A HIP-numbered listing is its star.** The Named Stars catalog (`Nam`)
  lists each star the IAU Catalog of Star Names gives a HIP number, and its
  sequence is that number (Vega is Nam 91262), so the number stays the
  star's as the WGSN adopts names (`HIP_NUMBERED_CATALOGS`). Such a listing
  is identified by its number alone, with the rule "HIP number": it is not
  cross-matched, takes no part in the rules below, and takes no `hip`
  correction. It changes no other listing's match, and joins whatever the
  rules and corrections identify as its HIP number in the merge. Where they
  miss a star another catalog lists, the Named Stars listing is a sky object
  of its own beside it, until a `hip` correction identifies the missed
  listing; position never joins them. The listing's position and V are
  Hipparcos's: V is the star's own where Hipparcos says so (9.4), and
  otherwise its system's combined light, which is what a finder shows of
  a star listed alone. A star with no other listing keeps that V, and
  without one it would drop out of every magnitude filter.

- **The match** is the one Hipparcos star within the listing's radius
  whose V lies within 1 mag of the listing's first magnitude, the
  primary's; for a variable listed by its range (TLK's [max, min]),
  within 1 mag of the range. No match is made when:
  - no star passes the V gate;
  - two stars pass it (a pair whose components each have a Hipparcos
    entry, such as 61 Oph or ε Equ);
  - the listing gives no V (SAC's continuation rows, such as ν Sco's AC).
    By position alone they found a companion or a neighbour.
  A variable whose catalog V is not Hipparcos's (Mira: SAC 2.0, Hipparcos
  6.47; TLK's photographic ranges) is therefore a `hip` correction.
- **The radius follows the position's precision**: 3′ for SAC, RASC and
  the bright stars, which round to 0.1ᵐ in RA and 1′ in Dec; 3″ for the
  arcsecond positions of WDS and TLK. Within 3″ a WDS listing is its
  Hipparcos star; its Durchmusterung number disagrees only where WDS's
  own column has a slip. A listing whose position stands in for its
  star's is not matched at all:
  - a WDS row without arcsecond coordinates, which its identifier places;
  - a SAC companion pair (BC, CD), which SAC places at its system's
    position (ε Lyr's CD row lies at ε¹).
  SAC's rows 3–6′ from their star were a third chance matches, so they are
  corrections too. Hipparcos's J1991.25 positions are carried to J2000 by
  their proper motion, which moves Arcturus 20″.
- **A match must not contradict the listing's own designations.**
  - Its HD, BD, CD or CPD numbers, if it gives any, must include the
    matched star's in Hipparcos's own columns.
  - A WDS listing's own DM, where it names a Hipparcos star within 15′,
    must name the matched one. Where WDS's position sits on one star of a
    pair and its DM names the other (LDS 5227), which star is the primary
    is not settled: 45 WDS listings go unmatched for it.
  - A double-star designation (SAC's "STF 362", "h 4166" for WDS's
    HJ 4166) that a WDS listing within 15′ carries must not place the pair
    elsewhere: that listing may not match another star, nor lie more than
    0.5′ from the matched one. That is how a SAC row 1–2′ off is kept off
    the wrong star when its own pair is not in Hipparcos.
- **Exact identifiers**, for a listing the position match leaves
  unmatched. A rule never replaces a position match, and two rules that
  name different stars, one that names two, or a veto against the result
  give no match.
  1. **A shared catalog number.** An HD, BD, CD or CPD number in the
     listing's names, or WDS's DM column (which does not say whether it is
     BD, CD or CPD), names the Hipparcos star that has it in its own
     columns. The star must lie within 3′ of a rounded position or 30″ of
     an arcsecond one, since a source's number can be a slip (SAC's TU Gem
     names a star 65° away); for WDS and TLK it must also be the nearest
     Hipparcos star, since a number never overrides an arcsecond position
     (θ¹ Ori's PTR 1 sits on one component while its DM names the other).
     And the listing's V must pass the V gate, as for a position match
     (SAC's red stars BE CMa and BE CMi give a V 1.7 mag brighter than the
     stars their HD numbers name), except for a star Hipparcos finds
     varying by more than 0.6 mag (its H6 flag is 3: Mira) and for a WDS
     listing, whose first magnitude is often another band's (K for an
     interferometric pair). WDS writes a five-digit DM number with no space
     after the zone (`-2616866`); the loader reads both forms.
  2. **A shared WDS designation.** A SAC or RASC row whose double-star
     designation a WDS listing within 15′ carries, and which that WDS
     listing's match identifies, is that star. This settles the pairs whose
     two components each have a Hipparcos entry: WDS's listing sits on its
     primary. A designation names a pair, so the star must pass the row's
     V gate where the row gives a V (θ¹ Ori's CF row is C, not STF 748's
     primary), and a WDS listing whose own DM names its other star vouches
     for nothing.
  3. **SAC's own systems.** SAC lists a multiple star as consecutive rows
     under one constellation and name (AB, then AC, CD…). A continuation
     row that gives no V, or that is a companion pair, joins its system's
     first row's sky object — with that row's HIP, or none — only if it is
     a pair of the first row's primary star: its components start with the
     first row's primary letter (ν Sco's AC after AB). A pair of other
     components (θ¹ Ori's CF, σ Ori's ED, α Cep's CD) is another star of
     the system, and a row or a system without components says nothing, so
     it stays its own sky object; a row that gives a V must also pass the
     V gate against its system's star. No rule identifies a companion pair
     at all: its names and numbers are its system's, and its double-star
     designation's WDS listing sits on the primary, so rules 1 and 2 would
     name the primary too (STF 2532's BC row). It does not join if its own
     identifiers name another star (STF 1830's rows). Joining every
     continuation row put θ¹ Ori's CF row (V 5.1, θ¹ Ori C) on HIP 26224
     (V 6.71) and σ Ori's ED row (V 6.5) on σ Ori A (V 3.77) — mrosseel's
     review of #685.
- **`hip` corrections come before the identifier rules.** A listing the
  rules miss (SAC's α Mic, whole degrees off; Mira's SAC rows; a pair's
  ambiguous components) gets a `hip` correction — the one correction that
  does not wait for the final pass (9.5). It replaces the listing's
  position match after the vetoes, and the identifier rules run after it,
  so they see the corrected stars: a SAC row whose WDS listing a
  correction identifies follows it by rule 2, and a continuation row
  follows a corrected first row by rule 3. (Applied after the rules, a
  correction of a WDS listing left the SAC rows rule 2 had put on its old
  star behind — mrosseel's review.) One whose designator resolves to
  nothing or to no star listing, that names a HIP number Hipparcos lacks,
  that reaches a sky object another correction reaches, or that names the
  star the rules find without any correction (redundant) fails the
  import, before anything is merged. A correction made redundant only by
  another correction (SaM 1105, which rule 2 finds once WDS 58296's
  correction applies) is not caught by the import; the list's
  maintenance tools check it.
- **The merge.** The first loader's sky object survives (the lowest id),
  as if the later listings had joined it, and keeps its position. The
  others' listings and names move onto it in id order, their names after
  its own (a name it already has is dropped), and their magnitudes and
  sizes fill its empty ones by the precedence of 9.1, never replacing
  one. The stage returns each surviving sky object's HIP number and
  records it in `STAR_HIPS`, which the Hipparcos and WGSN supplementary
  sources (9.4) join on.

A star is typed `D*` if SAC's doubles (SaM, less its "rej." rows),
RASC's doubles (RDS), or a WDS pair that is a double star lists it;
otherwise `*`. Each loader types its own listings by the rule — SaM and
RDS `D*`; Str, SaR and TLK `*`; a WDS listing `D*` when one of its pairs
is a double star — and a merged star is `D*` if any of its sky objects
was. A WDS pair is a double star unless WDS notes it as dubious (X) or
gives no magnitude for its companion: optical pairs (S, U, Y, L) count,
and so do pairs without the primary (BC), and pairs however close, wide
or unequal. WDS lists a pair because someone measured it as one, so the
type says what the object is; whether an observer can see the companion
is for the filters (a double filters by its brighter star, 2.2) and for
the separation and both magnitudes the entry shows. This follows
mrosseel's review of #697 (2026-11). The earlier rule kept only
unflagged pairs with the primary, 0.5″ to 60″ apart and within 5 mag,
and typed 40,788 of WDS's 131,303 listings `*`; the rule now types
10,597 `*`, nearly all because their only pairs are flagged X. Vega
(optical companions) and Fomalhaut (SHY 106, its wide companion TW PsA)
are `D*` by WDS, as SAC lists them. ζ Scl, which SAC lists but whose only
WDS pair (B 631) is flagged X, has a correction that makes it `*`.

A **not-found** NGC/IC number (Steinicke's status 10, about 300 of
them) keeps its listing, its nominal position and type `?`, and its
description leads with "Not found: nothing at Dreyer's position
(Steinicke)." ahead of Dreyer's text, so nobody hunts an empty field.
Where Corwin identifies one, a correction sets its position and type
and replaces that description.

A Steinicke **duplicate** (status 7, another number in the same
catalog; status 8, an IC number already in the NGC) is not a sky object
of its own: its listing joins the sky object of the twin its first
identification names (NGC 6 joins NGC 20), following a twin that is
itself a duplicate. This is Steinicke's identification, not an aka
match, so the match guard does not apply; instead, a duplicate whose
row lies more than 1′ from its twin's contradicts the source and stays
its own, logged (NGC 6363, whose named twin is 11° away). The loader
types every other row by its status first (galaxy, planetary, globular,
not found) and by its TYPE within the status's kind; a part of another
galaxy (status 6) is typed by its remark.

For NGC and IC numbers, where the sources disagree about an
identification, Corwin's decides; an identification Corwin leaves open
("?", "??") stays as the sources give it. Corwin is not a vendored
source, so his identifications enter as corrections.

### 9.4 Supplementary sources

A supplementary source never adds listings. It is joined on a stable
key and fills or replaces one or more fields by a stated rule:

| source | joined on | rule |
|---|---|---|
| Hipparcos (`hip_main.dat`) | HIP, from the star-identity stage (9.3) | **replace** the position on every identified star; **replace** the primary's V only where Hipparcos's V is that star's own — not a double's combined light or another component's, and not a large-amplitude variable's; a companion's magnitude is untouched |
| IAU WGSN, Catalog of Star Names (`iau_wgsn/`) | HIP, from the star-identity stage | **add** the IAU name as the **preferred name**, with an ASCII form beside one with diacritics; older names (Graffias, Tegmen) stay as ordinary names, so text search still finds them |
| Bica et al. 2008 (VizieR J/MNRAS/389/678) | NGC/IC designation, through the match guard | **fill** a missing size on a Magellanic object; never replace one |
| RC3 (VizieR VII/155), extract of the rows whose `BT` is coded "V" | NGC/IC designation, letter included, to the Steinicke row the loader kept | **replace** V with Steinicke's Bmag where that Bmag equals RC3's V-coded `BT` within 0.05 — Steinicke read those as B and subtracted a colour, making 49 galaxies about 1 mag too bright |

They run in `SUPPLEMENTARY_SOURCES` order (`main.py`), after every
loader, post-processing and the star cross-match, and before the
correction pass, so a correction still has the last word. Each source is
vendored under `astro_data/` with a README recording where it came from;
Bica and RC3 are VizieR extracts, kept verbatim as the recorded queries in
their `fetch.sh` return them, and the WGSN's catalog is its web page, kept
verbatim beside the table `extract.py` takes from it.

**Hipparcos.** A star is given Hipparcos's values only if the
star-identity stage identified it by HIP — by position, by an exact
identifier, or by a `hip` correction (9.3) — and this stage makes no
match of its own: an unidentified star keeps its source's values even
where it sits on a Hipparcos star. Those identifications are the ones
the audit checked.

- **Position.** Hipparcos's, carried to J2000 by its proper motion as the
  cross-match reads it. The constellation follows the new position, as a
  loader computes it at insert. For a close double Hipparcos gives the
  pair's photocentre (its `AstroRef` flag), which is as good at a finder's
  scale. The sources' positions are rounded (SAC's to 0.1ᵐ in RA and 1′ in
  Dec), and a few SAC rows identified by their WDS designation lie
  minutes off (SaM 1019, STF 1316, 14′).
- **V.** The primary's, the first magnitude, becomes Hipparcos's V (H5)
  only where that V is the star's own: Hipparcos flags a double's
  combined light (`CombMag`, H43) and the component its photometry
  refers to (`m_Hpmag`, H48: `*` and `-` a system's combined light, a
  letter that component). V is the star's own where H43 is blank and H48
  is blank or `A`. Porrima's Hipparcos V, 2.74, is its two 3.5 mag stars
  together; put in A's place beside B's 3.5, it would count B twice.
  Those stars keep their source's V, and so do:
  - a variable of large amplitude (H6, the variability flag, is 3: over
    0.6 mag), whose Hipparcos V is one value of its swing (SAC gives
    Mira's maximum, 2.0; Hipparcos 6.47);
  - a sky object whose magnitude is a variable's range (TLK's
    `[max, min]`), for the same reason;
  - a star Hipparcos gives no V for.

  A companion's magnitude is never touched: a `D*`'s `[A, B]` keeps B.

**WGSN.** The IAU Working Group on Star Names keeps the IAU Catalog of
Star Names as a living table on its own site; `fetch.sh` keeps the page
verbatim and `extract.py` writes the table the import reads, so the import
never parses HTML. Each name with a HIP number joins the star the
star-identity stage identified by that number, and nothing else:

- The IAU name becomes the sky object's **preferred name** (9.6), placed
  first, or moved first if the object already has it; its other names
  stay behind it, so Graffias, Azmidiske and Tegmen still find their
  stars.
- The name is stored as the WGSN spells it, diacritics included (Mönch,
  Dhanuśarāgra). Where it has diacritics its ASCII form (Unicode NFKD,
  combining marks dropped: Monch) is stored as well, as an ordinary
  name, so the keypad's text search finds it.
- A name with no HIP number, one whose star PiFinder doesn't hold or
  didn't identify, and the two names of HIP 72105 (Izar and Pulcherrima,
  with no component to choose between them) are skipped; the import logs
  how many, and the names other sky objects carry too. Since the Named
  Stars catalog lists every HIP number the WGSN names (9.3), every name
  with a HIP number has its star: Nam 72105 is ε Boo, the pair, with
  neither IAU name, as before.

Steinicke's Bmag is never used as a fallback V on its own: for
non-galaxies it is often NGC 2000.0's photographic figure, and for M 43
it is the exciting star's. An object with no V stays without one unless
a later loader fills it or a correction sets it.

**Bica.** Each NGC or IC number in a row's names joins that listing's
sky object, and the join must pass the match guard (9.3), as a loader's
does: the two catalogs disagree about some identifications, and position
is what shows it. Steinicke and Bica swap NGC 2029 and NGC 2030, 91′
apart; Bica's NGC 2171 and NGC 2094 lie 70′ and 33′ from Steinicke's;
and Steinicke types NGC 1932, IC 2115 and IC 2116 as stars, which none of
Bica's clusters, associations or nebulae joins. Each rejection is logged
and fills nothing. A not-found object gets no size either, since only an
identification places one (Bica has a cluster 5′ from NGC 1915's nominal
position). Where two rows reach one sky object, the nearer fills it:
Steinicke makes NGC 1911 a duplicate of NGC 1920, while Bica lists a
0.6′ cluster 8.8′ away as NGC 1911. A lettered name (`NGC1921e`,
`NGC1850A`) is half of a pair or a neighbour, so it joins nothing.

Fill-only for Bica is deliberate: its cluster-only sizes would otherwise
overwrite the complex sizes PiFinder keeps for objects like NGC 1966.
Where Bica shows that a size is simply wrong (NGC 602's 34′ for 3.2′),
or gives the size for an identification the join refused, that is a
correction citing Bica.

**RC3.** RC3 writes a galaxy's NGC or IC designation as Steinicke does,
letter included, so each RC3 name joins the Steinicke row the loader keeps
for that number (`select_listings`): RC3's NGC 78A is the row PiFinder
lists as NGC 78, and RC3's NGC 986A, a companion, is not NGC 986.
Steinicke's Bmag comes from that row in `steinicke_catalog.json`, which
the Steinicke loader extracts before anything else runs; the database
has no Bmag column and needs none. The V is replaced only on a sky object
that still holds that row's V, the value the rule fixes, and a row with
no V leaves its sky object without one. Matched this way, RC3 and
Steinicke give the audit's 48 galaxies exactly, plus NGC 78, which
Steinicke lists only as its A component.

### 9.5 Corrections

A **correction** is a cited value that replaces what the sources give,
in `astro_data/corrections/<source>.toml` — one file per published
source it contradicts, so each file doubles as the upstream report. The
format, and every check, is documented in
[`astro_data/corrections/README.md`](../../astro_data/corrections/README.md).

- **Keyed by designator**, applied to the sky object it resolves to; a
  description applies to that one listing.
- **Three operations**: set fields (`obj_type`, `ra`, `dec`, `const`,
  `size`, `mag`, `description`, and clear `size` or `mag` with `""`);
  edit names (`names.add`,
  `names.remove`, `names.preferred`); correct an identification
  (`same_as`, `own_object`, or `hip` for a star listing — applied
  before the star cross-match, not in the final pass).
- **Checked.** A field correction states the value it replaces
  (`was.<field>`). If the field already holds the corrected value the
  correction is redundant; if it holds anything but `was` it is stale.
  Either fails the import, as do two corrections reaching one field of
  one sky object, a designator that resolves to nothing, and a missing
  `why` or `sources`. Name and identification corrections are checked
  the same way: removing an absent name, or a `same_as` that is already
  true, fails. A `same_as` must also pass the loaders' match guard from
  the listing's own type and position, unless it opts out with a cited
  `guard = false`; a size must be finite and positive.
- **All or nothing.** Identifications go first, since they change what
  designators resolve to; every other correction is then checked before
  any is written, and a failure rolls the whole pass back.

The pass runs last (9.1), so a correction always wins. A rule of thumb
for anyone adding one: if you are about to write more than a handful of
corrections citing the same reference, it is a supplementary source.

### 9.6 Name order

The names table holds **common names** and **cross-designations** side
by side, in import order, and nothing marks which is which. The order is
meaningful: the device shows `names[0]` (chart readout, object list) and
the atlas takes the first name that survives its filters. A **preferred
name** is a common name placed first — by WGSN, by the Messier names, or
by a correction. An object without one shows its first cross-designation.

The name files:

- `ngc_ic_m/messier/messier_names.dat` is curated, one line per named
  Messier object (`M<n><TAB>Name; Name`). A post-processing step puts a
  line's names ahead of the object's other names, in order, so its first
  name is the object's preferred name. A cross-designation ("Winnecke 4")
  or a description ("Satellite of M31") is not a name, so it has no
  place here.
- `ngc_ic_m/ngc2000/names.dat` is NGC 2000.0's, published. It is read
  as published but title-cased on read (the atlas's rule: small words
  after the first stay lower case), so "Crab nebula" reads "Crab
  Nebula". Its misplaced names are corrected in `ngc2000_names.toml` —
  including the half of a fix whose key is another catalog's (the
  Horsehead moves from IC 434 to B 33): a correction lives in the file
  of the source whose error it fixes.
- `iau_wgsn/iau_csn.tsv` is the IAU's, published: each identified star's
  IAU name becomes its preferred name (9.4).

The import must therefore keep names in a reproducible order; a `set()`
of strings is ordered by Python's per-process hash seed and is not.

### 9.7 Committing the database

The committed `pifinder_objects.db` is about 24 MB compressed, and a
fielded unit's update downloads every version of it that was committed
since its last one. Commit a rebuilt database only in a pull request
that means to change the data, and batch import changes so one rebuild
carries many. Loader code may sit ahead of the committed database in
the meantime — a device never runs the import. The data assertions in
`tests/test_catalog_data.py` read the committed file, so they land
together with the rebuild that makes them true.

---

## 10. Glossary

The canonical glossary lives at [`catalog/CONTEXT.md`](./catalog/CONTEXT.md).
Use those terms when reading, writing, and discussing code in this area.
