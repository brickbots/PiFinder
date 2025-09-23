import pytest

import PiFinder.i18n  # noqa: F401
from PiFinder.ui import menu_structure


@pytest.mark.smoke
def test_menu_valid():
    assert type(menu_structure.pifinder_menu) is dict


@pytest.mark.smoke
def test_important_top_level_menu_entries_exist():
    """Test that important top-level menu entries exist."""
    menu = menu_structure.pifinder_menu
    menu_items = menu["items"]

    menu_names = [item["name"] for item in menu_items]

    assert "Start" in menu_names
    assert "Chart" in menu_names
    assert "Objects" in menu_names


@pytest.mark.smoke
def test_important_catalog_entries_exist():
    """Test that important catalog entries exist under Objects menu."""
    menu = menu_structure.pifinder_menu

    objects_menu = None
    for item in menu["items"]:
        if item["name"] == "Objects":
            objects_menu = item
            break

    assert objects_menu is not None, "Objects menu not found"

    by_catalog_menu = None
    for item in objects_menu["items"]:
        if item["name"] == "By Catalog":
            by_catalog_menu = item
            break

    assert by_catalog_menu is not None, "By Catalog menu not found"

    catalog_names = [item["name"] for item in by_catalog_menu["items"]]

    assert "Planets" in catalog_names
    assert "Comets" in catalog_names
    assert "NGC" in catalog_names
    assert "Messier" in catalog_names

    stars_menu = None
    for item in by_catalog_menu["items"]:
        if item["name"] == "Stars...":
            stars_menu = item
            break

    assert stars_menu is not None, "Stars menu not found"

    star_catalog_names = [item["name"] for item in stars_menu["items"]]

    assert "SAC Doubles" in star_catalog_names
    assert "RASC Doubles" in star_catalog_names


@pytest.mark.smoke
def test_status_and_restart_menu_entries_exist():
    """Test that Status and Restart menu entries exist."""
    menu = menu_structure.pifinder_menu

    tools_menu = None
    for item in menu["items"]:
        if item["name"] == "Tools":
            tools_menu = item
            break

    assert tools_menu is not None, "Tools menu not found"

    tools_menu_names = [item["name"] for item in tools_menu["items"]]

    assert "Status" in tools_menu_names

    power_menu = None
    for item in tools_menu["items"]:
        if item["name"] == "Power":
            power_menu = item
            break

    assert power_menu is not None, "Power menu not found"

    power_menu_names = [item["name"] for item in power_menu["items"]]

    assert "Restart" in power_menu_names
