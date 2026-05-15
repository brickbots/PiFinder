import pytest
from web_test_utils import (
    login_to_remote,
    navigate_to_root_menu,
    press_keys,
    press_keys_and_validate,
)

"""
Tests for the Filter menu in PiFinder's remote control interface.

Filter menu (reached from root Objects → D → Filter → R) items (0-indexed):
  0: Reset All  (confirmation submenu with Confirm / Cancel)
  1: Catalogs   (multi-select)
  2: Type       (multi-select)
  3: Altitude   (single-select: None, 0°, 10°, 20°, 30°, 40°)
  4: Magnitude  (single-select: None, 6..15)
  5: Observed   (single-select: Any, Observed, Not Observed)

Key sequence from navigate_to_root_menu() (lands on Objects in root menu):
  D  → highlight Filter in root menu
  R  → enter Filter submenu (now at Reset All, index 0)

All tests that change filter values use Reset All > Confirm to restore defaults
before exiting, keeping filter state neutral for subsequent tests.
"""

# ---------------------------------------------------------------------------
# Navigation: entering the Filter menu and each sub-item
# ---------------------------------------------------------------------------


@pytest.mark.web
def test_filter_menu_entry(driver):
    """Entering the Filter menu lands on Reset All."""
    login_to_remote(driver)
    navigate_to_root_menu(driver)

    press_keys_and_validate(
        driver,
        "DR",
        {
            "ui_type": "UITextMenu",
            "title": "Filter",
            "current_item": "Reset All",
        },
    )

    press_keys(driver, "ZL")  # back to root


@pytest.mark.web
def test_filter_reset_all_shows_confirm_cancel(driver):
    """Filter > Reset All opens a Confirm/Cancel dialog at Confirm."""
    login_to_remote(driver)
    navigate_to_root_menu(driver)

    # DR = enter Filter at Reset All; R = enter the confirmation submenu
    press_keys_and_validate(
        driver,
        "DRR",
        {
            "ui_type": "UITextMenu",
            "title": "Reset All",
            "current_item": "Confirm",
        },
    )

    press_keys(driver, "ZL")  # back to root without confirming


@pytest.mark.web
def test_filter_reset_all_cancel_returns_to_filter(driver):
    """Choosing Cancel in Reset All returns to the Filter menu."""
    login_to_remote(driver)
    navigate_to_root_menu(driver)

    # DRR = enter Reset All confirmation; D = move to Cancel; R = select Cancel
    press_keys_and_validate(
        driver,
        "DRRDR",
        {
            "ui_type": "UITextMenu",
            "title": "Filter",
        },
    )

    press_keys(driver, "ZL")  # back to root


@pytest.mark.web
def test_filter_reset_all_confirm_resets_filters(driver):
    """Choosing Confirm in Reset All resets filters and returns to Filter menu."""
    login_to_remote(driver)
    navigate_to_root_menu(driver)

    # DRR = enter Reset All confirmation; R = select Confirm
    press_keys_and_validate(
        driver,
        "DRRR",
        {
            "ui_type": "UITextMenu",
            "title": "Filter",
        },
    )

    press_keys(driver, "ZL")  # back to root


@pytest.mark.web
def test_filter_catalogs_entry(driver):
    """Filter > Catalogs opens the catalog multi-select menu."""
    login_to_remote(driver)
    navigate_to_root_menu(driver)

    # DR = enter Filter at Reset All; DR = D to Catalogs (index 1), R to enter
    press_keys_and_validate(
        driver,
        "DRDR",
        {
            "ui_type": "UITextMenu",
            "title": "Catalogs",
        },
    )

    press_keys(driver, "ZL")  # back to root


@pytest.mark.web
def test_filter_type_entry(driver):
    """Filter > Type opens the object type multi-select menu."""
    login_to_remote(driver)
    navigate_to_root_menu(driver)

    # DR = enter Filter; DDR = DD to Type (index 2), R to enter
    press_keys_and_validate(
        driver,
        "DRDDR",
        {
            "ui_type": "UITextMenu",
            "title": "Type",
        },
    )

    press_keys(driver, "ZL")  # back to root


@pytest.mark.web
def test_filter_altitude_entry(driver):
    """Filter > Altitude opens the altitude single-select menu."""
    login_to_remote(driver)
    navigate_to_root_menu(driver)

    # DR = enter Filter; DDDR = DDD to Altitude (index 3), R to enter
    press_keys_and_validate(
        driver,
        "DRDDDR",
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

    # Enter Altitude: DR (Filter) + DDDR (navigate to Altitude) + R (enter)
    # Altitude items: None (0), 0° (1), 10° (2), 20° (3), 30° (4), 40° (5)
    # DD = move to 10°; R = select → returns to Filter menu
    press_keys_and_validate(
        driver,
        "DRDDDRR",  # enter Altitude (now at None, index 0)
        {"ui_type": "UITextMenu", "title": "Altitude"},
    )
    press_keys_and_validate(
        driver,
        "DDR",  # select 10° → returns to Filter
        {"ui_type": "UITextMenu", "title": "Filter"},
    )

    # Reset all filters via Filter > Reset All > Confirm
    # We are in Filter, currently at Altitude (index 3). Go to Reset All (index 0).
    press_keys_and_validate(
        driver,
        "UUURR",  # UUU back to Reset All (index 0), RR enter + Confirm
        {"ui_type": "UITextMenu", "title": "Filter"},
    )

    press_keys(driver, "ZL")  # back to root


@pytest.mark.web
def test_filter_magnitude_entry(driver):
    """Filter > Magnitude opens the magnitude single-select menu."""
    login_to_remote(driver)
    navigate_to_root_menu(driver)

    # DR = enter Filter; DDDDR = DDDD to Magnitude (index 4), R to enter
    press_keys_and_validate(
        driver,
        "DRDDDDR",
        {
            "ui_type": "UITextMenu",
            "title": "Magnitude",
        },
    )

    press_keys(driver, "ZL")  # back to root


@pytest.mark.web
def test_filter_observed_entry(driver):
    """Filter > Observed opens the observed single-select menu."""
    login_to_remote(driver)
    navigate_to_root_menu(driver)

    # DR = enter Filter; DDDDDR = DDDDD to Observed (index 5), R to enter
    press_keys_and_validate(
        driver,
        "DRDDDDDR",
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
        "DRDDDDDRR",  # enter Filter + navigate to Observed + enter
        {"ui_type": "UITextMenu", "title": "Observed"},
    )
    press_keys_and_validate(
        driver,
        "DR",  # D = Observed (index 1), R = select → back to Filter
        {"ui_type": "UITextMenu", "title": "Filter"},
    )

    # Reset all filters: we are in Filter at Observed (index 5).
    # Navigate back to Reset All (index 0) with UUUUU, then Confirm (RR).
    press_keys_and_validate(
        driver,
        "UUUUURR",  # UUUUU → Reset All (index 0), RR → enter + Confirm
        {"ui_type": "UITextMenu", "title": "Filter"},
    )

    press_keys(driver, "ZL")  # back to root
