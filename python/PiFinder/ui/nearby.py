#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module contains all the UI Module classes

"""
from enum import Enum
import numpy as np
from typing import List, Tuple, Optional

from PiFinder import config
from PiFinder.obj_types import OBJ_TYPE_MARKERS
from PiFinder.ui.base import UIModule
from PiFinder.ui.ui_utils import (
    TextLayouterScroll,
    TextLayouter,
    TextLayouterSimple,
    SpaceCalculatorFixed,
)
from PiFinder.catalogs import (
    CatalogTracker,
)
from PiFinder.calc_utils import aim_degrees
from PiFinder.catalog_utils import ClosestObjectsFinder
from PiFinder import utils
from PiFinder.catalogs import CompositeObject
from PiFinder.ui.catalog import UICatalog
from PIL import Image, ImageChops
import functools
import logging
from pathlib import Path
import os
from itertools import cycle
from sklearn.neighbors import BallTree


class Modes(Enum):
    """
    Enum for the different modes
    """

    LOCATE = 0  # shows distance to the target
    NAME = 1  # shows common names of the target
    INFO = 2  # shows magnitude, size, seen, ...


class UINearby(UIModule):
    """
    Search catalogs for object to find
    """

    __title__ = "NEARBY"
    __button_hints__ = {
        "B": "Mode",
        "D": "Clear",
        "ENT": "Locate",
    }
    _config_options = {}
    checkmark = "󰄵"
    checkmark_no = ""
    sun = "󰖨"
    bulb = "󰛨"
    star = ""
    ruler = ""

    def __init__(self, ui_catalog: UICatalog, *args):
        super().__init__(*args)
        self.max_objects = int(
            (self.display_class.resY - self.display_class.titlebar_height)
            / self.fonts.base.height
        )
        print(f"max_objects: {self.max_objects}")
        self.ui_catalog = ui_catalog
        self._config_options = ui_catalog._config_options
        self.catalog_tracker: CatalogTracker = ui_catalog.catalog_tracker
        self.screen_direction = config.Config().get_option("screen_direction")
        self.mount_type = config.Config().get_option("mount_type")
        self.simpleTextLayout = functools.partial(
            TextLayouterSimple,
            draw=self.draw,
            color=self.colors.get(255),
            embedded_color=True,
        )
        self.descTextLayout = TextLayouter(
            "",
            draw=self.draw,
            color=self.colors.get(255),
            colors=self.colors,
            font=self.fonts.base,
        )
        self.ScrollTextLayout = functools.partial(
            TextLayouterScroll, draw=self.draw, color=self.colors.get(255)
        )
        self.space_calculator = SpaceCalculatorFixed(self.fonts.base.line_length - 2)
        self.closest_objects = []
        self.closest_objects_text = []
        self.objects_balltree: Optional[Tuple[List[CompositeObject], BallTree]]
        self.closest_objects_finder = ClosestObjectsFinder()
        self.current_line = -1
        self.mode_cycle = cycle(Modes)
        self.current_mode = next(self.mode_cycle)
        self.fullred = self.rgb_to_embedded_color((255, 0, 0))
        self.halfred = self.rgb_to_embedded_color((125, 0, 0))
        self.current_nr_objects = 0
        self.filter()

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

    def update_config(self):
        self.ui_catalog.update_config()
        self.objects_balltree = None
        return True

    def update_object_info(self):
        self.update()

    def filter(self):
        self.catalog_tracker.filter()

    def format_az_alt(self, point_az, point_alt):
        if point_az >= 0:
            az_arrow_symbol = self._LEFT_ARROW
        else:
            point_az *= -1
            az_arrow_symbol = self._RIGHT_ARROW

        if point_az < 1:
            az_string = f"{az_arrow_symbol}{point_az:04.2f}"
        else:
            az_string = f"{az_arrow_symbol}{point_az:04.1f}"

        if point_alt >= 0:
            alt_arrow_symbol = self._DOWN_ARROW
        else:
            point_alt *= -1
            alt_arrow_symbol = self._UP_ARROW

        if point_alt < 1:
            alt_string = f"{alt_arrow_symbol}{point_alt:04.2f}"
        else:
            alt_string = f"{alt_arrow_symbol}{point_alt:04.1f}"

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

    def rgb_to_embedded_color(self, rgb_tuple):
        """
        Convert an RGB color tuple to embedded color values with ANSI escape codes.

        Args:
            rgb_tuple (tuple): A tuple containing RGB values in the range [0, 255].

        Returns:
            str: A string with embedded color ANSI escape codes.
        """
        # Ensure that RGB values are within the valid range [0, 255]
        r, g, b = [max(0, min(255, value)) for value in rgb_tuple]

        # Convert RGB to ANSI escape codes for foreground color
        escape_code = f"\x1b[38;2;{r};{g};{b}m"

        # Return the escape code
        return escape_code

    def update_closest(self):
        """
        get the current pointing solution and search the 10 closest objects
        to that location
        """
        if self.shared_state.solution():
            ra, dec = (
                self.shared_state.solution()["RA"],
                self.shared_state.solution()["Dec"],
            )
            if not self.objects_balltree:
                self.objects_balltree = (
                    self.closest_objects_finder.calculate_objects_balltree(
                        ra, dec, catalogs=self.catalog_tracker.catalogs
                    )
                )
            closest_objects = self.closest_objects_finder.get_closest_objects(
                ra,
                dec,
                self.max_objects + 1,
                self.objects_balltree,
            )
            self.current_nr_objects = len(closest_objects)
            self.closest_objects = closest_objects

    def create_locate_text(self) -> List[Tuple[str, TextLayouterSimple]]:
        result = []
        for obj in self.closest_objects:
            az, alt = aim_degrees(
                self.shared_state, self.mount_type, self.screen_direction, obj
            )
            if az:
                az_txt, alt_txt = self.format_az_alt(az, alt)
                distance = f"{az_txt} {alt_txt}"
            else:
                distance = "--.- --.-"
            obj_name = f"{obj.catalog_code}{obj.sequence}"
            _, obj_dist = self.space_calculator.calculate_spaces(
                obj_name, distance, empty_if_exceeds=False, trunc_left=True
            )
            obj_mag, obj_color = self._obj_to_mag_color(obj)
            entry = self.simpleTextLayout(
                obj_dist,
                font=self.fonts.base,
                color=obj_color,
            )
            result.append((obj.obj_type, entry))
        return result

    def create_name_text(self) -> List[Tuple[str, TextLayouterSimple]]:
        result = []
        for obj in self.closest_objects:
            full_name = f"{','.join(obj.names)}" if obj.names else ""
            obj_name = f"{obj.catalog_code}{obj.sequence}"
            _, obj_dist = self.space_calculator.calculate_spaces(
                obj_name, full_name, empty_if_exceeds=False, trunc_left=False
            )

            obj_mag, obj_color = self._obj_to_mag_color(obj)
            entry = self.simpleTextLayout(
                obj_dist,
                font=self.fonts.base,
                color=obj_color,
            )
            result.append((obj.obj_type, entry))
        return result

    def create_info_text(self) -> List[Tuple[str, TextLayouterSimple]]:
        result = []
        for obj in self.closest_objects:
            obj_mag, obj_color = self._obj_to_mag_color(obj)
            mag = f"m{obj_mag}" if obj_mag != 99 else ""
            size = f"{self.ruler}{obj.size.strip()}" if obj.size.strip() else ""
            check = f" {self.checkmark}" if obj.logged else ""
            full_name = f"{mag} {size}{check}"
            if len(full_name) > 12:
                full_name = f"{mag}{check}"
            obj_name = f"{obj.catalog_code}{obj.sequence}"
            _, obj_dist = self.space_calculator.calculate_spaces(
                obj_name, full_name, empty_if_exceeds=False, trunc_left=False
            )

            entry = self.simpleTextLayout(
                obj_dist,
                font=self.fonts.base,
                color=obj_color,
            )
            result.append((obj.obj_type, entry))
        return result

    def _obj_to_mag_color(self, obj: CompositeObject):
        """
        Extract the magnitude safely from the object and convert it to a color
        """
        try:
            obj_mag = float(obj.mag)
        except (ValueError, TypeError):
            obj_mag = 99
        return obj_mag, self.colors.get(self._interpolate_color(obj_mag))

    def invert_red_channel(self, image, top_left, bottom_right):
        # Convert PIL image to NumPy array
        img_array = np.array(image)

        # Invert the red channel in the specified region
        img_array[top_left[1] : bottom_right[1], top_left[0] : bottom_right[0], 0] = (
            255
            - img_array[top_left[1] : bottom_right[1], top_left[0] : bottom_right[0], 0]
        )

        # Convert the NumPy array back to PIL image
        image.paste(
            Image.fromarray(
                img_array[
                    top_left[1] : bottom_right[1], top_left[0] : bottom_right[0], :
                ]
            ),
            top_left,
        )

    def active(self):
        # trigger refilter
        super().active()
        self.filter()
        self.objects_balltree = None
        self.update_object_info()

    def update(self, force=True):
        utils.sleep_for_framerate(self.shared_state)
        self.update_closest()
        text_lines = []
        if self.current_mode == Modes.LOCATE:
            text_lines = self.create_locate_text()
        elif self.current_mode == Modes.NAME:
            text_lines = self.create_name_text()
        elif self.current_mode == Modes.INFO:
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

    def key_d(self):
        self.current_line = -1

    def key_long_c(self):
        self.key_long_d()

    def key_long_d(self):
        # long d called from main
        self.catalog_tracker.set_current_object(None)
        self.update_object_info()

    def key_b(self):
        self.current_mode = next(self.mode_cycle)

    def key_enter(self):
        """
        When enter is pressed, set the
        target
        """
        if self.current_line == -1:
            return
        cat_object: CompositeObject = self.closest_objects[self.current_line]
        self.ui_state.set_target_and_add_to_history(cat_object)
        if cat_object:
            self.ui_state.set_active_list_to_history_list()
            self.switch_to = "UILocate"

    def key_up(self):
        if self.current_line == -1:
            self.current_line = self.current_nr_objects - 1
        else:
            self.current_line = max(-1, self.current_line - 1)

    def key_down(self):
        if self.current_line + 1 == self.current_nr_objects:
            self.current_line = -1
        else:
            self.current_line = (self.current_line + 1) % self.current_nr_objects

    def push_cat(self, obj_amount):
        self.ui_catalog.push_cat(obj_amount)

    def push_near(self, obj_amount):
        self.ui_catalog.push_near(obj_amount)
