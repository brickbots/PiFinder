"""Unit tests for the Set Time/Date location gate (callbacks.enter_time_entry).

Manual time entry is interpreted in the observer's local timezone, which is only
known once a location fix exists. enter_time_entry therefore refuses to open
UITimeEntry until shared_state has a locked location, bouncing the user with a
hint instead. See PR #508 follow-up.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import PiFinder.i18n  # noqa: F401  installs the _() gettext builtin
from PiFinder.state import Location
from PiFinder.ui import callbacks
from PiFinder.ui.timeentry import UITimeEntry


def _make_ui_module(location: Location):
    """A stub UIModule exposing just what enter_time_entry touches."""
    shared_state = SimpleNamespace(location=lambda: location)
    return SimpleNamespace(
        shared_state=shared_state,
        message=MagicMock(),
        add_to_stack=MagicMock(),
    )


@pytest.mark.unit
def test_enter_time_entry_blocked_without_location_lock():
    """No location lock -> show a hint, do not push the entry screen."""
    ui_module = _make_ui_module(Location(lock=False))

    callbacks.enter_time_entry(ui_module)

    ui_module.add_to_stack.assert_not_called()
    ui_module.message.assert_called_once()


@pytest.mark.unit
def test_enter_time_entry_opens_when_location_locked():
    """With a location lock -> push UITimeEntry wired to set_time, no hint."""
    ui_module = _make_ui_module(Location(lock=True, timezone="America/New_York"))

    callbacks.enter_time_entry(ui_module)

    ui_module.message.assert_not_called()
    ui_module.add_to_stack.assert_called_once()

    pushed = ui_module.add_to_stack.call_args.args[0]
    assert pushed["class"] is UITimeEntry
    assert pushed["custom_callback"] is callbacks.set_time
