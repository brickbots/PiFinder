"""The width of the two columns of an object list row.

Each row has a left column (the label) and a right column (the LOCATE, NAME
or INFO text). The right column shows only when its text adds information.
Then the label is cut to the row width minus a reserve. Else the label gets
the full row width. On the focus row a cut label scrolls, and the right text
stays still. On the other rows a cut label ends with "…".
"""

import functools
from typing import Optional

import pytest
from PIL import Image, ImageDraw

# Installs the ``_()`` gettext builtin the UI modules rely on. MUST precede any
# ``PiFinder.ui`` import.
import PiFinder.i18n  # noqa: F401

from PiFinder.catalogs import Catalog, CatalogFilter, Catalogs
from PiFinder.composite_object import CompositeObject
from PiFinder.displays import get_display
from PiFinder.state import SharedStateObj, UIState
from PiFinder.ui import object_list
from PiFinder.ui.layout import list_layout
from PiFinder.ui.object_list import (
    DisplayModes,
    UIObjectList,
    cut_text,
    right_column_text,
)
from PiFinder.ui.ui_utils import TextLayouterScroll
from satellite_helpers import make_catalog, seed_groups

DISPLAYS = {128: "headless", 176: "headless_176", 320: "headless_320"}


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
    """A catalog of the ISS only."""
    seed_groups(tmp_path, files=("stations",))
    return make_catalog(tmp_path)


@functools.cache
def display(width: int):
    return get_display(DISPLAYS[width])


def row_list(width: int, scroll_speed: str = "Med") -> UIObjectList:
    """A UIObjectList with only what the row code uses, on a real display."""
    display_class = display(width)
    module = UIObjectList.__new__(UIObjectList)
    module.display_class = display_class
    module.display = display_class.device
    module.fonts = display_class.fonts
    module.colors = display_class.colors
    module.screen = Image.new("RGB", display_class.resolution)
    module.draw = ImageDraw.Draw(module.screen, mode="RGBA")
    module.config_object = FakeConfig({"text_scroll_speed": scroll_speed})
    module.ScrollTextLayout = functools.partial(
        TextLayouterScroll, draw=module.draw, color=module.colors.get(255)
    )
    module._current_item_index = 0
    module.last_item_index = -1
    module.item_text_scroll = None
    module.item_label_scroll = None
    return module


def row(
    module: UIObjectList,
    label: str,
    text: str,
    focus: bool,
    info_chars: Optional[int] = None,
):
    font = module.fonts.bold if focus else module.fonts.base
    return module.row_text(
        label, text, font, list_layout(module.display_class).text_x, info_chars
    )


# -- the right column text ----------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("text", ["", "   "])
def test_empty_right_text_is_not_drawn(text):
    assert right_column_text("M31", text) == ""


@pytest.mark.unit
@pytest.mark.parametrize(
    "label, text",
    [
        ("ISS (ZARYA)", "ISS (ZARYA)"),
        ("ISS (ZARYA)", "iss (zarya)"),
        ("ISS (ZARYA)", "ISS(ZARYA)"),
        ("Sirius", " sirius "),
        ("1998-067A", "1998 067A"),
    ],
)
def test_right_text_that_repeats_the_label_is_not_drawn(label, text):
    assert right_column_text(label, text) == ""


@pytest.mark.unit
def test_a_repeated_name_is_removed_and_the_other_names_stay():
    assert right_column_text("ISS (ZARYA)", "ISS (ZARYA), ISS") == "ISS"
    assert right_column_text("Vega", "Vega, Alpha Lyr") == "Alpha Lyr"
    assert right_column_text("Vega", "Alpha Lyr, Vega") == "Alpha Lyr"


@pytest.mark.unit
@pytest.mark.parametrize(
    "label, text",
    [
        ("M31", "Andromeda Galaxy, NGC224"),
        ("NGC7000", " 12.3  -4.5"),
        ("NGC7000", "m 4 ⇔120'"),
        ("25544", "ISS (ZARYA)"),
    ],
)
def test_new_right_text_is_kept_as_it_is(label, text):
    assert right_column_text(label, text) == text


@pytest.mark.unit
def test_cut_text():
    assert cut_text("NGC7000", 8) == "NGC7000"
    assert cut_text("ISS (ZARYA)", 8) == "ISS (ZA…"


