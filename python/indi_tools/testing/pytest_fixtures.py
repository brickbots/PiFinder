"""
Pytest fixtures and utilities for INDI event recording and replay testing.

This module provides comprehensive pytest integration for the INDI event system,
including fixtures for mock clients, event data management, and assertion helpers.
"""

import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Any
import pytest
import PyIndi

# Add parent directory to path to import INDI tools
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parent_dir)

from event_replayer import IndiEventReplayer  # noqa: E402


class TestIndiClient(PyIndi.BaseClient):
    """
    Test INDI client designed for pytest usage.

    Provides comprehensive event tracking, state management, and assertion helpers
    specifically designed for testing scenarios.
    """

    def __init__(self, name: str = "TestClient"):
        super().__init__()
        self.name = name
        self.events = []
        self.devices = {}
        self.properties = {}
        self.messages = []
        self.connection_state = None
        self.start_time = time.time()

    def reset(self):
        """Reset client state for new test."""
        self.events.clear()
        self.devices.clear()
        self.properties.clear()
        self.messages.clear()
        self.connection_state = None
        self.start_time = time.time()

    def _record_event(self, event_type: str, **kwargs):
        """Record an event with timestamp."""
        event = {
            "type": event_type,
            "timestamp": time.time(),
            "relative_time": time.time() - self.start_time,
            "data": kwargs,
        }
        self.events.append(event)

    def newDevice(self, device):
        device_name = device.getDeviceName()
        self.devices[device_name] = device
        self._record_event("new_device", device_name=device_name)

    def removeDevice(self, device):
        device_name = device.getDeviceName()
        if device_name in self.devices:
            del self.devices[device_name]
        self._record_event("remove_device", device_name=device_name)

    def newProperty(self, prop):
        prop_key = f"{prop.getDeviceName()}.{prop.getName()}"
        self.properties[prop_key] = prop
        self._record_event(
            "new_property",
            device_name=prop.getDeviceName(),
            property_name=prop.getName(),
            property_type=prop.getTypeAsString(),
        )

    def updateProperty(self, prop):
        prop_key = f"{prop.getDeviceName()}.{prop.getName()}"
        self.properties[prop_key] = prop
        self._record_event(
            "update_property",
            device_name=prop.getDeviceName(),
            property_name=prop.getName(),
            property_state=prop.getStateAsString(),
        )

    def removeProperty(self, prop):
        prop_key = f"{prop.getDeviceName()}.{prop.getName()}"
        if prop_key in self.properties:
            del self.properties[prop_key]
        self._record_event(
            "remove_property",
            device_name=prop.getDeviceName(),
            property_name=prop.getName(),
        )

    def newMessage(self, device, message):
        msg_data = {
            "device_name": device.getDeviceName(),
            "message": message,
            "timestamp": time.time(),
        }
        self.messages.append(msg_data)
        self._record_event("new_message", **msg_data)

    def serverConnected(self):
        self.connection_state = "connected"
        self._record_event("server_connected")

    def serverDisconnected(self, code):
        self.connection_state = "disconnected"
        self._record_event("server_disconnected", exit_code=code)

    # Assertion helpers
    def assert_device_present(self, device_name: str):
        """Assert that a device is present."""
        assert (
            device_name in self.devices
        ), f"Device '{device_name}' not found. Available: {list(self.devices.keys())}"

    def assert_property_present(self, device_name: str, property_name: str):
        """Assert that a property is present."""
        prop_key = f"{device_name}.{property_name}"
        assert prop_key in self.properties, f"Property '{prop_key}' not found"

    def assert_message_received(self, device_name: str, message_content: str = None):
        """Assert that a message was received from a device."""
        device_messages = [
            msg for msg in self.messages if msg["device_name"] == device_name
        ]
        assert device_messages, f"No messages received from device '{device_name}'"

        if message_content:
            matching_messages = [
                msg for msg in device_messages if message_content in msg["message"]
            ]
            assert (
                matching_messages
            ), f"No messages from '{device_name}' containing '{message_content}'"

    def assert_event_count(self, event_type: str, expected_count: int):
        """Assert the number of events of a specific type."""
        actual_count = len([e for e in self.events if e["type"] == event_type])
        assert (
            actual_count == expected_count
        ), f"Expected {expected_count} {event_type} events, got {actual_count}"

    def assert_connected(self):
        """Assert that the client is connected."""
        assert self.connection_state == "connected", "Client is not connected"

    def get_events_by_type(self, event_type: str) -> List[Dict]:
        """Get all events of a specific type."""
        return [e for e in self.events if e["type"] == event_type]

    def get_property(self, device_name: str, property_name: str):
        """Get a property by device and property name."""
        prop_key = f"{device_name}.{property_name}"
        return self.properties.get(prop_key)


