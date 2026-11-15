"""The view that an object list opens in: the sort order, the label and the
INFO-mode text that a catalog gives.

A catalog can give the sort order of its list (``Catalog.default_sort``) and
the INFO-mode text of its objects (``Catalog.list_info_text``). The satellite
list opens in "Next pass" order, with the name label, in INFO mode. Its INFO
text is the altitude and the compass direction of a satellite above the
horizon, and the local start time of the next visible pass of one below the
horizon. Other catalogs keep their view.
"""

import datetime
from pathlib import Path

import pytest
import pytz

# Installs the ``_()`` gettext builtin the UI modules rely on. MUST precede any
# ``PiFinder.ui`` import.
import PiFinder.i18n  # noqa: F401

import PiFinder.satellite_catalog as satellite_catalog
import PiFinder.satellites as satellites
from PiFinder.catalogs import (
    DEFAULT_SORTS,
    Catalog,
    CatalogFilter,
    Catalogs,
    default_sort_for,
)
from PiFinder.comet_catalog import CometCatalog
from PiFinder.composite_object import CompositeObject, MagnitudeObject
from PiFinder.displays import get_display
from PiFinder.state import Location, SharedStateObj, UIState
from PiFinder.ui import object_list
from PiFinder.ui.object_list import DisplayModes, SortOrder, UIObjectList

DATA = Path(__file__).parent / "data" / "satellites"
UP = satellite_catalog.RISE_MARK


class FakeConfig:
    """The two Config methods the object list uses, on a dict."""

    def __init__(self, options=None):
        self.options = dict(options or {})

    def get_option(self, option, default=None):
        return self.options.get(option, default)

    def set_option(self, option, value):
        self.options[option] = value


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


@pytest.fixture
def sat_catalog(tmp_path):
    text = (DATA / "25544.3le").read_text()
    elements, _errors = satellites.parse_elements(text)
    (tmp_path / "stations.tle").write_text(text)
    now = elements[0].epoch + datetime.timedelta(days=1)
    cat = satellite_catalog.SatelliteCatalog(
        FixedSharedState(now), data_directory=tmp_path, start_threads=False
    )
    cat._spawn_pass_worker = cat._run_pass_updates
    cat.do_timed_task()
    return cat


def ngc_catalog() -> Catalog:
    catalog = Catalog("NGC", "NGC")
    for seq in (7000, 7009, 7293):
        catalog.add_object(
            CompositeObject(
                object_id=seq,
                catalog_code="NGC",
                sequence=seq,
                obj_type="Gx",
                mag=MagnitudeObject([8.0]),
                names=[f"Name {seq}"],
            )
        )
    return catalog


def bare_list(item_definition: dict, catalogs: Catalogs, config=None):
    """A UIObjectList with only what the sort and label code uses."""
    module = UIObjectList.__new__(UIObjectList)
    module.item_definition = item_definition
    module.catalogs = catalogs
    module.config_object = config if config is not None else FakeConfig()
    return module


def full_list(item_definition: dict, catalogs: Catalogs, monkeypatch, config=None):
    """A full UIObjectList on the 128 px headless display."""
    monkeypatch.setattr(UIObjectList, "screen_update", lambda self, *a, **k: None)
    shared_state = SharedStateObj()
    shared_state.set_ui_state(UIState())
    catalogs.set_catalog_filter(CatalogFilter(shared_state=shared_state))
    return UIObjectList(
        get_display("headless"),
        None,
        shared_state,
        {},
        config or FakeConfig({"text_scroll_speed": "Off"}),
        catalogs,
        item_definition=item_definition,
    )


def satellite(alt=None, az=None, next_pass_ts=None) -> CompositeObject:
    return CompositeObject(
        catalog_code="SA",
        sequence=25544,
        names=["ISS (ZARYA)"],
        alt=alt,
        az=az,
        next_pass_ts=next_pass_ts,
    )


# -- the default sort hook ----------------------------------------------------


@pytest.mark.unit
def test_default_sort_registry():
    assert DEFAULT_SORTS == {"SA": "NEXT_PASS"}
    assert default_sort_for("SA") == "NEXT_PASS"
    for code in ("M", "NGC", "IC", "MP", "CM", "PL"):
        assert default_sort_for(code) is None
        assert Catalog(code, code).default_sort is None
    assert SortOrder[default_sort_for("SA")] is SortOrder.NEXT_PASS


@pytest.mark.unit
def test_dynamic_catalogs_use_the_registry():
    assert satellite_catalog.SatelliteCatalog.default_sort is Catalog.default_sort
    assert CometCatalog.default_sort is Catalog.default_sort


