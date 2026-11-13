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

from PiFinder import satellite_groups, satellites, utils
from PiFinder.displays import get_display
from PiFinder.ui import menu_structure, sat_groups
from PiFinder.ui.base import UIModule
from PiFinder.ui.text_menu import UITextMenu


@pytest.fixture
def sat_dir(tmp_path, monkeypatch):
    directory = tmp_path / "satellites"
    monkeypatch.setattr(utils, "satellite_data_dir", directory)
    return directory


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch):
    monkeypatch.setattr(sat_groups, "downloads", sat_groups.GroupDownloads())
    monkeypatch.setattr(UIModule, "message_until", 0.0)


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
    menu._current_item_index = satellite_groups.CELESTRAK_GROUPS.index(group)


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
    items = definition["items"]
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
    # The menu has no "Select None" item.
    assert menu._menu_items[0] == "Brightest"
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
def test_toggle_stores_the_selection(display, sat_dir):
    path = satellites.group_file("visual", sat_dir)
    path.parent.mkdir(parents=True)
    path.write_text("")
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
def test_select_of_a_group_with_a_file_downloads_nothing(display, sat_dir):
    path = satellites.group_file("weather", sat_dir)
    path.parent.mkdir(parents=True)
    path.write_text("")
    menu = _group_menu(display)
    _move_to(menu, "weather")
    menu.key_right()
    assert sat_groups.downloads.thread is None
    assert _messages(menu) == []


@pytest.mark.unit
def test_large_group_shows_a_message(display, sat_dir):
    path = satellites.group_file("starlink", sat_dir)
    path.parent.mkdir(parents=True)
    path.write_text("")
    menu = _group_menu(display)
    _move_to(menu, "starlink")
    menu.key_right()
    assert _messages(menu) == ["Large group:\nslow passes"]


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
def test_large_group_download_shows_both_messages(display, sat_dir):
    result = satellites.GroupRefresh("failed", failed=("starlink",))
    menu = _group_menu(display)
    _move_to(menu, "starlink")
    with mock.patch.object(satellites, "refresh_groups", return_value=result):
        menu.key_right()
        sat_groups.downloads.thread.join(timeout=10)
    assert _messages(menu) == [
        "Large group:\nslow passes",
        "Downloading\nStarlink*",
        "Download failed\nStarlink*",
    ]


@pytest.mark.unit
def test_download_error_shows_failed(display, sat_dir):
    menu = _group_menu(display)
    _move_to(menu, "weather")
    with mock.patch.object(satellites, "refresh_groups", side_effect=OSError("x")):
        menu.key_right()
        sat_groups.downloads.thread.join(timeout=10)
    assert _messages(menu)[-1] == "Download failed\nWeather"


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
        (satellites.GroupRefresh("busy"), "Download busy"),
        (satellites.GroupRefresh("failed"), "Download failed"),
        (None, "Download failed"),
    ],
)
def test_result_message(result, text):
    assert sat_groups.result_message(result) == text


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
