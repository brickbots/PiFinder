#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module contains classes and utilities
related to the marking menu system

"""

from math import pi
from typing import Any, Union

from PIL import Image, ImageDraw, ImageChops
from PiFinder.ui.fonts import Font
from dataclasses import dataclass
from PiFinder.displays import DisplayBase


@dataclass
class MarkingMenuOption:
    enabled: bool = True  # Should this item be enabled/clickable
    label: str = ""
    selected: bool = False  # Draw highlighted?
    callback: Any = None
    menu_jump: Union[None, str] = None

    def __str__(self):
        return self.label

    def __repr__(self):
        return self.label


@dataclass
class MarkingMenu:
    down: MarkingMenuOption
    left: MarkingMenuOption
    right: MarkingMenuOption
    up: MarkingMenuOption = MarkingMenuOption(label="HELP")

    def select_none(self):
        self.up.selected = False
        self.down.selected = False
        self.left.selected = False
        self.right.selected = False


def render_marking_menu(
    bg_image: Image.Image,
    menu: MarkingMenu,
    display_class: DisplayBase,
    radius: int,
) -> Image.Image:
    """
    Renders the full marking menu on top of the BG image
    """

    _UP_ARROW = ""
    menu_items = [menu.up, menu.right, menu.down, menu.left]

    # Dim BG Image
    bg_draw = ImageDraw.Draw(bg_image, mode="RGBA")
    bg_draw.rectangle(
        [
            0,
            display_class.titlebar_height,
            display_class.resolution[0],
            display_class.resolution[1],
        ],
        fill=(0, 0, 0, 128),
    )

    # we need some padding here
    outer_radius = radius + display_class.fonts.large.height - 1
    inner_radius = radius - 3

    display_center = (
        display_class.resolution[0] / 2,
        display_class.resolution[1] / 2,
    )
    offset_center = (
        display_center[0],
        display_center[1] + int(display_class.titlebar_height / 2),
    )

    # cut circle out of BG image
    cutter = Image.new("RGB", display_class.resolution, (255, 255, 255))
    cutter_draw = ImageDraw.Draw(cutter)
    cutter_draw.circle(offset_center, outer_radius, outline=(0, 0, 0), fill=(0, 0, 0))
    cutter_draw.circle(
        offset_center, inner_radius, outline=(255, 255, 255), fill=(255, 255, 255)
    )
    bg_image = ImageChops.multiply(cutter, bg_image)

    # Draw menu
    menu_image = Image.new("RGB", display_class.resolution)

    # Pie slices....
    for i, menu_item in enumerate(menu_items):
        menu_draw = ImageDraw.Draw(menu_image)
        start_angle = i * 90 - 135
        end_angle = i * 90 + 90 - 135
        fill_color = display_class.colors.get(0)
        if menu_item.selected:
            fill_color = display_class.colors.get(64)

        menu_draw.pieslice(
            [
                display_center[0] - outer_radius,
                display_center[1] - outer_radius,
                display_center[0] + outer_radius,
                display_center[1] + outer_radius,
            ],
            start_angle,
            end_angle,
            fill_color,
            display_class.colors.get(128),
            1,
        )

        menu_text = render_menu_item(
            menu_item,
            i,
            display_class.fonts.large,
            display_class.colors.get(255),
            display_class.resolution,
            radius,
        )
        menu_image = ImageChops.add(menu_image, menu_text)

    # offset menu text down to center of menu area
    offset_menu_image = Image.new("RGB", display_class.resolution)
    offset_menu_image.paste(menu_image, (0, int(display_class.titlebar_height / 2)))

    # Inner Circle
    menu_draw = ImageDraw.Draw(offset_menu_image)
    menu_draw.circle(
        offset_center,
        inner_radius,
        outline=display_class.colors.get(128),
        fill=display_class.colors.get(0),
    )

    # Arrows
    arrow_image = Image.new("RGB", display_class.resolution)
    arrow_draw = ImageDraw.Draw(arrow_image)
    arrow_draw.text(
        (
            offset_center[0] - int(display_class.fonts.huge.width / 2),
            offset_center[1]
            - inner_radius
            - int(display_class.fonts.huge.height / 2)
            + 2,
        ),
        _UP_ARROW,
        font=display_class.fonts.huge.font,
        fill=display_class.colors.get(128),
    )
    offset_menu_image = ImageChops.add(offset_menu_image, arrow_image)
    base_arrow_image = arrow_image.copy()
    offset_menu_image = ImageChops.add(
        offset_menu_image, arrow_image.rotate(90, center=offset_center)
    )
    arrow_image = base_arrow_image.copy()
    offset_menu_image = ImageChops.add(
        offset_menu_image, arrow_image.rotate(180, center=offset_center)
    )
    arrow_image = base_arrow_image.copy()
    offset_menu_image = ImageChops.add(
        offset_menu_image, arrow_image.rotate(270, center=offset_center)
    )

    return ImageChops.add(bg_image, offset_menu_image)


def render_menu_item(
    menu_item: MarkingMenuOption,
    position: int,
    font_obj: Font,
    color: tuple[int, int, int],
    resolution: tuple[int, int],
    radius: int,
) -> Image.Image:
    """
    Takes menu text and renders a curved
    version.

    text: string to render
    position: integer reprenting MM position
        0 = top, 1 = right, 2 = bottom, 3 = left
    radius: inside radius of curve
    """
    base_angle = 90 * position

    char_angle = 360 / ((radius * pi * 2) / font_obj.width) - 1.5
    total_angle = char_angle * len(menu_item.label)
    start_angle = base_angle - (total_angle / 2) + (char_angle / 2)
    char_x_pos = int((resolution[0] / 2) - (font_obj.width / 2)) + 1
    char_y_pos = int((resolution[1] / 2) - radius) - font_obj.height

    if position == 2:
        # Bottom, we want text upright
        char_angle = char_angle * -1
        base_angle = 0
        start_angle = base_angle + (total_angle / 2) + (char_angle / 2)
        char_y_pos = int((resolution[1] / 2) + radius - 4)

    return_image = Image.new("RGB", resolution)

    for i, char_to_render in enumerate(menu_item.label.upper()):
        this_angle = (start_angle + (char_angle * (i))) * -1
        char_image = Image.new("RGB", resolution)
        char_draw = ImageDraw.Draw(char_image)

        char_draw.text(
            (char_x_pos, char_y_pos), char_to_render, font=font_obj.font, fill=color
        )
        return_image = ImageChops.add(return_image, char_image.rotate(this_angle))

    # char_draw = ImageDraw.Draw(return_image)
    # char_draw.line((0, resolution[1] / 2, resolution[0], resolution[1] / 2), fill=color)
    # char_draw.line((resolution[0] / 2, 0, resolution[0] / 2, resolution[1]), fill=color)
    return return_image
