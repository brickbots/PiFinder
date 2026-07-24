# The catalog system

This document describes how PiFinder loads, organizes, filters, searches,
and updates astronomical catalogs at runtime. The bulk of the system
lives in `PiFinder/catalogs.py`, with supporting types in
`PiFinder/catalog_base.py` and `PiFinder/composite_object.py`, and the
on-disk SQLite layer in `PiFinder/db/objects_db.py`.

For the canonical glossary of terms and data structures, see
[`catalog/CONTEXT.md`](./catalog/CONTEXT.md).

---

## 1. The big picture

At a high level:

```
   SQLite (astro_data/pifinder_objects.db)
        │
        ▼
   CatalogBuilder.build()
        │
        ├── synchronous load:  priority catalogs  (M, NGC, IC)
        │       │
        │       └─► List[CompositeObject] ─► _get_catalogs() ─► Catalogs
        │
        ├── background thread: deferred catalogs (WDS, …)
        │       │   via CatalogBackgroundLoader (batched, CPU-yielding)
        │       └─► on_complete → catalogs.get_catalog_by_code().add_objects()
        │                                                 └─► re-filter
        │
        ├── dynamic catalogs:  PlanetCatalog (TimerMixin, every ~5 min)
        │                       CometCatalog (similar)
        │
        └─► Catalogs object (single instance shared across the app)
                 │
                 ├── CatalogFilter (one shared instance set on every catalog)
                 ├── T9 / text search caches
                 └── Iterates as List[Catalog], each holding List[CompositeObject]
```

The `Catalogs` instance is the runtime API for the rest of PiFinder
(menus, charting, web). The integrator/solver layer doesn't touch
catalogs directly — they live in the main UI process.

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
  key on their own listing — see ADR 0020),
  `last_filtered_time`/`last_filtered_result` (used by the filter
  cache).

Two `CompositeObject`s are equal iff their `object_id`s match. That
means the same underlying object referenced by multiple catalogs (e.g.
M 31 ≡ NGC 224) will hash identically; this matters for set membership
but **not** for catalog iteration, which uses lists keyed by
`(catalog_code, sequence)`.

`display_name` returns `"PL <planet name>"` (capitalised) for planets,
otherwise `"<catalog_code> <sequence>"` — e.g. `"NGC 7000"`.

### 2.2 `MagnitudeObject`

Every `CompositeObject.mag` is a `MagnitudeObject` wrapping a list of
magnitudes (visual, photographic, combined-pair for doubles, etc.).

- `filter_mag` — single float used by the filter. Computed as the mean
  of all entries that parse as floats; defaults to
  `UNKNOWN_MAG = 99` when nothing parses.
- `calc_two_mag_representation()` — returns `"-"` if unknown, `"X.X"` if
  one value, `"min/max"` for two-or-more, used as `mag_str` for display.
- Serialised to/from JSON in the DB via `to_json` / `from_json`.

### 2.3 `Names`

`Names` (in `catalogs.py`) loads the common-names table once at startup
and exposes:

- `id_to_names: DefaultDict[int, List[str]]` — object_id → list of names.
- `name_to_id` — reverse lookup (built by `ObjectsDatabase.get_name_to_object_id`).

A `_sort_names()` hook exists for hierarchical sorting but is currently
empty.

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
- `get_status()` returning a `CatalogStatus(current, previous, data)`.
- `is_selected()` — whether this catalog appears in
  `catalog_filter.selected_catalogs`.

External code is expected to read through `get_objects()` (returns a
`ROArrayWrapper` — a read-only proxy that disallows assignment) or
`get_filtered_objects()`.

### 2.5 `Catalogs`

A container that holds a `List[Catalog]` plus the singleton
`CatalogFilter` and the T9 search cache. It exposes:

- `filter_catalogs()` — runs `filter_objects()` on every catalog.
- `set_catalog_filter(filter)` — installs one filter object on every
  catalog so changes propagate uniformly.
- `select_catalogs / select_all / select_no` — manipulate the selected
  set on the shared filter.
- `get_catalogs(only_selected=True)` / `get_codes(...)` /
  `get_objects(...)` — collection accessors.
- `get_catalog_by_code(code)` / `get_object(code, sequence)` — direct
  lookup.
- `search_by_text(s)` — substring match against all names (selected or
  not, filtered or not).
- `search_by_t9(digits)` — see §5.
- `add(catalog)` / `remove(code)` / `set(catalogs)` — mutate the
  collection and invalidate the T9 cache.
