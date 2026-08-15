# SSD1333 brightness dims by capping rendered pixel values, not by rewriting the gray scale LUT

*Revised 2026-08: the policy's model was refit from rig photometry
(`docs/ax/display/ssd1333-response.md`, stage-3 calibration and verification
journals in `docs/ax/display/measurements/ssd1333/`). The decisions in this
document stand; the by-eye measured claims the original recorded were partly
falsified by the rig and are corrected here.*

`DisplaySSD1333.set_brightness` drives the 1.91" panel through three measured
dimming axes. Two current registers — per-channel **contrast** (0xC1) and
**master brightness** (0xC7) — are photometrically a single axis, the **drive
product** `contrast × (master + 1)`: panel flux depends on the pair only
through that product (within 1.6%). The **gray scale ceiling** — the gray
level full-intensity red is rescaled onto before it reaches the panel — fixes
how *long* a lit pixel draws its current: the controller's built-in linear LUT
makes gray level *n* a pulse `(n − 1) × 4` DCLKs wide. The **pre-charge
voltage** (0xBB) sets the pixel's starting voltage, which dominates the light
of weakly driven pixels (32× authority at the drive floor) and vanishes
against strongly driven ones (1.3× at reference drive).

That last number is why the policy no longer models the axes as multiplying:
**the response surface is not separable**, and each axis's response is only
trustworthy on the slice it was measured on. The policy therefore walks three
measured response tables — one per regime — instead of factoring a target
into per-axis multipliers.

## Why dimming needs more than the current registers

The current registers cannot dim this panel far enough on their own. Their
product is quantised to whole numbers, and the panel stops emitting entirely
below a drive product of 4 — measured, and it stays dark however the two
registers are arranged to reach the same product. Worse than the quantisation
is the response: the drive floor still emits **28.5% of reference flux** (the
original estimate here, "about 0.16% of full", was off by two orders of
magnitude — the flux response is a cliff at the cut-out, nearly flat to a
product of ~32, and only ≈ √product above ~128, so the whole 640× register
range buys just 6.9× of light). A red night-vision panel at a dark site wants
to sit orders of magnitude below that.

Duty cycle is the way under it. Because the pixel still turns fully on and
simply turns off sooner, gray level 2 (a 4 DCLK pulse) is still clearly
visible where any comparable reduction in current is not. And below what the
ceiling can reach without destroying tonal range, the pre-charge voltage —
in exactly the weak-drive corner where it has real authority — carries the
range down to the panel's emission floor.

## Considered options

- **Cap rendered pixel values, leaving the built-in LUT alone (chosen).**
  luma packs red as `r & 0xF8`, so a red byte of `8n` selects gray level *n*
  directly. `ssd1333.gray_scale_ceiling` installs a PIL point table that
  rescales pixels on their way to the panel, and `display()` applies it.
  Clean at every level down to the floor. The rescale must work in
  **emitted-light space**: level *n* emits in proportion to `n − 1`, not *n*,
  so a pixel whose native level is *n* maps under ceiling *L* to
  `1 + (n − 1)(L − 1)/30`, rounded to the nearest level. Scaling the level
  number directly compounds that `−1` offset as the ceiling falls —
  mid-gray pixels (the title bar renders at value 64) dim faster than bright
  ones and then drop onto the dark levels 0/1 entirely, which reads as
  contrast changing with brightness. Field-observed: the title bar vanished
  between brightness settings 16 and 15 while full-intensity text dimmed
  smoothly on. Rig-validated (2026-08): at reference drive the remap's
  rounding plateaus land exactly where predicted, and the value-64 canary
  stays photometrically distinct from full intensity at every measured
  operating point (ratios 0.10–0.37).
- **Rewrite the gray scale tables (0xB8/0xBC/0xBD) to shorten the pulses
  directly.** Rejected on measurement. The tables' entries must increase
  strictly, which floors the top level at 30 of 120 DCLKs and caps this route
  at ~4× — but worse, it produced visible artifacts from about 60 DCLKs down,
  well before that floor. The decisive comparison: a 60 DCLK pulse reached by
  *rewriting the table* artifacts, while the same 60 DCLK pulse reached by
  *capping pixel values into the stock table* is clean. So the artifacts
  belong to the rewritten table, not to short pulses, and the LUT stays
  untouched.
- **Lower the pre-charge voltage (0xBB) — adopted as the dim regime's dial.**
  Originally shelved, then adopted for tone (2026-07) on an eyeball model —
  "linear in the code, multiplicative with the other axes, dark at code 0,
  codes 8–23 comfortably above the 0x00–0x05 cut-out" — that the rig
  falsified in every clause: the response is only linear-ish deep in the dim
  regime, it is nearly inert at reference drive (code 0 still emits 77% of
  code 0x17 there), and the cut-out edge moves with drive — at the dim-regime
  state the panel is dark only at code 3 and below, so codes 4–7 are usable
  and are precisely the panel's dimmest tonal-rule-compliant states. What
  survives: pre-charge dimming is artifact-free by eye, and it is the *only*
  axis with real range below the ceiling's tonal floor — 342× across codes
  4–23 at the floor state, measured.

## The measured policy (2026-08)

