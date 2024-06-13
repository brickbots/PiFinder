#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module contains all the UI Module classes

"""

import copy
from enum import Enum
from typing import List, Tuple, Optional
from pathlib import Path
import os

from PIL import Image, ImageChops
from itertools import cycle
from sklearn.neighbors import BallTree

from PiFinder.obj_types import OBJ_TYPE_MARKERS
from PiFinder.ui.text_menu import UITextMenu
from PiFinder.ui.ui_utils import (
    TextLayouterSimple,
)

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

    NEAREST = 0  # By Distance to target
    CATALOG_SEQUENCE = 1  # By catalog/sequence


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

    def __init__(self, *args, **kwargs):
        # hack at our item definition here to allow re-use of UITextMenu
        item_definition = copy.copy(kwargs["item_definition"])
        item_definition["select"] = "single"
        item_definition["items"] = []
        kwargs["item_definition"] = item_definition

        super().__init__(*args, **kwargs)
        self.max_objects = int(
            (self.display_class.resY - self.display_class.titlebar_height)
            / self.fonts.base.height
        )
        self.screen_direction = self.config_object.get_option("screen_direction")
        self.mount_type = self.config_object.get_option("mount_type")

        self.filter()
        self._menu_items = self.catalogs.get_objects(only_selected=True, filtered=True)
        self.objects_balltree: Optional[Tuple[List[CompositeObject], BallTree]]
        self.closest_objects_finder = ClosestObjectsFinder()

        self.mode_cycle = cycle(DisplayModes)
        self.current_mode = next(self.mode_cycle)

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

    def format_az_alt(self, point_az, point_alt):
        if point_az >= 0:
            az_arrow_symbol = self._LEFT_ARROW
        else:
            point_az *= -1
            az_arrow_symbol = self._RIGHT_ARROW

        if point_az < 1:
            az_string = f"{az_arrow_symbol}{point_az:04.1f}"
        else:
            az_string = f"{az_arrow_symbol}{point_az:04.0f}"

        if point_alt >= 0:
            alt_arrow_symbol = self._DOWN_ARROW
        else:
            point_alt *= -1
            alt_arrow_symbol = self._UP_ARROW

        if point_alt < 1:
            alt_string = f"{alt_arrow_symbol}{point_alt:04.1f}"
        else:
            alt_string = f"{alt_arrow_symbol}{point_alt:04.0f}"

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

    def sortby_closest(self):
        """
        get the current pointing solution and search the 10 closest objects
        to that location if the new location is sufficiently different
        than the previous one.
        """
        if self.shared_state.solution():
            ra, dec = (
                self.shared_state.solution()["RA"],
                self.shared_state.solution()["Dec"],
            )
            if abs(ra - self._last_update_ra) + abs(dec - self._last_update_dec) > 2:
                self._last_update_ra = ra
                self._last_update_dec = dec
                if not self.objects_balltree:
                    self.objects_balltree = (
                        self.closest_objects_finder.calculate_objects_balltree(
                            ra, dec, catalogs=self.catalogs
                        )
                    )
                closest_objects = self.closest_objects_finder.get_closest_objects(
                    ra,
                    dec,
                    self.max_objects + 1,
                    self.objects_balltree,
                )
                self.current_nr_objects = len(closest_objects)
                self.sorted_objects = closest_objects

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

    def create_aka_text(self, obj: CompositeObject) -> Tuple[str, TextLayouterSimple]:
        full_name = f"{','.join(obj.names)}" if obj.names else ""
        return full_name

    def create_info_text(self, obj: CompositeObject) -> TextLayouterSimple:
        obj_mag = self._safe_obj_mag(obj)
        mag = f"m{obj_mag}" if obj_mag != 99 else ""
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
                    line_font = self.fonts.bold
                    line_pos = 25
                if line_number == 3:
                    line_color = obj_mag_color
                    line_font = self.fonts.bold
                    line_pos = 42
                if line_number == 4:
                    line_color = int(0.75 * obj_mag_color)
                    line_font = self.fonts.bold
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

                item_line = f"{item_name} {item_text}"

                # Type Marker
                marker = OBJ_TYPE_MARKERS.get(_menu_item.obj_type)
                if marker:
                    self.screen.paste(self.markers[marker], (0, line_pos + 2))

                self.draw.text(
                    (15, line_pos),
                    item_line,
                    font=line_font.font,
                    fill=self.colors.get(line_color),
                )

            line_number += 1

        return self.screen_update()

    def _update(self, force=True):
        utils.sleep_for_framerate(self.shared_state)
        self.update_closest()
        text_lines = []
        if self.current_mode == DisplayModes.LOCATE:
            text_lines = self.create_locate_text()
        elif self.current_mode == DisplayModes.NAME:
            text_lines = self.create_name_text()
        elif self.current_mode == DisplayModes.INFO:
            text_lines = self.create_info_text()

        self.clear_screen()
        line = self.display_class.titlebar_height
        # Draw the closest objects
        for obj_type, txt in text_lines:
            marker = OBJ_TYPE_MARKERS.get(obj_type)
            if marker:
                self.screen.paste(self.markers[marker], (0, line + 1))
            txt.draw((12, line - 1))
            line += self.fonts.base.height
        # Show inverted selection on object
        if self.current_line > -1:
            topleft = (
                0,
                self.display_class.titlebar_height
                + self.fonts.base.height * self.current_line,
            )
            bottomright = (
                self.display_class.resX,
                self.display_class.titlebar_height
                + self.fonts.base.height * (self.current_line + 1)
                + 1,
            )
            self.invert_red_channel(self.screen, topleft, bottomright)
        return self.screen_update()

    def key_star(self):
        """
        Switch display modes
        """
        self.current_mode = next(self.mode_cycle)

    def key_enter(self):
        """
        When enter is pressed, set the
        target
        """
        if self.current_line == -1:
            return
        cat_object: CompositeObject = self.sorted_objects[self.current_line]
        self.ui_state.set_target_and_add_to_history(cat_object)
        if cat_object:
            self.ui_state.set_active_list_to_history_list()
            self.switch_to = "UILocate"
