"""The labels of the left column of the object list.

A catalog can give a list of labels (``Catalog.label_options``). The object
list of such a catalog gets "ID" on the DOWN slot of its marking menu. The
"ID" submenu chooses the label, and the config stores the choice per
catalog code. The satellite catalog has three labels: the name, the NORAD
number and the COSPAR id.
"""

import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

# Installs the ``_()`` gettext builtin the UI modules rely on. MUST precede any
# ``PiFinder.ui`` import.
import PiFinder.i18n  # noqa: F401

import PiFinder.satellite_catalog as satellite_catalog
import PiFinder.satellites as satellites
from PiFinder.catalogs import Catalog, Catalogs, ObjectLabel
from PiFinder.comet_catalog import CometCatalog
from PiFinder.composite_object import CompositeObject
from PiFinder.state import Location
from PiFinder.ui.marking_menus import MarkingMenu
from PiFinder.ui.object_list import LABEL_CONFIG_OPTION, UIObjectList

DATA = Path(__file__).parent / "data" / "satellites"
ISS_NORAD = 25544
DEVICE_LINE_CHARS = 16


def iss_elements() -> satellites.SatElements:
    results, _errors = satellites.parse_elements((DATA / "25544.3le").read_text())
    return results[0]


NOW = iss_elements().epoch + datetime.timedelta(days=1)


class FixedSharedState:
    def __init__(self, dt):
        self.dt = dt
        self._location = Location(
            lat=50.85, lon=4.35, altitude=50.0, lock=True, timezone="Europe/Brussels"
        )

    def altaz_ready(self):
        return True

    def datetime(self):
        return self.dt

    def location(self):
        return self._location


class FakeConfig:
    """The two Config methods the object list uses, on a dict."""

    def __init__(self, options=None):
        self.options = dict(options or {})

    def get_option(self, option, default=None):
        return self.options.get(option, default)

    def set_option(self, option, value):
        self.options[option] = value


@pytest.fixture
def sat_catalog(tmp_path):
    (tmp_path / "stations.tle").write_text((DATA / "25544.3le").read_text())
    cat = satellite_catalog.SatelliteCatalog(
        FixedSharedState(NOW), data_directory=tmp_path, start_threads=False
    )
    cat._spawn_pass_worker = cat._run_pass_updates
    cat.do_timed_task()
    return cat


def _object_list(catalog_code: str, catalogs: Catalogs, config=None) -> UIObjectList:
    """A UIObjectList with only what the label code uses.

    The full constructor needs a display and shared state; the label methods
    read only these attributes.
    """
    module = UIObjectList.__new__(UIObjectList)
    module.item_definition = {"objects": "catalog", "value": catalog_code}
    module.catalogs = catalogs
    module.config_object = config if config is not None else FakeConfig()
    module.last_item_index = 0
    module._init_labels()
    return module


# -- the hook -----------------------------------------------------------------


@pytest.mark.unit
def test_a_catalog_has_no_labels_by_default():
    assert Catalog("M", "Messier").label_options() == []
    assert CometCatalog.label_options is Catalog.label_options


@pytest.mark.unit
def test_list_without_labels_shows_the_designation():
    module = _object_list("M", Catalogs([Catalog("M", "Messier")]))
    assert module.label_options == []
    assert module.current_label is None
    obj = CompositeObject(object_id=1, catalog_code="M", sequence=31)
    assert module.create_label_text(obj) == "M31"


@pytest.mark.unit
def test_list_of_mixed_catalogs_shows_the_designation(sat_catalog):
    module = UIObjectList.__new__(UIObjectList)
    module.item_definition = {"objects": "recent"}
    module.catalogs = Catalogs([sat_catalog])
    module.config_object = FakeConfig()
    module._init_labels()
    assert module.current_label is None
    iss = sat_catalog.get_object_by_sequence(ISS_NORAD)
    assert module.create_label_text(iss) == "SA25544"


@pytest.mark.unit
def test_a_catalog_can_give_its_own_labels():
    class LabelledCatalog(Catalog):
        def label_options(self):
            return [
                ObjectLabel("seq", "Seq", lambda obj: str(obj.sequence)),
                ObjectLabel("code", "Code", lambda obj: obj.catalog_code),
            ]

    module = _object_list("XX", Catalogs([LabelledCatalog("XX", "Test")]))
    obj = CompositeObject(object_id=1, catalog_code="XX", sequence=7)
    assert module.current_label.key == "seq"
    assert module.create_label_text(obj) == "7"


# -- the satellite labels -----------------------------------------------------


@pytest.mark.unit
def test_satellite_labels(sat_catalog):
    labels = sat_catalog.label_options()
    assert [(label.key, label.menu_name) for label in labels] == [
        ("name", "Name"),
        ("norad", "NORAD"),
        ("cospar", "COSPAR"),
    ]
    iss = sat_catalog.get_object_by_sequence(ISS_NORAD)
    assert [label.text(iss) for label in labels] == [
        "ISS (ZARYA)",
        "25544",
        "1998-067A",
    ]


@pytest.mark.unit
def test_satellite_list_shows_the_name_by_default(sat_catalog):
    module = _object_list("SA", Catalogs([sat_catalog]))
    assert module.current_label.key == "name"
    iss = sat_catalog.get_object_by_sequence(ISS_NORAD)
    assert module.create_label_text(iss) == "ISS (ZARYA)"


@pytest.mark.unit
def test_satellite_without_a_name_or_a_cospar_id_shows_its_number(sat_catalog):
    obj = CompositeObject(object_id=1, catalog_code="SA", sequence=99999, names=[])
    labels = {label.key: label for label in sat_catalog.label_options()}
    assert labels["name"].text(obj) == "99999"
    assert labels["cospar"].text(obj) == "99999"


