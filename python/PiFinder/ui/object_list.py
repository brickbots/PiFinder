#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module contains all the UI Module classes

"""

import copy
from enum import Enum
from typing import Union, Optional, Tuple
from pathlib import Path
import os
import functools
from functools import cache
import math as math

from PIL import Image, ImageChops
from itertools import cycle

from PiFinder.ui.marking_menus import MarkingMenuOption, MarkingMenu
from PiFinder.obj_types import OBJ_TYPE_MARKERS
from PiFinder.ui.text_menu import UITextMenu
from PiFinder.ui.object_details import UIObjectDetails

from PiFinder.calc_utils import aim_degrees
from PiFinder import utils
from PiFinder.composite_object import CompositeObject, MagnitudeObject
from PiFinder.nearby import Nearby
from PiFinder.catalogs import CatalogState
from PiFinder.ui.ui_utils import (
    TextLayouterScroll,
    name_deduplicate,
)
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:

    def _(a) -> Any:
        return a


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
    RA = 3  # By RA


class UIObjectList(UITextMenu):
    """
    Displayes a list of objects
    """

    __help_name__ = "object_list"
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
        self.catalog_info_1: str = ""
        self.catalog_info_2: str = ""
        self._was_loading: bool = False  # Track loading state to detect completion

        # Init display mode defaults
        self.mode_cycle = cycle(DisplayModes)
        self.current_mode = next(self.mode_cycle)

        # Initialize sort default
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
            TextLayouterScroll, draw=self.draw, color=self.colors.get(255)
        )
        self.last_item_index = -1
        self.item_text_scroll: Union[None, TextLayouterScroll] = None

        # Base marking menu
        marking_menu_down = MarkingMenuOption()

        # Add refresh option for comet catalog only
        if self.item_definition.get("objects") == "catalog" and self.item_definition.get("value") == "CM":
            marking_menu_down = MarkingMenuOption(
                label=_("Refresh"),
                callback=self.mm_refresh_comets
            )

        self.marking_menu = MarkingMenu(
            left=MarkingMenuOption(
                label=_("Sort"),
                callback=MarkingMenu(
                    up=MarkingMenuOption(),
                    left=MarkingMenuOption(
                        label=_("Nearest"), callback=self.mm_change_sort
                    ),
                    down=MarkingMenuOption(),
                    right=MarkingMenuOption(
                        label=_("Standard"), callback=self.mm_change_sort
                    ),
                ),
            ),
            down=marking_menu_down,
            right=MarkingMenuOption(label=_("Filter"), menu_jump="filter_options"),
        )

        if self.current_sort == SortOrder.CATALOG_SEQUENCE:
            self.marking_menu.left.callback.right.selected = True
        if self.current_sort == SortOrder.NEAREST:
            self.marking_menu.left.callback.left.selected = True
        if self.current_sort == SortOrder.RA:
            self.marking_menu.left.callback.down.selected = True

        # Update object list populates self._menu_items
        # Force update because this is the first time and we
        # need to get the object list always
        self.refresh_object_list(force_update=True)
        self.nearby = Nearby(self.shared_state)

    def refresh_object_list(self, force_update=False):
        """
        Called whenever the object list might need to be updated.
        Updated here means reloaded from filtered catalog sources
        where possible

        force_update ignores filter dirty flag
        """
        if not self.catalogs.catalog_filter.is_dirty() and not force_update:
            return

        self.catalogs.filter_catalogs()

        # The object list can display objects from various sources
        # This key of the item definition controls where to get the
        # particular object list
        if self.item_definition["objects"] == "catalogs.filtered":
            self._menu_items = self.catalogs.get_objects(
                only_selected=True, filtered=True
            )

        if self.item_definition["objects"] == "catalog":
            for catalog in self.catalogs.get_catalogs(only_selected=False):
                if catalog.catalog_code == self.item_definition["value"]:
                    self._menu_items = catalog.get_filtered_objects()
                    age = catalog.get_age()
                    self.catalog_info_2 = "" if age is None else str(round(age, 0))

        if self.item_definition["objects"] == "recent":
            self._menu_items = self.ui_state.recent_list()

        if self.item_definition["objects"] == "custom":
            # item_definition must contain a list of CompositeObjects
            self._menu_items = self.item_definition["object_list"]

        self.catalog_info_1 = str(self.get_nr_of_menu_items())
        self._menu_items_sorted = self._menu_items
        self.sort()

    def _get_catalog_status_message(self) -> Tuple[Optional[str], Optional[int]]:
        """
        Generate status message explaining why catalog might be empty.
        Returns tuple of (message, progress_percentage).
        Returns (None, None) if catalog is ready (empty is due to filtering).

        Also handles refreshing object list when catalog transitions to READY.
        """
        if self.item_definition.get("objects") != "catalog":
            return (None, None)

        catalog_code = self.item_definition.get("value")
        if not catalog_code:
            return (None, None)

        for catalog in self.catalogs.get_catalogs(only_selected=False):
            if catalog.catalog_code == catalog_code:
                status = catalog.get_status()

                # Handle state transitions - refresh immediately when transitioning to READY
                if (status.previous != CatalogState.READY and
                    status.current == CatalogState.READY):
                    self.refresh_object_list(force_update=True)

                # Extract progress if available
                progress = None
                if status.data and "progress" in status.data:
                    progress = status.data["progress"]

                # Map state to user-facing messages
                if status.current == CatalogState.READY:
                    return (None, None)
                elif status.current == CatalogState.DOWNLOADING:
                    return (
                        _("Downloading..."),  # TRANSLATORS: Status when catalog data is downloading
                        progress
                    )
                elif status.current == CatalogState.NO_GPS:
                    return (
                        _("No GPS lock"),  # TRANSLATORS: Status when waiting for GPS position
                        None
                    )
                elif status.current == CatalogState.CALCULATING:
                    return (
                        _("Calculating..."),  # TRANSLATORS: Status when computing object positions
                        progress
                    )
                elif status.current == CatalogState.ERROR:
                    return (_("Error"), None)  # TRANSLATORS: Generic error status
                else:
                    return (_("Loading..."), None)  # TRANSLATORS: Generic loading status

        return (None, None)

    def sort(self) -> None:
        message = _(
            _("Sorting by\n{sort_order}").format(
                sort_order=_("RA")
                if self.current_sort == SortOrder.RA
                else _("Catalog")
                if self.current_sort == SortOrder.CATALOG_SEQUENCE
                else _("Nearby")
            )
        )
        self.message(message, 0.1)
        self.update()

        if self.current_sort == SortOrder.NEAREST:
            if self.shared_state.solution() is None:
                self.message(_("No Solve Yet"), 1)
                self.current_sort = SortOrder.CATALOG_SEQUENCE
            else:
                if self.catalogs.catalog_filter:
                    self._menu_items = self.catalogs.catalog_filter.apply(
                        self._menu_items
                    )
                self.nearby.set_items(self._menu_items)
                self.nearby_refresh()
                self._current_item_index = 0

        if self.current_sort == SortOrder.CATALOG_SEQUENCE:
            self._menu_items_sorted = self._menu_items
            self._current_item_index = 0
        self.update()

    def nearby_refresh(self):
        self._menu_items_sorted = self.nearby.refresh()
        if self._menu_items_sorted is None:
            self._menu_items_sorted = self._menu_items
            self.message(_("No Solve Yet"), 1)

    def format_az_alt(self, point_az, point_alt):
        if point_az >= 0:
            az_arrow_symbol = self._RIGHT_ARROW
        else:
            point_az *= -1
            az_arrow_symbol = self._LEFT_ARROW

            # Check az arrow config
            if (
                self.config_object.get_option("pushto_az_arrows", "Default")
                == "Reverse"
            ):
                if az_arrow_symbol == self._LEFT_ARROW:
                    az_arrow_symbol = self._RIGHT_ARROW
                else:
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
        mag = f"m{obj_mag:2.0f}" if obj_mag != MagnitudeObject.UNKNOWN_MAG else "m--"
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
        return obj.mag.filter_mag

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
        scrollspeed = self.config_object.get_option("text_scroll_speed", "Med")
        return scroll_dict[scrollspeed]

    def _draw_scrollbar(self):
        # Draw scrollbar
        sbr_x = self.display.width
        sbr_y_start = self.display_class.titlebar_height + 1
        sbr_y = self.display.height
        total = self.get_nr_of_menu_items()
        one_item_height = max(1, int((sbr_y - sbr_y_start) / total))
        box_pos = (sbr_y - sbr_y_start) * (self._current_item_index) / (total)
        # print(f"{sbr_x=} {sbr_y=} {total=} {box_pos=} {one_item_height=}, {sbr_y_start=}, {self._current_item_index=}, {self.get_nr_of_menu_items()=}")

        self.draw.rectangle(
            (sbr_x - 1, sbr_y_start, sbr_x, sbr_y), fill=self.colors.get(128)
        )
        self.draw.rectangle(
            (
                sbr_x - 1,
                sbr_y_start + box_pos - one_item_height // 2,
                sbr_x,
                sbr_y_start + box_pos + one_item_height // 2,
            ),
            fill=self.colors.get(255),
        )

    def get_line_font_color_pos(
        self,
        line_number,
        menu_item,
        is_focus=False,
        sort_order: SortOrder = SortOrder.CATALOG_SEQUENCE,
    ):
        obj_mag_color = self._obj_to_mag_color(menu_item)

        line_font = self.fonts.base
        line_color = int(self.color_modifier(line_number, sort_order) * obj_mag_color)
        line_pos = self.line_position(line_number)

        if is_focus:
            line_color = obj_mag_color
            line_font = self.fonts.bold
        return line_font, line_color, line_pos

    @cache
    def color_modifier(self, line_number: int, sort_order: SortOrder):
        if sort_order == SortOrder.NEAREST:
            line_number_modifiers = [0.38, 0.5, 0.75, 0.8, 0.75, 0.5, 0.38]
        else:
            line_number_modifiers = [1, 0.75, 0.75, 0.5, 0.5, 0.38, 0.38]
        return line_number_modifiers[line_number]

    @cache
    def line_position(self, line_number, title_offset=20):
        line_number_positions = [0, 13, 25, 42, 60, 76, 89]
        return line_number_positions[line_number] + title_offset

    def active(self):
        # trigger refilter
        super().active()

        # check for new push_to
        if self.ui_state.new_pushto():
            self.refresh_object_list(force_update=True)
            self.ui_state.set_new_pushto(False)
            self.show_object_details(0)
        else:
            self.refresh_object_list()

    def update(self, force: bool = False) -> None:
        self.clear_screen()
        begin_x = 12

        # Check if loading just completed and refresh if so
        is_loading = self.catalogs.is_loading()
        if self._was_loading and not is_loading:
            # Loading just completed - force refresh to show new objects
            # Update flag BEFORE calling refresh to avoid infinite loop
            self._was_loading = False
            self.refresh_object_list(force_update=True)
        else:
            self._was_loading = is_loading

        # no objects to display
        if self.get_nr_of_menu_items() == 0:
            # Get catalog-specific status message if available
            status_msg, progress = self._get_catalog_status_message()

            # Re-check menu items in case refresh happened during status check
            if self.get_nr_of_menu_items() > 0:
                # Objects were loaded, continue with normal rendering
                pass
            elif status_msg:
                # Display status message on line 2
                self.draw.text(
                    (begin_x, self.line_position(2)),
                    status_msg,
                    font=self.fonts.bold.font,
                    fill=self.colors.get(255),
                )
                # Display progress percentage on line 3 if available
                if progress is not None:
                    self.draw.text(
                        (begin_x, self.line_position(3)),
                        f"{progress}%",
                        font=self.fonts.bold.font,
                        fill=self.colors.get(255),
                    )
                self.screen_update()
                return
            else:
                # No status message, show default "no objects" message
                self.draw.text(
                    (begin_x, self.line_position(2)),
                    _("No objects"),  # TRANSLATORS: no objects in object list (1/2)
                    font=self.fonts.bold.font,
                    fill=self.colors.get(255),
                )
                self.draw.text(
                    (begin_x, self.line_position(3)),
                    _("match filter"),  # TRANSLATORS: no objects in object list (2/2)
                    font=self.fonts.bold.font,
                    fill=self.colors.get(255),
                )
                self.screen_update()
                return

        # should we refresh the nearby list?
        if self.current_sort == SortOrder.NEAREST and self.nearby.should_refresh():
            self.nearby_refresh()

        # Draw sorting mode in empty space
        if self._current_item_index < 3:
            intensity: int = int(64 + ((2.0 - self._current_item_index) * 32.0))
            self.draw.text(
                (begin_x, self.line_position(0)),
                _("{catalog_info_1} obj").format(
                    catalog_info_1=self.catalog_info_1
                )  # TRANSLATORS: number of objects in object list
                + _(", {catalog_info_2}d old").format(
                    catalog_info_2=self.catalog_info_2
                )
                if self.catalog_info_2
                else "",  # TRANSLATORS: suffix to number of objects in object list (indicating age of catalog data)
                font=self.fonts.bold.font,
                fill=self.colors.get(intensity),
            )
            self.draw.text(
                (begin_x, self.line_position(1)),
                _("Sort: {sort_order}").format(
                    sort_order=_("Catalog")
                    if self.current_sort == SortOrder.CATALOG_SEQUENCE
                    else _("Nearby")
                ),
                font=self.fonts.bold.font,
                fill=self.colors.get(intensity),
            )
        # Draw current selection hint
        self.draw.rectangle((-1, 60, 129, 80), outline=self.colors.get(128), width=1)
        line_number, line_pos = 0, 0
        line_color = None
        for i in range(self._current_item_index - 3, self._current_item_index + 4):
            if i >= 0 and i < len(self._menu_items_sorted):
                _menu_item = self._menu_items_sorted[i]
                is_focus = line_number == 3

                item_name = self.create_shortname_text(_menu_item)
                item_text = ""
                if self.current_mode == DisplayModes.LOCATE:
                    item_text = self.create_locate_text(_menu_item)
                elif self.current_mode == DisplayModes.NAME:
                    item_text = self.create_name_text(_menu_item)
                elif self.current_mode == DisplayModes.INFO:
                    item_text = self.create_info_text(_menu_item)

                # figure out line position / color / font
                line_font, line_color, line_pos = self.get_line_font_color_pos(
                    line_number, _menu_item, is_focus=is_focus
                )

                # Type Marker
                line_bg = 32 if is_focus else 0
                marker = self.get_marker(_menu_item.obj_type, line_color, line_bg)
                if marker is not None:
                    self.screen.paste(marker, (0, line_pos + 2))

                # calculate start of both pieces of text
                begin_x = 12
                begin_x2 = begin_x + (len(item_name) + 1) * line_font.width

                # draw first text
                self.draw.text(
                    (begin_x, line_pos),
                    item_name,  # TODO I18N: Does this need to be translated?
                    font=line_font.font,
                    fill=self.colors.get(line_color),
                )
                if is_focus:
                    # should scrolling second text be refreshed?
                    if (
                        not self.item_text_scroll
                        or self.last_item_index != self._current_item_index
                        or item_text != self.item_text_scroll.text
                    ):
                        self.last_item_index = self._current_item_index
                        self.item_text_scroll = self.ScrollTextLayout(
                            item_text,  # TODO I18N: Does this need to be translated?
                            font=self.fonts.bold,
                            width=math.floor(
                                (self.display.width - begin_x2) / line_font.width
                            ),
                            scrollspeed=self._get_scrollspeed_config(),
                        )
                    # draw scrolling second text
                    self.item_text_scroll.draw((begin_x2, line_pos))
                else:
                    # draw non-scrolling second text
                    self.draw.text(
                        (begin_x2, line_pos),
                        item_text,  # TODO I18N: Does this need to be translated?
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

        self.screen_update()

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

    def cycle_display_mode(self):
        """
        Switch display modes
        """
        if self.jump_input_display:
            self.jump_input_display = False
            self.jump_to_number.reset_number()
        else:
            self.current_mode = next(self.mode_cycle)
            self.refresh()

    def show_object_details(self, object_index):
        """
        Adds the object details UI module for the object
        at object_index to the top of the stack.
        """
        _menu_item = self._menu_items_sorted[object_index]

        object_item_definition = {
            "name": _menu_item.display_name,
            "class": UIObjectDetails,
            "object": _menu_item,
            "object_list": self._menu_items_sorted,
            "label": "object_details",
        }
        self.add_to_stack(object_item_definition)

    def key_right(self):
        """
        When right is pressed, move to
        object info screen
        """
        nr_menu_items = self.get_nr_of_menu_items()
        if nr_menu_items < self._current_item_index or nr_menu_items == 0:
            return

        # turn off input box if it's there
        if self.jump_input_display:
            self.jump_input_display = False
            self.jump_to_number.reset_number()

        self.show_object_details(self._current_item_index)

    def key_number(self, number):
        self.jump_to_number.append_number(number)
        if str(self.jump_to_number) == "----":
            self.jump_input_display = False
            return

        self.jump_input_display = True

        # Check for match
        self.scroll_to_sequence(self.jump_to_number.object_number)

        self.update()

    def key_long_up(self):
        self.menu_scroll(-1)

    def key_long_down(self):
        self.menu_scroll(999999999999999999999999999)

    def mm_change_sort(self, marking_menu, menu_item):
        """
        Called to change sort order from MM
        """
        marking_menu.select_none()
        menu_item.selected = True

        if menu_item.label == _("Nearest"):
            self.current_sort = SortOrder.NEAREST
            self.nearby_refresh()
            self.sort()
            return True

        if menu_item.label == _("Standard"):
            self.current_sort = SortOrder.CATALOG_SEQUENCE
            self.sort()
            return True

        if menu_item.label == _("RA"):
            self.current_sort = SortOrder.RA
            self.sort()
            return True

    def mm_jump_to_filter(self, marking_menu, menu_item):
        pass

    def mm_refresh_comets(self, marking_menu, menu_item):
        """Force refresh of comet data from the internet"""
        catalog = self.catalogs.get_catalog_by_code("CM")
        if catalog and hasattr(catalog, 'refresh'):
            self.message(_("Refreshing..."), 1)
            catalog.refresh()
            # Clear the UI object list and refresh to show status
            self.refresh_object_list(force_update=True)
        return True


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
