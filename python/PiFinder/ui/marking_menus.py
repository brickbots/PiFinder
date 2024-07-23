#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module contains classes and utilities
related to the marking menu system

"""

from math import pi

from PIL import Image, ImageDraw, ImageChops
from PiFinder.ui.fonts import Font


def render_menu_item(
    item_text: str,
    font_obj: Font,
    color: tuple[int, int, int],
    resolution,
    radius: int,
    base_angle: int,
) -> Image.Image:
    """
    Takes menu text and renders a curved
    version.

    text: string to render
    radius: inside radius of curve
    base_angle: The angle to offset the center of the
        rendered text.  0 = top, 90=right
    """

    char_angle = 360 / ((radius * pi) / font_obj.width)
    total_angle = char_angle * len(item_text)
    start_angle = base_angle - (total_angle / 2)
    char_pos = int(((radius + font_obj.height) / 2) + (font_obj.width / 2))

    return_image = Image.new("RGB", resolution)

    for i, _c in enumerate(item_text):
        _c_image = Image.new("RGB", resolution)
        _c_draw = ImageDraw.Draw(_c_image)
        _c_draw.text((char_pos, 0), _c, font=font_obj.font, fill=color)
        _c_image.rotate(start_angle + (char_angle * i))
        return_image = ImageChops.add(return_image, _c_image)

    return return_image
