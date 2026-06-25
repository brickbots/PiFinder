# Context Map

PiFinder is a multi-process Raspberry Pi finder/plate-solver. These contexts each own a distinct slice of the runtime and have their own vocabulary.

## Contexts

- [Catalog](./docs/ax/catalog/CONTEXT.md) — loads, filters, searches astronomical catalogs (M, NGC, IC, WDS, planets, comets) for the UI.
- [Positioning](./docs/ax/positioning/CONTEXT.md) — acquires telescope pointing via plate-solving and IMU dead-reckoning; publishes the canonical "where am I looking?" answer.
- [SQM](./docs/ax/sqm/CONTEXT.md) — estimates sky brightness in mag/arcsec² from solved frames; also produces the noise-floor signal auto-exposure consumes.
- [Equipment](./docs/ax/equipment/CONTEXT.md) — models the user's telescopes and eyepieces; supplies the active optics that drive magnification, true field of view, and object-image orientation.
- [UI](./docs/ax/ui/CONTEXT.md) — the on-device menu system: menu tree, screen modules, the navigation stack and key dispatch, marking menus.
- [Camera](./docs/ax/camera/CONTEXT.md) — captures frames and decides exposure: the three exposure regimes, the auto-exposure controllers, and zero-match recovery.

The remaining contexts own the platform lifecycle rather than a slice of the runtime — how a PiFinder is built, converted, and updated:

- [Migration](./docs/ax/migration/CONTEXT.md) — the one-time, on-device conversion of a deployed Raspberry Pi OS PiFinder to NixOS; reflashes the SD card in place and hands off to NixOS.
- NixOS — how a NixOS PiFinder is built, published, and updated over the air (binary cache, release channels, on-device upgrade). Lives at `docs/ax/nixos/CONTEXT.md`, added by PR #379.

## Relationships

- **Positioning → Catalog**: Catalog reads RA/Dec/Alt/Az from `shared_state.solution()` to compute visibility and "near me" lists.
- **Positioning → SQM**: SQM is a side effect of every successful plate solve in the solver process; it reuses the tetra3 `matched_centroids` and the camera frame.
- **SQM → Camera**: `shared_state.set_noise_floor()` feeds the minimum acceptable background used by the Camera context's background controller.
- **Positioning → Camera**: `Matches` is published on every solve attempt (success or failure) as the feedback signal for solver-driven auto-exposure.
- **Catalog ↔ Positioning**: Catalog supplies the `(RA, Dec)` target for the alignment flow that calibrates `solve_pixel` in Positioning.
- **Equipment → Catalog**: the active telescope's flip/flop flags and the active eyepiece's true field of view orient and scale the POSS/SDSS object image in `cat_images.get_display_image`.
- **Positioning → Equipment**: the object-image baseline rotation combines the active telescope's flip/flop with the live solve **roll** from `shared_state` (see [ADR 0003](./docs/adr/0003-object-image-orientation.md)).
- **NixOS → Migration**: a release cuts two sibling artifacts from one closure — Migration consumes the **migration tarball** (`pifinder-migration-vX.Y.Z.tar.zst`); a fresh card is flashed from the **SD image** (`pifinder-vX.Y.Z.img.zst`).
- **Migration → NixOS**: once a device is reflashed, Migration is done forever; every later update is a NixOS **system update** through the release channels.

Companion architecture docs live next to each `CONTEXT.md`:
- [`docs/ax/catalog.md`](./docs/ax/catalog.md)
- [`docs/ax/positioning.md`](./docs/ax/positioning.md)
- [`docs/ax/sqm.md`](./docs/ax/sqm.md)
- [`docs/ax/equipment.md`](./docs/ax/equipment.md)
- [`docs/ax/ui.md`](./docs/ax/ui.md)
- [`docs/ax/camera.md`](./docs/ax/camera.md)
- [`docs/ax/migration.md`](./docs/ax/migration.md)
