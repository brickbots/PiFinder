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
import logging

from PiFinder.db.observations_db import ObservationsDatabase
from PiFinder.catalogs import CompositeObject, CatalogBuilder, Catalogs


# Constants for display modes
DM_DESC = 0  # Display mode for description
DM_POSS = 1  # Display mode for POSS
DM_SDSS = 2  # Display mode for SDSS


class UICatalog(UIModule):
    """
    Search catalogs for object to find
    """

    __title__ = "CATALOG"
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

    def __init__(self, *args):
        super().__init__(*args)
        self.catalog_names = self.config_object.get_option("active_catalogs")
        self._config_options["Catalogs"]["value"] = self.catalog_names.copy()
        self._config_options["Catalogs"]["options"] = self.config_object.get_option(
            "catalogs"
        )[:10]

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
        self.catalogs: Catalogs = CatalogBuilder().build()
        # print("in UI module, catalogs is", self.catalogs, self.catalogs.catalogs[0].get_objects())
        self.catalog_tracker = CatalogTracker(
            self.catalogs, self.shared_state, self._config_options
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
        """
        Generates designator layout object
        If there is a selected object which
        is in the catalog, but not in the filtered
        catalog, dim the designator out
        """
        designator_color = 255
        current_designator = self.catalog_tracker.get_designator()
        if (
            current_designator.has_number()
            and current_designator.object_number
            not in self.catalog_tracker.current_catalog.filtered_objects_seq
        ):
            designator_color = 128
        return self.simpleTextLayout(
            str(current_designator),
            font=fonts.large,
            color=self.colors.get(designator_color),
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

        # Update catalog names if needed
        if self.catalog_names != self._config_options["Catalogs"]["value"]:
            self.message("Updating Cats.", 0)
            self.catalog_names = self._config_options["Catalogs"]["value"].copy()
            self.config_object.set_option("active_catalogs", self.catalog_names)
            self.catalog_tracker = CatalogTracker(
                self.catalogs, self.shared_state, self._config_options
            )

        # re-filter if needed
        self.catalog_tracker.filter()

        # Reset any sequence....
        if not self.catalog_tracker.does_filtered_have_current_object():
            self.delete()

    def push_cat(self, obj_amount):
        self._config_options["Push Cat."]["value"] = ""
        if obj_amount == "Go":
            self.message("Catalog Pushed", 2)

            # Filter the catalog one last time
            self.catalog_tracker.filter()
            self.ui_state.set_observing_list(
                self.catalog_tracker.current_catalog.filtered_objects
            )
            self.ui_state.set_active_list_to_observing_list()
            self.ui_state.set_target_to_active_list_index(0)
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

            # Filter ALL the catalogs one last time
            self.catalog_tracker.filter(current=False)
            near_catalog = self.catalog_tracker.get_closest_objects(
                solution["RA"],
                solution["Dec"],
                obj_amount,
                catalogs=self.catalog_tracker.catalogs,
            )
            # self.shared_state["observing_list"] = self.catalog_tracker.get_objects(catalogs=self.catalog_tracker.catalog_names, filtered=True)
            self.ui_state.set_observing_list(near_catalog)
            self.ui_state.set_active_list_to_observing_list()
            self.ui_state.set_target_to_active_list_index(0)
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

        if self.object_display_mode == DM_DESC:
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

            aka_recs = self.catalog_tracker.current_catalog.get_object_by_sequence(
                cat_object.sequence
            )
            if aka_recs:
                self.texts["aka"] = self.ScrollTextLayout(
                    ", ".join(aka_recs.names),
                    font=fonts.base,
                    scrollspeed=self._get_scrollspeed_config(),
                )

            # NGC description....
            logs = self.observations_db.get_logs_for_object(cat_object)
            desc = cat_object.description.replace("\t", " ") + "\n"
            if len(logs) == 0:
                desc = desc + "** Not Logged"
            else:
                desc = desc + f"** {len(logs)} Logs"

            self.descTextLayout.set_text(desc)
            self.texts["desc"] = self.descTextLayout

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
        super().active()
        self.catalog_tracker.filter()
        target = self.ui_state.target()
        if target:
            self.catalog_tracker.set_current_object(
                target.sequence, target.catalog_code
            )
            self.update_object_info()

    def update(self, force=True):
        # Clear Screen
        self.draw.rectangle([0, 0, 128, 128], fill=self.colors.get(0))
        cat_object = self.catalog_tracker.get_current_object()

        if self.object_display_mode == DM_DESC or cat_object is None:
            # catalog and entry field i.e. NGC-311
            self.refresh_designator()
            desig = self.texts["designator"]
            desig.draw((0, 21))
            # print("Drawing designator", self.catalog_tracker.current_catalog, self.catalog_tracker.current_catalog.get_objects())

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

        # Use all objects here, not filtered, so we can
        # surface any valid object in the catalog
        if self.catalog_tracker.current_catalog.get_object_by_sequence(searching_for):
            self.catalog_tracker.set_current_object(searching_for)
            return True
        else:
            logging.debug("find by designator, no match found")
            self.catalog_tracker.set_current_object(None)
            self.catalog_tracker.get_designator().set_number(searching_for)
        return False

    def key_number(self, number):
        if self.object_display_mode == DM_DESC:
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
            self.ui_state.set_target_and_add_to_history(cat_object)
            self.ui_state.set_active_list_to_history_list()
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
        if self.object_display_mode == DM_DESC:
            self.scroll_obj(-1)
        else:
            self.change_fov(-1)

    def key_down(self):
        if self.object_display_mode == DM_DESC:
            self.scroll_obj(1)
        else:
            self.change_fov(1)
