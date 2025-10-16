# INDI Tools Directory Structure

This document describes the organization of the INDI Tools directory after restructuring.

## Directory Structure

```
indi_tools/
├── __init__.py                     # Main package initialization
├── README.md                       # Main documentation
├── EVENT_FORMAT.md                 # Event format specification
├── STRUCTURE.md                    # This file
│
├── event_recorder.py               # Core event recording functionality
├── event_replayer.py               # Core event replay functionality
├── usage_example.py                # Usage examples and demonstrations
│
├── monitor.py                      # INDI monitoring utilities
├── pifinder_to_indi_bridge.py     # PiFinder-INDI bridge
├── pyindi.py                       # Basic PyIndi example
│
├── test_recording_replay.py        # Legacy test script (standalone)
│
└── testing/                        # Modern pytest-based testing framework
    ├── __init__.py                 # Testing package initialization
    ├── conftest.py                 # Pytest configuration
    ├── pytest_fixtures.py         # Core pytest fixtures and utilities
    │
    ├── test_examples.py            # Example test cases
    ├── test_recording_replay.py    # Legacy tests (pytest-compatible)
    │
    ├── test_data/                  # Test scenario data
    │   ├── basic_telescope.jsonl   # Basic telescope scenario (auto-generated)
    │   └── coordinate_updates.jsonl # Coordinate update scenario (auto-generated)
    │
    ├── PYTEST_GUIDE.md             # Comprehensive pytest usage guide
    └── PYTEST_USAGE_SUMMARY.md     # Quick reference for pytest usage
```

## Component Overview

### Core Components

#### Event System
- **`event_recorder.py`** - Records INDI events from live servers to JSON Lines files
- **`event_replayer.py`** - Replays recorded events to test INDI clients
- **`EVENT_FORMAT.md`** - Complete specification of the event format

#### Testing Framework (`testing/`)
- **`pytest_fixtures.py`** - Comprehensive pytest fixtures for INDI testing
- **`conftest.py`** - Pytest configuration and test environment setup
- **`test_examples.py`** - Example test cases demonstrating various patterns
- **`test_data/`** - Pre-built test scenarios and data files

#### Documentation
- **`README.md`** - Main documentation and quick start guide
- **`PYTEST_GUIDE.md`** - Comprehensive pytest integration guide
- **`PYTEST_USAGE_SUMMARY.md`** - Quick reference for daily use

#### Utilities and Examples
- **`usage_example.py`** - Interactive examples and demonstrations
- **`monitor.py`** - INDI monitoring and debugging utilities
- **`pifinder_to_indi_bridge.py`** - Bridge between PiFinder and INDI
- **`pyindi.py`** - Basic PyIndi usage example

## Usage Patterns

### Quick Testing (Modern Approach)
```bash
cd indi_tools/testing
pytest -v                    # Run all tests
pytest -m unit              # Run unit tests only
pytest -m replay            # Run replay tests only
```

### Event Recording
```bash
cd indi_tools
python event_recorder.py --duration 30 --output my_session.jsonl
```

### Event Replay
```bash
cd indi_tools
python event_replayer.py my_session.jsonl --speed 2.0
```

### Integration with Your Tests
```python
# In your test files
from indi_tools.testing import (
    test_client, event_replayer, basic_telescope_scenario
)

def test_my_client(test_client, basic_telescope_scenario, event_replayer):
    replayer = event_replayer(basic_telescope_scenario, test_client)
    replayer.start_playback(blocking=True)

    # Your assertions...
```

## Migration Notes

### From indi_poc to indi_tools
- The directory `indi_poc` has been renamed to `indi_tools`
- All testing framework components moved to `testing/` subdirectory
- Import paths updated:
  - Old: `from indi_poc.event_recorder import IndiEventRecorder`
  - New: `from indi_tools.event_recorder import IndiEventRecorder`
  - Testing: `from indi_tools.testing import test_client, event_replayer`

### Backward Compatibility
- Legacy test script `test_recording_replay.py` remains at the root level
- All original functionality preserved
- New pytest framework provides additional capabilities

## Development Workflow

### For INDI Client Development
1. Record events from your real setup: `python event_recorder.py`
2. Create tests using the recorded events
3. Use pytest fixtures for easy test setup
4. Run tests during development: `pytest -m unit`

### For Test Scenario Creation
1. Start with pre-built scenarios in `testing/test_data/`
2. Record custom scenarios for specific test cases
3. Edit scenarios as needed using any text editor
4. Share scenarios with team via version control

### For CI/CD Integration
```bash
# In your CI pipeline
cd python
source .venv/bin/activate
cd indi_tools/testing
pytest -m "unit or replay" --tb=short
```

## Best Practices

1. **Use pytest framework** for new tests (modern approach)
2. **Keep test scenarios** in version control for reproducibility
3. **Use fast replay speeds** (5x-10x) for quick testing
4. **Categorize tests** with appropriate pytest markers
5. **Document complex scenarios** for team understanding

## File Relationships

```
Event Recording Flow:
event_recorder.py → *.jsonl files → event_replayer.py → Your INDI Client

Testing Flow:
pytest_fixtures.py → test_examples.py → Your Test Results
                  ↗
test_data/*.jsonl ↗

Integration Flow:
Your Tests → testing/pytest_fixtures.py → event_replayer.py → Your INDI Client
```

This structure provides a clean separation between core INDI tools and the testing framework while maintaining backward compatibility and ease of use.