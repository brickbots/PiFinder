# INDI Tools - Event Recording and Replay System

This directory contains a complete toolkit for INDI development and testing, including an event recording and replay system. The tools allow you to capture real INDI protocol interactions and replay them later without requiring actual hardware.

## Components

### 1. Event Recorder (`event_recorder.py`)
A PyIndi client that connects to an INDI server and records all events to a JSON Lines file.

**Features:**
- Records all INDI protocol events (devices, properties, messages, etc.)
- Timestamps and sequences events for accurate replay
- Captures complete property metadata and widget values
- Handles all INDI property types (Text, Number, Switch, Light, BLOB)
- Configurable output file and recording duration

### 2. Event Replayer (`event_replayer.py`)
A mock system that reads recorded events and replays them to INDI clients.

**Features:**
- Replays events with accurate timing
- Configurable playback speed (fast-forward, slow-motion)
- Creates mock devices and properties that behave like real ones
- Thread-safe playback with start/stop controls
- Compatible with any PyIndi.BaseClient

### 3. Event Format Documentation (`EVENT_FORMAT.md`)
Complete specification of the JSON Lines event format used for recordings.

**Features:**
- Human-readable and editable format
- Detailed examples for all event types
- Editing guidelines and best practices
- Validation tools and techniques

### 4. Testing Framework (`testing/`)
Comprehensive pytest integration for testing INDI clients.

**Features:**
- Pytest fixtures for easy test setup
- Pre-built test scenarios
- Assertion helpers for INDI events
- Parameterized testing capabilities
- Test data management system

**Components:**
- `pytest_fixtures.py` - Core pytest fixtures and utilities
- `conftest.py` - Pytest configuration
- `test_examples.py` - Example test cases
- `PYTEST_GUIDE.md` - Comprehensive usage guide
- `PYTEST_USAGE_SUMMARY.md` - Quick reference

### 5. Legacy Test Suite (`test_recording_replay.py`)
Original comprehensive test script demonstrating all functionality.

**Features:**
- Live recording tests
- Replay validation tests
- Mock event generation
- Performance benchmarks
- Sample event creation

## Quick Start

### Prerequisites

1. Install PyIndi library:
```bash
# On Ubuntu/Debian
sudo apt install python3-indi

# Or build from source
pip install PyIndi
```

2. Start an INDI server for testing:
```bash
indiserver indi_simulator_telescope indi_simulator_ccd
```

### Recording Events

Record events from a live INDI server:

```bash
# Record for 30 seconds
python event_recorder.py --duration 30 --output my_session.jsonl

# Record with verbose logging
python event_recorder.py --verbose --output debug_session.jsonl

# Record from custom server
python event_recorder.py --host 192.168.1.100 --port 7624
```

### Replaying Events

Replay recorded events to test your INDI client:

```python
from event_replayer import IndiEventReplayer
import PyIndi

# Your INDI client
class MyClient(PyIndi.BaseClient):
    # ... your client implementation ...
    pass

# Create client and replayer
client = MyClient()
replayer = IndiEventReplayer("my_session.jsonl", client)

# Replay at 2x speed
replayer.set_time_scale(2.0)
replayer.start_playback(blocking=True)
```

Or use the command line:

```bash
# Replay with built-in test client
python event_replayer.py my_session.jsonl

# Replay at different speeds
python event_replayer.py my_session.jsonl --speed 0.5  # Half speed
python event_replayer.py my_session.jsonl --speed 5.0  # 5x speed
```

### Running Tests

Test the complete system:

```bash
# Modern pytest-based testing (recommended)
cd testing
pytest -v

# Run specific test categories
pytest -m unit          # Fast unit tests
pytest -m replay        # Event replay tests
pytest -m integration   # Integration tests

# Legacy test script
python test_recording_replay.py --mode test

# Test recording (requires live INDI server)
python test_recording_replay.py --mode record --duration 10

# Test replay with a sample file
python test_recording_replay.py --mode sample
python test_recording_replay.py --mode replay --file sample_events.jsonl
```

## Use Cases

### 1. Testing Without Hardware

Record a session with your real telescope setup, then replay it during development:

```bash
# At the telescope (with real hardware)
python event_recorder.py --output telescope_session.jsonl --duration 300

# Later, in development (no hardware needed)
python your_client_test.py --mock-events telescope_session.jsonl
```

### 2. Creating Test Scenarios

Edit recorded events to create specific test scenarios:

```bash
# Record base session
python event_recorder.py --output base.jsonl --duration 60

# Edit base.jsonl to add error conditions, timing changes, etc.
cp base.jsonl error_scenario.jsonl
# ... edit error_scenario.jsonl ...

# Test with modified scenario
python event_replayer.py error_scenario.jsonl
```