# -- the width decision -------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "width, focus_chars, row_chars, full_focus_chars, full_row_chars",
    [(128, 8, 10, 16, 19), (176, 12, 13, 20, 22), (320, 18, 20, 26, 29)],
)
def test_label_space_with_and_without_the_right_column(
    width, focus_chars, row_chars, full_focus_chars, full_row_chars
):
    module = row_list(width)
    assert row(module, "M31", "Andromeda", True).label_chars == focus_chars
    assert row(module, "M31", "Andromeda", False).label_chars == row_chars
    assert row(module, "M31", "", True).label_chars == full_focus_chars
    assert row(module, "M31", "", False).label_chars == full_row_chars


@pytest.mark.unit
@pytest.mark.parametrize("width", [128, 320])
def test_satellite_name_label_in_name_mode_gets_the_full_width(width):
    module = row_list(width)
    for focus in (True, False):
        result = row(module, "ISS (ZARYA)", "ISS (ZARYA)", focus)
        assert result.text == ""
        assert not result.label_cut
        assert cut_text(result.label, result.label_chars) == "ISS (ZARYA)"


@pytest.mark.unit
def test_dso_row_is_as_before_at_128():
    """NGC in LOCATE mode: the right column starts one character after the
    label, and the old reserve of nine base characters stays."""
    module = row_list(128)
    bold = module.fonts.bold
    result = row(module, "NGC7000", " 12.3  -4.5", True)
    assert result.label_chars == (128 - 12 - 9 * module.fonts.base.width) // 7
    assert not result.label_cut
    assert result.text == " 12.3  -4.5"
    assert result.text_x == 12 + 8 * bold.width
    assert result.text_chars == (128 - result.text_x) // bold.width


@pytest.mark.unit
@pytest.mark.parametrize("width", [128, 320])
def test_long_label_with_a_right_column_is_cut_on_other_rows(width):
    module = row_list(width)
    label = "A VERY LONG SATELLITE NAME"
    result = row(module, label, " 12.3  -4.5", False)
    assert result.label_cut
    shown = cut_text(result.label, result.label_chars)
    assert len(shown) == result.label_chars and shown.endswith("…")
    # The right column starts one character after the label space.
    font = module.fonts.base
    assert result.text_x == result.label_x + (result.label_chars + 1) * font.width


@pytest.mark.unit
@pytest.mark.parametrize(
    "width, focus_chars, row_chars", [(128, 9, 12), (176, 13, 15), (320, 19, 22)]
)
def test_satellite_info_column_leaves_the_rest_of_the_row_to_the_name(
    width, focus_chars, row_chars
):
    """The INFO text of a satellite has at most six characters. The label
    gets the row minus that text and a gap of one character."""
    module = row_list(width)
    for focus, chars in ((True, focus_chars), (False, row_chars)):
        result = row(module, "ATLAS CENTAUR 2", "42° SE", focus, info_chars=6)
        assert result.label_chars == chars
        font = module.fonts.bold if focus else module.fonts.base
        assert result.text_x + 6 * font.width <= width
        # Without the width of the catalog the reserve is nine characters.
        usual = row(module, "ATLAS CENTAUR 2", "42° SE", focus)
        assert usual.label_chars < chars


# -- the focus row scroll -----------------------------------------------------


def focus(module: UIObjectList, label: str, text: str):
    result = row(module, label, text, True)
    module._draw_focus_row(result, module.fonts.bold, 255, 50)
    return result


@pytest.mark.unit
def test_long_label_scrolls_on_the_focus_row_and_the_right_text_stays():
    module = row_list(128)
    result = focus(module, "1998-067A", "ISS (ZARYA)")
    assert result.label_cut
    assert module.item_label_scroll is not None
    assert module.item_label_scroll.text == "1998-067A"
    assert module.item_label_scroll.width == result.label_chars
    assert module.item_text_scroll is None


@pytest.mark.unit
def test_short_label_does_not_scroll_and_the_right_text_scrolls():
    module = row_list(128)
    focus(module, "M31", "Andromeda Galaxy, NGC224")
    assert module.item_label_scroll is None
    assert module.item_text_scroll is not None
    assert module.item_text_scroll.text == "Andromeda Galaxy, NGC224"


@pytest.mark.unit
def test_satellite_name_in_name_mode_does_not_scroll_at_128():
    module = row_list(128)
    focus(module, "ISS (ZARYA)", "ISS (ZARYA)")
    assert module.item_label_scroll is None
    assert module.item_text_scroll is None


@pytest.mark.unit
def test_label_scroll_goes_on_while_the_locate_text_changes():
    module = row_list(128)
    focus(module, "A VERY LONG NAME", " 12.3  -4.5")
    scroller = module.item_label_scroll
    focus(module, "A VERY LONG NAME", " 12.4  -4.5")
    assert module.item_label_scroll is scroller
    # A new focus object makes the scroller again.
    module._current_item_index = 1
    focus(module, "A VERY LONG NAME", " 12.4  -4.5")
    assert module.item_label_scroll is not scroller


