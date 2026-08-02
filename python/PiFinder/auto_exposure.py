#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Auto-exposure PID controller for optimizing star detection.

This module implements a PID (Proportional-Integral-Derivative) controller
that automatically adjusts camera exposure time to maintain an optimal number
of detected stars for plate solving.

The controller targets 17 matched stars (acceptable range: 12-22) which provides
reliable plate solving while avoiding over-saturation and maintaining good performance.
Rate limiting on downward adjustments reduces CPU usage.

When a solve attempt matches nothing, control delegates to ZeroMatchRecovery,
which walks a fixed exposure ladder until matches return (see ADR 0010).
"""

import logging
import time
from typing import List, Optional

import numpy as np
from PIL import Image

logger = logging.getLogger("AutoExposure")


def generate_exposure_sweep(
    min_exposure: int, max_exposure: int, num_steps: int
) -> List[int]:
    """
    Generate logarithmically-spaced exposure values for sweeps.

    Used by the diagnostic exposure sweep capture in the Experimental menu
    (camera_interface.py), which captures ~100 image pairs across the exposure
    range for offline analysis. This is unrelated to zero-match recovery, which
    walks a fixed ladder (see ZeroMatchRecovery / ADR 0010).

    Args:
        min_exposure: Minimum exposure in microseconds
        max_exposure: Maximum exposure in microseconds
        num_steps: Number of exposure values to generate

    Returns:
        List of exposure values in microseconds, logarithmically spaced
    """
    exposures = (
        np.logspace(np.log10(min_exposure), np.log10(max_exposure), num_steps)
        .astype(int)
        .tolist()
    )

    return exposures


# Recovery ladder (microseconds). The ordering encodes the night-time prior:
# start at the known-safe shipped default, climb to longer exposures first
# (too-dark dominates at night), then try one short rung. Floored at 200 ms
# per ADR 0010 -- below that a frame is unlikely to pick up enough stars to
# solve, even under a bright sky. The floor bounds recovery's blind search
# only; the match-count controller's feedback clamp still reaches 25 ms.
RECOVERY_LADDER = [400000, 800000, 1000000, 200000]


class ZeroMatchRecovery:
    """
    Zero-match recovery: the escape hatch when a solve attempt matches nothing.

    Walks the recovery ladder, trying each rung a fixed number of times and
    wrapping around until matches return. The match-count controller delegates
    here when matched stars hit zero.

    Its responsibility is exactly one failure cause: the exposure being badly
    wrong (dusk/dawn, slew into bright sky, returning from daytime alignment).
    Defocus, transient blockage, and solver-side failures are deliberately out
    of scope -- no exposure change fixes those. See ADR 0010.
    """

    def __init__(
        self,
        trigger_count: int = 2,
        repeats_per_exposure: int = 2,
    ):
        """
        Initialize zero-match recovery.

        Args:
            trigger_count: Consecutive zero-match solves before activating.
            repeats_per_exposure: Solve attempts to spend on each ladder rung.
        """
        self._active = False
        self._trigger_count = trigger_count
        self._repeats_per_exposure = repeats_per_exposure
        self._ladder = list(RECOVERY_LADDER)
        self._exposure_index = 0
        self._repeat_count = 0

        logger.info(
            f"ZeroMatchRecovery initialized: trigger after {trigger_count} "
            f"zero-match solves, ladder {self._ladder}µs"
        )

    def is_active(self) -> bool:
        return self._active

    def handle(self, current_exposure: int, zero_count: int) -> Optional[int]:
        """
        Advance recovery for a zero-match solve.

        Args:
            current_exposure: Current exposure time in microseconds.
            zero_count: Number of consecutive zero-match solves.

        Returns:
            Next exposure to try, or None while waiting for the trigger.
        """
        # Wait for trigger count
        if zero_count < self._trigger_count:
            logger.debug(
                f"Zero matches: {zero_count}/{self._trigger_count} before recovery activation"
            )
            return None

        # Activate if not already active
        if not self._active:
            self._active = True
            logger.debug(
                f"Recovery activated after {zero_count} zero-match solves "
                f"(stuck at {current_exposure}µs)"
            )

        # Walk the ladder
        return self._next_exposure()

    def _next_exposure(self) -> int:
        result = self._ladder[self._exposure_index]

        attempt_number = self._repeat_count + 1
        logger.debug(
            f"Recovery: trying {result}µs "
            f"({attempt_number}/{self._repeats_per_exposure})"
        )

        # Update state for next call
        self._repeat_count += 1
        if self._repeat_count >= self._repeats_per_exposure:
            # Completed all repeats, advance to next rung
            self._repeat_count = 0
            self._exposure_index += 1

            # Wrap around to start of ladder
            if self._exposure_index >= len(self._ladder):
                self._exposure_index = 0
                logger.debug(
                    f"Recovery: ladder complete, restarting from {self._ladder[0]}µs"
                )
            else:
                next_exposure = self._ladder[self._exposure_index]
                logger.debug(f"Recovery: advancing to {next_exposure}µs")

        return result

    def reset(self) -> None:
        self._active = False
        self._exposure_index = 0
        self._repeat_count = 0
        logger.debug("ZeroMatchRecovery reset")


class ExposureSNRController:
    """
    SNR-based auto exposure for SQM measurements.

    Targets a minimum background SNR and exposure time instead of star count.
    This provides more stable, longer exposures that are better for accurate
    SQM measurements compared to the histogram-based approach.

    Strategy:
    - Target specific background level above noise floor
    - Derive thresholds from camera profile (bit depth, bias offset)
    - Slower adjustments for stability
    """

    def __init__(
        self,
        min_exposure: int = 10000,  # 10ms minimum
        max_exposure: int = 1000000,  # 1.0s maximum
        target_background: int = 30,  # Target background level in ADU
        min_background: int = 15,  # Minimum acceptable background
        max_background: int = 100,  # Maximum before saturating
        adjustment_factor: float = 1.3,  # Gentle adjustments (30% steps)
    ):
        """
        Initialize SNR-based auto exposure.

        Args:
            min_exposure: Minimum exposure in microseconds (default 10ms)
            max_exposure: Maximum exposure in microseconds (default 1000ms)
            target_background: Target median background level in ADU
            min_background: Minimum acceptable background (increase if below)
            max_background: Maximum acceptable background (decrease if above)
            adjustment_factor: Multiplicative adjustment step (default 1.3 = 30%)
        """
        self.min_exposure = min_exposure
        self.max_exposure = max_exposure
        self.target_background = target_background
        self.min_background = min_background
        self.max_background = max_background
        self.adjustment_factor = adjustment_factor

        logger.info(
            f"AutoExposure SNR: target_bg={target_background}, "
            f"range=[{min_background}, {max_background}] ADU, "
            f"exp_range=[{min_exposure / 1000:.0f}, {max_exposure / 1000:.0f}]ms, "
            f"adjustment={adjustment_factor}x"
        )

    def update(
        self,
        current_exposure: int,
        image: Image.Image,
        noise_floor: Optional[float] = None,
        **kwargs,  # Ignore other params (matched_stars, etc.)
    ) -> Optional[int]:
        """
        Update exposure based on background level.

        Args:
            current_exposure: Current exposure in microseconds
            image: Current image for analysis
            noise_floor: Processed-image floor in 8-bit ADU (if available)
            **kwargs: Ignored (for compatibility with PID interface)

        Returns:
            New exposure in microseconds, or None if no change needed
        """
        # This controller measures the processed 8-bit image. Do not pass it a
        # raw-sensor SQM pedestal: those values are in different units.
        # Need margin above noise floor so background_corrected isn't near zero
        if noise_floor is not None:
            min_bg = noise_floor + 2
        else:
            min_bg = self.min_background

        # Analyze image
        if image.mode != "L":
            image = image.convert("L")
        img_array = np.asarray(image, dtype=np.float32)

        # Use 10th percentile as background estimate (dark pixels)
        background = float(np.percentile(img_array, 10))

        logger.debug(
            f"SNR AE: bg={background:.1f}, min={min_bg:.1f} ADU, exp={current_exposure / 1000:.0f}ms"
        )

        # Determine adjustment
        new_exposure = None

        if background < min_bg:
            # Too dark - increase exposure
            new_exposure = int(current_exposure * self.adjustment_factor)
            logger.info(
                f"SNR AE: Background too low ({background:.1f} < {min_bg:.1f}), "
                f"increasing exposure {current_exposure / 1000:.0f}ms → {new_exposure / 1000:.0f}ms"
            )
        elif background > self.max_background:
            # Too bright - decrease exposure
            new_exposure = int(current_exposure / self.adjustment_factor)
            logger.info(
                f"SNR AE: Background too high ({background:.1f} > {self.max_background}), "
                f"decreasing exposure {current_exposure / 1000:.0f}ms → {new_exposure / 1000:.0f}ms"
            )
        else:
            # Background is in acceptable range
            logger.debug(f"SNR AE: OK (bg={background:.1f} ADU)")
            return None

        # Clamp to limits
        new_exposure = max(self.min_exposure, min(self.max_exposure, new_exposure))
        return new_exposure

    def get_status(self) -> dict:
        return {
            "mode": "SNR",
            "target_background": self.target_background,
            "min_background": self.min_background,
            "max_background": self.max_background,
            "min_exposure": self.min_exposure,
            "max_exposure": self.max_exposure,
        }


class ExposurePIDController:
    """
    PID controller for automatic camera exposure adjustment.

    The controller adjusts exposure time based on the number of stars
    detected during plate solving, targeting an optimal count for
    reliable solving performance.
    """

    def __init__(
        self,
        target_stars: int = 17,
        gains_decrease: tuple = (
            500.0,  # Kp: Conservative (was 2000, reduced 75% to prevent crash)
            5.0,  # Ki: Minimal (was 10, reduced to prevent drift)
            250.0,  # Kd: Proportional (was 750, reduced 67%)
        ),  # Kp, Ki, Kd for too many stars (conservative descent)
        gains_increase: tuple = (
            4000.0,  # Kp: Moderate aggression (was 8000, reduced 50%)
            250.0,  # Ki: Moderate (was 500, reduced 50%)
            1500.0,  # Kd: Moderate (was 3000, reduced 50%)
        ),  # Kp, Ki, Kd for too few stars (faster ascent)
        min_exposure: int = 25000,
        max_exposure: int = 1000000,
        deadband: int = 5,
        update_interval: float = 0.5,  # Minimum seconds between decreasing adjustments
        recovery: Optional[ZeroMatchRecovery] = None,
    ):
        """
        Initialize PID controller with asymmetric gains.

        Uses conservative gains when decreasing exposure (gentle descent),
        aggressive gains when increasing (fast recovery).
        """
        self.target_stars = target_stars
        self.gains_decrease = gains_decrease
        self.gains_increase = gains_increase
        self.min_exposure = min_exposure
        self.max_exposure = max_exposure
        self.deadband = deadband
        self.update_interval = update_interval

        self._integral = 0.0
        self._last_error: Optional[float] = None
        self._zero_match_count = 0
        self._nonzero_match_count = 0  # Hysteresis: consecutive non-zero solves
        self._last_adjustment_time = 0.0
        self._recovery = recovery or ZeroMatchRecovery()

        logger.info(
            f"AutoExposure PID: target={target_stars}, deadband={deadband}, "
            f"update_interval={update_interval}s, "
            f"gains_dec={gains_decrease}, gains_inc={gains_increase}, "
            f"range=[{min_exposure}, {max_exposure}]µs"
        )

    def reset(self) -> None:
        self._integral = 0.0
        self._last_error = None
        self._zero_match_count = 0
        self._nonzero_match_count = 0
        self._last_adjustment_time = 0.0
        self._recovery.reset()
        logger.debug("PID controller reset")

    def _handle_zero_match(self, current_exposure: int) -> Optional[int]:
        """
        Handle zero-match scenarios by delegating to recovery.

        This is called ONLY when matched_stars == 0. Recovery walks the
        recovery ladder until matches return.

        Args:
            current_exposure: Current exposure time in microseconds

        Returns:
            New exposure from recovery, or None if waiting
        """
        self._zero_match_count += 1
        return self._recovery.handle(current_exposure, self._zero_match_count)

    def _update_pid(self, matched_stars: int, current_exposure: int) -> Optional[int]:
        """Core PID algorithm with asymmetric gains."""
        error = self.target_stars - matched_stars

        if abs(error) <= self.deadband:
            return None

        # Rate limiting: only when decreasing (too many stars)
        # When increasing (too few stars), respond immediately for faster recovery
        if error < 0:  # Too many stars, going down
            current_time = time.time()
            time_since_last = current_time - self._last_adjustment_time
            if time_since_last < self.update_interval:
                return None  # Skip debug log for performance
        else:
            current_time = time.time()  # Only get time when needed

        # Select gains: conservative when decreasing, aggressive when increasing
        kp, ki, kd = self.gains_decrease if error < 0 else self.gains_increase

        # Reset integral when error changes sign to prevent accumulated integral
        # from crashing exposure when conditions change suddenly
        # (e.g., going from too many stars to too few stars)
        if self._last_error is not None:
            if (error > 0 and self._last_error < 0) or (
                error < 0 and self._last_error > 0
            ):
                logger.debug(
                    f"PID: Error sign changed ({self._last_error:.0f} → {error:.0f}), resetting integral"
                )
                self._integral = 0.0

        # PID calculation
        p_term = kp * error

        self._integral += error
        if ki > 0:
            max_int = (self.max_exposure - self.min_exposure) / (2.0 * ki)
            self._integral = max(-max_int, min(max_int, self._integral))
        i_term = ki * self._integral

        d_term = 0.0 if self._last_error is None else kd * (error - self._last_error)

        new_exposure = int(current_exposure + p_term + i_term + d_term)

        # Anti-windup: if we hit limits, back out the integral contribution that caused it
        clamped_exposure = max(self.min_exposure, min(self.max_exposure, new_exposure))
        if clamped_exposure != new_exposure:
            if ki > 0:  # Only unwind if integral term is active
                overshoot = new_exposure - clamped_exposure
                self._integral -= overshoot / ki

        self._last_error = error
        self._last_adjustment_time = current_time

        return clamped_exposure

    def update(
        self,
        matched_stars: int,
        current_exposure: int,
    ) -> Optional[int]:
        """
        Update exposure based on star count.

        Main entry point for auto-exposure control. Routes to either
        PID control (normal) or zero-match recovery (exception).

        Args:
            matched_stars: Number of stars matched in last solve
            current_exposure: Current exposure time in microseconds

        Returns:
            New exposure time in microseconds, or None if no change needed
        """
        # Exception path: zero matches - delegate to recovery
        if matched_stars == 0:
            return self._handle_zero_match(current_exposure)

        # Exit recovery if we were in it (matches found!)
        if self._recovery.is_active():
            logger.debug(
                f"Recovery successful! Found {matched_stars} stars at {current_exposure}µs, "
                "switching to PID control"
            )
            self._recovery.reset()
            # Reset PID integral to prevent windup from affecting recovery
            self._integral = 0.0
            self._last_error = None

        # Reset zero-match counter
        self._zero_match_count = 0

        # Normal path: PID control (this is the king!)
        return self._update_pid(matched_stars, current_exposure)

    def set_target(self, target_stars: int) -> None:
        old_target = self.target_stars
        self.target_stars = target_stars
        logger.debug(f"Target stars changed: {old_target} → {target_stars}")

    def set_gains(
        self,
        gains_decrease: Optional[tuple] = None,
        gains_increase: Optional[tuple] = None,
    ) -> None:
        """Update PID gains. Each tuple is (Kp, Ki, Kd)."""
        if gains_decrease is not None:
            self.gains_decrease = gains_decrease
        if gains_increase is not None:
            self.gains_increase = gains_increase
        logger.debug(f"PID gains: dec={self.gains_decrease}, inc={self.gains_increase}")

    def get_status(self) -> dict:
        return {
            "target_stars": self.target_stars,
            "gains_decrease": self.gains_decrease,
            "gains_increase": self.gains_increase,
            "integral": self._integral,
            "last_error": self._last_error,
            "min_exposure": self.min_exposure,
            "max_exposure": self.max_exposure,
            "deadband": self.deadband,
            "update_interval": self.update_interval,
        }
