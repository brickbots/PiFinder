"""Per-frame airglow floor from the colour of the sky background.

At a dark site the radiometer's background carries a diffuse floor a hand-held
SQM-L does not report: measured on the 2026-07 imx462/HQ reference sweeps it is
~45-70 ADU/s while catalog-calibrated unresolved starlight accounts for only
~3-4 ADU/s of it — the rest fits a single zenith rate through the van Rhijn
law, i.e. it is atmospheric airglow. Airglow varies across the sky and night
to night (the OH bands swing 2-3x with season and solar activity), so no
stored constant or all-sky map can carry it; it must be measured in-session.

The Bayer mosaic supplies that measurement for free. OH airglow lives at
700-1000 nm where every Bayer filter leaks about equally, so an
airglow-dominated background is grey (R = G = B), while visible sky light is
green-peaked: bright LP skies measure R/G = 0.83-0.87, dark airglow-dominated
skies R/G = 1.0. The red excess of the background above the visible-sky colour
line is therefore a direct airglow gauge:

    floor = red_response * max(R_rate - visible_r_over_g * G_rate, 0)

One measured constant (``visible_r_over_g``, the bright-sky background colour)
and one fitted constant (``red_response``) for the test imx462. A deliberately minimal
form: a knob-count ablation under leave-one-night-out cross-validation showed
richer models (fitted colour, two-endmember unmixing with a blue channel)
generalize WORSE — dark-night RMS 0.21-0.23 mag against 0.14 for this form,
with bright skies at 0.08. The fitted ``red_response`` also matches its
physical prior: grey light adds only (NIR_r_over_g - visible_r_over_g) = 0.2
of itself to the red excess, and the SQM-L already sees ~15% of airglow, so
1/0.2 * 0.85 = 4.3 vs 4.07 fitted.

``paired_zero_point`` was calibrated together with ``red_response`` and
replaces the profile ``radiometric_zero_point`` whenever the floor is applied
— using either half of the pairing alone reintroduces a constant offset.

Other cameras are deliberately absent: ``floor_from_sample`` returns None and
the live process does not create a tracker for them.
"""

from __future__ import annotations

from collections import deque
from typing import Optional

import numpy as np

# Calibrated on the 2026-07 imx462 reference archive (22 sweeps over 5 nights):
# leave-one-sweep-out bright/dark RMS 0.08/0.14 mag.
_CAMERA = {
    "imx462": {
        "visible_r_over_g": 0.85,
        "red_response": 4.07,
        "paired_zero_point": 15.19,
    },
}


def paired_zero_point(camera_type: str) -> Optional[float]:
    """Radiometric zero point calibrated together with ``red_response``."""
    cam = _CAMERA.get(camera_type)
    return cam["paired_zero_point"] if cam else None


def calibration(camera_type: str) -> Optional[dict]:
    """Stored airglow calibration constants for a camera (a copy), or None.

    Snapshotting these into a telemetry header keeps a session recomputable if
    the constants change in code later.
    """
    cam = _CAMERA.get(camera_type)
    return dict(cam) if cam is not None else None


def floor_from_sample(
    sample: dict,
    camera_type: str,
    pedestal: float,
) -> Optional[float]:
    """NIR-excess airglow floor (ADU/s) for one radiometer sample.

    Needs the per-channel red background ``collect_radiometer_sample`` records
    on Bayer sensors (``background_red``); returns None on mono sensors or
    incomplete samples, so callers fall back to their static floor.
    """
    cam = _CAMERA.get(camera_type)
    if cam is None:
        return None
    red = sample.get("background_red")
    exposure = sample.get("exposure_sec")
    if red is None or not exposure or exposure <= 0:
        return None
    green_rate = (float(sample["background_per_pixel"]) - pedestal) / exposure
    red_rate = (float(red) - pedestal) / exposure
    excess = red_rate - cam["visible_r_over_g"] * green_rate
    return cam["red_response"] * max(excess, 0.0)


def sample_diagnostics(sample: dict, camera_type: str, pedestal: float) -> dict:
    """Return every intermediate used by the experimental colour correction."""
    result = {
        "camera_type": camera_type,
        "sequence": sample.get("sequence"),
        "captured_at": sample.get("captured_at"),
        "exposure_sec": sample.get("exposure_sec"),
        "pedestal": float(pedestal),
        "valid": False,
    }
    cam = _CAMERA.get(camera_type)
    if cam is None:
        result["failure_reason"] = "camera_not_calibrated"
        return result
    exposure = sample.get("exposure_sec")
    red = sample.get("background_red")
    green = sample.get("background_per_pixel")
    blue = sample.get("background_blue")
    if red is None or green is None or not exposure or exposure <= 0:
        result["failure_reason"] = "colour_sample_incomplete"
        return result

    exposure = float(exposure)
    red_rate = (float(red) - pedestal) / exposure
    green_rate = (float(green) - pedestal) / exposure
    blue_rate = (float(blue) - pedestal) / exposure if blue is not None else None
    excess = red_rate - cam["visible_r_over_g"] * green_rate
    clipped = max(excess, 0.0)
    correction = cam["red_response"] * clipped
    result.update(
        {
            "valid": True,
            "background_red": float(red),
            "background_green": float(green),
            "background_blue": float(blue) if blue is not None else None,
            "red_rate": red_rate,
            "green_rate": green_rate,
            "blue_rate": blue_rate,
            "red_over_green": red_rate / green_rate if green_rate > 0 else None,
            "blue_over_green": (
                blue_rate / green_rate
                if blue_rate is not None and green_rate > 0
                else None
            ),
            "visible_r_over_g": cam["visible_r_over_g"],
            "red_excess_unclipped": excess,
            "red_excess_clipped": clipped,
            "red_response": cam["red_response"],
            "correction_adu_per_sec": correction,
            "paired_zero_point": cam["paired_zero_point"],
        }
    )
    return result


class AirglowTracker:
    """Rolling median of per-frame airglow floors for a stable estimate.

    Single frames are shot-noise limited at short exposures; the tracker
    medians the recent per-frame floors the same way the radiometer
    accumulator medians its SQM samples.
    """

    def __init__(self, camera_type: str, max_samples: int = 12):
        self.camera_type = camera_type
        self.max_samples = max_samples
        self._samples: deque[dict] = deque(maxlen=max_samples)

    def add_sample(self, sample: dict, pedestal: float) -> Optional[float]:
        stored = sample.get("airglow_diagnostic")
        diagnostic = (
            dict(stored)
            if stored is not None
            else sample_diagnostics(sample, self.camera_type, pedestal)
        )
        if not diagnostic["valid"]:
            return None
        self._samples.append(diagnostic)
        return diagnostic["correction_adu_per_sec"]

    def floor(self) -> Optional[float]:
        if not self._samples:
            return None
        return float(
            np.median([sample["correction_adu_per_sec"] for sample in self._samples])
        )

    def dump(self) -> dict:
        """Full JSON-serializable state for post-observation replay."""
        floors = [sample["correction_adu_per_sec"] for sample in self._samples]
        return {
            "camera_type": self.camera_type,
            "n_samples": len(self._samples),
            "max_samples": self.max_samples,
            "floor": self.floor(),
            "floor_stddev": float(np.std(floors)) if floors else None,
            "floor_min": min(floors) if floors else None,
            "floor_max": max(floors) if floors else None,
            "samples": list(self._samples),
        }

    def reset(self) -> None:
        self._samples.clear()
