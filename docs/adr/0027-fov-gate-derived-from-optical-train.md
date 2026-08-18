# FOV gate derived from the optical train

PiFinder ships more than one camera sensor and now more than one lens, but the
solver's FOV gate was the fixed pair `fov_estimate=12.0, fov_max_error=4.0` —
a compromise straddling the two sensors rather than a description of either.
We now derive the gate, SQM's radiometric field width, and the chart's frustum
shading from an **optical train**: the auto-detected camera profile paired with
a user-configured **lens**. Field of view stops being three disagreeing
constants and becomes one computed value.

## Why it mattered

A 12 mm lens on an imx296 images 17.8°, which falls outside the old
`[8.0, 16.0]` window. Tetra3 enforces that window twice — candidates are pruned
by implied field of view before verification, and survivors are rejected after
fitting — so such a frame does not solve *at all*, however many good centroids
it contains. The old constants happened to cover three of the four
sensor × lens combinations we can ship, and nothing in the code said which one
they were for.

## Considered options

**Widening the fixed window** to span every combination would work, but it
keeps a constant that describes no actual hardware and gets looser with each
new lens. Deriving instead makes the gate *tighter* than before while being
correct everywhere: the old window was effectively ±33% of its estimate.

**Margin: ±15% of the derived field of view**, not a fixed number of degrees.
An absolute margin is proportionally four times looser on a 10° train than a
20° one. 15% covers lens-sample spread, barrel distortion and focus shift;
it was validated against real frames re-projected to all four combinations,
including injected ±5% lens error, with every case solving.

**Effective, not nominal, focal length** drives the derivation. The shipped
"16 mm" lens measures ~15.6 mm, and a single effective length of 15.61 mm
reproduces *both* independently calibrated SQM field widths (imx296 13.71,
imx462 10.38) to within 0.02°. Deriving from the nominal 16.0 instead would
silently shift every existing user's SQM by ~0.05 mag. `Lens` therefore
carries both: nominal for the menu label the user reads off the barrel,
effective for all arithmetic.

## Consequences

**A mis-stated lens means no solves, and we deliberately do not recover from
it.** The gate is centred on what the user said is fitted, so stating the
wrong lens puts every frame outside the window. We considered detecting this
(retry unconstrained, read the fitted FOV, infer the lens) and rejected it for
this change: the lens is clearly marked on the barrel, so the troubleshooting
path documents cleanly, and self-healing would add a recovery path through the
solver's hot loop for a once-per-device setting.

The sharp edge is that this failure *presents as an exposure problem*.
Auto-exposure is driven by `Matches`, not by centroid count, so zero matches
from a rejected-but-perfectly-good frame sends zero-match recovery walking the
exposure ladder indefinitely. That weakness is not new — defocus does the same
thing today — and gating recovery on centroid count is tracked separately.
Until then, "solves stopped after I changed the lens" is a documentation
problem, not a code path.