Anchor tables live in `DisplaySSD1333` and come from one rig session
(`stage3-calibration-20260802.jsonl`); flux units are the rig's ADU/s, and
only their ratios matter. The level range is three regimes, stacked:

- **Levels 1–20, the pre-charge regime.** Ceiling at its tonal floor
  (`MIN_TONAL_CEILING = 4`), drive at its cut-out, pre-charge walks codes
  4→0x17 one code per level along its measured response (151 → 5.03e4
  ADU/s). These are the panel's ~20 dimmest states that keep the UI's
  dimmest shade emitting; the policy's bottom **is** the measured emission
  floor. The bottom two steps are 6.3× and 2.5× — the panel's floor, not the
  curve's: there is simply nothing between those states.
- **Levels 21–47, the ceiling regime.** Drive stays at the cut-out,
  pre-charge full, ceiling walks 5→31 one step per level along its measured
  duty response (6.43e4 → 2.03e5 ADU/s). The nominal `(n − 1)/30` duty law
  holds at reference drive but is concave at the cut-out drive this regime
  runs at — low levels emit about twice their duty share — which is why the
  table is measured, not computed.
- **Levels 48–255, the drive regime.** Full ceiling and pre-charge — full
  tonal range at every normal brightness. The level maps to a target flux by
  a power law anchored at the ceiling regime's top and reaching
  `MAX_TARGET_FLUX` at 255, and the measured drive response is inverted
  (log-log interpolation) for the drive product; master current stays minimal
  so the contrast register keeps the steps fine.

The keypress, not the level, is the curve's step unit above the knee: the UI
moves the level ±10–20% of itself per press, so the power law gives a
near-constant ~9–19% flux change per press, while inside the ladders every
level is one measured panel state. Unit tests hold exactly this line: no
keypress anywhere in 1–255 may leave the light unchanged (the UI's actual
+20%/−10% stepping is simulated); adjacent levels may collide only where the
drive response is flat near its cut-out.

## Consequences

- **Dimming below the drive cut-out costs UI tonal range, so the ceiling
  never leaves 4–31.** The UI's shades land on the levels below the ceiling;
  `MIN_TONAL_CEILING = 4` is the lowest ceiling where a 25% shade still
  rounds onto an emitting level. The tonal-range rule — the title bar's
  value-64 shade stays photometrically distinct from full intensity at every
  lit setting — is rig-verified across the range and held by
  `test_ssd1333_brightness.py`.
- **The register fit search is gone.** The old policy searched
  ceiling × drive (and pre-charge × contrast) grids against a multiplicative
  light model; with measured tables there is nothing to search — each regime
  is a monotone measured ladder, inverted directly. Contrast trim in the dim
  regime was dropped outright: measured, contrast 4→16 moves the floor-state
  flux ≤ 10% while one pre-charge code moves it 7–530%, so the trim could
  never fill a gap.
- **The curve's span is the panel's: ≈3.8 decades within the tonal rule**
  (151 → 1.04e6 ADU/s), versus 233:1 for the pre-refit policy, whose
  "dimmest" setting actually emitted 40× above the panel's floor because its
  multiplicative model credited the axes with ranges they never had.
- **Full level is a soft top: 75% of the measured clean maximum**
  (`MAX_TARGET_FLUX = 0.75 × 1.39e6 ADU/s`, landing at drive product ≈1030).
  The last 25% of flux costs disproportionate current (√-law), and the top of
  the range is where blooming lives. The blooming cap itself
  (`MAX_DRIVE_PRODUCT`, 70% of the register maximum) and `MAX_CONTRAST = 160`
  are eyeball-judged constants the rig cannot see; they stand unexamined and
  the soft top keeps the policy well inside both.
- **Pre-charge glow is accepted.** Native gray level 1 (no current drive)
  emits ~1.4e3 ADU/s absolute at pre-charge 0x17, dark by code 8 — so at
  mid/bright settings, "black" pixels carry a small additive floor. This was
  equally true of the pre-refit policy (init value 0x17); the dim regime's
  low codes actually reduce it.
- **Saved brightness settings shift, dim ones dramatically.** The knee state
  (ceiling 4, drive floor, pre-charge 0x17) is unchanged, so settings ≥ 20
  render within ~30% of their pre-refit light (old 50 ≈ new 48, old 125 ≈ new
  96, top 18% dimmer under the soft cap). Below the knee the range now runs
  40× deeper: the old dimmest setting emitted ~5.8e3 ADU/s, which the new
  curve reaches around level 8 — settings 1–7 are darkness the panel could
  always produce and the old model could not find.
- **Rendering costs ~0.5 ms per frame while dimmed.** The point table is
  applied in `ssd1333.display`. At the full ceiling it is `None` and
  rendering is a true pass-through, so normal brightness pays nothing.
- **These constants are one panel's photometry and do not transfer.** A
  different 1.91" panel, or a supplier change, invalidates every table; the
  rig (`PiFinder.panel_photometry`) is how they are re-measured. The curve
  itself was verified end-to-end on the rig — one measurement per level, all
  255 levels — before shipping (`stage3-verification-20260802.jsonl`).
- The SSD1351 path is untouched and still passes its 0-255 level through to
  the two current registers.