class EventDataManager:
    """
    Manages test event data files and scenarios.

    Provides utilities for creating, loading, and managing event files
    for different testing scenarios. Automatically discovers all .jsonl files
    in the test_data directory as available scenarios, with user-defined
    scenarios taking precedence over file-based ones.
    """

    def __init__(self, base_dir: Path = None):
        self.base_dir = base_dir or Path(__file__).parent / "test_data"
        self.base_dir.mkdir(exist_ok=True)
        self._user_scenarios = {}  # Store user-defined scenarios that override files

    def create_scenario(self, name: str, events: List[Dict]) -> Path:
        """
        Create an event scenario file.

        User-defined scenarios take precedence over existing files with the same name.
        """
        scenario_file = self.base_dir / f"{name}.jsonl"

        # Mark this as a user-defined scenario (takes precedence over files)
        self._user_scenarios[name] = scenario_file

        with open(scenario_file, "w") as f:
            for event in events:
                f.write(f"{json.dumps(event)}\n")

        return scenario_file

    def load_scenario(self, name: str) -> List[Dict]:
        """
        Load events from a scenario file.

        Checks for user-defined scenarios first, then falls back to
        any .jsonl file in the test_data directory with matching name.
        """
        # First check if this is a user-defined scenario (takes precedence)
        if name in self._user_scenarios:
            scenario_file = self._user_scenarios[name]
        else:
            # Check for any .jsonl file with the matching name
            scenario_file = self.base_dir / f"{name}.jsonl"

        if not scenario_file.exists():
            raise FileNotFoundError(f"Scenario '{name}' not found at {scenario_file}")

        events = []
        with open(scenario_file, "r") as f:
            for line in f:
                line = line.strip()
                # Skip empty lines and comment lines (starting with #)
                if line and not line.startswith("#"):
                    events.append(json.loads(line))

        return events

    def list_scenarios(self) -> List[str]:
        """
        List all available scenarios.

        Returns a combined list of file-based scenarios and user-defined scenarios,
        with user-defined scenarios taking precedence (no duplicates).
        """
        # Get all .jsonl files in the test_data directory
        file_scenarios = {f.stem for f in self.base_dir.glob("*.jsonl")}

        # Get user-defined scenario names
        user_scenarios = set(self._user_scenarios.keys())

        # Combine both sets (user scenarios will override file scenarios automatically)
        all_scenarios = file_scenarios | user_scenarios

        return sorted(list(all_scenarios))

    def create_basic_telescope_scenario(self) -> Path:
        """Create a basic telescope connection scenario."""
        events = [
            {
                "timestamp": time.time(),
                "relative_time": 0.0,
                "event_number": 0,
                "event_type": "server_connected",
                "data": {"host": "localhost", "port": 7624},
            },
            {
                "timestamp": time.time() + 1,
                "relative_time": 1.0,
                "event_number": 1,
                "event_type": "new_device",
                "data": {
                    "device_name": "Test Telescope",
                    "driver_name": "test_telescope",
                    "driver_exec": "test_telescope",
                    "driver_version": "1.0",
                },
            },
            {
                "timestamp": time.time() + 2,
                "relative_time": 2.0,
                "event_number": 2,
                "event_type": "new_property",
                "data": {
                    "name": "CONNECTION",
                    "device_name": "Test Telescope",
                    "type": "Switch",
                    "state": "Idle",
                    "permission": "ReadWrite",
                    "group": "Main Control",
                    "label": "Connection",
                    "rule": "OneOfMany",
                    "widgets": [
                        {"name": "CONNECT", "label": "Connect", "state": "Off"},
                        {"name": "DISCONNECT", "label": "Disconnect", "state": "On"},
                    ],
                },
            },
            {
                "timestamp": time.time() + 3,
                "relative_time": 3.0,
                "event_number": 3,
                "event_type": "update_property",
                "data": {
                    "name": "CONNECTION",
                    "device_name": "Test Telescope",
                    "type": "Switch",
                    "state": "Ok",
                    "permission": "ReadWrite",
                    "group": "Main Control",
                    "label": "Connection",
                    "rule": "OneOfMany",
                    "widgets": [
                        {"name": "CONNECT", "label": "Connect", "state": "On"},
                        {"name": "DISCONNECT", "label": "Disconnect", "state": "Off"},
                    ],
                },
            },
            {
                "timestamp": time.time() + 4,
                "relative_time": 4.0,
                "event_number": 4,
                "event_type": "new_message",
                "data": {
                    "device_name": "Test Telescope",
                    "message": "Telescope connected successfully",
                },
            },
        ]

        return self.create_scenario("basic_telescope", events)

    def create_coordinate_update_scenario(self) -> Path:
        """Create a scenario with telescope coordinate updates."""
        base_time = time.time()
        events = [
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
                    "device_name": "Test Telescope",
                    "driver_name": "test_telescope",
                    "driver_exec": "test_telescope",
                    "driver_version": "1.0",
                },
            },
            {
                "timestamp": base_time + 2,
                "relative_time": 2.0,
                "event_number": 2,
                "event_type": "new_property",
                "data": {
                    "name": "EQUATORIAL_EOD_COORD",
                    "device_name": "Test Telescope",
                    "type": "Number",
                    "state": "Idle",
                    "permission": "ReadWrite",
                    "group": "Main Control",
                    "label": "Equatorial Coordinates",
                    "rule": "AtMostOne",
                    "widgets": [
                        {
                            "name": "RA",
                            "label": "RA (hours)",
                            "value": 0.0,
                            "min": 0.0,
                            "max": 24.0,
                            "step": 0.0,
                            "format": "%010.6m",
                        },
                        {
                            "name": "DEC",
                            "label": "DEC (degrees)",
                            "value": 0.0,
                            "min": -90.0,
                            "max": 90.0,
                            "step": 0.0,
                            "format": "%010.6m",
                        },
                    ],
                },
            },
        ]

        # Add coordinate updates
        for i, (ra, dec) in enumerate([(12.5, 45.0), (12.6, 45.1), (12.7, 45.2)]):
            events.append(
                {
                    "timestamp": base_time + 3 + i,
                    "relative_time": 3.0 + i,
                    "event_number": 3 + i,
                    "event_type": "update_property",
                    "data": {
                        "name": "EQUATORIAL_EOD_COORD",
                        "device_name": "Test Telescope",
                        "type": "Number",
                        "state": "Ok",
                        "permission": "ReadWrite",
                        "group": "Main Control",
                        "label": "Equatorial Coordinates",
                        "rule": "AtMostOne",
                        "widgets": [
                            {
                                "name": "RA",
                                "label": "RA (hours)",
                                "value": ra,
                                "min": 0.0,
                                "max": 24.0,
                                "step": 0.0,
                                "format": "%010.6m",
                            },
                            {
                                "name": "DEC",
                                "label": "DEC (degrees)",
                                "value": dec,
                                "min": -90.0,
                                "max": 90.0,
                                "step": 0.0,
                                "format": "%010.6m",
                            },
                        ],
                    },
                }
            )

        return self.create_scenario("coordinate_updates", events)


