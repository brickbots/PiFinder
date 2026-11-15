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
    menu_manager.stack = [Mock(shows_mount_status=False)]
    console = Mock()
    main.show_status_message(menu_manager, console, message)
    menu_manager.message.assert_called_once_with(message[1], seconds)
    console.write.assert_called_once_with(f"{message[0]}: {message[1]}")


def test_mount_page_hides_mount_progress_but_not_warnings():
    menu_manager = Mock()
    menu_manager.stack = [Mock(shows_mount_status=True)]
    console = Mock()
    main.show_status_message(menu_manager, console, ["MOUNT", "Slewing"])
    menu_manager.message.assert_not_called()
    console.write.assert_called_once_with("MOUNT: Slewing")
    main.show_status_message(menu_manager, console, ["WARNING", "Goto failed!"])
    menu_manager.message.assert_called_once_with("Goto failed!", 3.0)
