"""
Transmission diagnostics from stellar zero point, with a cloud/dew guard.

The exposure-normalized zero point (``mzero - 2.5*log10(exposure)``) is a
per-device constant on a clear night: it depends on optics, gain and focus,
not on the sky. Anything between the stars and the sensor attenuates it. The
independent radiometer continues to measure the scene, while this estimator
classifies likely causes:

- **Cloud** dims stars while often brightening a light-polluted sky. It changes
  the scene; the radiometric reading is therefore published without correction.
- **Dew or a dirty lens** dims stars and diffuse sky together at the instrument.
  Once a clear session baseline exists, its stellar deficit can compensate the
  radiometric attenuation.

The discriminator is the independent radiometric sky. Cloud is flagged only
when the zero-point deficit is real and the sky is anomalously bright relative
to the device's learned clear-sky level. Frames with either cloud or a large
non-cloud throughput deficit are withheld from the clear baseline, so a long
cloud/dew episode cannot teach itself away. Factory constants support immediate
cloud diagnostics, but automatic optics compensation additionally requires a
session-conditioned clear baseline because startup cloud versus dew is not
generally identifiable.
"""

import logging
import math
from collections import deque
from typing import Optional

import numpy as np

logger = logging.getLogger("SQM.Clouds")

# Extinction coefficient (mag/airmass), matching the SQM altitude correction.
_K_EXTINCTION = 0.28

# Zero-point deficit above this (mag) is a candidate for cloud.
CLOUD_THRESHOLD = 0.25

# The sky must also be at least this much brighter (mag) than the learned
# clear-sky level for a deficit to count as cloud rather than dew/optics.
SKY_EXCESS_GATE = 0.30


def _airmass(altitude_deg: Optional[float]) -> float:
    """Pickering (2002) airmass; 1.0 when altitude is unknown/invalid."""
    if altitude_deg is None or altitude_deg <= 0:
        return 1.0
    h = altitude_deg + 244.0 / (165.0 + 47.0 * altitude_deg**1.1)
    return 1.0 / math.sin(math.radians(h))


def _median(values) -> float:
    return float(np.median(values))


class CloudEstimator:
    """Clear-sky zero-point baseline and cloud/dew-discriminated deficit."""

    def __init__(
        self,
        clear_zero_point: float = 0.0,
        clear_sky_brightness: float = 0.0,
        max_samples: int = 240,
        min_samples: int = 12,
        smooth_samples: int = 3,
        cloud_threshold: float = CLOUD_THRESHOLD,
        sky_excess_gate: float = SKY_EXCESS_GATE,
    ):
        """
                Args:
                    clear_zero_point: per-sensor clear-sky normalized zero point that
                        seeds the baseline before a session has conditioned its own
                        (boot-under-cloud). 0.0 = no seed (waits for conditioning).
                    clear_sky_brightness: per-sensor typical clear-sky SQM that seeds
                        the sky-excess guard. 0.0 = no seed (guard waits for a learned
        level, i.e. never fires until conditioned).
                    max_samples: rolling window of clear-flagged samples (240 SQM
                        updates ~ 20 min at the 5 s cadence).
                    min_samples: clear-flagged samples needed before the session
                        baseline replaces the factory seed.
                    smooth_samples: the current level is the median of this many latest
                        samples, so one noisy frame cannot raise the flag.
                    cloud_threshold: deficit (mag) above which cloud is possible.
                    sky_excess_gate: sky brightening (mag) required to confirm cloud.
        """
        self.clear_zero_point = clear_zero_point
        self.clear_sky_brightness = clear_sky_brightness
        self.max_samples = max_samples
        self.min_samples = min_samples
        self.smooth_samples = smooth_samples
        self.cloud_threshold = cloud_threshold
        self.sky_excess_gate = sky_excess_gate
        # Recent normalized zero points (all frames) -> current transmission.
        self._recent: deque = deque(maxlen=smooth_samples)
        # Clear-flagged history -> baselines (asymmetric: cloud never feeds).
        self._clear_zp: deque = deque(maxlen=max_samples)
        self._clear_sky: deque = deque(maxlen=max_samples)
        self._deficit: Optional[float] = None
        self._cloudy: Optional[bool] = None

    def add_sample(
        self,
        mzero: float,
        exposure_sec: float,
        sky_brightness: Optional[float] = None,
        wing_correction: float = 0.0,
        altitude_deg: Optional[float] = None,
    ) -> Optional[float]:
        """Record one SQM update; returns the current cloud deficit (mag).

        Args:
            mzero: the frame's photometric zero point (aperture-uncorrected).
            exposure_sec: frame exposure.
            sky_brightness: the frame's published SQM (mag/arcsec²); enables
                the sky-excess guard. None disables the guard for this frame
                (no cloud can be confirmed without it).
            wing_correction: session aperture correction (``-2.5*log10(f)``)
                so focus drift does not masquerade as cloud.
            altitude_deg: pointing altitude for airmass compensation; None
                skips the term (low pointings then read slightly cloudy).
        """
        if mzero is None or not exposure_sec or exposure_sec <= 0:
            return self._deficit
        norm = (
            mzero
            - 2.5 * np.log10(exposure_sec)
            + wing_correction
            + _K_EXTINCTION * (_airmass(altitude_deg) - 1.0)
        )
        self._recent.append(float(norm))

        base = self.baseline()
        current = _median(list(self._recent))
        deficit = None if base is None else max(0.0, base - current)

        sky_level = self.clear_sky_level()
        sky_excess = (
            None
            if (sky_level is None or sky_brightness is None)
            else sky_level - sky_brightness
        )
        cloudy = bool(
            deficit is not None
            and deficit > self.cloud_threshold
            and sky_excess is not None
            and sky_excess > self.sky_excess_gate
        )

        # Only genuinely clear-throughput frames condition the baselines. Cloud
        # and instrument-attenuation candidates must both be excluded or a long
        # dew episode slowly teaches itself away.
        clear_throughput = deficit is None or deficit <= self.cloud_threshold
        if not cloudy and clear_throughput:
            self._clear_zp.append(float(norm))
            if sky_brightness is not None:
                self._clear_sky.append(float(sky_brightness))

        self._deficit = deficit
        self._cloudy = cloudy
        return deficit

    def baseline(self) -> Optional[float]:
        """Clear-sky normalized zero point: session median once conditioned,
        else the factory seed, else None."""
        if len(self._clear_zp) >= self.min_samples:
            return _median(list(self._clear_zp))
        return self.clear_zero_point or None

    def clear_sky_level(self) -> Optional[float]:
        """Learned clear-sky SQM: session median once conditioned, else the
        factory seed, else None."""
        if len(self._clear_sky) >= self.min_samples:
            return _median(list(self._clear_sky))
        return self.clear_sky_brightness or None

    def deficit(self) -> Optional[float]:
        """Last sample's cloud extinction estimate (mag), or None."""
        return self._deficit

    def is_cloudy(self) -> Optional[bool]:
        """Whether the last sample was cloud-affected (deficit AND sky excess),
        or None until a baseline exists."""
        if self._deficit is None:
            return None
        return self._cloudy

    def conditioned(self) -> bool:
        """Whether this session has established its own clear baseline."""
        return len(self._clear_zp) >= self.min_samples

    def reset(self) -> None:
        self._recent.clear()
        self._clear_zp.clear()
        self._clear_sky.clear()
        self._deficit = None
        self._cloudy = None
