# Catalog

The Catalog context owns runtime loading, filtering, searching and display of astronomical catalogs (Messier, NGC, IC, WDS, planets, comets…) for the UI and web layers. Catalog state lives in the main UI process; other processes only see catalog content indirectly through the shared `objects.db` and `observations.db`.

> Companion architecture doc: [`../catalog.md`](../catalog.md).

## Language

### Identity

**Catalog code**:
Short string identifier for a catalog as a whole — `"M"`, `"NGC"`, `"IC"`, `"WDS"`, `"PL"` (planets), `"MP"` (asteroids). Drives DB queries and the UI designator. Its readable sibling is the **catalog display name** ("Collinder" for code `"Cr"`).
_Avoid_: catalog id, prefix; for the readable form say **catalog display name**, not "catalog name".

**Catalog display name**:
The readable, human-facing label for a catalog as a whole — `"Collinder"`, `"Caldwell"`, `"SAC Doubles"` — the prose twin of the terse **catalog code** (`"Cr"`, `"C"`). Stored as `Catalog.name` (DB column `name`); `None` for virtual/legacy catalogs, where the UI falls back to the code. Distinct from object-level **Names** ("Andromeda"): a display name names the *catalog*, not a sky object.
_Avoid_: catalog name (prefer the full term), catalog title, long name.

**Sequence**:
Integer position of an object inside one catalog (e.g. `13` for M 13). Must be unique within a catalog (enforced by `CatalogBase.check_sequences()`).
_Avoid_: number, index, ordinal.

**Object ID** (`object_id`):
Primary key in the SQLite `objects` table — i.e. the **sky object**'s id. The same sky object may appear in multiple catalog listings and they all share one `object_id` (e.g. M 31 ≡ NGC 224). `CompositeObject` equality/hash is keyed on this.
_Avoid_: object key, db id.

**Catalog object ID** (`id`):
Primary key in the `catalog_objects` table — the **catalog listing**'s id, distinct from `object_id`. Rarely used outside DB code.
_Avoid_: row id, catalog row.

**Sky object**:
A row in the `objects` SQLite table — the physical thing in the sky. One sky object can be listed in many catalogs.
_Avoid_: object (without "sky" qualifier, "object" means `CompositeObject`), DSO row.

**Catalog listing**:
A row in the `catalog_objects` SQLite table — how a sky object appears in one particular catalog (catalog_code + sequence + description). One sky object can have many catalog listings.
_Avoid_: catalog object (sounds like `CompositeObject`), entry, catalog row.

**Virtual ID**:
Negative `object_id` minted by `VirtualIDManager` for in-memory-only catalog objects (planets, comets, coordinate objects from observing lists) so they still hash uniquely. All virtual IDs come from the manager — never hand-pick a negative number, or two in-memory objects can collide and compare equal.
_Avoid_: synthetic id, fake id.

**Designator**:
The user-facing formatted string for a catalog entry — `"NGC 7000"`, `"M 13"`, `"PL Mars"`. Managed by `CatalogDesignator`; per-catalog width comes from `max_sequence`.
_Avoid_: label, name (a "name" is a common name like "Andromeda").

### Domain objects

**CompositeObject**:
The runtime unit displayed in the UI: a catalog listing merged with its underlying sky object, common names, magnitude, and `logged` flag. Built once and held by reference across catalogs. The bare word "object" in prose means a `CompositeObject`.
_Avoid_: object record, catalog row, entry.

**MagnitudeObject**:
Wrapper around a list of magnitude values. Exposes `filter_mag` (mean of parseable floats) for filtering and `calc_two_mag_representation()` for the `"min/max"` display string. `UNKNOWN_MAG = 99` is the sentinel.
_Avoid_: magnitude, mag (those are the underlying floats).

**Names**:
The common-name lookup: `id_to_names: object_id → list[str]` and the reverse `name_to_id`. Loaded once at startup.
_Avoid_: aliases, labels.

**Catalog** (the class):
A `CatalogBase` (object list + sequence/id indices) plus filtering: holds the shared `CatalogFilter`, the `filtered_objects` view, and `get_status()`.
_Avoid_: catalog object, catalog instance — use `Catalog` when the class is meant.

