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
import functools
import math as math

from PIL import Image, ImageChops
from itertools import cycle

from PiFinder.obj_types import OBJ_TYPE_MARKERS
from PiFinder.ui.text_menu import UITextMenu
from PiFinder.ui.object_details import UIObjectDetails

from PiFinder.calc_utils import aim_degrees
from PiFinder.catalog_utils import ClosestObjectsFinder
from PiFinder import utils
from PiFinder.catalogs import CompositeObject
from PiFinder.ui.ui_utils import (
    TextLayouterScroll,
    name_deduplicate,
)


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

    def __init__(self, *args, **kwargs) -> None:
        # hack at our item definition here to allow re-use of UITextMenu
        item_definition = copy.copy(kwargs["item_definition"])
        item_definition["select"] = "single"
        item_definition["items"] = []
        kwargs["item_definition"] = item_definition

        super().__init__(*args, **kwargs)
        self.screen_direction = self.config_object.get_option("screen_direction")
        self.mount_type = self.config_object.get_option("mount_type")

        self._menu_items: list[CompositeObject] = []

        # The object list can display objects from various sources
        # This key of the item definition controls where to get the
        # particular object list
        if item_definition["objects"] == "catalogs.filtered":
            self.filter()
            self._menu_items = self.catalogs.get_objects(
                only_selected=True, filtered=True
            )

        if item_definition["objects"] == "catalog":
            for catalog in self.catalogs.get_catalogs(only_selected=False):
                if catalog.catalog_code == item_definition["value"]:
                    self._menu_items = catalog.get_filtered_objects()

        if item_definition["objects"] == "custom":
            # item_definition must contian a list of CompositeObjects
            self._menu_items = item_definition["object_list"]

        self._menu_items_sorted = self._menu_items
        if len(self._menu_items) > 0:
            self.closest_objects_finder = ClosestObjectsFinder()
            self.closest_objects_finder.calculate_objects_balltree(
                objects=self._menu_items,
            )

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

        self.jump_to_number = CatalogSequence()
        self.jump_input_display = False
        self.ScrollTextLayout = functools.partial(
            TextLayouterScroll, draw=self.draw,
            color=self.colors.get(255)
        )
        self.last_item_index = -1
        self.item_text_scroll = None

    def filter(self):
        self.catalogs.filter_catalogs()

    def sort(self) -> None:
        self.message("Sorting...", 0.1)
        self.update()
        if self.current_sort == SortOrder.CATALOG_SEQUENCE:
            self._menu_items_sorted = self._menu_items
            self._current_item_index = 0

        if self.current_sort == SortOrder.NEAREST:
            if not self.shared_state.solution():
                self.message("No Solution Yet", 2)
            else:
                ra, dec = (
                    self.shared_state.solution()["RA"],
                    self.shared_state.solution()["Dec"],
                )

                self._menu_items_sorted = (
                    self.closest_objects_finder.get_closest_objects(
                        ra,
                        dec,
                    )
                )
                self._current_item_index = 0

    def format_az_alt(self, point_az, point_alt):
        if point_az >= 0:
            az_arrow_symbol = self._RIGHT_ARROW
        else:
            point_az *= -1
            az_arrow_symbol = self._LEFT_ARROW

        if point_az > 100:
            point_az = 99

        if point_az < 10:
            az_string = f"{az_arrow_symbol}{point_az:03.1f}"
        else:
            az_string = f"{az_arrow_symbol}{point_az:03.0f}"

        if point_alt >= 0:
            alt_arrow_symbol = self._UP_ARROW
        else:
            point_alt *= -1
            alt_arrow_symbol = self._DOWN_ARROW

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
        dedups = name_deduplicate(obj.names, [f"{obj.catalog_code}{obj.sequence}"])
        result = ", ".join(dedups)
        return result

    def create_shortname_text(self, obj: CompositeObject) -> str:
        name = f"{obj.catalog_code}{obj.sequence}"
        return name
        # return f"{name: <7}"

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

    def _get_scrollspeed_config(self):
        scroll_dict = {
            "Off": 0,
            "Fast": TextLayouterScroll.FAST,
            "Med": TextLayouterScroll.MEDIUM,
            "Slow": TextLayouterScroll.SLOW,
        }
        scrollspeed = self._config_options["Scrolling"]["value"]
        return scroll_dict[scrollspeed]


    def _draw_scrollbar(self):
        # Draw scrollbar
        sbr_x = self.display.width
        sbr_y_start = self.display_class.titlebar_height + 1
        sbr_y = self.display.height
        total = self.get_nr_of_menu_items()
        one_item_height = max(1, int((sbr_y - sbr_y_start) / total))
        box_pos = (sbr_y - sbr_y_start) * self._current_item_index / (total-1)
        # print(f"{sbr_x=} {sbr_y=} {total=} {box_pos=} {one_item_height=}, {sbr_y_start=}, {self._current_item_index=}, {self.get_nr_of_menu_items()=}")

        self.draw.rectangle([sbr_x-1, sbr_y_start, sbr_x, sbr_y], fill=self.colors.get(128))
        self.draw.rectangle([sbr_x-1, sbr_y_start + box_pos - one_item_height // 2, sbr_x, sbr_y_start + box_pos + one_item_height // 2], fill=self.colors.get(255))


    def active(self):
        # trigger refilter
        super().active()
        self.filter()
        self.objects_balltree = None

    def update(self, force=False):
        # clear screen
        self.clear_screen()

        if len(self._menu_items) == 0:
            self.draw.text(
                (12, 42),
                "No objects",
                font=self.fonts.bold.font,
                fill=self.colors.get(255),
            )
            self.draw.text(
                (12, 60),
                "match filter",
                font=self.fonts.bold.font,
                fill=self.colors.get(255),
            )
            return self.screen_update()

        # Draw current selection hint
        self.draw.rectangle([-1, 60, 129, 80], outline=self.colors.get(128), width=1)
        line_number, line_pos = 0, 0
        line_color = None
        for i in range(self._current_item_index - 3, self._current_item_index + 4):
            if i >= 0 and i < len(self._menu_items_sorted):
                # figure out line position / color / font

                _menu_item = self._menu_items_sorted[i]
                obj_mag_color = self._obj_to_mag_color(_menu_item)

                is_focus = line_number == 3
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
                if is_focus:
                    line_color = obj_mag_color
                    line_font = self.fonts.bold
                    line_pos = 42
                if line_number == 4:
                    line_color = int(0.75 * obj_mag_color)
                    line_pos = 60
                if line_number == 5:
                    line_color = int(0.5 * obj_mag_color)
                    line_pos = 76
                if line_number == 6:
                    line_color = int(0.38 * obj_mag_color)
                    line_pos = 89

                # Offset for title
                line_pos += 20

                item_name = self.create_shortname_text(_menu_item)
                item_text = ""
                if self.current_mode == DisplayModes.LOCATE:
                    item_text = self.create_locate_text(_menu_item)
                elif self.current_mode == DisplayModes.NAME:
                    item_text = self.create_name_text(_menu_item)
                elif self.current_mode == DisplayModes.INFO:
                    item_text = self.create_info_text(_menu_item)

                # Type Marker
                line_bg = 32 if is_focus else 0
                marker = self.get_marker(_menu_item.obj_type, line_color, line_bg)
                if marker is not None:
                    self.screen.paste(marker, (0, line_pos + 2))

                # calculate start of both pieces of text
                begin_x = 12
                space = 0 if is_focus and not self.current_mode == DisplayModes.NAME else 1
                begin_x2 = begin_x + (len(item_name)+space)*line_font.width

                # draw first text
                self.draw.text(
                    (begin_x, line_pos),
                    item_name,
                    font=line_font.font,
                    fill=self.colors.get(line_color),
                )
                if is_focus:
                    # should scrolling second text be refreshed?
                    if not self.item_text_scroll or self.last_item_index != self._current_item_index or item_text != self.item_text_scroll.text:
                        self.last_item_index = self._current_item_index
                        self.item_text_scroll = self.ScrollTextLayout(
                            item_text,
                            font=self.fonts.bold,
                            width=math.floor((self.display.width - begin_x2)/line_font.width),
                            # scrollspeed=self._get_scrollspeed_config(),
                            scrollspeed=TextLayouterScroll.FAST,
                            )
                    # draw scrolling second text
                    self.item_text_scroll.draw((begin_x2, line_pos))
                else:
                    # draw non-scrolling second text
                    self.draw.text(
                        (begin_x2, line_pos),
                        item_text,
                        font=line_font.font,
                        fill=self.colors.get(line_color),
                    )

            line_number += 1

        if self.jump_input_display:
            self.message(
                str(self.jump_to_number),
                0.1,
                [30, 10, 93, 40],
            )
        self._draw_scrollbar()

        return self.screen_update()

    def scroll_to_sequence(
        self, sequence: int, start_at_top=True, direction="down"
    ) -> None:
        """
        Scrolls the list to the first item matching
        this number
        """
        if start_at_top:
            self._current_item_index = 0

        if direction == "down":
            search_list = list(
                range(self._current_item_index + 1, len(self._menu_items_sorted))
            )
        else:
            search_list = list(range(0, self._current_item_index - 1))
            search_list.reverse()

        for i in search_list:
            if self._menu_items_sorted[i].sequence == sequence:
                self._current_item_index = i
                break

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

    def refresh(self):
        self.last_item_index = -1

    def key_up(self):
        if self.jump_input_display:
            self.scroll_to_sequence(
                self.jump_to_number.object_number, start_at_top=False, direction="up"
            )
        else:
            super().key_up()

    def key_down(self):
        if self.jump_input_display:
            self.scroll_to_sequence(
                self.jump_to_number.object_number, start_at_top=False, direction="down"
            )
        else:
            super().key_down()

    def key_square(self):
        """
        Switch display modes
        """
        if self.jump_input_display:
            self.jump_input_display = False
            self.jump_to_number.reset_number()
        else:
            self.current_mode = next(self.mode_cycle)
            self.refresh()

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
        _menu_item = self._menu_items_sorted[self._current_item_index]

        object_item_definition = {
            "name": _menu_item.display_name,
            "class": UIObjectDetails,
            "object": _menu_item,
        }
        self.add_to_stack(object_item_definition)

    def key_number(self, number):
        self.jump_to_number.append_number(number)
        if str(self.jump_to_number) == "----":
            self.jump_input_display = False
            return

        self.jump_input_display = True

        # Check for match
        self.scroll_to_sequence(self.jump_to_number.object_number)

        self.update()


class CatalogSequence:
    """
    Holds the string that represents the numeric portion
    of a catalog entry
    """

    def __init__(self):
        self.object_number = 0
        self.width = 4
        self.field = self.get_designator()

    def append_number(self, number):
        number_str = str(self.object_number) + str(number)
        if len(number_str) > self.get_catalog_width():
            number_str = number_str[1:]
        self.object_number = int(number_str)
        self.field = self.get_designator()

    def set_number(self, number):
        self.object_number = number
        self.field = self.get_designator()

    def has_number(self):
        return self.object_number > 0

    def reset_number(self):
        self.object_number = 0
        self.field = self.get_designator()

    def increment_number(self):
        self.object_number += 1
        self.field = self.get_designator()

    def decrement_number(self):
        self.object_number -= 1
        self.field = self.get_designator()

    def get_catalog_name(self):
        return self.catalog_name

    def get_catalog_width(self):
        return self.width

    def get_designator(self):
        number_str = str(self.object_number) if self.has_number() else ""
        return f"{number_str:->{self.get_catalog_width()}}"

    def __str__(self):
        return self.field

    def __repr__(self):
        return self.field
