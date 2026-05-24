# Context Map

PiFinder is a multi-process Raspberry Pi finder/plate-solver. These contexts each own a distinct slice of the runtime and have their own vocabulary.

## Contexts

- [Catalog](./docs/ax/catalog/CONTEXT.md) — loads, filters, searches astronomical catalogs (M, NGC, IC, WDS, planets, comets) for the UI.
- [Positioning](./docs/ax/positioning/CONTEXT.md) — acquires telescope pointing via plate-solving and IMU dead-reckoning; publishes the canonical "where am I looking?" answer.
- [SQM](./docs/ax/sqm/CONTEXT.md) — estimates sky brightness in mag/arcsec² from solved frames; also produces the noise-floor signal auto-exposure consumes.

## Relationships

- **Positioning → Catalog**: Catalog reads RA/Dec/Alt/Az from `shared_state.solution()` to compute visibility and "near me" lists.
- **Positioning → SQM**: SQM is a side effect of every successful plate solve in the solver process; it reuses the tetra3 `matched_centroids` and the camera frame.
- **SQM → Camera (auto-exposure)**: `shared_state.set_noise_floor()` feeds the SNR target used by auto-exposure in the camera process.
- **Catalog ↔ Positioning**: Catalog supplies the `(RA, Dec)` target for the alignment flow that calibrates `solve_pixel` in Positioning.

Companion architecture docs live next to each `CONTEXT.md`:
- [`docs/ax/catalog.md`](./docs/ax/catalog.md)
- [`docs/ax/positioning.md`](./docs/ax/positioning.md)
- [`docs/ax/sqm.md`](./docs/ax/sqm.md)
