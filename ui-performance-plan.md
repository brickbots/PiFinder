# UI performance — design plan

**Goal:** the UI holds 30 FPS on a CM4 at all times, also while catalogs load
and while other processes are busy.

**Why this plan:** the UI process does heavy CPU work (the catalog loader, the
catalog filter), and its UI thread makes many small, blocking calls to the
shared-state manager process on every frame. Each call releases the GIL. A busy
thread in the same process then keeps the GIL for up to the switch interval
(5 ms by default). While catalogs loaded, the UI fell to 2 FPS. PR #111
reduces the effect (1 ms switch interval, about 7 in place of about 14 calls
per frame). This plan removes the two causes:

1. **Step 1 — state snapshot:** the UI reads shared state from shared memory,
   with no round trip to the manager process.
2. **Step 2 — catalog arrays:** catalogs are numpy columns in a memory-mapped
   file. There is no loader thread and no Python object per catalog listing.

Status: step 1 design agreed on 2026-09-30 (one lock per slot). Step 2
design agreed on 2026-09-30 (arrays built in CI).

---

## Step 1 — state snapshot

### What changes

- The manager process (`SharedStateObj`) stays the owner of shared state. All
  setters stay as they are: they still go through the proxy, and the
  writer-side rules stay on the write path (the timezone lookup in
  `set_location`, the forward-only rule and the manual latch in
  `set_datetime`, the value check in `set_power_state`).
- After a setter changes a value that is in the snapshot, `SharedStateObj`
  also writes that value into a **slot** in a shared-memory block.
- A reader calls `reader.read()` and gets a `StateSnapshot`: a frozen
  dataclass with all snapshot values. This is a memory copy in the reader
  process. There is no socket round trip and the GIL is not released.
- The manager process is the only process that writes slots. Its server
  runs one thread per client connection, so two threads can write the same
  slot (for example `set_location` from the UI and from telemetry replay).
  The slot lock covers this.

### Why one lock per slot

- The values in different slots have no relation to each other. The IMU and
  the power state do not need to agree. So there is no lock for the whole
  block.
- One value can be many fields. A solution holds RA, Dec, roll, constellation
  and times. Without a lock, a reader can copy half of an old solution and
  half of a new one. A half-written pickle can also fail to decode.
- A sequence counter (seqlock) needs memory barriers, because the ARM CPU in
  the CM4 can change the order of memory writes. Python cannot add these
  barriers reliably. A lock is correct by construction.
- Cost: `multiprocessing.Lock` first tries `sem_trywait` and keeps the GIL.
  A lock that nobody holds costs about 1 µs, and the reader does not release
  the GIL. The reader holds the lock only while it copies the bytes, and it
  decodes after it releases the lock.

### Slot layout

One `multiprocessing.shared_memory.SharedMemory` block. Each slot has a fixed
place and a fixed maximum size:

```
| version: u64 | length: u32 | payload: pickle bytes (max size per slot) |
```

- **version:** the writer adds 1 on each write. A reader keeps the last
  decoded value and its version for each slot. When the version did not
  change, the reader does not copy or decode the slot again. Most slots do
  not change between two frames.
- **payload:** a pickle of the value. This keeps the existing types
  (`PointingEstimate`, `ImuSample`, `Location`, ...). A fixed struct layout
  would be faster but is more code. We change to structs only if a
  measurement shows the need.
- **Maximum sizes:** a solution with 30 matched stars pickles to 2.4 KB, so
  the solution slot gets 16 KB. The other slots get 4 KB. The block is about
  64 KB. When a value does not fit, the writer logs an error and keeps the
  old value in the slot. A unit test checks the sizes against large values.

### Snapshot contents

Values that the UI reads on each frame, or on each frame of one screen:

