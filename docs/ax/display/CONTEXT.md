# Display

Owns how PiFinder's OLED/LCD panels turn rendered pixels into light: the
brightness axes each panel exposes, the dimming policy that drives them, and
the bench photometry that measures panel light output with a camera instead of
an eyeball. Bench tooling plus the runtime brightness policy — not the UI's
layout or rendering, which belong to the UI context.

## Language

### Panels and axes

**Panel**:
A physical display module with its own controller and measured constants — the
1.91" SSD1333, the original 1.27" SSD1351, the ST7789 LCD. Constants measured
on one panel do not transfer to another.
_Avoid_: screen, display (ambiguous with the Display context itself)

**Brightness axis**:
One independently programmable control that scales a panel's light output —
e.g. contrast (0xC1), master (0xC7), gray-scale ceiling, pre-charge voltage
(0xBB). Each panel exposes its own set; the SSD1333 exposes four.
_Avoid_: register (an axis may not be a bare register — the ceiling is a
render-side LUT), knob, setting (reserved for the UI's 0-255 level)

**Drive** (drive current):
The current a lit pixel draws, fixed jointly by the contrast and master axes;
their product quantises to whole units of contrast-at-full-master.

**Drive product**:
The single variable `contrast × (master + 1)` the two current registers
reduce to: measured on the SSD1333, panel flux depends on the pair only
through this product (within 1.6 %), so the registers are one dimming axis,
not two. Lit iff the product is ≥ 4.
_Avoid_: treating contrast and master as independent brightness axes

**Pre-charge glow**:
The small constant emission of native gray level 1 — which has no current
drive at all — coming from the pre-charge stage itself at high pre-charge
codes (~1.4e3 ADU/s at code 0x17 on the SSD1333, dark by code 8). An
additive floor under dim states, tied to the pre-charge code.

**Gray scale ceiling**:
The gray level that full-intensity red is rescaled onto before reaching the
panel; dims by shortening the pulse a pixel is driven for. Costs tonal range
as it falls.
_Avoid_: LUT rewrite (a rejected, different mechanism — see ADR 0023)

**Pre-charge regime**:
The dim span of the level range where the ceiling has hit its tonal floor and
the pre-charge voltage axis carries the remaining dimming.

**Emission floor**:
The dimmest programmable state at which a panel still emits at all; below it
the panel is dark, not merely dim. Per-axis floors exist too (contrast cut-out,
pre-charge cut-out).
_Avoid_: minimum brightness (that is the policy's chosen bottom, not the
panel's physical floor)

**Tonal range**:
How many distinct shades below full intensity still render as distinct light
levels at a given brightness state. The UI's dimmest large surface (the
title-bar shade, pixel value 64) is the canary: it must stay photometrically
distinct from full intensity at every lit setting.
_Avoid_: contrast (collides with the contrast axis 0xC1)

### Dimming policy

**Level**:
The UI-facing 0-255 brightness setting a user steps through by keypress. The
policy maps level → target light via the knee curve, then target → axis values.
_Avoid_: brightness (ambiguous between level, target, and measured light)

**Knee curve**:
The dim-weighted two-regime level→light mapping: fine geometric steps per
level below the knee (the pre-charge regime), a coarser power law per keypress
above it. Field-validated shape; its constants are panel measurements.

### Bench photometry

**Photometer rig**:
The bench setup that turns the PiFinder's own camera into a photometer: the
lensless sensor ~1 cm from the panel in a dark enclosure, all stray light
sources (keypad backlight, status LEDs) doused. It integrates flux; it cannot
resolve panel pixels, so spatial artifacts stay eyeball-judged.
_Avoid_: imager, test camera

**Panel flux**:
The one unit every measurement reduces to: bias-subtracted mean raw ADU over
the sensor ROI, divided by the actual (metadata-reported) exposure time —
ADU per second. Comparable across the whole range only via the exposure
ladder.
_Avoid_: brightness value, luminance (not calibrated to SI units)

**Exposure ladder**:
The small set of fixed exposure times the rig steps through to span more
decades of panel flux than one exposure can resolve. Each measurement uses the
longest unsaturated tier.

**Tier**:
One fixed exposure time on the ladder. Within a tier, exposure never varies.

**Cross-calibration**:
Measuring the same panel state at two adjacent tiers to fix their empirical
flux ratio; nominal exposure times are never trusted for this.

**Refresh beat**:
The frame-to-frame scatter a camera exposure shorter than the panel's refresh
period picks up by sampling the panel's PWM at random phase. Nulled by
**period-locked tiers** — exposures that are integer multiples of the refresh
period, which the rig measures at every bring-up (the controller clock is an
RC oscillator: per-panel and temperature-dependent). Only the **sub-period
tier**, needed for the brightest states, keeps beat, paid for by averaging
many frames.

**Sentinel**:
A fixed dim panel state re-measured periodically through a run; its flux
moving is how thermal drift shows up in the journal. Dim so it lands on a
period-locked tier and is measured beat-free.

**Dark floor**:
The rig's reading with the panel fully off — the gate that proves the
enclosure is actually dark before a run, and the noise floor under every dim
measurement.

**Response surface**:
A panel's measured light output as a function of its brightness axes and the
rendered pixel value. The policy's model assumes the axes multiply
(**separability**); the rig tests that instead of assuming it.

**Separability**:
The property that a panel's response factors into independent per-axis curves
multiplied together. Where it fails, the response surface needs local, denser
measurement. (Measured 2026-08: the SSD1333 is *not* separable — pre-charge
authority spans 32× to 1.1× depending on drive; see `ssd1333-response.md`.)

## Flagged ambiguities

- "Brightness" alone is banned in this context: say **level** (UI setting),
  **target** (what the knee curve asks for), or **panel flux** (what the rig
  measured).
- "Contrast" means the 0xC1 axis. For lightest-vs-darkest rendering headroom,
  say **tonal range**.

## Example dialogue

> **Dev:** Setting 12 looks wrong — the title bar disappeared.
>
> **Domain expert:** That's a tonal-range regression, not a level-curve one.
> Setting 12 is inside the pre-charge regime, so the ceiling should be pinned
> at its tonal floor and the pre-charge axis doing the dimming. If the canary
> shade stopped emitting, either the ceiling fell below the floor or the
> pixel-value transfer isn't mapping in emitted-light space.
>
> **Dev:** Can the rig catch that?
>
> **Domain expert:** Yes — render the canary shade full-screen and compare its
> panel flux against full intensity at the same axis state. If they collapse
> together or the canary hits the dark floor, the tonal range is gone. But if
> the panel *smears* at that setting, the rig can't see it — no lens, no
> spatial resolution. That stays an eyeball job.
