import pytest
from web_test_utils import (
    login_to_remote,
    navigate_to_root_menu,
    press_keys,
    press_keys_and_validate,
)

"""
Tests for the Tools menu in PiFinder's remote control interface.

This file tests Tools menu *navigation* via the virtual keypad (remote control).
Web-page-level tests for /equipment and /locations are in test_web_equipment.py
and test_web_locations.py respectively.

Tools menu (root → DDD → R) items (0-indexed):
  0: Status        (UIStatus screen)
  1: Equipment     (UIEquipment screen)
  2: Place & Time  (submenu)
  3: Console       (UIConsole – not tested: dev-only stream)
  4: Software Upd  (UISoftware)
  5: Test Mode     (callback, not tested)
  6: Experimental  (submenu, not tested: hardware/restart-dependent)
  7: Power         (submenu, not tested: shutdown/restart dangerous)

Place & Time submenu (0-indexed):
  0: GPS Status    (UIGPSStatus screen)
  1: Set Location  (UILocationList screen)
  2: Set Time      (UITimeEntry screen)
  3: Reset         (callback: gps_reset)

Key sequences from navigate_to_root_menu() (lands on Objects in root menu):
  DDD  → highlight Tools (index 5, 3 downs from Objects=2)
  R    → enter Tools submenu (now at Status, index 0)
"""

# ---------------------------------------------------------------------------
# Tools menu entry
# ---------------------------------------------------------------------------


@pytest.mark.web
def test_tools_menu_entry(driver):
    """Entering the Tools menu lands on Status."""
    login_to_remote(driver)
    navigate_to_root_menu(driver)

    # DDD = navigate to Tools in root; R = enter Tools submenu
    press_keys_and_validate(
        driver,
        "DDDR",
        {
            "ui_type": "UITextMenu",
            "title": "Tools",
            "current_item": "Status",
        },
    )

    press_keys(driver, "ZL")  # back to root


# ---------------------------------------------------------------------------
# Tools > Status
# ---------------------------------------------------------------------------


@pytest.mark.web
def test_tools_status_screen(driver):
    """Tools > Status navigates to the UIStatus screen."""
    login_to_remote(driver)
    navigate_to_root_menu(driver)

    # DDDR = enter Tools at Status; R = enter UIStatus screen
    press_keys_and_validate(
        driver,
        "DDDRR",
        {
            "ui_type": "UIStatus",
        },
    )

    press_keys(driver, "ZL")  # back to root


# ---------------------------------------------------------------------------
# Tools > Place & Time
# ---------------------------------------------------------------------------


@pytest.mark.web
def test_tools_place_and_time_entry(driver):
    """Tools > Place & Time opens the submenu at GPS Status."""
    login_to_remote(driver)
    navigate_to_root_menu(driver)

    # DDDR = enter Tools at Status; DD = navigate to Place & Time (index 2); R = enter
    press_keys_and_validate(
        driver,
        "DDDRDDR",
        {
            "ui_type": "UITextMenu",
            "title": "Place & Time",
            "current_item": "GPS Status",
        },
    )

    press_keys(driver, "ZL")  # back to root


@pytest.mark.web
def test_tools_gps_status_screen(driver):
    """Tools > Place & Time > GPS Status opens the UIGPSStatus screen."""
    login_to_remote(driver)
    navigate_to_root_menu(driver)

    # DDDRDDR = enter Place & Time at GPS Status; R = enter UIGPSStatus
    press_keys_and_validate(
        driver,
        "DDDRDDRR",
        {
            "ui_type": "UIGPSStatus",
        },
    )

    press_keys(driver, "ZL")  # back to root


@pytest.mark.web
def test_tools_set_time_screen(driver):
    """Tools > Place & Time > Set Time opens the UITimeEntry screen."""
    login_to_remote(driver)
    navigate_to_root_menu(driver)

    # DDDRDDR = enter Place & Time at GPS Status (index 0)
    # DD = navigate to Set Time (index 2); R = enter UITimeEntry
    press_keys_and_validate(
        driver,
        "DDDRDDRDDR",
        {
            "ui_type": "UITimeEntry",
        },
    )

    press_keys(driver, "ZL")  # back to root


@pytest.mark.web
def test_tools_set_location_screen(driver):
    """Tools > Place & Time > Set Location opens the UILocationList screen."""
    login_to_remote(driver)
    navigate_to_root_menu(driver)

    # DDDRDDR = enter Place & Time at GPS Status (index 0)
    # D = navigate to Set Location (index 1); R = enter UILocationList
    press_keys_and_validate(
        driver,
        "DDDRDDRDR",
        {
            "ui_type": "UILocationList",
        },
    )

    press_keys(driver, "ZL")  # back to root


# ---------------------------------------------------------------------------
# Tools > Software Upd
# ---------------------------------------------------------------------------


@pytest.mark.web
def test_tools_software_update_screen(driver):
    """Tools > Software Upd opens the UISoftware screen (read-only, no update triggered)."""
    login_to_remote(driver)
    navigate_to_root_menu(driver)

    # DDDR = enter Tools at Status (0); DDDD = navigate to Software Upd (index 4); R = enter
    press_keys_and_validate(
        driver,
        "DDDRDDDDR",
        {
            "ui_type": "UISoftware",
        },
    )

    press_keys(driver, "ZL")  # back to root
