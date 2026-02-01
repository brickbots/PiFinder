"""
INDI Event System Testing Framework

This package provides comprehensive testing utilities for INDI clients using
event recording and replay functionality with pytest integration.
"""

# Import main testing utilities for easy access
try:
    # Try relative import first (when imported as a package)
    from .pytest_fixtures import (
        TestIndiClient,
        EventDataManager,
        test_client,
        event_replayer,
        event_data_manager,
        basic_telescope_scenario,
        coordinate_scenario,
        wait_for_events,
        assert_event_sequence,
        pytest_markers,
    )
except ImportError:
    # Fallback to direct import (when running pytest from different directory)
    try:
        from pytest_fixtures import (
            TestIndiClient,
            EventDataManager,
            test_client,
            event_replayer,
            event_data_manager,
            basic_telescope_scenario,
            coordinate_scenario,
            wait_for_events,
            assert_event_sequence,
            pytest_markers,
        )
    except ImportError:
        # If both fail, we're probably being imported during pytest discovery
        # The fixtures will still be available via conftest.py
        pass

__version__ = "1.0.0"

# Only include in __all__ if imports succeeded
__all__ = []
if "TestIndiClient" in locals():
    __all__ = [
        "TestIndiClient",
        "EventDataManager",
        "test_client",
        "event_replayer",
        "event_data_manager",
        "basic_telescope_scenario",
        "coordinate_scenario",
        "wait_for_events",
        "assert_event_sequence",
        "pytest_markers",
    ]
