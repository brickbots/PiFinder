"""Tests for the per-catalog default display mode of the object list (#408).

A list of one catalog opens in its catalog's default display mode: NAME for
catalogs whose objects go by name (planets, comets, stars, doubles), LOCATE
for the others. SQUARE then cycles on from there in the usual order. Lists
that mix catalogs keep the LOCATE start.
"""

import pytest

from PiFinder.catalogs import (
    NAME_MODE_CATALOGS,
    Catalog,
    Catalogs,
    PlanetCatalog,
    default_display_mode_for,
)
from PiFinder.comet_catalog import CometCatalog
from PiFinder.ui.object_list import DisplayModes, UIObjectList

NAME_MODE = ["PL", "CM", "Str", "Nam", "SaA", "SaR", "TLK", "SaM", "RDS", "WDS"]
LOCATE_MODE = [
    "M",
    "NGC",
    "IC",
    "C",
    "Col",
    "Sh2",
    "H",
    "B",
    "Abl",
    "Arp",
    "Ta2",
    "Har",
    "EGC",
    "Lyn",
    "OBS",
]


def _object_list(item_definition: dict, catalogs: Catalogs) -> UIObjectList:
    """A UIObjectList with only what the display mode code uses.

    The full constructor needs a display, a config and shared state; the
    display mode methods read only these attributes.
    """
    module = UIObjectList.__new__(UIObjectList)
    module.item_definition = item_definition
    module.catalogs = catalogs
    module.jump_input_display = False
    module.last_item_index = 0
    module.update = lambda *args, **kwargs: None  # key_square redraws
    module._init_display_mode()
    return module


@pytest.fixture
def catalogs() -> Catalogs:
    return Catalogs([Catalog(code, code) for code in NAME_MODE + LOCATE_MODE])


@pytest.mark.unit
def test_registry():
    assert NAME_MODE_CATALOGS == frozenset(NAME_MODE)
    for code in NAME_MODE:
        assert default_display_mode_for(code) == "NAME"
        assert Catalog(code, code).default_display_mode == "NAME"
    for code in LOCATE_MODE:
        assert default_display_mode_for(code) == "LOCATE"
        assert Catalog(code, code).default_display_mode == "LOCATE"


@pytest.mark.unit
def test_registry_values_are_display_modes():
    assert DisplayModes[default_display_mode_for("SaR")] is DisplayModes.NAME
    assert DisplayModes[default_display_mode_for("NGC")] is DisplayModes.LOCATE


@pytest.mark.unit
def test_dynamic_catalogs_inherit_the_default():
    # Planets and comets are built at run time; their classes use the same
    # registry as every other Catalog.
    assert PlanetCatalog.default_display_mode is Catalog.default_display_mode
    assert CometCatalog.default_display_mode is Catalog.default_display_mode


@pytest.mark.unit
@pytest.mark.parametrize("catalog_code", NAME_MODE)
def test_names_catalog_opens_in_name_mode(catalog_code, catalogs):
    module = _object_list({"objects": "catalog", "value": catalog_code}, catalogs)
    assert module.current_mode is DisplayModes.NAME


@pytest.mark.unit
@pytest.mark.parametrize("catalog_code", ["M", "NGC", "IC", "Col"])
def test_deep_sky_catalog_opens_in_locate_mode(catalog_code, catalogs):
    module = _object_list({"objects": "catalog", "value": catalog_code}, catalogs)
    assert module.current_mode is DisplayModes.LOCATE


@pytest.mark.unit
def test_catalog_not_built_yet_uses_the_registry():
    # The comet catalog may be missing while it loads; the registry decides.
    module = _object_list({"objects": "catalog", "value": "CM"}, Catalogs([]))
    assert module.current_mode is DisplayModes.NAME


@pytest.mark.unit
def test_square_cycles_on_from_a_name_start(catalogs):
    module = _object_list({"objects": "catalog", "value": "SaR"}, catalogs)
    seen = [module.current_mode]
    for _ in range(4):
        module.key_square()
        seen.append(module.current_mode)
    assert seen == [
        DisplayModes.NAME,
        DisplayModes.INFO,
        DisplayModes.LOCATE,
        DisplayModes.NAME,
        DisplayModes.INFO,
    ]


@pytest.mark.unit
def test_square_cycles_on_from_a_locate_start(catalogs):
    module = _object_list({"objects": "catalog", "value": "NGC"}, catalogs)
    seen = [module.current_mode]
    for _ in range(3):
        module.key_square()
        seen.append(module.current_mode)
    assert seen == [
        DisplayModes.LOCATE,
        DisplayModes.NAME,
        DisplayModes.INFO,
        DisplayModes.LOCATE,
    ]


@pytest.mark.unit
@pytest.mark.parametrize("objects", ["catalogs.filtered", "recent", "custom"])
def test_mixed_lists_open_in_locate_mode(objects, catalogs):
    module = _object_list({"objects": objects}, catalogs)
    assert module.current_mode is DisplayModes.LOCATE