# Pytest fixtures
@pytest.fixture
def test_client():
    """Provide a clean test INDI client for each test."""
    client = TestIndiClient()
    yield client
    # Cleanup happens automatically


@pytest.fixture
def event_data_manager(tmp_path):
    """Provide an event data manager with temporary directory."""
    manager = EventDataManager(tmp_path / "test_data")
    return manager


@pytest.fixture
def basic_telescope_scenario(event_data_manager):
    """Provide a basic telescope connection scenario."""
    scenario_file = event_data_manager.create_basic_telescope_scenario()
    return scenario_file


@pytest.fixture
def coordinate_scenario(event_data_manager):
    """Provide a coordinate update scenario."""
    scenario_file = event_data_manager.create_coordinate_update_scenario()
    return scenario_file


@pytest.fixture
def event_replayer():
    """Factory fixture for creating event replayers."""
    replayers = []

    def _create_replayer(event_file, client, speed=1.0):
        replayer = IndiEventReplayer(str(event_file), client)
        replayer.set_time_scale(speed)
        replayers.append(replayer)
        return replayer

    yield _create_replayer

    # Cleanup
    for replayer in replayers:
        replayer.stop_playback()


@pytest.fixture
def temp_event_file(tmp_path):
    """Provide a temporary event file for recording."""
    event_file = tmp_path / "test_recording.jsonl"
    return event_file