@pytest.mark.unit
@pytest.mark.parametrize(
    "field, cospar",
    [
        ("98067A  ", "1998-067A"),
        ("57001B  ", "1957-001B"),
        ("99025ABC", "1999-025ABC"),
        ("00001A  ", "2000-001A"),
        ("24123AB ", "2024-123AB"),
        ("56999Z  ", "2056-999Z"),
        ("        ", ""),
        ("XXXXXXXX", ""),
    ],
)
def test_cospar_id_of_the_tle_field(field, cospar):
    assert satellites.cospar_from_tle_field(field) == cospar


@pytest.mark.unit
@pytest.mark.parametrize("suffix", ["tle", "3le", "json", "xml"])
def test_every_format_gives_the_cospar_id(suffix):
    results, errors = satellites.parse_elements((DATA / f"25544.{suffix}").read_text())
    assert errors == []
    assert results[0].cospar_id == "1998-067A"


@pytest.mark.unit
def test_details_screen_shows_the_three_ids(sat_catalog):
    """The details screen shows the names (the "aka" line) and the
    description sections."""
    iss = sat_catalog.get_object_by_sequence(ISS_NORAD)
    assert iss.names == ["ISS (ZARYA)"]
    text = "\n".join(desc for _label, desc in iss.composed_sections())
    lines = text.split("\n")
    assert "NORAD 25544" in lines
    assert "COSPAR 1998-067A" in lines
    for line in ("NORAD 25544", "COSPAR 1998-067A"):
        assert len(line) <= DEVICE_LINE_CHARS
    assert any(line.startswith("TLE ") and "d old" in line for line in lines)


# -- the marking menu ---------------------------------------------------------


@pytest.mark.unit
def test_satellite_list_has_id_on_down(sat_catalog):
    module = _object_list("SA", Catalogs([sat_catalog]))
    down = module._marking_menu_down()
    assert down.label == "ID"
    submenu = down.callback
    assert isinstance(submenu, MarkingMenu)
    assert [
        (slot.label, slot.value)
        for slot in (submenu.left, submenu.up, submenu.right, submenu.down)
    ] == [("Name", "name"), ("NORAD", "norad"), ("COSPAR", "cospar"), ("", None)]
    # The submenu shows the label of the list as selected.
    assert submenu.left.selected
    assert not submenu.up.selected


@pytest.mark.unit
@pytest.mark.parametrize("code", ["CM", "MP"])
def test_comet_and_asteroid_lists_keep_refresh_on_down(code):
    module = _object_list(code, Catalogs([Catalog(code, code)]))
    down = module._marking_menu_down()
    assert down.label == "Refresh"
    assert down.callback == module.mm_refresh_dynamic_catalog


@pytest.mark.unit
@pytest.mark.parametrize("code", ["M", "NGC", "PL"])
def test_other_lists_have_an_empty_down(code):
    module = _object_list(code, Catalogs([Catalog(code, code)]))
    assert module._marking_menu_down().label == ""


@pytest.mark.unit
def test_satellite_list_before_the_catalog_exists_keeps_refresh():
    # Without the catalog there are no labels, so the generic rule applies.
    module = _object_list("SA", Catalogs([]))
    assert module._marking_menu_down().label == "Refresh"


# -- choosing a label ---------------------------------------------------------


@pytest.mark.unit
def test_choosing_a_label_changes_the_left_column_and_is_stored(sat_catalog):
    config = FakeConfig({LABEL_CONFIG_OPTION: {"XX": "other"}})
    module = _object_list("SA", Catalogs([sat_catalog]), config)
    submenu = module._marking_menu_down().callback
    iss = sat_catalog.get_object_by_sequence(ISS_NORAD)

    assert module.mm_change_label(submenu, submenu.up) is True
    assert module.create_label_text(iss) == "25544"
    assert submenu.up.selected and not submenu.left.selected
    # The choice of another catalog stays.
    assert config.options[LABEL_CONFIG_OPTION] == {"XX": "other", "SA": "norad"}
    # The scrolling text of the focus line is made again.
    assert module.last_item_index == -1

    module.mm_change_label(submenu, submenu.right)
    assert module.create_label_text(iss) == "1998-067A"
    assert config.options[LABEL_CONFIG_OPTION]["SA"] == "cospar"


@pytest.mark.unit
def test_stored_label_is_read_back(sat_catalog):
    config = FakeConfig()
    first = _object_list("SA", Catalogs([sat_catalog]), config)
    submenu = first._marking_menu_down().callback
    first.mm_change_label(submenu, submenu.right)

    again = _object_list("SA", Catalogs([sat_catalog]), config)
    assert again.current_label.key == "cospar"
    assert again._marking_menu_down().callback.right.selected


@pytest.mark.unit
@pytest.mark.parametrize("stored", [{"SA": "gone"}, "not a dict", None])
def test_unknown_stored_label_gives_the_default(sat_catalog, stored):
    config = FakeConfig({LABEL_CONFIG_OPTION: stored})
    module = _object_list("SA", Catalogs([sat_catalog]), config)
    assert module.current_label.key == "name"


@pytest.mark.unit
def test_an_unknown_menu_value_changes_nothing(sat_catalog):
    config = FakeConfig()
    module = _object_list("SA", Catalogs([sat_catalog]), config)
    marking_menu = SimpleNamespace(select_none=lambda: None)
    item = SimpleNamespace(value="gone", selected=False)
    assert module.mm_change_label(marking_menu, item) is False
    assert module.current_label.key == "name"
    assert LABEL_CONFIG_OPTION not in config.options