- `is_loading()` — reports whether the background loader thread is
  still alive (UI uses this to show a "still loading" indicator).
- `__iter__` — yields only selected catalogs.

---

## 3. Building: `CatalogBuilder`

`CatalogBuilder.build(shared_state, ui_queue=None)` is called once
during startup (from the main process when initialising the catalog
menu). It:

1. Opens `ObjectsDatabase` and `ObservationsDatabase`.
2. Loads all rows from `catalog_objects`, the keyed-by-id `objects`
   dict, `Names`, and `catalogs_info` (descriptions + max_sequence per
   catalog).
3. Splits `catalog_objects` rows into two buckets based on
   `catalog_code`:
   - **priority** (`{"NGC", "IC", "M"}`) — loaded **synchronously** by
     `_create_full_composite_object()`. About 13k objects.
   - **deferred** (everything else, e.g. WDS) — handed to a
     `CatalogBackgroundLoader`.
4. Groups the loaded priority composites by `catalog_code` and creates
   one `Catalog` per entry in `catalogs_info`, ending up with a
   `Catalogs` instance even for catalogs that are currently empty (the
   background loader will populate them later).
5. Appends two dynamic catalogs: `PlanetCatalog` (`PL`) and, via local
   import, `CometCatalog`.
6. Asserts `check_catalogs_sequences(...)`.

The reference to the background loader is also stashed on the
`Catalogs` instance as `_background_loader` so `Catalogs.is_loading()`
can introspect it.

### 3.1 Priority vs. deferred — why

Synchronously loading every catalog (including WDS, ~tens of thousands
of double stars) blocks UI startup unacceptably. Splitting on
"popular" catalogs (M, NGC, IC) yields a usable UI in a few hundred
milliseconds; the rest stream in over the next several seconds while
the user can already navigate.

### 3.2 `CatalogBackgroundLoader`

A standalone, testable helper (no Catalog/Catalogs references — just
dicts, names, and the observations DB). Runs in a daemon thread:

- `batch_size = 100` `CompositeObject`s per batch.
- `yield_time = 0.05` s sleep between batches (gives CPU back to the
  solver/UI).
- Progress callback (`_on_loader_progress`) logs every 10k objects.
- Completion callback (`_on_loader_complete`) groups loaded objects by
  `catalog_code` and calls `catalog.add_objects(batch)` once per
  catalog (much cheaper than per-object adds, since `add_objects`
  rebuilds the position indices only at the end). It then re-runs
  `catalog.filter_objects()` on each catalog that now has new content,
  and finally pushes `"catalogs_fully_loaded"` onto `ui_queue` so the
  main loop can refresh.
- `stop()` sets a flag the worker checks per iteration and joins with a
  1 s timeout — used during shutdown.

---

## 4. Filtering: `CatalogFilter`

A single `CatalogFilter` is shared across all `Catalog`s via
`Catalogs.set_catalog_filter(...)`. It maintains five filter parameters
plus a selected-catalogs set:

| Property | Type | Meaning |
| --- | --- | --- |
| `magnitude` | `float | None` | Maximum `filter_mag`. `None` disables. |
| `object_types` | `list[str] | None` | Allowed obj_type values (e.g. `["Gal", "Neb"]`). Empty list **rejects everything**. |
| `altitude` | `int` | Minimum altitude in degrees. `-1` disables. Requires GPS lock to compute. |
| `observed` | `"Any" | "Yes" | "No"` | Match on `obj.logged`. |
| `constellations` | `list[str]` | Required `const` values. Empty list **rejects everything**. |
| `selected_catalogs` | `set[str]` | Which catalogs are "on" in the UI. |

### 4.1 Dirty tracking

Filtering is the hot path — every menu redraw asks for filtered objects.
Caching happens in two layers, both keyed against `dirty_time`:

- Every setter calls `mark_dirty()`, bumping `dirty_time = time.time()`.
- Per object: `CompositeObject.last_filtered_time` and
  `.last_filtered_result` cache the most recent decision;
  `apply_filter(obj)` short-circuits if `obj.last_filtered_time >
  self.dirty_time` — i.e. the object was filtered after the last change.
- Per catalog: `Catalog.filter_objects()` returns its cached
  `filtered_objects` list outright while `catalog.last_filtered >
  dirty_time`; any object-set mutation (`add_object`, `add_objects`,
  `clear_objects`) resets `last_filtered = 0` for that catalog.

