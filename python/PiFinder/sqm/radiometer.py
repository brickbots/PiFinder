"""Solve-independent, low-cost radiometric sky measurements.

The camera process reduces each raw frame to a small scalar sample while the
matrix is already local.  The solver process can then aggregate and publish SQM
without copying/scanning the raw frame and without requiring a plate solve.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Optional

import numpy as np


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


def extract_bayer_rb(raw, profile) -> Optional[tuple[np.ndarray, np.ndarray]]:
    """Return the (red, blue) Bayer planes as ``float32``, or None for mono.

    The background's colour is a per-frame airglow gauge (see ``airglow``):
    OH airglow lives at 700-1000 nm where every Bayer filter leaks equally, so
    an airglow-dominated background is grey (R = G = B) while visible sky light
    is green-peaked. The green plane alone cannot see that difference.
    """
    if raw is None:
        return None
    arr = np.asarray(raw)
    if arr.ndim != 2 or not str(profile.format).upper().startswith("SRGGB"):
        return None
    height, width = arr.shape
    if height < 2 or width < 2:
        return None
    red = arr[0 : height - height % 2 : 2, 0 : width - width % 2 : 2]
    blue = arr[1:height:2, 1:width:2]
    return red.astype(np.float32), blue.astype(np.float32)


def collect_radiometer_sample(
    raw,
    profile,
    exposure_sec: float,
    *,
    sequence: int,
    captured_at: float,
    border_fraction: float = 0.10,
    stride: int = 4,
    optical_black_pedestal: Optional[float] = None,
) -> Optional[dict]:
    """Reduce a raw frame to a robust sky-background sample.

    A deterministic sparse grid keeps the per-frame camera-process cost small.
    The outer ten percent is excluded to reduce corner-vignetting bias. Stars
    occupy far below half the grid, so the median rejects them without building
    a source mask. Four quadrant medians provide a cheap gradient diagnostic.
    """
    if not exposure_sec or exposure_sec <= 0 or stride < 1:
        return None
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

    background_red = background_blue = None
    rb = extract_bayer_rb(raw, profile)
    if rb is not None:
        red, blue = rb
        for name, plane in (("red", red), ("blue", blue)):
            b_y = int(plane.shape[0] * border_fraction)
            b_x = int(plane.shape[1] * border_fraction)
            grid = plane[
                b_y : plane.shape[0] - b_y : stride, b_x : plane.shape[1] - b_x : stride
            ]
            if grid.size >= 64:
                if name == "red":
                    background_red = float(np.median(grid))
                else:
                    background_blue = float(np.median(grid))

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
    if background_red is not None:
        sample["background_red"] = background_red
    if background_blue is not None:
        sample["background_blue"] = background_blue
    if optical_black_pedestal is not None and np.isfinite(optical_black_pedestal):
        sample["optical_black_pedestal"] = float(optical_black_pedestal)
    return sample


def radiometric_sqm(
    sample: dict,
    profile,
    *,
    pedestal: Optional[float] = None,
    floor: float = 0.0,
    zero_point: Optional[float] = None,
) -> tuple[Optional[float], dict]:
    """Convert one camera sample directly to SQM-L-equivalent brightness.

    ``floor`` is the expected diffuse-background rate (ADU/s) for this pointing
    — integrated starlight, airglow, zodiacal — that a hand-held reference does
    not see the same way (see ``skyglow_map``). It accumulates with exposure
    like the sky, so ``floor * exposure`` is removed from the signal before the
    magnitude conversion. Zero (the default) leaves the pre-floor behaviour.
    """
    exposure_sec = float(sample["exposure_sec"])
    background = float(sample["background_per_pixel"])
    optical_black = sample.get("optical_black_pedestal")
    if optical_black is not None and np.isfinite(optical_black):
        # Shielded pixels from the same frame already contain bias plus the
        # frame's accumulated dark signal, so a valid OB value is the complete
        # pedestal.  Calibrated or tracked pedestals only apply without OB.
        pedestal = float(optical_black)
        pedestal_source = "optical_black"
    elif pedestal is not None:
        pedestal_source = "calibrated"
    else:
        pedestal = float(profile.bias_offset)
        pedestal_source = "profile"
    signal = background - pedestal - floor * exposure_sec
    effective_zero_point = (
        float(zero_point)
        if zero_point is not None
        else float(profile.radiometric_zero_point)
    )
    details = {
        **sample,
        "pedestal": pedestal,
        "pedestal_source": pedestal_source,
        "skyglow_floor": floor,
        "background_corrected": signal,
        "radiometric_zero_point": effective_zero_point,
        "radiometric_fov_degrees": profile.radiometric_fov_degrees,
    }
    if signal <= 1.0:
        details["failure_reason"] = "background_not_resolved_above_pedestal"
        return None, details
    if not effective_zero_point or not profile.radiometric_fov_degrees:
        details["failure_reason"] = "radiometric_factory_calibration_unavailable"
        return None, details

    pixels_per_side = int(sample["pixels_per_side"])
    arcsec_squared_per_pixel = (
        profile.radiometric_fov_degrees * 3600.0
    ) ** 2 / pixels_per_side**2
    flux_density = signal / arcsec_squared_per_pixel
    value = (
        effective_zero_point
        + 2.5 * math.log10(exposure_sec)
        - 2.5 * math.log10(flux_density)
    )
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
        self, profile, now: float, pedestal_for_exposure=None, floor: float = 0.0
    ):
        values = []
        accepted = []
        for sample in self._samples:
            age = now - float(sample["captured_at"])
            if age < 0 or age > self.max_age_seconds:
                continue
            pedestal = sample.get("paired_pedestal")
            if pedestal is None and pedestal_for_exposure is not None:
                pedestal = pedestal_for_exposure(float(sample["exposure_sec"]))
            sample_floor = float(sample.get("spectral_floor", floor))
            sample_zero_point = sample.get("paired_radiometric_zero_point")
            value, details = radiometric_sqm(
                sample,
                profile,
                pedestal=pedestal,
                floor=sample_floor,
                zero_point=sample_zero_point,
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
