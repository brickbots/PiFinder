"""
Cloud detection from the photometric zero point.

The exposure-normalized zero point (``mzero - 2.5*log10(exposure)``) is a
per-device constant on a clear night: it depends on optics, gain and focus,
not on the sky. Clouds attenuate the calibration stars, so the zero point
drops by exactly the cloud extinction — while sky glow (moonlight, light
pollution) leaves it untouched, because glow brightens the background, not
the stars. That makes the zero point a live transmission monitor:

- **Baseline**: a high percentile of recent normalized zero points, i.e. the
  best transmission seen lately. Samples are compensated for airmass (low
  pointings genuinely dim stars) and for the session aperture correction
  (focus drift moves the zero point; the wing estimator already measures it).
- **Deficit**: baseline minus the current sample = magnitudes of cloud
  extinction right now. Above ``CLOUD_THRESHOLD`` the SQM reading is flagged
  cloud-affected. The deficit is also the correction a star-calibrated SQM
  needs under cloud: the zero point was measured through the cloud but the
  (mostly light-pollution) glow originates below it, so the reported sky is
  too bright by roughly the deficit.

Measured on the 2026-07 archive: clear-night baseline stable to ±0.09 over
six nights (imx462); cloud deficits of 0.25/0.71/0.73 against SQM-vs-meter
errors of 0.46/0.60/0.65. Solid detection from ~0.3 mag of cloud; light haze
(~0.2) sits at the noise edge.
"""

import logging
import math
from collections import deque
from typing import Optional

import numpy as np

logger = logging.getLogger("SQM.Clouds")

# Extinction coefficient (mag/airmass), matching the SQM altitude correction.
_K_EXTINCTION = 0.28

# Deficits above this are reported as cloud (mag).
CLOUD_THRESHOLD = 0.2


def _airmass(altitude_deg: Optional[float]) -> float:
    """Pickering (2002) airmass; 1.0 when altitude is unknown/invalid."""
    if altitude_deg is None or altitude_deg <= 0:
        return 1.0
    h = altitude_deg + 244.0 / (165.0 + 47.0 * altitude_deg**1.1)
    return 1.0 / math.sin(math.radians(h))


class CloudEstimator:
    """Rolling clear-sky zero-point baseline and per-sample cloud deficit."""

    def __init__(
        self,
        max_samples: int = 240,
        min_samples: int = 12,
        baseline_percentile: float = 85.0,
        smooth_samples: int = 3,
    ):
        """
        Args:
            max_samples: rolling window of normalized zero points (240 SQM
                updates ~ 20 min at the 5 s cadence).
            min_samples: samples needed before deficits are reported; the
                estimator needs some recent history to know "clear".
            baseline_percentile: percentile of the window taken as the
                clear-sky baseline (high = best transmission seen lately;
                not the max, so a single noisy sample cannot set it).
            smooth_samples: the current level is the median of this many
                latest samples, so one noisy frame cannot raise the flag.
        """
        self.max_samples = max_samples
        self.min_samples = min_samples
        self.baseline_percentile = baseline_percentile
        self.smooth_samples = smooth_samples
        self._samples: deque = deque(maxlen=max_samples)

    def add_sample(
        self,
        mzero: float,
        exposure_sec: float,
        wing_correction: float = 0.0,
        altitude_deg: Optional[float] = None,
    ) -> Optional[float]:
        """Record one SQM update's zero point; returns the current deficit.

        Args:
            mzero: the frame's photometric zero point (aperture-uncorrected).
            exposure_sec: frame exposure.
            wing_correction: session aperture correction (``-2.5*log10(f)``)
                so focus drift does not masquerade as cloud.
            altitude_deg: pointing altitude for airmass compensation; None
                skips the term (conservative: low pointings then read as
                slightly cloudy rather than clear).
        """
        if mzero is None or not exposure_sec or exposure_sec <= 0:
            return None
        norm = (
            mzero
            - 2.5 * np.log10(exposure_sec)
            + wing_correction
            + _K_EXTINCTION * (_airmass(altitude_deg) - 1.0)
        )
        self._samples.append(float(norm))
        return self.deficit()

    def baseline(self) -> Optional[float]:
        """Clear-sky normalized zero point, or None until conditioned."""
        if len(self._samples) < self.min_samples:
            return None
        return float(np.percentile(self._samples, self.baseline_percentile))

    def deficit(self) -> Optional[float]:
        """Current cloud extinction estimate (mag), or None until conditioned.

        Clamped at 0: readings above baseline are the baseline improving,
        not negative cloud.
        """
        base = self.baseline()
        if base is None:
            return None
        n = min(self.smooth_samples, len(self._samples))
        current = float(np.median(list(self._samples)[-n:]))
        return max(0.0, base - current)

    def is_cloudy(self) -> Optional[bool]:
        """True when the current deficit exceeds CLOUD_THRESHOLD; None until
        conditioned."""
        d = self.deficit()
        if d is None:
            return None
        return d > CLOUD_THRESHOLD

    def reset(self) -> None:
        self._samples.clear()
