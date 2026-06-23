import pytest
from web_test_utils import (
    login_to_remote,
    navigate_to_root_menu,
    press_keys,
    press_keys_and_validate,
)

"""
Tests for the Set Filters menu in PiFinder's remote control interface.

For the 2.6.0 release this menu moved: it used to be a top-level "Filter" menu,
and is now the last item *inside* the Objects menu, renamed "Set Filters".

Objects submenu (entered from root Objects → R) items (0-indexed):
  0: All Filtered
  1: By Catalog
  2: Recent
  3: Obs Lists
  4: Custom
  5: Name Search
  6: Set Filters   ← this menu

Set Filters submenu (0-indexed):
  0: Reset All  (confirmation submenu with Confirm / Cancel)
  1: Catalogs   (multi-select)
  2: Type       (multi-select)
  3: Altitude   (single-select: None, 0°, 10°, 20°, 30°, 40°)
  4: Magnitude  (single-select: None, 6..15)
  5: Observed   (single-select: Any, Observed, Not Observed)

Key sequence from navigate_to_root_menu() (lands on Objects in root menu):
  R        → enter Objects (lands on All Filtered, index 0)
  DDDDDD   → highlight Set Filters (index 6)
  R        → enter Set Filters submenu (now at Reset All, index 0)
  i.e. "RDDDDDDR" enters Set Filters at Reset All.

All tests that change filter values use Reset All > Confirm to restore defaults
before exiting, keeping filter state neutral for subsequent tests.
"""

# ---------------------------------------------------------------------------
# Navigation: entering the Set Filters menu and each sub-item
# ---------------------------------------------------------------------------


@pytest.mark.web
def test_filter_menu_entry(driver):
    """Entering the Set Filters menu lands on Reset All."""
    login_to_remote(driver)
    navigate_to_root_menu(driver)

    # RDDDDDD = enter Objects, down to Set Filters (index 6); R = enter it
    press_keys_and_validate(
        driver,
        "RDDDDDDR",
        {
            "ui_type": "UITextMenu",
            "title": "Set Filters",
            "current_item": "Reset All",
        },
    )

    press_keys(driver, "ZL")  # back to root


@pytest.mark.web
def test_filter_reset_all_shows_confirm_cancel(driver):
    """Set Filters > Reset All opens a Confirm/Cancel dialog at Confirm."""
    login_to_remote(driver)
    navigate_to_root_menu(driver)

    # RDDDDDDR = enter Set Filters at Reset All; R = enter the confirmation submenu
    press_keys_and_validate(
        driver,
        "RDDDDDDRR",
        {
            "ui_type": "UITextMenu",
            "title": "Reset All",
            "current_item": "Confirm",
        },
    )

    press_keys(driver, "ZL")  # back to root without confirming


@pytest.mark.web
def test_filter_reset_all_cancel_returns_to_filter(driver):
    """Choosing Cancel in Reset All returns to the Set Filters menu."""
    login_to_remote(driver)
    navigate_to_root_menu(driver)

    # RDDDDDDRR = enter Reset All confirmation; D = move to Cancel; R = select Cancel
    press_keys_and_validate(
        driver,
        "RDDDDDDRRDR",
        {
            "ui_type": "UITextMenu",
            "title": "Set Filters",
        },
    )

    press_keys(driver, "ZL")  # back to root


@pytest.mark.web
def test_filter_reset_all_confirm_resets_filters(driver):
    """Choosing Confirm in Reset All resets filters and returns to Set Filters menu."""
    login_to_remote(driver)
    navigate_to_root_menu(driver)

    # RDDDDDDRR = enter Reset All confirmation; R = select Confirm
    press_keys_and_validate(
        driver,
        "RDDDDDDRRR",
        {
            "ui_type": "UITextMenu",
            "title": "Set Filters",
        },
    )

    press_keys(driver, "ZL")  # back to root


@pytest.mark.web
def test_filter_catalogs_entry(driver):
    """Set Filters > Catalogs opens the catalog multi-select menu."""
    login_to_remote(driver)
    navigate_to_root_menu(driver)

    # RDDDDDDR = enter Set Filters at Reset All; DR = D to Catalogs (index 1), R to enter
    press_keys_and_validate(
        driver,
        "RDDDDDDRDR",
        {
            "ui_type": "UITextMenu",
            "title": "Catalogs",
        },
    )

    press_keys(driver, "ZL")  # back to root


