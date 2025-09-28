# INDI Event System Pytest Integration Guide

This guide shows how to use the INDI event recording and replay system with pytest for comprehensive testing of INDI clients.

## Quick Start

### 1. Basic Test Setup

```python
import pytest
from pytest_fixtures import test_client, basic_telescope_scenario, event_replayer

def test_my_indi_client(test_client, basic_telescope_scenario, event_replayer):
    """Test your INDI client with a basic telescope scenario."""
    # Create replayer with your client
    replayer = event_replayer(basic_telescope_scenario, test_client, speed=5.0)

    # Run the scenario
    replayer.start_playback(blocking=True)

    # Make assertions
    test_client.assert_connected()
    test_client.assert_device_present("Test Telescope")
    assert len(test_client.events) > 0
```

### 2. Testing Your Own INDI Client

```python
class MyMountControl(PyIndi.BaseClient):
    def __init__(self):
        super().__init__()
        self.telescope_connected = False
        self.current_coordinates = (0.0, 0.0)

    def newDevice(self, device):
        if "telescope" in device.getDeviceName().lower():
            self.telescope_connected = True

    # ... your implementation ...

def test_my_mount_control(basic_telescope_scenario, event_replayer):
    """Test your mount control implementation."""
    mount = MyMountControl()
    replayer = event_replayer(basic_telescope_scenario, mount)

    replayer.start_playback(blocking=True)

    assert mount.telescope_connected
    # Add your specific assertions...
```

## Available Fixtures

### Core Fixtures

#### `test_client`
Provides a comprehensive test INDI client with event tracking and assertion helpers.

```python
def test_with_client(test_client):
    # Client automatically tracks all events
    assert len(test_client.events) == 0

    # Built-in assertion helpers
    test_client.assert_device_present("Device Name")
    test_client.assert_property_present("Device", "Property")
    test_client.assert_message_received("Device", "message content")
    test_client.assert_event_count("new_device", 2)
```

#### `event_replayer`
Factory fixture for creating event replayers.

```python
def test_with_replayer(event_replayer, test_client):
    replayer = event_replayer(
        event_file="my_scenario.jsonl",
        client=test_client,
        speed=2.0  # 2x speed
    )
    replayer.start_playback(blocking=True)
```

#### `event_data_manager`
Manages test scenario files.

```python
def test_custom_scenario(event_data_manager):
    # Create custom scenario
    events = [
        {"event_type": "server_connected", "data": {...}},
        {"event_type": "new_device", "data": {...}}
    ]

    scenario_file = event_data_manager.create_scenario("custom", events)

    # Load existing scenario
    loaded_events = event_data_manager.load_scenario("basic_telescope")
```

### Pre-built Scenarios

#### `basic_telescope_scenario`
Basic telescope connection and setup scenario.

```python
def test_basic_connection(test_client, basic_telescope_scenario, event_replayer):
    replayer = event_replayer(basic_telescope_scenario, test_client)
    replayer.start_playback(blocking=True)

    # Telescope should be connected with basic properties
    test_client.assert_device_present("Test Telescope")
    test_client.assert_property_present("Test Telescope", "CONNECTION")
```

#### `coordinate_scenario`
Telescope with coordinate updates.

```python
def test_coordinate_tracking(test_client, coordinate_scenario, event_replayer):
    replayer = event_replayer(coordinate_scenario, test_client)
    replayer.start_playback(blocking=True)

    # Should have received coordinate updates
    coord_updates = test_client.get_events_by_type('update_property')
    assert len(coord_updates) >= 3
```

### Parametrized Testing

Test multiple scenarios automatically:

```python
@pytest.mark.parametrize("scenario_name", ["basic_telescope", "coordinate_updates"])
def test_multiple_scenarios(test_client, scenario_name, session_event_data, event_replayer):
    scenario_file = session_event_data.base_dir / f"{scenario_name}.jsonl"
    replayer = event_replayer(scenario_file, test_client, speed=10.0)

    replayer.start_playback(blocking=True)

    # Tests that should pass for any scenario
    test_client.assert_connected()
    assert len(test_client.devices) > 0
```

## Creating Custom Test Scenarios

### Method 1: Programmatic Creation