| Slot | Type | Writer (through the manager) | Rate |
|---|---|---|---|
| `power_state` | int | UI | on event |
| `solution` | `PointingEstimate` | integrator | up to 30 Hz |
| `imu` | `ImuSample` | IMU process | about 30 Hz |
| `location` | `Location` (with timezone) | UI, telemetry replay | on fix / event |
| `datetime` | base datetime, its `time.time()` base, manual flag | UI, telemetry replay | about 1 Hz |
| `sqm` | `SQM` | solver | ≤ 1 Hz |
| `sqm_details` | dict | solver | ≤ 1 Hz |
| `battery` | `BatteryState` | battery process | every 5 s |
| `sats`, `gps_comms` | tuples | UI | ≤ 1 Hz |
| `last_image_metadata` | dict | camera | per frame |
| `hardware`, `camera_type`, `camera_lens`, `optical_train_known`, `test_mode` | small values | once or rare | rare |

Derived in the reader, not stored:

- `solve_state` = `solution is not None and solution.has_pointing()`
  (this is what `set_solution` stores today).
- `altaz_ready` = `location.lock and datetime is set`.
- `datetime` = base datetime + (now − base time), as `SharedStateObj.datetime()`
  does today. The snapshot stores the base, because the value changes with
  time.
- `local_datetime`, `utc_datetime`, `sky_brightness`.

