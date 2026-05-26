# Object-detail image orientation: `rotate(180 + roll)` then flip/flop

The object-details survey image is oriented to match what the observer sees in the eyepiece. POSS plates are stored in naked-eye / true-sky orientation (North up, East left), so we keep the existing fixed `rotate(180 + roll)` as the baseline — correct for the dominant, parity-preserving Newtonian / straight-refractor case — and apply the active telescope's `flip_image` (top-bottom mirror) and `flop_image` (left-right mirror) as **additional single-mirror transposes after the rotation**. Mirroring after the rotation is the physically correct order: a mirror reverses the apparent sense of roll, which is exactly what a real star-diagonal eyepiece does.

## Considered Options

- **Re-express the 180° as `flip + flop` and drop the hard-coded rotation.** Rejected: a 180° rotation equals `flip + flop`, so this would force the common Newtonian/Dobsonian to set *both* flags, breaking the "an unconfigured Dob needs no flags" property and every shipped and saved default. Keeping the rotation lets the dominant case need zero flags.
- **Apply flip/flop *before* the roll rotation.** Rejected: it leaves mirrored scopes rotating the wrong way during live solves. A mirror does not commute with an arbitrary rotation — it passes through it and flips the sign: `M · R(180 + roll) = R(180 − roll) · M`. That sign reversal is the real behavior of a mirrored eyepiece, and it only falls out for free if the mirror is applied last.

## Consequences

- **Parity model (count reflections, not refractor-vs-reflector):** even reflections (Newtonian, straight refractor) → rotated, non-mirrored → both flags false; odd reflections (anything with a star diagonal) → mirror image → exactly one flag set. Which flag depends on diagonal clocking; the user toggles whichever matches their eyepiece.
- **No active telescope** (`active_telescope is None`) → no mirror (`flip = flop = false`), i.e. unchanged from today's behavior.
- The shipped default "Generic Dobsonian" carried `flop_image = true`, which is wrong (a Newtonian needs neither flag). `default_config.json` is corrected, and a post-update migration repairs persisted user configs — see `pifinder_post_update.sh`.
- Applied **only** to the object-details survey image (`cat_images.get_display_image`). The live camera preview and the push-to arrow flags (`reverse_arrow_*`) are intentionally unaffected.
- Companion glossary: [`docs/ax/equipment/CONTEXT.md`](../ax/equipment/CONTEXT.md).
