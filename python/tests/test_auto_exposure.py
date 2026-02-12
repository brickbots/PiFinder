#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Unit tests for auto_exposure.py - PID controller and zero-star handler plugins.
"""

import pytest
from typing import Optional
from PIL import Image
from PiFinder.auto_exposure import (
    ZeroStarHandler,
    SweepZeroStarHandler,
    ExponentialSweepZeroStarHandler,
    ResetZeroStarHandler,
    HistogramZeroStarHandler,
    ExposurePIDController,
)


# Mock handler for testing the abstract base class
class MockZeroStarHandler(ZeroStarHandler):
    """Mock handler for testing."""

    def __init__(self):
        super().__init__()
        self.handle_called = False
        self.reset_called = False

    def handle(
        self,
        current_exposure: int,
        zero_count: int,
        image: Optional[Image.Image] = None,
    ):
        self.handle_called = True
        return 100000  # Return 100ms

    def reset(self):
        super().reset()
        self.reset_called = True
        self._active = False


@pytest.mark.unit
class TestZeroStarHandler:
    """Tests for ZeroStarHandler abstract base class."""

    def test_abstract_methods(self):
        """Cannot instantiate abstract base class."""
        with pytest.raises(TypeError):
            ZeroStarHandler()

    def test_mock_handler_interface(self):
        """Mock handler implements the interface correctly."""
        handler = MockZeroStarHandler()
        assert not handler.is_active()

        # Test handle
        result = handler.handle(50000, 1)
        assert handler.handle_called
        assert result == 100000

        # Test reset
        handler._active = True
        assert handler.is_active()
        handler.reset()
        assert handler.reset_called
        assert not handler.is_active()


@pytest.mark.unit
class TestSweepZeroStarHandler:
    """Tests for SweepZeroStarHandler recovery strategy."""

    def test_initialization(self):
        """Handler initializes with correct defaults."""
        handler = SweepZeroStarHandler()
        assert not handler.is_active()
        assert handler._trigger_count == 2
        # Sweep starts at 400ms, goes up, then tries shorter exposures
        assert handler._exposures == [
            400000,
            800000,
            1000000,
            200000,
            100000,
            50000,
            25000,
        ]
        assert handler._repeats_per_exposure == 2

    def test_custom_initialization(self):
        """Handler accepts custom parameters."""
        handler = SweepZeroStarHandler(
            min_exposure=10000, max_exposure=500000, trigger_count=3
        )
        assert handler._trigger_count == 3

    def test_trigger_delay(self):
        """Handler doesn't activate until trigger count is reached."""
        handler = SweepZeroStarHandler(trigger_count=2)

        # First zero - should not activate
        result = handler.handle(50000, 1)
        assert result is None
        assert not handler.is_active()

        # Second zero - should activate and return first exposure (400ms)
        result = handler.handle(50000, 2)
        assert result == 400000
        assert handler.is_active()

    def test_sweep_pattern_start_at_400ms(self):
        """Sweep starts at 400ms and repeats each exposure 2 times."""
        handler = SweepZeroStarHandler(trigger_count=1)

        # Activate sweep - starts at 400ms
        result = handler.handle(50000, 1)
        assert result == 400000  # First attempt at 400ms

        # Second attempt at 400ms
        result = handler.handle(50000, 2)
        assert result == 400000

        # Move to 800ms
        result = handler.handle(50000, 3)
        assert result == 800000

        # Second attempt at 800ms
        result = handler.handle(50000, 4)
        assert result == 800000

        # Move to 1000ms
        result = handler.handle(50000, 5)
        assert result == 1000000

    def test_sweep_continues_to_shorter_exposures(self):
        """After longer exposures, sweep tries shorter ones."""
        handler = SweepZeroStarHandler(trigger_count=1)

        # 400ms: 2 times (first in sweep)
        handler.handle(50000, 1)  # 400ms attempt 1
        handler.handle(50000, 2)  # 400ms attempt 2
        # 800ms: 2 times
        handler.handle(50000, 3)  # 800ms attempt 1
        handler.handle(50000, 4)  # 800ms attempt 2
        # 1000ms: 2 times
        handler.handle(50000, 5)  # 1000ms attempt 1
        handler.handle(50000, 6)  # 1000ms attempt 2

        # Now at 200ms - sweep continues with shorter exposures
        result = handler.handle(50000, 7)
        assert result == 200000  # Attempt 1

        result = handler.handle(50000, 8)
        assert result == 200000  # Attempt 2

        # Move to 100ms
        result = handler.handle(50000, 9)
        assert result == 100000

    def test_sweep_wraps_around(self):
        """Sweep wraps back to start (400ms) after completing all exposures."""
        handler = SweepZeroStarHandler(trigger_count=1)

        # Fast-forward through entire sweep
        # 400ms (2×), 800ms (2×), 1000ms (2×), 200ms (2×), 100ms (2×), 50ms (2×), 25ms (2×)
        total_cycles = 2 + 2 + 2 + 2 + 2 + 2 + 2  # = 14

        for i in range(1, total_cycles + 1):
            handler.handle(50000, i)

        # Next cycle should wrap to 400ms (start of sweep)
        result = handler.handle(50000, total_cycles + 1)
        assert result == 400000

    def test_reset(self):
        """Reset clears handler state."""
        handler = SweepZeroStarHandler(trigger_count=2)

        # Activate sweep (need 2 zeros)
        handler.handle(50000, 1)  # First zero - no action
        handler.handle(50000, 2)  # Second zero - activates, 25ms attempt 1
        handler.handle(50000, 3)  # 25ms attempt 2
        handler.handle(50000, 4)  # 50ms attempt 1
        assert handler.is_active()

        # Reset
        handler.reset()
        assert not handler.is_active()
        assert handler._exposure_index == 0
        assert handler._repeat_count == 0

        # After reset, should start from beginning (needs 2 zeros again)
        result = handler.handle(50000, 1)
        assert result is None  # Trigger count = 2, so first call returns None


