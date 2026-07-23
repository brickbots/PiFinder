"""
Black-level (pedestal) tracking from the sky-vs-exposure relation.

The sensor background is linear in exposure:

    background_per_pixel = bias_offset + (dark_current + sky_rate) * exposure

so the intercept of ``background_per_pixel`` against ``exposure`` is the
electronic pedestal at zero exposure — the sensor's true black level right
now, no lens cap or dark frame required. The auto-exposure loop naturally
varies the exposure (around slews and sky-brightness changes), which supplies
the lever arm for the fit.

This matters because the profile ``bias_offset`` is a static constant while
the real black level wanders ±2 ADU night to night (sensor temperature the
suspect). That wander is negligible against a bright city background but worth
0.2–0.4 mag at a dark site, where it must be tracked. Measured on the 2026-07
archive ramps, the intercept fit recovers each night's pedestal to
±0.06–0.6 ADU.

The fit is only trusted when the sky held still while the samples were taken:
a drifting sky (twilight, moonrise, cloud) breaks the single-line model and
inflates the intercept's standard error, which the ``max_intercept_stderr``
gate rejects. The caller additionally withholds samples taken through cloud
(``stable=False``). Until a confident fit exists, ``pedestal()`` returns
``None`` and the caller falls back to the profile constant.
"""

import logging
import time
from collections import deque
from typing import Optional, Tuple

import numpy as np

logger = logging.getLogger("SQM.BlackLevel")


