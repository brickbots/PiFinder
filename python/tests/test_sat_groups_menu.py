"""The device menu that selects the CelesTrak satellite groups.

The tests use a temporary data directory and a mock download. They use no
network and start no thread that sleeps.
"""

import subprocess
import sys
from types import SimpleNamespace
from unittest import mock

import pytest

# Installs the ``_()`` gettext builtin that PiFinder.ui modules rely on.
import PiFinder.i18n  # noqa: F401

from PiFinder import satellite_catalog, satellite_groups, satellites
from PiFinder.displays import get_display
from PiFinder.ui import menu_structure, sat_groups
from PiFinder.ui.base import UIModule
from PiFinder.ui.text_menu import UITextMenu
from satellite_helpers import make_old, seed_groups


pytestmark = pytest.mark.usefixtures("fresh_sat_messages")


@pytest.fixture(scope="module")
def display():
    return get_display("headless")


def _find_menu(node, name):
    if node.get("name") == name:
        return node
    for item in node.get("items", []):
        found = _find_menu(item, name)
        if found is not None:
            return found
    return None


def _make_menu(display, item_definition, config_object=None):
    return UITextMenu(
        display,
        None,
        mock.MagicMock(name="shared_state"),
        {},
        config_object or mock.MagicMock(name="config"),
        mock.MagicMock(name="catalogs"),
        item_definition=item_definition,
    )


def _group_menu(display):
    definition = _find_menu(menu_structure.pifinder_menu, "Sat groups")
    assert definition is not None
    return _make_menu(display, definition)


def _move_to(menu, group):
    # "Update now" is the first item, before the groups.
    menu._current_item_index = satellite_groups.CELESTRAK_GROUPS.index(group) + 1


def _messages(menu):
    """Show each waiting message, as the menu does on each frame."""
    shown = []
    with mock.patch.object(menu, "message") as message:
        while True:
            UIModule.message_until = 0.0
            before = message.call_count
            menu.update()
            if message.call_count == before:
                return shown
            shown.append(message.call_args.args[0])


@pytest.mark.unit
def test_menu_is_next_to_the_satellite_list():
    by_catalog = _find_menu(menu_structure.pifinder_menu, "By Catalog")
    satellites_menu = _find_menu(by_catalog, "Satellites...")
    names = [item["name"] for item in satellites_menu["items"]]
    assert names == ["Satellites", "Sat groups"]


@pytest.mark.unit
def test_menu_lists_every_group_with_a_mark_on_large_groups():
    definition = _find_menu(menu_structure.pifinder_menu, "Sat groups")
    items = definition["items"][1:]
    assert [item["value"] for item in items] == list(satellite_groups.CELESTRAK_GROUPS)
    labels = {item["value"]: item["name"] for item in items}
    assert labels["starlink"] == "Starlink*"
    assert labels["visual"] == "Brightest"
    assert len(set(labels.values())) == len(labels)
    for group in satellite_groups.AVAILABLE_GROUPS:
        assert labels[group.name].endswith("*") == group.large


@pytest.mark.unit
def test_satellites_module_re_exports_the_group_names():
    assert satellites.AVAILABLE_GROUPS is satellite_groups.AVAILABLE_GROUPS
    assert satellites.DEFAULT_GROUPS is satellite_groups.DEFAULT_GROUPS
    assert satellites.CelestrakGroup is satellite_groups.CelestrakGroup


@pytest.mark.unit
def test_menu_shows_the_stored_selection(display, sat_dir):
    satellites.set_group_enabled("visual", False, sat_dir)
    satellites.set_group_enabled("weather", True, sat_dir)
    menu = _group_menu(display)
    assert sorted(menu._selected_values) == ["stations", "weather"]
    # The menu has no "Select None" item: "Update now" and then the groups.
    assert menu._menu_items[:2] == ["Update now", "Brightest"]
    menu.update()


@pytest.mark.unit
def test_menu_without_a_stored_selection_shows_the_defaults(display, sat_dir):
    menu = _group_menu(display)
    assert sorted(menu._selected_values) == sorted(satellite_groups.DEFAULT_GROUPS)


@pytest.mark.unit
def test_menu_reads_the_selection_again_when_it_becomes_active(display, sat_dir):
    menu = _group_menu(display)
    satellites.set_group_enabled("geo", True, sat_dir)
    menu.active()
    assert "geo" in menu._selected_values


