# Equipment

The Equipment context models the user's optical gear — their telescopes and eyepieces — and exposes the **active** telescope and eyepiece that the rest of the system reads to compute magnification, true field of view, and the orientation of the object-detail image. Persisted in config under `equipment`; reached at runtime via `config_object.equipment`.

> Companion architecture doc: [`../equipment.md`](../equipment.md) (planned). Orientation decision recorded in [`../../adr/0003-object-image-orientation.md`](../../adr/0003-object-image-orientation.md).

## Language

### Equipment records

**Equipment**:
The container holding the user's telescopes, eyepieces, and which of each is active. One per config, reached via `config_object.equipment`. Owns the active-selection state and the optics calculations.
_Avoid_: gear, kit, instruments (collectively).

**Telescope**:
A configured optical instrument: make, name, aperture, focal length, central obstruction, mount type, image-orientation flags (**flip**/**flop**), and arrow-reversal flags. Defined in `equipment.py`.
_Avoid_: scope (overloaded — see Flagged ambiguities and ADR 0001), OTA, instrument.

**Eyepiece**:
A configured ocular: focal length, apparent field of view, field stop. Paired with the active telescope to derive magnification and true field.
_Avoid_: ocular, EP.

**Active telescope** / **active eyepiece**:
The single telescope / eyepiece currently selected for calculations and display. Exposed as `active_telescope` / `active_eyepiece`; **either is `None`** when nothing is selected.
_Avoid_: selected scope, current telescope, default telescope.

### Image orientation

**Flip** (`flip_image`):
A top-to-bottom (vertical) mirror of the displayed object image, modelling a vertical mirroring in the optical train.
_Avoid_: "vertical flip" used loosely, invert, rotate (a flip is a mirror, not a rotation).

**Flop** (`flop_image`):
A left-to-right (horizontal) mirror of the displayed object image.
_Avoid_: "mirror" unqualified (state the axis), horizontal rotate.

**Parity**:
Whether the optical train mirrors the image (reverses handedness). Set by the number of reflections: **even** (Newtonian, straight refractor) = non-mirrored; **odd** (anything with a star diagonal) = mirrored. Decides whether *any* flip/flop is needed — refractor-vs-reflector is irrelevant, reflection count is what matters.
_Avoid_: handedness, chirality (fine in prose; the term is "parity"), orientation (too broad).

**Baseline rotation**:
The fixed 180° rotation applied to the object image before flip/flop, combined with the live solve **roll**. Correct on its own for the common non-mirrored (Newtonian / straight-refractor) view; flip/flop are applied *after* it. Rationale in ADR 0003.
_Avoid_: newtonian rotation, default rotation.

### Optical calculations

**Magnification**:
Active telescope focal length ÷ active eyepiece focal length. `calc_magnification()`.
_Avoid_: power, zoom.

**True field of view** (**TFOV**):
The actual angular field seen through the active telescope + eyepiece — eyepiece AFOV ÷ magnification. `calc_tfov()`. Drives the crop/scale of the object image.
_Avoid_: FOV (unqualified), field.

**Apparent field of view** (**AFOV**):
The eyepiece's own angular field — a property of the eyepiece, independent of the telescope.
_Avoid_: FOV (unqualified).

### Navigation

**Reverse arrow A / B** (`reverse_arrow_a` / `reverse_arrow_b`):
Per-telescope flags that invert push-to chart arrow directions to match how the observer reads their eyepiece/finder. These orient the *arrows*, never the *image*.
_Avoid_: flip arrows, mirror arrows.

### Field rules

**Measurement**:
Any numeric field on a telescope or eyepiece — aperture, focal length, obstruction, AFOV, field stop. All measurements are **floats**: real optics are fractional (a 11" SCT is 279.4mm, a focal reducer turns 2032mm into 1280.2mm). Rendered for display through `format_measurement()`, which drops a meaningless `.0`.
_Avoid_: dimension, spec, number.

**Limits**:
The inclusive `(minimum, maximum)` range a measurement may take, declared once in `equipment.py` (`TELESCOPE_LIMITS`, `EYEPIECE_LIMITS`). The edit form renders them into its client-side check and the API re-checks them; neither is the sole authority, but the API is the one that decides what reaches config.
_Avoid_: bounds, constraints, validation rules (as a name for the table).

The rules the two forms and the API enforce:

| Record | Field | Required | Range | Notes |
| --- | --- | --- | --- | --- |
| Telescope | `make` | no | ≤ 64 chars | Free text, stripped. |
| | `name` | **yes** | ≤ 64 chars | Blank names read as an empty row in the menu and the tables. |
| | `aperture_mm` | yes | 1 – 2000 | |
| | `focal_length_mm` | yes | 1 – 20000 | Zero would make magnification zero. |
| | `obstruction_perc` | no (0) | 0 – 100 | A percentage; a refractor is 0. |
| | `mount_type` | yes | `alt/az` \| `equatorial` | Anything else has no meaning. |
| Eyepiece | `make` | no | ≤ 64 chars | |
| | `name` | **yes** | ≤ 64 chars | |
| | `focal_length_mm` | yes | 0.1 – 100 | `calc_magnification` divides by it, so never 0. |
| | `afov` | yes | 1 – 180 | Degrees. |
| | `field_stop` | no (0) | 0 – 100 | 0 means unknown — TFOV falls back to AFOV ÷ magnification. |

Two rules that are not about ranges:

- **A blank field is not a zero.** An empty required measurement is an error, never silently `0`. Only `obstruction_perc` and `field_stop` have a documented zero meaning, and only those default when left blank.
- **A rejected entry never reports success.** The handler re-renders the form with the message and the values the user typed. This is the defect [#569](https://github.com/brickbots/PiFinder/issues/569) was raised for: the old handlers logged the failure and rendered "Eyepiece added" anyway.

Recorded in [ADR 0033](../../adr/0033-equipment-measurements-are-validated-floats.md).

### Boundary terms

- **Roll** — the camera roll from the latest plate-solve, owned by [Positioning](../positioning/CONTEXT.md); the object-image baseline rotation consumes it.
- **Object image** — the POSS/SDSS survey image on the object-detail screen; the one surface flip/flop orient. The image files belong to [Catalog](../catalog/CONTEXT.md); Equipment only supplies the orientation/scale inputs.
- **Live camera preview** — the real-time camera frame; oriented by the physical optics, **not** by flip/flop. Owned by the camera/preview UI.

## Flagged ambiguities

- **"Scope"** — avoid entirely. ADR 0001 established that "scope" is overloaded (telescope, eyepiece, finder, optical). Say **telescope** for the instrument and **active telescope** for the selected one.
- **"Flip" vs "flop"** — flip = top-bottom (vertical) mirror; flop = left-right (horizontal) mirror. Never say "mirror" or "flip" without naming the axis.
- **"Field of view"** — always qualify: **AFOV** is the eyepiece's; **TFOV** is what telescope + eyepiece actually show.
- **Image orientation vs arrow reversal** — flip/flop orient the *displayed image*; `reverse_arrow_*` orient *push-to arrows*. Different concerns; don't conflate.

## Example dialogue

> **Dev:** My refractor has a star diagonal — do I set flip or flop?
>
> **Domain:** A diagonal adds one reflection, so the parity is odd — you need exactly one mirror. The baseline 180° already gives the correct non-mirrored view; the diagonal makes your eyepiece mirrored, so set whichever of flip/flop makes the object image match what you see. Which one depends on how the diagonal is clocked in the focuser.
>
> **Dev:** And a plain Dobsonian?
>
> **Domain:** Even parity — two reflections, non-mirrored, just rotated 180°. The baseline rotation already covers it, so flip and flop both stay off. If a Dob image looks mirrored, that's the old bad default value; clear flop.
