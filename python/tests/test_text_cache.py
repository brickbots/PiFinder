import pytest
from PIL import Image, ImageChops, ImageDraw

from PiFinder.ui.base import UIModule
from PiFinder.ui.fonts import Fonts
from PiFinder.ui.ui_utils import draw_text_cached


def _draw_both(text, font, fill, xy=(5, 7)):
    background = (40, 10, 0)
    plain = Image.new("RGB", (176, 60), background)
    # The UI modules draw with mode="RGBA" (base.py).
    ImageDraw.Draw(plain, mode="RGBA").text(xy, text, font=font, fill=fill)
    cached = Image.new("RGB", (176, 60), background)
    draw_text_cached(cached, xy, text, font, fill)
    return plain, cached


@pytest.mark.unit
@pytest.mark.parametrize("width", [128, 176])
@pytest.mark.parametrize(
    "text",
    ["Messier", "NGC 7000", "Settings", "g j p q y", UIModule._CHECKMARK, "M 31 "],
)
def test_cached_text_matches_imagedraw(width, text):
    fonts = Fonts(screen_width=width)
    for font in (fonts.base, fonts.bold, fonts.large):
        for fill in ((255, 0, 0), (96, 0, 0)):
            plain, cached = _draw_both(text, font.font, fill)
            assert ImageChops.difference(plain, cached).getbbox() is None, (
                text,
                font.font.size,
                fill,
            )


@pytest.mark.unit
def test_cached_text_same_mask_for_another_colour():
    font = Fonts(screen_width=128).bold.font
    for fill in ((255, 0, 0), (128, 0, 0)):
        plain, cached = _draw_both("Catalogs", font, fill, xy=(0, 20))
        assert ImageChops.difference(plain, cached).getbbox() is None