@pytest.mark.unit
class TestExponentialSweepZeroStarHandler:
    """Tests for ExponentialSweepZeroStarHandler recovery strategy."""

    def test_initialization(self):
        """Handler initializes with correct defaults."""
        handler = ExponentialSweepZeroStarHandler()
        assert not handler.is_active()
        assert handler._trigger_count == 2
        assert handler._sweep_steps == 7
        assert handler._repeats_per_exposure == 2
        assert len(handler._exposures) == 7
        # Check exposures are logarithmically spaced (within tolerance for rounding)
        assert abs(handler._exposures[0] - 25000) < 10
        assert abs(handler._exposures[-1] - 1000000) < 10

    def test_custom_initialization(self):
        """Handler accepts custom parameters."""
        handler = ExponentialSweepZeroStarHandler(
            min_exposure=10000,
            max_exposure=500000,
            trigger_count=3,
            sweep_steps=5,
            repeats_per_exposure=3,
        )
        assert handler._trigger_count == 3
        assert handler._sweep_steps == 5
        assert handler._repeats_per_exposure == 3
        assert len(handler._exposures) == 5
        assert abs(handler._exposures[0] - 10000) < 10
        assert abs(handler._exposures[-1] - 500000) < 10

    def test_trigger_delay(self):
        """Handler doesn't activate until trigger count is reached."""
        handler = ExponentialSweepZeroStarHandler(trigger_count=2)

        # First zero - should not activate
        result = handler.handle(50000, 1)
        assert result is None
        assert not handler.is_active()

        # Second zero - should activate and return first exposure
        result = handler.handle(50000, 2)
        assert abs(result - 25000) < 10  # Approximately 25000
        assert handler.is_active()

    def test_exponential_sweep_pattern(self):
        """Sweep uses logarithmic spacing and repeats each exposure."""
        handler = ExponentialSweepZeroStarHandler(
            trigger_count=1, sweep_steps=4, repeats_per_exposure=2
        )

        # Activate sweep
        exp1 = handler.handle(50000, 1)
        assert abs(exp1 - 25000) < 10  # Approximately 25000

        # Second attempt at first exposure
        exp2 = handler.handle(50000, 2)
        assert exp2 == exp1  # Should be same exposure

        # Move to second exposure (logarithmic spacing means not just doubling)
        exp3 = handler.handle(50000, 3)
        assert exp3 > exp1  # Should be higher
        # Not exactly double due to logarithmic spacing
        assert abs(exp3 - exp1 * 2) > 1000  # Should differ from doubling

        # Second attempt at second exposure
        exp4 = handler.handle(50000, 4)
        assert exp4 == exp3

    def test_logarithmic_spacing(self):
        """Exposures are logarithmically spaced, not linear."""
        handler = ExponentialSweepZeroStarHandler(
            min_exposure=25000, max_exposure=1000000, sweep_steps=7
        )

        exposures = handler._exposures
        assert len(exposures) == 7

        # Check spacing increases exponentially
        # Ratio between consecutive exposures should be roughly constant
        ratios = [exposures[i + 1] / exposures[i] for i in range(len(exposures) - 1)]

        # All ratios should be similar (within 20% tolerance)
        avg_ratio = sum(ratios) / len(ratios)
        for ratio in ratios:
            assert abs(ratio - avg_ratio) / avg_ratio < 0.2

    def test_sweep_wraps_around(self):
        """Sweep wraps back to minimum after reaching maximum."""
        handler = ExponentialSweepZeroStarHandler(
            trigger_count=1, sweep_steps=3, repeats_per_exposure=2
        )

        # Fast-forward through entire sweep (3 exposures × 2 repeats = 6 cycles)
        for i in range(1, 7):
            handler.handle(50000, i)

        # Next cycle should wrap to first exposure
        result = handler.handle(50000, 7)
        assert result == handler._exposures[0]  # Back to minimum

    def test_reset(self):
        """Reset clears handler state."""
        handler = ExponentialSweepZeroStarHandler(trigger_count=2)

        # Activate sweep
        handler.handle(50000, 1)  # First zero - no action
        handler.handle(50000, 2)  # Second zero - activates
        handler.handle(50000, 3)  # First attempt complete
        handler.handle(50000, 4)  # Move to second exposure
        assert handler.is_active()

        # Reset
        handler.reset()
        assert not handler.is_active()
        assert handler._exposure_index == 0
        assert handler._repeat_count == 0

        # After reset, should start from beginning
        result = handler.handle(50000, 1)
        assert result is None  # Trigger count = 2


