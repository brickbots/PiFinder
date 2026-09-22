# SQM: the radiometer reads the frame's properties instead of assuming them

ADR 0022 made the radiometer the published SQM source. Its reduction is small:
take the sky background out of a raw frame, subtract a pedestal, divide by the
solid angle one pixel covers, and convert to a magnitude against a fixed
per-sensor zero point.

Three of those four inputs come from the frame. The fourth, the zero point, is
a calibration constant. The reduction is therefore only as good as the
assumption that the frame in hand has the same *shape* and the same *scaling*
as the frames the zero point was fitted on. Two of those properties were
assumed rather than read, and both were silently violated.

## The two properties

**Extent.** `arcsec²_per_pixel = (field_width_degrees × 3600)² /
pixels_per_side²`, where `pixels_per_side` is the photometry image's height.
That is correct only when the frame height spans `field_width_degrees`. Since
#544 exposure sweeps archive the whole sensor, not the crop, on the explicit
contract that a reader reduces the frame with `CameraProfile.ensure_cropped()`
before photometry. Nothing ever called it. The vocabulary said the same thing —
[`../ax/sqm/CONTEXT.md`](../ax/sqm/CONTEXT.md) defines the raw photometry image
as "always the crop, never the full-sensor frame that exposure sweeps archive"
— and the code still measured whatever it was handed.

A 1080-row IMX462 frame replayed against a field width fitted on the 980-row
crop credits every pixel with too little sky and reads `5 log10(1080/980)` =
0.211 mag bright. The live path is unaffected: `camera_pi` calls
`crop_and_rotate` before it samples.

**Scaling.** The driver reports a `DigitalGain` per frame that multiplies the
background above the pedestal. Nothing under `PiFinder/sqm/` read it. It is
identically zero-effect on the hardware each zero point was fitted on — mr2
reports 1.0166 on all 500 of its archived frames, mr reports 1.0098 on all 80 —
so it is invisible to any regression built from our own sweeps, and it stayed
invisible until an independent unit arrived reporting 1.246.

## Decision

`collect_radiometer_sample` reduces its input with `profile.ensure_cropped()`
before measuring anything. That is a no-op on the crop the live path already
hands it, so published values do not move; it makes every offline replay measure
what production measures, by routing through the ordinary crop rather than by a
second implementation of it.

The reported `DigitalGain` is recorded on the sample, and `radiometric_sqm`
divides the corrected signal by it. The divisor is not the reported gain but its
ratio to a new per-profile constant, `CameraProfile.calibration_digital_gain`:
the median gain the sweeps that fitted that profile's zero point actually ran
at. A frame reporting no gain, and a unit running the calibration gain, both
produce exactly the value they produced before.

Normalising to the calibration cohort rather than to 1.0 is the whole point. The
zero point already absorbed whatever gain its own frames carried. Dividing by
the raw reported gain would subtract that absorption a second time and shift
every calibrated device by 0.02 mag for no reason.

## The pedestal is not a third such property

The same frames report `SensorBlackLevels` of 240.0 where the IMX462 profile
assumes 238.0, which looks like a third assumed property worth 0.204 mag. It is
not, and the distinction matters because the fix would have been to trust a
number that is wrong.

A sweep steps exposure about 40x at a fixed sky, so its background is a straight
line, `pedestal + rate × t`. The intercept is the pedestal in raw ADU, measured
from the pixels with no constant involved. The IMX462 sweeps fit to:

| Sweep | Fitted pedestal | Reported `SensorBlackLevels` | Profile |
|---|---:|---:|---:|
| markcasazza 20260912_021411 | 238.78 | 240.00 | 238.0 |
| markcasazza 20260912_072553 | 238.73 | 240.00 | 238.0 |
| mr2 20260721_233525 | 237.86 | 239.09 | 238.0 |
| mr2 20260721_235303 | 238.11 | 239.41 | 238.0 |

The profile constant is right and the reported value is libcamera's static
tuning tuple. Taking it anyway raises that unit's own mean absolute error over
the archive from 0.117 to 0.185, and on the IMX296 sweeps the static 240.0 sits
at or above the background, so `sky − pedestal` goes non-positive and the
radiometer publishes nothing at all on 0 of 80 frames.

Nothing changes here. ADR 0028 already decides the pedestal correctly: the
tracked black level, fitted from the frames themselves, is the same measurement
the table above makes by hand.

## Evidence that the digital gain reaches the raw pixels

PiFinder samples `make_array("raw")`, which bypasses the ISP, so whether the
reported gain is in the pixels had to be measured rather than assumed. With the
extent corrected and each sweep's pedestal taken from its own line fit above,
the two units differ by 0.213 and 0.215 mag on two sweeps apiece.
`2.5 log10(1.2464 / 1.0166)` predicts 0.221. For the IMX290/462 the IPA programs
the sensor's own digital-gain register, so it is in the raw.

Why the units differ at all is the software stack, not the sky. Over 820
archived frames `DigitalGain` tracks `1.0166 / min(ColourGains)` whenever a
colour gain falls below unity: correlation +0.99 and +0.97 on the two units that
show it. Those libcamera versions fold the white-balance normalisation into the
sensor's digital gain. mr2 never folds — its colour gains reach 0.82 on its own
darkest sweeps, lower than the folding unit's, and its gain does not move,
correlation −0.03. A Pi OS update that starts folding would move our published
SQM by up to 0.2 mag with no code change, which is the standing risk this
removes.

## Alternatives considered

**Crop at every call site instead of inside the sample reduction.** This is what
#544 intended and what did not happen. The contract lived in a docstring and a
CONTEXT entry, and three scripts, the live path and every future replay each had
to remember it. Putting it inside the one function that reduces a frame makes
the rule unforgeable and costs a size comparison per frame.

**Refuse a full-sensor frame rather than reduce it.** Honest, and it would have
surfaced this immediately, but it makes every archived sweep since #544
unreplayable, which is the opposite of what an archive is for.

**Normalise the digital gain to 1.0.** Simpler to state and wrong, for the
reason above: it double-counts the gain the zero point already absorbed.

**Refit each zero point with the gain divided out.** Equivalent in the end and
strictly worse to land: it moves every calibrated device's published value on
the same commit that introduces the mechanism, so a regression in either one
cannot be told from the other.

## Consequences

- Published live values do not move. Over all 66 referenced archive sweeps, mr2,
  mr, archive-hq and archive-imx296 replay bit-identical, and radiometer
  publication counts are unchanged at 1843.
- Archive mean absolute error falls from 0.251 to 0.202 mag. The unit reporting
  a folded gain falls from 0.762 to 0.378.
- `CameraProfile` now carries the gain its calibration ran at. A profile whose
  zero point is refitted must update that constant in the same change, or the
  new zero point will be normalised against the old cohort.
- `sqm_details` carries `digital_gain` and `digital_gain_ratio`, so an archive
  replay can tell what scaling a frame was published under.
- ADR 0028 closed with a validation obligation on independent dark-site nights.
  This archive supplies them: on the two clear 21.44 and 21.55 mag sweeps the
  black-level tracker returns 238.65 and 238.62 against the independent line fit
  of 238.78 and 238.73, agreeing to about 0.1 ADU on a sky where the profile
  constant alone would have been wrong by more.
- Two properties are read where two were assumed. The zero point and the field
  width remain assumed, and remain the next thing to check when a unit disagrees
  with a meter.
