#!/usr/bin/env python3

import pytest
from queue import Queue
import time
import datetime
from unittest.mock import Mock, MagicMock, patch

# Check if PyIndi is available for integration tests
try:
    # Ignoring unused import, we want to skip the integration tests, if PyIndi is not available below.
    import PyIndi  # noqa: F401

    PYINDI_AVAILABLE = True
except ImportError:
    PYINDI_AVAILABLE = False

# Import the classes we want to test
from PiFinder.mountcontrol_indi import MountControlIndi
from PiFinder.mountcontrol_interface import (
    MountControlPhases,
    MountDirectionsEquatorial,
)
from PiFinder.state import SharedStateObj


@pytest.mark.smoke
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
        self.mock_indi_client.isServerConnected.return_value = False
        self.mock_indi_client.telescope_device = None

        # Create mock telescope device
        self.mock_telescope = MagicMock()
        self.mock_telescope.getDeviceName.return_value = "Telescope Simulator"

        with patch("PiFinder.mountcontrol_indi.PyIndi", self.mock_pyindi):
            with patch(
                "PiFinder.mountcontrol_indi.PiFinderIndiClient"
            ) as mock_client_class:
                mock_client_class.return_value = self.mock_indi_client
                self.mount_control = MountControlIndi(
                    self.mount_queue,
                    self.console_queue,
                    self.shared_state,
                    self.log_queue,
                )

    def test_init_mount_success(self):
        """Test successful mount initialization."""
        # Setup mock client to simulate successful connection
        self.mock_indi_client.telescope_device = self.mock_telescope

        # Mock isServerConnected to return True after connectServer is called
        def connect_side_effect():
            self.mock_indi_client.isServerConnected.return_value = True
            return True

        self.mock_indi_client.connectServer.side_effect = connect_side_effect

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
        # After successful init, server should be connected
        assert self.mount_control.client.isServerConnected() is True

    def test_init_mount_connection_failure(self):
        """Test mount initialization when server connection fails."""
        # Setup mock client to fail connection
        self.mock_indi_client.connectServer.return_value = False

        # Execute init_mount
        result = self.mount_control.init_mount()

        # Verify failure
        assert result is False
        assert self.mount_control.client.isServerConnected() is False

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
        self.mock_indi_client.isServerConnected.return_value = True
        self.mock_indi_client.set_switch.return_value = True
        self.mock_indi_client.set_number.return_value = True

        # Execute sync
        result = self.mount_control.sync_mount(45.0, 30.0)

        # Verify
        assert result is True

        # Verify all the set_switch calls were made in order
        calls = self.mock_indi_client.set_switch.call_args_list
        assert len(calls) == 3, f"Expected 3 set_switch calls, got {len(calls)}"

        # First call: set ON_COORD_SET to SYNC
        assert calls[0][0] == (self.mock_telescope, "ON_COORD_SET", "SYNC")
        # Second call: set ON_COORD_SET to TRACK
        assert calls[1][0] == (self.mock_telescope, "ON_COORD_SET", "TRACK")
        # Third call: set TELESCOPE_TRACK_STATE to TRACK_ON
        assert calls[2][0] == (self.mock_telescope, "TELESCOPE_TRACK_STATE", "TRACK_ON")

        # Verify set_number was called with coordinates (RA converted to hours)
        self.mock_indi_client.set_number.assert_called_with(
            self.mock_telescope,
            "EQUATORIAL_EOD_COORD",
            {"RA": 3.0, "DEC": 30.0},  # 45.0 deg / 15.0 = 3.0 hours
        )

    def test_sync_mount_no_device(self):
        """Test sync when no telescope device available."""
        self.mock_indi_client.telescope_device = None

        result = self.mount_control.sync_mount(45.0, 30.0)

        assert result is False

    def test_stop_mount_success(self):
        """Test successful mount stop."""
        # Setup
        self.mock_indi_client.telescope_device = self.mock_telescope
        self.mock_indi_client.set_switch.return_value = True

        # Execute stop
        result = self.mount_control.stop_mount()

        # Verify
        assert result is True
        self.mock_indi_client.set_switch.assert_called_with(
            self.mock_telescope, "TELESCOPE_ABORT_MOTION", "ABORT"
        )
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
        self.mock_indi_client.set_switch.return_value = True
        self.mock_indi_client.set_number.return_value = True

        # Execute goto
        result = self.mount_control.move_mount_to_target(120.0, 45.0)

        # Verify
        assert result is True
        # Verify set_switch was called with ON_COORD_SET to TRACK
        self.mock_indi_client.set_switch.assert_called_with(
            self.mock_telescope, "ON_COORD_SET", "TRACK"
        )
        # Verify set_number was called with coordinates (RA converted to hours)
        self.mock_indi_client.set_number.assert_called_with(
            self.mock_telescope,
            "EQUATORIAL_EOD_COORD",
            {"RA": 8.0, "DEC": 45.0},  # 120.0 deg / 15.0 = 8.0 hours
        )

    def test_move_mount_to_target_no_device(self):
        """Test goto when no telescope device available."""
        self.mock_indi_client.telescope_device = None

        result = self.mount_control.move_mount_to_target(120.0, 45.0)

        assert result is False

    def test_move_mount_manual_north(self):
        """Test manual movement in north direction."""
        # Setup
        self.mock_indi_client.telescope_device = self.mock_telescope
        self.mock_indi_client.set_switch.return_value = True
        self.mock_indi_client.set_switch_off.return_value = True
        # Mock available slew rates
        self.mount_control.available_slew_rates = [
            "SLEW_GUIDE",
            "SLEW_CENTERING",
            "SLEW_FIND",
            "SLEW_MAX",
        ]
        # Set initial position to avoid None in formatting
        self.mount_control.current_ra = 45.0
        self.mount_control.current_dec = 30.0

        # Execute manual movement
        with patch("time.sleep"):  # Mock sleep to speed up test
            result = self.mount_control.move_mount_manual(
                MountDirectionsEquatorial.NORTH, "SLEW_GUIDE", 1.0
            )

        # Verify
        assert result is True

        # Verify set_switch calls
        calls = self.mock_indi_client.set_switch.call_args_list
        # Should have two calls: one for slew rate, one for motion start
        assert len(calls) >= 2

        # Check slew rate was set
        assert any("TELESCOPE_SLEW_RATE" in str(call) for call in calls)
        # Check motion was started
        assert any(
            "TELESCOPE_MOTION_NS" in str(call) and "MOTION_NORTH" in str(call)
            for call in calls
        )

        # Verify set_switch_off was called to stop motion
        self.mock_indi_client.set_switch_off.assert_called_once()

    def test_move_mount_manual_no_device(self):
        """Test manual movement when no telescope device available."""
        self.mock_indi_client.telescope_device = None

        result = self.mount_control.move_mount_manual(
            MountDirectionsEquatorial.NORTH, "SLEW_GUIDE", 1.0
        )

        assert result is False

    def test_set_mount_step_size(self):
        """Test setting step size (always succeeds as it's managed by base class)."""
        result = self.mount_control.set_mount_step_size(2.5)

        assert result is True

    def test_disconnect_mount_success(self):
        """Test successful mount disconnection."""
        # Setup
        self.mock_indi_client.telescope_device = self.mock_telescope
        self.mock_indi_client.isServerConnected.return_value = True

        # Mock DISCONNECT property
        mock_disconnect_prop = MagicMock()
        mock_disconnect_switch = MagicMock()
        mock_disconnect_switch.name = "DISCONNECT"
        mock_disconnect_prop.nsp = 1
        mock_disconnect_prop.sp = [mock_disconnect_switch]
        self.mock_telescope.getProperty.return_value = mock_disconnect_prop

        # Mock disconnectServer to update isServerConnected
        def disconnect_side_effect():
            self.mock_indi_client.isServerConnected.return_value = False

        self.mock_indi_client.disconnectServer.side_effect = disconnect_side_effect

        # Execute disconnect
        result = self.mount_control.disconnect_mount()

        # Verify
        assert result is True
        self.mock_indi_client.disconnectServer.assert_called_once()
        assert self.mount_control.client.isServerConnected() is False

    def test_set_mount_drift_rates_not_implemented(self):
        """Test that drift rates return False (not implemented)."""
        result = self.mount_control.set_mount_drift_rates(0.1, 0.2)

        assert result is False


