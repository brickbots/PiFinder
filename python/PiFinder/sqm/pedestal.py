"""
Per-frame pedestal (black-level) estimator for SQM.

SQM subtracts a pedestal from the measured sky background before converting it
to a surface brightness. A *static* ``bias_offset`` that doesn't match the real
black level leaves a constant residual that does not scale with exposure, so it
never cancels the exposure-dependence in the star zero point -- the measured SQM
then dives at short exposures and plateaus at long ones.

Auto-exposure varies the exposure time continuously, so the stream of
``(exposure_sec, background_per_pixel)`` samples lets us fit

    background = P0 + rate * exposure_sec

and recover the true black level ``P0`` directly. This is self-calibrating and
tracks slow drift (temperature, sky) without any hand-tuned constant.

The fit needs samples spanning a range of exposures to be conditioned; until
then the caller falls back to the profile ``bias_offset``.
"""

import logging
from collections import deque
from typing import Optional

import numpy as np

logger = logging.getLogger("SQM.Pedestal")


class PedestalEstimator:
    """Rolling least-squares fit of black level from (exposure, background)."""

    def __init__(
        self,
        max_samples: int = 40,
        min_samples: int = 6,
        min_exposure_ratio: float = 2.0,
    ):
        """
        Args:
            max_samples: rolling window size.
            min_samples: minimum samples before a fit is attempted.
            min_exposure_ratio: required max/min exposure span for a conditioned
                fit (a flat exposure range can't separate P0 from rate).
        """
        self.max_samples = max_samples
        self.min_samples = min_samples
        self.min_exposure_ratio = min_exposure_ratio
        self._exp: deque = deque(maxlen=max_samples)
        self._bg: deque = deque(maxlen=max_samples)
        self._p0: Optional[float] = None

    def add(self, exposure_sec: float, background_per_pixel: float) -> None:
        """Record a new (exposure, measured background) sample."""
        if exposure_sec is None or exposure_sec <= 0:
            return
        if background_per_pixel is None or not np.isfinite(background_per_pixel):
            return
        self._exp.append(float(exposure_sec))
        self._bg.append(float(background_per_pixel))
        self._refit()

    def _refit(self) -> None:
        n = len(self._exp)
        if n < self.min_samples:
            return
        exp = np.asarray(self._exp)
        bg = np.asarray(self._bg)
        if exp.min() <= 0 or exp.max() / exp.min() < self.min_exposure_ratio:
            return  # exposure span too narrow to separate pedestal from slope

        # Robust-ish: one ordinary fit, drop the worst residuals, refit once.
        A = np.vstack([np.ones_like(exp), exp]).T
        coef, *_ = np.linalg.lstsq(A, bg, rcond=None)
        resid = bg - A @ coef
        keep = np.abs(resid) <= 3.0 * (np.median(np.abs(resid)) * 1.4826 + 1e-9)
        if keep.sum() >= self.min_samples and not keep.all():
            coef, *_ = np.linalg.lstsq(A[keep], bg[keep], rcond=None)

        p0 = float(coef[0])
        if np.isfinite(p0):
            self._p0 = p0

    def pedestal(self, fallback: float) -> float:
        """Best pedestal estimate, or ``fallback`` until the fit is conditioned."""
        return self._p0 if self._p0 is not None else fallback

    @property
    def is_conditioned(self) -> bool:
        return self._p0 is not None

    def reset(self) -> None:
        self._exp.clear()
        self._bg.clear()
        self._p0 = None
