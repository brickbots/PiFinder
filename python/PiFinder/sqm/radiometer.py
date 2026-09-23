"""Solve-independent, low-cost radiometric sky measurements.

The camera process reduces each raw frame to a small scalar sample while the
matrix is already local.  The solver process can then aggregate and publish SQM
without copying/scanning the raw frame and without requiring a plate solve.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

from PiFinder.optics import optical_train_for_profile


def extract_photometry_image(raw, profile) -> Optional[np.ndarray]:
    """Return linear mono or averaged Bayer-green pixels as ``float32``."""
    if raw is None:
        return None
    arr = np.asarray(raw)
    if arr.ndim != 2:
        return None
    if str(profile.format).upper().startswith("SRGGB"):
        height, width = arr.shape
        if height < 2 or width < 2:
            return None
        return (
            arr[0 : height - height % 2 : 2, 1:width:2].astype(np.float32)
            + arr[1:height:2, 0 : width - width % 2 : 2].astype(np.float32)
        ) / 2.0
    return arr.astype(np.float32)


def _mosaic_phase_is_rggb(profile) -> bool:
    """True when pixel (0, 0) of a ``crop_and_rotate`` frame is still red.

    Red is far more phase-fragile than green, which is why this guard is new
    with the colour term and ``extract_photometry_image`` never needed it. A
    180-degree rotation maps the block ``R G / G B`` to ``B G / G R``: the two
    green sites are invariant, but red and blue swap. An odd crop origin
    shifts the mosaic by one site with the same effect. Either would make the
    sampler read blue as red, and a wrong R/G does not fail loudly -- it just
    moves the published zero point by up to the width of the clamp.

    So require the three invariants the sampler assumes rather than trusting
    them to stay true: RGGB order (not merely "some Bayer format"), no
    rotation, and an even crop origin on both axes.
    """
    if not str(getattr(profile, "format", "")).upper().startswith("SRGGB"):
        return False  # mono, or a CFA order this sampler cannot read
    if int(getattr(profile, "rotation_90", 0) or 0) % 4 != 0:
        return False  # 90/270 transpose the CFA; 180 swaps red and blue
    crop_y = getattr(profile, "crop_y", (0, 0))
    crop_x = getattr(profile, "crop_x", (0, 0))
    return crop_y[0] % 2 == 0 and crop_x[0] % 2 == 0


def _sky_red_green(
    raw, profile, border_fraction: float, stride: int
) -> Tuple[Optional[float], Optional[float]]:
    """Median red and green sky level from an RGGB mosaic, or (None, None).

    Sky colour is what converts the sensor's passband to the meter's V band:
    light pollution is sodium/LED and green-weighted, airglow is grey and
    NIR-rich. Mono sensors carry no colour and return (None, None), which
    falls back to a constant zero point.

    Colour sensors that do not *use* the correction still report here: the HQ
    is RGGB and gets real values, which its zero point then ignores because
    its colour slope is 0. That costs nothing and accumulates the colour data
    a future refit would need.
    """
    if not _mosaic_phase_is_rggb(profile):
        return None, None
    a = np.asarray(raw)
    if a.ndim != 2 or min(a.shape) < 64:
        return None, None
    by = int(a.shape[0] * border_fraction)
    bx = int(a.shape[1] * border_fraction)
    by += by % 2  # keep mosaic phase: (0, 0) must stay red
    bx += bx % 2
    c = a[by : a.shape[0] - by, bx : a.shape[1] - bx]
    if min(c.shape) < 32:
        return None, None
    red = float(np.median(c[0::2, 0::2][::stride, ::stride]))
    green = float(
        np.median(
            np.concatenate(
                [
                    c[0::2, 1::2][::stride, ::stride].ravel(),
                    c[1::2, 0::2][::stride, ::stride].ravel(),
                ]
            )
        )
    )
    return red, green


def collect_radiometer_sample(
    raw,
    profile,
    exposure_sec: float,
    *,
    sequence: int,
    captured_at: float,
    border_fraction: float = 0.10,
    stride: int = 4,
    digital_gain: Optional[float] = None,
) -> Optional[dict]:
    """Reduce a raw frame to a robust sky-background sample.

    A deterministic sparse grid keeps the per-frame camera-process cost small.
    The outer ten percent is excluded to reduce corner-vignetting bias. Stars
    occupy far below half the grid, so the median rejects them without building
    a source mask. Four quadrant medians provide a cheap gradient diagnostic.

    ``raw`` may be either a crop or a whole sensor frame. Live capture hands
    over the crop, but sweeps archive the full sensor, so anything replaying
    one would otherwise measure a frame the calibration never saw: a taller
    frame spans more sky than ``radiometric_fov_degrees`` describes, and every
    pixel would be credited with too little of it. ``ensure_cropped`` reduces
    it through the ordinary crop path first, which is a no-op on a crop.

    ``digital_gain`` is the driver's reported DigitalGain for this frame. It
    multiplies the background, so it is recorded here and divided out against
    ``profile.calibration_digital_gain`` when the sample becomes a magnitude.
    """
    if not exposure_sec or exposure_sec <= 0 or stride < 1:
        return None
    if raw is not None and hasattr(profile, "ensure_cropped"):
        raw = profile.ensure_cropped(np.asarray(raw))
    image = extract_photometry_image(raw, profile)
    if image is None or min(image.shape) < 32:
        return None

    border_y = int(image.shape[0] * border_fraction)
    border_x = int(image.shape[1] * border_fraction)
    y_stop = image.shape[0] - border_y
    x_stop = image.shape[1] - border_x
    sampled = image[border_y:y_stop:stride, border_x:x_stop:stride]
    if sampled.size < 64:
        return None

    background = float(np.median(sampled))
    mad = float(np.median(np.abs(sampled - background)))
    mid_y, mid_x = sampled.shape[0] // 2, sampled.shape[1] // 2
    quadrants = (
        sampled[:mid_y, :mid_x],
        sampled[:mid_y, mid_x:],
        sampled[mid_y:, :mid_x],
        sampled[mid_y:, mid_x:],
    )
    quadrant_medians = [float(np.median(part)) for part in quadrants if part.size]

    sample = {
        "sequence": int(sequence),
        "captured_at": float(captured_at),
        "exposure_sec": float(exposure_sec),
        "background_per_pixel": background,
        "background_mad": mad,
        "background_quadrants": quadrant_medians,
        "background_gradient": max(quadrant_medians) - min(quadrant_medians),
        "sampled_pixels": int(sampled.size),
        "pixels_per_side": int(image.shape[0]),
        "method": "sparse_central_median",
    }
    red, green = _sky_red_green(raw, profile, border_fraction, stride)
    if red is not None:
        sample["background_red"] = red
        sample["background_green"] = green
    gain = _usable_gain(digital_gain)
    if gain is not None:
        sample["digital_gain"] = gain
    return sample


def _usable_gain(reported) -> Optional[float]:
    """The reported gain as a positive finite float, or None.

    Drivers do mistype their metadata keys -- ``camera_pi`` guards its
    ``SensorTemperature`` read for the same reason -- and this runs in the
    capture loop with no caller-side try, so a string here would stop
    captures rather than lose one frame's gain.
    """
    if reported is None:
        return None
    try:
        value = float(reported)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value > 0 else None


def digital_gain_ratio(sample: dict, profile) -> float:
    """Reported DigitalGain over the gain this profile was calibrated at.

    Returns 1.0 when the frame reports no gain, and when the profile states no
    calibration gain. The second case covers sensors where nothing shows the
    reported gain reaching the raw array (HQ, IMX296): correcting for a gain
    that is not in the pixels would bias the value instead of fixing it.

    Public because the black-level tracker needs it too: it fits the pedestal
    as the intercept of background against exposure, and the gain multiplies
    the slope, so a window whose gain moves must be fitted against
    ``ratio * exposure`` or the jitter lands in the intercept.
    """
    calibrated = getattr(profile, "calibration_digital_gain", None)
    reported = _usable_gain(sample.get("digital_gain"))
    if reported is None or not calibrated or calibrated <= 0:
        return 1.0
    return reported / float(calibrated)


def radiometric_sqm(
    sample: dict,
    profile,
    *,
    pedestal: Optional[float] = None,
    field_width_degrees: Optional[float] = None,
) -> tuple[Optional[float], dict]:
    """Convert one camera sample directly to SQM-L-equivalent brightness.

    ``field_width_degrees`` is the radiometric field width -- the angular
    width the sampled pixels span, which sets the solid angle every published
    value is divided by. It is a property of the sensor *and* the fitted lens,
    so callers that know the live optical train should pass its field of view;
    an error here biases every radiometric SQM, and one lens step is worth
    ~0.6 mag. Omitting it assumes the sensor's shipped lens.

    A sample carrying ``digital_gain`` is normalised to the gain its profile's
    zero point was fitted at. The gain multiplies the signal above the
    pedestal, so this is one division of the corrected signal. A unit running
    the calibration gain does not move.
    """
    exposure_sec = float(sample["exposure_sec"])
    background = float(sample["background_per_pixel"])
    if pedestal is None:
        pedestal = float(profile.bias_offset)
    if field_width_degrees is None:
        field_width_degrees = optical_train_for_profile(profile).fov_degrees
    signal = background - pedestal
    gain_ratio = digital_gain_ratio(sample, profile)
    signal /= gain_ratio
    details = {
        **sample,
        "pedestal": pedestal,
        "digital_gain_ratio": gain_ratio,
        "background_corrected": signal,
        "radiometric_zero_point": profile.radiometric_zero_point,
        "radiometric_fov_degrees": field_width_degrees,
    }
    if signal <= 1.0:
        details["failure_reason"] = "background_not_resolved_above_pedestal"
        return None, details
    if not profile.radiometric_zero_point or not field_width_degrees:
        details["failure_reason"] = "radiometric_factory_calibration_unavailable"
        return None, details

    # Sky colour sets the sensor-band to V-band conversion, so the effective
    # zero point moves with it. Slope 0 (mono, or an IR-cut sensor with no NIR
    # leak to correct) leaves this a plain constant. R/G is clamped to the
    # calibrated range rather than extrapolated off the end of the fit.
    zero_point = float(profile.radiometric_zero_point)
    slope = float(getattr(profile, "radiometric_colour_slope", 0.0) or 0.0)
    red = sample.get("background_red")
    green = sample.get("background_green")
    if slope and red is not None and green is not None and (green - pedestal) > 1.0:
        ratio = (red - pedestal) / (green - pedestal)
        lo, hi = profile.radiometric_colour_range
        clamped = min(max(ratio, lo), hi)
        zero_point += slope * (clamped - profile.radiometric_colour_pivot)
        details["sky_red_over_green"] = ratio
        details["sky_red_over_green_clamped"] = clamped
    # radiometric_zero_point keeps meaning the profile constant, so archives
    # stay comparable across this change; the applied value is reported
    # alongside it and is always present, corrected or not.
    details["radiometric_zero_point_effective"] = zero_point

    pixels_per_side = int(sample["pixels_per_side"])
    arcsec_squared_per_pixel = (field_width_degrees * 3600.0) ** 2 / pixels_per_side**2
    flux_density = signal / arcsec_squared_per_pixel
    value = zero_point + 2.5 * math.log10(exposure_sec) - 2.5 * math.log10(flux_density)
    details.update(
        {
            "background_flux_density": flux_density,
            "arcsec_squared_per_pixel": arcsec_squared_per_pixel,
            "sqm_radiometric": value,
        }
    )
    return value, details


@dataclass
class RadiometerAccumulator:
    """Small rolling buffer of solve-independent per-frame measurements."""

    max_samples: int = 12
    max_age_seconds: float = 15.0

    def __post_init__(self) -> None:
        self._samples: deque[dict] = deque(maxlen=self.max_samples)
        self._last_sequence: Optional[int] = None

    def add(self, sample: Optional[dict]) -> bool:
        if not sample or "sequence" not in sample:
            return False
        sequence = int(sample["sequence"])
        if self._last_sequence == sequence:
            return False
        self._last_sequence = sequence
        self._samples.append(dict(sample))
        return True

    def estimate(
        self,
        profile,
        now: float,
        pedestal_for_exposure=None,
        field_width_degrees: Optional[float] = None,
    ):
        values = []
        accepted = []
        for sample in self._samples:
            age = now - float(sample["captured_at"])
            if age < 0 or age > self.max_age_seconds:
                continue
            pedestal = (
                pedestal_for_exposure(float(sample["exposure_sec"]))
                if pedestal_for_exposure is not None
                else None
            )
            value, details = radiometric_sqm(
                sample,
                profile,
                pedestal=pedestal,
                field_width_degrees=field_width_degrees,
            )
            if value is not None:
                values.append(value)
                accepted.append(details)
        if not values:
            return None, {"failure_reason": "no_recent_resolved_radiometer_samples"}
        value = float(np.median(values))
        latest = dict(accepted[-1])
        latest.update(
            {
                "sqm_radiometric": value,
                "radiometer_samples": len(values),
                "radiometer_frame_scatter": float(np.std(values)),
            }
        )
        return value, latest

    def dump(self) -> dict:
        """Full JSON-serializable window state for diagnostics/sweeps."""
        return {
            "n_samples": len(self._samples),
            "last_sequence": self._last_sequence,
            "config": {
                "max_samples": self.max_samples,
                "max_age_seconds": self.max_age_seconds,
            },
            "samples": [dict(s) for s in self._samples],
        }

    def reset(self) -> None:
        self._samples.clear()
        self._last_sequence = None
