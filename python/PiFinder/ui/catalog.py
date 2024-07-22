#!/usr/bin/python
# -*- coding:utf-8 -*-
# mypy: ignore-errors
"""
This module contains all the UI Module classes

"""

import time

from PiFinder import cat_images
from PiFinder.catalog_utils import ClosestObjectsFinder
from PiFinder.obj_types import OBJ_TYPES
from PiFinder.ui.base import UIModule
from PiFinder.ui.ui_utils import (
    TextLayouterScroll,
    TextLayouter,
    TextLayouterSimple,
    SpaceCalculatorFixed,
    name_deduplicate,
)
from PiFinder import calc_utils
import functools
import logging

from PiFinder.db.observations_db import ObservationsDatabase
from PiFinder.catalogs import (
    CompositeObject,
    CatalogTracker,
    CatalogBuilder,
    Catalogs,
    PlanetCatalog,
)


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
            "value": list(OBJ_TYPES.keys()),
            "options": list(OBJ_TYPES.keys()),
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

        # Initialze Catalogs
        self.catalogs: Catalogs = CatalogBuilder().build()

        self.catalog_names = self.config_object.get_option("active_catalogs")
        self._config_options["Catalogs"]["value"] = self.catalog_names.copy()
        self._config_options["Catalogs"]["options"] = self.catalogs.get_codes(
            only_selected=False
        )

        self.object_text = ["No Object Found"]
        self.simpleTextLayout = functools.partial(
            TextLayouterSimple,
            draw=self.draw,
            color=self.colors.get(255),
            font=self.fonts.base,
        )
        self.descTextLayout: TextLayouter = TextLayouter(
            "",
            draw=self.draw,
            color=self.colors.get(255),
            colors=self.colors,
            font=self.fonts.base,
        )
        self.ScrollTextLayout = functools.partial(
            TextLayouterScroll,
            draw=self.draw,
            color=self.colors.get(255),
            font=self.fonts.base,
        )
        self.space_calculator = SpaceCalculatorFixed(18)
        self.texts = {
            "type-const": self.simpleTextLayout(
                "No Object Found",
                font=self.fonts.bold,
                color=self.colors.get(255),
            ),
        }
        logging.debug(f"Catalogs created: {self.catalogs}")
        logging.debug(
            f"Value:{self._config_options['Catalogs']['value']}, Options{self._config_options['Catalogs']['options']}"
        )
        self.catalog_tracker = CatalogTracker(
            self.catalogs, self.shared_state, self._config_options
        )
        self.catalog_tracker.select_catalogs(self._config_options["Catalogs"]["value"])
        self.observations_db = ObservationsDatabase()

        self.object_display_mode = DM_DESC
        self.object_image = None

        self.fov_list = [1, 0.5, 0.25, 0.125]
        self.fov_index = 0

        self.catalog_tracker.filter()
        self.closest_objects_finder = ClosestObjectsFinder()
        self.update_object_info()

    def add_planets(self, dt):
        """
        Since we can't calc planet positions until we know the date/time
        this is called once we have a GPS lock to add on the planets catalog
        """
        self.catalogs.remove("PL")

        # We need to feed through the planet catalog selection status
        # here so when it gets re-added we can re-select it if needed
        _select = "PL" in self._config_options["Catalogs"]["value"]
        self.catalogs.add(PlanetCatalog(dt), select=_select)
        self.catalog_tracker = CatalogTracker(
            self.catalogs, self.shared_state, self._config_options
        )

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
            not in self.catalog_tracker.get_current_catalog().filtered_objects_seq
        ):
            designator_color = 128
        return self.simpleTextLayout(
            str(current_designator),
            font=self.fonts.large,
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
        catalog_values = self._config_options["Catalogs"]["value"]
        if self.catalog_names != catalog_values:
            self.message("Updating Cats.", 0)
            self.catalog_names = catalog_values.copy()
            if len(self.catalog_names) == 0:
                self.catalog_names.append("M")
                catalog_values.append("M")
            self.config_object.set_option("active_catalogs", self.catalog_names)
            self.catalog_tracker.select_catalogs(self.catalog_names)

        # re-filter if needed
        self.catalog_tracker.filter()

        # Reset any sequence....
        # if not self.catalog_tracker.does_filtered_have_current_object():
        #     self.key_long_d()

    def push_cat(self, obj_amount):
        self._config_options["Push Cat."]["value"] = ""
        if obj_amount == "Go":
            self.message("Catalog Pushed", 2)

            # Filter the catalog one last time
            self.catalog_tracker.filter()
            self.ui_state.set_observing_list(
                self.catalog_tracker.get_current_catalog().filtered_objects
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
            self.catalog_tracker.filter()
            ra, dec = (
                self.shared_state.solution()["RA"],
                self.shared_state.solution()["Dec"],
            )
            self.objects_balltree = (
                self.closest_objects_finder.calculate_objects_balltree(
                    ra, dec, catalogs=self.catalog_tracker.catalogs
                )
            )
            near_objects = self.closest_objects_finder.get_closest_objects(
                ra,
                dec,
                obj_amount,
                self.objects_balltree,
            )
            self.ui_state.set_observing_list(near_objects)
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
            self.texts = {}
            self.texts["type-const"] = TextLayouter(
                (
                    self.catalog_tracker.get_current_catalog().desc
                    if not self.catalog_tracker.get_designator().has_number()
                    else "Object not found"
                ),
                draw=self.draw,
                colors=self.colors,
                font=self.fonts.base,
                color=self.colors.get(255),
                available_lines=6,
            )
            return

        if self.object_display_mode == DM_DESC:
            print("We're in DM_DESC")
            # text stuff....
            current_desig = str(self.catalog_tracker.get_designator())

            self.texts = {}
            # Type / Constellation
            object_type = OBJ_TYPES.get(cat_object.obj_type, cat_object.obj_type)

            # layout the type - constellation line
            _, typeconst = self.space_calculator.calculate_spaces(
                object_type, cat_object.const
            )
            self.texts["type-const"] = self.simpleTextLayout(
                typeconst,
                font=self.fonts.bold,
                color=self.colors.get(255),
            )
            # Magnitude / Size
            # try to get object mag to float

            obj_mag = cat_object.mag.calc_two_mag_representation()
            print(f"in desc: obj_mag: {obj_mag}")

            size = str(cat_object.size).strip()
            size = "-" if size == "" else size
            # Only construct mag/size if at least one is present
            magsize = ""
            if size != "-" or obj_mag != "-":
                spaces, magsize = self.space_calculator.calculate_spaces(
                    f"Mag:{obj_mag}", f"Sz:{size}"
                )
                if spaces == -1:
                    spaces, magsize = self.space_calculator.calculate_spaces(
                        f"Mag:{obj_mag}", size
                    )
                if spaces == -1:
                    spaces, magsize = self.space_calculator.calculate_spaces(
                        obj_mag, size
                    )
            print(f"in desc: magsize: {magsize}")

            self.texts["magsize"] = self.simpleTextLayout(
                magsize, font=self.fonts.bold, color=self.colors.get(255)
            )

            aka_recs = (
                self.catalog_tracker.get_current_catalog().get_object_by_sequence(
                    cat_object.sequence
                )
            )
            if aka_recs:
                # first deduplicate the aka's
                dedups = name_deduplicate(aka_recs.names, [current_desig])
                self.texts["aka"] = self.ScrollTextLayout(
                    ", ".join(dedups),
                    font=self.fonts.base,
                    scrollspeed=self._get_scrollspeed_config(),
                )

            # NGC description....
            logs = self.observations_db.get_logs_for_object(cat_object)
            desc = cat_object.description.replace("\t", " ") + "\n"
            if len(logs) == 0:
                desc = desc + "  Not Logged"
            else:
                desc = desc + f"  {len(logs)} Logs"

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
                self.display_class,
            )

    def active(self):
        # trigger refilter
        super().active()

        # check for planet add
        dt = self.shared_state.datetime()
        if dt:
            self.add_planets(dt)

        self.catalog_tracker.filter()
        target = self.ui_state.target()
        if target:
            self.catalog_tracker.set_current_object(
                target.sequence, target.catalog_code
            )
            self.update_object_info()

    def update(self, force=True):
        # Clear Screen
        self.clear_screen()
        cat_object = self.catalog_tracker.get_current_object()
        print(f"in update catalog: {cat_object}")

        if self.object_display_mode == DM_DESC or cat_object is None:
            # catalog and entry field i.e. NGC-311
            self.refresh_designator()
            desc_available_lines = (
                2 if self.button_hints_visible else 3
            )  # extra lines for description
            desig = self.texts["designator"]
            desig.draw((0, 21))
            # print("Drawing designator", self.catalog_tracker.current_catalog, self.catalog_tracker.current_catalog.get_objects())

            # catalog counts....
            self.draw.text(
                (100, 21),
                f"{self.catalog_tracker.get_current_catalog().get_filtered_count()}",
                font=self.fonts.base.font,
                fill=self.colors.get(128),
            )
            self.draw.text(
                (100, 31),
                f"{self.catalog_tracker.get_current_catalog().get_count()}",
                font=self.fonts.base.font,
                fill=self.colors.get(96),
            )

            # Object TYPE and Constellation i.e. 'Galaxy    PER'
            typeconst = self.texts.get("type-const")
            if typeconst:
                typeconst.draw((0, 48))

            # Object Magnitude and size i.e. 'Mag:4.0   Sz:7"'
            magsize = self.texts.get("magsize")
            posy = 62
            if magsize and magsize.text.strip():
                if cat_object:
                    # check for visibility and adjust mag/size text color
                    obj_altitude = calc_utils.calc_object_altitude(
                        self.shared_state, cat_object
                    )

                    if obj_altitude:
                        if obj_altitude < 10:
                            # Not really visible
                            magsize.set_color = self.colors.get(128)
                magsize.draw((0, posy))
                posy += 17
            else:
                posy += 3
                desc_available_lines += 1  # extra lines for description

            # Common names for this object, i.e. M13 -> Hercules cluster
            aka = self.texts.get("aka")
            if aka and aka.text.strip():
                aka.draw((0, posy))
                posy += 11
            else:
                desc_available_lines += 1  # extra lines for description

            # Remaining lines with object description
            desc = self.texts.get("desc")
            if desc:
                desc.set_available_lines(desc_available_lines)
                desc.draw((0, posy))

        else:
            self.screen.paste(self.object_image)
        return self.screen_update()

    def key_d(self):
        self.descTextLayout.next()
        typeconst = self.texts.get("type-const")
        if typeconst and isinstance(typeconst, TextLayouter):
            typeconst.next()

    def key_c(self):
        # C is for catalog
        self.catalog_tracker.next_catalog()
        self.catalog_tracker.filter()
        self.update_object_info()
        self.object_display_mode = DM_DESC

    def key_long_c(self):
        self.key_long_d()
        self.catalog_tracker.previous_catalog()
        self.catalog_tracker.filter()
        self.update_object_info()

    def key_long_d(self):
        # long d is also called from main
        self.catalog_tracker.set_current_object(None)
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
        # TODO: Background update is not called any more
        if time.time() - self.catalog_tracker.get_current_catalog().last_filtered > 60:
            self.catalog_tracker.filter()

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
        if self.catalog_tracker.get_current_catalog().get_object_by_sequence(
            searching_for
        ):
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
        self.ui_state.set_target_and_add_to_history(cat_object)
        if cat_object:
            self.ui_state.set_active_list_to_history_list()
            self.switch_to = "UILocate"

    def scroll_obj(self, direction):
        """
        Looks for the next object up/down
        sets the sequence and object
        """
        if self.catalog_tracker.get_current_catalog().get_filtered_count() == 0:
            logging.debug("No objects in filtered catalog")
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