**Catalogs** (the catalog collection):
The container of `Catalog`s. Owns the singleton `CatalogFilter` and the T9/text search caches; this is the runtime API used by the UI and web. In prose, say "the catalog collection"; reserve `Catalogs` (code-style) for the type itself.
_Avoid_: catalog list, catalog set, the catalogs object.

### Filtering

**CatalogFilter**:
Single shared filter installed on every `Catalog`. Holds five filter parameters plus the enabled-catalogs set; every setter calls `mark_dirty()`.
_Avoid_: filter, criteria — "the filter" is fine in prose but the type name is `CatalogFilter`.

**Enabled catalog**:
A catalog whose code is in `CatalogFilter.selected_catalogs` — i.e. the user has turned it on in the UI. `Catalog.is_selected()` checks membership; iterating `Catalogs` yields enabled catalogs only.
_Avoid_: selected catalog (the code identifier says `selected_catalogs`, but in prose we reserve "selected" for the displayed object — see below), active catalog.

> Note: the field is named `selected_catalogs` in code (`catalogs.py:182`, menu structure, config key `filter.selected_catalogs`). The prose term is "enabled" — keep the existing identifier names but say "enabled" in docs and conversation.

**Filtered objects**:
The post-filter view returned by `Catalog.get_filtered_objects()`. Distinct from enabling: filtering operates inside a catalog; enabling picks whole catalogs in/out.
_Avoid_: matching objects, visible objects.

**Selected object**:
The single `CompositeObject` currently being viewed in `UIObjectDetails` (info + push-to guidance). Not a property of a catalog — it's a UI cursor.
_Avoid_: current object, active object, target object.

