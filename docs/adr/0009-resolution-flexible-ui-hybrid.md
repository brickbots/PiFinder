# Resolution-flexible UI: derive geometry, hand-tune a few per-display knobs

## Context

PiFinder gained a second display panel: the NHD **SSD1333**, 176×176 px, 1.91″,
alongside the existing **SSD1351**, 128×128 px, 1.5″. The UI had been written
against 128 throughout — screens carried hardcoded pixel positions (`(0, 114)`
for the chart RA/Dec line, `[0, 13, 25, 42, 60, 76, 89]` for object-list rows,
`(64, 64)` for the align reticle centre, `image.resize((128, 128))` in the camera
preview, and so on).

The two panels have **near-identical pixel density** (128 px / 1.5″ ≈ 121 ppi;
176 px / 1.91″ ≈ 130 ppi). A glyph drawn at the same pixel count is therefore
~the same physical size on both. The product goal for the 176 panel was *not*
"the same UI, bigger" — it was **slightly larger elements** (measured by ruler,
which costs pixels spent on bigger fonts) **and slightly more content per screen**
(e.g. more menu rows). The 176 panel has ~1.34× the linear pixels to split
between those two wants. So the mechanism had to let us choose, per display, how
to spend the extra pixels — not just scale.

We considered three mechanisms:

- **(A) Uniform scale factor** — multiply every 128 coordinate by `resX/128`.
  Cheapest to apply, but it spends *all* the extra pixels on "bigger" and none on
  "more", can't add menu rows, and scaling bitmap glyphs/markers by 1.375× gives
  fractional, blurry results. It also bakes the 128 origin in permanently.
- **(B) Fully derived** — compute *everything* (including font sizes) from the
  resolution with no per-display constants. Maximally flexible, but it removes the
  hand control we explicitly want (how big is "slightly bigger"? how many rows is
  "slightly more"?), and forces the established, much-looked-at 128 layout to be
  reverse-engineered into formulas exactly or it visibly shifts.
- **(C) Hybrid** — derive *geometry* from font metrics + resolution, but keep a
  **small set of hand-tuned per-display knobs**.

## Decision

Adopt **(C), the hybrid**. Two halves:

1. **Per-display knobs** live as class attributes on the `DisplayBase` subclass
   (the *display instance*): the five font sizes, `titlebar_height`, and
   `menu_visible_items`. These are the *intent* — "fonts ~15–20 % larger, two
   extra carousel rows" — and are hand-chosen per panel (`Layout176` mixin in
   `displays.py`). They are a deliberate starting point for the physical
   ruler/readability sign-off, expected to be nudged.

2. **Everything else is geometry, derived** from those knobs plus `resolution`
   and live font metrics (`font.height`, `font.width`): row counts and positions,
   line anchors, text/marker indents, the carousel/list selection boxes, image
   scaling, zoom crops, scroll-bar edges, reticle centres. The shared maths lives
   in `ui/layout.py` (`carousel_layout`, `list_layout`); individual screens read
   `display_class.resX/resY/centerX/centerY/fov_res/titlebar_height` and font
   metrics rather than literals.

**We accept minor (≤1–2 px) drift on the existing 128 layout.** We do **not**
special-case 128 to reproduce its old pixels exactly; the derived formulas were
tuned to land within a couple of pixels of the legacy positions (e.g. the
object-list focus row moved from y=62 to y=66), which is below the threshold of
notice on the panel.

## Why the native-frame constants stay explicit

Some coordinates are not display geometry at all — they live in the **camera /
solver native frame** (documented 512×512: `target_pixel`, centroids). Those are
scaled to the display with an explicit `CAMERA_NATIVE_RES = 512` constant in the
screens that need it (`preview.py`, `align.py`), *not* folded into the resolution
knobs, because they track the camera, not the panel. The pre-existing
`SharedStateObj.target_pixel(screen_space=True)` helper is hardcoded to a 128
screen; rather than change that Positioning-context method, the UI scales the raw
native value itself.

## Consequences

- One profile (`Layout176`) is shared by the real OLED (`DisplaySSD1333`,
  `rotate=2`), the pygame emulator (`DisplayPygame_176`) and the headless dummy
  (`DisplayHeadless176`), so the dev preview faithfully matches hardware.
- Adding a future panel is a new `DisplayBase` subclass with its own knobs — no
  per-screen edits, provided screens keep reading derived geometry.
- `menu_visible_items` **must be odd** (the carousel/list focus sits on the
  symmetric centre line); this is an invariant of the layout helpers.
- The 128 layout is now defined by formulas, not literals, so it can shift by a
  pixel or two if a font metric or knob changes. That is the accepted trade for
  not maintaining two parallel layouts. Pixel-exact 128 reproduction is a
  non-goal — see `docs/ax/ui/CONTEXT.md` (term: *carousel*).
- The hand-tuned 176 font sizes are provisional until the ruler/readability
  sign-off on the physical prototype.
