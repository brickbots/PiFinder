#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module contains all the UI Module classes

"""

import copy
from enum import Enum
from typing import Union
from pathlib import Path
import os

from PIL import Image, ImageChops
from itertools import cycle

from PiFinder.obj_types import OBJ_TYPE_MARKERS
from PiFinder.ui.text_menu import UITextMenu

from PiFinder.calc_utils import aim_degrees
from PiFinder.catalog_utils import ClosestObjectsFinder
from PiFinder import utils
from PiFinder.catalogs import CompositeObject


class DisplayModes(Enum):
    """
    Enum for the different modes
    """

    LOCATE = 0  # shows distance to the target
    NAME = 1  # shows common names of the target
    INFO = 2  # shows magnitude, size, seen, ...


class SortOrder(Enum):
    """
    Enum for the different sort orders
    """

    CATALOG_SEQUENCE = 0  # By catalog/sequence
    NEAREST = 1  # By Distance to target


class UIObjectList(UITextMenu):
    """
    Displayes a list of objects
    """

    __title__ = "OBJECTS"
    checkmark = "󰄵"
    checkmark_no = ""
    sun = "󰖨"
    bulb = "󰛨"
    star = ""
    ruler = ""

    # These are the RA/DEC of the last 'nearest' sort
    _last_update_ra = 0
    _last_update_dec = 0

    def __init__(self, *args, **kwargs) -> None:
        # hack at our item definition here to allow re-use of UITextMenu
        item_definition = copy.copy(kwargs["item_definition"])
        item_definition["select"] = "single"
        item_definition["items"] = []
        kwargs["item_definition"] = item_definition

        super().__init__(*args, **kwargs)
        self.screen_direction = self.config_object.get_option("screen_direction")
        self.mount_type = self.config_object.get_option("mount_type")

        self.filter()
        self._menu_items = self.catalogs.get_objects(only_selected=True, filtered=True)
        self.closest_objects_finder = ClosestObjectsFinder()

        self.mode_cycle = cycle(DisplayModes)
        self.current_mode = next(self.mode_cycle)

        self.sort_cycle = cycle(SortOrder)
        self.current_sort = next(self.sort_cycle)

        marker_path = Path(utils.pifinder_dir, "markers")
        self.markers = {}
        render_size = (11, 11)
        for filename in os.listdir(marker_path):
            if filename.startswith("mrk_"):
                marker_code = filename[4:-4]
                _image = Image.new("RGB", render_size)
                _image.paste(
                    Image.open(f"{marker_path}/mrk_{marker_code}.png"),
                    (0, 0),
                )
                self.markers[marker_code] = ImageChops.multiply(
                    _image, Image.new("RGB", render_size, self.colors.get(255))
                )

    def filter(self):
        self.catalogs.filter_catalogs()

    def sort(self) -> None:
        self.filter()
        if self.current_sort == SortOrder.CATALOG_SEQUENCE:
            self._menu_items = self.catalogs.get_objects(
                only_selected=True, filtered=True
            )
            self._current_item_index = 0

        if self.current_sort == SortOrder.NEAREST:
            if not self.shared_state.solution():
                self.message("No Solution Yet", 2)
            else:
                ra, dec = (
                    self.shared_state.solution()["RA"],
                    self.shared_state.solution()["Dec"],
                )

                # If we have moved enough, update our anchor sort position
                if (
                    abs(ra - self._last_update_ra) + abs(dec - self._last_update_dec)
                    > 2
                ):
                    self._last_update_ra = ra
                    self._last_update_dec = dec

                    self.closest_objects_finder.calculate_objects_balltree(
                        self._last_update_ra,
                        self._last_update_ra,
                        objects=self.catalogs.get_objects(
                            only_selected=True, filtered=True
                        ),
                    )
                self._menu_items = self.closest_objects_finder.get_closest_objects(
                    ra,
                    dec,
                )
                self._current_item_index = 0

    def format_az_alt(self, point_az, point_alt):
        if point_az >= 0:
            az_arrow_symbol = self._LEFT_ARROW
        else:
            point_az *= -1
            az_arrow_symbol = self._RIGHT_ARROW

        if point_az > 100:
            point_az = 99

        if point_az < 10:
            az_string = f"{az_arrow_symbol}{point_az:03.1f}"
        else:
            az_string = f"{az_arrow_symbol}{point_az:03.0f}"

        if point_alt >= 0:
            alt_arrow_symbol = self._DOWN_ARROW
        else:
            point_alt *= -1
            alt_arrow_symbol = self._UP_ARROW

        if point_alt < 10:
            alt_string = f"{alt_arrow_symbol}{point_alt:03.1f}"
        else:
            alt_string = f"{alt_arrow_symbol}{point_alt:03.0f}"

        return az_string, alt_string

    def _interpolate_color(self, mag, min_mag=9, max_mag=16):
        """
        choose a color corresponding to the Magnitude
        """
        if mag <= min_mag:
            return 255
        elif mag >= max_mag:
            return 125
        else:
            return int(255 + ((125 - 255) / (16 - 9)) * (mag - 9))

    def create_name_text(self, obj: CompositeObject) -> str:
        """
        Returns the catalog code + sequence
        padded out to be 7 chars
        NGC0000
        """
        name = f"{obj.catalog_code}{obj.sequence}"
        return f"{name: <7}"

    def create_locate_text(self, obj: CompositeObject) -> str:
        az, alt = aim_degrees(
            self.shared_state, self.mount_type, self.screen_direction, obj
        )
        if az:
            az_txt, alt_txt = self.format_az_alt(az, alt)
            distance = f"{az_txt} {alt_txt}"
        else:
            distance = "--- ---"

        return distance

    def create_aka_text(self, obj: CompositeObject) -> str:
        full_name = f"{','.join(obj.names)}" if obj.names else ""
        return full_name

    def create_info_text(self, obj: CompositeObject) -> str:
        obj_mag = self._safe_obj_mag(obj)
        mag = f"m{obj_mag:2.0f}" if obj_mag != 99 else "m--"
        size = f"{self.ruler}{obj.size.strip()}" if obj.size.strip() else ""
        check = f" {self.checkmark}" if obj.logged else ""
        size_logged = f"{mag} {size}{check}"
        if len(size_logged) > 12:
            size_logged = f"{mag}{check}"
        return size_logged

    def _safe_obj_mag(self, obj: CompositeObject) -> float:
        """
        Extract the magnitude safely from the object
        """
        try:
            obj_mag = float(obj.mag)
        except (ValueError, TypeError):
            obj_mag = 99

        return obj_mag

    def _obj_to_mag_color(self, obj: CompositeObject) -> int:
        """
        Extract the magnitude safely from the object and convert it to a color
        """
        return self._interpolate_color(self._safe_obj_mag(obj))

    def active(self):
        # trigger refilter
        super().active()
        self.filter()
        self.objects_balltree = None

    def update(self, force=False):
        # clear screen
        self.draw.rectangle([0, 0, 128, 128], fill=self.colors.get(0))

        # Draw current selection hint
        # self.draw.line([0,80,128,80], width=1, fill=self.colors.get(32))
        self.draw.rectangle([0, 60, 128, 80], fill=self.colors.get(32))
        line_number = 0
        for i in range(self._current_item_index - 3, self._current_item_index + 4):
            if i >= 0 and i < len(self._menu_items):
                # figure out line position / color / font

                _menu_item = self._menu_items[i]
                obj_mag_color = self._obj_to_mag_color(_menu_item)

                line_font = self.fonts.base
                if line_number == 0:
                    line_color = int(0.38 * obj_mag_color)
                    line_pos = 0
                if line_number == 1:
                    line_color = int(0.5 * obj_mag_color)
                    line_pos = 13
                if line_number == 2:
                    line_color = int(0.75 * obj_mag_color)
                    line_pos = 25
                if line_number == 3:
                    line_color = obj_mag_color
                    line_font = self.fonts.bold
                    line_pos = 42
                if line_number == 4:
                    line_color = int(0.75 * obj_mag_color)
                    line_pos = 60
                if line_number == 5:
                    line_color = int(0.5 * obj_mag_color)
                    line_color = 192
                    line_pos = 76
                if line_number == 6:
                    line_color = int(0.38 * obj_mag_color)
                    line_pos = 89

                # Offset for title
                line_pos += 20

                item_name = self.create_name_text(_menu_item)
                if self.current_mode == DisplayModes.LOCATE:
                    item_text = self.create_locate_text(_menu_item)
                elif self.current_mode == DisplayModes.NAME:
                    item_text = self.create_name_text(_menu_item)
                elif self.current_mode == DisplayModes.INFO:
                    item_text = self.create_info_text(_menu_item)

                if line_number == 3:
                    item_line = f"{item_name}{item_text}"
                else:
                    item_line = f"{item_name} {item_text}"

                # Type Marker
                line_bg = 0
                if line_number == 3:
                    line_bg = 32
                marker = self.get_marker(_menu_item.obj_type, line_color, line_bg)
                if marker is not None:
                    self.screen.paste(marker, (0, line_pos + 2))

                self.draw.text(
                    (12, line_pos),
                    item_line,
                    font=line_font.font,
                    fill=self.colors.get(line_color),
                )

            line_number += 1

        return self.screen_update()

    def get_marker(
        self, obj_type: str, color: int, bgcolor: int
    ) -> Union[Image.Image, None]:
        """
        Returns the right marker for this object
        multiplied by the color

        returns None if no marker is found for this obj type
        """
        marker = OBJ_TYPE_MARKERS.get(obj_type)
        if marker is None:
            return None

        marker_img = self.markers[marker]

        # dim
        _img = Image.new("RGB", marker_img.size, self.colors.get(color))
        marker_img = ImageChops.multiply(marker_img, _img)

        # raise by bg
        _img = Image.new("RGB", marker_img.size, self.colors.get(bgcolor))
        marker_img = ImageChops.add(marker_img, _img)

        return marker_img

    def key_square(self):
        """
        Switch display modes
        """
        self.current_mode = next(self.mode_cycle)

    def key_plus(self):
        """
        Switch sort modes
        """
        self.current_sort = next(self.sort_cycle)
        self.sort()

    def key_right(self):
        """
        When right is pressed, move to
        object info screen
        """
        pass
