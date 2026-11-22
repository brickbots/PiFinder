"""Unit tests for recovery mode: the app wiring (PiFinder.recovery) and the
recovery behaviour of the Software screen (ADR 0038)."""

from unittest.mock import MagicMock, patch

import pytest

# Installs the _() gettext builtin the UI modules rely on; must precede ui imports.
import PiFinder.i18n  # noqa: F401
from PiFinder import recovery
from PiFinder.config import Config
from PiFinder.displays import get_display
from PiFinder.keyboard_interface import KeyboardInterface as K
from PiFinder.ui.base import UIModule
from PiFinder.ui.software import UIReleaseNotes, UISoftware, _entry_row_parts

ROLLBACK = [
    {
        "ref": "/nix/store/aaa-nixos-system-pifinder-26.05",
        "label": "v3.1.0",
        "version": "v3.1.0",
        "notes": None,
        "subtitle": "gen 7 · 01 Nov 20:00",
        "channel": "rollback",
        "confirmed": True,
    },
    {
        "ref": "/nix/store/bbb-nixos-system-pifinder-26.05",
        "label": "PR#140-abc1234",
        "version": "PR#140-abc1234",
        "notes": None,
        "subtitle": "gen 6 · 30 Oct 19:00",
        "channel": "rollback",
        "confirmed": False,
    },
]


@pytest.fixture
def screens():
    """Recovery screens on a headless display, with no network and a
    fixed rollback list."""
    with (
        patch.object(UISoftware, "_start_refresh") as refresh,
        patch("PiFinder.ui.software._load_cached_manifest", return_value=None),
        patch.object(UISoftware, "_list_rollback_targets", return_value=ROLLBACK),
    ):
        cfg = MagicMock(spec=Config)
        cfg.get_option.side_effect = lambda _name, default=None: default
        result = recovery.RecoveryScreens(
            get_display("headless"), recovery.RecoveryState(), cfg
        )
        result.refresh = refresh
        yield result


@pytest.mark.unit
def test_the_software_screen_is_the_whole_ui(screens):
    assert len(screens.stack) == 1
    software = screens.stack[0]
    assert isinstance(software, UISoftware)
    assert software._recovery is True
    assert software.title == "Recovery"


@pytest.mark.unit
def test_left_on_the_software_screen_starts_it_again(screens):
    software = screens.stack[0]
    software._phase = "failed"
    screens.key(K.LEFT)
    assert screens.stack == [software]
    assert software._phase == "loading"


@pytest.mark.unit
def test_cancel_after_a_failed_install_returns_to_the_list(screens):
    software = screens.stack[0]
    software._phase = "failed"
    software._fail_option = "Cancel"
    screens.key(K.RIGHT)
    assert screens.stack == [software]
    assert software._phase != "failed"


@pytest.mark.unit
def test_release_notes_open_on_top_and_left_closes_them(screens):
    screens.add_to_stack({"class": UIReleaseNotes, "notes_text": "# Notes"})
    assert isinstance(screens.stack[-1], UIReleaseNotes)
    screens.key(K.LEFT)
    assert len(screens.stack) == 1


@pytest.mark.unit
def test_keys_go_to_the_screen_on_top(screens):
    top = MagicMock()
    screens.stack.append(top)
    for keycode, handler in [
        (K.UP, top.key_up),
        (K.DOWN, top.key_down),
        (K.RIGHT, top.key_right),
        (K.SQUARE, top.key_square),
        (K.PLUS, top.key_plus),
        (K.MINUS, top.key_minus),
    ]:
        screens.key(keycode)
        handler.assert_called_once()
    screens.key(5)
    top.key_number.assert_called_once_with(5)


@pytest.mark.unit
def test_update_sends_the_frame_to_the_display(screens):
    screens.display_class.device.display = MagicMock()
    with patch.object(UIModule, "message_until", 0.0):
        screens.update()
    screens.display_class.device.display.assert_called_once()
    assert screens.shared_state.screen() is not None


@pytest.mark.unit
def test_recovery_state_holds_the_battery():
    state = recovery.RecoveryState()
    assert state.battery() is None
    battery = MagicMock(on_external_power=False)
    state.set_battery(battery)
    assert state.battery() is battery
    state.ui_state().set_message_timeout(1.0)


@pytest.mark.unit
def test_read_battery_stops_without_a_charger():
    state = recovery.RecoveryState()
    with patch.object(recovery, "BQ25895", side_effect=OSError("no i2c")):
        recovery.read_battery(state, MagicMock())
    assert state.battery() is None


@pytest.mark.unit
def test_keyboard_modules_cover_the_choices():
    assert set(recovery.KEYBOARD_MODULES) == {"pi", "local", "none"}
    assert callable(recovery.keyboard_function("none"))


