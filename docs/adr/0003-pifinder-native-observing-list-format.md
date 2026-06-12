# 0003: A native `.pifinder` observing-list format

PiFinder reads eight third-party observing-list formats (SkySafari, CSV, plain text, Stellarium, Autostar Tour, Argo Navis, NexTour, EQMOD Tour), but none can carry everything a PiFinder object knows: catalog keys (catalog code + sequence), structured multi-band magnitudes, size/extent geometry, and explicit coordinate epochs. Rather than stretching one of them, we define a ninth, native format: versioned JSON with a `.pifinder` extension.

An entry is either **catalog-keyed** (`catalog_code` + `sequence`, resolved against the local catalog DB at load time) or a **coordinate entry** (name/type/RA/Dec, with optional magnitude, extents, and epoch). Coordinates are J2000 by default; other epochs (e.g. `J2016.0`) are precessed to J2000 at read time, so everything downstream of the reader stays J2000-only. Files carry `version: 1`; readers reject anything else with a structured `PiFinderFormatError` instead of guessing.

## Considered options

- **Adopt SkySafari `.skylist` as the native format** — already PiFinder's write format, but line-oriented, has no size/epoch/structured-magnitude fields, and catalog identity must be inferred from display strings.
- **Adopt Stellarium's JSON list format** — JSON, but coordinates are formatted strings, there are no catalog keys, and there is no version field to evolve against.
- **Extend the CSV format** — flat columns scale poorly to nested data such as extent polygons and segment lists.

## Consequences

- The format is a public contract: external generators (e.g. [py-asterisms](https://github.com/mrosseel/py-asterisms)) emit it, so any change requires a version bump and a migration story.
- Catalog-keyed entries are only as portable as the receiving device's catalog DB; coordinate entries are fully self-contained.
