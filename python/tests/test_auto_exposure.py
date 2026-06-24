#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Unit tests for auto_exposure.py - PID controller and zero-match recovery.
"""

import pytest
from PiFinder.auto_exposure import (
    RECOVERY_LADDER,
    ZeroMatchRecovery,
    ExposurePIDController,
)


@pytest.mark.unit
class TestZeroMatchRecovery:
    """Tests for ZeroMatchRecovery (the single recovery ladder, ADR 0010)."""

    def test_initialization(self):
        """Recovery initializes with the floored ladder and defaults."""
        recovery = ZeroMatchRecovery()
        assert not recovery.is_active()
        assert recovery._trigger_count == 2
        # Ladder starts at the shipped default, climbs, then one short rung.
        assert recovery._ladder == [400000, 800000, 1000000, 200000]
        assert recovery._repeats_per_exposure == 2

    def test_ladder_floors_at_200ms(self):
        """The ladder never descends below 200 ms (ADR 0010)."""
        assert RECOVERY_LADDER == [400000, 800000, 1000000, 200000]
        assert min(RECOVERY_LADDER) == 200000
        assert all(rung >= 200000 for rung in RECOVERY_LADDER)

    def test_custom_initialization(self):
        """Recovery accepts custom trigger and repeat counts."""
        recovery = ZeroMatchRecovery(trigger_count=3, repeats_per_exposure=3)
        assert recovery._trigger_count == 3
        assert recovery._repeats_per_exposure == 3

    def test_trigger_delay(self):
        """Recovery doesn't activate until the trigger count is reached."""
        recovery = ZeroMatchRecovery(trigger_count=2)

        # First zero - should not activate
        result = recovery.handle(50000, 1)
        assert result is None
        assert not recovery.is_active()

        # Second zero - should activate and return first rung (400ms)
        result = recovery.handle(50000, 2)
        assert result == 400000
        assert recovery.is_active()

    def test_ladder_pattern(self):
        """Recovery climbs the ladder, trying each rung twice, then goes short."""
        recovery = ZeroMatchRecovery(trigger_count=1)

        # 400ms ×2
        assert recovery.handle(50000, 1) == 400000
        assert recovery.handle(50000, 2) == 400000
        # 800ms ×2
        assert recovery.handle(50000, 3) == 800000
        assert recovery.handle(50000, 4) == 800000
        # 1000ms ×2
        assert recovery.handle(50000, 5) == 1000000
        assert recovery.handle(50000, 6) == 1000000
        # 200ms ×2 (the single short rung)
        assert recovery.handle(50000, 7) == 200000
        assert recovery.handle(50000, 8) == 200000

    def test_ladder_wraps_around(self):
        """Recovery wraps back to 400ms after the full ladder (4 rungs × 2)."""
        recovery = ZeroMatchRecovery(trigger_count=1)

        # 4 rungs × 2 repeats = 8 attempts
        total_cycles = len(RECOVERY_LADDER) * 2  # = 8
        for i in range(1, total_cycles + 1):
            recovery.handle(50000, i)

        # Next attempt wraps to the first rung
        result = recovery.handle(50000, total_cycles + 1)
        assert result == 400000

    def test_reset(self):
        """Reset clears recovery state."""
        recovery = ZeroMatchRecovery(trigger_count=2)

        # Activate (needs 2 zeros), then advance
        recovery.handle(50000, 1)  # First zero - no action
        recovery.handle(50000, 2)  # Second zero - activates, 400ms attempt 1
        recovery.handle(50000, 3)  # 400ms attempt 2
        recovery.handle(50000, 4)  # 800ms attempt 1
        assert recovery.is_active()

        recovery.reset()
        assert not recovery.is_active()
        assert recovery._exposure_index == 0
        assert recovery._repeat_count == 0

        # After reset, needs the trigger count again
        result = recovery.handle(50000, 1)
        assert result is None