@pytest.mark.web
def test_filter_type_entry(driver):
    """Set Filters > Type opens the object type multi-select menu."""
    login_to_remote(driver)
    navigate_to_root_menu(driver)

    # RDDDDDDR = enter Set Filters; DDR = DD to Type (index 2), R to enter
    press_keys_and_validate(
        driver,
        "RDDDDDDRDDR",
        {
            "ui_type": "UITextMenu",
            "title": "Type",
        },
    )

    press_keys(driver, "ZL")  # back to root


@pytest.mark.web
def test_filter_altitude_entry(driver):
    """Set Filters > Altitude opens the altitude single-select menu."""
    login_to_remote(driver)
    navigate_to_root_menu(driver)

    # RDDDDDDR = enter Set Filters; DDDR = DDD to Altitude (index 3), R to enter
    press_keys_and_validate(
        driver,
        "RDDDDDDRDDDR",
        {
            "ui_type": "UITextMenu",
            "title": "Altitude",
        },
    )

    press_keys(driver, "ZL")  # back to root


@pytest.mark.web
def test_filter_altitude_select_and_reset(driver):
    """Select altitude 10° then reset all filters back to defaults."""
    login_to_remote(driver)
    navigate_to_root_menu(driver)

    # Enter Altitude: RDDDDDDR (Set Filters) + DDDR (navigate to Altitude) + R (enter)
    # Altitude items: None (0), 0° (1), 10° (2), 20° (3), 30° (4), 40° (5)
    # DD = move to 10°; R = select → returns to Set Filters menu
    press_keys_and_validate(
        driver,
        "RDDDDDDRDDDRR",  # enter Altitude (now at None, index 0)
        {"ui_type": "UITextMenu", "title": "Altitude"},
    )
    press_keys_and_validate(
        driver,
        "DDR",  # select 10° → returns to Set Filters
        {"ui_type": "UITextMenu", "title": "Set Filters"},
    )

    # Reset all filters via Set Filters > Reset All > Confirm
    # We are in Set Filters, currently at Altitude (index 3). Go to Reset All (index 0).
    press_keys_and_validate(
        driver,
        "UUURR",  # UUU back to Reset All (index 0), RR enter + Confirm
        {"ui_type": "UITextMenu", "title": "Set Filters"},
    )

    press_keys(driver, "ZL")  # back to root


@pytest.mark.web
def test_filter_magnitude_entry(driver):
    """Set Filters > Magnitude opens the magnitude single-select menu."""
    login_to_remote(driver)
    navigate_to_root_menu(driver)

    # RDDDDDDR = enter Set Filters; DDDDR = DDDD to Magnitude (index 4), R to enter
    press_keys_and_validate(
        driver,
        "RDDDDDDRDDDDR",
        {
            "ui_type": "UITextMenu",
            "title": "Magnitude",
        },
    )

    press_keys(driver, "ZL")  # back to root


@pytest.mark.web
def test_filter_observed_entry(driver):
    """Set Filters > Observed opens the observed single-select menu."""
    login_to_remote(driver)
    navigate_to_root_menu(driver)

    # RDDDDDDR = enter Set Filters; DDDDDR = DDDDD to Observed (index 5), R to enter
    press_keys_and_validate(
        driver,
        "RDDDDDDRDDDDDR",
        {
            "ui_type": "UITextMenu",
            "title": "Observed",
        },
    )

    press_keys(driver, "ZL")  # back to root


@pytest.mark.web
def test_filter_observed_select_and_reset(driver):
    """Select 'Observed' in the Observed filter then reset all filters."""
    login_to_remote(driver)
    navigate_to_root_menu(driver)

    # Enter Observed menu, select the 'Observed' value (index 1)
    # Observed items: Any (0), Observed (1), Not Observed (2)
    press_keys_and_validate(
        driver,
        "RDDDDDDRDDDDDRR",  # enter Set Filters + navigate to Observed + enter
        {"ui_type": "UITextMenu", "title": "Observed"},
    )
    press_keys_and_validate(
        driver,
        "DR",  # D = Observed (index 1), R = select → back to Set Filters
        {"ui_type": "UITextMenu", "title": "Set Filters"},
    )

    # Reset all filters: we are in Set Filters at Observed (index 5).
    # Navigate back to Reset All (index 0) with UUUUU, then Confirm (RR).
    press_keys_and_validate(
        driver,
        "UUUUURR",  # UUUUU → Reset All (index 0), RR → enter + Confirm
        {"ui_type": "UITextMenu", "title": "Set Filters"},
    )

    press_keys(driver, "ZL")  # back to root
