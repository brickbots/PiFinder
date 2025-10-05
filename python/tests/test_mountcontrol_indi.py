#!/usr/bin/env python3

import pytest
import unittest.mock as mock
from queue import Queue
import time
from unittest.mock import Mock, MagicMock, patch, call
import sys

# Check if PyIndi is available for integration tests
try:
    import PyIndi
    PYINDI_AVAILABLE = True
except ImportError:
    PYINDI_AVAILABLE = False

# Import the classes we want to test
from PiFinder.mountcontrol_indi import MountControlIndi, PiFinderIndiClient
from PiFinder.mountcontrol_interface import MountControlPhases, MountDirectionsEquatorial
from PiFinder.state import SharedStateObj


class TestMountControlIndiUnit:
    """Unit tests for MountControlIndi with mocked PyIndi."""

    def setup_method(self):
        """Setup test environment before each test."""
        # Create mock queues
        self.mount_queue = Queue()
        self.console_queue = Queue()
        self.log_queue = Queue()

        # Create mock shared state
        self.shared_state = Mock(spec=SharedStateObj)

        # Mock PyIndi module
        self.mock_pyindi = MagicMock()
        self.mock_base_client = MagicMock()
        self.mock_pyindi.BaseClient = self.mock_base_client
        self.mock_pyindi.ISS_ON = 1
        self.mock_pyindi.ISS_OFF = 0

        # Create mock INDI client
        self.mock_indi_client = MagicMock()
        self.mock_indi_client.connectServer.return_value = True
        self.mock_indi_client.telescope_device = None

        # Create mock telescope device
        self.mock_telescope = MagicMock()
        self.mock_telescope.getDeviceName.return_value = "Telescope Simulator"

        with patch('PiFinder.mountcontrol_indi.PyIndi', self.mock_pyindi):
            with patch('PiFinder.mountcontrol_indi.PiFinderIndiClient') as mock_client_class:
                mock_client_class.return_value = self.mock_indi_client
                self.mount_control = MountControlIndi(
                    self.mount_queue,
                    self.console_queue,
                    self.shared_state,
                    self.log_queue
                )

    def test_init_mount_success(self):
        """Test successful mount initialization."""
        # Setup mock client to simulate successful connection
        self.mock_indi_client.telescope_device = self.mock_telescope

        # Mock CONNECTION property
        mock_connect_prop = MagicMock()
        mock_connect_switch = MagicMock()
        mock_connect_switch.name = "CONNECT"
        mock_connect_switch.s = 0  # Not connected
        mock_connect_prop.nsp = 1
        mock_connect_prop.sp = [mock_connect_switch]
        self.mock_telescope.getProperty.return_value = mock_connect_prop

        # Execute init_mount
        result = self.mount_control.init_mount()

        # Verify connection was attempted
        self.mock_indi_client.connectServer.assert_called_once()
        assert result is True
        assert self.mount_control._connected is True

    def test_init_mount_connection_failure(self):
        """Test mount initialization when server connection fails."""
        # Setup mock client to fail connection
        self.mock_indi_client.connectServer.return_value = False

        # Execute init_mount
        result = self.mount_control.init_mount()

        # Verify failure
        assert result is False
        assert self.mount_control._connected is False

    def test_init_mount_no_telescope_device(self):
        """Test mount initialization when no telescope device is found."""
        # Setup mock client with no telescope device
        self.mock_indi_client.telescope_device = None

        # Execute init_mount
        result = self.mount_control.init_mount()

        # Verify failure
        assert result is False

    def test_sync_mount_success(self):
        """Test successful mount sync."""
        # Setup
        self.mock_indi_client.telescope_device = self.mock_telescope
        self.mount_control._connected = True

        # Mock properties - need to support both getProperty and getSwitch/getNumber
        mock_coord_set_prop = MagicMock()
        mock_sync_switch = MagicMock()
        mock_sync_switch.name = "SYNC"
        mock_coord_set_prop.__len__ = MagicMock(return_value=1)
        mock_coord_set_prop.__getitem__ = MagicMock(return_value=mock_sync_switch)

        mock_coord_prop = MagicMock()
        mock_ra_num = MagicMock()
        mock_ra_num.name = "RA"
        mock_dec_num = MagicMock()
        mock_dec_num.name = "DEC"
        mock_coord_prop.__len__ = MagicMock(return_value=2)
        mock_coord_prop.__getitem__ = MagicMock(side_effect=[mock_ra_num, mock_dec_num])

        self.mock_telescope.getProperty.return_value = True  # Property exists
        self.mock_telescope.getSwitch.return_value = mock_coord_set_prop
        self.mock_telescope.getNumber.return_value = mock_coord_prop

        # Execute sync
        result = self.mount_control.sync_mount(45.0, 30.0)

        # Verify
        assert result is True
        self.mock_indi_client.sendNewSwitch.assert_called()
        self.mock_indi_client.sendNewNumber.assert_called()
        # RA should be converted from degrees to hours (45.0 / 15.0 = 3.0)
        assert mock_ra_num.value == 3.0
        assert mock_dec_num.value == 30.0

    def test_sync_mount_no_device(self):
        """Test sync when no telescope device available."""
        self.mock_indi_client.telescope_device = None

        result = self.mount_control.sync_mount(45.0, 30.0)

        assert result is False

    def test_stop_mount_success(self):
        """Test successful mount stop."""
        # Setup
        self.mock_indi_client.telescope_device = self.mock_telescope

        # Mock ABORT property
        mock_abort_prop = MagicMock()
        mock_abort_switch = MagicMock()
        mock_abort_switch.name = "ABORT"
        mock_abort_prop.nsp = 1
        mock_abort_prop.sp = [mock_abort_switch]
        self.mock_telescope.getProperty.return_value = mock_abort_prop

        # Execute stop
        result = self.mount_control.stop_mount()

        # Verify
        assert result is True
        self.mock_indi_client.sendNewSwitch.assert_called_once()
        assert self.mount_control.state == MountControlPhases.MOUNT_STOPPED

    def test_stop_mount_no_device(self):
        """Test stop when no telescope device available."""
        self.mock_indi_client.telescope_device = None

        result = self.mount_control.stop_mount()

        assert result is False

    def test_move_mount_to_target_success(self):
        """Test successful goto command."""
        # Setup
        self.mock_indi_client.telescope_device = self.mock_telescope

        # Mock properties - need to support both getProperty and getSwitch/getNumber
        mock_coord_set_prop = MagicMock()
        mock_track_switch = MagicMock()
        mock_track_switch.name = "TRACK"
        mock_coord_set_prop.__len__ = MagicMock(return_value=1)
        mock_coord_set_prop.__getitem__ = MagicMock(return_value=mock_track_switch)

        mock_coord_prop = MagicMock()
        mock_ra_num = MagicMock()
        mock_ra_num.name = "RA"
        mock_dec_num = MagicMock()
        mock_dec_num.name = "DEC"
        mock_coord_prop.__len__ = MagicMock(return_value=2)
        mock_coord_prop.__getitem__ = MagicMock(side_effect=[mock_ra_num, mock_dec_num])

        self.mock_telescope.getProperty.return_value = True  # Property exists
        self.mock_telescope.getSwitch.return_value = mock_coord_set_prop
        self.mock_telescope.getNumber.return_value = mock_coord_prop

        # Execute goto
        result = self.mount_control.move_mount_to_target(120.0, 45.0)

        # Verify
        assert result is True
        self.mock_indi_client.sendNewSwitch.assert_called()
        self.mock_indi_client.sendNewNumber.assert_called()
        # RA should be converted from degrees to hours (120.0 / 15.0 = 8.0)
        assert mock_ra_num.value == 8.0
        assert mock_dec_num.value == 45.0

    def test_move_mount_to_target_no_device(self):
        """Test goto when no telescope device available."""
        self.mock_indi_client.telescope_device = None

        result = self.mount_control.move_mount_to_target(120.0, 45.0)

        assert result is False

    def test_move_mount_manual_north(self):
        """Test manual movement in north direction."""
        # Setup
        self.mock_indi_client.telescope_device = self.mock_telescope

        # Mock motion property
        mock_motion_prop = MagicMock()
        mock_north_switch = MagicMock()
        mock_north_switch.name = "MOTION_NORTH"
        mock_south_switch = MagicMock()
        mock_south_switch.name = "MOTION_SOUTH"
        mock_motion_prop.nsp = 2
        mock_motion_prop.sp = [mock_north_switch, mock_south_switch]
        self.mock_telescope.getProperty.return_value = mock_motion_prop

        # Execute manual movement
        with patch('time.sleep'):  # Mock sleep to speed up test
            result = self.mount_control.move_mount_manual(MountDirectionsEquatorial.NORTH, 1.0)

        # Verify
        assert result is True
        assert self.mock_indi_client.sendNewSwitch.call_count >= 2  # Start and stop motion

    def test_move_mount_manual_no_device(self):
        """Test manual movement when no telescope device available."""
        self.mock_indi_client.telescope_device = None

        result = self.mount_control.move_mount_manual(MountDirectionsEquatorial.NORTH, 1.0)

        assert result is False

    def test_set_mount_step_size(self):
        """Test setting step size (always succeeds as it's managed by base class)."""
        result = self.mount_control.set_mount_step_size(2.5)

        assert result is True

    def test_disconnect_mount_success(self):
        """Test successful mount disconnection."""
        # Setup
        self.mock_indi_client.telescope_device = self.mock_telescope
        self.mount_control._connected = True

        # Mock DISCONNECT property
        mock_disconnect_prop = MagicMock()
        mock_disconnect_switch = MagicMock()
        mock_disconnect_switch.name = "DISCONNECT"
        mock_disconnect_prop.nsp = 1
        mock_disconnect_prop.sp = [mock_disconnect_switch]
        self.mock_telescope.getProperty.return_value = mock_disconnect_prop

        # Execute disconnect
        result = self.mount_control.disconnect_mount()

        # Verify
        assert result is True
        self.mock_indi_client.disconnectServer.assert_called_once()
        assert self.mount_control._connected is False

    def test_set_mount_drift_rates_not_implemented(self):
        """Test that drift rates return False (not implemented)."""
        result = self.mount_control.set_mount_drift_rates(0.1, 0.2)

        assert result is False


