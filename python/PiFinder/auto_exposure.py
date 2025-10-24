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
from typing import Optional

logger = logging.getLogger("AutoExposure")


class ExposurePIDController:
    """
    PID controller for automatic camera exposure adjustment.

    The controller adjusts exposure time based on the number of stars
    detected during plate solving, targeting an optimal count for
    reliable solving performance.

    Attributes:
        target_stars: Target number of matched stars (default: 15)
        kp: Proportional gain coefficient
        ki: Integral gain coefficient
        kd: Derivative gain coefficient
        min_exposure: Minimum exposure time in microseconds
        max_exposure: Maximum exposure time in microseconds
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

        logger.info(
            f"AutoExposure PID initialized: target={target_stars}, "
            f"Kp={kp}, Ki={ki}, Kd={kd}, "
            f"range=[{min_exposure}, {max_exposure}]µs, deadband=±{deadband}"
        )

    def reset(self) -> None:
        """Reset the PID controller state."""
        self._integral = 0.0
        self._last_error = None
        logger.debug("PID controller reset")

    def update(
        self, matched_stars: int, current_exposure: int
    ) -> Optional[int]:
        """
        Calculate new exposure time based on current star count.

        This method implements a PID control loop that adjusts exposure
        to maintain the target number of matched stars. Updates on every
        new solve result (naturally rate-limited by exposure + solve time).

        Args:
            matched_stars: Number of stars matched in last solve
            current_exposure: Current exposure time in microseconds

        Returns:
            New exposure time in microseconds, or None if no update needed
            (within deadband)
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
        # Clamp integral to prevent windup
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

    def set_target(self, target_stars: int) -> None:
        """
        Change the target number of stars.

        Args:
            target_stars: New target star count
        """
        old_target = self.target_stars
        self.target_stars = target_stars
        logger.info(f"Target stars changed: {old_target} → {target_stars}")

    def set_gains(self, kp: Optional[float] = None, ki: Optional[float] = None, kd: Optional[float] = None) -> None:
        """
        Update PID gain coefficients.

        Args:
            kp: Proportional gain (if provided)
            ki: Integral gain (if provided)
            kd: Derivative gain (if provided)
        """
        if kp is not None:
            self.kp = kp
        if ki is not None:
            self.ki = ki
        if kd is not None:
            self.kd = kd

        logger.info(f"PID gains updated: Kp={self.kp}, Ki={self.ki}, Kd={self.kd}")

    def get_status(self) -> dict:
        """
        Get current controller status.

        Returns:
            Dictionary with controller state information
        """
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
