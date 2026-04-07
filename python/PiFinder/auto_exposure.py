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
"""

import logging
import time
from abc import ABC, abstractmethod
from typing import List, Optional

import numpy as np
from PIL import Image

logger = logging.getLogger("AutoExposure")


def generate_exposure_sweep(
    min_exposure: int, max_exposure: int, num_steps: int
) -> List[int]:
    """
    Generate logarithmically-spaced exposure values for sweeps.

    This utility function is used by:
    - ExponentialSweepZeroStarHandler - configurable steps (default 7) for zero-star recovery
    - HistogramZeroStarHandler - configurable steps (default 8) for live histogram analysis
    - Experimental menu sweep capture (camera_interface.py) - 100 steps for analysis

    Note: SweepZeroStarHandler uses a hard-coded doubling pattern [25, 50, 100, 200, 400, 800, 1000]ms
    instead of this function for a simpler, predictable pattern.

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
        image: Optional[Image.Image] = None,
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
        # Start at 400ms (reasonable middle), sweep up, then try shorter exposures
        # Note: This is intentionally NOT using generate_exposure_sweep() because
        # it uses a specific pattern optimized for recovery
        self._exposures = [400000, 800000, 1000000, 200000, 100000, 50000, 25000]
        self._repeats_per_exposure = 2  # Try each exposure 2 times

        logger.info(
            f"SweepZeroStarHandler initialized: trigger after {trigger_count} zeros, "
            f"sweep pattern {self._exposures}µs"
        )

    def handle(
        self,
        current_exposure: int,
        zero_count: int,
        image: Optional[Image.Image] = None,
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
            logger.debug(
                f"Zero stars: {zero_count}/{self._trigger_count} before sweep activation"
            )
            return None

        # Activate if not already active
        if not self._active:
            self._active = True
            logger.debug(
                f"Sweep activated after {zero_count} zero-star solves (stuck at {current_exposure}µs)"
            )

        # Execute sweep
        return self._next_exposure()

    def _next_exposure(self) -> int:
        current_sweep_exposure = self._exposures[self._exposure_index]

        # Log current attempt
        attempt_number = self._repeat_count + 1
        logger.debug(
            f"Sweep: trying {current_sweep_exposure}µs "
            f"({attempt_number}/{self._repeats_per_exposure})"
        )

        # Save result to return
        result = current_sweep_exposure

        # Update state for next call
        self._repeat_count += 1
        if self._repeat_count >= self._repeats_per_exposure:
            # Completed all repeats, advance to next exposure
            self._repeat_count = 0
            self._exposure_index += 1

            # Wrap around to start of sweep
            if self._exposure_index >= len(self._exposures):
                self._exposure_index = 0
                logger.debug(f"Sweep: complete, restarting from {self._exposures[0]}µs")
            else:
                next_exposure = self._exposures[self._exposure_index]
                logger.debug(f"Sweep: advancing to {next_exposure}µs")

        return result

    def reset(self) -> None:
        self._active = False
        self._exposure_index = 0
        self._repeat_count = 0
        logger.debug("SweepZeroStarHandler reset")


class ExponentialSweepZeroStarHandler(ZeroStarHandler):
    """
    Recovery strategy: exponential (logarithmic) exposure sweep.

    Similar to SweepZeroStarHandler but uses logarithmically-spaced exposures
    instead of doubling pattern. Provides more granular coverage across the
    exposure range.
    """

    def __init__(
        self,
        min_exposure: int = 25000,
        max_exposure: int = 1000000,
        trigger_count: int = 2,
        sweep_steps: int = 7,
        repeats_per_exposure: int = 2,
    ):
        """
        Initialize the exponential sweep handler.

        Args:
            min_exposure: Minimum exposure in microseconds
            max_exposure: Maximum exposure in microseconds
            trigger_count: Number of zeros before activating
            sweep_steps: Number of exposures in sweep (default 7)
            repeats_per_exposure: Times to try each exposure (default 2)
        """
        super().__init__()
        self._trigger_count = trigger_count
        self._min_exposure = min_exposure
        self._max_exposure = max_exposure
        self._sweep_steps = sweep_steps
        self._repeats_per_exposure = repeats_per_exposure
        self._exposure_index = 0
        self._repeat_count = 0

        # Generate logarithmically-spaced exposure sweep
        self._exposures = generate_exposure_sweep(
            min_exposure, max_exposure, sweep_steps
        )

        logger.info(
            f"ExponentialSweepZeroStarHandler initialized: trigger after {trigger_count} zeros, "
            f"{sweep_steps} logarithmic steps from {min_exposure}µs to {max_exposure}µs"
        )

    def handle(
        self,
        current_exposure: int,
        zero_count: int,
        image: Optional[Image.Image] = None,
    ) -> Optional[int]:
        """
        Handle zero stars by sweeping through logarithmic exposures.

        Args:
            current_exposure: Current exposure time in microseconds
            zero_count: Number of consecutive zero-star solves
            image: Unused by this handler

        Returns:
            New exposure to try, or None if waiting for trigger
        """
        # Wait for trigger count
        if zero_count < self._trigger_count:
            logger.debug(
                f"Zero stars: {zero_count}/{self._trigger_count} before exponential sweep activation"
            )
            return None

        # Activate if not already active
        if not self._active:
            self._active = True
            logger.debug(
                f"Exponential sweep activated after {zero_count} zero-star solves "
                f"(stuck at {current_exposure}µs)"
            )

        # Execute sweep
        return self._next_exposure()

    def _next_exposure(self) -> int:
        current_sweep_exposure = self._exposures[self._exposure_index]

        # Log current attempt
        attempt_number = self._repeat_count + 1
        logger.debug(
            f"Exponential sweep: trying {current_sweep_exposure}µs "
            f"({attempt_number}/{self._repeats_per_exposure})"
        )

        # Save result to return
        result = current_sweep_exposure

        # Update state for next call
        self._repeat_count += 1
        if self._repeat_count >= self._repeats_per_exposure:
            # Completed all repeats, advance to next exposure
            self._repeat_count = 0
            self._exposure_index += 1

            # Wrap around to start of sweep
            if self._exposure_index >= len(self._exposures):
                self._exposure_index = 0
                logger.debug(
                    f"Exponential sweep: complete, restarting from {self._exposures[0]}µs"
                )
            else:
                next_exposure = self._exposures[self._exposure_index]
                logger.debug(f"Exponential sweep: advancing to {next_exposure}µs")

        return result

    def reset(self) -> None:
        self._active = False
        self._exposure_index = 0
        self._repeat_count = 0
        logger.debug("ExponentialSweepZeroStarHandler reset")


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
        image: Optional[Image.Image] = None,
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
            logger.debug(
                f"Zero stars: {zero_count}/{self._trigger_count} before reset activation"
            )
            return None

        # Activate and return reset exposure
        if not self._active:
            self._active = True
            logger.debug(
                f"Reset activated after {zero_count} zero-star solves "
                f"(resetting from {current_exposure}µs to {self._reset_exposure}µs)"
            )

        return self._reset_exposure

    def reset(self) -> None:
        self._active = False
        logger.debug("ResetZeroStarHandler reset")


class HistogramZeroStarHandler(ZeroStarHandler):
    """
    Recovery strategy: histogram-based quick sweep to find optimal viable exposure.

    When no stars are detected (likely defocused), performs a quick sweep
    through configurable number of exposures (default 8), analyzing the histogram
    of each image to find the highest viable exposure for best star detection.
    Works across different instruments and sky conditions.

    Viability criteria:
    - Mean brightness > 20 (enough signal above noise floor)
    - Std deviation > 5 (some structure/variation, not flat)
    - Saturation < 5% (not overexposed)

    Strategy:
    1. On activation, start sweep from min_exposure to max_exposure (logarithmic)
    2. Capture and analyze histogram of each image in real-time
    3. Complete full sweep to identify all viable exposures
    4. Settle on highest viable exposure (best for star detection)
    5. If no viable found, use highest exposure from sweep

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
        self._sweep_results: List[
            tuple
        ] = []  # Store (exposure, viable, metrics) tuples
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
            self._min_exposure, self._max_exposure, self._sweep_steps
        )

    def _analyze_image_viability(self, image: Image.Image) -> tuple:
        """
        Analyze image to determine if it's viable for defocused focusing.

        Returns:
            (viable, metrics_dict) - viable is bool, metrics_dict has mean/std/saturation
        """
        # Convert to grayscale numpy array
        if image.mode != "L":
            image = image.convert("L")
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
            "mean": mean,
            "std": std,
            "saturation_pct": saturation_pct,
            "has_signal": has_signal,
            "has_structure": has_structure,
            "not_saturated": not_saturated,
        }

        return viable, metrics

    def handle(
        self,
        current_exposure: int,
        zero_count: int,
        image: Optional[Image.Image] = None,
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
            logger.debug(
                f"Zero stars: {zero_count}/{self._trigger_count} before histogram handler activation"
            )
            return None

        # Activate and start sweep
        if not self._active:
            self._active = True
            self._sweep_index = 0
            self._sweep_exposures = self._generate_sweep_exposures()
            self._sweep_results = []
            logger.debug(
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

            logger.debug(
                f"Histogram analysis for {sweep_exposure/1000:.1f}ms: "
                f"viable={'YES' if viable else 'NO'}, "
                f"mean={metrics['mean']:.1f}, std={metrics['std']:.1f}, sat={metrics['saturation_pct']:.1f}%"
            )

            # Track viable exposures but continue sweep to find best option
            if viable:
                logger.debug(
                    f"Histogram handler: found viable exposure {sweep_exposure/1000:.1f}ms "
                    f"(step {self._sweep_index+1}/{self._sweep_steps}), continuing sweep"
                )

        # If we've completed the sweep, settle on target exposure
        if self._sweep_index >= len(self._sweep_exposures):
            if self._target_exposure is None:
                # Find highest viable exposure from sweep results
                if self._sweep_results:
                    # Find all viable exposures
                    viable_exposures = [
                        exp for exp, viable, _ in self._sweep_results if viable
                    ]

                    if viable_exposures:
                        # Use highest viable exposure for best star detection
                        self._target_exposure = max(viable_exposures)
                        logger.debug(
                            f"Histogram handler: settling on highest viable exposure {self._target_exposure/1000:.1f}ms"
                        )
                    else:
                        # No viable exposures - use highest from sweep
                        highest_exp = self._sweep_results[-1][0]
                        self._target_exposure = highest_exp
                        logger.debug(
                            f"Histogram handler: no viable exposure found, using highest {highest_exp/1000:.1f}ms"
                        )
                else:
                    # Fallback to middle exposure
                    middle_idx = len(self._sweep_exposures) // 2
                    middle_exp = self._sweep_exposures[middle_idx]
                    self._target_exposure = middle_exp
                    logger.debug(
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
            logger.debug(
                f"Histogram handler: sweep step {self._sweep_index+1}/{self._sweep_steps} → {next_exp/1000:.1f}ms"
            )
            return next_exp
        else:
            # Just finished last sweep step, next call will analyze and settle
            logger.debug("Histogram handler: sweep complete, analyzing final image")
            return None

    def reset(self) -> None:
        self._active = False
        self._sweep_index = 0
        self._sweep_exposures = []
        self._sweep_results = []
        self._target_exposure = None
        logger.debug("HistogramZeroStarHandler reset")


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
            f"exp_range=[{min_exposure/1000:.0f}, {max_exposure/1000:.0f}]ms, "
            f"adjustment={adjustment_factor}x"
        )

    @classmethod
    def from_camera_profile(
        cls,
        camera_type: str,
        min_exposure: int = 10000,
        max_exposure: int = 1000000,
        adjustment_factor: float = 1.3,
    ) -> "ExposureSNRController":
        """
        Create controller with thresholds derived from camera profile.

        Calculates min/target/max background based on bit depth and bias offset.

        Args:
            camera_type: Camera type (e.g., "imx296_processed", "imx462_processed")
            min_exposure: Minimum exposure in microseconds
            max_exposure: Maximum exposure in microseconds
            adjustment_factor: Multiplicative adjustment step

        Returns:
            ExposureSNRController configured for the camera
        """
        from PiFinder.sqm.camera_profiles import get_camera_profile

        profile = get_camera_profile(camera_type)

        # Derive thresholds from camera specs
        max_adu = (2 ** profile.bit_depth) - 1
        bias = profile.bias_offset

        # min_background: bias + margin (2x bias or bias + 8, whichever larger)
        min_background = int(max(bias * 2, bias + 8))

        # max_background: ~40% of full range (avoid saturation/nonlinearity)
        max_background = int(max_adu * 0.4)

        # target_background: just above min (lower = shorter exposure = more linear response)
        target_background = min_background + 2

        logger.info(
            f"SNR controller from {camera_type}: "
            f"bit_depth={profile.bit_depth}, bias={bias:.0f}, "
            f"thresholds=[{min_background}, {target_background}, {max_background}]"
        )

        return cls(
            min_exposure=min_exposure,
            max_exposure=max_exposure,
            target_background=target_background,
            min_background=min_background,
            max_background=max_background,
            adjustment_factor=adjustment_factor,
        )

    def update(
        self,
        current_exposure: int,
        image: Image.Image,
        noise_floor: Optional[float] = None,
        **kwargs  # Ignore other params (matched_stars, etc.)
    ) -> Optional[int]:
        """
        Update exposure based on background level.

        Args:
            current_exposure: Current exposure in microseconds
            image: Current image for analysis
            noise_floor: Adaptive noise floor from SQM calculator (if available)
            **kwargs: Ignored (for compatibility with PID interface)

        Returns:
            New exposure in microseconds, or None if no change needed
        """
        # Use adaptive noise floor if available, otherwise fall back to static config
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
            f"SNR AE: bg={background:.1f}, min={min_bg:.1f} ADU, exp={current_exposure/1000:.0f}ms"
        )

        # Determine adjustment
        new_exposure = None

        if background < min_bg:
            # Too dark - increase exposure
            new_exposure = int(current_exposure * self.adjustment_factor)
            logger.info(
                f"SNR AE: Background too low ({background:.1f} < {min_bg:.1f}), "
                f"increasing exposure {current_exposure/1000:.0f}ms → {new_exposure/1000:.0f}ms"
            )
        elif background > self.max_background:
            # Too bright - decrease exposure
            new_exposure = int(current_exposure / self.adjustment_factor)
            logger.info(
                f"SNR AE: Background too high ({background:.1f} > {self.max_background}), "
                f"decreasing exposure {current_exposure/1000:.0f}ms → {new_exposure/1000:.0f}ms"
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
        zero_star_handler: Optional[ZeroStarHandler] = None,
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
        self._zero_star_count = 0
        self._nonzero_star_count = 0  # Hysteresis: consecutive non-zero solves
        self._last_adjustment_time = 0.0
        self._zero_star_handler = zero_star_handler or SweepZeroStarHandler(
            min_exposure=min_exposure, max_exposure=max_exposure
        )

        logger.info(
            f"AutoExposure PID: target={target_stars}, deadband={deadband}, "
            f"update_interval={update_interval}s, "
            f"gains_dec={gains_decrease}, gains_inc={gains_increase}, "
            f"range=[{min_exposure}, {max_exposure}]µs"
        )

    def reset(self) -> None:
        self._integral = 0.0
        self._last_error = None
        self._zero_star_count = 0
        self._nonzero_star_count = 0
        self._last_adjustment_time = 0.0
        self._zero_star_handler.reset()
        logger.debug("PID controller reset")

    def _handle_zero_stars(
        self, current_exposure: int, image: Optional[Image.Image] = None
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
        return self._zero_star_handler.handle(
            current_exposure, self._zero_star_count, image
        )

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
            if (error > 0 and self._last_error < 0) or (error < 0 and self._last_error > 0):
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
        image: Optional[Image.Image] = None,
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
            logger.debug(
                f"Zero-star handler successful! Found {matched_stars} stars at {current_exposure}µs, "
                "switching to PID control"
            )
            self._zero_star_handler.reset()
            # Reset PID integral to prevent windup from affecting recovery
            self._integral = 0.0
            self._last_error = None

        # Reset zero-star counter
        self._zero_star_count = 0

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
