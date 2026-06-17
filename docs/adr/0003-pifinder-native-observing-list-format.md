# 0003: A native `.pifinder` observing-list format

PiFinder reads eight third-party observing-list formats (SkySafari, CSV, plain text, Stellarium, Autostar Tour, Argo Navis, NexTour, EQMOD Tour), but none can carry everything a PiFinder object knows: catalog keys (catalog code + sequence), structured multi-band magnitudes, size/extent geometry, and explicit coordinate epochs. Rather than stretching one of them, we define a ninth, native format: versioned JSON with a `.pifinder` extension.

An entry is either **catalog-keyed** (`catalog_code` + `sequence`, resolved against the local catalog DB at load time) or a **coordinate entry** (name/type/RA/Dec, with optional magnitude and extents). The file declares a default coordinate `epoch` (J2000 unless stated) and a coordinate entry may carry its own `epoch` to override it; all non-J2000 coordinates are precessed to J2000 at read time, so everything downstream of the reader stays J2000-only. Files carry `version: 1`; readers reject anything else with a structured `PiFinderFormatError` instead of guessing.

The writer emits catalog keys, structured magnitudes, size/extent geometry, and notes, so a round trip is lossless for those. Epoch is where the *application* and the *format* diverge: the format permits any per-object `epoch` (default J2000), but **within PiFinder everything is J2000** — the reader precesses non-J2000 inputs to J2000, and PiFinder writes J2000. Used as a standalone library, the format and its readers/writers are epoch-agnostic; J2000 normalization is PiFinder's application choice, not a limit of the format. Either way the writer is a first-class producer of the public format (a third party can consume what PiFinder emits), even though the on-device save path currently writes SkySafari `.skylist`.

## Considered options

- **Adopt SkySafari `.skylist` as the native format** — already PiFinder's write format, but line-oriented, has no size/epoch/structured-magnitude fields, and catalog identity must be inferred from display strings.
- **Adopt Stellarium's JSON list format** — JSON, but coordinates are formatted strings, there are no catalog keys, and there is no version field to evolve against.
- **Extend the CSV format** — flat columns scale poorly to nested data such as extent polygons and segment lists.

## Consequences

- The format is a public contract: external generators emit it, so any change requires a version bump and a migration story.
- Catalog-keyed entries are only as portable as the receiving device's catalog DB; coordinate entries are fully self-contained.
- The on-disk contract is documented for external generators in [`docs/ax/catalog/obslist-formats/`](../ax/catalog/obslist-formats/README.md) — JSON Schema, reference, and an example.