@pytest.mark.unit
def test_open_menu_follows_a_change_on_the_web_page(display, sat_dir):
    menu = _group_menu(display)
    assert "visual" in menu._selected_values
    # The web page disables the group while the menu is on the screen.
    satellites.set_group_enabled("visual", False, sat_dir)
    menu.update()
    assert "visual" not in menu._selected_values
    satellites.set_group_enabled("visual", True, sat_dir)
    menu.update()
    assert "visual" in menu._selected_values


@pytest.mark.unit
def test_toggle_uses_the_stored_state(display, sat_dir):
    seed_groups(sat_dir, ["visual"])
    menu = _group_menu(display)
    _move_to(menu, "visual")
    # The web page disables the group, and no frame is drawn before the key.
    satellites.set_group_enabled("visual", False, sat_dir)
    menu.key_right()
    assert "visual" in satellites.selected_groups(sat_dir)
    assert "visual" in menu._selected_values


@pytest.mark.unit
def test_toggle_stores_the_selection(display, sat_dir):
    seed_groups(sat_dir, ["visual"])
    menu = _group_menu(display)
    _move_to(menu, "visual")
    menu.key_right()
    assert "visual" not in satellites.selected_groups(sat_dir)
    assert "visual" not in menu._selected_values
    menu.key_right()
    assert "visual" in satellites.selected_groups(sat_dir)
    assert "visual" in menu._selected_values


@pytest.mark.unit
def test_deselect_downloads_nothing(display, sat_dir):
    menu = _group_menu(display)
    _move_to(menu, "visual")
    with mock.patch.object(satellites, "refresh_groups") as refresh:
        menu.key_right()
    assert sat_groups.downloads.thread is None
    refresh.assert_not_called()
    assert _messages(menu) == []


@pytest.mark.unit
@pytest.mark.parametrize(
    "group, messages",
    [("weather", []), ("starlink", ["Large group:\nslow passes"])],
)
def test_select_of_a_group_with_a_file_downloads_nothing(
    display, sat_dir, group, messages
):
    """A large group shows a message."""
    seed_groups(sat_dir, [group])
    menu = _group_menu(display)
    _move_to(menu, group)
    menu.key_right()
    assert sat_groups.downloads.thread is None
    assert _messages(menu) == messages


@pytest.mark.unit
def test_select_downloads_the_group_in_a_thread(display, sat_dir):
    result = satellites.GroupRefresh("downloaded", downloaded=("weather",))
    menu = _group_menu(display)
    _move_to(menu, "weather")
    with mock.patch.object(
        satellites, "refresh_groups", return_value=result
    ) as refresh:
        menu.key_right()
        sat_groups.downloads.thread.join(timeout=10)
    assert not sat_groups.downloads.thread.is_alive()
    refresh.assert_called_once()
    assert refresh.call_args.kwargs["force"] is True
    assert refresh.call_args.kwargs["groups"] == ("weather",)
    assert refresh.call_args.kwargs["directory"] == sat_dir
    assert _messages(menu) == ["Downloading\nWeather", "Downloaded\nWeather"]


@pytest.mark.unit
@pytest.mark.parametrize(
    "group, refresh, messages",
    [
        # A large group shows its message and the download messages.
        (
            "starlink",
            {"return_value": satellites.GroupRefresh("failed", failed=("starlink",))},
            [
                "Large group:\nslow passes",
                "Downloading\nStarlink*",
                "Download failed\nStarlink*",
            ],
        ),
        # An error in the download is a failed download.
        (
            "weather",
            {"side_effect": OSError("x")},
            ["Downloading\nWeather", "Download failed\nWeather"],
        ),
    ],
)
def test_failed_download_shows_failed(display, sat_dir, group, refresh, messages):
    menu = _group_menu(display)
    _move_to(menu, group)
    with mock.patch.object(satellites, "refresh_groups", **refresh):
        menu.key_right()
        sat_groups.downloads.thread.join(timeout=10)
    assert _messages(menu) == messages


@pytest.mark.unit
def test_a_message_waits_while_another_message_shows(display, sat_dir):
    menu = _group_menu(display)
    sat_groups.downloads.post("First")
    with mock.patch.object(menu, "message") as message:
        UIModule.message_until = 1e12
        menu.update()
        message.assert_not_called()


