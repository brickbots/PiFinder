#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Integration test for PiFinder menu system.

This test launches the full PiFinder application with the automated menu test
keyboard interface to verify that all menu items can be navigated and accessed
without errors.
"""

import pytest
import subprocess
import sys
import logging
from pathlib import Path


@pytest.mark.integration
def test_menu_system_integration():
    """
    Integration test that runs the full PiFinder application with the automated
    menu test keyboard interface.

    This test:
    1. Launches PiFinder with fake hardware, null display, and menutest keyboard
    2. Waits for the automated menu traversal to complete
    3. Verifies the application exits cleanly
    4. Checks that no fatal errors occurred during the test

    The test uses a timeout to prevent hanging and validates that the menu
    system can handle automated navigation through all menu items.
    """
    # Set up test parameters
    timeout_seconds = 300  # 5 minutes should be enough for menu traversal

    # Command to run PiFinder with test configuration
    cmd = [
        sys.executable,
        "-m",
        "PiFinder.main",
        "--fakehardware",  # Use fake GPS/IMU hardware
        "--camera",
        "debug",  # Use debug camera (no real camera needed)
        "--keyboard",
        "menutest",  # Use automated menu test keyboard
        "--display",
        "null",  # Use null display (no GUI)
        "--verbose",  # Enable verbose logging for debugging
    ]

    logging.info(f"Starting menu integration test with command: {' '.join(cmd)}")

    try:
        # Run PiFinder with automated menu testing
        result = subprocess.run(
            cmd,
            timeout=timeout_seconds,
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent,  # Run from python/ directory
        )

        # Check that the process completed successfully
        assert result.returncode == 0, f"PiFinder exited with code {result.returncode}"

        # Verify that the menu test completed successfully
        stdout_lower = result.stdout.lower()
        stderr_lower = result.stderr.lower()

        # Check for test completion indicators
        test_completed = any(
            [
                "test completed successfully" in stdout_lower,
                "menu system test completed successfully" in stdout_lower,
                "total ui leaf nodes visited" in stdout_lower,
            ]
        )

        assert test_completed, "Menu test did not complete successfully"

        # Check for critical errors that would indicate problems
        critical_errors = [
            "traceback",
            "error during menu test",
            "failed to",
            "exception in main",
        ]

        has_critical_error = any(
            [
                error in stdout_lower or error in stderr_lower
                for error in critical_errors
            ]
        )

        assert not has_critical_error, f"Critical errors detected in output:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"

        # Log success information
        logging.info("Menu integration test completed successfully")

        # Extract and log visited paths for verification
        if "visited ui leaf nodes:" in stdout_lower:
            lines = result.stdout.split("\n")
            visited_section = False
            visited_count = 0

            for line in lines:
                if "visited ui leaf nodes:" in line.lower():
                    visited_section = True
                    continue
                elif visited_section and line.strip().startswith("✓"):
                    visited_count += 1
                elif (
                    visited_section
                    and not line.strip().startswith("✓")
                    and line.strip()
                ):
                    # End of visited section
                    break

            logging.info(f"Successfully visited {visited_count} UI leaf nodes")
            assert visited_count > 0, "No UI leaf nodes were visited during the test"

    except subprocess.TimeoutExpired:
        pytest.fail(f"Menu integration test timed out after {timeout_seconds} seconds")

    except Exception as e:
        pytest.fail(f"Menu integration test failed with exception: {e}")


@pytest.mark.integration
def test_menu_test_keyboard_import():
    """
    Simple test to verify that the menu test keyboard module can be imported
    and instantiated without errors when the full PiFinder environment is available.
    """
    try:
        # This import will only work in the context where PiFinder's i18n is initialized
        # but we can at least verify the module structure is correct
        from PiFinder.keyboard_menutest import KeyboardMenuTest

        # Test instantiation without queue (won't send keys)
        keyboard = KeyboardMenuTest(q=None, keystroke_delay=0.01)

        # Verify expected attributes exist
        assert hasattr(keyboard, "TEST_COMPLETE")
        assert hasattr(keyboard, "visited_paths")
        assert hasattr(keyboard, "skipped_callbacks")
        assert keyboard.TEST_COMPLETE == 999

        logging.info("Menu test keyboard module imported and instantiated successfully")

    except ImportError as e:
        # This is expected if we're not in a full PiFinder environment
        # but the test framework should handle this gracefully
        pytest.skip(f"Cannot import menu test keyboard in this environment: {e}")


if __name__ == "__main__":
    # Allow running this test directly for debugging
    pytest.main([__file__, "-v", "-s"])