@pytest.mark.integration
@pytest.mark.skipif(
    not PYINDI_AVAILABLE,
    reason="PyIndi not available - integration tests require PyIndi installed",
)
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
            indi_port=7624,
        )

    def teardown_method(self):
        """Cleanup after each test."""
        if hasattr(self, "mount_control"):
            self.mount_control.disconnect_mount()

    def _init_mount(self):
        ret = self.mount_control.init_mount(
            latitude_deg=51.183333,
            longitude_deg=7.083333,
            elevation_m=250.0,
            utc_time=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        )
        return ret

    def test_radec_diff(self):
        """Test RA/Dec difference calculations."""
        # Test normal case (no wraparound)
        ra_diff, dec_diff = self.mount_control._radec_diff(10.0, 20.0, 15.0, 25.0)
        assert ra_diff == 5.0, f"Expected RA diff 5.0, got {ra_diff}"
        assert dec_diff == 5.0, f"Expected Dec diff 5.0, got {dec_diff}"

        # Test negative differences
        ra_diff, dec_diff = self.mount_control._radec_diff(15.0, 25.0, 10.0, 20.0)
        assert ra_diff == -5.0, f"Expected RA diff -5.0, got {ra_diff}"
        assert dec_diff == -5.0, f"Expected Dec diff -5.0, got {dec_diff}"

        # Test RA wraparound from 350° to 10° (should be +20°, not +380°)
        ra_diff, dec_diff = self.mount_control._radec_diff(350.0, 0.0, 10.0, 0.0)
        assert ra_diff == 20.0, f"Expected RA diff 20.0 (wraparound), got {ra_diff}"
        assert dec_diff == 0.0, f"Expected Dec diff 0.0, got {dec_diff}"

        # Test RA wraparound from 10° to 350° (should be -20°, not -340°)
        ra_diff, dec_diff = self.mount_control._radec_diff(10.0, 0.0, 350.0, 0.0)
        assert ra_diff == -20.0, f"Expected RA diff -20.0 (wraparound), got {ra_diff}"
        assert dec_diff == 0.0, f"Expected Dec diff 0.0, got {dec_diff}"

        # Test exactly 180° difference (should not wraparound)
        ra_diff, dec_diff = self.mount_control._radec_diff(0.0, 0.0, 180.0, 0.0)
        assert ra_diff == 180.0, f"Expected RA diff 180.0, got {ra_diff}"

        # Test exactly -180° difference (should not wraparound)
        ra_diff, dec_diff = self.mount_control._radec_diff(180.0, 0.0, 0.0, 0.0)
        assert ra_diff == -180.0, f"Expected RA diff -180.0, got {ra_diff}"

        # Test just over 180° (should wraparound)
        ra_diff, dec_diff = self.mount_control._radec_diff(0.0, 0.0, 181.0, 0.0)
        assert ra_diff == -179.0, f"Expected RA diff -179.0 (wraparound), got {ra_diff}"

        # Test just under -180° (should wraparound)
        ra_diff, dec_diff = self.mount_control._radec_diff(181.0, 0.0, 0.0, 0.0)
        assert ra_diff == 179.0, f"Expected RA diff 179.0 (wraparound), got {ra_diff}"

        # Test Dec limits (no wraparound for Dec)
        ra_diff, dec_diff = self.mount_control._radec_diff(0.0, -90.0, 0.0, 90.0)
        assert ra_diff == 0.0, f"Expected RA diff 0.0, got {ra_diff}"
        assert dec_diff == 180.0, f"Expected Dec diff 180.0, got {dec_diff}"

        # Test same positions
        ra_diff, dec_diff = self.mount_control._radec_diff(45.0, 30.0, 45.0, 30.0)
        assert ra_diff == 0.0, f"Expected RA diff 0.0, got {ra_diff}"
        assert dec_diff == 0.0, f"Expected Dec diff 0.0, got {dec_diff}"

    def test_init_mount_real_indi(self):
        """Test initialization with real INDI server."""
        # Use test location: N51° 11m 0s E7° 5m 0s, elevation 250m
        result = self._init_mount()

        assert result is True, "Failed to initialize mount with INDI server"
        assert self.mount_control.client.isServerConnected() is True
        assert self.mount_control._get_telescope_device() is not None
        print(
            f"Connected to: {self.mount_control._get_telescope_device().getDeviceName()}"
        )

    def test_sync_mount_real_indi(self):
        """Test sync with real INDI server."""
        # First initialize
        assert self._init_mount() is True

        # Give device time to fully initialize
        time.sleep(1.0)

        # Execute sync
        result = self.mount_control.sync_mount(45.0, 30.0)

        assert result is True, "Failed to sync mount"

        assert self.mount_control.current_ra == 45.0, "RA not updated to synced value"
        assert self.mount_control.current_dec == 30.0, "Dec not updated to synced value"

    def test_goto_mount_real_indi(self):
        """Test goto command with real INDI server."""
        # First initialize
        assert self._init_mount() is True
        time.sleep(1.0)

        # Sync to a known position first
        assert self.mount_control.sync_mount(0.0, 0.0) is True
        time.sleep(0.5)

        # Execute goto
        result = self.mount_control.move_mount_to_target(60.0, 45.0)

        assert result is True, "Failed to send goto command"

        start = time.time()
        timeout = 30.0  # seconds
        while time.time() - start < timeout:
            if self.mount_control.target_reached:
                break
            time.sleep(0.1)
        assert (
            self.mount_control.target_reached
        ), "Mount did not reach target within timeout."

    def test_stop_mount_real_indi(self):
        """Test stop command with real INDI server."""
        # First initialize
        assert self._init_mount() is True
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
        assert self._init_mount() is True
        time.sleep(1.0)

        self.mount_control.sync_mount(0.0, 0.0)
        time.sleep(0.5)

        # Get initial position
        (initial_ra, initial_dec) = (
            self.mount_control.current_ra,
            self.mount_control.current_dec,
        )
        print(f"Initial position: RA={initial_ra}, Dec={initial_dec}")

        # Move north (should increase Dec)
        result = self.mount_control.move_mount_manual(
            MountDirectionsEquatorial.NORTH, "4x", 1.0
        )
        assert result is True, "Failed to execute manual movement"

        # Wait for movement to complete
        time.sleep(0.5)

        # Check position changed
        final_ra = self.mount_control.current_ra
        final_dec = self.mount_control.current_dec
        print(f"Final position: RA={final_ra}, Dec={final_dec}")

        # Dec should have increased (north movement)
        if initial_dec is not None and final_dec is not None:
            assert (
                final_dec > initial_dec
            ), "Dec should have increased after north movement"

    def test_disconnect_mount_real_indi(self):
        """Test disconnection from real INDI server."""
        # First initialize and connect
        assert self._init_mount() is True

        # Disconnect
        result = self.mount_control.disconnect_mount()

        assert result is True, "Failed to disconnect mount"
        assert self.mount_control.client.isServerConnected() is False


if __name__ == "__main__":
    # Run unit tests
    print("Running unit tests...")
    pytest.main([__file__, "-v", "-m", "not integration"])

    print("\n" + "=" * 80)
    print("To run integration tests, ensure INDI Telescope Simulator is running:")
    print("  indiserver -v indi_simulator_telescope")
    print("Then run:")
    print("  pytest tests/test_mountcontrol_indi.py -v -m integration")
    print("=" * 80)
