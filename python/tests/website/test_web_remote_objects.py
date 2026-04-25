import pytest
from web_test_utils import (
    login_to_remote,
    navigate_to_root_menu,
    press_keys,
    press_keys_and_validate,
)

"""
Tests for the Objects menu in PiFinder's remote control interface.

These tests extend the coverage in test_web_remote.py, which already covers:
  - Objects > By Catalog > Messier (navigation + object list)
  - Objects > Name Search (text entry)
  - Objects > Recent (via LONG+RIGHT shortcut)
  - Object list Marking Menu (sort order)

This file adds coverage for the remaining Objects sub-items:
  - Objects > All Filtered
  - Objects > By Catalog > Planets, Comets, NGC
  - Objects > By Catalog > DSO... (nested submenu)
  - Objects > By Catalog > Stars... (nested submenu)
  - Objects > Custom (UIRADecEntry)

Objects submenu (entered from root menu Objects → R) items (0-indexed):
  0: All Filtered  (UIObjectList)
  1: By Catalog    (submenu)
  2: Recent        (UIObjectList)
  3: Custom        (UIRADecEntry)
  4: Name Search   (UITextEntry)  ← already tested in test_web_remote.py

By Catalog submenu (0-indexed):
  0: Planets   (UIObjectList, catalog "PL")
  1: Comets    (UIObjectList, catalog "CM")
  2: NGC       (UIObjectList, catalog "NGC")
  3: Messier   (UIObjectList, catalog "M")  ← already tested
  4: DSO...    (nested UITextMenu submenu)
  5: Stars...  (nested UITextMenu submenu)

Key sequences from navigate_to_root_menu() (lands on Objects in root menu):
  R     → enter Objects submenu (now at All Filtered, index 0)
  D     → By Catalog (index 1)
  DD    → Recent     (index 2)
  DDD   → Custom     (index 3)
  DDDD  → Name Search (index 4) ← confirmed by test_remote_entry in test_web_remote.py
"""

# ---------------------------------------------------------------------------
# Objects > All Filtered
# ---------------------------------------------------------------------------


@pytest.mark.web
def test_objects_all_filtered_entry(driver):
    """Objects > All Filtered opens the full filtered object list."""
    login_to_remote(driver)
    navigate_to_root_menu(driver)

    # R = enter Objects submenu at All Filtered (index 0); R = enter UIObjectList
    press_keys_and_validate(
        driver,
        "RR",
        {
            "ui_type": "UIObjectList",
            "title": "All Filtered",
        },
    )

    press_keys(driver, "ZL")  # back to root


@pytest.mark.web
def test_objects_all_filtered_shows_current_item(driver):
    """All Filtered list exposes a current_item (non-empty list with default filters)."""
    login_to_remote(driver)
    navigate_to_root_menu(driver)

    result = press_keys_and_validate(
        driver,
        "RR",
        {"ui_type": "UIObjectList", "title": "All Filtered"},
    )

    # With default filters the list should not be empty
    assert "current_item" in result, (
        "All Filtered list should expose a current_item; "
        "list may be empty due to active filters"
    )

    press_keys(driver, "ZL")  # back to root


# ---------------------------------------------------------------------------
# Objects > By Catalog — direct catalog lists
# ---------------------------------------------------------------------------


@pytest.mark.web
def test_objects_by_catalog_planets(driver):
    """Objects > By Catalog > Planets opens the Planets object list."""
    login_to_remote(driver)
    navigate_to_root_menu(driver)

    # R = Objects submenu; D = By Catalog; R = enter By Catalog at Planets (0); R = enter
    press_keys_and_validate(
        driver,
        "RDRR",
        {
            "ui_type": "UIObjectList",
            "title": "Planets",
        },
    )

    press_keys(driver, "ZL")  # back to root


@pytest.mark.web
def test_objects_by_catalog_comets(driver):
    """Objects > By Catalog > Comets opens the Comets object list."""
    login_to_remote(driver)
    navigate_to_root_menu(driver)

    # R = Objects submenu; D = By Catalog; R = enter By Catalog at Planets (0)
    # D = Comets (1); R = enter
    press_keys_and_validate(
        driver,
        "RDRDR",
        {
            "ui_type": "UIObjectList",
            "title": "Comets",
        },
    )

    press_keys(driver, "ZL")  # back to root