@pytest.mark.unit
class TestExposurePIDController:
    """Tests for ExposurePIDController with plugin architecture."""

    def test_initialization_defaults(self):
        """Controller initializes with default parameters."""
        pid = ExposurePIDController()
        assert pid.target_stars == 17
        assert pid.gains_decrease == (500.0, 5.0, 250.0)
        assert pid.gains_increase == (4000.0, 250.0, 1500.0)
        assert pid.min_exposure == 25000
        assert pid.max_exposure == 1000000
        assert pid.deadband == 5
        assert isinstance(pid._zero_star_handler, SweepZeroStarHandler)

    def test_initialization_custom_handler(self):
        """Controller accepts custom zero-star handler."""
        mock_handler = MockZeroStarHandler()
        pid = ExposurePIDController(zero_star_handler=mock_handler)
        assert pid._zero_star_handler is mock_handler

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
            target_stars=15, min_exposure=25000, gains_decrease=(50000.0, 0.0, 0.0)
        )

        # Many stars should drive exposure down to minimum
        result = pid.update(100, 50000)
        assert result == 25000

    def test_pid_clamps_to_max_exposure(self):
        """PID clamps output to maximum exposure."""
        pid = ExposurePIDController(
            target_stars=15, max_exposure=1000000, gains_increase=(50000.0, 0.0, 0.0)
        )

        # Very few stars should drive exposure up to maximum
        result = pid.update(1, 900000)
        assert result == 1000000

    def test_zero_stars_delegates_to_handler(self):
        """Zero stars delegates to handler plugin."""
        mock_handler = MockZeroStarHandler()
        pid = ExposurePIDController(zero_star_handler=mock_handler)

        result = pid.update(0, 50000)
        assert mock_handler.handle_called
        assert result == 100000  # Mock returns 100ms

    def test_zero_star_counter_increments(self):
        """Zero-star counter increments correctly."""
        mock_handler = MockZeroStarHandler()
        pid = ExposurePIDController(zero_star_handler=mock_handler)

        # First zero
        pid.update(0, 50000)
        assert pid._zero_star_count == 1

        # Second zero
        pid.update(0, 50000)
        assert pid._zero_star_count == 2

        # Finding stars resets counter
        pid.update(15, 50000)
        assert pid._zero_star_count == 0

    def test_recovery_to_pid_transition(self):
        """Transition from handler mode back to PID when stars found."""
        mock_handler = MockZeroStarHandler()
        pid = ExposurePIDController(zero_star_handler=mock_handler)

        # Activate handler
        mock_handler._active = True

        # Find stars - should reset handler
        _ = pid.update(15, 50000)
        assert mock_handler.reset_called
        assert pid._zero_star_count == 0

    def test_reset_clears_state(self):
        """Reset clears all controller state."""
        pid = ExposurePIDController()

        # Build up some state
        pid.update(10, 100000)  # Sets _last_error and _integral
        pid.update(0, 100000)  # Increments zero counter

        assert pid._last_error is not None
        assert pid._zero_star_count > 0

        # Reset
        pid.reset()
        assert pid._integral == 0.0
        assert pid._last_error is None
        assert pid._zero_star_count == 0

    def test_set_target(self):
        """set_target updates target star count."""
        pid = ExposurePIDController(target_stars=15)
        pid.set_target(20)
        assert pid.target_stars == 20

    def test_set_gains(self):
        """set_gains updates PID coefficients."""
        pid = ExposurePIDController()

        # Update decrease gains
        pid.set_gains(gains_decrease=(5000.0, 300.0, 2000.0))
        assert pid.gains_decrease == (5000.0, 300.0, 2000.0)
        assert pid.gains_increase == (4000.0, 250.0, 1500.0)  # Unchanged (new default)

        # Update increase gains
        pid.set_gains(gains_increase=(10000.0, 600.0, 4000.0))
        assert pid.gains_increase == (10000.0, 600.0, 4000.0)
        assert pid.gains_decrease == (5000.0, 300.0, 2000.0)  # Unchanged

    def test_get_status(self):
        """get_status returns controller state."""
        pid = ExposurePIDController(
            target_stars=15, min_exposure=25000, max_exposure=1000000, deadband=2
        )

        status = pid.get_status()
        assert status["target_stars"] == 15
        assert status["gains_decrease"] == (500.0, 5.0, 250.0)  # New defaults
        assert status["gains_increase"] == (4000.0, 250.0, 1500.0)  # New defaults
        assert status["min_exposure"] == 25000
        assert status["max_exposure"] == 1000000
        assert status["deadband"] == 2
        assert "integral" in status
        assert "last_error" in status


