# INDI Event System - Pytest Integration Summary

## Quick Start for Pytest Testing

### 1. Setup
```bash
# Activate virtual environment
cd /path/to/PiFinder/python
source .venv/bin/activate

# Navigate to indi_tools testing directory
cd indi_tools/testing
```

### 2. Run Tests
```bash
# Run all tests
pytest

# Run specific test categories
pytest -m unit          # Fast unit tests only
pytest -m replay         # Event replay tests only
pytest -m integration    # Integration tests only

# Run with verbose output
pytest -v

# Run specific test file
pytest test_examples.py

# Run specific test
pytest test_examples.py::test_basic_telescope_replay
```

### 3. Basic Test Structure
```python
def test_my_indi_client(test_client, basic_telescope_scenario, event_replayer):
    """Test your INDI client with recorded events."""
    # Setup
    replayer = event_replayer(basic_telescope_scenario, test_client, speed=5.0)

    # Execute
    replayer.start_playback(blocking=True)

    # Assert
    test_client.assert_connected()
    test_client.assert_device_present("Test Telescope")
    assert len(test_client.events) > 0
```

## Available Fixtures

### Core Fixtures
- **`test_client`** - Pre-configured test INDI client with assertion helpers
- **`event_replayer`** - Factory for creating event replayers
- **`event_data_manager`** - Manages test scenario files

### Pre-built Scenarios
- **`basic_telescope_scenario`** - Basic telescope connection scenario
- **`coordinate_scenario`** - Telescope with coordinate updates

### Utilities
- **`temp_event_file`** - Temporary file for test recordings
- **`session_event_data`** - Session-scoped test data

## Test Categories (Markers)

- `@pytest.mark.unit` - Fast, isolated unit tests
- `@pytest.mark.integration` - Component integration tests
- `@pytest.mark.replay` - Tests using event replay
- `@pytest.mark.slow` - Tests that take significant time
- `@pytest.mark.indi` - INDI protocol specific tests

## Example Test Patterns

### 1. Testing Your INDI Client
```python
class MyTelescopeClient(PyIndi.BaseClient):
    def __init__(self):
        super().__init__()
        self.connected = False
        self.telescope_ra = 0.0
        self.telescope_dec = 0.0

    # ... your implementation ...

@pytest.mark.integration
def test_my_telescope_client(basic_telescope_scenario, event_replayer):
    client = MyTelescopeClient()
    replayer = event_replayer(basic_telescope_scenario, client)

    replayer.start_playback(blocking=True)

    assert client.connected
    # Add your specific assertions...
```

### 2. Custom Test Scenarios
```python
def test_custom_scenario(event_data_manager, test_client, event_replayer):
    # Create custom event sequence
    events = [
        {"event_type": "server_connected", "data": {...}},
        {"event_type": "new_device", "data": {...}},
        # ... more events ...
    ]

    scenario_file = event_data_manager.create_scenario("custom_test", events)
    replayer = event_replayer(scenario_file, test_client)

    replayer.start_playback(blocking=True)

    # Your assertions...
```

### 3. Parameterized Testing
```python
@pytest.mark.parametrize("speed", [1.0, 2.0, 5.0])
def test_different_speeds(test_client, basic_telescope_scenario, event_replayer, speed):
    replayer = event_replayer(basic_telescope_scenario, test_client, speed=speed)

    start_time = time.time()
    replayer.start_playback(blocking=True)
    duration = time.time() - start_time

    # Test timing expectations based on speed...
```

## Assertion Helpers

### Client Assertions
```python
# Connection and device assertions
test_client.assert_connected()
test_client.assert_device_present("Device Name")
test_client.assert_property_present("Device", "Property")

# Message assertions
test_client.assert_message_received("Device")
test_client.assert_message_received("Device", "specific content")

# Event counting
test_client.assert_event_count("new_device", 2)
```

### Utility Functions
```python
# Wait for events with timeout
success = wait_for_events(test_client, 'new_device', count=2, timeout=5.0)

# Check event sequences
assert_event_sequence(test_client, ['server_connected', 'new_device'])

# Get events by type
device_events = test_client.get_events_by_type('new_device')
```

## Integration with PiFinder Testing

### Add to Your Test Suite
```python
# In your test file
from indi_tools.testing.pytest_fixtures import (
    test_client, event_replayer, basic_telescope_scenario
)

def test_pifinder_mount_control(basic_telescope_scenario, event_replayer):
    """Test PiFinder mount control with INDI events."""
    from PiFinder.mountcontrol_indi import MountControlIndi

    # Use event replay instead of real INDI server
    mount_control = MountControlIndi(mock_events=basic_telescope_scenario)

    # Test mount control functionality...
```

### Test Structure Example
```
tests/
├── conftest.py                 # Import indi_tools.testing.pytest_fixtures
├── test_mount_control.py       # Your mount control tests
├── test_integration.py         # Integration tests
└── test_scenarios/            # Custom test scenarios
    ├── slewing.jsonl
    ├── connection_error.jsonl
    └── multi_device.jsonl
```

## Running Tests in CI/CD

### GitHub Actions Example
```yaml
- name: Run INDI Tests
  run: |
    cd python
    source .venv/bin/activate

    # Run fast tests
    pytest indi_tools/testing/ -m "unit or replay" --tb=short

    # Run integration tests (optional)
    pytest indi_tools/testing/ -m integration --tb=short
```

### Test Performance
- Unit tests: ~0.01-0.1 seconds each
- Replay tests: ~0.1-2 seconds each (depending on speed setting)
- Integration tests: ~1-5 seconds each

## Debugging Tips

### 1. Verbose Output
```bash
pytest -v -s  # Show print statements
```

### 2. Stop on First Failure
```bash
pytest -x
```

### 3. Debug Specific Test
```bash
pytest test_examples.py::test_basic_telescope_replay -v -s
```

### 4. Create Debug Scenarios
```python
def test_debug_scenario(event_data_manager, test_client, event_replayer):
    # Create minimal scenario for debugging
    events = [{"event_type": "server_connected", "data": {}}]

    scenario_file = event_data_manager.create_scenario("debug", events)
    replayer = event_replayer(scenario_file, test_client, speed=1.0)

    # Add breakpoint or verbose logging
    import pdb; pdb.set_trace()

    replayer.start_playback(blocking=True)
```

## Best Practices

1. **Use appropriate test markers** for categorization
2. **Start with fast unit tests** before integration tests
3. **Create reusable scenarios** for common test cases
4. **Use descriptive test names** that explain what's being tested
5. **Keep tests isolated** - each test should be independent
6. **Use fast replay speeds** for quick testing (5x-10x)
7. **Document complex scenarios** with comments or separate files

## File Overview

- `pytest_fixtures.py` - All pytest fixtures and utilities
- `conftest.py` - Pytest configuration and setup
- `test_examples.py` - Example test cases showing usage patterns
- `PYTEST_GUIDE.md` - Comprehensive usage guide
- `PYTEST_USAGE_SUMMARY.md` - This quick reference

The pytest integration provides a complete testing framework for INDI clients that's fast, reliable, and doesn't require actual hardware.