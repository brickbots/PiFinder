# The alignment point belongs to the telescope

Each `Telescope` record keeps its own **target pixel** — the `(Y, X)` camera
pixel at the centre of its eyepiece. Selecting a telescope selects its
alignment. A telescope that has never been aligned falls back to the global
`Config["target_pixel"]`, so an upgrade changes nothing until the user aligns.

## Context

The target pixel measures how the PiFinder sits on one particular telescope:
which way the finder bracket points relative to that telescope's optical axis.
It was a single global config key. A user who moves their PiFinder between a
Dobsonian and a refractor had to re-align every time they switched, even though
the Equipment menu already knew which telescope was in use. The value was
already per-telescope in fact; only the storage was global.

## Decision

1. **The point is a field on `Telescope`**: `target_pixel: Optional[list[float]]`,
   default `None` ("never aligned"). It is saved and loaded with the rest of the
   equipment section and is deleted with its telescope.

2. **One resolver decides which point applies**: `Config.active_target_pixel()`
   returns the active telescope's point, else the global `target_pixel`, else
   the image centre `(256, 256)`. `Config.save_target_pixel()` writes to the
   active telescope, or to the global key when no telescope is selected. Every
   alignment screen and the boot-time `SharedStateObj` go through these two.

3. **Unaligned telescopes fall back to the global point; there is no
   migration.** The global key keeps its old meaning, the point every telescope
   used before, so each telescope behaves as it did until it is aligned on its
   own. The shipped default telescope in `default_config.json` has no point of
   its own either, so a new unit and an upgraded one follow the same path.

4. **The field is excluded from equality** (`field(compare=False)`). Telescopes
   are found by value: `set_active_telescope` uses `telescopes.index()`, the
   device menu tests `value in selected_values`, the DeepskyLog import checks
   for duplicates, and the web add form matches an existing record. After a
   `reload_config` the device menu still holds the records it was built from;
   if the point took part in equality, re-selecting a telescope aligned since
   then would raise `ValueError`.

5. **Changing the active telescope pushes its point to `shared_state`**, which
   the solver reads on every solve: the Telescope menu's `post_callback`
   (`callbacks.apply_target_pixel`) on the device, and the `reload_config`
   handler in `main.py` for the web page. The switch is silent.

## Considered options

- **A separate map in config, keyed by telescope index or name.** Rejected: an
  index shifts when a telescope above it is deleted, and names are neither
  required to be unique nor stable across an edit. A field on the record moves,
  edits and deletes with it for free.
- **Seed every existing telescope with the global point on upgrade.** Same
  visible behaviour as the fallback, but it rewrites every user's config,
  makes "never aligned" indistinguishable from "aligned to the old point",
  and would have to be repeated for telescopes added later.
- **Fall back to the image centre.** Cleaner, but every telescope would lose
  its alignment on upgrade.
- **Give the default telescope in `default_config.json` a point.** It would be
  `(256, 256)` — the global default already. And `load_config` re-uses the
  default telescope list when the saved one is empty or cannot be decoded; a
  point there would reset the user's global alignment to the centre in exactly
  those recovery paths.

## Consequences

- **Load stays tolerant (ADR 0033).** A stored point that is not a usable
  pixel — wrong shape, not numbers, a bool, NaN/inf, or off the 512×512
  frame — is dropped with a warning before `Equipment.from_dict` runs. That
  telescope falls back to the global point, rather than the decode failing
  and every telescope and eyepiece being replaced with the shipped defaults.
- **A web edit keeps the point.** The instrument form has no alignment field;
  `server.replace_telescope` carries the old record's point onto the edited one.
- **The web page does not show or reset alignment.** Alignment is done on the
  device, and the point is not something a user can usefully type.
- **The global `target_pixel` remains** as the fallback and as the point used
  with no telescope selected. That state is rare in practice: `load_config`
  restores the default telescope when the list is empty, and an
  `active_telescope_index` of `-1` selects the last telescope.
- **Deleting a telescope keeps the active one.** The active telescope is
  stored by index, and the web delete route used a bare `pop`, so deleting a
  telescope listed above it selected a different one. That only swapped
  flip/flop before; with this change it would also move the alignment point.
  `Equipment.remove_telescope` now re-finds the active record (by identity,
  because equality ignores the point); deleting the active telescope itself
  selects the first one.
- **Alignment needs every process's save to survive.** Each process holds its
  own `Config`, and saving used to write that whole boot-time copy back, so
  the camera process saving an exposure reverted an alignment saved by the
  UI. That was already true of the global key; it is fixed separately in
  [ADR 0048](0048-config-saves-write-only-their-own-keys.md).
- **The Align screen starts from the active telescope's point.** It is
  preloaded once, so align mode re-reads the point on entry and clears any
  star left from an earlier alignment; otherwise SQUARE could re-align on
  that old star onto the telescope now active.
- **Between a switch and the next solve**, the IMU-only estimate still uses the
  old point; `q_cam2aligned` is re-derived on the next solve, so no reset is
  needed.