class TestPIDIntegration:
    """Integration tests for PID controller with real sweep handler."""

    def test_full_zero_star_recovery_cycle(self):
        """Test complete zero-star recovery and return to PID."""
        pid = ExposurePIDController(target_stars=15, deadband=2)

        # Normal operation - PID control
        current_exposure = 100000
        result = pid.update(10, current_exposure)
        assert result > current_exposure  # Too few stars, increase exposure

        # Zero stars (first time) - no action yet
        result = pid.update(0, current_exposure)
        assert result is None  # Trigger count = 2

        # Zero stars (second time) - sweep activates at 400ms
        result = pid.update(0, current_exposure)
        assert result == 400000  # Sweep starts at 400ms
        assert pid._zero_star_handler.is_active()

        # Continue sweep
        result = pid.update(0, current_exposure)
        assert result == 400000  # Second attempt at 400ms

        # Still zero stars, sweep continues
        result = pid.update(0, current_exposure)
        assert result == 800000  # Move to 800ms

        # Find stars again - return to PID
        result = pid.update(15, 50000)
        assert not pid._zero_star_handler.is_active()
        assert pid._zero_star_count == 0
        assert result is None  # Within deadband

    def test_pid_proportional_response(self):
        """Test that PID responds proportionally to error magnitude."""
        pid = ExposurePIDController(
            target_stars=15,
            gains_decrease=(1000.0, 0.0, 0.0),
            gains_increase=(1000.0, 0.0, 0.0),
            deadband=0,
        )

        current_exposure = 100000

        # Small error (1 star off)
        result_small = pid.update(14, current_exposure)
        small_change = result_small - current_exposure

        # Reset for clean test
        pid.reset()

        # Large error (10 stars off)
        result_large = pid.update(5, current_exposure)
        large_change = result_large - current_exposure

        # Large error should produce larger correction
        assert abs(large_change) > abs(small_change)

    def test_integral_windup_protection(self):
        """Test that integral term is clamped to prevent windup."""
        pid = ExposurePIDController(
            target_stars=15,
            gains_decrease=(0.0, 100.0, 0.0),
            gains_increase=(0.0, 100.0, 0.0),
            min_exposure=25000,
            max_exposure=1000000,
        )

        # Feed consistent error to build up integral
        current_exposure = 100000
        for _ in range(100):
            result = pid.update(5, current_exposure)
            current_exposure = result

        # Integral should be clamped, not infinite
        max_integral = (pid.max_exposure - pid.min_exposure) / (
            2.0 * pid.gains_increase[1]
        )
        assert abs(pid._integral) <= max_integral

    def test_derivative_dampens_oscillation(self):
        """Test that derivative term responds to rate of change."""
        pid = ExposurePIDController(
            target_stars=15,
            gains_decrease=(0.0, 0.0, 1000.0),
            gains_increase=(0.0, 0.0, 1000.0),
            deadband=0,
        )

        current_exposure = 100000

        # First update - no derivative yet (no previous error)
        result1 = pid.update(10, current_exposure)
        # With only D term and no previous error, first result equals input
        assert result1 == current_exposure

        # Second update - derivative kicks in (error changed from 5 to 10)
        result2 = pid.update(5, current_exposure)
        # Error went from 5 to 10 (increased by 5), derivative should respond
        assert result2 != current_exposure

        # Third update - error stabilizing (changed from 10 to 11, smaller change)
        result3 = pid.update(4, current_exposure)
        # Error went from 10 to 11 (increased by 1), smaller derivative response
        assert result3 != current_exposure

        # The derivative response should differ based on rate of change
        # Second update had larger error change (5) than third (1)
        change2 = abs(result2 - current_exposure)
        change3 = abs(result3 - current_exposure)
        assert change2 > change3  # Larger error change = larger correction