@pytest.mark.unit
def test_with_scrolling_off_the_focus_label_is_cut():
    module = row_list(128, scroll_speed="Off")
    focus(module, "1998-067A", "ISS (ZARYA)")
    assert module.item_label_scroll is None


# -- a rendered list ----------------------------------------------------------


def render_list(
    width: int,
    item_definition: dict,
    catalogs: Catalogs,
    mode: Optional[DisplayModes] = None,
):
    """Build a full UIObjectList on a headless display and draw one frame.

    With ``mode``, SQUARE goes to that display mode first. The title bar is
    left out: screen_update is not called.
    """
    display_class = get_display(DISPLAYS[width])
    shared_state = SharedStateObj()
    shared_state.set_ui_state(UIState())
    catalogs.set_catalog_filter(CatalogFilter(shared_state=shared_state))
    module = UIObjectList(
        display_class,
        None,
        shared_state,
        {},
        FakeConfig({"text_scroll_speed": "Off"}),
        catalogs,
        item_definition=item_definition,
    )
    while mode is not None and module.current_mode is not mode:
        module.cycle_display_mode()
    module.update()
    return module


def ngc_catalog() -> Catalog:
    catalog = Catalog("NGC", "NGC")
    for seq in (7000, 7009, 7293, 7331, 7662):
        catalog.add_object(
            CompositeObject(
                object_id=seq,
                catalog_code="NGC",
                sequence=seq,
                obj_type="Gx",
                names=[f"Name {seq}"],
            )
        )
    return catalog


def record_texts(monkeypatch) -> list:
    """Record the texts the object list draws, and draw them."""
    texts: list = []
    draw = object_list.draw_text_cached

    def recording(screen, pos, text, *args, **kwargs):
        texts.append(text)
        return draw(screen, pos, text, *args, **kwargs)

    monkeypatch.setattr(object_list, "draw_text_cached", recording)
    monkeypatch.setattr(UIObjectList, "screen_update", lambda self, *a, **k: None)
    return texts


@pytest.mark.unit
@pytest.mark.parametrize("width", [128, 320])
def test_satellite_list_draws_the_full_name(width, sat_catalog, monkeypatch):
    texts = record_texts(monkeypatch)
    module = render_list(
        width,
        {"objects": "catalog", "value": "SA"},
        Catalogs([sat_catalog]),
        mode=DisplayModes.NAME,
    )
    # Only the texts of a NAME-mode frame.
    texts.clear()
    module.update()
    # The focus row: the full name, and no right column.
    assert texts[-1] == "ISS (ZARYA)"
    assert not any("…" in text for text in texts)
    assert module.item_label_scroll is None
    assert module.item_text_scroll is None


@pytest.mark.unit
def test_satellite_info_list_at_128_cuts_names_at_12_characters(tmp_path, monkeypatch):
    seed_groups(tmp_path)
    cat = make_catalog(tmp_path)
    texts = record_texts(monkeypatch)
    module = render_list(128, {"objects": "catalog", "value": "SA"}, Catalogs([cat]))
    assert module.current_mode is DisplayModes.INFO
    names = {obj.names[0] for obj in cat.get_objects()}
    cut = [text for text in texts if text.endswith("…")]
    # The focus row has the wider bold font and 9 characters. With
    # scrolling off its label is cut too.
    assert sorted(len(text) for text in cut)[1:] == [12] * (len(cut) - 1)
    assert len(cut) > 1 and len(min(cut, key=len)) in (9, 12)
    for text in cut:
        assert any(name.startswith(text[:-1]) for name in names)
    # A name of 12 characters or fewer is drawn in full on the other rows.
    assert any(name in texts and 10 < len(name) <= 12 for name in names)


@pytest.mark.unit
@pytest.mark.parametrize("width", [128, 320])
def test_ngc_list_draws_the_designation_and_the_locate_text(width, monkeypatch):
    texts = record_texts(monkeypatch)
    module = render_list(
        width, {"objects": "catalog", "value": "NGC"}, Catalogs([ngc_catalog()])
    )
    assert module.current_mode is DisplayModes.LOCATE
    assert "NGC7000" in texts
    assert texts[-2:] == ["NGC7331", "--- ---"]
    assert module.item_text_scroll is not None
    assert module.item_text_scroll.text == "--- ---"