```python
def test_custom_scenario(event_data_manager, test_client, event_replayer):
    # Define your scenario
    events = [
        {
            "timestamp": time.time(),
            "relative_time": 0.0,
            "event_number": 0,
            "event_type": "server_connected",
            "data": {"host": "localhost", "port": 7624}
        },
        {
            "timestamp": time.time() + 1,
            "relative_time": 1.0,
            "event_number": 1,
            "event_type": "new_device",
            "data": {
                "device_name": "My Custom Device",
                "driver_name": "custom_driver",
                "driver_exec": "custom_driver",
                "driver_version": "1.0"
            }
        },
        # Add more events...
    ]

    scenario_file = event_data_manager.create_scenario("my_test", events)
    replayer = event_replayer(scenario_file, test_client)
    replayer.start_playback(blocking=True)

    # Your assertions...
```

### Method 2: Record and Edit

```python
# First, record real events
def record_scenario_for_testing():
    """Run this once to record a real scenario."""
    from event_recorder import IndiEventRecorder

    recorder = IndiEventRecorder("my_real_scenario.jsonl")
    recorder.setServer("localhost", 7624)
    recorder.connectServer()

    # Let it record for a while...
    time.sleep(30)

    recorder.disconnectServer()
    recorder.close()

# Then use in tests
def test_real_scenario(test_client, event_replayer):
    replayer = event_replayer("my_real_scenario.jsonl", test_client)
    replayer.start_playback(blocking=True)
    # Your tests...
```

### Method 3: Edit Existing Scenarios

```python
def test_modified_scenario(event_data_manager, test_client, event_replayer):
    # Load existing scenario
    events = event_data_manager.load_scenario("basic_telescope")

    # Modify events (e.g., change timing, add errors, etc.)
    for event in events:
        if event["event_type"] == "new_message":
            event["data"]["message"] = "Modified test message"

    # Save modified scenario
    modified_file = event_data_manager.create_scenario("modified_test", events)

    replayer = event_replayer(modified_file, test_client)
    replayer.start_playback(blocking=True)

    # Test with modified scenario
    test_client.assert_message_received("Test Telescope", "Modified test message")
```

## Advanced Testing Patterns

### Testing Timing and Performance

```python
def test_replay_timing(test_client, basic_telescope_scenario, event_replayer):
    """Test that replay timing is correct."""
    replayer = event_replayer(basic_telescope_scenario, test_client, speed=2.0)

    start_time = time.time()
    replayer.start_playback(blocking=True)
    duration = time.time() - start_time

    # With 2x speed, should take about half the original time
    assert 1.0 <= duration <= 3.0
```

### Testing Error Scenarios

```python
def test_connection_failure(event_data_manager, test_client, event_replayer):
    """Test handling of connection failures."""
    error_events = [
        {
            "timestamp": time.time(),
            "relative_time": 0.0,
            "event_number": 0,
            "event_type": "server_connected",
            "data": {"host": "localhost", "port": 7624}
        },
        {
            "timestamp": time.time() + 1,
            "relative_time": 1.0,
            "event_number": 1,
            "event_type": "server_disconnected",
            "data": {"host": "localhost", "port": 7624, "exit_code": 1}
        }
    ]

    scenario_file = event_data_manager.create_scenario("connection_error", error_events)
    replayer = event_replayer(scenario_file, test_client)

    replayer.start_playback(blocking=True)

    # Should handle disconnection gracefully
    assert test_client.connection_state == 'disconnected'
```

### Testing State Transitions

```python
def test_telescope_states(event_data_manager, test_client, event_replayer):
    """Test telescope state transitions."""
    state_events = [
        # Connection events
        {"event_type": "server_connected", ...},
        {"event_type": "new_device", ...},

        # Initial disconnected state
        {"event_type": "update_property", "data": {
            "name": "CONNECTION",
            "widgets": [
                {"name": "CONNECT", "state": "Off"},
                {"name": "DISCONNECT", "state": "On"}
            ]
        }},

        # Connect
        {"event_type": "update_property", "data": {
            "name": "CONNECTION",
            "widgets": [
                {"name": "CONNECT", "state": "On"},
                {"name": "DISCONNECT", "state": "Off"}
            ]
        }},

        # Connected message
        {"event_type": "new_message", "data": {
            "message": "Telescope connected"
        }}
    ]

    # Test the sequence...
```

