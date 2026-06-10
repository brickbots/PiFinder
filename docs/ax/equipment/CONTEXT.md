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
