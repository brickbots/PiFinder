"""
Pytest configuration for INDI event system tests.

This file provides pytest configuration and setup for testing
INDI clients with the event recording and replay system.
"""

import pytest
import sys
import os

# Add directories to Python path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)
sys.path.insert(0, current_dir)

# Import all fixtures to make them available to tests
try:
    # Try importing from current directory first
    import pytest_fixtures  # noqa: F401

    # Import specific fixtures explicitly (needed for pytest fixture discovery)
    from pytest_fixtures import (  # noqa: F401
        indi_client,
        event_recorder,
        mock_indi_server,
        sample_events,
        test_device,
    )
except ImportError:
    # If that fails, try relative import
    try:
        from . import pytest_fixtures  # noqa: F401
        from .pytest_fixtures import (  # noqa: F401
            indi_client,
            event_recorder,
            mock_indi_server,
            sample_events,
            test_device,
        )
    except ImportError:
        # If both fail, something is wrong with the setup
        import pytest_fixtures as pytest_fixtures_module

        # Import everything from pytest_fixtures manually
        for name in dir(pytest_fixtures_module):
            if not name.startswith("_"):
                globals()[name] = getattr(pytest_fixtures_module, name)


def pytest_configure(config):
    """Configure pytest markers and settings."""
    # Register custom markers
    config.addinivalue_line("markers", "unit: Unit tests - fast, isolated tests")
    config.addinivalue_line(
        "markers", "integration: Integration tests - test component interactions"
    )
    config.addinivalue_line(
        "markers", "slow: Slow tests - tests that take significant time"
    )
    config.addinivalue_line(
        "markers", "replay: Event replay tests - tests using recorded events"
    )
    config.addinivalue_line(
        "markers", "recording: Event recording tests - tests that record live events"
    )
    config.addinivalue_line(
        "markers", "indi: INDI-related tests - tests specific to INDI protocol"
    )


def pytest_collection_modifyitems(config, items):
    """Modify test collection to add markers based on test names."""
    for item in items:
        # Auto-mark tests based on naming conventions
        if "slow" in item.name or "timing" in item.name:
            item.add_marker(pytest.mark.slow)

        if "replay" in item.name:
            item.add_marker(pytest.mark.replay)

        if "integration" in item.name:
            item.add_marker(pytest.mark.integration)

        if "unit" in item.name or item.parent.name.startswith("test_unit"):
            item.add_marker(pytest.mark.unit)


def pytest_runtest_setup(item):
    """Setup for each test run."""
    # Skip slow tests by default unless explicitly requested
    if "slow" in [mark.name for mark in item.iter_markers()]:
        if not item.config.getoption("--runslow", default=False):
            pytest.skip("need --runslow option to run slow tests")


def pytest_addoption(parser):
    """Add custom command line options."""
    parser.addoption(
        "--runslow", action="store_true", default=False, help="run slow tests"
    )
    parser.addoption(
        "--live-indi",
        action="store_true",
        default=False,
        help="run tests that require a live INDI server",
    )


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Setup test environment once per session."""
    # Create test data directory if it doesn't exist
    test_data_dir = os.path.join(current_dir, "test_data")
    os.makedirs(test_data_dir, exist_ok=True)

    # Cleanup any leftover test files from previous runs
    import glob

    for temp_file in glob.glob(os.path.join(test_data_dir, "temp_*.jsonl")):
        try:
            os.unlink(temp_file)
        except OSError:
            pass

    yield

    # Session cleanup
    # Remove temporary test files
    for temp_file in glob.glob(os.path.join(test_data_dir, "temp_*.jsonl")):
        try:
            os.unlink(temp_file)
        except OSError:
            pass


# Pytest plugin hooks for better test output
def pytest_runtest_logstart(nodeid, location):
    """Log test start."""
    pass  # Could add custom logging here


def pytest_runtest_logfinish(nodeid, location):
    """Log test finish."""
    pass  # Could add custom logging here


# Custom pytest report
def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Add custom terminal summary."""
    if hasattr(terminalreporter, "stats"):
        # Count tests by marker
        replay_tests = len(
            [
                item
                for item in terminalreporter.stats.get("passed", [])
                if hasattr(item, "item")
                and "replay" in [m.name for m in item.item.iter_markers()]
            ]
        )

        if replay_tests > 0:
            terminalreporter.write_sep("=", "INDI Event Replay Summary")
            terminalreporter.write_line(f"Event replay tests run: {replay_tests}")


# Error handling for missing dependencies
def pytest_sessionstart(session):
    """Check for required dependencies at session start."""
    try:
        import importlib.util

        if importlib.util.find_spec("PyIndi") is None:
            raise ImportError
    except ImportError:
        pytest.exit(
            "PyIndi library not found. Please install PyIndi to run INDI tests."
        )

    # Check if test data directory is writable
    test_data_dir = os.path.join(current_dir, "test_data")
    try:
        os.makedirs(test_data_dir, exist_ok=True)
        test_file = os.path.join(test_data_dir, "test_write.tmp")
        with open(test_file, "w") as f:
            f.write("test")
        os.unlink(test_file)
    except Exception as e:
        pytest.exit(f"Cannot write to test data directory {test_data_dir}: {e}")


# Fixtures for test isolation
@pytest.fixture(autouse=True)
def isolate_tests():
    """Ensure tests are isolated from each other."""
    # This fixture runs before and after each test
    yield
    # Could add cleanup code here if needed


# Timeout fixture for preventing hanging tests
@pytest.fixture(scope="function")
def test_timeout():
    """Provide a reasonable timeout for tests."""
    return 30.0  # seconds
