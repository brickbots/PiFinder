# Plan: FOV gate width follows lens confidence (2.6.2)

Decisions taken in the grilling session are recorded in
[ADR 0029](docs/adr/0029-fov-gate-width-follows-lens-confidence.md); the
vocabulary is in `docs/ax/camera/CONTEXT.md` (**stated lens** / **assumed
lens**) and `docs/ax/positioning/CONTEXT.md` (**FOV gate**, **fitted FOV**).
This file is the implementation checklist.

## What was dropped, and why

- **`camera_lens` in `default_config.json`.** Already unnecessary: the 16 mm
  default exists per-sensor as `CameraProfile.default_lens_key`, which is
  `16mm` for imx296/imx462/imx290. Adding the key would break hq units —
  `Config.get_option` consults the default file before `resolve_lens` ever
  sees a `None`, so hq would derive 17.12° instead of its true 10.33°.
- **A rev4 → 12 mm config migration.** Rev4 reports as `imx462` and so do some
  v3 units, so the sensor is not the predicate; the board is probeable
  (BQ25895 at 0x6A) but board revision is not the fact we need — *which lens
  was in the box* is, and not all rev4s shipped with the 12 mm. It would fix
  most units by breaking the rest.

## Code changes

### 1. `python/PiFinder/camera_profiles.py` — record every shipped lens

Add alongside `default_lens_key`:

```python
# Every lens this sensor has shipped with. The assumed-lens FOV gate spans
# all of them, so this is the set of lenses a unit with no stated lens can
# still solve on. default_lens_key must be one of these.
shipped_lens_keys: Tuple[str, ...] = ()
```

- imx296, imx462, imx290 → `("16mm", "12mm")`
- hq → `("25mm",)`

Keep `default_lens_key` as-is — it is now specifically *the lens to assume*,
which is a narrower job than the docstring's "the lens this sensor ships
with" now that two lenses ship. Update that docstring accordingly, and assert
the invariant `default_lens_key in shipped_lens_keys` in a unit test rather
than at import.

### 2. `python/PiFinder/optics.py` — separate stated from assumed

```python
def lens_is_stated(lens_key: Optional[str]) -> bool:
    """True when config names a lens we recognise — a claim, not a fallback."""
    return bool(lens_key) and lens_key in LENSES
```

`resolve_lens` keeps its signature (only two callers, but no reason to churn
them). `OpticalTrain` gains `lens_stated: bool = False`, set by
`optical_train_for_profile` from `lens_is_stated(lens_key)`.

`solver_fov_params()` branches:

```python
def solver_fov_params(self) -> Tuple[float, float]:
    if self.lens_stated:
        fov = self.fov_degrees
        return fov, fov * FOV_GATE_MARGIN
    # Assumed: nothing has been claimed, so span every lens this sensor
    # shipped with. tetra3's window is symmetric, so re-centre the union.
    bounds = [
        OpticalTrain(self.profile, get_lens(k), lens_stated=True).fov_degrees
        for k in self.profile.shipped_lens_keys or (self.lens.key,)
    ]
    low = min(b * (1 - FOV_GATE_MARGIN) for b in bounds)
    high = max(b * (1 + FOV_GATE_MARGIN) for b in bounds)
    return (low + high) / 2, (high - low) / 2
```

**`fov_degrees` must not change.** SQM's solid angle and the chart frustum
keep using the assumed lens's field of view; only the *gate* widens. Those
stay approximate until self-heal corrects the lens, which is the point of
self-heal.

### 3. `python/PiFinder/integrator.py` — self-heal

The integrator is the right home: it already holds a `Config` (line 88) and a
`shared_state`, it sees every `SuccessfulSolve` with its diagnostics, and it
is not the solver's hot loop. `SharedStateObj.set_camera_lens` already exists
and its docstring already promises exactly this ("publish a lens change so the
solver picks it up on the next frame").

On each successful solve:

1. Skip unless the lens is **assumed** (`lens_is_stated(shared_state.camera_lens())`
   is false). A stated lens is never overwritten.
2. Skip unless `diagnostics.FOV` is present.
3. Identify: nearest lens **among `profile.shipped_lens_keys` only** by
   relative error against its derived field of view. Restricting to shipped
   keys is self-consistent — those are the only lenses the assumed gate could
   have admitted a solve for.
4. Accept only within **5%**. tetra3 fits the FOV to well under a percent, and
   the imx462's candidates are 13.51° and 10.40° — a 30% separation — so 5% is
   generous without being ambiguous. Outside 5%, log once and leave it
   assumed (third-party lens).
5. Require **3 consecutive agreeing identifications** before writing. Cheap
   insurance against a single rogue fit; costs about three frames.
6. Write: `cfg.load_config()` (the integrator's dict is loaded at process
   start and `dump_config` rewrites the whole file — reload first so a menu
   change made since startup is not clobbered), then
   `cfg.set_option("camera_lens", key)`, then `shared_state.set_camera_lens(key)`.
   Log at INFO with both the fitted and derived figures.

tetra3's `match_threshold` is *not* a sufficient guard on its own — with
injected noise it accepted confident false solves at 20–23°. What rejects
those is the FOV gate's upper bound, which the assumed gate keeps (see ADR
0029). This is an argument for the union gate over no hint at all; it does not
change self-heal, whose input is an already-successful solve.