@pytest.mark.unit
@pytest.mark.parametrize(
    "result, text",
    [
        (satellites.GroupRefresh("downloaded"), "Downloaded"),
        (satellites.GroupRefresh("current"), "Up to date"),
        (satellites.GroupRefresh("too_soon", wait_seconds=200.0), "Wait 4 min"),
        (satellites.GroupRefresh("too_soon", wait_seconds=5.0), "Wait 1 min"),
        (satellites.GroupRefresh("too_soon", wait_seconds=3540.0), "Wait 59 min"),
        (satellites.GroupRefresh("too_soon", wait_seconds=3541.0), "Wait 1h00"),
        (satellites.GroupRefresh("too_soon", wait_seconds=3900.0), "Wait 1h05"),
        (satellites.GroupRefresh("too_soon", wait_seconds=6300.0), "Wait 1h45"),
        (satellites.GroupRefresh("too_soon", wait_seconds=7199.5), "Wait 2h00"),
        (satellites.GroupRefresh("busy"), "Download busy"),
        (satellites.GroupRefresh("failed"), "Download failed"),
        (None, "Download failed"),
    ],
)
def test_result_message(result, text):
    assert sat_groups.result_message(result) == text


@pytest.mark.unit
def test_wait_message_fits_a_device_line():
    # About 16 characters fit a line of the 128 px screen.
    for seconds in (1.0, 59 * 60.0, 3600.0, 7200.0, 12 * 3600.0):
        assert len(sat_groups.wait_message(seconds)) <= 16
    assert sat_groups.wait_message(12 * 3600.0) == "Wait 12h00"


@pytest.mark.unit
def test_downloads_run_one_at_a_time_in_order(sat_dir):
    downloads = sat_groups.GroupDownloads()
    calls = []

    def fake_refresh(now, force, directory, groups):
        calls.append(groups)
        return satellites.GroupRefresh("downloaded")

    with (
        mock.patch.object(satellites, "refresh_groups", side_effect=fake_refresh),
        mock.patch.object(sat_groups.threading, "Thread") as thread_class,
    ):
        downloads.request("weather", sat_dir)
        downloads.request("geo", sat_dir)
        downloads.request("weather", sat_dir)
        # One thread for the queue. Run its target here.
        assert thread_class.call_count == 1
        thread_class.call_args.kwargs["target"]()
    assert calls == [("weather",), ("geo",)]
    assert downloads.next_message() == "Downloaded\nWeather"
    assert downloads.next_message() == "Downloaded\nGeostat."
    assert downloads.next_message() is None


@pytest.mark.unit
def test_config_multi_menu_still_works(display):
    stored = {}
    config = SimpleNamespace(
        get_option=lambda key: stored.get(key),
        set_option=lambda key, value: stored.__setitem__(key, list(value)),
    )
    definition = {
        "name": "Test",
        "class": UITextMenu,
        "select": "multi",
        "config_option": "test.multi",
        "items": [{"name": "A", "value": "a"}, {"name": "B", "value": "b"}],
    }
    menu = _make_menu(display, definition, config)
    # No stored value means all selected, and the first item is "Select None".
    assert menu._menu_items == ["Select None", "A", "B"]
    assert menu._selected_values == ["a", "b"]
    menu._current_item_index = 1
    menu.key_right()
    assert stored["test.multi"] == ["b"]
    menu._current_item_index = 0
    menu.key_right()
    assert stored["test.multi"] == []
    assert menu._menu_items[0] == "Select All"
    menu.update()


@pytest.mark.unit
def test_single_menu_with_value_callback_still_works(display):
    definition = {
        "name": "Test",
        "class": UITextMenu,
        "select": "single",
        "value_callback": lambda ui: ["b"],
        "items": [{"name": "A", "value": "a"}, {"name": "B", "value": "b"}],
    }
    menu = _make_menu(display, definition)
    assert menu._selected_values == ["b"]
    assert menu._current_item_index == 1