class BlackLevelTracker:
    """Rolling estimate of the sensor pedestal from (exposure, background)."""

    def __init__(
        self,
        bias_offset: float,
        min_samples: int = 12,
        max_samples: int = 60,
        min_exposure_ratio: float = 1.5,
        max_intercept_stderr: float = 0.6,
        max_offset_deviation: float = 12.0,
        max_age_seconds: float = 900.0,
    ):
        """
        Args:
            bias_offset: profile pedestal; the fit is rejected if it strays
                more than ``max_offset_deviation`` from this sanity anchor.
            min_samples: samples needed before a fit is attempted.
            max_samples: rolling window of (exposure, background) pairs.
            min_exposure_ratio: max/min exposure in the window must exceed this
                — without a lever arm the intercept is an unreliable
                extrapolation (and its stderr gate would reject it anyway).
            max_intercept_stderr: reject the fit when the intercept's standard
                error exceeds this (ADU). A stable sky sits at 0.1–0.6; a
                drifting sky blows past 1.0.
            max_offset_deviation: reject a fitted pedestal further than this
                (ADU) from the profile constant — a guard against a
                pathological fit driving the pedestal to nonsense.
            max_age_seconds: an accepted pedestal expires after this long
                without a fresh accepting refit. Prevents one plausible-but-
                wrong fit (e.g. accepted through smooth cloud drift, observed
                2026-07-17) from ruling a whole session; expiry falls back to
                the profile constant.
        """
        self.bias_offset = bias_offset
        self.min_samples = min_samples
        self.min_exposure_ratio = min_exposure_ratio
        self.max_intercept_stderr = max_intercept_stderr
        self.max_offset_deviation = max_offset_deviation
        self.max_age_seconds = max_age_seconds
        self._samples: deque = deque(maxlen=max_samples)
        self._pedestal: Optional[float] = None
        self._stderr: Optional[float] = None
        self._accepted_at: Optional[float] = None

    def add_sample(
        self,
        exposure_sec: float,
        background_per_pixel: float,
        stable: bool = True,
    ) -> None:
        """Record one frame's raw (pre-pedestal) background and refit.

        Args:
            exposure_sec: frame exposure.
            background_per_pixel: median sky background in ADU *before*
                pedestal subtraction (``details['background_per_pixel']``).
            stable: False when transmission is changing (cloud) — the sample
                is dropped so a moving sky cannot corrupt the intercept.
        """
        if (
            not stable
            or exposure_sec is None
            or exposure_sec <= 0
            or background_per_pixel is None
            or not np.isfinite(background_per_pixel)
        ):
            return
        self._samples.append((float(exposure_sec), float(background_per_pixel)))
        self._refit()

    def _refit(self) -> None:
        if len(self._samples) < self.min_samples:
            self._pedestal = None
            self._stderr = None
            return
        exps = np.array([s[0] for s in self._samples], dtype=np.float64)
        bgs = np.array([s[1] for s in self._samples], dtype=np.float64)
        if exps.min() <= 0 or exps.max() / exps.min() < self.min_exposure_ratio:
            return  # no lever arm; keep the prior estimate
        n = len(exps)
        xbar = exps.mean()
        sxx = float(np.sum((exps - xbar) ** 2))
        if sxx <= 0:
            return
        slope, intercept = np.polyfit(exps, bgs, 1)
        if slope < 0:
            # Background cannot fall as exposure rises; the samples are not a
            # clean sky ramp (blend of fields/conditions). Reject.
            return
        resid = bgs - (intercept + slope * exps)
        dof = n - 2
        s = float(np.sqrt(np.sum(resid**2) / dof)) if dof > 0 else float("inf")
        stderr = s * float(np.sqrt(1.0 / n + xbar**2 / sxx))
        if stderr > self.max_intercept_stderr:
            return  # sky was drifting; keep the prior estimate
        if abs(intercept - self.bias_offset) > self.max_offset_deviation:
            logger.debug(
                "Black-level fit %.1f rejected: %.1f ADU from profile %.1f",
                intercept,
                abs(intercept - self.bias_offset),
                self.bias_offset,
            )
            return
        if abs(intercept - self.bias_offset) > 2.0 and (
            self._pedestal is None or abs(intercept - self._pedestal) > 0.25
        ):
            # A tracked level this far from the static bias is exactly the
            # case the tracker exists for — worth a visible trace.
            logger.info(
                "Tracked black level %.2f ADU (static bias %.1f, stderr %.2f)",
                intercept,
                self.bias_offset,
                stderr,
            )
        self._pedestal = float(intercept)
        self._stderr = stderr
        self._accepted_at = time.monotonic()

    def pedestal(self) -> Optional[float]:
        """Current fitted black level (ADU), or None until a confident fit.

        An accepted fit is a lease, not a latch: unless a fresh fit passes
        within ``max_age_seconds`` its evidence has aged out of the window
        unreplaced, and callers fall back to the profile constant — the same
        state every session starts in.
        """
        if self._pedestal is None or self._accepted_at is None:
            return None
        if time.monotonic() - self._accepted_at > self.max_age_seconds:
            return None
        return self._pedestal

    def stderr(self) -> Optional[float]:
        """Standard error of the current intercept (ADU), or None."""
        return self._stderr

    def state(self) -> Tuple[Optional[float], Optional[float], int]:
        """(pedestal, stderr, n_samples) for diagnostics."""
        return self._pedestal, self._stderr, len(self._samples)

    def dump(self) -> dict:
        """Full JSON-serializable window state for diagnostics/sweeps."""
        return {
            "pedestal": self.pedestal(),
            "stderr": self._stderr,
            "n_samples": len(self._samples),
            "age_seconds": (
                time.monotonic() - self._accepted_at
                if self._accepted_at is not None
                else None
            ),
            "config": {
                "bias_offset": self.bias_offset,
                "min_samples": self.min_samples,
                "max_samples": self._samples.maxlen,
                "min_exposure_ratio": self.min_exposure_ratio,
                "max_intercept_stderr": self.max_intercept_stderr,
                "max_offset_deviation": self.max_offset_deviation,
                "max_age_seconds": self.max_age_seconds,
            },
            "samples_exposure_sec": [s[0] for s in self._samples],
            "samples_background_per_pixel": [s[1] for s in self._samples],
        }

    def reset(self) -> None:
        self._samples.clear()
        self._pedestal = None
        self._stderr = None
        self._accepted_at = None
