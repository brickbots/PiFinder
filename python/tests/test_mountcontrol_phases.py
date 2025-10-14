#!/usr/bin/env python3

import pytest
from queue import Queue
import time
from unittest.mock import Mock

# Import the classes we want to test
from PiFinder.mountcontrol_interface import MountControlBase, MountControlPhases
from PiFinder.state import SharedStateObj


class MountControlPhasesTestable(MountControlBase):
    """Testable subclass of MountControlBase for testing _process_phase method."""

    def __init__(self, mount_queue, console_queue, shared_state):
        super().__init__(mount_queue, console_queue, shared_state)

        # Create mocks for all abstract methods but don't mock the helper methods
        self.init_mount = Mock(return_value=True)
        self.sync_mount = Mock(return_value=True)
        self.stop_mount = Mock(return_value=True)
        self.move_mount_to_target = Mock(return_value=True)
        self.is_mount_moving = Mock(return_value=False)
        self.adjust_mount_drift_rates = Mock(return_value=True)
        self.move_mount_manual = Mock(return_value=True)
        self.set_mount_step_size = Mock(return_value=True)
        self.disconnect_mount = Mock(return_value=True)


class TestMountControlPhases:
    """
    Test harness for MountControlBase._process_phase method.

    This test harness creates a mock environment with:
    - Initialized queues for mount, console, and logging
    - Mocked shared state object with solution data
    - Test cases for each mount control phase and their transitions
    - Does NOT mock _stop_mount, _move_mount_manual, _goto_target helper methods
    """

    def setup_method(self):
        """Setup test environment before each test."""
        # Create mock queues
        self.mount_queue = Queue()
        self.console_queue = Queue()

        # Create mock shared state with solution capabilities
        self.shared_state = Mock(spec=SharedStateObj)
        # Create a mock solution that supports both attribute and dictionary access
        self.mock_solution = {
            "RA_target": 15.5,  # degrees
            "Dec_target": 45.2,  # degrees
        }
        self.shared_state.solution.return_value = self.mock_solution
        self.shared_state.solve_state.return_value = True

        # Create the testable mount control instance
        self.mount_control = MountControlPhasesTestable(
            self.mount_queue, self.console_queue, self.shared_state
        )

        # Set initial target coordinates for refine tests
        self.mount_control.target_ra = 15.5
        self.mount_control.target_dec = 45.2

        # Set initial current position (what the mount reports)
        self.mount_control.current_ra = 15.5
        self.mount_control.current_dec = 45.2

    def _execute_phase_generator(
        self, retry_count=3, delay=0.01, max_iterations=50, timeout=1.0
    ):
        """Helper to execute a phase generator with protection against infinite loops."""
        phase_generator = self.mount_control._process_phase(
            retry_count=retry_count, delay=delay
        )
        if phase_generator is not None:
            iterations = 0
            start_time = time.time()
            try:
                while (
                    iterations < max_iterations and (time.time() - start_time) < timeout
                ):
                    next(phase_generator)
                    iterations += 1
                    time.sleep(delay / 3)
                if iterations >= max_iterations:
                    # This is expected for some retry scenarios, not necessarily an error
                    assert False, "Max iterations reached in phase generator"
            except StopIteration:
                pass

    def test_mount_unknown_phase(self):
        """Test MOUNT_UNKNOWN phase does nothing."""
        self.mount_control.state = MountControlPhases.MOUNT_UNKNOWN

        # Execute the phase
        self._execute_phase_generator()

        # Verify no abstract methods were called
        self.mount_control.init_mount.assert_not_called()
        self.mount_control.sync_mount.assert_not_called()
        self.mount_control.stop_mount.assert_not_called()
        self.mount_control.move_mount_to_target.assert_not_called()
        self.mount_control.is_mount_moving.assert_not_called()
        self.mount_control.adjust_mount_drift_rates.assert_not_called()
        self.mount_control.move_mount_manual.assert_not_called()
        self.mount_control.set_mount_step_size.assert_not_called()
        self.mount_control.disconnect_mount.assert_not_called()

        # Verify state unchanged
        assert self.mount_control.state == MountControlPhases.MOUNT_UNKNOWN

        # Verify no console messages
        assert self.console_queue.empty()

    def test_mount_init_telescope_success(self):
        """Test successful MOUNT_INIT_TELESCOPE phase."""
        self.mount_control.state = MountControlPhases.MOUNT_INIT_TELESCOPE

        # Execute the phase
        self._execute_phase_generator()

        # Verify init_mount was called
        self.mount_control.init_mount.assert_called_once()

        # Verify state transition to MOUNT_TRACKING (changed in mountcontrol_interface.py:761)
        assert self.mount_control.state == MountControlPhases.MOUNT_TRACKING

        # Verify no warning messages
        assert self.console_queue.empty()

    def test_mount_init_telescope_failure_with_retry(self):
        """Test MOUNT_INIT_TELESCOPE phase with initial failure and successful retry."""
        self.mount_control.state = MountControlPhases.MOUNT_INIT_TELESCOPE

        # Mock init_mount to fail first time, succeed second time
        self.mount_control.init_mount.side_effect = [False, True]

        # Execute the phase with sufficient time for retries
        self._execute_phase_generator(retry_count=3, delay=0.001, timeout=1.0)

        # Verify init_mount was called twice (first fails, second succeeds)
        assert self.mount_control.init_mount.call_count == 2

        # Verify state transition to MOUNT_TRACKING after successful init (changed in mountcontrol_interface.py:761)
        assert self.mount_control.state == MountControlPhases.MOUNT_TRACKING

        # Verify no warning messages since it eventually succeeded
        assert self.console_queue.empty()

    def test_mount_init_telescope_total_failure(self):
        """Test MOUNT_INIT_TELESCOPE phase that fails all retries."""
        self.mount_control.state = MountControlPhases.MOUNT_INIT_TELESCOPE

        # Mock init_mount to always fail
        self.mount_control.init_mount.return_value = False

        # Execute the phase with 2 retries and sufficient time
        self._execute_phase_generator(retry_count=3, delay=0.001, timeout=1.0)

        # Verify init_mount was called 3 times (initial + 2 retries)
        assert self.mount_control.init_mount.call_count == 3

        # Verify state transition to MOUNT_UNKNOWN after total failure (per system reminder line 511)
        assert self.mount_control.state == MountControlPhases.MOUNT_UNKNOWN

        # Verify warning message was sent
        assert not self.console_queue.empty()
        warning_msg = self.console_queue.get()
        assert warning_msg[0] == "WARNING"

    @pytest.mark.parametrize(
        "phase", [MountControlPhases.MOUNT_STOPPED, MountControlPhases.MOUNT_TRACKING]
    )
    def test_mount_stopped_and_tracking_phases(self, phase):
        """Test MOUNT_STOPPED and MOUNT_TRACKING phases do nothing."""
        self.mount_control.state = phase

        # Execute the phase
        self._execute_phase_generator()

        # Verify no abstract methods were called
        self.mount_control.init_mount.assert_not_called()
        self.mount_control.sync_mount.assert_not_called()
        self.mount_control.stop_mount.assert_not_called()
        self.mount_control.move_mount_to_target.assert_not_called()
        self.mount_control.is_mount_moving.assert_not_called()
        self.mount_control.adjust_mount_drift_rates.assert_not_called()
        self.mount_control.move_mount_manual.assert_not_called()
        self.mount_control.set_mount_step_size.assert_not_called()
        self.mount_control.disconnect_mount.assert_not_called()

        # Verify state unchanged
        assert self.mount_control.state == phase

        # Verify no console messages
        assert self.console_queue.empty()

    def test_mount_target_acquisition_move_target_reached(self):
        """Test MOUNT_TARGET_ACQUISITION_MOVE phase when target is reached."""
        self.mount_control.state = MountControlPhases.MOUNT_TARGET_ACQUISITION_MOVE
        self.mount_control.target_reached = True

        # Execute the phase
        self._execute_phase_generator()

        # Verify state transition to MOUNT_TARGET_ACQUISITION_REFINE
        assert (
            self.mount_control.state
            == MountControlPhases.MOUNT_TARGET_ACQUISITION_REFINE
        )

        # Verify no console messages
        assert self.console_queue.empty()

    def test_mount_target_acquisition_move_waiting(self):
        """Test MOUNT_TARGET_ACQUISITION_MOVE phase when waiting (mount still moving)."""
        self.mount_control.state = MountControlPhases.MOUNT_TARGET_ACQUISITION_MOVE
        self.mount_control.target_reached = False
        # Mount is still moving, so we should stay in the same state
        self.mount_control.is_mount_moving.return_value = True

        # Execute the phase
        self._execute_phase_generator()

        # Verify state unchanged (still waiting)
        assert (
            self.mount_control.state == MountControlPhases.MOUNT_TARGET_ACQUISITION_MOVE
        )

        # Verify no console messages
        assert self.console_queue.empty()

    def test_mount_target_acquisition_refine_no_solve(self):
        """Test MOUNT_TARGET_ACQUISITION_REFINE phase when solve fails."""
        self.mount_control.state = MountControlPhases.MOUNT_TARGET_ACQUISITION_REFINE

        # Mock solve_state to always return False (no solution)
        self.shared_state.solve_state.return_value = False
        # Also set solution to None to simulate no solution
        self.shared_state.solution.return_value = None

        # Execute the phase with 2 retries
        phase_generator = self.mount_control._process_phase(retry_count=2, delay=0.01)

        start_time = time.time()
        try:
            while time.time() - start_time < 0.5:
                next(phase_generator)
        except StopIteration:
            pass

        # Verify state transition to MOUNT_TRACKING after solve failure
        assert self.mount_control.state == MountControlPhases.MOUNT_TRACKING

        # Verify warning message was sent
        assert not self.console_queue.empty()
        warning_msg = self.console_queue.get()
        assert warning_msg[0] == "WARNING"

    def test_mount_target_acquisition_refine_target_acquired(self):
        """Test MOUNT_TARGET_ACQUISITION_REFINE phase when target is acquired within tolerance."""
        self.mount_control.state = MountControlPhases.MOUNT_TARGET_ACQUISITION_REFINE

        # Set target and solution to be within tolerance (0.01 degrees)
        self.mount_control.target_ra = 15.5
        self.mount_control.target_dec = 45.2
        self.mock_solution["RA_target"] = 15.505  # Within 0.01 degrees
        self.mock_solution["Dec_target"] = 45.205  # Within 0.01 degrees

        # Execute the phase
        self._execute_phase_generator()

        # Verify state transition to MOUNT_DRIFT_COMPENSATION
        assert self.mount_control.state == MountControlPhases.MOUNT_DRIFT_COMPENSATION

        # Verify no warning messages
        assert self.console_queue.empty()

    def test_mount_target_acquisition_refine_sync_and_move_success(self):
        """Test MOUNT_TARGET_ACQUISITION_REFINE phase with successful sync and move."""
        self.mount_control.state = MountControlPhases.MOUNT_TARGET_ACQUISITION_REFINE

        # Set target and solution to be outside tolerance (> 0.01 degrees)
        self.mount_control.target_ra = 15.5
        self.mount_control.target_dec = 45.2
        self.mock_solution["RA_target"] = 15.52  # Outside tolerance
        self.mock_solution["Dec_target"] = 45.22  # Outside tolerance

        # Execute the phase
        self._execute_phase_generator()

        # Verify sync_mount was called with solution coordinates
        self.mount_control.sync_mount.assert_called_with(15.52, 45.22)

        # Verify move_mount_to_target was called with target coordinates
        self.mount_control.move_mount_to_target.assert_called_with(15.5, 45.2)

        # Verify state transition to MOUNT_TARGET_ACQUISITION_MOVE
        assert (
            self.mount_control.state == MountControlPhases.MOUNT_TARGET_ACQUISITION_MOVE
        )

        # Verify no warning messages
        assert self.console_queue.empty()

    def test_mount_target_acquisition_refine_sync_failure(self):
        """Test MOUNT_TARGET_ACQUISITION_REFINE phase when sync fails."""
        self.mount_control.state = MountControlPhases.MOUNT_TARGET_ACQUISITION_REFINE

        # Set target and solution to be outside tolerance
        self.mount_control.target_ra = 15.5
        self.mount_control.target_dec = 45.2
        self.mock_solution["RA_target"] = 15.52
        self.mock_solution["Dec_target"] = 15.22

        # Mock sync_mount to fail
        self.mount_control.sync_mount.return_value = False

        # Execute the phase with sufficient retries and time
        self._execute_phase_generator(retry_count=2, delay=0.001, timeout=1.0)

        # Verify sync_mount was called at least once (exact count depends on timing)
        assert self.mount_control.sync_mount.call_count >= 1

        # Verify state transition to MOUNT_STOPPED after sync failure
        assert self.mount_control.state == MountControlPhases.MOUNT_STOPPED

        # Verify warning message was sent
        assert not self.console_queue.empty()
        warning_msg = self.console_queue.get()
        assert warning_msg[0] == "WARNING"

    def test_mount_target_acquisition_refine_move_failure(self):
        """Test MOUNT_TARGET_ACQUISITION_REFINE phase when move fails after successful sync."""
        self.mount_control.state = MountControlPhases.MOUNT_TARGET_ACQUISITION_REFINE

        # Set target and solution to be outside tolerance
        self.mount_control.target_ra = 15.5
        self.mount_control.target_dec = 45.2
        self.mock_solution["RA_target"] = 15.52
        self.mock_solution["Dec_target"] = 45.22

        # Mock move_mount_to_target to fail
        self.mount_control.move_mount_to_target.return_value = False

        # Execute the phase with sufficient time
        self._execute_phase_generator(retry_count=1, delay=0.001, timeout=1.0)

        # Verify sync_mount was called successfully
        self.mount_control.sync_mount.assert_called_once()

        # Verify move_mount_to_target was called at least once
        assert self.mount_control.move_mount_to_target.call_count >= 1

        # Verify state transition to MOUNT_TRACKING after move failure
        assert self.mount_control.state == MountControlPhases.MOUNT_TRACKING

        # Verify warning message was sent
        assert not self.console_queue.empty()
        warning_msg = self.console_queue.get()
        assert warning_msg[0] == "WARNING"

    def test_mount_drift_compensation_with_good_fit(self):
        """Test MOUNT_DRIFT_COMPENSATION phase with mocked solves that produce good R² fit."""
        self.mount_control.state = MountControlPhases.MOUNT_DRIFT_COMPENSATION

        # Create mock solution data that changes linearly over time
        # Simulating drift: RA increases by 0.001 deg/s, Dec increases by 0.0005 deg/s
        base_ra = 15.5
        base_dec = 45.2
        ra_drift_rate = 0.001  # degrees per second
        dec_drift_rate = 0.0005  # degrees per second
        base_time = 1000.0  # Arbitrary base timestamp

        # Pre-generate 13 solve samples spanning 12 seconds
        mock_solves = []
        for i in range(13):  # 0 to 12 seconds
            elapsed = i
            mock_solves.append({
                "solve_time": base_time + elapsed,
                "RA_target": base_ra + ra_drift_rate * elapsed,
                "Dec_target": base_dec + dec_drift_rate * elapsed,
            })

        solve_index = [0]

        def mock_solution_sequential():
            """Return pre-generated solutions sequentially."""
            if solve_index[0] < len(mock_solves):
                result = mock_solves[solve_index[0]]
                solve_index[0] += 1
                return result
            # Return last solution if we run out
            return mock_solves[-1]

        self.shared_state.solution.side_effect = mock_solution_sequential

        # Execute phase generator for each solve
        phase_generator = None
        for i in range(len(mock_solves)):
            # Simulate the main loop: create new generator if needed
            if phase_generator is None:
                phase_generator = self.mount_control._process_phase(retry_count=3, delay=0.01)

            try:
                next(phase_generator)
            except StopIteration:
                # Generator finished, will create new one on next iteration
                phase_generator = None

        # Verify that adjust_mount_drift_rates was called with detected drift
        assert self.mount_control.adjust_mount_drift_rates.called, \
            "adjust_mount_drift_rates should have been called"

        # Get the drift rate adjustments that were passed (absolute slopes detected)
        call_args = self.mount_control.adjust_mount_drift_rates.call_args
        assert call_args is not None, "adjust_mount_drift_rates should have been called with arguments"

        ra_adjustment, dec_adjustment = call_args[0]

        # Verify the adjustments are close to expected drift rates (within 20% tolerance due to discrete sampling)
        assert abs(ra_adjustment - ra_drift_rate) < ra_drift_rate * 0.2, \
            f"RA drift rate adjustment {ra_adjustment} should be close to expected {ra_drift_rate}"
        assert abs(dec_adjustment - dec_drift_rate) < dec_drift_rate * 0.2, \
            f"Dec drift rate adjustment {dec_adjustment} should be close to expected {dec_drift_rate}"

    def test_mount_drift_compensation_with_poor_fit(self):
        """Test MOUNT_DRIFT_COMPENSATION phase with noisy data that produces poor R² fit."""
        import random
        self.mount_control.state = MountControlPhases.MOUNT_DRIFT_COMPENSATION

        # Create mock solution data with random noise (poor fit)
        base_ra = 15.5
        base_dec = 45.2
        base_time = 1000.0

        # Pre-generate 13 solve samples with random noise
        mock_solves = []
        for i in range(13):
            mock_solves.append({
                "solve_time": base_time + i,
                "RA_target": base_ra + random.uniform(-0.1, 0.1),
                "Dec_target": base_dec + random.uniform(-0.1, 0.1),
            })

        solve_index = [0]

        def mock_solution_with_noise():
            """Return solutions with significant random noise."""
            if solve_index[0] < len(mock_solves):
                result = mock_solves[solve_index[0]]
                solve_index[0] += 1
                return result
            return mock_solves[-1]

        self.shared_state.solution.side_effect = mock_solution_with_noise

        # Execute phase generator for each solve
        phase_generator = None
        for i in range(len(mock_solves)):
            if phase_generator is None:
                phase_generator = self.mount_control._process_phase(retry_count=3, delay=0.01)

            try:
                next(phase_generator)
            except StopIteration:
                phase_generator = None

        # Verify that adjust_mount_drift_rates was NOT called (due to poor R²)
        assert not self.mount_control.adjust_mount_drift_rates.called, \
            "adjust_mount_drift_rates should NOT have been called with poor R² fit"

        # Verify no INFO console message (only logger messages)
        # There might be WARNING messages, but no INFO about drift rates adjusted
        while not self.console_queue.empty():
            msg = self.console_queue.get()
            assert msg[0] != "INFO" or "Drift rates adjusted" not in str(msg), \
                "Should not send INFO message about drift rates with poor fit"

    def test_mount_spiral_search_unimplemented(self):
        """Test MOUNT_SPIRAL_SEARCH phase that is not yet implemented."""
        self.mount_control.state = MountControlPhases.MOUNT_SPIRAL_SEARCH

        # Execute the phase
        self._execute_phase_generator()

        # Verify no abstract methods were called
        self.mount_control.init_mount.assert_not_called()
        self.mount_control.sync_mount.assert_not_called()
        self.mount_control.move_mount_to_target.assert_not_called()

        # Verify state unchanged
        assert self.mount_control.state == MountControlPhases.MOUNT_SPIRAL_SEARCH

        # Verify no console messages
        assert self.console_queue.empty()

    def test_phase_state_change_during_processing(self):
        """Test behavior when state changes during phase processing."""
        self.mount_control.state = MountControlPhases.MOUNT_TARGET_ACQUISITION_REFINE

        # Set up for refine phase that would normally succeed
        self.mount_control.target_ra = 15.5
        self.mount_control.target_dec = 45.2
        self.mock_solution["RA_target"] = 15.52
        self.mock_solution["Dec_target"] = 45.22

        # Change state during processing to simulate external state change
        def sync_side_effect(*args):
            # Change state during sync operation to test state change handling
            self.mount_control.state = MountControlPhases.MOUNT_STOPPED
            return True

        self.mount_control.sync_mount.side_effect = sync_side_effect

        # Execute the phase
        self._execute_phase_generator()

        # Verify sync was called
        assert self.mount_control.sync_mount.call_count >= 1
        assert self.mount_control.move_mount_to_target.call_count >= 1

        # The state machine should respect the state change and exit appropriately
        # The actual final state may vary depending on timing and state machine logic
        # The key point is that the phase processing should handle state changes gracefully
        assert self.mount_control.state in [
            MountControlPhases.MOUNT_STOPPED,
            MountControlPhases.MOUNT_TARGET_ACQUISITION_MOVE,
        ]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