@pytest.mark.unit
def test_satellite_list_sorts_by_next_pass(sat_catalog):
    item = {"objects": "catalog", "value": "SA"}
    assert bare_list(item, Catalogs([sat_catalog]))._default_sort() is (
        SortOrder.NEXT_PASS
    )
    # Before the satellite catalog is built, the registry decides.
    assert bare_list(item, Catalogs([]))._default_sort() is SortOrder.NEXT_PASS


@pytest.mark.unit
@pytest.mark.parametrize("code", ["M", "NGC"])
def test_other_lists_sort_by_catalog(code):
    item = {"objects": "catalog", "value": code}
    module = bare_list(item, Catalogs([Catalog(code, code)]))
    assert module._default_sort() is SortOrder.CATALOG_SEQUENCE


@pytest.mark.unit
@pytest.mark.parametrize("objects", ["catalogs.filtered", "recent", "custom"])
def test_mixed_lists_sort_by_catalog(objects, sat_catalog):
    module = bare_list({"objects": objects}, Catalogs([sat_catalog]))
    assert module._default_sort() is SortOrder.CATALOG_SEQUENCE


@pytest.mark.unit
def test_satellite_list_opens_with_pass_selected(sat_catalog, monkeypatch):
    module = full_list(
        {"objects": "catalog", "value": "SA"}, Catalogs([sat_catalog]), monkeypatch
    )
    assert module.current_sort is SortOrder.NEXT_PASS
    sort_menu = module.marking_menu.left.callback
    assert sort_menu.down.value is SortOrder.NEXT_PASS
    assert sort_menu.down.selected
    assert not sort_menu.right.selected


@pytest.mark.unit
def test_a_user_sort_wins_over_the_default(sat_catalog, monkeypatch):
    module = full_list(
        {"objects": "catalog", "value": "SA"}, Catalogs([sat_catalog]), monkeypatch
    )
    sort_menu = module.marking_menu.left.callback
    assert module.mm_change_sort(sort_menu, sort_menu.right)
    assert module.current_sort is SortOrder.CATALOG_SEQUENCE
    # A rebuild of the list (a filter change, a satellite update) keeps it.
    module.refresh_object_list(force_update=True)
    module.active()
    assert module.current_sort is SortOrder.CATALOG_SEQUENCE
    assert sort_menu.right.selected
    assert not sort_menu.down.selected


@pytest.mark.unit
def test_ngc_list_opens_as_before(monkeypatch):
    module = full_list(
        {"objects": "catalog", "value": "NGC"}, Catalogs([ngc_catalog()]), monkeypatch
    )
    assert module.current_sort is SortOrder.CATALOG_SEQUENCE
    assert module.current_mode is DisplayModes.LOCATE
    assert module.current_label is None
    assert module.marking_menu.left.callback.right.selected


# -- the default label --------------------------------------------------------


@pytest.mark.unit
def test_satellite_list_starts_with_the_name_label(sat_catalog):
    module = bare_list({"objects": "catalog", "value": "SA"}, Catalogs([sat_catalog]))
    module._init_labels()
    assert module.current_label.key == "name"
    obj = sat_catalog.get_objects()[0]
    assert module.create_label_text(obj) == "ISS (ZARYA)"


@pytest.mark.unit
def test_a_stored_label_wins_over_the_name(sat_catalog):
    config = FakeConfig({object_list.LABEL_CONFIG_OPTION: {"SA": "norad"}})
    module = bare_list(
        {"objects": "catalog", "value": "SA"}, Catalogs([sat_catalog]), config
    )
    module._init_labels()
    assert module.current_label.key == "norad"


# -- the INFO-mode text of a catalog ------------------------------------------


@pytest.mark.unit
def test_a_catalog_gives_no_info_text_by_default():
    assert Catalog("M", "Messier").list_info_text(CompositeObject()) is None
    assert CometCatalog.list_info_text is Catalog.list_info_text


@pytest.mark.unit
@pytest.mark.parametrize(
    "alt, az, text",
    [
        (42.4, 135.0, "42° SE"),
        (7.6, 2.0, "8° N"),
        (89.9, 270.0, "90° W"),
    ],
)
def test_satellite_above_the_horizon_shows_altitude_then_compass(
    sat_catalog, alt, az, text
):
    obj = satellite(alt=alt, az=az, next_pass_ts=-alt)
    assert sat_catalog.list_info_text(obj) == text


