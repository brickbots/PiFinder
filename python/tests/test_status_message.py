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
        (["CONFIRM", "Seen +7.0s"], 2.0),
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


def test_three_line_message_gets_a_larger_box_and_more_time():
    menu_manager = Mock()
    screen = Mock(shows_mount_status=False)
    screen.display_class.resX = 128
    screen.display_class.resY = 128
    menu_manager.stack = [screen]
    text = "Next pass 21:43\nin 2h05\nmax 38° SE"
    main.show_status_message(menu_manager, Mock(), ["WARNING", text])
    menu_manager.message.assert_called_once_with(
        text, main.LONG_MESSAGE_SECONDS, size=(5, 34, 123, 94)
    )


def test_mount_page_shows_the_seen_confirmation():
    """The "I see it" press changes only the status band of the mount page.
    The CONFIRM message shows on the mount page and on the other screens."""
    for on_mount_page in (True, False):
        menu_manager = Mock()
        menu_manager.stack = [Mock(shows_mount_status=on_mount_page)]
        main.show_status_message(menu_manager, Mock(), ["CONFIRM", "Seen +7.0s"])
        menu_manager.message.assert_called_once_with("Seen +7.0s", 2.0)
