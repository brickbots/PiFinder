# Equipment measurements are validated floats, and a rejected entry never reports success

Every numeric field on a `Telescope` or an `Eyepiece` is a **float**, and every
value entering one is range-checked against a single table of limits in
`equipment.py` before it reaches config. A value that fails re-renders the form
with the reason; it never renders the success banner.

## Context

Two defects with one root. `equipment_add_eyepiece` / `equipment_add_instrument`
parsed with bare `float()` / `int()` inside `except Exception: logger.error(...)`
and then fell through to the success template regardless
([#569](https://github.com/brickbots/PiFinder/issues/569)):

```
POST /equipment/add_eyepiece/-1  focal_length_mm=7,5
  -> HTTP 200 + "Eyepiece added, restart your PiFinder to use"
  -> eyepiece count unchanged.  Nothing was saved.
```

And the types themselves rejected real gear. `aperture_mm` and
`focal_length_mm` were `int` on `Telescope`, so an 11" SCT (279.4mm) could not
be entered — and an older release that wrote the string `"279.5"` into config
made the PiFinder **unbootable**: `Equipment.from_dict` raised
`invalid literal for int()` inside `main()` before the UI came up
([#291](https://github.com/brickbots/PiFinder/issues/291)). Meanwhile
`Eyepiece.focal_length_mm` *was* a float, so the same field name carried two
types.

A decimal comma is the easiest way to trigger the parse failure — PiFinder ships
de/es/fr/zh, and a comma-locale keyboard offers a comma — but any unreadable
value did it, including the blank instrument name from #569's description.

## Decision

1. **Measurements are floats.** `aperture_mm`, `focal_length_mm` and `afov`
   join `obstruction_perc` and `field_stop`. Optics are fractional: 279.4mm of
   aperture, 1280.2mm behind a reducer, a 3.5mm Nagler. Whole millimetres
   still *display* as whole millimetres — `format_measurement()` drops the
   `.0`, so the tables read "1000", not "1000.0". Loading only gets more
   tolerant: an int, a float or a numeric string all decode.

2. **One table of limits, two enforcement points.** `TELESCOPE_LIMITS` and
   `EYEPIECE_LIMITS` live in `equipment.py`. The edit forms render them into
   their client-side check; the API re-checks them in `telescope_from_form` /
   `eyepiece_from_form`. The client's job is fast feedback, the API's job is
   deciding what reaches config — the ranges are shared so the two can't drift.
   The ranges themselves are documented in
   [`docs/ax/equipment/CONTEXT.md`](../ax/equipment/CONTEXT.md).

3. **A failed save re-renders the form, never the success banner.** With the
   message and the values the user typed, so one bad field doesn't cost them
   the whole entry.

4. **A blank required field is an error, not a zero.** Only `obstruction_perc`
   and `field_stop` have a meaning for zero ("refractor", "unknown"), and only
   those default when left blank. The old handlers' `request.form.get(x) or "0"`
   turned every empty field into a valid-looking record.

## Considered options

- **Keep `Telescope.focal_length_mm` as an int and reject decimals with a clear
  message.** Honest, and the smallest change. Rejected: it makes the API refuse
  values that physically exist, and it leaves the same field name carrying two
  types across the two records. The display concern that motivated `int` is a
  formatting concern, and `format_measurement()` answers it directly.
- **Validate in the dataclasses' `__post_init__`.** Rejected: the records are
  also built by `from_dict` at boot, and raising there re-creates #291's
  unbootable device. Validation belongs at the write boundary — the API — with
  the loader staying permissive and falling back to defaults.
- **Client-side validation only.** Rejected outright: it is exactly what the
  system already had, and #569 is a report of it being bypassed. A `POST` from
  a script, a stale page, or any browser quirk reaches the same handler.

## Consequences

- **The config loader no longer aborts the boot.** `config.py` catches a
  malformed equipment section, logs it and falls back to the shipped defaults.
  A PiFinder with a hand-edited config comes up usable instead of not at all.
- **The DeepskyLog import obeys the same limits.** A record it can't make sense
  of is skipped and counted in the result message rather than written through
  and discovered at the next boot.
- **`Eyepiece.__str__` formats through `format_measurement()`**, so the eyepiece
  label on the object-detail screen reads "25mm Plossl" rather than
  "25.0mm Plossl".
- **The bounds are judgement calls, not physics.** 2000mm of aperture and 180°
  of AFOV are past anything an amateur owns; they exist to catch a typo or a
  mis-parse, not to police gear. Widen them if someone's real equipment doesn't
  fit — that is a bug in the limit, not in the user's telescope.
- **Existing configs are untouched.** No migration: the stored values are
  already numbers the float fields read, and nothing rewrites them until the
  user edits that record.
