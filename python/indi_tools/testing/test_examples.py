"""
Example pytest test cases demonstrating INDI event recording and replay testing.

This module shows various patterns for testing INDI clients using the
event recording and replay system with pytest fixtures.
"""

import time
import pytest
import PyIndi

# Import our pytest fixtures and utilities
from pytest_fixtures import wait_for_events, assert_event_sequence, pytest_markers


class ExampleMountControl(PyIndi.BaseClient):
    """
    Example mount control class for testing.

    This represents the kind of INDI client you might want to test.
    """

    def __init__(self):
        super().__init__()
        self.telescope_device = None
        self.connected = False
        self.current_ra = 0.0
        self.current_dec = 0.0
        self.connection_messages = []

    def newDevice(self, device):
        device_name = device.getDeviceName()
        if any(keyword in device_name.lower() for keyword in ["telescope", "mount"]):
            self.telescope_device = device

    def newProperty(self, prop):
        # Handle new properties
        # This helps with device detection
        pass

    def updateProperty(self, prop):
        # Handle coordinate updates
        if (
            prop.getName() == "EQUATORIAL_EOD_COORD"
            and prop.getType() == PyIndi.INDI_NUMBER
        ):
            # Iterate over property widgets using the standard interface
            for widget in prop:
                if widget.getName() == "RA":
                    self.current_ra = widget.getValue()
                elif widget.getName() == "DEC":
                    self.current_dec = widget.getValue()

    def newMessage(self, device, message):
        # Store all messages from telescope/mount devices
        if (
            self.telescope_device
            and device.getDeviceName() == self.telescope_device.getDeviceName()
        ):
            self.connection_messages.append(message)

        # Also check for connection-specific messages
        if "connect" in message.lower():
            self.connection_messages.append(message)
            if "success" in message.lower():
                self.connected = True

    def serverConnected(self):
        pass

    def serverDisconnected(self, code):
        self.connected = False

    def get_coordinates(self):
        """Get current telescope coordinates."""
        return self.current_ra, self.current_dec

    def is_connected(self):
        """Check if telescope is connected."""
        return self.connected


# Basic functionality tests
@pytest_markers["unit"]
def test_client_basic_functionality(test_client):
    """Test basic test client functionality."""
    # Initially empty
    assert len(test_client.events) == 0
    assert len(test_client.devices) == 0
    assert test_client.connection_state is None

    # Test reset
    test_client._record_event("test_event", data="test")
    assert len(test_client.events) == 1

    test_client.reset()
    assert len(test_client.events) == 0


@pytest_markers["unit"]
def test_event_data_manager(event_data_manager):
    """Test event data manager functionality."""
    # Create a simple scenario
    events = [
        {"event_type": "test", "data": {"value": 1}},
        {"event_type": "test", "data": {"value": 2}},
    ]

    scenario_file = event_data_manager.create_scenario("test_scenario", events)
    assert scenario_file.exists()

    # Load and verify
    loaded_events = event_data_manager.load_scenario("test_scenario")
    assert len(loaded_events) == 2
    assert loaded_events[0]["data"]["value"] == 1

    # List scenarios
    scenarios = event_data_manager.list_scenarios()
    assert "test_scenario" in scenarios


# Replay testing
@pytest_markers["replay"]
def test_basic_telescope_replay(test_client, basic_telescope_scenario, event_replayer):
    """Test replaying a basic telescope connection scenario."""
    # Create replayer and start playback
    replayer = event_replayer(basic_telescope_scenario, test_client, speed=10.0)
    replayer.start_playback(blocking=True)

    # Assert expected events occurred
    test_client.assert_connected()
    test_client.assert_device_present("Test Telescope")
    test_client.assert_property_present("Test Telescope", "CONNECTION")
    test_client.assert_message_received("Test Telescope", "connected")

    # Check event sequence
    expected_sequence = [
        "server_connected",
        "new_device",
        "new_property",
        "update_property",
        "new_message",
    ]
    assert_event_sequence(test_client, expected_sequence)


