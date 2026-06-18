# PiFinder observing-list formats

PiFinder reads observing lists in several on-disk formats and resolves each entry
against the catalog DB (see the Catalog [CONTEXT.md](../CONTEXT.md) — *Observing
lists*). This folder documents those formats well enough to **recreate** them:

- [`pifinder-list.schema.json`](./pifinder-list.schema.json) — normative JSON Schema for the native `.pifinder` format.
- [`example.pifinder`](./example.pifinder) — a small valid file exercising every feature.
- This README — the field-by-field reference.

The source of truth is the reader/writer in `python/PiFinder/obslist_formats.py`;
the design rationale is [ADR 0003](../../../adr/0003-pifinder-native-observing-list-format.md).

## Supported formats

| Format | Extension | Direction | Notes |
|---|---|---|---|
| **PiFinder (native)** | `.pifinder` | read + write | Versioned JSON; the only **lossless** format (catalog keys, structured magnitudes, size/extent geometry, epochs). Documented below. |
| SkySafari | `.skylist` | read + write | PiFinder's on-device **save** format. |
| CSV | `.csv` | read + write | Flat columns. |
| Stellarium | `.sol` | read + write | JSON; coordinates as formatted strings. |
| Autostar / Meade tour | `.txt` / `.mtf` | read + write | |
| Argo Navis | `.txt` | read + write | |
| NexTour | `.hct` | read + write | |
| EQMOD tour | `.lst` | read + write | `!J2000` epoch header. |
| Plain text | `.txt` | read + write | Names only; the fallback when content can't be sniffed. |

Format is detected by extension first, then by content sniffing; unrecognized
content degrades to plain text.

## The `.pifinder` format

A `.pifinder` file is a JSON object:

| Field | Type | Required | Description |
|---|---|---|---|
| `version` | integer | yes | Must be `1`. Readers reject any other value with a `PiFinderFormatError`. |
| `name` | string | yes | Display name of the list. |
| `epoch` | string | no (default `"J2000"`) | File-level default coordinate epoch, e.g. `"J2000"`, `"J2016.0"`. Coordinate entries inherit it unless they override it. |
| `objects` | array | yes | The entries (see below). |

Each element of `objects` is **one of two kinds**, distinguished by whether it
carries `catalog_code`.

### Catalog-keyed entry

Identifies an object by catalog code + sequence; resolved against the receiving
device's catalog DB at load time. Compact, but only as portable as that DB.

| Field | Type | Required | Description |
|---|---|---|---|
| `catalog_code` | string | yes | e.g. `"NGC"`, `"M"`, `"IC"`. |
| `sequence` | integer | yes | e.g. `224` for `NGC 224`. |
| `notes` | string | no | The object's observing-list description for this list. |

```json
{ "catalog_code": "NGC", "sequence": 7000, "notes": "North America Nebula" }
```

### Coordinate entry

Self-contained; carries its own coordinates. Used when an object is not
catalog-keyed.

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | yes | Object name. |
| `obj_type` | string | yes | Type code, e.g. `"Gx"`, `"Neb"`, `"*"`, `"?"`. |
| `ra` | number | yes | Right ascension, degrees (0–360), in the entry's effective epoch. |
| `dec` | number | yes | Declination, degrees (−90–+90). |
| `epoch` | string | no | Per-entry override of the file-level `epoch`. |
| `mag` | number **or** object | no | See *Magnitude*. |
| `extents` | object | no | See *Extents*. |
| `notes` | string | no | The object's observing-list description for this list. |

```json
{ "name": "VY Andromedae", "obj_type": "*", "ra": 6.984, "dec": 44.281, "mag": 9.7 }
```

### Epoch

Coordinates are J2000 unless an epoch says otherwise. The effective epoch of an
entry is its own `epoch` if present, else the file-level `epoch`, else `"J2000"`.
On read, non-J2000 coordinates are **precessed to J2000**, so everything
downstream of the reader is J2000.

`epoch` is a string of the form `J<year>` (`"J2000"`, `"J2016.0"`).

### Magnitude

Either a bare number, or a structured object for multi-band data:

```json
"mag": 9.7
"mag": { "mags": [8.1, 12.4], "filter_mag": 8.1 }
```

`mags` holds the raw values (numbers, or strings like `"~12"`); `filter_mag` is
the mean of the parseable ones, used for filtering.

### Extents

Angular size / shape. `shape` interpretation depends on its nesting:

| `shape` | Meaning | Units |
|---|---|---|
| `[d]` | circle, diameter `d` | arcseconds |
| `[major, minor]` | ellipse axes | arcseconds |
| `[v1, v2, …]` | radial polygon distances | arcseconds |
| `[[ra,dec], …]` | polyline vertices | degrees |
| `[[[ra,dec],[ra,dec]], …]` | disconnected segments | degrees |

Optional `position_angle` (degrees, default `0`). **A nested (RA/Dec) `shape`
requires `geometry`** — `"polyline"` or `"segments"` — to disambiguate the last
two cases; flat (arcsecond) shapes don't need it.

```json
"extents": { "shape": [[83.0, -1.0], [84.5, -3.0]], "geometry": "polyline" }
```

## Reader vs writer

The reference reader and writer are deliberately **not symmetric**:

- **Reader** — lenient and epoch-agnostic: accepts any `epoch` (precessing to
  J2000), tolerates a missing file-level `epoch` (defaults J2000), and ignores
  unknown properties.
- **Writer** — emits catalog keys, J2000 coordinates, structured magnitudes,
  size/extent geometry, and notes, so a round trip is lossless. It always stamps
  the file-level `epoch` (self-describing) and writes a per-entry `epoch` only
  when it overrides the file default. Within PiFinder everything is J2000, so the
  writer emits J2000; the format itself permits any epoch.

## Validation

The reader raises `PiFinderFormatError` for: a non-object root; a missing
`version`/`name`/`objects`; `version != 1`; a non-string `epoch`; a non-array
`objects`; a catalog entry missing `sequence`; a coordinate entry missing
`name`/`obj_type`/`ra`/`dec`; or a nested `extents.shape` without `geometry`.

## Example

See [`example.pifinder`](./example.pifinder): a catalog-keyed entry, a coordinate
entry with a bare magnitude, one with structured magnitude and polyline extents,
and one with a per-entry epoch override.
