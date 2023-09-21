#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module contains all the UI Module classes

"""
import time

from PiFinder import solver, obslog, cat_images
from PiFinder.obj_types import OBJ_TYPES
import PiFinder.utils as utils
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
from PiFinder import calc_utils
import functools
import sqlite3
import logging

from PiFinder.db.observations_db import ObservationsDatabase
from PiFinder.catalogs import CompositeObject


# Constants for display modes
DM_DESC = 0  # Display mode for description
DM_OBS = 1  # Display mode for observed
DM_POSS = 2  # Display mode for POSS
DM_SDSS = 3  # Display mode for SDSS


class UICatalog(UIModule):
    """
    Search catalogs for object to find
    """

    __title__ = "CATALOG"
    _config_options = {
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
            "options": ["None", 8, 9, 10, 11, 12, 13, 14, 15, 16, 17],
        },
        "Obj Types": {
            "type": "multi_enum",
            "value": ["None"],
            "options": ["None"] + list(OBJ_TYPES.keys()),
        },
        "Observed": {"type": "enum", "value": ["Any"], "options": ["Any", "Yes", "No"]},
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

    def __init__(self, *args):
        super().__init__(*args)
        self.catalog_names = self.config_object.get_option("catalogs")
        self.object_text = ["No Object Found"]
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
        self.space_calculator = SpaceCalculatorFixed(18)
        self.texts = {
            "type-const": self.simpleTextLayout(
                "No Object Found", font=self.font_bold, color=self.colors.get(255)
            ),
        }
        self.catalog_tracker = CatalogTracker(
            self.catalog_names, self.shared_state, self._config_options
        )
        self.observations_db = ObservationsDatabase()
        self.font_large = fonts.large

        self.object_display_mode = DM_DESC
        self.object_image = None

        self.fov_list = [1, 0.5, 0.25, 0.125]
        self.fov_index = 0

        self.catalog_tracker.filter()
        self.update_object_info()

    def _layout_designator(self):
        return self.simpleTextLayout(
            str(self.catalog_tracker.get_designator()),
            font=fonts.large,
            color=self.colors.get(255),
        )

    def refresh_designator(self):
        self.texts["designator"] = self._layout_designator()

    def _get_scrollspeed_config(self):
        scroll_dict = {
            "Off": 0,
            "Fast": TextLayouterScroll.FAST,
            "Med": TextLayouterScroll.MEDIUM,
            "Slow": TextLayouterScroll.SLOW,
        }
        scrollspeed = self._config_options["Scrolling"]["value"]
        return scroll_dict[scrollspeed]

    def update_config(self):
        if self.texts.get("aka"):
            self.texts["aka"].set_scrollspeed(self._get_scrollspeed_config())
        # re-filter if needed
        self.catalog_tracker.filter()

        # Reset any sequence....
        if not self.catalog_tracker.does_filtered_have_current_object():
            self.delete()

    def push_cat(self, obj_amount):
        self._config_options["Push Cat."]["value"] = ""
        if obj_amount == "Go":
            solution = self.shared_state.solution()
            if not solution:
                self.message("No Solve!", 1)
                return False
            self.message("Catalog Pushed", 2)

            # Filter the catalog one last time
            self.catalog_tracker.filter()
            self.ui_state["observing_list"] = self.catalog_tracker.get_objects(
                filtered=True
            )
            self.ui_state["active_list"] = self.ui_state["observing_list"]
            self.ui_state["target"] = self.ui_state["active_list"][0]
            return "UILocate"
        else:
            return False

    def push_near(self, obj_amount):
        self._config_options["Near Obj."]["value"] = ""
        if obj_amount != "CANCEL":
            solution = self.shared_state.solution()
            if not solution:
                self.message("No Solve!", 1)
                return False
            self.message(f"Near {obj_amount} Pushed", 2)

            # Filter the catalog one last time
            self.catalog_tracker.filter()
            near_catalog = self.catalog_tracker.get_closest_objects(
                solution["RA"],
                solution["Dec"],
                obj_amount,
                catalogs=self.catalog_tracker.catalog_names,
            )
            # self.ui_state["observing_list"] = self.catalog_tracker.get_objects(catalogs=self.catalog_tracker.catalog_names, filtered=True)
            self.ui_state["observing_list"] = near_catalog
            self.ui_state["active_list"] = self.ui_state["observing_list"]
            self.ui_state["target"] = self.ui_state["active_list"][0]
            return "UILocate"
        else:
            return False

    def update_object_info(self):
        """
        Generates object text and loads object images
        """
        cat_object: CompositeObject = self.catalog_tracker.get_current_object()
        if not cat_object:
            has_number = self.catalog_tracker.get_designator().has_number()
            self.texts = {}
            self.texts["type-const"] = TextLayouter(
                self.catalog_tracker.current_catalog.desc
                if not has_number
                else "Object not found",
                draw=self.draw,
                colors=self.colors,
                font=fonts.base,
                color=self.colors.get(255),
                available_lines=6,
            )
            return

        if self.object_display_mode in [DM_DESC, DM_OBS]:
            # text stuff....

            self.texts = {}
            # Type / Constellation
            object_type = OBJ_TYPES.get(cat_object.obj_type, cat_object.obj_type)

            # layout the type - constellation line
            _, typeconst = self.space_calculator.calculate_spaces(
                object_type, cat_object.const
            )
            self.texts["type-const"] = self.simpleTextLayout(
                typeconst,
                font=fonts.bold,
                color=self.colors.get(255),
            )
            # Magnitude / Size
            # try to get object mag to float
            try:
                obj_mag = float(cat_object.mag)
            except (ValueError, TypeError):
                obj_mag = "-" if cat_object.mag == "" else cat_object.mag

            size = str(cat_object.size).strip()
            size = "-" if size == "" else size
            spaces, magsize = self.space_calculator.calculate_spaces(
                f"Mag:{obj_mag}", f"Sz:{size}"
            )
            if spaces == -1:
                spaces, magsize = self.space_calculator.calculate_spaces(
                    f"Mag:{obj_mag}", size
                )
            if spaces == -1:
                spaces, magsize = self.space_calculator.calculate_spaces(obj_mag, size)

            self.texts["magsize"] = self.simpleTextLayout(
                magsize, font=fonts.bold, color=self.colors.get(255)
            )

            aka_recs = self.catalog_tracker.current_catalog.common_names.get(
                cat_object.object_id
            )
            if aka_recs:
                # aka_list = []
                # for rec in aka_recs:
                #     if rec["common_name"].startswith("M"):
                #         aka_list.insert(0, rec["common_name"])
                #     else:
                #         aka_list.append(rec["common_name"])
                self.texts["aka"] = self.ScrollTextLayout(
                    ", ".join(aka_recs),
                    font=fonts.base,
                    scrollspeed=self._get_scrollspeed_config(),
                )

            if self.object_display_mode == DM_DESC:
                # NGC description....
                desc = cat_object.description.replace("\t", " ")
                self.descTextLayout.set_text(desc)
                self.texts["desc"] = self.descTextLayout

            if self.object_display_mode == DM_OBS:
                logs = self.observations_db.get_logs_for_object(cat_object)
                if len(logs) == 0:
                    self.texts["desc"] = self.simpleTextLayout("No Logs")
                else:
                    self.texts["desc"] = self.simpleTextLayout(
                        f"Logged {len(logs)} times"
                    )
        else:
            # Image stuff...
            if self.object_display_mode == DM_SDSS:
                source = "SDSS"
            else:
                source = "POSS"

            solution = self.shared_state.solution()
            roll = 0
            if solution:
                roll = solution["Roll"]

            self.object_image = cat_images.get_display_image(
                cat_object,
                source,
                self.fov_list[self.fov_index],
                roll,
                self.colors,
            )

    def active(self):
        # trigger refilter
        self.catalog_tracker.filter()
        target = self.ui_state["target"]
        if target:
            self.catalog_tracker.set_current_object(
                target.sequence, target.catalog_code
            )
            self.update_object_info()

    def update(self, force=True):
        # Clear Screen
        self.draw.rectangle([0, 0, 128, 128], fill=self.colors.get(0))
        cat_object = self.catalog_tracker.get_current_object()

        if self.object_display_mode in [DM_DESC, DM_OBS] or cat_object is None:
            # catalog and entry field i.e. NGC-311
            self.refresh_designator()
            desig = self.texts["designator"]
            desig.draw((0, 21))

            # catalog counts....
            self.draw.text(
                (100, 21),
                f"{self.catalog_tracker.current_catalog.get_filtered_count()}",
                font=self.font_base,
                fill=self.colors.get(128),
            )
            self.draw.text(
                (100, 31),
                f"{self.catalog_tracker.current_catalog.get_count()}",
                font=self.font_base,
                fill=self.colors.get(96),
            )

            # Object TYPE and Constellation i.e. 'Galaxy    PER'
            typeconst = self.texts.get("type-const")
            if typeconst:
                typeconst.draw((0, 48))

            # Object Magnitude and size i.e. 'Mag:4.0   Sz:7"'
            magsize = self.texts.get("magsize")
            if magsize:
                if cat_object:
                    # check for visibility and adjust mag/size text color
                    obj_altitude = self.calc_object_altitude(cat_object)

                    if obj_altitude:
                        if obj_altitude < 10:
                            # Not really visible
                            magsize.set_color = self.colors.get(128)

                magsize.draw((0, 62))

            # Common names for this object, i.e. M13 -> Hercules cluster
            posy = 79
            aka = self.texts.get("aka")
            if aka:
                aka.draw((0, posy))
                posy += 11

            # Remaining lines with object description
            desc = self.texts.get("desc")
            if desc:
                desc.draw((0, posy))

        else:
            self.screen.paste(self.object_image)
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
                self.object_display_mode + 1 if self.object_display_mode < 3 else 0
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
            aa = calc_utils.FastAltAz(
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

        if searching_for in self.catalog_tracker.current_catalog.filtered_objects:
            self.catalog_tracker.set_current_object(searching_for)
            return True
        else:
            logging.debug("find by designator, no match found")
            self.catalog_tracker.set_current_object(None)
            self.catalog_tracker.get_designator().set_number(searching_for)
        return False

    def key_number(self, number):
        if self.object_display_mode in [DM_DESC, DM_OBS]:
            designator = self.catalog_tracker.get_designator()
            designator.append_number(number)
            # Check for match
            self.find_by_designator(designator)
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
        self.fov_index += direction
        if self.fov_index < 0:
            self.fov_index = 0
        if self.fov_index >= len(self.fov_list):
            self.fov_index = len(self.fov_list) - 1
        self.update_object_info()
        self.update()

    def key_up(self):
        if self.object_display_mode in [DM_DESC, DM_OBS]:
            self.scroll_obj(-1)
        else:
            self.change_fov(-1)

    def key_down(self):
        if self.object_display_mode in [DM_DESC, DM_OBS]:
            self.scroll_obj(1)
        else:
            self.change_fov(1)
