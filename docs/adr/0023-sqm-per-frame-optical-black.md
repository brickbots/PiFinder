# Per-frame optical black as the IMX290/IMX462 SQM pedestal

## Decision

On IMX290/IMX462 the SQM pedestal is the sensor's own shielded optical-black
(OB) rows, measured on every frame, rather than a static profile offset or a
nightly-fitted dark-current model.

The IMX290/462 already transmits ten front vertical OB rows per frame. A kernel
patch adds a second sensor source pad (`MEDIA_BUS_FMT_SENSOR_DATA`) so those
rows reach the receiver as a separate metadata stream without changing the
1920x1080 image matrix. A libcamera cam-helper unpacks the shielded pixels,
trims the outer 5% each side, averages the central 90% and publishes the result
through `controls::SensorBlackLevels` on the 16-bit scale, tagging it
`{level, level, level, level + 1}`. The one-count sentinel in the fourth
channel distinguishes a measured value from libcamera's static tuning tuple.
`camera_pi` converts a marked value back to native ADU and attaches it to the
radiometer sample as `optical_black_pedestal`.

A valid marked OB value is the complete per-frame pedestal: it already contains
the bias and the frame's accumulated dark signal. Pedestal precedence is
therefore: valid same-frame OB, then a user-calibrated pedestal, then the
profile `bias_offset`. No dark-current rate is applied on top of OB and no
nightly rate is fitted or persisted for these sensors.

## Status

Accepted for IMX462 (and IMX290, same driver). Supersedes the earlier
scheduled-pedestal-probe proposal, which is not implemented: same-frame OB makes
scheduled probe frames unnecessary on these sensors.

## Rationale

Sony documents OB as the reference zero for image signals, but documentation
alone did not prove OB dark accumulation matches active-pixel dark accumulation
on this stack. A same-frame cupboard test on mr2 (IMX462, production gain,
requested 30 / reported 29.512) settled it: comparing normal Bayer pixels and
shielded OB rows from identical frames, the active-green and OB
dark-accumulation slopes agreed to well under 1 ADU/s, with active green a fixed
~0.8-1.0 ADU below OB (~0.01 mag). That residual is too small to justify a
per-unit constant from one camera and is left unmodelled.

A same-frame measurement strictly dominates a once-per-night model: it tracks
bias and accumulated dark signal live, with no user action. The rolling
radiometer median smooths gain-30 frame noise without storing a fitted rate.
Central-90% averaging (not a whole-code median) preserves sub-ADU resolution,
which matters because the exposure-dependent dark signal is small.

## Consequences

- IMX462 SQM is zero-touch: no lens cap, dark frames, or calibration wizard.
- Manual calibration remains the fallback for sensors without usable OB and for
  frames where OB is missing or unmarked; it never overrides valid OB.
- The patched kernel is built via `nixos-hardware`; `pifinder-fast` /
  `pifinder-kernel-cross` provide a fast x86_64 cross build to seed the binary
  cache so CI substitutes the kernel rather than compiling it.
- Added camera-process cost is about +0.23 percentage points of one core.
- Open: IMX296 OB uses a different CSI line-type path; IMX477 OB is not yet
  proved accessible in this stack. Independent-unit and temperature-range
  validation of IMX462 remains useful but is not required for users.
