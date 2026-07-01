import requests

import pytest
from web_test_utils import (
    get_homepage_url,
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
  0: GPS Status      (UIGPSStatus screen)
  1: Set Location    (submenu: Enter Coords, Load Location, Save Location)
  2: Set Time/Date   (UITimeEntry screen; self-gates on a location fix)
  3: Reset Location  (callback: gps_reset)
  4: Reset Time/Date (callback: datetime_reset)

Key sequences from navigate_to_root_menu() (lands on Objects in root menu):
  DDD  → highlight Tools (index 5, 3 downs from Objects=2)
  R    → enter Tools submenu (now at Status, index 0)
"""


def _force_location(driver, lat=50.0, lon=3.0, altitude=10.0):
    """Establish a location fix via the web GPS endpoint.

    UITimeEntry opens regardless of location, but self-gates: without a fix it
    shows a "set location first" notice with inert entry boxes (see ADR 0019).
    Tests that need the live entry boxes seed a fix first. POST /gps/update
    sleeps ~1s server-side to let the GPS thread apply the fix before returning.
    """
    cookies = {cookie["name"]: cookie["value"] for cookie in driver.get_cookies()}
    resp = requests.post(
        f"{get_homepage_url()}/gps/update",
        data={
            "latitudeDecimal": str(lat),
            "longitudeDecimal": str(lon),
            "altitude": str(altitude),
        },
        cookies=cookies,
    )
    assert resp.status_code in (200, 302)


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
    """Tools > Place & Time > Set Time/Date opens the UITimeEntry screen.

    With a location fix seeded, the screen opens with live entry boxes. (The
    screen self-gates on the fix -- see ADR 0019 -- but always opens; the gate
    only governs the entry boxes and the set_time callback, not navigation.)
    """
    login_to_remote(driver)
    _force_location(driver)
    navigate_to_root_menu(driver)

    # DDDRDDR = enter Place & Time at GPS Status (index 0)
    # DD = navigate to Set Time/Date (index 2); R = enter UITimeEntry
    press_keys_and_validate(
        driver,
        "DDDRDDRDDR",
        {
            "ui_type": "UITimeEntry",
        },
    )

    press_keys(driver, "ZL")  # back to root


@pytest.mark.web
def test_tools_set_time_screen_opens_without_location(driver):
    """Set Time/Date is never hard-blocked: it opens even with no location seeded.

    This guards the ADR-0019 change from regressing back to a menu-layer gate
    that refused to open the screen without a fix. The module self-gates
    internally instead (showing a "set location first" notice with inert boxes),
    so ``ui_type`` is UITimeEntry regardless of whether a fix is present.
    """
    login_to_remote(driver)
    navigate_to_root_menu(driver)  # deliberately no _force_location()

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
    """Tools > Place & Time > Set Location > Load Location opens the UILocationList screen."""
    login_to_remote(driver)
    navigate_to_root_menu(driver)

    # DDDRDDR = enter Place & Time at GPS Status (index 0)
    # D = navigate to Set Location (index 1); R = enter Set Location submenu
    # D = navigate to Load Location (index 1); R = enter UILocationList
    press_keys_and_validate(
        driver,
        "DDDRDDRDRDR",
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
