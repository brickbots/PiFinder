# SQM: the tracked black level supersedes any stored bias offset

ADR 0022 made the radiometer the published SQM source. Its reduction subtracts a
detector **pedestal** from the measured sky background, and the size of the
published magnitude depends directly on getting that pedestal right:

```text
sqm = effective_zero_point
      + 2.5 log10(exposure_seconds)
      − 2.5 log10((sky − pedestal) / arcsec²_per_pixel)
```

The pedestal's bias term was a stored constant. It came from the per-sensor
profile, or from the optional calibration wizard when a user had run it. Both
are measured once and then trusted indefinitely.

That assumption is wrong about the hardware. The sensor's optical-black clamp
pins raw black to a target that **moves with sensor state**, temperature being
the suspect. On the 2026-07-18 imx296 reference sweeps the delivered black level
was 55.9–56.3 ADU, while the device's own wizard calibration said 58 and the
profile constant said 60. Both over-subtracted.

A few ADU sounds harmless and is not. Against a bright city background it is
negligible. At dark-site signal levels a 2–4 ADU over-subtraction produces a
**−0.9 to −1.5 mag/decade** SQM-versus-exposure slope, and it kills short
exposures outright: `sky − pedestal` goes non-positive and the frame is
discarded as `background_not_resolved_above_pedestal`. The night-to-night wander
alone is worth 0.2–0.4 mag at a dark site.

The measurement was already available in the frames. Sensor background is linear
in exposure:

```text
background_per_pixel = bias_offset + (dark_current + sky_rate) × exposure
```

so the **intercept** of background against exposure is the electronic pedestal
at zero exposure — the true black level right now, with no lens cap and no dark
frame. The auto-exposure loop varies exposure by itself around slews and
sky-brightness changes, which supplies the lever arm. Against the 2026-07
archive ramps the intercept fit recovers each night's pedestal to ±0.06–0.6 ADU.

## The decision

**A leased tracked black level supersedes every stored bias offset, including a
wizard-measured one.** `BlackLevelTracker` fits the in-session intercept, and
`update_radiometric_sqm()` prefers it over `profile.bias_offset` whenever the
lease holds. The stored constant becomes the fallback for the period before the
fit converges.

**The dark-current rate stays the wizard's.** The intercept fit cannot separate
dark current from sky, because both are linear in exposure and only their sum is
observable in the slope. Only a lens-capped measurement can attribute that term,
so a measured `dark_current_rate` is still added on top of the tracked bias.

Trust is a **lease, not a latch**. An accepted fit expires and must be re-earned
from fresh frames. The gates:

| gate | default | why |
|---|---|---|
| `min_samples` | 12 | enough points for a meaningful intercept |
| `min_exposure_ratio` | 1.5 | without a lever arm the intercept is unconstrained |
| `max_intercept_stderr` | 0.6 ADU | a drifting sky breaks the single-line model and inflates this |
| `max_offset_deviation` | 12.0 ADU | sanity anchor against the profile constant |
| `max_age_seconds` | 900 | evidence ages out of the window |

Samples taken while the transmission diagnostic reports cloud are withheld
(`stable=False`). A moving sky breaks the single-line model, and the stderr gate
is the backstop for drift the flag misses.

## Considered and rejected

**Keep trusting the stored constant.** This is what produced the failure. It is
also the option that degrades most where SQM matters most, since the error is
invisible under a city sky and largest at a dark site.

**Fix it by re-running the wizard more often.** This puts a lens cap, three
minutes, and a service flow in front of a value that drifts within a single
session. It also contradicts the zero-touch product intent in
[`../ax/sqm/CONTEXT.md`](../ax/sqm/CONTEXT.md): normal operation must not require
calibration.

**Let the user correct the residual by hand.** This was `SQM Correct`, removed on
2026-07-18. A magnitude-additive knob silently absorbs an ADU-space,
brightness-dependent error, so it masks a pedestal fault instead of fixing it and
produces a correction valid at exactly one sky brightness.

**Estimate the pedestal from a low image percentile.** Ordinary sky pixels
contain real sky light, so this biases the pedestal upward by an amount that
depends on the sky. `NoiseFloorEstimator` retains such percentiles as
diagnostics only, for this reason.

## Consequences

- The wizard's headline output is no longer its most valuable one. Its lasting
  contribution is the dark-current rate; its bias offset is superseded whenever
  the tracker is leased, and its read noise was always diagnostic. The user-facing
  page [`docs/source/sqm.rst`](../source/sqm.rst) says so rather than implying
  calibration is a general accuracy upgrade.
- A stored bias measured on a warm bench no longer poisons a cold field session.
- The published pedestal can differ between two units with identical profiles and
  identical calibration files. That is the intended behaviour, not drift.
- `sqm_details` carries `black_level_tracked`, `black_level_pedestal` and
  `black_level_stderr` so an archive replay can tell which pedestal a frame used.
  The flag reflects what publication actually used, not the raw last fit.
- The tracker conditions from radiometer samples on every fresh frame rather than
  from the 10-second stellar diagnostics, so it converges in minutes and keeps
  working through failed solves.
- The headline archive accuracy in [`../ax/sqm.md`](../ax/sqm.md) is unchanged by
  this. Those sweeps are light-pollution-dominated Ghent skies, where the
  correction is negligible by construction. Its value at dark sites is argued
  from the physics and the imx296 sweeps above, and remains a validation
  obligation on independent dark-site nights.