@pytest.mark.unit
class TestExposurePIDController:
    """Tests for ExposurePIDController."""

    def test_initialization_defaults(self):
        """Controller initializes with default parameters."""
        pid = ExposurePIDController()
        assert pid.target_stars == 17
        assert pid.gains_decrease == (500.0, 5.0, 250.0)
        assert pid.gains_increase == (4000.0, 250.0, 1500.0)
        assert pid.min_exposure == 25000
        assert pid.max_exposure == 1000000
        assert pid.deadband == 5
        assert isinstance(pid._recovery, ZeroMatchRecovery)

    def test_initialization_custom_recovery(self):
        """Controller accepts a custom recovery instance."""
        recovery = ZeroMatchRecovery(trigger_count=1)
        pid = ExposurePIDController(recovery=recovery)
        assert pid._recovery is recovery

    def test_pid_within_deadband(self):
        """PID returns None when within deadband."""
        pid = ExposurePIDController(target_stars=15, deadband=2)

        # 15 stars = exactly at target
        result = pid.update(15, 100000)
        assert result is None

        # 14 stars = within deadband (15 - 2 <= 14 <= 15 + 2)
        result = pid.update(14, 100000)
        assert result is None

        # 17 stars = within deadband
        result = pid.update(17, 100000)
        assert result is None

    def test_pid_increases_exposure_for_too_few_stars(self):
        """PID increases exposure when stars < target."""
        pid = ExposurePIDController(target_stars=15, deadband=2)

        # 10 stars = too few (below deadband)
        current_exposure = 100000
        result = pid.update(10, current_exposure)
        assert result is not None
        assert result > current_exposure  # Should increase exposure

    def test_pid_decreases_exposure_for_too_many_stars(self):
        """PID decreases exposure when stars > target."""
        pid = ExposurePIDController(target_stars=15, deadband=2)

        # 25 stars = too many (above deadband)
        current_exposure = 100000
        result = pid.update(25, current_exposure)
        assert result is not None
        assert result < current_exposure  # Should decrease exposure

    def test_pid_clamps_to_min_exposure(self):
        """PID clamps output to minimum exposure."""
        pid = ExposurePIDController(
            target_stars=15,
            min_exposure=25000,
            gains_decrease=(50000.0, 0.0, 0.0),
        )

        # Many stars should drive exposure down to minimum
        result = pid.update(100, 50000)
        assert result == 25000

    def test_pid_clamps_to_max_exposure(self):
        """PID clamps output to maximum exposure."""
        pid = ExposurePIDController(
            target_stars=15,
            max_exposure=1000000,
            gains_increase=(50000.0, 0.0, 0.0),
        )

        # Very few stars should drive exposure up to maximum
        result = pid.update(1, 900000)
        assert result == 1000000

    def test_zero_match_delegates_to_recovery(self):
        """Zero matches delegate to recovery, which walks the ladder."""
        # trigger_count=1 so recovery acts on the first zero-match solve
        pid = ExposurePIDController(recovery=ZeroMatchRecovery(trigger_count=1))

        result = pid.update(0, 50000)
        assert pid._recovery.is_active()
        assert result == 400000  # First rung of the ladder

    def test_zero_match_counter_increments(self):
        """Zero-match counter increments and resets when matches return."""
        pid = ExposurePIDController()

        # First zero
        pid.update(0, 50000)
        assert pid._zero_match_count == 1

        # Second zero
        pid.update(0, 50000)
        assert pid._zero_match_count == 2

        # Finding stars resets counter
        pid.update(15, 50000)
        assert pid._zero_match_count == 0

    def test_recovery_to_pid_transition(self):
        """Transition from recovery back to PID when matches return."""
        pid = ExposurePIDController(target_stars=15, deadband=2)

        # Two zero-match solves activate recovery (default trigger_count=2)
        pid.update(0, 50000)
        pid.update(0, 50000)
        assert pid._recovery.is_active()

        # Find stars - recovery resets, counter clears
        pid.update(15, 50000)
        assert not pid._recovery.is_active()
        assert pid._zero_match_count == 0

    def test_reset_clears_state(self):
        """Reset clears all controller state."""
        pid = ExposurePIDController()

        # Build up some state
        pid.update(10, 100000)  # Sets _last_error and _integral
        pid.update(0, 100000)  # Increments zero-match counter

        assert pid._last_error is not None
        assert pid._zero_match_count > 0

        # Reset
        pid.reset()
        assert pid._integral == 0.0
        assert pid._last_error is None
        assert pid._zero_match_count == 0

    def test_set_target(self):
        """set_target updates target star count."""
        pid = ExposurePIDController(target_stars=15)
        pid.set_target(20)
        assert pid.target_stars == 20

    def test_set_gains(self):
        """set_gains updates PID coefficients."""
        pid = ExposurePIDController()

        pid.set_gains(gains_decrease=(5000.0, 300.0, 2000.0))
        assert pid.gains_decrease == (5000.0, 300.0, 2000.0)

    def test_get_status(self):
        """get_status returns controller state."""
        pid = ExposurePIDController(
            target_stars=15, min_exposure=25000, max_exposure=1000000, deadband=2
        )

        status = pid.get_status()
        assert status["target_stars"] == 15
        assert status["gains_decrease"] == (500.0, 5.0, 250.0)
        assert status["gains_increase"] == (4000.0, 250.0, 1500.0)
        assert status["min_exposure"] == 25000
        assert status["max_exposure"] == 1000000
        assert status["deadband"] == 2
        assert "integral" in status
        assert "last_error" in status


@pytest.mark.unit
class TestPIDRecoveryIntegration:
    """Integration tests for PID controller with real recovery."""

    def test_full_zero_match_recovery_cycle(self):
        """Test complete zero-match recovery and return to PID."""
        pid = ExposurePIDController(target_stars=15, deadband=2)

        # Normal operation - PID control
        current_exposure = 100000
        result = pid.update(10, current_exposure)
        assert result > current_exposure  # Too few stars, increase exposure

        # Zero matches (first time) - no action yet
        result = pid.update(0, current_exposure)
        assert result is None  # Trigger count = 2

        # Zero matches (second time) - recovery activates at 400ms
        result = pid.update(0, current_exposure)
        assert result == 400000  # Ladder starts at 400ms
        assert pid._recovery.is_active()

        # Continue on the first rung
        result = pid.update(0, current_exposure)
        assert result == 400000  # Second attempt at 400ms

        # Still zero matches, ladder advances
        result = pid.update(0, current_exposure)
        assert result == 800000  # Move to 800ms

        # Find stars again - return to PID
        result = pid.update(15, 50000)
        assert not pid._recovery.is_active()
        assert pid._zero_match_count == 0
        assert result is None  # Within deadband