@pytest.mark.unit
class TestResetZeroStarHandler:
    """Tests for ResetZeroStarHandler recovery strategy."""

    def test_initialization(self):
        """Handler initializes with correct defaults."""
        handler = ResetZeroStarHandler()
        assert not handler.is_active()
        assert handler._reset_exposure == 400000
        assert handler._trigger_count == 2

    def test_custom_reset_exposure(self):
        """Handler accepts custom reset exposure."""
        handler = ResetZeroStarHandler(reset_exposure=500000, trigger_count=3)
        assert handler._reset_exposure == 500000
        assert handler._trigger_count == 3

    def test_trigger_delay(self):
        """Handler doesn't activate until trigger count is reached."""
        handler = ResetZeroStarHandler(trigger_count=2)

        # First zero - should not activate
        result = handler.handle(25000, 1)
        assert result is None
        assert not handler.is_active()

        # Second zero - should activate and return reset exposure
        result = handler.handle(25000, 2)
        assert result == 400000
        assert handler.is_active()

    def test_consistent_reset_value(self):
        """Handler returns same reset value each time."""
        handler = ResetZeroStarHandler(reset_exposure=300000, trigger_count=1)

        # Activate
        result1 = handler.handle(50000, 1)
        assert result1 == 300000

        # Subsequent calls return same value
        result2 = handler.handle(50000, 2)
        assert result2 == 300000

        result3 = handler.handle(100000, 3)
        assert result3 == 300000

    def test_reset(self):
        """Reset clears handler state."""
        handler = ResetZeroStarHandler(trigger_count=1)

        # Activate
        handler.handle(50000, 1)
        assert handler.is_active()

        # Reset
        handler.reset()
        assert not handler.is_active()


