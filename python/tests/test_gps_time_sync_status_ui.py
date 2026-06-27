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
    assert entries[0]["name"] == "GPS Time Sync"


def test_gps_time_sync_settings_menu_entries_exist():
    expected_options = {
        "gps_time_sync",
        "software_pps",
        "gps_time_sync_system_clock",
        "rtc_sync",
    }
    entries = {
        node.get("config_option"): node
        for node in _iter_menu_nodes(menu_structure.pifinder_menu)
        if node.get("config_option") in expected_options
    }

    assert set(entries) == expected_options
    for node in entries.values():
        assert [item["value"] for item in node["items"]] == [False, True]
        assert node["items"][0]["name"] == "Off"
        assert node["items"][1]["name"] == "On"
        assert node["post_callback"] is menu_structure.callbacks.reload_config


def test_gps_time_sync_status_summary_lines():
    screen = _screen()
    status = {
        "state": "low_quality",
        "latest": {
            "valid": False,
            "source": "GPS",
            "message_class": "NAV-PVT",
            "tAcc_ns": 4_294_967_295,
        },
        "system_clock_sync": {"state": "disabled"},
        "rtc_sync": {"state": "disabled"},
        "software_pps": {"enabled": True, "tick_count": 7},
    }
    helper = {"state": "idle"}

    lines = screen._summary_lines(status, helper, request_present=False)

    assert "State: low_quality" in lines
    assert "GPS valid: No" in lines
    assert "Source: GPS NAV-PVT" in lines
    assert "Sys: disabled" in lines
    assert "RTC: disabled" in lines
    assert "Helper: idle" in lines
    assert "Request: No" in lines
    assert "PPS: On 7" in lines


def test_gps_time_sync_status_detail_lines_include_helper_results():
    screen = _screen()
    status = {
        "state": "stable",
        "message": "GPS time is stable",
        "latest": {
            "gps_time": "2026-06-27T01:58:23+00:00",
            "age_seconds": 3.2,
            "valid": True,
            "tAcc_ns": 10_000,
            "offset_seconds": 0.1,
            "system_offset_seconds": 5.0,
        },
        "samples": {"count": 5, "min_required": 5},
        "system_clock_sync": {"state": "requested"},
        "rtc_sync": {"state": "requested"},
        "software_pps": {"tick_count": 11},
    }
    helper = {
        "state": "completed",
        "effective_uid": 0,
        "message": "GPS time sync request processed",
        "results": {
            "system_clock": {"state": "synced"},
            "rtc": {"state": "synced"},
        },
    }

    lines = screen._detail_lines(status, helper, request_present=True)

    assert "State: stable" in lines
    assert "GPS: 2026-06-27 01:58:23" in lines
    assert "Valid: Yes" in lines
    assert "Sys req: requested" in lines
    assert "RTC req: requested" in lines
    assert "Helper: completed" in lines
    assert "Helper UID: 0" in lines
    assert "Req file: Yes" in lines
    assert "Sys result: synced" in lines
    assert "RTC result: synced" in lines