@pytest_markers["replay"]
def test_coordinate_updates(test_client, coordinate_scenario, event_replayer):
    """Test coordinate update scenario."""
    replayer = event_replayer(coordinate_scenario, test_client, speed=5.0)
    replayer.start_playback(blocking=True)

    # Check that we received coordinate updates
    coord_updates = test_client.get_events_by_type("update_property")
    coord_updates = [
        e for e in coord_updates if e["data"]["property_name"] == "EQUATORIAL_EOD_COORD"
    ]

    assert len(coord_updates) >= 3, "Should have received at least 3 coordinate updates"

    # Verify the property exists
    test_client.assert_property_present("Test Telescope", "EQUATORIAL_EOD_COORD")


# Integration tests with custom mount control
@pytest_markers["integration"]
def test_mount_control_connection(basic_telescope_scenario, event_replayer):
    """Test mount control client with connection scenario."""
    mount = ExampleMountControl()
    replayer = event_replayer(basic_telescope_scenario, mount, speed=5.0)

    replayer.start_playback(blocking=True)

    # Check mount control state
    assert mount.telescope_device is not None
    assert mount.is_connected()
    assert len(mount.connection_messages) > 0


@pytest_markers["integration"]
def test_mount_control_coordinates(coordinate_scenario, event_replayer):
    """Test mount control coordinate tracking."""
    mount = ExampleMountControl()
    replayer = event_replayer(coordinate_scenario, mount, speed=10.0)

    replayer.start_playback(blocking=True)

    # Check coordinate tracking
    ra, dec = mount.get_coordinates()
    assert ra > 0.0, "RA should have been updated"
    assert dec > 0.0, "DEC should have been updated"


# Parametrized tests
@pytest_markers["replay"]
def test_multiple_scenarios(test_client, scenario_file, event_replayer):
    """Test multiple scenarios using parametrized fixtures."""
    replayer = event_replayer(scenario_file, test_client, speed=10.0)
    replayer.start_playback(blocking=True)

    # Basic assertions that should work for any scenario
    test_client.assert_connected()
    assert len(test_client.devices) > 0
    assert len(test_client.events) > 0


# Timing and performance tests
@pytest_markers["replay"]
def test_replay_timing(test_client, basic_telescope_scenario, event_replayer):
    """Test that replay timing is approximately correct."""
    replayer = event_replayer(basic_telescope_scenario, test_client, speed=2.0)

    start_time = time.time()
    replayer.start_playback(blocking=True)
    duration = time.time() - start_time

    # With 2x speed, 4 seconds of events should take ~2 seconds
    # Allow some tolerance for processing time
    assert 1.5 <= duration <= 3.0, f"Replay took {duration}s, expected ~2s"


@pytest_markers["slow"]
def test_replay_at_normal_speed(test_client, basic_telescope_scenario, event_replayer):
    """Test replay at normal speed (slower test)."""
    replayer = event_replayer(basic_telescope_scenario, test_client, speed=1.0)

    start_time = time.time()
    replayer.start_playback(blocking=True)
    duration = time.time() - start_time

    # Should take close to the original 4 seconds
    assert 3.5 <= duration <= 5.0, f"Replay took {duration}s, expected ~4s"


# Error handling tests
@pytest_markers["unit"]
def test_missing_scenario_file(event_data_manager):
    """Test handling of missing scenario files."""
    with pytest.raises(FileNotFoundError):
        event_data_manager.load_scenario("nonexistent_scenario")


@pytest_markers["replay"]
def test_replayer_with_invalid_file(test_client):
    """Test replayer with invalid event file."""
    from event_replayer import IndiEventReplayer
    import tempfile

    # Create a file with invalid JSON
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write('{"invalid": json}\n')
        f.write("not json at all\n")
        invalid_file = f.name

    try:
        # Should handle invalid JSON gracefully
        replayer = IndiEventReplayer(invalid_file, test_client)
        # Should have loaded only valid events (none in this case)
        assert len(replayer.events) == 0
    finally:
        import os

        os.unlink(invalid_file)


# Comment parsing tests
@pytest_markers["unit"]
def test_comment_parsing(event_data_manager, test_client):
    """Test that comment lines starting with # are skipped."""
    from event_replayer import IndiEventReplayer

    # Use the EventDataManager to get the commented_events scenario file
    scenario_file = event_data_manager.base_dir / "commented_events.jsonl"

    replayer = IndiEventReplayer(str(scenario_file), test_client)

    # Should load exactly 2 events (comments ignored)
    assert len(replayer.events) == 2
    assert replayer.events[0]["event_type"] == "server_connected"
    assert replayer.events[1]["event_type"] == "new_device"