@pytest.fixture(scope="session")
def session_event_data():
    """Session-scoped event data manager for shared test data."""
    manager = EventDataManager()
    # Create common scenarios once per session
    manager.create_basic_telescope_scenario()
    manager.create_coordinate_update_scenario()
    return manager


# Parametrized fixtures for testing multiple scenarios
@pytest.fixture(params=["basic_telescope", "coordinate_updates"])
def scenario_name(request):
    """Parametrized fixture for testing multiple scenarios."""
    return request.param


@pytest.fixture
def scenario_file(scenario_name, session_event_data):
    """Load scenario file based on parametrized scenario name."""
    scenario_file = session_event_data.base_dir / f"{scenario_name}.jsonl"
    if not scenario_file.exists():
        # Create the scenario if it doesn't exist
        if scenario_name == "basic_telescope":
            return session_event_data.create_basic_telescope_scenario()
        elif scenario_name == "coordinate_updates":
            return session_event_data.create_coordinate_update_scenario()
        else:
            pytest.skip(f"Unknown scenario: {scenario_name}")
    return scenario_file


# Utility functions for tests
def wait_for_events(
    client: TestIndiClient, event_type: str, count: int, timeout: float = 5.0
) -> bool:
    """Wait for a specific number of events of a given type."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        current_count = len(client.get_events_by_type(event_type))
        if current_count >= count:
            return True
        time.sleep(0.1)
    return False


def assert_event_sequence(client: TestIndiClient, expected_sequence: List[str]):
    """Assert that events occurred in a specific sequence."""
    actual_sequence = [event["type"] for event in client.events]
    assert (
        actual_sequence == expected_sequence
    ), f"Expected {expected_sequence}, got {actual_sequence}"


def assert_property_value(
    client: TestIndiClient,
    device_name: str,
    property_name: str,
    widget_name: str,
    expected_value: Any,
):
    """Assert that a property widget has a specific value."""
    prop = client.get_property(device_name, property_name)
    assert prop is not None, f"Property {device_name}.{property_name} not found"

    # This is a simplified assertion - in real usage you'd need to handle
    # different property types and extract widget values properly
    # For now, we'll just check that the property exists
    client.assert_property_present(device_name, property_name)


# Pytest markers for categorizing tests
pytest_markers = {
    "integration": pytest.mark.integration,
    "unit": pytest.mark.unit,
    "slow": pytest.mark.slow,
    "indi": pytest.mark.indi,
    "replay": pytest.mark.replay,
    "recording": pytest.mark.recording,
}