@pytest.mark.unit
def test_satellite_below_the_horizon_shows_the_local_pass_start(sat_catalog):
    sat_catalog._zone = pytz.timezone("Europe/Brussels")
    start = datetime.datetime(2026, 11, 15, 20, 43, tzinfo=datetime.timezone.utc)
    obj = satellite(alt=-12.0, az=40.0, next_pass_ts=start.timestamp())
    # Brussels is one hour ahead of UTC in November.
    assert sat_catalog.list_info_text(obj) == UP + "21:43"


@pytest.mark.unit
def test_satellite_without_a_pass_or_a_position(sat_catalog):
    assert sat_catalog.list_info_text(satellite(-5.0, 10.0, None)) == "--"
    assert sat_catalog.list_info_text(satellite()) == "--"


@pytest.mark.unit
def test_the_rise_mark_is_in_the_device_fonts():
    # A glyph that a font does not have draws as the same box as U+10FFFD.
    display = get_display("headless")
    for font in (display.fonts.base.font, display.fonts.bold.font):
        missing = bytes(font.getmask("\U0010fffd"))
        assert bytes(font.getmask(UP)) != missing
        assert bytes(font.getmask("°")) != missing


@pytest.mark.unit
def test_the_position_update_sets_the_altitude(sat_catalog):
    obj = sat_catalog.get_objects()[0]
    assert obj.alt is not None and obj.az is not None
    sat = sat_catalog._tracked[obj.sequence]
    look = satellites.look_many(
        [sat],
        sat_catalog._topos(sat_catalog.shared_state.location()),
        sat_catalog.shared_state.datetime(),
    )[0]
    assert obj.alt == pytest.approx(look.alt)
    assert obj.az == pytest.approx(look.az)
    if obj.alt > 0:
        assert obj.next_pass_ts == pytest.approx(-obj.alt)


@pytest.mark.unit
def test_info_text_follows_the_position_update(sat_catalog):
    obj = sat_catalog.get_objects()[0]
    shared_state = sat_catalog.shared_state
    texts = set()
    for minutes in range(0, 24 * 60, 10):
        shared_state.dt = shared_state.dt + datetime.timedelta(minutes=10)
        sat_catalog.do_timed_task()
        texts.add(sat_catalog.list_info_text(obj))
        if obj.alt > 0:
            assert sat_catalog.list_info_text(obj).endswith(satellites.compass(obj.az))
        elif obj.next_pass_ts is not None:
            assert sat_catalog.list_info_text(obj).startswith(UP)
    # Over a day the ISS rises and sets: both kinds of text show.
    assert any(text.startswith(UP) for text in texts)
    assert any("°" in text for text in texts)


@pytest.mark.unit
def test_object_list_info_text_uses_the_catalog(sat_catalog):
    module = UIObjectList.__new__(UIObjectList)
    module.catalogs = Catalogs([sat_catalog, ngc_catalog()])
    sat = satellite(alt=30.0, az=180.0, next_pass_ts=-30.0)
    found: dict = {}
    assert module.create_info_text(sat, module._catalog_of(sat, found)) == "30° S"
    ngc = module.catalogs.get_catalog_by_code("NGC").get_objects()[0]
    assert module.create_info_text(ngc, module._catalog_of(ngc, found)) == (
        module.create_info_text(ngc)
    )
    assert module.create_info_text(ngc) == "m 8 "
    assert set(found) == {"SA", "NGC"}


# -- the satellite list opens in its view -------------------------------------


@pytest.mark.unit
def test_satellite_list_opens_in_the_altitude_view(sat_catalog, monkeypatch):
    texts: list = []
    draw = object_list.draw_text_cached

    def recording(screen, pos, text, *args, **kwargs):
        texts.append(text)
        return draw(screen, pos, text, *args, **kwargs)

    monkeypatch.setattr(object_list, "draw_text_cached", recording)
    module = full_list(
        {"objects": "catalog", "value": "SA"}, Catalogs([sat_catalog]), monkeypatch
    )
    assert module.current_mode is DisplayModes.INFO
    assert module.current_sort is SortOrder.NEXT_PASS
    assert module.current_label.key == "name"
    texts.clear()
    module.update()
    obj = module._menu_items_sorted[0]
    assert "Sort: Next pass" in texts
    # The focus row: the name, cut, and the INFO text of the catalog.
    assert any(text.startswith("ISS") for text in texts)
    assert module.item_text_scroll is not None
    assert module.item_text_scroll.text == sat_catalog.list_info_text(obj)
    # SQUARE still cycles the views.
    module.cycle_display_mode()
    assert module.current_mode is DisplayModes.LOCATE
