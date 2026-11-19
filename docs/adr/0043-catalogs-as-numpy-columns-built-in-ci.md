# The DB catalogs are numpy columns built in CI, and objects are made only for the rows on screen

**Status: accepted.** Design: `ui-performance-plan.md`, step 2.

The 21 DB catalogs hold 151,170 catalog listings; WDS alone has 131,303. The UI process kept one `CompositeObject` per listing. That used about 276 MB of RAM, plus 46 MB for the T9 search cache, and the UI process used about 540 MB in total. A loader thread built the WDS objects after start, and it took the GIL from the UI thread for about 17 s. Filters, search, "All Filtered" and the Nearby index all walked every object in Python.

So each DB catalog is a set of numpy columns (`PiFinder/catalog_arrays.py`):

- Fixed fields are `.npy` files (`ra`, `dec`, `filter_mag`, `object_id`, `id`, `sequence`, and 1-byte codes for `obj_type` and `const`). Text is one UTF-8 blob per field with an offset array: names, description, the magnitude and size JSON, and the precomputed T9 digits and lower-case names.
- The app opens them with `np.load(mmap_mode="r")`. The pages come from the file cache.
- `ArrayCatalog` makes a `CompositeObject` only when code asks for a row, and keeps the last 5000. Runtime state per listing (`logged`, the filter verdict, observing-list descriptions) lives in arrays and a dict next to the columns.
- Lists of objects are `ObjectSequence`s (`PiFinder/object_sequence.py`): a source and a row per position. Filter, sort, Nearby de-duplication and search work on whole columns.
- Planets, comets and observing-list objects change at runtime, so they stay Python objects in a plain `Catalog`.
- A Nix derivation (`nixos/pkgs/catalog-arrays.nix`) builds the arrays in CI from the DB and the builder files only. A device never builds them. Without Nix, the app builds them once into `~/PiFinder_data/cache/catalog_arrays`.

## Considered options

- **Columns built in CI (chosen).** The objects DB is part of each release, so the arrays can be built with it. The derivation's inputs are only the DB and three Python files, so a normal code change does not rebuild the arrays or add a store path to download.
- **Columns built on the device at first boot, rejected.** The build takes about 4 s on a PC and much longer on a CM4, and it needs a cache check at every start. A Nix device does not need it.
- **Keep the objects, and load WDS on demand, rejected.** The first WDS list, search or Nearby sort would still build 131,000 objects, and the RAM would stay.
- **The pickle cache of objects (as before), rejected.** It is fast to write, but loading it still makes every object in Python.

## Consequences

Measured on a CM4 (pifinder.local), from a copy in `/tmp`:

- Opening the 21 catalogs takes about 0.8 to 0.9 s, with no thread after start.
- Filtering WDS with an altitude and a magnitude criterion takes 150 to 200 ms (2.37 s with objects). All 21 catalogs take about 170 ms.
- The Nearby de-duplication and BallTree over "All Filtered" take about 220 ms. T9 search takes 0.1 to 0.5 s and runs in its search thread.
- In a headless run on a PC, the private RAM of the UI process went from 542 MB to 152 MB.

Other consequences:

- Making one row costs about 1 ms on a CM4, so code must read columns, not iterate a large sequence. Iteration still works, but it makes every object.
- A `CompositeObject` made twice for the same row after it left the row cache is a new instance. Equality stays on `object_id`, and the runtime state lives in the arrays, so both instances agree.
- The per-object filter cache (`last_filtered_time` on the object) does not apply to DB listings. The per-catalog cache (`Catalog.last_filtered` against `dirty_time`) stays.
- A DB change or a builder change makes a new arrays store path. The `format` field in `meta.json` must change when the files change in a way the reader must know about.
