# SSD1333 measured response surface (photometric, 2026-08-02)

Stage-2 deliverable of the panel-characterization effort: the 1.91" SSD1333's
light output as measured by the photometer rig (`PiFinder.panel_photometry`),
replacing the by-eye model recorded in ADR 0023. Every number below is panel
flux (bias-subtracted ADU/s on the rig's IMX462; see
`docs/ax/display/CONTEXT.md` for units and vocabulary). The dimming policy
(stage 3) should be fittable from this document plus the journals alone.

Conditions: one panel, one session day; refresh period 14 500 µs every
bring-up; sentinel drift ≤ 0.9 % within every run (each journal carries its
own sentinels); measurement precision ~0.2 % on period-locked tiers, ~4 % on
the sub-period tier before 48-frame averaging. Test frame: full-screen
uniform red, pixel value 255 except where stated. Fill fraction does not
matter — see finding 0.

Journals (all in `measurements/ssd1333/`, with the sweep specs and runner
scripts that produced them):

| journal | contents |
|---|---|
| `selftest-20260802-*.jsonl` | commissioning + pre-sweep gate runs |
| `apl-fill-probe-20260802.jsonl` | response vs lit-pixel fraction (finding 0) |
| `contrast-1d-20260802b.jsonl` | contrast 0–176, others at reference (supersedes `contrast-1d-20260802.jsonl`, whose bright points carry ~15 % refresh-beat noise from a 4-frame override) |
| `master-1d-20260802.jsonl`, `ceiling-1d-20260802.jsonl`, `precharge-1d-20260802.jsonl` | the other 1-D sweeps at reference |
| `grid-<a>-<b>-20260802.jsonl` (6 files) | 4×4 pairwise interaction grids |
| `dimslice-contrast-precharge-20260802.jsonl` | contrast × pre-charge at ceiling 4, master 0 (the policy's dim regime) |
| `valuetransfer-<op>-20260802.jsonl` (4 files) | pixel-value transfer at four operating points |
| `edge-*-20260802.jsonl` (5 files) | cut-out edges and emission floors |

Reference state throughout: contrast 64, master 7, ceiling 31, pre-charge
0x17 — panel flux **7.10e5 ADU/s** (session mean; individual runs 7.07–7.15e5).

## 0. The response is fill-independent

Flux per lit pixel is constant to ≤ 5 % between full-screen, 1-in-4 and
1-in-16 fill at every drive tested, and the response *ratios* along contrast
and master are identical at all three fills. There is no global
current-limiting / average-picture-level compression: the compressed axis
responses below are the panel's true register behaviour, and full-screen
test frames are a valid stand-in for sparse UI content.

## 1. Contrast and master collapse onto one drive variable

Panel flux at fixed ceiling/pre-charge is a single-valued function of the
**drive product P = contrast × (master + 1)** — every (contrast, master)
pair with the same P lands on one curve within 1.6 %, across independent
rig sessions, from the cut-out to P = 1280 (e.g. P = 160 reached as
contrast 20 × master 7 or contrast 160 × master 0: 1.5 % apart). The two
registers are one axis, not two.

Measured f(P) at ceiling 31, pre-charge 0x17, normalised to reference
(P = 512):

| P | 4 | 8 | 16 | 32 | 64 | 128 | 192 | 256 | 320 | 384 | 448 | 512 | 640 | 768 | 896 | 1024 | 1280 | 2560 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| f(P)/f(512) | .285 | .293 | .308 | .338 | .396 | .502 | .599 | .694 | .776 | .854 | .930 | 1.000 | 1.130 | 1.245 | 1.336 | 1.438 | 1.606 | 1.966 |

Shape: **dark below P = 4; a cliff at P = 4 straight to 28.5 % of
reference; nearly flat to P ≈ 32 (16× the drive for 1.19× the light);
then flux ≈ √(P)/22.6 · reference within ±2 % for P ≥ 128.** The old
policy's assumption (flux ∝ P) is wrong everywhere: the full P range
4→2560 (640×) delivers only 6.9× of light.

Consequences the old model got right: the cut-out is exactly the ADR's
`MIN_DRIVE` — lit iff P ≥ 4, confirmed at ceiling 31 and ceiling 4, and
all just-lit pairs (c1·m3, c2·m1, c4·m0) emit identically. Nothing exists
between dark and 28.5 % of reference on the drive axis alone.

## 2. The gray-scale ceiling obeys its duty law

The one axis that behaves as modelled: flux tracks `(n − 1)/30` within
~1 % over levels 2–31 at reference drive (worst point +9 % at level 5).
Native level 1 is dark at pre-charge ≤ 8 (see the pre-charge glow,
finding 4). The ceiling is the panel's only near-linear, wide-range,
trustworthy dimming axis.

## 3. Pre-charge authority depends on the operating point (separability fails)

Pre-charge voltage multiplies the light of a *weakly driven* pixel and
barely touches a strongly driven one. Measured span of pre-charge
0 → 0x17 (dark cells excluded), each at otherwise-reference state:

| at | contrast 4 | contrast 16 | contrast 64 | contrast 160 |
|---|---|---|---|---|
| pc 0→23 span | **32×** | 2.8× | 1.29× | 1.10× |

| at | master 0 | master 3 | master 7 | master 15 |
|---|---|---|---|---|
| pc 0→23 span | 6.8× | 1.68× | 1.29× | 1.13× |

| at | ceiling 2 | ceiling 4 | ceiling 10 | ceiling 31 |
|---|---|---|---|---|
| pc 0→23 span | dark→2.4e4 | 7.3× | 2.4× | 1.29× |

This is the headline separability verdict: **the response surface does not
factor into per-axis curves.** Interaction indices
I = (R(a,b)·R(a₀,b₀))/(R(a,b₀)·R(a₀,b)) reach 0.03 for pre-charge pairs
(and 2.3–2.8 for drive × ceiling — which finding 1's product collapse plus
a drive-dependent duty curve explains). The physical reading: pre-charge
sets the pixel's starting voltage, so it dominates short/weak drive pulses
and vanishes against long/strong ones. The eyeball `code/0x17` linear law
(ADR 0023) was measured in the dim regime, where pre-charge does have
authority; it must not be applied outside it — at reference, code 0 still
emits 77 % of code 0x17 (the 1-D pre-charge sweep is nearly flat).

The policy-relevant dim-regime surface (ceiling 4, master 0 — see
`dimslice-*`): pre-charge is the only real dial there. Contrast 4 → 16
moves flux ≤ 10 % while pre-charge 6 → 23 moves it 21× (2 422 → 50 660
ADU/s). The ADR's "joint contrast × pre-charge grid" is, photometrically,
a pre-charge staircase with contrast as a few-percent trim.

## 4. Pixel-value transfer: right at reference, drive-dependent elsewhere

At reference drive the native-level law holds: flux(level n) tracks
`(n − 1)/30` within a few percent, level 1 dark — the emitted-light-space
remap math in `ssd1333.gray_scale_ceiling` is validated, and its rounding
plateaus land exactly where predicted (ceiling 4: native 1–5 → mapped 1,
6–16 → 2, 17–25 → 3, 26–31 → 4).

But the per-level law bends with drive: at contrast 16 / master 3, level 2
emits 2.0× its duty share (curve concave); at the dimmest state the mapped
plateaus emit {dark, 0.103, 0.544, 1.0} of full instead of {0, ⅓, ⅔, 1} —
dim shades under-deliver at the bottom of the range.

**Pre-charge glow**: at pre-charge 0x17, native level 1 (no current drive)
emits a constant ~1.4e3 ADU/s absolute, independent of drive settings —
the pre-charge stage itself emits. At pre-charge 8 it is fully dark. Dim
states therefore have a small additive floor tied to the pre-charge code.

**Tonal range (canary) verdict**: value 64 vs value 255 stays
photometrically distinct at all four operating points measured — ratios
0.242 (bright ref, ≈ 7/30 as designed), 0.373 (mid drive), 0.368 (knee),
0.103 (dimmest). The user's tonal-range rule holds under the current
remap, with the caveat that the canary runs relatively dimmer than
designed at the very bottom.

## 5. Boundaries and the reachable range

- **Drive cut-out**: lit iff P = contrast × (master + 1) ≥ 4, at both
  ceiling 31 and ceiling 4. (ADR confirmed.)
- **Pre-charge cut-out moves with drive**: dark ≤ code 3 at the dim-regime
  state (contrast 4, master 0, ceiling 4); dark ≤ code 5 at ceiling 2 weak
  drive; dark ≤ code 1 at ceiling 2 reference drive. The eyeball
  "0x00–0x05 cut-out" was one slice of a drive-dependent boundary.
- **Emission floor within the tonal rule (ceiling ≥ 4)**: contrast 4,
  master 0, ceiling 4, pre-charge 4 → **148 ADU/s**. Steps just above the
  edge are steep (pc 4→5→6: 148 → 937 → 2 333 ADU/s).
- **Absolute emission floor measured** (tonal rule waived, ceiling 2):
  pre-charge 6 at weak drive → 20 ADU/s. Not policy-reachable by the
  user's constraints; documented for completeness.
- **Reachable span**: top ~1.4e6 ADU/s clean maximum measured (P = 2560);
  policy top ≈ 75 % of clean max ≈ 1.0e6. Against the 148 ADU/s floor:
  **≈ 3.8 decades (≈ 7 000:1) available within the tonal rule** — versus
  233:1 for the shipped policy's endpoints (its "dimmest" state
  actually emits 5.8–6.4e3 ADU/s, 40× above the panel's floor).

## 6. Answers to the stage-2 open questions

1. **The dim anomaly** (dimmest policy state ~78× brighter than modelled):
   no single axis under-delivers — the multiplicative model itself is the
   error. It multiplied per-axis spans (contrast 16×, master 8×, …) that
   the panel never had: measured, drive contributes 3.5× (not 128×) at the
   policy's dim settings and pre-charge/ceiling interact instead of
   multiplying. The panel *can* reach very dim (148 ADU/s, finding 5); the
   shipped policy just stops 40× short of it because its model's "dim"
   states aren't dim.
2. **Contrast nonlinearity**: fully mapped — finding 1. Flux is a function
   of the drive product, flat from P = 4 to ~32, √P above ~128.
3. **Pre-charge `code/0x17` law**: linear-ish *within the dim regime* but
   with a drive-dependent cut-out and 32× authority at low drive vs 1.3×
   at reference — finding 3. **Ceiling `(n−1)/30` duty law**: holds at
   reference drive; per-level shape bends with drive — findings 2 and 4.

## 7. Contradictions with ADR 0023 (flagged, not fixed)

The ADR's *decisions* (cap pixel values, leave the LUT alone, four axes,
knee shape) are untouched. These *measured claims* in it are wrong and
need a stage-3 amendment:

