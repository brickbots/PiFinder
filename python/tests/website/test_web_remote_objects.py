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
  - Objects > By Catalog > Planets, NGC
  - Objects > By Catalog > Small bodies... > Comets, Asteroids
  - Objects > By Catalog > DSO... (nested submenu)
  - Objects > By Catalog > Stars... (nested submenu)
  - Objects > Custom (UIRADecEntry)

Objects submenu (entered from root menu Objects → R) items (0-indexed):
  0: All Filtered  (UIObjectList)
  1: By Catalog    (submenu)
  2: Recent        (UIObjectList)
  3: Obs Lists     (UIObjectList)
  4: Custom        (UIRADecEntry)
  5: Name Search   (UITextEntry)  ← already tested in test_web_remote.py
  6: Set Filters   (submenu)      ← navigation tested in test_web_remote_filter.py

By Catalog submenu (0-indexed):
  0: Messier          (UIObjectList, catalog "M")  ← already tested
  1: NGC              (UIObjectList, catalog "NGC")
  2: Planets          (UIObjectList, catalog "PL")
  3: DSO...           (nested UITextMenu submenu)
  4: Stars...         (nested UITextMenu submenu)
  5: Small bodies...  (nested submenu: 0 Comets "CM", 1 Asteroids "MP")
  6: Satellites...    (nested submenu: 0 Satellites "SA", 1 Sat groups)

Key sequences from navigate_to_root_menu() (lands on Objects in root menu):
  R      → enter Objects submenu (now at All Filtered, index 0)
  D      → By Catalog (index 1)
  DD     → Recent     (index 2)
  DDD    → Obs Lists  (index 3)
  DDDD   → Custom     (index 4)
  DDDDD  → Name Search (index 5) ← confirmed by test_remote_entry in test_web_remote.py
  DDDDDD → Set Filters (index 6) ← see test_web_remote_filter.py
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

    # R = Objects submenu; D = By Catalog; R = enter By Catalog at Messier (0)
    # DD = Planets (2); R = enter
    press_keys_and_validate(
        driver,
        "RDRDDR",
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

    # R = Objects submenu; D = By Catalog; R = enter By Catalog at Messier (0)
    # DDDDD = Small bodies... (5); R = enter at Comets (0); R = enter
    press_keys_and_validate(
        driver,
        "RDRDDDDDRR",
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

    # R = Objects submenu; D = By Catalog; R = enter By Catalog at Messier (0)
    # D = NGC (1); R = enter
    press_keys_and_validate(
        driver,
        "RDRDR",
        {
            "ui_type": "UIObjectList",
            "title": "NGC",
        },
    )

    press_keys(driver, "ZL")  # back to root


@pytest.mark.web
def test_objects_by_catalog_asteroids(driver):
    """Objects > By Catalog > Asteroids opens the Asteroids object list."""
    login_to_remote(driver)
    navigate_to_root_menu(driver)

    # Small bodies... (5), then Asteroids (1)
    press_keys_and_validate(
        driver,
        "RDRDDDDDRDR",
        {
            "ui_type": "UIObjectList",
            "title": "Asteroids",
        },
    )

    press_keys(driver, "ZL")


# ---------------------------------------------------------------------------
# Objects > By Catalog > DSO... (nested submenu)
# ---------------------------------------------------------------------------


@pytest.mark.web
def test_objects_by_catalog_dso_submenu_entry(driver):
    """Objects > By Catalog > DSO... opens the DSO nested submenu."""
    login_to_remote(driver)
    navigate_to_root_menu(driver)

    # R = Objects submenu; D = By Catalog; R = enter By Catalog at Messier (0)
    # DDD = DSO... (3); R = enter
    press_keys_and_validate(
        driver,
        "RDRDDDR",
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
        "RDRDDDR",
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
        "RDRDDDR",  # enter DSO...
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

    # By Catalog: ..., DSO...(3), Stars...(4)
    # R = Objects submenu; D = By Catalog; R = enter By Catalog at Messier (0)
    # DDDD = Stars... (4); R = enter
    press_keys_and_validate(
        driver,
        "RDRDDDDR",
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
        "RDRDDDDR",
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
    # DDDD = Custom (index 4); R = enter UIRADecEntry
    press_keys_and_validate(
        driver,
        "RDDDDR",
        {
            "ui_type": "UIRADecEntry",
        },
    )

    press_keys(driver, "ZL")  # back to root


# ---------------------------------------------------------------------------
# Objects > Set Filters (relocated from the old top-level Filter menu in 2.6.0)
# ---------------------------------------------------------------------------


@pytest.mark.web
def test_objects_set_filters_is_last_item(driver):
    """Set Filters is the last Objects item (index 6) and opens the filter menu."""
    login_to_remote(driver)
    navigate_to_root_menu(driver)

    # R = Objects submenu at All Filtered (0)
    # DDDDDD = Set Filters (index 6); R = enter the Set Filters submenu at Reset All
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