@pytest.mark.integration
@pytest.mark.skipif(not PYINDI_AVAILABLE, reason="PyIndi not available - integration tests require PyIndi installed")
class TestMountControlIndiIntegration:
    """Integration tests with real INDI Telescope Simulator.

    These tests require:
    1. PyIndi Python module installed (pip install pyindi-client)
    2. INDI server with Telescope Simulator running on localhost:7624
       Start with: indiserver -v indi_simulator_telescope
    """

    def setup_method(self):
        """Setup test environment before each test."""
        # Create real queues
        self.mount_queue = Queue()
        self.console_queue = Queue()
        self.log_queue = Queue()

        # Create mock shared state (still mocked as we don't need full state for these tests)
        self.shared_state = Mock(spec=SharedStateObj)
        self.mock_solution = Mock()
        self.mock_solution.RA_target = 45.0
        self.mock_solution.Dec_target = 30.0
        self.shared_state.solution.return_value = self.mock_solution
        self.shared_state.solve_state.return_value = True

        # Create mount control instance (will connect to real INDI server)
        self.mount_control = MountControlIndi(
            self.mount_queue,
            self.console_queue,
            self.shared_state,
            self.log_queue,
            indi_host="localhost",
            indi_port=7624
        )

    def teardown_method(self):
        """Cleanup after each test."""
        if hasattr(self, 'mount_control'):
            self.mount_control.disconnect_mount()

    def test_init_mount_real_indi(self):
        """Test initialization with real INDI server."""
        # Use test location: N51° 11m 0s E7° 5m 0s, elevation 250m
        import datetime
        result = self.mount_control.init_mount(
            latitude_deg=51.183333,  # 51° 11' 0"
            longitude_deg=7.083333,   # 7° 5' 0"
            elevation_m=250.0,
            utc_time=datetime.datetime.utcnow().isoformat()
        )

        assert result is True, "Failed to initialize mount with INDI server"
        assert self.mount_control._connected is True
        assert self.mount_control._get_telescope_device() is not None
        print(f"Connected to: {self.mount_control._get_telescope_device().getDeviceName()}")

    def test_sync_mount_real_indi(self):
        """Test sync with real INDI server."""
        # First initialize
        import datetime
        assert self.mount_control.init_mount(
            latitude_deg=51.183333,
            longitude_deg=7.083333,
            elevation_m=250.0,
            utc_time=datetime.datetime.utcnow().isoformat()
        ) is True

        # Give device time to fully initialize
        time.sleep(1.0)

        # Execute sync
        result = self.mount_control.sync_mount(45.0, 30.0)

        assert result is True, "Failed to sync mount"

        # Verify position was updated (may take a moment)
        time.sleep(0.5)
        # Current position should be updated via callback
        print(f"Mount position after sync: RA={self.mount_control.current_ra}, Dec={self.mount_control.current_dec}")

    def test_goto_mount_real_indi(self):
        """Test goto command with real INDI server."""
        # First initialize
        import datetime
        assert self.mount_control.init_mount(
            latitude_deg=51.183333,
            longitude_deg=7.083333,
            elevation_m=250.0,
            utc_time=datetime.datetime.utcnow().isoformat()
        ) is True
        time.sleep(1.0)

        # Sync to a known position first
        assert self.mount_control.sync_mount(0.0, 0.0) is True
        time.sleep(0.5)

        # Execute goto
        result = self.mount_control.move_mount_to_target(60.0, 45.0)

        assert result is True, "Failed to send goto command"

        # Wait a moment for mount to start moving
        time.sleep(1.0)

        # Verify position is updating
        print(f"Mount position during goto: RA={self.mount_control.current_ra}, Dec={self.mount_control.current_dec}")

    def test_stop_mount_real_indi(self):
        """Test stop command with real INDI server."""
        # First initialize
        import datetime
        assert self.mount_control.init_mount(
            latitude_deg=51.183333,
            longitude_deg=7.083333,
            elevation_m=250.0,
            utc_time=datetime.datetime.utcnow().isoformat()
        ) is True
        time.sleep(1.0)

        # Start a goto
        assert self.mount_control.move_mount_to_target(90.0, 45.0) is True
        time.sleep(0.5)

        # Stop the mount
        result = self.mount_control.stop_mount()

        assert result is True, "Failed to stop mount"
        assert self.mount_control.state == MountControlPhases.MOUNT_STOPPED

    def test_manual_movement_real_indi(self):
        """Test manual movement with real INDI server."""
        # First initialize
        import datetime
        assert self.mount_control.init_mount(
            latitude_deg=51.183333,
            longitude_deg=7.083333,
            elevation_m=250.0,
            utc_time=datetime.datetime.utcnow().isoformat()
        ) is True
        time.sleep(1.0)

        # Get initial position
        initial_ra = self.mount_control.current_ra
        initial_dec = self.mount_control.current_dec
        print(f"Initial position: RA={initial_ra}, Dec={initial_dec}")

        # Move north (should increase Dec)
        result = self.mount_control.move_mount_manual(MountDirectionsEquatorial.NORTH, 0.1)

        assert result is True, "Failed to execute manual movement"

        # Wait for movement to complete
        time.sleep(1.5)

        # Check position changed
        final_ra = self.mount_control.current_ra
        final_dec = self.mount_control.current_dec
        print(f"Final position: RA={final_ra}, Dec={final_dec}")

        # Dec should have increased (north movement)
        if initial_dec is not None and final_dec is not None:
            assert final_dec > initial_dec, "Dec should have increased after north movement"

    def test_disconnect_mount_real_indi(self):
        """Test disconnection from real INDI server."""
        # First initialize and connect
        import datetime
        assert self.mount_control.init_mount(
            latitude_deg=51.183333,
            longitude_deg=7.083333,
            elevation_m=250.0,
            utc_time=datetime.datetime.utcnow().isoformat()
        ) is True

        # Disconnect
        result = self.mount_control.disconnect_mount()

        assert result is True, "Failed to disconnect mount"
        assert self.mount_control._connected is False


if __name__ == "__main__":
    # Run unit tests
    print("Running unit tests...")
    pytest.main([__file__, "-v", "-m", "not integration"])

    print("\n" + "="*80)
    print("To run integration tests, ensure INDI Telescope Simulator is running:")
    print("  indiserver -v indi_simulator_telescope")
    print("Then run:")
    print("  pytest tests/test_mountcontrol_indi.py -v -m integration")
    print("="*80)