**Logged**:
Technical: the object has a row in the observations DB log table. The `CompositeObject.logged` bool is populated at build time from `ObservationsDatabase.check_logged(obj)`. Use this term when talking about table membership / DB queries / the field itself.
_Avoid_: observed (that's the user-facing twin — see below).

**Observed**:
User-facing: "I've seen this object." Surfaces as the `CatalogFilter.observed` parameter (`"Yes" | "No" | "Any"`) and in UI copy. The predicate test reads `obj.logged`, so the two terms refer to the same underlying state — they're deliberately split into a technical term (`logged`) and a colloquial one (`observed`).
_Avoid_: logged (when speaking to users or in UI copy), seen.

**Dirty time** (`dirty_time` / `last_filtered_time`):
Pair of epoch timestamps that drive the per-object filter cache. An object is re-evaluated only when `obj.last_filtered_time < filter.dirty_time`.
_Avoid_: invalidation, cache key.

**Catalog content dirty**:
A wake-up flag for runtime object changes under unchanged filter criteria. The changed catalog resets its own cached verdicts, then `mark_catalog_content_dirty()` makes open lists rebuild without advancing **Dirty time**.
_Avoid_: filter dirty (the criteria did not change), stale (time did not expire the verdict).

**Empty-list rejection**:
For `object_types` and `constellations`, an empty list rejects every object; only `None` (or `"Any"` for `observed`) means "don't filter on this dimension." Flagged here because it surprises callers.
_Avoid_: empty filter, no filter.

### Loading

**Priority catalogs**:
The hard-coded set `{"NGC", "IC", "M"}` loaded synchronously during `CatalogBuilder.build()` so the UI is usable in a few hundred ms.
_Avoid_: core catalogs, default catalogs.

**Deferred catalogs**:
Everything else (e.g. WDS) — loaded in a daemon thread by `CatalogBackgroundLoader` after the UI is up.
_Avoid_: background catalogs, lazy catalogs.

**Populated**:
A catalog has at least one `CompositeObject` in its `get_objects()` list. Priority catalogs are populated by the end of `build()`; deferred catalogs become populated at the moment `_on_loader_complete` runs (all deferred catalogs flip together — intentional, so the UI gets one `"catalogs_fully_loaded"` notification rather than a stream).
_Avoid_: loaded (without qualifier), ready.

**Fully loaded**:
The background loader thread has exited — `Catalogs.is_loading()` returns False. For deferred catalogs this coincides with becoming populated; for priority catalogs there is a window where they're populated but the system isn't fully loaded yet.
_Avoid_: loaded (without qualifier), done.

**CatalogBackgroundLoader**:
Daemon thread that streams deferred catalog objects in batches of 100 with a 0.05 s CPU-yield between batches; signals completion to the UI by pushing `"catalogs_fully_loaded"` on `ui_queue`.
_Avoid_: background loader, async loader.

**`catalogs_fully_loaded`**:
The literal string token pushed onto `ui_queue` once deferred loading completes. The UI watches for it to refresh lists.
_Avoid_: load-done event, ready signal.

### Dynamic catalogs

**Dynamic catalog**:
A `Catalog` whose objects are computed at runtime rather than loaded from `objects.db`. Currently `PlanetCatalog`, `CometCatalog`, and `AsteroidCatalog`.
_Avoid_: live catalog, computed catalog.

**PlanetCatalog**:
The `"PL"` catalog. Recomputes planet positions on a `TimerMixin` schedule using `sf_utils.calc_planets(dt)`. Adaptive delay: 10 s pre-GPS-lock, 307 s after.
_Avoid_: planets, ephemeris (those are more general).

**CometCatalog**:
Comet equivalent of `PlanetCatalog`. Imported locally inside `CatalogBuilder.build()` to break a circular import.
_Avoid_: comets.

**AsteroidCatalog**:
The `"MP"` dynamic catalog. Loads the MPC annual bright-minor-planet subset, uses the numbered minor planet as its stable **Sequence**, computes current position and H-G apparent magnitude, and enriches visible objects with distance, opposition/greatest-elongation, and apparition-peak data. Source replacement is atomic; populated objects remain available during download.
_Avoid_: minor planets (when the concrete catalog class is meant), `Ast` (that code means asterism).

**Catalog data age**:
Whole days since the active downloaded elements file's server timestamp. Used for frequently refreshed sources such as comets. During refresh this continues to describe the objects actually on screen; it changes only after a validated file replaces the active source. Annual asteroid data instead shows its compact MPC edition label, because a large day count is normal rather than a stale-data warning.
_Avoid_: catalog age (ambiguous with the runtime `Catalog` object).

**Download progress**:
The `CatalogStatus.data["progress"]` percentage for a downloaded dynamic catalog. `None` means the response has no known Content-Length and the UI draws an indeterminate bar. Progress does not imply the old objects have been removed; they stay usable until recalculation succeeds.
_Avoid_: loading progress (deferred database catalog loading is a different lifecycle).

**TimerMixin**:
Composition helper providing self-rescheduling periodic timers. `time_delay_seconds` may be a callable for adaptive delays. Updates run in their own thread, not on the timer thread.
_Avoid_: scheduler, ticker.

**Catalog status** (`CatalogStatus`):
NamedTuple `(current, previous, data)` exposing the lifecycle state of a (typically dynamic) catalog. Current values: `READY`, `NO_GPS`, `DOWNLOADING`, `CALCULATING`, `ERROR`.
_Avoid_: catalog state (the enum is `CatalogState`; the wrapper is `CatalogStatus`).

### Search

**Text search** (`search_by_text`):
Lower-case substring match against every name in every catalog. Selection and filter state are ignored. Backs the UI context's **multi-tap** search input method.
_Avoid_: name search, full-text search.

**T9 search** (`search_by_t9`):
Substring search after translating names to PiFinder's non-standard keypad-digit form (`KEYPAD_DIGIT_TO_CHARS` — `7→abc`, `1→tuv`, …). Backed by `_t9_cache` keyed on `(catalog_code, sequence)`. Backs the UI context's **T9** search input method; reserve "T9 search" for this algorithm — the user-facing setting is the **search input method**.
_Avoid_: keypad search, digit search.

### Observing lists

**Observing list**:
An ordered set of targets stored as one file under `PiFinder_data/obslists/`. A list's **origin** is just how that file got there — exported from another app (any of the third-party **list formats**), hand-authored, the **native format**, or saved by PiFinder itself (SkySafari `.skylist`); PiFinder reads the file regardless. There is no built-in online/download source for lists today (the DeepSkyLog integration is for **equipment**, not lists).
_Avoid_: target list, tour (a tour is a device-specific format family, not the concept), skylist (that's one format).

**Observing list entry** (`ObsListEntry`):
One target as parsed from a list file — the format-neutral interchange item every reader produces and every writer consumes. Either **catalog-keyed** (carries a catalog code + sequence) or a **coordinate entry** (carries RA/Dec plus name and type). It is not a `CompositeObject`; it becomes one through resolution.
_Avoid_: entry (unqualified — too close to "catalog listing"), row, line, custom object.

**List format**:
One of the supported on-disk representations of an observing list: SkySafari, CSV, plain text, Stellarium, Autostar Tour, Argo Navis, NexTour, EQMOD Tour, and the native format. Detected by file extension first, content sniffing second; unrecognized content degrades to plain text (names only).
_Avoid_: file type, flavor.

**Native format** (`.pifinder`):
PiFinder's own versioned JSON list format — the only one that losslessly carries catalog keys, structured magnitudes, and size/extent geometry. The format permits any coordinate `epoch` — a file-level default with optional per-entry overrides (J2000 unless stated); within PiFinder everything is J2000, so the reader precesses non-J2000 inputs to J2000 and the writer emits J2000. As a standalone library the format is epoch-agnostic. See [ADR 0016](../../adr/0016-pifinder-native-observing-list-format.md) and the format reference in [`obslist-formats/`](./obslist-formats/README.md).
_Avoid_: PiFinder format (ambiguous in prose), JSON format (Stellarium is JSON too).

**Resolution**:
The umbrella term for matching an observing list entry to a `CompositeObject` in the catalog collection. Two strategies are tried in a fixed order, then a coordinate fallback:
1. **Catalog-keyed resolution** — match by catalog code + sequence, with alias mapping (Messier→M, Caldwell→C, Collinder→Cr). Tried whenever the entry carries a catalog key.
2. **Name resolution** — exact, case-insensitive match of the entry's name against catalog object names, also trying a constellation-genitive–normalized variant ("VY Andromedae" → "VY And"). **Strictly a fallback**: attempted only when catalog-keyed resolution finds nothing. Names collide more readily than catalog keys, so a name never overrides a key match.
3. If both fail, an entry carrying coordinates becomes a **coordinate object**; an entry with no key, no name match, and no coordinates is dropped.
_Avoid_: lookup, import (import is the whole read-then-resolve flow).

**Coordinate object**:
A `CompositeObject` minted at list-load time from a coordinate entry when resolution fails. In-memory only, carries a virtual ID, catalog code `OBS`.
_Avoid_: custom object, user object, unresolved object (it *is* resolved — to coordinates).

### Composed descriptions

**Composed description**:
The merged, multi-source description shown for the selected object in object details. Sections appear in a fixed order: **observing list descriptions first** (this session's), then the **home** catalog description, then the object's **other catalog listings'** descriptions (deduped). Built by `CompositeObject.composed_sections()`; `composed_description()` is the flat-string form for non-UI consumers.
_Avoid_: aggregated description, full description, merged text.

**Section source**:
The provenance label on one section of a composed description. Three kinds: *observing-list source* — a per-list **observing list description**, labeled with the **observing list** name, shown **first**; *home* — the selected object's own catalog description, **unlabeled when it leads** (you already know what you're looking at), but labeled with the object's own **Designator** once an observing list description precedes it, so it doesn't read as part of it; *catalog-listing source* — the same sky object's description in another catalog listing, labeled with that listing's **Designator** (`"Cr 24"`, kept code-based — not the catalog display name — to stay short on a 128-px screen). The label is drawn as a rule (`─── Cr 24 ───`) above its text.
_Avoid_: section header / section heading (that's the visual rendering of the label), provenance, origin.

**Observing list description**:
The description text an observing list carries for one of its targets — the observing-list counterpart of a **catalog description**. So an object's description can come from a catalog *or* from an observing list, and the **composed description** shows both. Session-only, held in `CompositeObject.list_descriptions` keyed by list name (re-loading a list replaces its own entry, never duplicates). Set only on **resolved** objects; a **coordinate object** has none (its list text becomes its own catalog-side description, since it has nothing else).
_Avoid_: list note, note, comment, annotation, user description.

### UI helpers

**CatalogDesignator**:
Holds the formatted input string the user edits during catalog-code selection (`"NGC----"`, `"M-13"`). Width derives from each catalog's `max_sequence`.
_Avoid_: input buffer, designator input.

**ROArrayWrapper**:
Read-only proxy returned from `CatalogBase.get_objects()`. Iterable and indexable, not mutable.
_Avoid_: readonly list, immutable view.

### Boundary terms

**`shared_state`** is referenced by Catalog but **owned by Positioning**. See [Positioning](../positioning/CONTEXT.md).

**`logged`** on `CompositeObject` is set at build time from `ObservationsDatabase.check_logged(obj)`; the observations DB is read-only from the Catalog's perspective.

**`altaz_ready` / `FastAltAz`** come from the Positioning context — Catalog uses them only to gate the altitude filter.

## Flagged ambiguities

- **"Catalog"** — refers either to the class `Catalog` (one M, NGC, etc.) or the collection `Catalogs`. In prose, prefer "the catalog collection" for the `Catalogs` instance and "a catalog" for one of them; write `Catalogs` / `Catalog` in code-style when the type itself is meant.
- **"Object"** — bare word means `CompositeObject`. For the DB layers force a qualifier: **"sky object"** = `objects` row (the physical thing; one per real-world target), **"catalog listing"** = `catalog_objects` row (one per appearance of a sky object in a catalog). M 31 is one sky object with multiple catalog listings ("M 31" and "NGC 224"), all surfaced as separate `CompositeObject`s but sharing an `object_id`.
- **"Selected"** has two valid meanings — keep them apart:
  - **Selected object** = the single object currently displayed in `UIObjectDetails`. UI-cursor concept.
  - The catalog-level concept used to be called "selected catalogs" in code and is still named that way (`CatalogFilter.selected_catalogs`, `Catalog.is_selected()`). In **prose** we now say "enabled catalog" to avoid confusion with the selected object. Don't rename the code identifiers — just the words you use to talk about them.
- **"Filtered"** vs **"enabled"** — filtered is per-object inside a catalog; enabled is whole-catalog in/out. They compose: a filtered-out object can live in an enabled catalog.
- **"Entry"** — never bare. An **observing list entry** is the parsed interchange item from a list file; a **catalog listing** is a `catalog_objects` DB row. They are unrelated despite both sounding like "entry".

## Example dialogue

> **Dev:** I want to show only galaxies the user has seen in the M and NGC catalogs.
>
> **Domain:** So you'll **enable** M and NGC (`selected_catalogs = {"M", "NGC"}` in code), set `object_types = ["Gal"]`, and `observed = "Yes"`. Iterating the `Catalogs` collection yields just those two enabled `Catalog`s, and `get_filtered_objects()` on each gives you the galaxies with `logged=True`.
>
> **Dev:** And when the user opens NGC 7000 from the list?
>
> **Domain:** That makes NGC 7000 the **selected object** — the one `UIObjectDetails` is showing. Selecting an object doesn't change which catalogs are enabled or which objects are filtered in; it's an independent UI cursor.
>
> **Dev:** What if no galaxies are logged yet?
>
> **Domain:** Then `filtered_objects` is empty — which is fine. Watch out though: if you bound the type list to a UI list and the user unchecks everything, you'll send `object_types=[]`, which **rejects everything**. Only `None` means "don't filter on type."
>
> **Dev:** The user loads an observing list with "M 31" and a nameless target at some RA/Dec. What comes out?
>
> **Domain:** Two **observing list entries**. "M 31" is **catalog-keyed**, so **resolution** finds the existing `CompositeObject` — same `object_id`, same logged state. The RA/Dec one is a **coordinate entry**; it can't resolve, so it's minted as a **coordinate object** with a fresh **virtual ID** under catalog code `OBS`. Don't call either one a "catalog listing" — that's a DB row.