Not in the snapshot: `screen`, `cam_raw`, `camera_image` (large images),
`current_ui_state`, the `UIState` proxy and `target_pixel`. These stay on the
manager. The UI-only values `message_timeout` and `show_fps` are already local
in the UI process (PR #111).

### How the processes get the block and the locks

- `main.py` creates the block and the locks **before** it starts the manager.
  A `SnapshotSpec` holds the block name, the slot layout and the locks.
- `multiprocessing` locks can go to another process only when that process
  starts. So:
  - the manager starts with `manager.start(initializer=..., initargs=(spec,))`
    in place of `with StateManager() as manager`. The initializer attaches the
    writer in the manager process.
  - each worker process gets the spec as a `Process` argument and makes its
    own `StateReader`.
- This works with the `fork` start method (Python 3.13 on Linux) and also
  with `forkserver` (the default from Python 3.14).
- `main.py` unlinks the block at shutdown. At startup it removes a block that
  a killed run left behind, as `solver.py` does for the cedar block.

### How the UI uses it

- The main loop reads the snapshot once per frame and stores it in
  `UIModule.snapshot`. Every screen reads `self.snapshot.solution()`,
  `self.snapshot.imu()`, and so on. All screens see the same values during
  one frame.
- `StateSnapshot` has the same getter names as `SharedStateObj`. So a helper
  that only reads state (`calc_utils.aim_degrees`, `pointing_snapshot`,
  `sleep_for_framerate`) takes either one, unchanged.
- Objects that keep a state object for their whole life (the catalog filter,
  `Nearby`) get `CurrentSnapshot()`, a view that answers from
  `UIModule.snapshot`.
- `PowerManager` is the only writer of the power state, so it keeps the value
  itself and does not read it back.
- Code that writes state keeps the setters on the proxy.
- The SQM calibration and sweep screens wait in loops for a new camera frame.
  The snapshot changes only between frames, so these screens keep the proxy.
- The getters on `SharedStateObj` stay. The web server, pos_server and the
  worker processes can change to the snapshot later.

### Why the code gets simpler

- One call, `reader.read()`, gives a consistent view. Today a screen calls
  `solve_state()` and then `solution()`, and the two calls can disagree.
- Draw code makes no proxy calls, so it cannot get a dead-manager error.
- Tests build a `StateSnapshot` directly. Today they need a fake
  shared-state class with the right methods.
- `solve_state` and `altaz_ready` are computed in one place.

### Open points

1. **Dead manager detection.** Today the UI finds out that the manager died
   when `sleep_for_framerate` gets an error from `power_state()`
   (`SharedStateLost`, PR #105). A snapshot read does not fail. Proposal: a
   thread in the manager process writes a heartbeat slot every second. A
   reader that sees a heartbeat older than 5 s raises `SharedStateLost`.
2. **`location` read-modify-write in `main.py`.** The main loop keeps a local
   `Location`, changes it and writes it back. It stays on the proxy for now.
3. **Web server and pos_server.** They read per HTTP request. They are not
   part of the frame rate, so they change later.

### Tests

- Unit: slot write and read, the version check, a value that is too large,
  and the derived values (`solve_state`, `altaz_ready`, `datetime`).
- Multi-process: a writer process writes pairs of values that must be equal
  as fast as it can. A reader process reads for some seconds and checks that
  every pair is equal (no half-written read).
- Count the manager calls per UI frame in a headless run, as for PR #111.
  Target: no manager call in a normal frame.
- Measure the FPS on the CM4 while catalogs load.

---

## Step 2 — catalog arrays

### Findings

- 151,170 catalog listings in 21 catalogs, 149,329 sky objects. WDS has
  131,303 listings. Priority catalogs (M, NGC, IC) are 13,336 listings.
- As `CompositeObject` instances the listings use about 276 MB of RAM
  (about 1.8 KB each). The T9 search cache adds 46 MB. As columns, the fixed
  fields need about 6 MB, and the text (names, descriptions, magnitude and
  size JSON) about 23 MB.
- The fields that change at runtime for DB-backed objects are only `logged`,
  `last_filtered_*` and `list_descriptions` (and `image_name`, which is never
  read). `_details_loaded`, `surface_brightness` and the object's own
  `last_filtered_time` are never read.
- Planets and comets change at runtime (in place, or rebuilt with new
  virtual IDs), and OBS, PUSH and USER objects exist only in memory.
- Objects go to other processes as pickles through `UIState` (recent list,
  target, observing list, pos_server push).
- `CompositeObject` equality is on `object_id`. The recent list, the details
  scroll and the nearby and chart de-duplication use this.
- Lists of objects are passed around as Python lists and used with `len`,
  `[i]`, `.index(obj)` and `np.where(array == obj)`.

### Storage

- Each DB catalog is a set of numpy columns in `.npy` files: `ra`, `dec`
  (f8), `filter_mag` (f4), `object_id`, `id`, `sequence` (i4), and
  `obj_type`, `const` as 1-byte codes with a code table.
- Text fields are one UTF-8 blob per field with an offset column: `names`,
  `description`, the magnitude JSON and the size JSON.
- Search data is computed ahead of time as blobs: the T9 digits of every
  name, and the lower-case names.
- The UI opens the files with `np.load(mmap_mode="r")`. This takes
  milliseconds. The pages come from the file cache, so they do not add to
  the process RAM like Python objects do.
- `meta.json` holds a format version, the DB size and the catalog table
  (code, display name, max sequence, row count).

### Build in CI

- A new Nix derivation `catalog-arrays` takes the DB from `astro-data` and
  the builder module `PiFinder/catalog_arrays.py` as its only inputs. It runs
  the builder and writes the column files. `pifinder-src` links the result
  in, as it does for `astro_data` and `fonts`.
- A normal code change does not rebuild the arrays and does not add a new
  store path to download. A DB change or a builder change does.
- The builder uses the `MagnitudeObject` rule for `filter_mag` (the mean of
  the values that parse, or 99), by import, so there is one rule.
- On the device the app never builds arrays. When `meta.json` does not
  match (format version, DB size), the app logs an error and builds the
  arrays into `~/PiFinder_data/cache/`.
- Without Nix (a dev venv, tests), the app builds the arrays into
  `~/PiFinder_data/cache/` on first start, or with
  `python -m PiFinder.catalog_arrays build`. Tests build arrays from a test
  DB with the same builder.

### Runtime state in the UI process

- `logged`: a writable bool array per catalog. At startup
  `logged = np.isin(object_id, observed_ids)` plus the listing match.
  `Catalogs.mark_logged` sets `logged[object_id == x] = True` in every
  catalog, with no object loop.
- The filter result: a bool array per catalog, and an index array of the
  rows that pass.
- `list_descriptions`: a dict keyed by `(catalog_code, sequence)`.

### Objects only for the rows on screen

- `catalog.row(i)` builds a `CompositeObject` from the columns and the
  runtime state. It stays the same dataclass, so pickling through `UIState`
  (recent list, target, observing list, pos_server push) does not change.
- `ObjectList` (a catalog plus an index array) replaces the Python lists of
  objects. It supports `len`, `[i]`, iteration and `.index(obj)`, and builds
  rows on access. The `np.where(array == obj)` in object details changes to
  `.index`.

### Operations on the arrays

- Filter: directly on the columns; the result is an index array per catalog.
- Sort by RA: `argsort`. Sort by catalog sequence: the row order.
- Nearby and chart: the BallTree is built from the `ra`/`dec` columns.
  De-duplication by `object_id` with `np.unique`. Only the results (at most
  200) become objects.
- T9 and text search: a substring search in one joined string. Match
  positions map back to rows with `searchsorted`. Results stay an index
  array, so a search that matches every WDS row is cheap.

### Two kinds of catalog, one interface

- `ArrayCatalog`: the DB catalogs.
- `ObjectCatalog`: planets, comets, and observing-list objects, as Python
  objects, as today. They change at runtime, so they cannot live in a
  read-only file.

### What goes away

The loader threads, priority and deferred catalogs, the "Catalogs Fully
Loaded" step, the pickle cache (`catalog_cache.py`), the T9 cache, and the
per-object filter fields. Expected RAM saving in the UI process: about 250
to 300 MB (an estimate).

### Tests

- Builder: a small test DB gives the expected columns, blobs and meta.
- `ArrayCatalog`: `row(i)` equals the `CompositeObject` that the old builder
  made for the same listing, for every listing of the real DB.
- Filter, sort, nearby and search give the same results as the old code on
  the real DB.
- `ObjectList`: `len`, `[i]`, iteration, `.index`.
- `mark_logged` marks sibling listings in other catalogs.
- On the CM4: startup time, RAM of the UI process, FPS after start.

### Results

Measured on a CM4 (pifinder.local), from a copy in `/tmp`, with the arrays
of the repo DB:

| Step | Objects (before) | Columns |
|---|---|---|
| Open the catalogs | about 1 s, then a 17 s loader thread | 0.8 to 0.9 s, no thread |
| Filter WDS (altitude + magnitude) | 2.37 s | 150 to 200 ms |
| Filter all 21 catalogs | | about 170 ms |
| Nearby de-duplication + BallTree, All Filtered | | about 220 ms |
| T9 search | | 0.1 to 0.5 s |
| Text search "andromeda" | | 40 to 140 ms |
| Make one row | | about 1 ms |

Private RAM of the UI process in a headless run on a PC: 542 MB before,
152 MB after.

The first Nearby sort after a start imports sklearn, which takes about 9 s
on a CM4. This is not part of this change.

### Bugs found on the way (not part of this plan)

- `catalog_cache.save()` sets `logged = False` on the live objects, so after
  a first boot every logged check mark is gone until the next restart
  (`catalog_cache.py:162-163`).
- On the DB-build path, `_background_loader` keeps all build data in memory
  for ever (`catalogs.py:1063`).
- `check_catalogs_sequences` returns after the first catalog
  (`catalogs.py:1089-1095`).
- `object_details.serialize_ui_state` reads the attributes `catalog` and
  `magnitude`, which do not exist (`object_details.py:786-805`).
- `docs/ax/catalog/CONTEXT.md` said that an empty `object_types` or
  `constellations` list rejects every object. The code treats an empty list
  as "no filter". The docs now say so (fixed with step 2).
