import PiFinder.i18n  # noqa: F401

from PiFinder.ui.gps_time_sync_status import UIGPSTimeSyncStatus
from PiFinder.ui import menu_structure


def _screen():
    return object.__new__(UIGPSTimeSyncStatus)


def _iter_menu_nodes(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _iter_menu_nodes(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_menu_nodes(item)


def test_gps_time_sync_status_menu_entry_exists():
    entries = [
        node
        for node in _iter_menu_nodes(menu_structure.pifinder_menu)
        if node.get("class") is UIGPSTimeSyncStatus
    ]

    assert len(entries) == 1
    assert entries[0]["name"] == "Time Sync"


def test_gps_time_sync_settings_menu_entries_exist():
    expected_options = {
        "time_sync_enabled",
        "time_sync_source_mode",
        "gps_time_sync",
        "ntp_time_sync",
        "ntp_server",
        "software_pps",
        "time_sync_system_clock",
        "rtc_sync",
    }
    entries = {
        node.get("config_option"): node
        for node in _iter_menu_nodes(menu_structure.pifinder_menu)
        if node.get("config_option") in expected_options
    }

    assert set(entries) == expected_options

    for option in (
        "time_sync_enabled",
        "gps_time_sync",
        "ntp_time_sync",
        "software_pps",
        "time_sync_system_clock",
        "rtc_sync",
    ):
        node = entries[option]
        assert [item["value"] for item in node["items"]] == [False, True]
        assert node["items"][0]["name"] == "Off"
        assert node["items"][1]["name"] == "On"
        assert node["post_callback"] is menu_structure.callbacks.reload_config

    assert [item["value"] for item in entries["time_sync_source_mode"]["items"]] == [
        "best",
        "gps",
        "ntp",
    ]
    assert [item["value"] for item in entries["ntp_server"]["items"]] == [
        "pool.ntp.org",
        "time.google.com",
        "time.cloudflare.com",
        "time.nist.gov",
        "custom",
    ]


def test_custom_ntp_server_is_handled_from_ntp_server_menu():
    ntp_server_entries = [
        node
        for node in _iter_menu_nodes(menu_structure.pifinder_menu)
        if node.get("config_option") == "ntp_server"
    ]

    assert len(ntp_server_entries) == 1
    custom_items = [
        item
        for item in ntp_server_entries[0]["items"]
        if item.get("value") == "custom"
    ]
    assert len(custom_items) == 1
    assert custom_items[0]["name"] == "Custom"
    assert custom_items[0]["callback"] is menu_structure.callbacks.edit_custom_ntp_server
    assert (
        custom_items[0]["name_suffix_callback"]
        is menu_structure.callbacks.get_custom_ntp_server_display
    )

    standalone_entries = [
        node
        for node in _iter_menu_nodes(menu_structure.pifinder_menu)
        if node.get("name") == "Custom NTP Server"
    ]
    assert standalone_entries == []


def test_gps_time_sync_status_summary_lines():
    screen = _screen()
    status = {
        "state": "low_quality",
        "selected": None,
        "latest": {
            "valid": False,
            "source": "GPS",
            "message_class": "NAV-PVT",
            "tAcc_ns": 4_294_967_295,
        },
        "ntp": {"state": "unavailable", "server": "pool.ntp.org"},
        "system_clock_sync": {"state": "disabled"},
        "rtc_sync": {"state": "disabled"},
        "software_pps": {"enabled": True, "tick_count": 7},
    }
    helper = {"state": "idle"}

    lines = screen._summary_lines(status, helper, request_present=False)

    assert "State: low_quality" in lines
    assert "Selected: --" in lines
    assert "GPS valid: No" in lines
    assert "Source: GPS NAV-PVT" in lines
    assert "NTP: unavailable" in lines
    assert "Sys: disabled" in lines
    assert "RTC: disabled" in lines
    assert "Helper: idle" in lines
    assert "Request: No" in lines
    assert "PPS: On 7" in lines


def test_gps_time_sync_status_detail_lines_include_helper_results():
    screen = _screen()
    status = {
        "state": "stable",
        "message": "Selected GPS time source",
        "selected": {
            "source": "GPS",
            "time": "2026-06-27T01:58:23+00:00",
        },
        "latest": {
            "gps_time": "2026-06-27T01:58:23+00:00",
            "age_seconds": 3.2,
            "valid": True,
            "tAcc_ns": 10_000,
            "offset_seconds": 0.1,
            "system_offset_seconds": 5.0,
        },
        "ntp": {
            "state": "stable",
            "server": "pool.ntp.org",
            "time": "2026-06-27T01:58:22+00:00",
            "delay_seconds": 0.08,
        },
        "samples": {"count": 5, "min_required": 5},
        "system_clock_sync": {"state": "requested"},
        "rtc_sync": {"state": "requested"},
        "software_pps": {"tick_count": 11},
    }
    helper = {
        "state": "completed",
        "effective_uid": 0,
        "message": "Time sync request processed",
        "results": {
            "system_clock": {"state": "synced"},
            "rtc": {"state": "synced"},
        },
    }

    lines = screen._detail_lines(status, helper, request_present=True)

    assert "State: stable" in lines
    assert "Selected: GPS" in lines
    assert "Sel time: 2026-06-27 01:58:23" in lines
    assert "GPS: 2026-06-27 01:58:23" in lines
    assert "NTP: stable" in lines
    assert "Valid: Yes" in lines
    assert "Sys req: requested" in lines
    assert "RTC req: requested" in lines
    assert "Helper: completed" in lines
    assert "Helper UID: 0" in lines
    assert "Req file: Yes" in lines
    assert "Sys result: synced" in lines
    assert "RTC result: synced" in lines