### 3. Regression Testing

Capture known-good behavior and replay it for regression tests:

```python
def test_telescope_slew():
    client = MyTelescopeClient()
    replayer = IndiEventReplayer("slew_test.jsonl", client)

    replayer.start_playback(blocking=True)

    # Verify expected behavior
    assert client.final_ra == expected_ra
    assert client.final_dec == expected_dec
```

### 4. Performance Testing

Test client performance with accelerated event streams:

```bash
# Replay 1-hour session in 1 minute
python event_replayer.py long_session.jsonl --speed 60.0
```

## Editing Event Streams

Event files use JSON Lines format where each line is a complete event. This makes them easy to edit:

### Common Edits

1. **Change timing**: Modify `relative_time` values
2. **Alter coordinates**: Edit RA/DEC values in property updates
3. **Add errors**: Insert error messages or connection failures
4. **Remove devices**: Delete all events for a specific device

### Example: Speed up all events by 2x

```bash
# Use sed to halve all relative_time values
sed 's/"relative_time": *\([0-9.]*\)/"relative_time": \1/2/g' events.jsonl > fast_events.jsonl
```

### Example: Change telescope coordinates

Edit the file and find lines like:
```json
{"event_type": "update_property", "data": {"name": "EQUATORIAL_EOD_COORD", ...}}
```

Change the RA/DEC widget values to your desired coordinates.

## Integration with PiFinder

This system can be integrated with PiFinder's mount control for testing:

```python
# Modern pytest-based testing (recommended)
from indi_tools.testing import test_client, basic_telescope_scenario, event_replayer

def test_pifinder_mount_control(basic_telescope_scenario, event_replayer):
    mount = MountControlIndi()
    replayer = event_replayer(basic_telescope_scenario, mount)
    replayer.start_playback(blocking=True)

    # Test mount control functionality
    assert mount.is_connected()

# Legacy integration approach
from indi_tools.event_replayer import IndiEventReplayer

class MountControlIndi(MountControlBase):
    def __init__(self, mock_events=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if mock_events:
            # Use mock events instead of real server
            self.replayer = IndiEventReplayer(mock_events, self)
            self.replayer.start_playback()
        else:
            # Connect to real INDI server
            self.client = PiFinderIndiClient()
            # ... normal connection code ...
```

## Troubleshooting

### Common Issues

1. **"Cannot connect to INDI server"**
   - Make sure indiserver is running: `ps aux | grep indiserver`
   - Check the correct host/port
   - Verify firewall settings

2. **"Invalid JSON" errors**
   - Validate your edited files: `python -m json.tool < events.jsonl`
   - Check for missing commas or quotes after editing

3. **"Events not replaying correctly"**
   - Verify event order (should be sorted by `relative_time`)
   - Check that device names match between events
   - Ensure property types are consistent

4. **Performance issues with large files**
   - Filter events by device or type
   - Split large recordings into smaller segments
   - Use faster playback speeds for quick testing

### Debugging

Enable verbose logging for detailed information:

```bash
python event_recorder.py --verbose
python event_replayer.py events.jsonl --verbose
python test_recording_replay.py --mode test --verbose
```

## Advanced Usage

### Custom Event Processing

Create your own event processors:

```python
class CustomEventProcessor:
    def process_events(self, events):
        # Filter, modify, or analyze events
        for event in events:
            if event['event_type'] == 'update_property':
                # Custom processing
                pass
        return events

# Use with replayer
replayer = IndiEventReplayer("events.jsonl", client)
processor = CustomEventProcessor()
# replayer.events = processor.process_events(replayer.events)
```

### Multi-Device Scenarios

Record and replay complex multi-device setups:

```bash
# Start multiple INDI devices
indiserver indi_simulator_telescope indi_simulator_ccd indi_simulator_wheel indi_simulator_focus

# Record the complete setup
python event_recorder.py --output multi_device.jsonl --duration 120
```

### Event Analysis

Analyze recorded events for debugging:

```python
import json

def analyze_events(filename):
    events = []
    with open(filename) as f:
        for line in f:
            events.append(json.loads(line))

    # Analyze event patterns
    device_events = {}
    for event in events:
        if 'device_name' in event.get('data', {}):
            device = event['data']['device_name']
            if device not in device_events:
                device_events[device] = []
            device_events[device].append(event)

    # Report statistics
    for device, events in device_events.items():
        print(f"{device}: {len(events)} events")

analyze_events("my_session.jsonl")
```

## Contributing

When adding new features:

1. Update the event format documentation if adding new event types
2. Add test cases to the test suite
3. Update this README with new usage examples
4. Ensure backward compatibility with existing event files