## Assertion Helpers Reference

### Client Assertions

```python
# Device and property assertions
test_client.assert_device_present("Device Name")
test_client.assert_property_present("Device", "Property")

# Message assertions
test_client.assert_message_received("Device")  # Any message
test_client.assert_message_received("Device", "specific content")

# Event counting
test_client.assert_event_count("new_device", 2)
test_client.assert_event_count("update_property", 5)

# Connection state
test_client.assert_connected()
```

### Event Sequence Assertions

```python
from pytest_fixtures import assert_event_sequence

# Test exact event sequence
assert_event_sequence(test_client, [
    'server_connected',
    'new_device',
    'new_property',
    'update_property'
])
```

### Utility Functions

```python
from pytest_fixtures import wait_for_events

# Wait for specific events with timeout
success = wait_for_events(test_client, 'new_device', count=2, timeout=5.0)
assert success

# Get events by type
device_events = test_client.get_events_by_type('new_device')
assert len(device_events) == 2

# Get specific property
prop = test_client.get_property("Device", "Property")
assert prop is not None
```

## Test Organization

### Using Pytest Markers

```python
import pytest
from pytest_fixtures import pytest_markers

# Categorize your tests
@pytest_markers['unit']
def test_basic_functionality():
    """Fast unit test."""
    pass

@pytest_markers['integration']
def test_full_scenario():
    """Integration test with full INDI interaction."""
    pass

@pytest_markers['slow']
def test_long_scenario():
    """Test that takes a long time."""
    pass

@pytest_markers['replay']
def test_event_replay():
    """Test using event replay."""
    pass
```

Run specific test categories:
```bash
# Run only unit tests
pytest -m unit

# Run everything except slow tests
pytest -m "not slow"

# Run only replay tests
pytest -m replay
```

### Conftest.py Setup

Create `conftest.py` in your test directory:

```python
# conftest.py
import pytest
import sys
import os

# Add INDI poc directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'indi_tools'))

# Import all fixtures
from pytest_fixtures import *

# Configure pytest markers
def pytest_configure(config):
    config.addinivalue_line("markers", "unit: Unit tests")
    config.addinivalue_line("markers", "integration: Integration tests")
    config.addinivalue_line("markers", "slow: Slow tests")
    config.addinivalue_line("markers", "replay: Event replay tests")
    config.addinivalue_line("markers", "indi: INDI-related tests")
```

## Running Tests

### Basic Usage

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest test_examples.py

# Run specific test
pytest test_examples.py::test_basic_telescope_replay
```

### Parallel Testing

```bash
# Install pytest-xdist
pip install pytest-xdist

# Run tests in parallel
pytest -n 4  # Use 4 workers
```

### Coverage Reports

```bash
# Install pytest-cov
pip install pytest-cov

# Run with coverage
pytest --cov=your_module --cov-report=html
```

## Best Practices

### 1. Test Organization

- Use clear, descriptive test names
- Group related tests in classes
- Use appropriate pytest markers
- Keep tests focused and isolated

### 2. Scenario Management

- Create reusable scenarios for common cases
- Use descriptive scenario names
- Version control your scenario files
- Document complex scenarios

### 3. Performance

- Use faster replay speeds for quick tests
- Cache common scenarios at session scope
- Use parametrized tests efficiently
- Mark slow tests appropriately

### 4. Debugging

- Use verbose output for debugging
- Add custom logging to your clients
- Save failing scenario data for reproduction
- Use pytest's debugging features (`--pdb`)

### 5. Continuous Integration

- Run fast tests on every commit
- Run slow/integration tests nightly
- Use different test environments
- Archive test scenarios with releases

## Example Test Suite Structure

```
tests/
├── conftest.py                 # Pytest configuration
├── test_unit/                  # Unit tests
│   ├── test_client_basic.py
│   └── test_utils.py
├── test_integration/           # Integration tests
│   ├── test_mount_control.py
│   └── test_full_scenarios.py
├── test_data/                  # Test scenarios
│   ├── basic_telescope.jsonl
│   ├── coordinate_updates.jsonl
│   └── error_scenarios.jsonl
└── test_performance/           # Performance tests
    └── test_timing.py
```

This structure provides comprehensive testing capabilities for INDI clients using the event recording and replay system with pytest.