# Custom scenario creation tests
@pytest_markers["unit"]
def test_custom_scenario_creation(event_data_manager):
    """Test creating custom test scenarios."""
    # Create a scenario with specific timing
    events = []
    base_time = time.time()

    for i in range(5):
        events.append(
            {
                "timestamp": base_time + i * 0.5,
                "relative_time": i * 0.5,
                "event_number": i,
                "event_type": "test_event",
                "data": {"sequence": i},
            }
        )

    event_data_manager.create_scenario("timing_test", events)
    loaded_events = event_data_manager.load_scenario("timing_test")

    assert len(loaded_events) == 5
    for i, event in enumerate(loaded_events):
        assert event["data"]["sequence"] == i
        assert event["relative_time"] == i * 0.5


# Assertion helper tests
@pytest_markers["unit"]
def test_assertion_helpers(test_client):
    """Test custom assertion methods."""
    # Test device assertion (should fail)
    with pytest.raises(AssertionError):
        test_client.assert_device_present("NonexistentDevice")

    # Test property assertion (should fail)
    with pytest.raises(AssertionError):
        test_client.assert_property_present("Device", "Property")

    # Test event count assertion
    test_client._record_event("test_event")
    test_client._record_event("test_event")
    test_client.assert_event_count("test_event", 2)

    with pytest.raises(AssertionError):
        test_client.assert_event_count("test_event", 3)


# Utility function tests
@pytest_markers["unit"]
def test_wait_for_events(test_client):
    """Test the wait_for_events utility function."""
    import threading
    import time

    def delayed_events():
        time.sleep(0.5)
        test_client._record_event("delayed_event")
        time.sleep(0.5)
        test_client._record_event("delayed_event")

    # Start delayed event generation
    thread = threading.Thread(target=delayed_events)
    thread.start()

    # Wait for events
    success = wait_for_events(test_client, "delayed_event", 2, timeout=2.0)
    assert success

    thread.join()

    # Test timeout
    success = wait_for_events(test_client, "nonexistent_event", 1, timeout=0.1)
    assert not success


# Real-world scenario test
@pytest_markers["integration"]
def test_telescope_slew_scenario(event_data_manager, event_replayer):
    """Test a realistic telescope slewing scenario."""
    # Create a slewing scenario
    base_time = time.time()
    slew_events = [
        # Connection
        {
            "timestamp": base_time,
            "relative_time": 0.0,
            "event_number": 0,
            "event_type": "server_connected",
            "data": {"host": "localhost", "port": 7624},
        },
        {
            "timestamp": base_time + 1,
            "relative_time": 1.0,
            "event_number": 1,
            "event_type": "new_device",
            "data": {
                "device_name": "Test Mount",
                "driver_name": "test_mount",
                "driver_exec": "test_mount",
                "driver_version": "1.0",
            },
        },
        # Start slew
        {
            "timestamp": base_time + 2,
            "relative_time": 2.0,
            "event_number": 2,
            "event_type": "new_message",
            "data": {
                "device_name": "Test Mount",
                "message": "Slewing to target coordinates",
            },
        },
        # Slew progress updates
        {
            "timestamp": base_time + 3,
            "relative_time": 3.0,
            "event_number": 3,
            "event_type": "new_message",
            "data": {"device_name": "Test Mount", "message": "Slew progress: 50%"},
        },
        # Slew complete
        {
            "timestamp": base_time + 4,
            "relative_time": 4.0,
            "event_number": 4,
            "event_type": "new_message",
            "data": {
                "device_name": "Test Mount",
                "message": "Slew completed successfully",
            },
        },
    ]

    scenario_file = event_data_manager.create_scenario("telescope_slew", slew_events)

    # Test with mount control
    mount = ExampleMountControl()
    replayer = event_replayer(scenario_file, mount, speed=5.0)

    replayer.start_playback(blocking=True)

    # Verify slew scenario
    assert mount.telescope_device is not None
    assert "Slewing" in " ".join(mount.connection_messages)
    assert "completed" in " ".join(mount.connection_messages)


if __name__ == "__main__":
    # Run tests when script is executed directly
    pytest.main([__file__, "-v"])
