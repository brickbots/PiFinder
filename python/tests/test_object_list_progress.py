"""Compact progress-bar rendering used by populated dynamic catalogs."""

from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

from PiFinder.ui.object_list import UIObjectList


class Colors:
    def get(self, value):
        return (value, 0, 0)


def progress_list():
    ui = UIObjectList.__new__(UIObjectList)
    ui.display = SimpleNamespace(width=128)
    ui.fonts = SimpleNamespace(bold=SimpleNamespace(height=9))
    ui.colors = Colors()
    ui.line_position = lambda _line: 12
    image = Image.new("RGB", (128, 32))
    ui.draw = ImageDraw.Draw(image)
    return ui, image


@pytest.mark.unit
def test_determinate_progress_bar_draws_outline_and_half_fill():
    ui, image = progress_list()
    ui._draw_download_progress(50, 255)
    # Right-aligned 32px bar on a 128px display; midpoint is filled but its
    # far-right interior remains empty.
    assert image.getpixel((100, 18))[0] == 255
    assert image.getpixel((122, 18))[0] == 0


@pytest.mark.unit
def test_indeterminate_progress_bar_draws_activity(monkeypatch):
    ui, image = progress_list()
    monkeypatch.setattr("PiFinder.ui.object_list.time.monotonic", lambda: 0.0)
    ui._draw_download_progress(None, 255)
    red_pixels = sum(
        image.getpixel((x, y))[0] > 0
        for x in range(image.width)
        for y in range(image.height)
    )
    assert red_pixels > 2 * 32  # outline plus a moving interior segment
