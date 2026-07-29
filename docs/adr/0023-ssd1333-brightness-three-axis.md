# SSD1333 brightness dims by capping rendered pixel values, not by rewriting the gray scale LUT

`DisplaySSD1333.set_brightness` drives the 1.91" panel with three settings that multiply together, not the two the SSD1351 uses. Two are registers fixing the **drive current** a lit pixel draws — per-channel **contrast** (0xC1) and **master brightness** (0xC7, scaling current by `(master + 1) / 16`). The third is the **gray scale ceiling**: the gray level that full-intensity red is rescaled onto before it reaches the panel, which fixes how *long* the pixel draws that current for. The controller's built-in linear LUT makes gray level *n* a pulse `(n - 1) * 4` DCLKs wide, so capping at level 2 is a 30x reduction in duty cycle.

Every constant below is measured on hardware, not derived from the datasheet.

## Why a third axis exists at all

The two current registers cannot dim this panel far enough on their own, for two compounding reasons.

Their product `contrast * (master + 1)` is always a whole number, so current-only brightness quantises to `n/16` of a contrast unit. And the panel stops emitting entirely below `contrast = 4` at `master = 0` — measured, and it stays dark however the two registers are arranged to reach the same current. So `MIN_DRIVE = 4/16` is a hard floor with **nothing reachable between `3/16` and `4/16`**.

That floor is far brighter than this display gets used at. A red night-vision panel at a dark site wants to sit near the bottom of its range; the current registers alone bottom out at about 0.16% of full, which reads as "still too bright" in the field.

Duty cycle is the way under it. Because the pixel still turns fully on and simply turns off sooner, there is no turn-on knee to fall off — gray level 2 (a 4 DCLK pulse) is still clearly visible where any comparable reduction in current is not. Measured floor: gray level 1 is dark, matching the datasheet note that level 1 has only a pre-charge stage and no current drive at all.

## Considered options

- **Cap rendered pixel values, leaving the built-in LUT alone (chosen).** luma packs red as `r & 0xF8`, so a red byte of `8n` selects gray level `n` directly. `ssd1333.gray_scale_ceiling` installs a PIL point table that rescales pixels on their way to the panel, and `display()` applies it. Clean at every level down to the floor.
- **Rewrite the gray scale tables (0xB8/0xBC/0xBD) to shorten the pulses directly.** Rejected on measurement. The tables' entries must increase strictly, which floors the top level at 30 of 120 DCLKs and caps this route at ~4x — but worse, it produced visible artifacts from about 60 DCLKs down, well before that floor. The decisive comparison: a 60 DCLK pulse reached by *rewriting the table* artifacts, while the same 60 DCLK pulse reached by *capping pixel values into the stock table* is clean. So the artifacts belong to the rewritten table, not to short pulses, and the LUT stays untouched.
- **Lower the pre-charge voltage (0xBB).** A real fourth axis — the panel dims with it and goes dark between 0x05 and 0x00 — but the gray scale ceiling already reaches the emission floor, so this would buy range that cannot be used. Left at its init value.

## Consequences

- **Dimming below `MIN_DRIVE` costs UI tonal range.** The UI's shades land on the levels *below* the ceiling, so a ceiling of 7 leaves seven distinct shades for text and chart shading. `set_brightness` therefore holds the ceiling as high as the target allows and only pulls it down once drive current alone cannot reach the target. Every setting at or above 0.35% of full renders at the full 31 levels; the ceiling only falls under 16 below 0.16% of full, and under 8 below 0.07%.
- **`DIM_DRIVE` sits at twice the floor rather than on it.** When the ceiling is doing the dimming, aiming drive slightly above its floor leaves the contrast register room to interpolate between ceiling steps, which are coarse down there. Worth about a third off the largest jump between adjacent brightness settings.
- **Rendering costs ~0.5 ms per frame while dimmed.** The point table is applied in `ssd1333.display`. At the full ceiling it is `None` and rendering is a true pass-through, so normal brightness pays nothing.
- **Adjustment steps are coarser than a two-register driver's: about 23% per keypress, against 5-19% before.** This is not tunable away. The UI adjusts brightness by a percentage of the current level and takes ~45 presses to cross its range, so covering the resulting 13400:1 span costs at least 19% per press. `GAMMA` is set to 2.5 for that reason: shallower cannot reach `MIN_BRIGHTNESS` at level 1 and strands the dim settings, steeper starts repeating brightnesses on adjacent levels.
- **Full level is held to 70% of available current (`MAX_BRIGHTNESS`).** Measured: the top of the range blooms, bright pixels smearing into neighbours. Blooming tracks total current rather than the contrast register value — contrast 160 paired with a mid master is clean — so the cap is on brightness, and the contrast register is still free to reach its own 160 ceiling at lower master values.
- **These constants are panel measurements and do not transfer.** A different 1.91" panel, or a supplier change, invalidates `MIN_CONTRAST`, `MAX_CONTRAST`, `MAX_BRIGHTNESS` and `MIN_GRAY_SCALE_LEVEL` alike. Re-measuring means sweeping each axis on hardware and watching the screen; there is no way to derive them.
- The SSD1351 path is untouched and still passes its 0-255 level through to the two current registers.