So if the filter has not changed since the last sweep, a list open is
O(catalogs) cache reads with no real predicate work.

Two freshness triggers advance `dirty_time` besides the setters
([ADR 0020](../adr/0020-filter-freshness-staleness-promotion.md)):

- **Logging**: `Catalogs.mark_logged(obj)` sets `obj.logged` — on the
  object and its sibling composites sharing a non-negative `object_id`
  (M 31 / NGC 224) — and marks dirty when an observed criterion is
  active, so "Observed: No" lists drop the object on their next
  refresh. The refresh keeps the cursor on the selected object, or
  moves it to the old successor when the selection itself dropped out
  (`_next_target_index`).
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

### 4.3 Surprising "empty list = reject" behaviour

For both `object_types` and `constellations`, an **empty list rejects
every object**. Only `None` (or "Any" for observed) means "don't
filter." This is intentional — empty constellation list means "the user
unchecked everything." Callers should be careful when constructing
filters programmatically.

### 4.4 `load_from_config`

`CatalogFilter.load_from_config(cfg)` pulls the same five parameters
from `Config` under the `filter.*` namespace (`filter.magnitude`,
`filter.object_types`, …, `filter.selected_catalogs`). This is how the
filter is restored on app start.

---

## 5. Search

### 5.1 Text search

`Catalogs.search_by_text(s)` does a substring lower-case match against
each name on each object. Returns a `List[CompositeObject]`. No indexing
— it's O(n_names) per call but fine in practice.

### 5.2 T9 (keypad) search

PiFinder's hardware keypad uses a non-standard digit-to-letter mapping
(`KEYPAD_DIGIT_TO_CHARS` at the top of `catalogs.py` — note `7→abc`,
`1→tuv`, `3→'-+/`, etc.). `Catalogs.search_by_t9(digits)`:

1. Translates every object name to its digit-form via a
   `str.maketrans` table.
2. Filters out characters that aren't valid T9 digits.
3. Caches `(catalog_code, sequence) → list[digit_string]` in
   `_t9_cache`, invalidated when catalogs are added/removed/replaced.
4. Returns any object whose digit string contains the search pattern as
   a substring (skipping objects whose digit string is shorter than the
   query, since the substring couldn't match).

The cache is rebuilt lazily by `_ensure_t9_cache(objs)` only if the
dirty flag is set **or** the set of object keys has changed since the
last rebuild — so dynamic catalogs (PL, comets) updating their
positions don't trigger a rebuild as long as their key set is stable.

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
- **CatalogDesignator** (`catalogs.py`, near the bottom) holds the
  formatted input string for catalog-code selection — `"NGC----"`,
  `"M-13"`, etc., respecting a per-catalog width derived from
  `max_sequence`. It exposes `set_number`, `append_number`,
  `increment_number`/`decrement_number`, and `has_number`.
- **The filter UI** mutates `Catalogs.catalog_filter` via its
  properties (which mark it dirty); the next call to
  `Catalog.filter_objects()` re-runs the cached sweep.
- **Background-loader completion** sends `"catalogs_fully_loaded"`
  onto `ui_queue`, allowing the UI to refresh lists once the deferred
  load finishes.
- **The web server** uses the same `Catalogs` instance through the
  shared object model, exposing object data through `/api/...` routes.

There is no separate "catalog state" published on `shared_state`; the
catalogs live in the main process and are shared with other processes
only via the lower-level DB queries (`ObservationsDatabase` write-back
of logged status, for example).

---

## 8. Lifecycle summary

1. `CatalogBuilder.build()` constructs `Catalogs`, loads priority
   catalogs, starts background loader, attaches `PlanetCatalog` and
   `CometCatalog`.
2. `CatalogFilter` is constructed and hooked in via
   `set_catalog_filter`. `load_from_config(cfg)` restores user
   preferences.
3. Each UI refresh that needs filtered objects calls
   `catalog.filter_objects()` — cheap thanks to the dirty-time cache.
4. Periodic timers update `PlanetCatalog` / `CometCatalog` positions.
5. Background loader, when it completes, batch-adds deferred objects to
   their catalogs, triggers a re-filter, and signals the UI.
6. On shutdown, `CatalogBackgroundLoader.stop()` and any
   `TimerMixin.stop()` calls cancel their threads.

---

## 9. Glossary

The canonical glossary lives at [`catalog/CONTEXT.md`](./catalog/CONTEXT.md).
Use those terms when reading, writing, and discussing code in this area.
