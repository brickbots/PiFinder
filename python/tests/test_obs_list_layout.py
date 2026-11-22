"""
Layout tests for the observing-list picker (UIObsList).

The picker has no drawing loop of its own: UITextMenu.update draws it with the
resolution-flexible ``carousel_layout``, and the picker only overrides
``_draw_item_text`` so the selected row can scroll. On the 176x176 rev4 panel
that is 9 rows with the selection box on the centre line, not the 7 fixed rows
of the 128x128 panel.
"""

import pytest
from PIL import Image, ImageDraw

# Installs the _() gettext builtin the UI modules rely on; must precede ui imports.
import PiFinder.i18n  # noqa: F401

from PiFinder.displays import get_display
from PiFinder.ui.layout import carousel_layout
from PiFinder.ui.obs_list import UIObsList

pytestmark = pytest.mark.unit


class RecordingDraw:
    """Wraps a real ImageDraw and records rectangle / text calls."""

    def __init__(self, size):
        self._draw = ImageDraw.Draw(Image.new("RGB", size))
        self.rectangles = []
        self.texts = []

    def rectangle(self, xy, *args, **kwargs):
        self.rectangles.append(tuple(xy))
        return self._draw.rectangle(xy, *args, **kwargs)

    def text(self, xy, text, *args, **kwargs):
        self.texts.append((tuple(xy), text))
        return self._draw.text(xy, text, *args, **kwargs)

    # TextLayouterScroll (the selected row) draws through multiline_text.
    def multiline_text(self, xy, text, *args, **kwargs):
        self.texts.append((tuple(xy), text))
        return self._draw.multiline_text(xy, text, *args, **kwargs)


def _picker(display_name, n_items, index):
    """A UIObsList with only the attributes update() touches, built without
    the heavy UIModule.__init__ (no shared state, catalogs or obslist dir)."""
    display = get_display(display_name)
    ui = UIObsList.__new__(UIObsList)
    ui.display_class = display
    ui.colors = display.colors
    ui.fonts = display.fonts
    ui.draw = RecordingDraw(display.resolution)
    ui.clear_screen = lambda: None
    ui.screen_update = lambda *a, **k: None
    ui.config_object = type("Cfg", (), {"get_option": lambda self, k, d=None: d})()
    names = [f"List {i:02d}" for i in range(n_items)]
    ui.item_definition = {
        "select": "single",
        "items": [{"name": n, "value": f"/obslists/{n}.txt"} for n in names],
    }
    ui._menu_items = names
    ui._selected_values = []
    ui._current_item_index = index
    ui._scroll_text = None
    ui._scroll_item = None
    return ui, carousel_layout(display)


@pytest.mark.parametrize(
    "display_name, visible", [("headless", 7), ("headless_176", 9)]
)
def test_picker_fills_every_carousel_row(display_name, visible):
    ui, layout = _picker(display_name, n_items=20, index=10)
    ui.update()

    assert len(layout.rows) == visible
    # One text per carousel row, at the layout's positions, top -> bottom.
    assert [xy for xy, _ in ui.draw.texts] == [
        (layout.text_x, row.y) for row in layout.rows
    ]
    half = layout.center_index
    assert [t for _, t in ui.draw.texts] == [
        f"List {i:02d}" for i in range(10 - half, 10 + half + 1)
    ]


@pytest.mark.parametrize("display_name", ["headless", "headless_176"])
def test_selection_box_brackets_the_selected_row(display_name):
    ui, layout = _picker(display_name, n_items=20, index=10)
    ui.update()

    assert ui.draw.rectangles == [layout.selection_box]
    _x0, y0, x1, y1 = layout.selection_box
    assert x1 >= ui.display_class.resX - 1  # spans the full width
    focus = layout.rows[layout.center_index]
    assert y0 < focus.y < y1
    # The selected item is the one drawn on the focus row, by the scroller.
    assert ((layout.text_x, focus.y), "List 10") in ui.draw.texts
    assert ui._scroll_item == "List 10"


@pytest.mark.parametrize("display_name", ["headless", "headless_176"])
def test_short_list_draws_only_existing_items(display_name):
    ui, layout = _picker(display_name, n_items=3, index=0)
    ui.update()

    half = layout.center_index
    assert [xy for xy, _ in ui.draw.texts] == [
        (layout.text_x, row.y) for row in layout.rows[half : half + 3]
    ]