# --- The Software screen in recovery mode ---------------------------------


def _software(recovery_mode: bool, wifi: str) -> UISoftware:
    ui = UISoftware.__new__(UISoftware)
    ui._recovery = recovery_mode
    ui._wifi_mode = wifi
    ui.config_object = MagicMock()
    ui.config_object.get_option.return_value = False
    ui._channel_names = []
    ui._channel_index = 0
    ui._list_index = 0
    ui._scroll_offset = 0
    ui._software_version = "3.1.1"
    ui._refresh_thread = None
    return ui


@pytest.mark.unit
def test_recovery_without_wifi_shows_the_rollback_list_alone():
    ui = _software(recovery_mode=True, wifi="AP")
    with (
        patch.object(UISoftware, "_list_rollback_targets", return_value=ROLLBACK),
        patch.object(UISoftware, "_start_refresh") as refresh,
    ):
        ui.active()
    assert ui._local_only is True
    assert ui._phase == "browse"
    assert ui._channel_names == ["rollback"]
    assert ui._version_list == ROLLBACK
    refresh.assert_not_called()


@pytest.mark.unit
def test_recovery_without_wifi_or_generations_shows_the_wifi_notice():
    ui = _software(recovery_mode=True, wifi="AP")
    with (
        patch.object(UISoftware, "_list_rollback_targets", return_value=[]),
        patch.object(UISoftware, "_start_refresh"),
        patch("PiFinder.ui.software._load_cached_manifest", return_value=None),
    ):
        ui.active()
    assert ui._local_only is False


@pytest.mark.unit
def test_normal_mode_without_wifi_keeps_the_wifi_notice():
    ui = _software(recovery_mode=False, wifi="AP")
    with (
        patch.object(UISoftware, "_list_rollback_targets", return_value=ROLLBACK),
        patch.object(UISoftware, "_start_refresh"),
        patch("PiFinder.ui.software._load_cached_manifest", return_value=None),
    ):
        ui.active()
    assert ui._local_only is False


@pytest.mark.unit
def test_square_does_not_fetch_in_the_local_list():
    ui = _software(recovery_mode=True, wifi="AP")
    ui._phase = "browse"
    ui._local_only = True
    with patch.object(UISoftware, "_start_refresh") as refresh:
        ui.key_square()
    refresh.assert_not_called()


@pytest.mark.unit
@pytest.mark.parametrize(
    "recovery_mode, first", [(True, "rollback"), (False, "stable")]
)
def test_rollback_comes_first_in_recovery(recovery_mode, first):
    ui = _software(recovery_mode=recovery_mode, wifi="Client")
    channels = {"stable": [{"label": "v3.2.0", "ref": "/nix/store/ccc"}], "beta": []}
    with (
        patch.object(UISoftware, "_list_rollback_targets", return_value=ROLLBACK),
        patch("PiFinder.ui.software._current_store_path", return_value=None),
    ):
        ui._apply_manifest(channels)
    assert ui._channel_names[0] == first
    assert set(ui._channel_names) == {"stable", "beta", "rollback"}


@pytest.mark.unit
def test_a_confirmed_generation_has_a_check_mark():
    prefix, text = _entry_row_parts(ROLLBACK[0])
    assert prefix == f"{UIModule._CHECKMARK} "
    assert text == "v3.1.0"
    assert _entry_row_parts(ROLLBACK[1]) == ("", "PR#140-abc1234")


@pytest.mark.unit
def test_a_rollback_pick_installs_the_generation():
    """The pick goes through the normal upgrade with the store path of the
    generation. The upgrade makes it the boot default (sticky)."""
    ui = _software(recovery_mode=True, wifi="AP")
    ui.shared_state = MagicMock()
    ui.shared_state.battery.return_value = None
    ui.clear_screen = MagicMock()
    ui._draw_upgrading = MagicMock()
    ui.screen_update = MagicMock()
    with (
        patch.object(UISoftware, "_list_rollback_targets", return_value=ROLLBACK),
        patch.object(UISoftware, "_start_refresh"),
    ):
        ui.active()
    ui.key_down()  # channel -> list
    ui.key_right()  # list -> confirm
    assert ui._confirm_options[0] == "Install"
    with patch("PiFinder.ui.software.sys_utils") as sys_utils:
        sys_utils.update_software.return_value = True
        ui.key_right()  # Install
    sys_utils.update_software.assert_called_once()
    kwargs = sys_utils.update_software.call_args.kwargs
    assert kwargs["ref"] == ROLLBACK[0]["ref"]
    assert kwargs["selection"]["channel"] == "rollback"
    assert ui._phase == "upgrading"
