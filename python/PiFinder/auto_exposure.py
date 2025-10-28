#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Auto-exposure PID controller for optimizing star detection.

This module implements a PID (Proportional-Integral-Derivative) controller
that automatically adjusts camera exposure time to maintain an optimal number
of detected stars for plate solving.

The controller targets 15 matched stars, which provides reliable plate solving
while avoiding over-saturation and maintaining good performance.
"""

import logging
from abc import ABC, abstractmethod
from typing import List, Optional

import numpy as np
from PIL import Image

logger = logging.getLogger("AutoExposure")


def generate_exposure_sweep(
    min_exposure: int,
    max_exposure: int,
    num_steps: int
) -> List[int]:
    """
    Generate logarithmically-spaced exposure values for sweeps.

    This utility function is used by:
    - Experimental menu sweep capture (camera_interface.py) - 100 steps for analysis
    - HistogramZeroStarHandler - configurable steps (default 8) for live histogram analysis

    Note: SweepZeroStarHandler uses a hard-coded doubling pattern [25, 50, 100, 200, 400, 800, 1000]ms
    instead of this function because it has specific behavior tied to the 400ms value.

    Args:
        min_exposure: Minimum exposure in microseconds
        max_exposure: Maximum exposure in microseconds
        num_steps: Number of exposure values to generate

    Returns:
        List of exposure values in microseconds, logarithmically spaced
    """
    exposures = np.logspace(
        np.log10(min_exposure),
        np.log10(max_exposure),
        num_steps
    ).astype(int).tolist()

    return exposures


class ZeroStarHandler(ABC):
    """
    Base class for handling zero-star scenarios.

    Plugins implement different strategies for recovering when no stars
    are detected. The PID controller delegates to these handlers when
    matched_stars == 0.
    """

    def __init__(self):
        self._active = False

    @abstractmethod
    def handle(
        self,
        current_exposure: int,
        zero_count: int,
        image: Optional[Image.Image] = None
    ) -> Optional[int]:
        """
        Handle a zero-star solve.

        Args:
            current_exposure: Current exposure time in microseconds
            zero_count: Number of consecutive zero-star solves
            image: Optional PIL Image for histogram analysis

        Returns:
            New exposure to try, or None if no action yet
        """
        pass

    @abstractmethod
    def reset(self) -> None:
        pass

    def is_active(self) -> bool:
        return self._active


class SweepZeroStarHandler(ZeroStarHandler):
    """
    Recovery strategy: systematic exposure sweep.

    Sweeps through predefined exposure values, trying each multiple times.
    Includes extended hold at 400ms for manual focus adjustment.
    """

    def __init__(
        self,
        min_exposure: int = 25000,
        max_exposure: int = 1000000,
        trigger_count: int = 2,
    ):
        """
        Initialize the sweep handler.

        Args:
            min_exposure: Minimum exposure in sweep
            max_exposure: Maximum exposure in sweep
            trigger_count: Number of zeros before activating
        """
        super().__init__()
        self._trigger_count = trigger_count
        self._exposure_index = 0
        self._repeat_count = 0

        # Sweep pattern: exposure values in microseconds
        # Uses doubling pattern (2x each step) with special hold at 400ms
        # Note: This is intentionally NOT using generate_exposure_sweep() because
        # it has specific behavior tied to these exact values (400ms hold)
        self._exposures = [25000, 50000, 100000, 200000, 400000, 800000, 1000000]
        self._repeats_per_exposure = 2  # Try each exposure 2 times
        self._focus_hold_cycles = 12  # Hold at 400ms for ~10 seconds

        logger.info(
            f"SweepZeroStarHandler initialized: trigger after {trigger_count} zeros, "
            f"sweep pattern {self._exposures}µs"
        )

    def handle(
        self,
        current_exposure: int,
        zero_count: int,
        image: Optional[Image.Image] = None
    ) -> Optional[int]:
        """
        Handle zero stars by sweeping through exposures.

        Args:
            current_exposure: Current exposure time in microseconds
            zero_count: Number of consecutive zero-star solves
            image: Unused by this handler

        Returns:
            New exposure to try, or None if waiting for trigger
        """
        # Wait for trigger count
        if zero_count < self._trigger_count:
            logger.info(f"Zero stars: {zero_count}/{self._trigger_count} before sweep activation")
            return None

        # Activate if not already active
        if not self._active:
            self._active = True
            logger.warning(
                f"Sweep activated after {zero_count} zero-star solves (stuck at {current_exposure}µs)"
            )

        # Execute sweep
        return self._next_exposure()

    def _next_exposure(self) -> int:
        current_sweep_exposure = self._exposures[self._exposure_index]

        # Special handling for 400ms - hold longer for manual focus
        is_focus_exposure = (current_sweep_exposure == 400000)
        repeats_needed = self._focus_hold_cycles if is_focus_exposure else self._repeats_per_exposure

        # Log current attempt
        attempt_number = self._repeat_count + 1
        if is_focus_exposure:
            logger.info(
                f"Sweep: holding at {current_sweep_exposure}µs for focusing "
                f"({attempt_number}/{repeats_needed})"
            )
        else:
            logger.info(
                f"Sweep: trying {current_sweep_exposure}µs "
                f"({attempt_number}/{repeats_needed})"
            )

        # Save result to return
        result = current_sweep_exposure

        # Update state for next call
        self._repeat_count += 1
        if self._repeat_count >= repeats_needed:
            # Completed all repeats, advance to next exposure
            self._repeat_count = 0
            self._exposure_index += 1

            # Wrap around to start of sweep
            if self._exposure_index >= len(self._exposures):
                self._exposure_index = 0
                logger.warning(f"Sweep: complete, restarting from {self._exposures[0]}µs")
            else:
                next_exposure = self._exposures[self._exposure_index]
                logger.info(f"Sweep: advancing to {next_exposure}µs")

        return result

    def reset(self) -> None:
        self._active = False
        self._exposure_index = 0
        self._repeat_count = 0
        logger.debug("SweepZeroStarHandler reset")


class ResetZeroStarHandler(ZeroStarHandler):
    """
    Recovery strategy: reset to fixed exposure.

    Simply resets to a safe default exposure (400ms) when zero stars detected.
    Fast recovery but may not be optimal for all conditions.
    """

    def __init__(
        self,
        reset_exposure: int = 400000,
        trigger_count: int = 2,
    ):
        """
        Initialize the reset handler.

        Args:
            reset_exposure: Exposure to reset to (default: 400ms)
            trigger_count: Number of zeros before activating
        """
        super().__init__()
        self._trigger_count = trigger_count
        self._reset_exposure = reset_exposure

        logger.info(
            f"ResetZeroStarHandler initialized: trigger after {trigger_count} zeros, "
            f"reset to {reset_exposure}µs"
        )

    def handle(
        self,
        current_exposure: int,
        zero_count: int,
        image: Optional[Image.Image] = None
    ) -> Optional[int]:
        """
        Handle zero stars by resetting to fixed exposure.

        Args:
            current_exposure: Current exposure time in microseconds
            zero_count: Number of consecutive zero-star solves
            image: Unused by this handler

        Returns:
            Reset exposure, or None if waiting for trigger
        """
        # Wait for trigger count
        if zero_count < self._trigger_count:
            logger.info(f"Zero stars: {zero_count}/{self._trigger_count} before reset activation")
            return None

        # Activate and return reset exposure
        if not self._active:
            self._active = True
            logger.warning(
                f"Reset activated after {zero_count} zero-star solves "
                f"(resetting from {current_exposure}µs to {self._reset_exposure}µs)"
            )

        return self._reset_exposure

    def reset(self) -> None:
        self._active = False
        logger.debug("ResetZeroStarHandler reset")


class HistogramZeroStarHandler(ZeroStarHandler):
    """
    Recovery strategy: histogram-based quick sweep to find minimum viable exposure.

    When no stars are detected (likely defocused), performs a quick sweep
    through configurable number of exposures (default 8), analyzing the histogram
    of each image to find the minimum viable exposure where defocused stars would
    be visible. Works across different instruments and sky conditions.

    Viability criteria (from test_find_min_exposure.py):
    - Mean brightness > 20 (enough signal above noise floor)
    - Std deviation > 5 (some structure/variation, not flat)
    - Saturation < 5% (not overexposed)

    Strategy:
    1. On activation, start sweep from min_exposure to max_exposure (logarithmic)
    2. Capture and analyze histogram of each image in real-time
    3. Settle on first viable exposure (minimum where defocused stars visible)
    4. If no viable found after full sweep, use highest exposure from sweep

    The sweep covers the full exposure range to accommodate different instruments,
    apertures, and sky conditions. Histogram analysis ensures the right exposure
    is found dynamically rather than relying on hard-coded values.
    """

    def __init__(
        self,
        min_exposure: int = 25000,
        max_exposure: int = 1000000,
        trigger_count: int = 2,
        sweep_steps: int = 8,
    ):
        """
        Initialize the histogram handler.

        Args:
            min_exposure: Minimum exposure in microseconds
            max_exposure: Maximum exposure in microseconds
            trigger_count: Number of zeros before activating
            sweep_steps: Number of exposures to try in quick sweep (default 8)
        """
        super().__init__()
        self._trigger_count = trigger_count
        self._min_exposure = min_exposure
        self._max_exposure = max_exposure
        self._sweep_steps = sweep_steps
        self._sweep_index = 0
        self._sweep_exposures: List[int] = []
        self._sweep_results: List[tuple] = []  # Store (exposure, viable, metrics) tuples
        self._target_exposure: Optional[int] = None

        logger.info(
            f"HistogramZeroStarHandler initialized: trigger after {trigger_count} zeros, "
            f"quick sweep with {sweep_steps} steps using histogram analysis"
        )

    def _generate_sweep_exposures(self) -> list:
        """
        Generate sweep exposure values.
        Uses logarithmic spacing across full exposure range.
        Histogram analysis will find the minimum viable exposure dynamically.
        """
        return generate_exposure_sweep(
            self._min_exposure,
            self._max_exposure,
            self._sweep_steps
        )

    def _analyze_image_viability(self, image: Image.Image) -> tuple:
        """
        Analyze image to determine if it's viable for defocused focusing.

        Returns:
            (viable, metrics_dict) - viable is bool, metrics_dict has mean/std/saturation
        """
        # Convert to grayscale numpy array
        if image.mode != 'L':
            image = image.convert('L')
        img_array = np.asarray(image, dtype=np.float32)

        # Calculate metrics
        mean = float(np.mean(img_array))
        std = float(np.std(img_array))
        saturated = np.sum(img_array > 250)
        saturation_pct = (saturated / img_array.size) * 100

        # Viability criteria from test_find_min_exposure.py
        has_signal = mean > 20  # Enough brightness above noise floor
        has_structure = std > 5  # Some variation (not completely flat)
        not_saturated = saturation_pct < 5  # Not overexposed

        viable = has_signal and has_structure and not_saturated

        metrics = {
            'mean': mean,
            'std': std,
            'saturation_pct': saturation_pct,
            'has_signal': has_signal,
            'has_structure': has_structure,
            'not_saturated': not_saturated
        }

        return viable, metrics

    def handle(
        self,
        current_exposure: int,
        zero_count: int,
        image: Optional[Image.Image] = None
    ) -> Optional[int]:
        """
        Handle zero stars with histogram-based quick sweep.

        Strategy:
        - Activates after trigger_count zero-star solves
        - Performs quick sweep, analyzing histogram of each image
        - Settles on first viable exposure (minimum viable)
        - If no viable found, uses last exposure from sweep

        Args:
            current_exposure: Current exposure time in microseconds
            zero_count: Number of consecutive zero-star solves
            image: PIL Image for histogram analysis

        Returns:
            Next sweep exposure, or settled exposure after sweep completes
        """
        # Wait for trigger count
        if zero_count < self._trigger_count:
            logger.info(f"Zero stars: {zero_count}/{self._trigger_count} before histogram handler activation")
            return None

        # Activate and start sweep
        if not self._active:
            self._active = True
            self._sweep_index = 0
            self._sweep_exposures = self._generate_sweep_exposures()
            self._sweep_results = []
            logger.warning(
                f"Histogram handler activated: starting {self._sweep_steps}-step histogram sweep "
                f"from {self._sweep_exposures[0]/1000:.1f}ms to {self._sweep_exposures[-1]/1000:.1f}ms"
            )
            return self._sweep_exposures[0]

        # Analyze current image if we have one
        # The image was captured at current_exposure, which should match our last returned exposure
        if image is not None and self._sweep_index < len(self._sweep_exposures):
            # Match current_exposure to find which sweep exposure was used
            sweep_exposure = self._sweep_exposures[self._sweep_index]

            viable, metrics = self._analyze_image_viability(image)
            self._sweep_results.append((sweep_exposure, viable, metrics))

            logger.info(
                f"Histogram analysis for {sweep_exposure/1000:.1f}ms: "
                f"viable={'YES' if viable else 'NO'}, "
                f"mean={metrics['mean']:.1f}, std={metrics['std']:.1f}, sat={metrics['saturation_pct']:.1f}%"
            )

            # If we found first viable exposure, we can settle immediately
            if viable and self._target_exposure is None:
                self._target_exposure = sweep_exposure
                logger.info(
                    f"Histogram handler: found minimum viable exposure {sweep_exposure/1000:.1f}ms "
                    f"(step {self._sweep_index+1}/{self._sweep_steps})"
                )
                # Stop sweep and settle on this exposure
                return self._target_exposure

        # If we've completed the sweep, settle on target exposure
        if self._sweep_index >= len(self._sweep_exposures):
            if self._target_exposure is None:
                # No viable exposure found - use highest from sweep
                # Or pick one with best metrics
                if self._sweep_results:
                    # Use the last (highest) exposure
                    highest_exp = self._sweep_results[-1][0]
                    self._target_exposure = highest_exp
                    logger.warning(
                        f"Histogram handler: no viable exposure found, using highest {highest_exp/1000:.1f}ms"
                    )
                else:
                    # Fallback to middle exposure
                    middle_idx = len(self._sweep_exposures) // 2
                    middle_exp = self._sweep_exposures[middle_idx]
                    self._target_exposure = middle_exp
                    logger.warning(
                        f"Histogram handler: no analysis data, using middle {middle_exp/1000:.1f}ms"
                    )

            # Hold at target
            if current_exposure != self._target_exposure:
                return self._target_exposure
            return None

        # Continue sweep - advance to next exposure
        self._sweep_index += 1
        if self._sweep_index < len(self._sweep_exposures):
            next_exp = self._sweep_exposures[self._sweep_index]
            logger.info(
                f"Histogram handler: sweep step {self._sweep_index+1}/{self._sweep_steps} → {next_exp/1000:.1f}ms"
            )
            return next_exp
        else:
            # Just finished last sweep step, next call will analyze and settle
            logger.info("Histogram handler: sweep complete, analyzing final image")
            return None

    def reset(self) -> None:
        self._active = False
        self._sweep_index = 0
        self._sweep_exposures = []
        self._sweep_results = []
        self._target_exposure = None
        logger.debug("HistogramZeroStarHandler reset")


class ExposurePIDController:
    """
    PID controller for automatic camera exposure adjustment.

    The controller adjusts exposure time based on the number of stars
    detected during plate solving, targeting an optimal count for
    reliable solving performance.
    """

    def __init__(
        self,
        target_stars: int = 15,
        kp: float = 8000.0,
        ki: float = 500.0,
        kd: float = 3000.0,
        min_exposure: int = 25000,
        max_exposure: int = 1000000,
        deadband: int = 2,
        zero_star_handler: Optional[ZeroStarHandler] = None,
    ):
        """
        Initialize the PID controller.

        Args:
            target_stars: Optimal number of stars to maintain (default: 15)
            kp: Proportional gain - immediate response to error
            ki: Integral gain - eliminates steady-state error
            kd: Derivative gain - dampens oscillation
            min_exposure: Minimum exposure time in microseconds (default: 25ms)
            max_exposure: Maximum exposure time in microseconds (default: 1s)
            deadband: Don't adjust if within ±deadband of target (default: 2)
            zero_star_handler: Plugin for handling zero-star scenarios (default: SweepZeroStarHandler)
        """
        self.target_stars = target_stars
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.min_exposure = min_exposure
        self.max_exposure = max_exposure
        self.deadband = deadband

        # PID state variables
        self._integral = 0.0
        self._last_error: Optional[float] = None

        # Zero-star handling (pluggable)
        self._zero_star_count = 0
        self._zero_star_handler = zero_star_handler or SweepZeroStarHandler(
            min_exposure=min_exposure,
            max_exposure=max_exposure
        )

        logger.info(
            f"AutoExposure PID initialized: target={target_stars}, "
            f"Kp={kp}, Ki={ki}, Kd={kd}, "
            f"range=[{min_exposure}, {max_exposure}]µs, deadband=±{deadband}, "
            f"zero_star_handler={self._zero_star_handler.__class__.__name__}"
        )

    def reset(self) -> None:
        self._integral = 0.0
        self._last_error = None
        self._zero_star_count = 0
        self._zero_star_handler.reset()
        logger.debug("PID controller reset")

    def _handle_zero_stars(
        self,
        current_exposure: int,
        image: Optional[Image.Image] = None
    ) -> Optional[int]:
        """
        Handle zero-star scenarios by delegating to the pluggable handler.

        This is called ONLY when matched_stars == 0. The handler implements
        the recovery strategy (e.g., sweep, reset, etc.).

        Args:
            current_exposure: Current exposure time in microseconds
            image: Optional PIL Image for histogram analysis

        Returns:
            New exposure from handler, or None if waiting
        """
        self._zero_star_count += 1
        return self._zero_star_handler.handle(current_exposure, self._zero_star_count, image)

    def _update_pid(self, matched_stars: int, current_exposure: int) -> Optional[int]:
        """
        Core PID control algorithm.

        Calculates exposure adjustment based on star count error using
        Proportional-Integral-Derivative feedback control.

        Args:
            matched_stars: Number of stars matched in last solve
            current_exposure: Current exposure time in microseconds

        Returns:
            New exposure time in microseconds, or None if within deadband
        """
        # Calculate error (negative = too many stars, positive = too few)
        error = self.target_stars - matched_stars

        # Deadband - don't adjust if we're close enough
        if abs(error) <= self.deadband:
            logger.debug(
                f"Within deadband: {matched_stars} stars "
                f"(target {self.target_stars} ±{self.deadband})"
            )
            return None

        # Use fixed dt since we update once per solve cycle
        # (not time-based, but iteration-based)
        dt = 1.0

        # Proportional term
        p_term = self.kp * error

        # Integral term with anti-windup
        self._integral += error * dt
        # Clamp integral to prevent windup (only if ki > 0)
        if self.ki > 0:
            max_integral = (self.max_exposure - self.min_exposure) / (2.0 * self.ki)
            self._integral = max(-max_integral, min(max_integral, self._integral))
        i_term = self.ki * self._integral

        # Derivative term
        if self._last_error is None:
            d_term = 0.0
        else:
            d_term = self.kd * (error - self._last_error) / dt

        # Calculate adjustment
        adjustment = p_term + i_term + d_term

        # Apply adjustment to current exposure
        new_exposure = int(current_exposure + adjustment)

        # Clamp to valid range
        new_exposure = max(self.min_exposure, min(self.max_exposure, new_exposure))

        # Update state
        self._last_error = error

        logger.debug(
            f"PID update: {matched_stars} stars (target {self.target_stars}), "
            f"error={error}, P={p_term:.0f}, I={i_term:.0f}, D={d_term:.0f}, "
            f"exposure {current_exposure}→{new_exposure}µs"
        )

        return new_exposure

    def update(
        self,
        matched_stars: int,
        current_exposure: int,
        image: Optional[Image.Image] = None
    ) -> Optional[int]:
        """
        Update exposure based on star count.

        Main entry point for auto-exposure control. Routes to either
        PID control (normal) or zero-star handler (exception).

        Args:
            matched_stars: Number of stars matched in last solve
            current_exposure: Current exposure time in microseconds
            image: Optional PIL Image for histogram analysis (used by zero-star handler)

        Returns:
            New exposure time in microseconds, or None if no change needed
        """
        # Exception path: zero stars - delegate to handler plugin
        if matched_stars == 0:
            return self._handle_zero_stars(current_exposure, image)

        # Exit handler mode if we were in it (stars found!)
        if self._zero_star_handler.is_active():
            logger.info(
                f"Zero-star handler successful! Found {matched_stars} stars at {current_exposure}µs, "
                "switching to PID control"
            )
            self._zero_star_handler.reset()

        # Reset zero-star counter
        self._zero_star_count = 0

        # Normal path: PID control (this is the king!)
        return self._update_pid(matched_stars, current_exposure)

    def set_target(self, target_stars: int) -> None:
        old_target = self.target_stars
        self.target_stars = target_stars
        logger.info(f"Target stars changed: {old_target} → {target_stars}")

    def set_gains(self, kp: Optional[float] = None, ki: Optional[float] = None, kd: Optional[float] = None) -> None:
        if kp is not None:
            self.kp = kp
        if ki is not None:
            self.ki = ki
        if kd is not None:
            self.kd = kd

        logger.info(f"PID gains updated: Kp={self.kp}, Ki={self.ki}, Kd={self.kd}")

    def get_status(self) -> dict:
        return {
            "target_stars": self.target_stars,
            "kp": self.kp,
            "ki": self.ki,
            "kd": self.kd,
            "integral": self._integral,
            "last_error": self._last_error,
            "min_exposure": self.min_exposure,
            "max_exposure": self.max_exposure,
            "deadband": self.deadband,
        }
