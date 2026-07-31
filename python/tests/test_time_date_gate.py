"""Unit tests for the Set Time/Date self-gate (UITimeEntry / UIDateEntry).

Manual time/date entry is interpreted in the observer's local timezone, which
only exists once a location fix is present. Rather than hard-blocking entry from
the menu, each screen self-gates (see ADR 0019): the user may open the screen,
but the entry boxes and the set_time / set_datetime callbacks stay inert -- and
a "set location first" notice is shown -- until a fix locks; the user backs out
with LEFT/Cancel. These tests drive the modules directly in the locked and
unlocked states, asserting the gate logic (key suppression, callback
suppression, live predicate). Full-screen rendering in both states is covered by
the cold/warm crash-smoke in test_ui_modules.py.
"""

import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import PiFinder.i18n  # noqa: F401  installs the _() gettext builtin
from PiFinder.displays import get_display
from PiFinder.state import Location
from PiFinder.ui import callbacks
from PiFinder.ui.dateentry import UIDateEntry
from PiFinder.ui.timeentry import UITimeEntry

pytestmark = pytest.mark.unit


def _make_shared_state(location: Location):
    """A stub shared_state exposing just what the entry modules touch."""
    return SimpleNamespace(
        ui_state=lambda: MagicMock(),
        location=lambda: location,
        local_datetime=lambda: None,  # UIDateEntry pre-fills from this
        set_screen=lambda *a, **k: None,
    )


def _build(module_cls, location: Location):
    """Construct a real entry module on a headless display with a stub state."""
    display = get_display("headless")
    return module_cls(
        display,
        None,  # camera_image
        _make_shared_state(location),
        {},  # command_queues
        MagicMock(),  # config_object
        MagicMock(),  # catalogs
        item_definition={"custom_callback": MagicMock()},
        add_to_stack=MagicMock(),
        remove_from_stack=MagicMock(),
    )


_LOCKED = Location(lock=True, timezone="America/New_York")
_UNLOCKED = Location(lock=False)


# --------------------------------------------------------------------------- #
# UITimeEntry
# --------------------------------------------------------------------------- #


def test_time_entry_unlocked_is_inert():
    """No location lock -> digits ignored, RIGHT doesn't chain, no set_time."""
    module = _build(UITimeEntry, _UNLOCKED)

    assert module._location_locked() is False

    module.key_number(5)
    assert module.boxes == ["", "", ""]  # entry suppressed

    assert module.key_right() is False
    module.remove_from_stack.assert_not_called()  # no chain to date entry
    module.add_to_stack.assert_not_called()

    module.inactive()
    module.custom_callback.assert_not_called()  # set_time suppressed


def test_time_entry_locked_accepts_entry_and_fires_callback():
    """With a lock -> digits land in the boxes and set_time fires on exit."""
    module = _build(UITimeEntry, _LOCKED)

    assert module._location_locked() is True

    module.key_number(1)
    module.key_number(2)
    assert module.boxes[0] == "12"

    module.inactive()
    module.custom_callback.assert_called_once_with(module, "12:00:00")


def test_time_entry_gate_message_renders():
    """The base gate helper draws without error on a real headless display."""
    module = _build(UITimeEntry, _UNLOCKED)
    module.draw_gate_message("Set location\nfirst")  # must not raise


def _drawn_text(module):
    """Run draw_local_time_note against a recording draw, return the strings."""
    module.draw = MagicMock()
    module.draw_local_time_note()  # must not raise
    return [call.args[1] for call in module.draw.text.call_args_list]


def test_time_entry_shows_utc_when_the_fix_has_no_resolvable_timezone():
    """A lock without a resolvable zone must still name the zone in use.

    Location.timezone is Optional -- timezone_at() returns None for
    coordinates it cannot place. set_time reads the entry as UTC in that case,
    so the note says UTC; leaving the line blank would hide which zone the
    user's digits are being interpreted against.
    """
    assert "UTC" in _drawn_text(_build(UITimeEntry, Location(lock=True, timezone=None)))

    # and a zone that did resolve is still shown as-is
    assert "America/New_York" in _drawn_text(_build(UITimeEntry, _LOCKED))


def test_set_time_survives_a_fix_with_no_resolvable_timezone():
    """The commit path must tolerate what the screen renders.

    _location_locked() gates on the fix alone, so a lock whose zone did not
    resolve reaches set_time on the way out of the screen. pytz.timezone(None)
    raises UnknownTimeZoneError, which would surface as a crash on commit --
    the entry is read as UTC instead, matching what the note now shows.
    """
    gps_queue = MagicMock()
    ui_module = MagicMock()
    ui_module.command_queues = {"gps": gps_queue}
    ui_module.shared_state.location.return_value = Location(lock=True, timezone=None)
    ui_module.item_definition = {"time_str": "21:30:00"}

    callbacks.set_time(ui_module, "21:30:00")  # must not raise
    callbacks.set_datetime(ui_module, "2026-07-30")  # must not raise

    pushed = [call.args[0] for call in gps_queue.put.call_args_list]
    assert [name for name, _payload in pushed] == ["time_force", "time_force"]
    assert [str(payload["time"].tzinfo) for _name, payload in pushed] == ["UTC", "UTC"]


def test_enter_local_time_is_an_extractable_literal():
    """The note must stay a literal so Babel keeps it in the catalogs.

    Passing a variable to _() extracts nothing, which silently obsoletes the
    msgid on the next extract run and drops every existing translation.
    """
    source = Path(inspect.getfile(UITimeEntry)).read_text()

    assert '_("Enter Local Time")' in source


# --------------------------------------------------------------------------- #
# UIDateEntry (symmetric guard -- reached only via the time screen today, but
# self-gates on the same precondition for correctness if ever surfaced directly)
# --------------------------------------------------------------------------- #


def test_date_entry_unlocked_is_inert():
    """No location lock -> digits ignored, no set_datetime even if confirmed."""
    module = _build(UIDateEntry, _UNLOCKED)

    assert module._location_locked() is False

    module.key_number(5)
    assert module.boxes == ["", "", ""]  # entry suppressed

    module._confirmed = True
    module.inactive()
    module.custom_callback.assert_not_called()  # set_datetime suppressed


def test_date_entry_locked_accepts_entry_and_fires_callback():
    """With a lock -> digits land and set_datetime fires when confirmed."""
    module = _build(UIDateEntry, _LOCKED)

    assert module._location_locked() is True

    for digit in (2, 0, 2, 4):
        module.key_number(digit)
    assert module.boxes[0] == "2024"

    module._confirmed = True
    module.inactive()
    module.custom_callback.assert_called_once()