@pytest.mark.unit
class TestHistogramZeroStarHandler:
    """Tests for HistogramZeroStarHandler recovery strategy."""

    def test_initialization(self):
        """Handler initializes with correct defaults."""
        handler = HistogramZeroStarHandler()
        assert not handler.is_active()
        assert handler._min_exposure == 25000
        assert handler._max_exposure == 1000000
        assert handler._trigger_count == 2
        assert handler._sweep_steps == 8

    def test_trigger_delay(self):
        """Handler doesn't activate until trigger count is reached."""
        handler = HistogramZeroStarHandler(trigger_count=2)

        # First zero - should not activate
        result = handler.handle(50000, 1)
        assert result is None
        assert not handler.is_active()

        # Second zero - should activate and start sweep
        result = handler.handle(50000, 2)
        assert result is not None
        assert handler.is_active()
        # Should return first sweep exposure (approximately min_exposure)
        assert abs(result - 25000) < 10  # Allow small rounding differences

    def test_quick_sweep_sequence(self):
        """Handler performs quick sweep through exposures."""
        handler = HistogramZeroStarHandler(trigger_count=1, sweep_steps=5)

        # Activation - returns first sweep exposure
        result1 = handler.handle(50000, 1)
        assert result1 is not None
        assert handler.is_active()

        # Subsequent calls advance through sweep
        result2 = handler.handle(result1, 1)
        assert result2 is not None
        assert result2 > result1  # Should increase

        result3 = handler.handle(result2, 1)
        assert result3 is not None
        assert result3 > result2

        result4 = handler.handle(result3, 1)
        assert result4 is not None
        assert result4 > result3

        result5 = handler.handle(result4, 1)
        assert result5 is not None
        assert result5 > result4

        # After sweep_steps, should settle on middle exposure
        _result6 = handler.handle(result5, 1)
        # Either returns target or None (if already at target)
        # Since we've completed the sweep, it should settle

    def test_settles_after_sweep(self):
        """Handler settles on middle exposure after sweep completes."""
        handler = HistogramZeroStarHandler(trigger_count=1, sweep_steps=4)

        # Run through sweep
        exposures = []
        exp = 50000
        for i in range(6):  # More than sweep_steps to ensure completion
            result = handler.handle(exp, 1)
            if result is not None:
                exposures.append(result)
                exp = result

        # Should have collected sweep exposures
        assert len(exposures) >= 4

        # Final exposure should be held
        final_exp = exposures[-1]
        result = handler.handle(final_exp, 1)
        # Should either return None (holding) or return same exposure
        assert result is None or result == final_exp

    def test_reset(self):
        """Reset clears handler state including sweep progress."""
        handler = HistogramZeroStarHandler(trigger_count=1)

        # Activate and start sweep
        handler.handle(50000, 1)
        assert handler.is_active()
        assert handler._sweep_index > 0 or len(handler._sweep_exposures) > 0

        # Reset
        handler.reset()
        assert not handler.is_active()
        assert handler._sweep_index == 0
        assert len(handler._sweep_exposures) == 0

    def test_histogram_analysis_dark_image(self):
        """Handler correctly identifies dark image as non-viable."""
        import numpy as np
        from PIL import Image

        handler = HistogramZeroStarHandler(trigger_count=1)

        # Create dark image (mean < 20)
        dark_array = np.ones((128, 128), dtype=np.uint8) * 10
        dark_image = Image.fromarray(dark_array, mode="L")

        viable, metrics = handler._analyze_image_viability(dark_image)
        assert not viable
        assert not metrics["has_signal"]  # Too dark
        assert metrics["mean"] < 20

    def test_histogram_analysis_flat_image(self):
        """Handler correctly identifies flat image as non-viable."""
        import numpy as np
        from PIL import Image

        handler = HistogramZeroStarHandler(trigger_count=1)

        # Create flat image (std < 5)
        flat_array = np.ones((128, 128), dtype=np.uint8) * 100
        flat_image = Image.fromarray(flat_array, mode="L")

        viable, metrics = handler._analyze_image_viability(flat_image)
        assert not viable
        assert not metrics["has_structure"]  # Too flat
        assert metrics["std"] < 5

    def test_histogram_analysis_saturated_image(self):
        """Handler correctly identifies saturated image as non-viable."""
        import numpy as np
        from PIL import Image

        handler = HistogramZeroStarHandler(trigger_count=1)

        # Create saturated image (> 5% pixels > 250)
        saturated_array = np.ones((128, 128), dtype=np.uint8) * 255
        saturated_image = Image.fromarray(saturated_array, mode="L")

        viable, metrics = handler._analyze_image_viability(saturated_image)
        assert not viable
        assert not metrics["not_saturated"]  # Too saturated
        assert metrics["saturation_pct"] > 5

    def test_histogram_analysis_viable_image(self):
        """Handler correctly identifies viable image."""
        import numpy as np
        from PIL import Image

        handler = HistogramZeroStarHandler(trigger_count=1)

        # Create viable image (mean > 20, std > 5, not saturated)
        # Add some noise/texture
        viable_array = np.random.normal(80, 15, (128, 128)).astype(np.uint8)
        viable_image = Image.fromarray(viable_array, mode="L")

        viable, metrics = handler._analyze_image_viability(viable_image)
        assert viable
        assert metrics["has_signal"]
        assert metrics["has_structure"]
        assert metrics["not_saturated"]
        assert metrics["mean"] > 20
        assert metrics["std"] > 5

    def test_histogram_sweep_with_images(self):
        """Handler performs sweep with image analysis and settles on highest viable."""
        import numpy as np
        from PIL import Image

        handler = HistogramZeroStarHandler(trigger_count=1, sweep_steps=4)

        # Activation - returns first exposure
        exp1 = handler.handle(50000, 1)
        assert exp1 is not None
        assert handler.is_active()

        # Create images for sweep
        # First image: too dark (non-viable)
        dark_image = Image.fromarray(np.ones((128, 128), dtype=np.uint8) * 10, mode="L")
        exp2 = handler.handle(exp1, 1, dark_image)
        assert exp2 is not None
        assert exp2 > exp1  # Should continue sweep

        # Second image: viable (but not the highest)
        viable_image1 = Image.fromarray(
            np.random.normal(80, 15, (128, 128)).astype(np.uint8), mode="L"
        )
        exp3 = handler.handle(exp2, 1, viable_image1)
        assert exp3 is not None  # Should continue sweep, not settle yet
        assert exp3 > exp2

        # Third image: also viable (higher exposure)
        viable_image2 = Image.fromarray(
            np.random.normal(90, 20, (128, 128)).astype(np.uint8), mode="L"
        )
        exp4 = handler.handle(exp3, 1, viable_image2)
        assert exp4 is not None  # Should continue sweep
        assert exp4 > exp3

        # Fourth image: complete the sweep
        viable_image3 = Image.fromarray(
            np.random.normal(100, 25, (128, 128)).astype(np.uint8), mode="L"
        )
        result = handler.handle(exp4, 1, viable_image3)
        # Sweep should signal completion (return None since no more exposures)
        assert result is None

        # Next call should analyze final image and settle on target exposure
        settled_exp = handler.handle(exp4, 1)

        # Should settle on highest viable (exp4)
        assert handler._target_exposure is not None
        assert handler._target_exposure == exp4  # Highest viable exposure
        # Since current_exposure == target, returns None (already at target)
        assert settled_exp is None or settled_exp == exp4