@pytest.mark.unit
def test_group_modules_load_no_satellite_code():
    # A fresh interpreter: this test process loaded the modules already.
    code = (
        "import sys, PiFinder.satellite_groups; "
        "print(sorted(m for m in ('skyfield', 'sgp4', 'numpy') if m in sys.modules)); "
        "import PiFinder.i18n, PiFinder.ui.sat_groups; "
        "print('PiFinder.satellites' in sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    # Other output, for example the pygame banner, can come between them.
    lines = result.stdout.strip().splitlines()
    assert "[]" in lines
    assert lines[-1] == "False"


def _update_now_menu(display):
    menu = _group_menu(display)
    menu._current_item_index = 0
    assert menu._menu_items[0] == "Update now"
    return menu


def _write_group_files(directory, groups, age_seconds):
    seed_groups(directory, groups)
    for group in groups:
        make_old(satellites.group_file(group, directory), age_seconds / 3600.0)


@pytest.mark.unit
def test_update_now_is_the_first_item_of_the_menu():
    definition = _find_menu(menu_structure.pifinder_menu, "Sat groups")
    first = definition["items"][0]
    assert first["name"] == "Update now"
    assert first["callback"] is sat_groups.update_now
    assert "value" not in first


@pytest.mark.unit
def test_update_now_downloads_each_selected_group(display, sat_dir, monkeypatch):
    monkeypatch.setattr(satellite_catalog, "_active_catalog", None)
    result = satellites.GroupRefresh("downloaded")
    menu = _update_now_menu(display)
    with mock.patch.object(
        satellites, "refresh_groups", return_value=result
    ) as refresh:
        menu.key_right()
        sat_groups.downloads.thread.join(timeout=10)
    groups = [call.kwargs["groups"] for call in refresh.call_args_list]
    assert groups == [("visual",), ("stations",)]
    assert all(call.kwargs["force"] for call in refresh.call_args_list)
    assert _messages(menu) == [
        "Updating...",
        "Downloaded\nBrightest",
        "Downloaded\nStations",
    ]


@pytest.mark.unit
@pytest.mark.parametrize(
    "age_seconds, text", [(0, "Wait 2h00"), (15 * 60, "Wait 1h45")]
)
def test_update_now_refuses_a_download_within_2_hours(
    display, sat_dir, monkeypatch, age_seconds, text
):
    monkeypatch.setattr(satellite_catalog, "_active_catalog", None)
    _write_group_files(sat_dir, ["visual", "stations"], age_seconds)
    menu = _update_now_menu(display)
    with mock.patch.object(satellites, "refresh_groups") as refresh:
        menu.key_right()
    refresh.assert_not_called()
    assert sat_groups.downloads.thread is None
    assert _messages(menu) == [text]


@pytest.mark.unit
def test_update_now_permits_a_download_when_one_group_is_old(
    display, sat_dir, monkeypatch
):
    monkeypatch.setattr(satellite_catalog, "_active_catalog", None)
    _write_group_files(sat_dir, ["visual"], 0)
    _write_group_files(sat_dir, ["stations"], 3 * 3600)
    menu = _update_now_menu(display)
    result = satellites.GroupRefresh("downloaded")
    with mock.patch.object(satellites, "refresh_groups", return_value=result):
        menu.key_right()
        sat_groups.downloads.thread.join(timeout=10)
    assert _messages(menu)[0] == "Updating..."


@pytest.mark.unit
def test_update_now_uses_the_satellite_catalog(display, sat_dir, monkeypatch):
    catalog = SimpleNamespace(refresh=mock.MagicMock(return_value=None))
    catalog.touch = lambda: None
    monkeypatch.setattr(satellite_catalog, "_active_catalog", catalog)
    menu = _update_now_menu(display)
    with mock.patch.object(satellites, "refresh_groups") as refresh:
        menu.key_right()
    catalog.refresh.assert_called_once_with()
    # The catalog downloads in its own thread and posts the result.
    refresh.assert_not_called()
    assert sat_groups.downloads.thread is None
    assert _messages(menu) == ["Updating..."]


@pytest.mark.unit
def test_update_now_shows_the_wait_of_the_catalog(display, sat_dir, monkeypatch):
    catalog = SimpleNamespace(refresh=mock.MagicMock(return_value=600))
    catalog.touch = lambda: None
    monkeypatch.setattr(satellite_catalog, "_active_catalog", catalog)
    menu = _update_now_menu(display)
    menu.key_right()
    assert _messages(menu) == ["Updating...", "Wait 10 min"]


@pytest.mark.unit
def test_update_now_without_groups(display, sat_dir, monkeypatch):
    monkeypatch.setattr(satellite_catalog, "_active_catalog", None)
    for group in satellite_groups.DEFAULT_GROUPS:
        satellites.set_group_enabled(group, False, sat_dir)
    menu = _update_now_menu(display)
    with mock.patch.object(satellites, "refresh_groups") as refresh:
        menu.key_right()
    refresh.assert_not_called()
    assert _messages(menu) == ["No groups\nselected"]