@pytest.mark.web
def test_objects_by_catalog_ngc(driver):
    """Objects > By Catalog > NGC opens the NGC object list."""
    login_to_remote(driver)
    navigate_to_root_menu(driver)

    # R = Objects submenu; D = By Catalog; R = enter By Catalog at Planets (0)
    # DD = NGC (2); R = enter
    press_keys_and_validate(
        driver,
        "RDRDDR",
        {
            "ui_type": "UIObjectList",
            "title": "NGC",
        },
    )

    press_keys(driver, "ZL")  # back to root


# ---------------------------------------------------------------------------
# Objects > By Catalog > DSO... (nested submenu)
# ---------------------------------------------------------------------------


@pytest.mark.web
def test_objects_by_catalog_dso_submenu_entry(driver):
    """Objects > By Catalog > DSO... opens the DSO nested submenu."""
    login_to_remote(driver)
    navigate_to_root_menu(driver)

    # R = Objects submenu; D = By Catalog; R = enter By Catalog at Planets (0)
    # DDDD = DSO... (4); R = enter
    press_keys_and_validate(
        driver,
        "RDRDDDDR",
        {
            "ui_type": "UITextMenu",
            "title": "DSO...",
        },
    )

    press_keys(driver, "ZL")  # back to root


@pytest.mark.web
def test_objects_by_catalog_dso_first_item_is_abell(driver):
    """DSO... submenu first entry is Abell Pn."""
    login_to_remote(driver)
    navigate_to_root_menu(driver)

    press_keys_and_validate(
        driver,
        "RDRDDDDR",
        {
            "ui_type": "UITextMenu",
            "title": "DSO...",
            "current_item": "Abell Pn",
        },
    )

    press_keys(driver, "ZL")  # back to root


@pytest.mark.web
def test_objects_by_catalog_dso_enter_catalog(driver):
    """DSO... > Caldwell opens a UIObjectList."""
    login_to_remote(driver)
    navigate_to_root_menu(driver)

    # DSO... submenu items: Abell Pn(0), Arp Galaxies(1), Barnard(2), Caldwell(3)
    # Enter DSO..., navigate to Caldwell (DDDR), enter
    press_keys_and_validate(
        driver,
        "RDRDDDDR",  # enter DSO...
        {"ui_type": "UITextMenu", "title": "DSO..."},
    )
    press_keys_and_validate(
        driver,
        "DDDR",  # DDD = Caldwell (index 3); R = enter
        {
            "ui_type": "UIObjectList",
            "title": "Caldwell",
        },
    )

    press_keys(driver, "ZL")  # back to root


# ---------------------------------------------------------------------------
# Objects > By Catalog > Stars... (nested submenu)
# ---------------------------------------------------------------------------


@pytest.mark.web
def test_objects_by_catalog_stars_submenu_entry(driver):
    """Objects > By Catalog > Stars... opens the Stars nested submenu."""
    login_to_remote(driver)
    navigate_to_root_menu(driver)

    # By Catalog: ..., DSO...(4), Stars...(5)
    # R = Objects submenu; D = By Catalog; R = enter By Catalog at Planets (0)
    # DDDDD = Stars... (5); R = enter
    press_keys_and_validate(
        driver,
        "RDRDDDDDR",
        {
            "ui_type": "UITextMenu",
            "title": "Stars...",
        },
    )

    press_keys(driver, "ZL")  # back to root


@pytest.mark.web
def test_objects_by_catalog_stars_first_item_is_bright_named(driver):
    """Stars... submenu first entry is Bright Named."""
    login_to_remote(driver)
    navigate_to_root_menu(driver)

    press_keys_and_validate(
        driver,
        "RDRDDDDDR",
        {
            "ui_type": "UITextMenu",
            "title": "Stars...",
            "current_item": "Bright Named",
        },
    )

    press_keys(driver, "ZL")  # back to root


# ---------------------------------------------------------------------------
# Objects > Custom (RA/Dec coordinate entry)
# ---------------------------------------------------------------------------


@pytest.mark.web
def test_objects_custom_radec_entry_screen(driver):
    """Objects > Custom opens the RA/Dec coordinate entry screen."""
    login_to_remote(driver)
    navigate_to_root_menu(driver)

    # R = Objects submenu at All Filtered (0)
    # DDD = Custom (index 3); R = enter UIRADecEntry
    press_keys_and_validate(
        driver,
        "RDDDR",
        {
            "ui_type": "UIRADecEntry",
        },
    )

    press_keys(driver, "ZL")  # back to root
