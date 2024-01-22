#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module contains all the UI Module classes

"""
import time
from typing import List

from PiFinder import config
from PiFinder.obj_types import OBJ_TYPES, OBJ_TYPE_MARKERS
from PiFinder.ui.base import UIModule
from PiFinder.ui.fonts import Fonts as fonts
from PiFinder.ui.ui_utils import (
    TextLayouterScroll,
    TextLayouter,
    TextLayouterSimple,
    SpaceCalculatorFixed,
)
from PiFinder.catalogs import (
    CatalogTracker,
)
from PiFinder.calc_utils import aim_degrees, FastAltAz
import functools
import logging

from PiFinder.db.observations_db import ObservationsDatabase
from PiFinder.catalogs import CompositeObject
from PiFinder.ui.fonts import Fonts as fonts


# Constants for display modes
DM_DESC = 0  # Display mode for description
DM_POSS = 1  # Display mode for POSS
DM_SDSS = 2  # Display mode for SDSS


class UIBrowsing(UIModule):
    """
    Search catalogs for object to find
    """

    __title__ = "TOURIST"
    __button_hints__ = {
        "B": "Image",
        "C": "Catalog",
        "D": "More",
    }
    _config_options = {
        "Catalogs": {
            "type": "multi_enum",
            "value": [],
            "options": [],
        },
        "Alt Limit": {
            "type": "enum",
            "value": 10,
            "options": ["None", 10, 20, 30],
        },
        "Scrolling": {
            "type": "enum",
            "value": "Med",
            "options": ["Off", "Fast", "Med", "Slow"],
        },
        "Magnitude": {
            "type": "enum",
            "value": "None",
            "options": ["None", 6, 7, 8, 9, 10, 11, 12, 13, 14],
        },
        "Obj Types": {
            "type": "multi_enum",
            "value": ["None"],
            "options": ["None"] + list(OBJ_TYPES.keys()),
        },
        "Observed": {"type": "enum", "value": "Any", "options": ["Any", "Yes", "No"]},
        "Push Cat.": {
            "type": "enum",
            "value": "",
            "options": ["Go", "CANCEL"],
            "callback": "push_cat",
        },
        "Near Obj.": {
            "type": "enum",
            "value": "",
            "options": ["CANCEL", 5, 10, 15, 20],
            "callback": "push_near",
        },
    }
    left_arrow = ""
    right_arrow = ""
    up_arrow = ""
    down_arrow = ""

    def __init__(self, catalog_tracker: CatalogTracker, *args):
        super().__init__(*args)
        self.catalog_tracker = catalog_tracker
        logging.debug(f"browsing has tracker: {catalog_tracker=}")
        self.screen_direction = config.Config().get_option("screen_direction")
        self.mount_type = config.Config().get_option("mount_type")
        self.simpleTextLayout = functools.partial(
            TextLayouterSimple, draw=self.draw, color=self.colors.get(255)
        )
        self.descTextLayout = TextLayouter(
            "",
            draw=self.draw,
            color=self.colors.get(255),
            colors=self.colors,
            font=fonts.base,
        )
        self.ScrollTextLayout = functools.partial(
            TextLayouterScroll, draw=self.draw, color=self.colors.get(255)
        )
        self.space_calculator = SpaceCalculatorFixed(fonts.base_width)
        self.texts = {
            "type-const": self.simpleTextLayout(
                "No Object Found", font=self.font_bold, color=self.colors.get(255)
            ),
        }
        self.closest_objects_text = []
        self.font_large = fonts.large
        self.catalog_tracker.filter()
        self.update_object_info()

    def update_config(self):
        if self.texts.get("aka"):
            self.texts["aka"].set_scrollspeed(self._get_scrollspeed_config())

        # Update catalog names if needed
        if self.catalog_names != self._config_options["Catalogs"]["value"]:
            self.message("Updating Cats.", 0)
            self.catalog_names = self._config_options["Catalogs"]["value"].copy()
            self.config_object.set_option("active_catalogs", self.catalog_names)
            self.catalog_tracker = CatalogTracker(
                self.catalog_names, self.shared_state, self._config_options
            )

        # re-filter if needed
        self.catalog_tracker.filter()

        # Reset any sequence....
        if not self.catalog_tracker.does_filtered_have_current_object():
            self.delete()

    def push_near(self, obj_amount):
        self._config_options["Near Obj."]["value"] = ""
        if obj_amount != "CANCEL":
            solution = self.shared_state.solution()
            if not solution:
                self.message("No Solve!", 1)
                return False

            # Filter the catalogs one last time
            self.catalog_tracker.filter(False)
            near_catalog = self.catalog_tracker.get_closest_objects(
                solution["RA"],
                solution["Dec"],
                obj_amount,
                catalogs=self.catalog_tracker.catalogs,
            )

    def update_object_info(self):
        self.update()

    def format_az_alt(self, point_az, point_alt):
        if point_az >= 0:
            az_arrow_symbol = self.right_arrow
        else:
            point_az *= -1
            az_arrow_symbol = self.left_arrow

        if point_az < 1:
            az_string = f"{az_arrow_symbol}{point_az:04.2f}"  # Zero-padded to 6 characters, including decimal point
        else:
            az_string = f"{az_arrow_symbol}{point_az:04.1f}"

        if point_alt >= 0:
            alt_arrow_symbol = self.up_arrow
        else:
            point_alt *= -1
            alt_arrow_symbol = self.down_arrow

        if point_alt < 1:
            alt_string = f"{alt_arrow_symbol}{point_alt:04.2f}"
        else:
            alt_string = f"{alt_arrow_symbol}{point_alt:04.1f}"

        return az_string, alt_string

    def update_closest(self):
        if self.shared_state.solution():
            closest_objects: List[
                CompositeObject
            ] = self.catalog_tracker.get_closest_objects(
                self.shared_state.solution()["RA"],
                self.shared_state.solution()["Dec"],
                11,
                catalogs=self.catalog_tracker.catalogs,
            )
            logging.debug(f"Closest objects: {closest_objects}")
            closest_objects_text = []
            for obj in closest_objects:
                az, alt = aim_degrees(
                    self.shared_state, self.mount_type, self.screen_direction, obj
                )
                if az:
                    az_txt, alt_txt = self.format_az_alt(az, alt)
                    distance = f"{az_txt} {alt_txt}"
                else:
                    distance = "---,- --,-"
                logging.debug(f"Closest object dist = {az}, {alt}")
                obj_name = (
                    obj.names[0] if obj.names else f"{obj.catalog_code} {obj.sequence}"
                )
                # layout the type - constellation line
                _, obj_dist = self.space_calculator.calculate_spaces(
                    obj_name, distance, empty_if_exceeds=False
                )
                entry = self.simpleTextLayout(
                    obj_dist,
                    font=fonts.base,
                    color=self.colors.get(255),
                )
                closest_objects_text.append(entry)
            logging.debug(f"Closest objects text: {closest_objects_text}")
            self.closest_objects_text = closest_objects_text

    def active(self):
        # trigger refilter
        super().active()
        self.catalog_tracker.filter()
        self.update_object_info()

    def update(self, force=True):
        time.sleep(1 / 30)
        self.update_closest()
        # Clear Screen
        self.draw.rectangle([0, 0, 128, 128], fill=self.colors.get(0))
        line = 22
        for txt in self.closest_objects_text:
            # logging.debug(f"Drawing closest object text: {txt=} on line {line=} on line {line=}")
            txt.draw((0, line))
            line += 10
        # logging.debug(f"Browsing update, nr text = {len(self.closest_objects_text)}, line={line}")
        # time.sleep(1)
        return self.screen_update()

    def key_d(self):
        self.descTextLayout.next()
        typeconst = self.texts.get("type-const")
        if typeconst and isinstance(typeconst, TextLayouter):
            typeconst.next()

    def delete(self):
        # long d called from main
        self.catalog_tracker.set_current_object(None)
        self.update_object_info()

    def key_c(self):
        # C is for catalog
        self.catalog_tracker.next_catalog()
        self.catalog_tracker.filter()
        self.update_object_info()
        self.object_display_mode = DM_DESC

    def key_long_c(self):
        self.delete()
        self.catalog_tracker.previous_catalog()
        self.catalog_tracker.filter()
        self.update_object_info()

    def key_b(self):
        if self.catalog_tracker.get_current_object() is None:
            self.object_display_mode = DM_DESC
        else:
            # switch object display text
            self.object_display_mode = (
                self.object_display_mode + 1 if self.object_display_mode < 2 else 0
            )
            self.update_object_info()
            self.update()

    def background_update(self):
        if time.time() - self.catalog_tracker.current_catalog.last_filtered > 60:
            self.catalog_tracker.filter()

    # duplicate code in Catalog, but this is a bit different
    def calc_object_altitude(self, obj):
        solution = self.shared_state.solution()
        location = self.shared_state.location()
        dt = self.shared_state.datetime()
        if location and dt and solution:
            aa = FastAltAz(
                location["lat"],
                location["lon"],
                dt,
            )
            obj_alt = aa.radec_to_altaz(
                obj.ra,
                obj.dec,
                alt_only=True,
            )
            return obj_alt

        return None

    def find_by_designator(self, designator):
        """
        Searches the loaded catalog for the designator
        """
        searching_for = designator.object_number
        if searching_for == 0:
            logging.debug("find by designator, objectnumber is 0")
            return False

        # Use all objects here, not filtered, so we can
        # surface any valid object in the catalog
        if searching_for in self.catalog_tracker.current_catalog.cobjects:
            self.catalog_tracker.set_current_object(searching_for)
            return True
        else:
            logging.debug("find by designator, no match found")
            self.catalog_tracker.set_current_object(None)
            self.catalog_tracker.get_designator().set_number(searching_for)
        return False

    def key_number(self, number):
        self.update_object_info()

    def key_enter(self):
        """
        When enter is pressed, set the
        target
        """
        cat_object: CompositeObject = self.catalog_tracker.get_current_object()
        if cat_object:
            self.ui_state["target"] = cat_object
            if len(self.ui_state["history_list"]) == 0:
                self.ui_state["history_list"].append(self.ui_state["target"])
            elif self.ui_state["history_list"][-1] != self.ui_state["target"]:
                self.ui_state["history_list"].append(self.ui_state["target"])

            self.ui_state["active_list"] = self.ui_state["history_list"]
            self.switch_to = "UILocate"

    def scroll_obj(self, direction):
        """
        Looks for the next object up/down
        sets the sequence and object
        """
        if self.catalog_tracker.current_catalog.get_filtered_count() == 0:
            return
        self.catalog_tracker.next_object(direction)
        self.update_object_info()

    def change_fov(self, direction):
        pass

    def key_up(self):
        pass

    def key_down(self):
        pass
