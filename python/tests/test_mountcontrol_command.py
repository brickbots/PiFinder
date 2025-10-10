#!/usr/bin/env python3

import pytest
from queue import Queue
import time
from unittest.mock import Mock, patch

# Import the classes we want to test
from PiFinder.mountcontrol_interface import (
    MountControlPhases,
    MountDirectionsEquatorial,
    MountControlBase,
)
from PiFinder.state import SharedStateObj


class TestMountControl:
    """
    Test harness for MountControlBase._process_command method.

    This test harness creates a mock environment with:
    - Initialized queues for target, console, and logging
    - Mocked shared state object
    - Overridden abstract methods to track calls
    - Test cases for each command type and branch in _process_command
    """

    def setup_method(self):
        """Setup test environment before each test."""
        # Create mock queues
        self.target_queue = Queue()
        self.console_queue = Queue()

        # Create mock shared state
        self.shared_state = Mock(spec=SharedStateObj)

        # Create the mount control instance with mocked INDI client
        with patch(
            "PiFinder.mountcontrol_interface.MountControlBase"
        ) as mock_client_class:
            mock_client = Mock()
            mock_client.setServer.return_value = None
            mock_client.connectServer.return_value = True
            mock_client_class.return_value = mock_client

            self.mount_control = MountControlBase(
                self.target_queue, self.console_queue, self.shared_state
            )
            self.mock_client = mock_client

        # Override abstract methods to track calls
        self.mount_control.init_mount = Mock(return_value=True)
        self.mount_control.sync_mount = Mock(return_value=True)
        self.mount_control.stop_mount = Mock(return_value=True)
        self.mount_control.move_mount_to_target = Mock(return_value=True)
        self.mount_control.set_mount_drift_rates = Mock(return_value=True)
        self.mount_control.move_mount_manual = Mock(return_value=True)
        self.mount_control.set_mount_step_size = Mock(return_value=True)
        self.mount_control.disconnect_mount = Mock(return_value=True)

    def _execute_command_generator(self, command):
        """Helper to execute a command generator fully."""
        command_generator = self.mount_control._process_command(command)
        if command_generator is not None:
            try:
                while True:
                    next(command_generator)
            except StopIteration:
                pass

    def test_exit_command(self):
        """Test the 'exit' command type."""
        # Setup initial state - use TRACKING so stop_mount gets called
        self.mount_control.state = MountControlPhases.MOUNT_TRACKING

        # Create exit command
        command = {"type": "exit"}

        # Execute the command
        system_exit_thrown = False
        try:
            self._execute_command_generator(command)
        except SystemExit:
            system_exit_thrown = True

        assert system_exit_thrown, "SystemExit was not raised on exit command"

        # Verify that stop_mount was called (since we started from TRACKING state)
        self.mount_control.stop_mount.assert_called_once()

        # Verify no messages were sent to console queue for successful exit
        assert self.console_queue.empty()

    def test_stop_movement_success(self):
        """Test successful 'stop_movement' command."""
        # Setup initial state
        self.mount_control.state = MountControlPhases.MOUNT_TARGET_ACQUISITION_MOVE

        # Create stop command
        command = {"type": "stop_movement"}

        # Execute the command
        self._execute_command_generator(command)

        # Verify that stop_mount was called
        self.mount_control.stop_mount.assert_called_once()

        # Verify no warning messages were sent to console
        assert self.console_queue.empty()

    def test_stop_movement_success_with_retry(self):
        """Test 'stop_movement' command with initial failure and successful retry."""
        # Setup initial state
        self.mount_control.state = MountControlPhases.MOUNT_TARGET_ACQUISITION_MOVE

        # Mock stop_mount to fail first time, succeed second time
        self.mount_control.stop_mount.side_effect = [False, True]

        # Create stop command
        command = {"type": "stop_movement"}

        # Execute with shorter delay for faster testing
        command_generator = self.mount_control._process_command(
            command, retry_count=2, delay=0.1
        )

        # Execute the generator, simulating time passage
        start_time = time.time()
        try:
            while True:
                next(command_generator)
                # Simulate time passage to avoid infinite waiting
                if time.time() - start_time > 0.5:
                    assert False, "Test timed out"
        except StopIteration:
            pass

        # Verify that _stop_mount was called twice (initial + 1 retry)
        assert self.mount_control.stop_mount.call_count == 2

        # Verify no warning messages since it eventually succeeded
        assert self.console_queue.empty()

    def test_stop_movement_failure_after_retry(self):
        """Test 'stop_movement' command that fails all retries."""
        # Setup initial state
        self.mount_control.state = MountControlPhases.MOUNT_TARGET_ACQUISITION_MOVE

        # Mock _stop_mount to always fail
        self.mount_control.stop_mount.return_value = False

        # Create stop command
        command = {"type": "stop_movement"}

        # Execute with 1 retry and very short delay for faster testing
        command_generator = self.mount_control._process_command(
            command, retry_count=2, delay=0.01
        )

        # Execute the generator
        start_time = time.time()
        try:
            while True:
                next(command_generator)
                # Simulate time passage
                if time.time() - start_time > 0.1:
                    assert False, "Test timed out"
        except StopIteration:
            pass

        # Verify that stop_mount was called the retry count + 1 times
        assert self.mount_control.stop_mount.call_count == 2  # initial + 1 retry

        # Verify warning message was sent to console
        assert not self.console_queue.empty()
        warning_msg = self.console_queue.get()
        assert warning_msg[0] == "WARNING"

        # Verify state was set to MOUNT_INIT_TELESCOPE on total failure
        assert self.mount_control.state == MountControlPhases.MOUNT_INIT_TELESCOPE

    def test_sync_success(self):
        """Test successful 'sync' command."""
        # Setup initial state
        self.mount_control.state = MountControlPhases.MOUNT_STOPPED

        # Create sync command
        command = {"type": "sync", "ra": 10.5, "dec": -20.3}

        # Execute the command
        self._execute_command_generator(command)

        # Verify that sync_mount was called with correct parameters
        self.mount_control.sync_mount.assert_called_once_with(10.5, -20.3)

        # Verify no warning messages
        assert self.console_queue.empty()

    def test_gototarget_success(self):
        """Test successful 'goto_target' command."""
        # Setup initial state
        self.mount_control.state = MountControlPhases.MOUNT_STOPPED

        # Create goto command
        command = {
            "type": "goto_target",
            "ra": 15.5,  # Right Ascension in degrees
            "dec": 45.2,  # Declination in degrees
        }

        # Execute the command
        self._execute_command_generator(command)

        # Verify that goto_target was called with correct parameters
        self.mount_control.move_mount_to_target.assert_called_once_with(15.5, 45.2)

        # Verify no warning messages
        assert self.console_queue.empty()

    def test_gototarget_failure(self):
        """Test 'goto_target' command that fails all retries."""
        # Setup initial state
        self.mount_control.state = MountControlPhases.MOUNT_STOPPED

        # Mock _goto_target to always fail
        self.mount_control.move_mount_to_target.return_value = False

        # Create goto command
        command = {"type": "goto_target", "ra": 15.5, "dec": 45.2}

        # Execute with 1 retry and short delay
        command_generator = self.mount_control._process_command(
            command, retry_count=1, delay=0.01
        )

        start_time = time.time()
        try:
            while True:
                next(command_generator)
                if time.time() - start_time > 0.1:
                    break
        except StopIteration:
            pass

        # Verify warning message was sent
        assert not self.console_queue.empty()
        warning_msg = self.console_queue.get()
        assert warning_msg[0] == "WARNING"

    @pytest.mark.parametrize(
        "initial_state",
        [
            MountControlPhases.MOUNT_STOPPED,
            MountControlPhases.MOUNT_TRACKING,
            MountControlPhases.MOUNT_TARGET_ACQUISITION_MOVE,
            MountControlPhases.MOUNT_TARGET_ACQUISITION_REFINE,
            MountControlPhases.MOUNT_DRIFT_COMPENSATION,
        ],
    )
    def test_gototarget_success_after_retry(self, initial_state):
        """Test 'goto_target' command that fails all retries."""
        # Setup initial state
        self.mount_control.state = initial_state

        # Mock _goto_target to always fail
        self.mount_control.move_mount_to_target.side_effect = [False, True]

        # Create goto command
        command = {"type": "goto_target", "ra": 15.5, "dec": 45.2}

        # Execute with 1 retry and short delay
        command_generator = self.mount_control._process_command(
            command, retry_count=3, delay=0.01
        )

        start_time = time.time()
        try:
            while True:
                next(command_generator)
                if time.time() - start_time > 0.1:
                    assert False, "Test timed out"
        except StopIteration:
            pass

        assert (
            self.mount_control.move_mount_to_target.call_count == 2
        ), "Expected two calls to move_mount_to_target"
        assert (
            self.mount_control.state == MountControlPhases.MOUNT_TARGET_ACQUISITION_MOVE
        ), "Mount state should be TARGET_ACQUISITION_MOVE after successful goto"

        # Verify warning message
        assert (
            self.console_queue.empty()
        ), "No warning should be sent if eventually successful"

    @pytest.mark.parametrize(
        "initial_state",
        [
            MountControlPhases.MOUNT_STOPPED,
            MountControlPhases.MOUNT_TRACKING,
            MountControlPhases.MOUNT_TARGET_ACQUISITION_MOVE,
            MountControlPhases.MOUNT_TARGET_ACQUISITION_REFINE,
            MountControlPhases.MOUNT_DRIFT_COMPENSATION,
        ],
    )
    def test_gototarget_failure_after_retries(self, initial_state):
        """Test 'goto_target' command that fails all retries from different initial states."""
        # Setup initial state
        self.mount_control.state = initial_state

        # Mock _goto_target to always fail
        self.mount_control.move_mount_to_target.return_value = False

        # Create goto command
        command = {"type": "goto_target", "ra": 15.5, "dec": 45.2}

        # Execute with 2 retries and short delay
        command_generator = self.mount_control._process_command(
            command, retry_count=3, delay=0.01
        )

        start_time = time.time()
        try:
            while True:
                next(command_generator)
                if time.time() - start_time > 0.1:
                    assert False, "Test timed out"
        except StopIteration:
            pass

        # Verify that move_mount_to_target was called 3 times (initial + 2 retries)
        assert self.mount_control.move_mount_to_target.call_count == 3
        # Stop mount should be called once after failure (unless already stopped)
        if initial_state == MountControlPhases.MOUNT_STOPPED:
            # _stop_mount returns True without calling stop_mount if already stopped
            assert self.mount_control.stop_mount.call_count == 0
        else:
            assert self.mount_control.stop_mount.call_count == 1
        # State should remain as initial state
        assert self.mount_control.state == initial_state

        # Verify warning message was sent to console
        assert not self.console_queue.empty()
        warning_msg = self.console_queue.get()
        assert warning_msg[0] == "WARNING"

    @pytest.mark.parametrize(
        "initial_state",
        [
            MountControlPhases.MOUNT_STOPPED,
            MountControlPhases.MOUNT_TRACKING,
            MountControlPhases.MOUNT_TARGET_ACQUISITION_MOVE,
            MountControlPhases.MOUNT_TARGET_ACQUISITION_REFINE,
            MountControlPhases.MOUNT_DRIFT_COMPENSATION,
        ],
    )
    def test_gototarget_full_failure_after_retries(self, initial_state):
        """Test 'goto_target' command that fails all retries and stop also fails multiple times."""
        # Setup initial state
        self.mount_control.state = initial_state

        # Mock _goto_target to always fail as does stop_mount
        self.mount_control.move_mount_to_target.return_value = False
        self.mount_control.stop_mount.return_value = False

        # Create goto command
        command = {"type": "goto_target", "ra": 15.5, "dec": 45.2}

        # Execute with 2 retries and short delay
        command_generator = self.mount_control._process_command(
            command, retry_count=2, delay=0.01
        )

        start_time = time.time()
        try:
            while True:
                next(command_generator)
                if time.time() - start_time > 0.1:
                    assert False, "Test timed out"
        except StopIteration:
            pass

        # Verify that move_mount_to_target was called 2 times (initial + 1 retry)
        assert self.mount_control.move_mount_to_target.call_count == 2
        # Stop mount should be called after failure (unless already stopped)
        if initial_state == MountControlPhases.MOUNT_STOPPED:
            # _stop_mount returns True without calling stop_mount if already stopped
            assert self.mount_control.stop_mount.call_count == 0
        else:
            # Stop mount should be called once (nested generator doesn't fully execute due to yield/while pattern)
            assert self.mount_control.stop_mount.call_count == 1
        # State should remain as initial_state when stop doesn't fully execute
        assert self.mount_control.state == initial_state

        # Verify warning message was sent to console
        assert not self.console_queue.empty()
        warning_msg = self.console_queue.get()
        assert warning_msg[0] == "WARNING"

    def test_manual_movement_command_success(self):
        """Test successful 'manual_movement' command."""
        # Setup initial state
        self.mount_control.state = MountControlPhases.MOUNT_STOPPED
        self.mount_control.step_size = 1.0  # 1 degree step size

        # Create manual movement command
        command = {
            "type": "manual_movement",
            "direction": "north",
            "slew_rate": "SLEW_GUIDE",
            "duration": 1.0,
        }

        # Execute the command
        self._execute_command_generator(command)

        # Verify that _move_mount_manual was called with correct parameters
        self.mount_control.move_mount_manual.assert_called_once_with(
            MountDirectionsEquatorial.NORTH, "SLEW_GUIDE", 1.0
        )

        # Verify no warning messages
        assert self.console_queue.empty()

    def test_manual_movement_command_failure(self):
        """Test 'manual_movement' command that fails."""
        # Setup initial state
        self.mount_control.state = MountControlPhases.MOUNT_STOPPED

        # Mock move_mount_manual to fail
        self.mount_control.move_mount_manual.return_value = False

        # Create manual movement command
        command = {
            "type": "manual_movement",
            "direction": MountDirectionsEquatorial.SOUTH,
            "slew_rate": "SLEW_GUIDE",
            "duration": 1.0,
        }

        # Execute the command
        self._execute_command_generator(command)

        # Verify warning message was sent
        assert not self.console_queue.empty()
        warning_msg = self.console_queue.get()
        assert warning_msg[0] == "WARNING"

    def test_reduce_step_size_command(self):
        """Test 'reduce_step_size' command."""
        # Setup initial step size
        initial_step_size = 1.0
        self.mount_control.step_size = initial_step_size

        # Create reduce step size command
        command = {"type": "reduce_step_size"}

        # Execute the command
        self._execute_command_generator(command)

        # Verify step size was halved
        expected_step_size = initial_step_size / 2
        assert self.mount_control.step_size == expected_step_size

        # Test minimum limit
        self.mount_control.step_size = 1 / 3600  # 1 arcsec
        self._execute_command_generator(command)

        # Verify it doesn't go below minimum
        assert self.mount_control.step_size == 1 / 3600

    def test_increase_step_size_command(self):
        """Test 'increase_step_size' command."""
        # Setup initial step size
        initial_step_size = 1.0
        self.mount_control.step_size = initial_step_size

        # Create increase step size command
        command = {"type": "increase_step_size"}

        # Execute the command
        self._execute_command_generator(command)

        # Verify step size was doubled
        expected_step_size = initial_step_size * 2
        assert self.mount_control.step_size == expected_step_size

        # Test maximum limit
        self.mount_control.step_size = 10.0  # Maximum
        self._execute_command_generator(command)

        # Verify it doesn't go above maximum
        assert self.mount_control.step_size == 10.0

    def test_set_step_size_command_success(self):
        """Test successful 'set_step_size' command with valid values."""
        # Test setting a valid step size
        command = {"type": "set_step_size", "step_size": 2.5}

        # Execute the command
        self._execute_command_generator(command)

        # Verify that set_mount_step_size was called with correct value
        self.mount_control.set_mount_step_size.assert_called_once_with(2.5)

        # Verify step size was updated
        assert self.mount_control.step_size == 2.5

        # Verify no warning messages
        assert self.console_queue.empty()

    def test_set_step_size_command_boundary_values(self):
        """Test 'set_step_size' command with boundary values."""
        # Test minimum valid value (1 arcsec = 1/3600 degrees)
        min_step_size = 1 / 3600
        command = {"type": "set_step_size", "step_size": min_step_size}

        self._execute_command_generator(command)
        self.mount_control.set_mount_step_size.assert_called_with(min_step_size)
        assert self.mount_control.step_size == min_step_size
        assert self.console_queue.empty()

        # Reset mock
        self.mount_control.set_mount_step_size.reset_mock()

        # Test maximum valid value (10 degrees)
        max_step_size = 10.0
        command = {"type": "set_step_size", "step_size": max_step_size}

        self._execute_command_generator(command)
        self.mount_control.set_mount_step_size.assert_called_with(max_step_size)
        assert self.mount_control.step_size == max_step_size
        assert self.console_queue.empty()

    def test_set_step_size_command_too_small(self):
        """Test 'set_step_size' command with value below minimum."""
        # Store original step size
        original_step_size = self.mount_control.step_size

        # Test value below minimum (less than 1 arcsec)
        command = {
            "type": "set_step_size",
            "step_size": 1 / 7200,  # 0.5 arcsec
        }

        self._execute_command_generator(command)

        # Verify that set_mount_step_size was NOT called
        self.mount_control.set_mount_step_size.assert_not_called()

        # Verify step size was not changed
        assert self.mount_control.step_size == original_step_size

        # Verify warning message was sent
        assert not self.console_queue.empty()
        warning_msg = self.console_queue.get()
        assert warning_msg[0] == "WARNING"
        assert "Step size must be between 1 arcsec and 10 degrees" in warning_msg[1]

    def test_set_step_size_command_too_large(self):
        """Test 'set_step_size' command with value above maximum."""
        # Store original step size
        original_step_size = self.mount_control.step_size

        # Test value above maximum (more than 10 degrees)
        command = {"type": "set_step_size", "step_size": 15.0}

        self._execute_command_generator(command)

        # Verify that set_mount_step_size was NOT called
        self.mount_control.set_mount_step_size.assert_not_called()

        # Verify step size was not changed
        assert self.mount_control.step_size == original_step_size

        # Verify warning message was sent
        assert not self.console_queue.empty()
        warning_msg = self.console_queue.get()
        assert warning_msg[0] == "WARNING"
        assert "Step size must be between 1 arcsec and 10 degrees" in warning_msg[1]

    def test_set_step_size_command_mount_failure(self):
        """Test 'set_step_size' command when mount fails to set step size."""
        # Store original step size
        original_step_size = self.mount_control.step_size

        # Mock set_mount_step_size to fail
        self.mount_control.set_mount_step_size.return_value = False

        command = {"type": "set_step_size", "step_size": 3.0}

        self._execute_command_generator(command)

        # Verify that set_mount_step_size was called
        self.mount_control.set_mount_step_size.assert_called_once_with(3.0)

        # Verify step size was NOT updated due to failure
        assert self.mount_control.step_size == original_step_size

        # Verify warning message was sent
        assert not self.console_queue.empty()
        warning_msg = self.console_queue.get()
        assert warning_msg[0] == "WARNING"
        assert "Cannot set step size" in warning_msg[1]

    @pytest.mark.parametrize(
        "step_size,expected_valid",
        [
            (1 / 3600, True),  # Minimum valid (1 arcsec)
            (0.001, True),  # Valid small value
            (1.0, True),  # Valid medium value
            (5.0, True),  # Valid large value
            (10.0, True),  # Maximum valid
            (1 / 7200, False),  # Too small (0.5 arcsec)
            (0.0, False),  # Zero
            (-1.0, False),  # Negative
            (15.0, False),  # Too large
            (100.0, False),  # Way too large
        ],
    )
    def test_set_step_size_command_validation(self, step_size, expected_valid):
        """Test 'set_step_size' command validation with various values."""
        # Store original step size
        original_step_size = self.mount_control.step_size

        command = {"type": "set_step_size", "step_size": step_size}

        self._execute_command_generator(command)

        if expected_valid:
            # Valid values should call set_mount_step_size and update step_size
            self.mount_control.set_mount_step_size.assert_called_once_with(step_size)
            assert self.mount_control.step_size == step_size
            assert self.console_queue.empty()
        else:
            # Invalid values should not call set_mount_step_size or update step_size
            self.mount_control.set_mount_step_size.assert_not_called()
            assert self.mount_control.step_size == original_step_size

            # Should send warning message
            assert not self.console_queue.empty()
            warning_msg = self.console_queue.get()
            assert warning_msg[0] == "WARNING"

        # Reset mock for next iteration
        self.mount_control.set_mount_step_size.reset_mock()

    def test_spiral_search_command_not_implemented(self):
        """Test 'spiral_search' command raises NotImplementedError."""
        # Create spiral search command
        command = {"type": "spiral_search"}

        # Verify that NotImplementedError is raised
        with pytest.raises(NotImplementedError):
            self._execute_command_generator(command)

    def test_unknown_command_type(self):
        """Test handling of unknown command types."""
        # Create unknown command
        command = {"type": "unknown_command"}

        # Execute the command - should do nothing without error
        self._execute_command_generator(command)

        # Verify no abstract methods were called and no messages sent
        self.mount_control.init_mount.assert_not_called()
        self.mount_control.sync_mount.assert_not_called()
        self.mount_control.stop_mount.assert_not_called()
        self.mount_control.move_mount_to_target.assert_not_called()
        self.mount_control.set_mount_drift_rates.assert_not_called()
        self.mount_control.move_mount_manual.assert_not_called()
        self.mount_control.set_mount_step_size.assert_not_called()
        self.mount_control.disconnect_mount.assert_not_called()

        assert self.console_queue.empty()