- "four settings that **multiply** together" — separability fails
  (finding 3); contrast and master are one variable (finding 1).
- Pre-charge "response linear in the code … dark at code 0" and
  "multiplicative with the other axes" — only true in the dim regime;
  nearly inert at reference; cut-out edge moves with drive.
- "codes 8–23, comfortably above the 0x00–0x05 cut-out" — at the dim-regime
  state the cut-out ends at code 3; codes 4–7 are usable and provide the
  panel's dimmest tonal-rule-compliant states.
- The current-register floor "0.16 % of full" — the drive floor emits
  28.5 % of reference (~15 % of policy top), not 0.16 %.
- Level→light claims for the shipped knee curve ("~6 %/level below the
  knee, ~35 %/press above") describe the *intent*; measured level→flux for
  the shipped policy is not in this dataset (stage 3 should re-measure its
  own curve end-to-end as its acceptance test).

Blooming (`MAX_BRIGHTNESS` 70 %) and `MAX_CONTRAST = 160` are
eyeball-judged constants the rig cannot see; they stand unexamined.

## 8. Guidance for stage 3

Fit space is three axes: **drive product P** (use low contrast codes with
master as coarse multiplier only for grid density — flux cares only about
P), **ceiling**, **pre-charge**. Anchor tables: f(P) (finding 1), duty law
(finding 2), pre-charge families (finding 3), dim slice, and the edges
(finding 5). Suggested policy skeleton consistent with the data: bright
regime rides P at ceiling 31 (√P gives smooth fine steps); mid regime
lowers the ceiling on the duty law at the drive floor; dim regime holds
ceiling 4 / P = 4 and walks pre-charge 23 → 4, accepting coarser steps at
the very bottom (pc 4→6 steps are ~2.5–6×; interpolate with contrast trim
and the pre-charge glow caveat). Re-measure any candidate curve
end-to-end on the rig before shipping — single-command sweep specs make
that cheap.