#### Interaction with tetra3's pattern cache — check this, don't assume it

`Tetra3._pattern_cache` (`tetra3.py:2255`) is keyed on `hash_index` alone but
stores the **FOV-pruned** result (pruning happens at `tetra3.py:2271`, inside
the cached function). It is created once at `Tetra3.__init__` (`tetra3.py:407`)
and **never cleared** — there is no invalidation path in tetra3 or in
PiFinder, only LRU eviction. PiFinder holds one long-lived `Tetra3` across
lens changes.

For self-heal this is the **safe direction**: promotion goes assumed (wide) →
stated (tight), so cached entries were pruned under the *wider* window and are
a superset of what the tighter one wants. Over-permissive costs a little
speed, and the post-fit rejection at `tetra3.py:1953` still enforces the tight
window. Nothing is wrongly accepted.

The unsafe direction is tight → different-tight, i.e. **a user changing the
lens in the Lens menu**. Cached entries pruned for the old window can exclude
patterns the new one needs, so the change may not fully take effect. This was
a pre-existing 2.6.2 bug rather than one this change introduces, and it is
**already fixed on its own branch — PR #625**, which makes
`callbacks.set_camera_lens` restart the service the way the neighbouring
PiFinder Type and Camera Type settings do. Nothing further is needed here;
just do not be surprised to find `set_camera_lens` already restarting.

The upstream cache bug itself remains and is out of scope for both PRs: the
cached value also depends on the per-frame `image_pattern_largest_edge`, so
the cache is approximate across frames even under a fixed gate.

### 4. `python/PiFinder/api_extensions.py:465` — comment fix

The comment says the frustum "follows the fitted optical train" but the code
uses the **derived** train (`_API_OPTICAL_TRAIN.resolve(...).fov_degrees`).
`docs/ax/positioning/CONTEXT.md` reserves *fitted* for tetra3's measurement.
Say "derived".

## Tests

- `test_optics.py`: assumed-lens gate bounds per sensor against the table in
  ADR 0029; stated-lens gate unchanged at ±15%; `fov_degrees` unchanged in
  both cases; `lens_is_stated` for `None`, `""`, a known key, an unknown key.
- `test_camera_profiles.py`: `default_lens_key in shipped_lens_keys` for every
  profile.
- New integrator/self-heal test: writes on 3 agreeing solves; does not write
  on 2; never writes when the lens is stated; does not write when the fitted
  FOV is >5% from every shipped lens; reloads config before writing.
- Regression guard: an imx462 with no stated lens admits a 13.51° frame (the
  bug), and an hq with no stated lens has an unchanged gate.

## Docs

- ADR 0029 — written.
- `docs/ax/camera/CONTEXT.md`, `docs/ax/positioning/CONTEXT.md` — written.
- `release_notes/2.6.2.md` — add the fix. It must say plainly that rev4 units
  which stopped solving on 2.6.2 recover automatically, and that the Lens
  setting still exists for anyone who wants to state it.
- `docs/source/troubleshooting.rst` — the "changed lens → no solves" path
  (#613), now narrower: self-heal covers the never-stated case, so the doc is
  for users who stated a lens and then changed the glass.
- `docs/source/BOM.rst:96` still says "something fast with a 10deg FOV is
  ideal", which is imx462-specific (#613).

## Release mechanics

`origin/release` is `origin/main` plus one commit (`b485e3be`) that reverts
`version.txt` to `2.6.1` to hold the update back. Nothing has shipped. When
this lands on `main` and is promoted, `version.txt` on `release` goes back to
`2.6.2` — that revert is the thing currently gating every device, so it is the
last step, and `ui/software.py:245` compares against `release/version.txt`.

No `migration_source/v2.6.2.sh` is needed: self-heal is in-app.
