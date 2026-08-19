# FOV gate width follows lens confidence

[ADR 0027](0027-fov-gate-derived-from-optical-train.md) derived the solver's
FOV gate from the optical train and narrowed it to ±15%. That is right when we
know what lens is fitted. We frequently do not — and 0027 treated the camera
profile's fallback lens as though it were knowledge. So the gate width now
follows how the lens was obtained: a **stated lens** keeps ±15%, an **assumed
lens** gets a gate spanning every lens that sensor has shipped with, and the
first confident solve under an assumption promotes it to a statement by
identifying the lens from the **fitted FOV**.

## What went wrong

Some rev4 units shipped with a 12 mm lens and no `camera_lens` in their
config. `resolve_lens` falls back to `CameraProfile.default_lens_key`, which
is `16mm` for the imx462 — so the device assumed 16 mm, derived 10.40°, and
gated `[8.84, 11.96]`. The true field of view is 13.51°. Every frame was
rejected before verification. **Those units stopped solving on update having
changed nothing**, and the symptom presents as an exposure problem
(0027's known sharp edge, tracked as #610/#611).

The pre-0027 window was the fixed `12.0 ± 4.0` = `[8.0, 16.0]`, which happened
to span the imx462 at *both* 12 mm and 16 mm. That is the whole reason these
units worked on 2.6.1 and not on 2.6.2.

The failure class matters. 0027 reasoned about a user who *changed* something
and can be told to check the barrel. Nobody here changed anything, and the
config that broke them is the config we shipped them. A fallback is not a
statement, and it should never have bought a statement's confidence.

## The gate, by confidence

Assumed-lens gates are the union over the lenses that sensor has shipped with,
re-centred (tetra3's window is symmetric — `fov_estimate ± fov_max_error`):

| sensor | shipped lenses | assumed gate | stated-16mm gate |
|---|---|---|---|
| imx462 / imx290 | 12 mm (13.51°), 16 mm (10.40°) | `12.19 ± 3.35` = [8.84, 15.53] | [8.84, 11.96] |
| imx296 | 12 mm (17.78°), 16 mm (13.71°) | `16.05 ± 4.39` = [11.65, 20.44] | [11.65, 15.77] |
| hq | 25 mm (10.33°) | [8.78, 11.88] — unchanged | n/a |

**Every 12 mm figure in this table is superseded** — see the amendment at the
foot of this document. The reasoning stands; the arithmetic moved.

The imx462 assumed gate lands within a whisker of the pre-0027 constants it
replaces, which is the behaviour these units are known to work under. The hq
only ever shipped one lens, so nothing about it widens.

The shipped `default_database.npz` is built over `[10.0, 30.0]°`, so the
imx462's assumed gate is effectively `[10.0, 15.53]` — the part below 10°
holds no patterns and can match nothing. Widening therefore costs less than
the numbers suggest: the database floor is already doing some of the pruning.
It also means the imx462 at 16 mm sits just 0.40° above that floor, which is a
narrower margin than anything else we ship and worth remembering before any
future change to either the crop or the database range.

## What the narrow gate was actually buying

Measured before committing to the widening, against the real solver and real
frames (`test_images/pifinder_debug_0{1,2}.png`, 512×512, median of 5, fresh
`Tetra3` per run):

| gate | debug_01 | debug_02 |
|---|---|---|
| ±15% (today) | 1.2 ms | 1.4 ms |
| `12.0 ± 4.0` (pre-0027) | 1.1 ms | 1.4 ms |
| ±30% | 1.1 ms | 1.4 ms |
| ±50% | 1.1 ms | 1.4 ms |
| no hint at all | 1.5 ms | 1.7 ms |

**On speed, essentially nothing.** RA/Dec/FOV/Matches were identical and
`Prob` bit-identical across every width. This is despite the gate being a real
prune rather than a post-hoc filter — it culls the pattern catalog inside the
hash lookup, before verification (`tetra3.py:2271`), and rejects again after
fitting (`tetra3.py:1953`). The catalog-eval term it grows is simply not where
the time goes. Note `fov_max_error` is an **absolute** angle, not a fraction —
`np.deg2rad(float(fov_max_error))` at `tetra3.py:1697`; `solver_fov_params`
manufactures the absolute value as `fov * FOV_GATE_MARGIN`.

**On mis-solve rejection, something real** — and this is the reason not to go
further than we are going. With spurious centroids injected to displace the
real stars past the `verification_stars_per_fov` trim, wide gates returned
*confident* false solves that `match_threshold` did not reject: a `20.0 ± 10.0`
gate "solved" at 23.2°, and no-hint at 20.4°, both with ~26 matches. The FOV
gate is what would have caught those. The assumed gate proposed here still
excludes everything above 15.53°, so it keeps that protection; **omitting the
hint entirely would give it up, which is why we do not.** (Single-shot noise
trials, not a false-positive *rate* measurement — treat the direction as
established and the magnitude as not.)

**And the cost is wildly asymmetric.** A good frame *outside* the gate burns
the entire `solve_timeout` (`solve_timeout=1000` at `solver.py:1082`) and
returns nothing — every frame, forever. Against a wide gate's ~0.3 ms, an
over-tight gate is the expensive failure by three orders of magnitude. That
asymmetry is the whole argument: widening risks a little precision, while
over-tightening costs the device its function.

## Considered options

**A migration writing `camera_lens=12mm` on rev4 boards** was the first
instinct and is wrong. Rev4 reports as `imx462`, but so do v3 units, so the
sensor cannot be the predicate; the board can be probed (the BQ25895 ACK at
0x6A is the rev4 marker `splash.py` already uses to pick the panel), but the
predicate would still be *board revision*, and the fact we need is *which lens
was in the box*. Not all rev4s shipped with the 12 mm. The migration would fix
most units by breaking the rest, and it would break them in exactly the way we
are here to fix. A wrong write is worse than no write, because after the gate
tightens around it the device can no longer measure its way out.

**Raising `FOV_GATE_MARGIN` globally** to ~0.30 is a one-line diff, but it
loosens the gate for every user who stated their lens correctly — spending
0027's entire benefit to cover a case those users are not in. It is also
uncomfortably tight by accident: at 0.30 the imx462's 16 mm gate reaches
13.52° against a 12 mm field of view of 13.51°, a 0.01° margin that only looks
like a decision.

**Storing a measured effective focal length** instead of snapping the fitted
FOV to a registry key would be exact for any lens, including third-party
glass. Rejected as scope, not as a bad idea: `camera_lens` is a registry key
the Lens menu renders, so this needs a second config key and a menu that can
display a custom focal length.

## Consequences

**`fov_estimate` is no longer this device's field of view when the lens is
assumed.** It is the centre of a plausible range. The pair has to be read
together; neither half means anything alone.

**Self-heal writes once, and only into an assumption.** A stated lens is never
overwritten — the user's claim stays authoritative, and 0027's "a mis-stated
lens means no solves" is untouched. Because the write only happens when the
lens is assumed, it happens at most once per device.

**A fitted FOV matching no known lens writes nothing.** It leaves the lens
assumed, logs the measurement, and the device keeps solving on the wide gate
forever. Third-party lenses therefore work but keep approximate SQM, which is
honest: we do not know their focal length.

**A physical lens swap after self-heal deadlocks**, exactly as it does for any
stated lens: the gate is tight around the old lens, so no frame solves, so no
fitted FOV arrives to correct it, and the user must set the menu. This is
0027's accepted consequence, but it newly reaches users who never opened the
menu — before this change they had a fallback and, from 2.6.1, a window wide
enough to have absorbed the swap. The general cure is to re-open the gate on
sustained zero matches *with adequate centroids*, which is #611's scope and
needs `Centroids` on `SolveDiagnostics` (#610). Until then it is a
documentation path (#613).

## Amendment (#627): the 12 mm's field of view was derived from a guess

Every 12 mm number above — 13.51°, 17.78°, and the two assumed gates built on
them — came from `LENSES["12mm"].effective_focal_length_mm = 12.0`, which was
the nominal standing in for a measurement, flagged
`effective_focal_length_measured=False` in the registry and called out in a
comment as optimistic. It was.

A rev4 imx462 on a 12 mm fitted **12.4366 ± 0.0025°** over six solves, giving
an effective focal length of **13.04 mm** — the barrel runs 8.7% long. The same
board, same night, same code, then took a 16 mm and fitted 10.4011°, which
reproduces that lens's derived field to 0.02% and its 15.61 mm to 15.613. That
control is what makes this a measurement of the 12 mm rather than of the crop
geometry, which it independently confirms.

| sensor | shipped lenses | assumed gate | stated-12mm gate |
|---|---|---|---|
| imx462 / imx290 | 12 mm (**12.44°**), 16 mm (10.40°) | **`11.57 ± 2.73` = [8.84, 14.30]** | [10.57, 14.30] |
| imx296 | 12 mm (**16.38°**), 16 mm (13.71°) | **`15.25 ± 3.59` = [11.65, 18.84]** | [13.92, 18.84] |
| hq | 25 mm (10.33°) | [8.78, 11.88] — still unchanged | n/a |

What this does and does not disturb:

**The decision is unaffected.** Gate width still follows lens confidence, the
assumed gate still spans every lens its sensor shipped with, and the hq still
has no union to take. Only the field of view the 12 mm implies has moved.

**The regression this ADR exists to fix was real either way.** A rev4
assuming the 16 mm gated `[8.84, 11.96]` against frames that are 12.44° wide,
not 13.51° — still outside, still every frame, still forever.

**The assumed gates narrowed rather than widened**, because the 12 mm's true
field is closer to the 16 mm's than the nominal suggested. The imx462's upper
bound moves 15.53° → 14.30°, so the mis-solve rejection argued for above gets
slightly stronger, not weaker. The database floor note still holds: the
effective imx462 assumed gate is now `[10.0, 14.30]`.

**Self-heal could not identify the 12 mm until this was fixed.** A fitted
12.44° sat 7.9% from the derived 13.51°, outside `LENS_IDENTIFY_TOLERANCE`
(5%), so `identify_lens_from_fitted_fov` returned None on every frame and the
affected units kept solving on the wide gate forever — the "matching no known
lens writes nothing" consequence, firing on a lens we shipped. That is the
symptom that surfaced this, and it is what #627 fixes.

**SQM on 12 mm units was reading a field 8.6% too wide**, and its zero point
with it. The f-number comment above still wants settling separately.

**The 5% tolerance survives.** The imx462's two candidates are now 19.6% apart
rather than ~30%, which is still far outside any plausible ambiguity.

One caveat, recorded honestly: 13.04 mm rests on a **single 12 mm sample**. The
16 mm earned its 15.61 by reproducing two independently calibrated field
widths on two different sensors. A second 12 mm — ideally on an imx296, so the
sensor half varies too — would put it on the same footing.
