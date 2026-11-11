"""[kind, text] console messages from worker processes reach the screen."""

from unittest.mock import Mock

import pytest

from PiFinder import main

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "message, seconds",
    [
        (["WARNING", "Goto failed!"], 3.0),
        (("MOUNT", "Slewing"), 1.5),
        (["X", "y"], 2.0),
    ],
)
def test_status_message_shows_and_logs(message, seconds):
    menu_manager = Mock()
    console = Mock()
    main.show_status_message(menu_manager, console, message)
    menu_manager.message.assert_called_once_with(message[1], seconds)
    console.write.assert_called_once_with(f"{message[0]}: {message[1]}")
