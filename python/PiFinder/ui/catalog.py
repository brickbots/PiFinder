#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module contains all the UI Module classes

"""
import time
import os
import sqlite3
import pandas as pd
import numpy as np
from sklearn.neighbors import BallTree
from pathlib import Path

from PiFinder import solver, obslog, cat_images
from PiFinder.obj_types import OBJ_TYPES
from PiFinder.ui.base import UIModule
from PiFinder.ui.fonts import Fonts as fonts
from PiFinder.ui.ui_utils import (
    TextLayouterScroll,
    TextLayouter,
    TextLayouterSimple,
    CatalogDesignator,
    SpaceCalculatorFixed,
)
from PiFinder import calc_utils
import functools
import logging


# Constants for display modes
DM_DESC = 0  # Display mode for description
DM_OBS = 1  # Display mode for observed
DM_POSS = 2  # Display mode for POSS
DM_SDSS = 3  # Display mode for SDSS


def get_closest_objects(catalog, ra, dec, n):
    """
    Takes a catalog and returns the
    n closest objects to ra/dec
    """
    object_ras = [np.deg2rad(x["ra"]) for x in catalog]
    object_decs = [np.deg2rad(x["dec"]) for x in catalog]

    objects_df = pd.DataFrame(
        {
            "ra": object_ras,
            "dec": object_decs,
        }
    )
    objects_bt = BallTree(objects_df[["ra", "dec"]], leaf_size=4, metric="haversine")

    query_df = pd.DataFrame({"ra": [np.deg2rad(ra)], "dec": [np.deg2rad(dec)]})
    _dist, obj_ind = objects_bt.query(query_df, k=n)
    return [catalog[x] for x in obj_ind[0]]


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
        "Push List": {
            "type": "enum",
            "value": "",
            "options": ["Go", "CANCEL"],
            "callback": "push_list",
        },
        "Push Near": {
            "type": "enum",
            "value": "",
            "options": ["CANCEL", 5, 10, 15, 20],
            "callback": "push_near",
        },
    }

    def __init__(self, *args):
        super().__init__(*args)
        self.__catalogs = {}
        self.__catalog_names = self.config_object.get_option("catalogs")
        self.catalog_index = 0
        self.cat_object = None
        self.object_text = ["No Object Found"]
        self.SimpleTextLayout = functools.partial(
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
            "type-const": self.SimpleTextLayout(
                "No Object Found", font=self.font_bold, color=self.colors.get(255)
            ),
        }
        self.designatorobj = CatalogDesignator(self.__catalog_names, self.catalog_index)
        root_dir = os.path.realpath(
            os.path.join(os.path.dirname(__file__), "..", "..", "..")
        )
        db_path = os.path.join(root_dir, "astro_data", "pifinder_objects.db")
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.font_large = fonts.large

        self.object_display_mode = DM_DESC
        self.object_image = None

        self._catalog_item_index = 0
        self.fov_list = [1, 0.5, 0.25, 0.125]
        self.fov_index = 0

        self.load_catalogs()
        self.set_catalog()

    def layout_designator(self):
        return self.SimpleTextLayout(
            str(self.designatorobj),
            font=fonts.large,
            color=self.colors.get(255),
        )

    def refresh_designator(self):
        self.texts["designator"] = self.layout_designator()

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
        # call load catalog to re-filter if needed
        self.set_catalog()

        # Reset any sequence....
        if not self._catalog_item_index:
            self.delete()

    def push_list(self, option):
        self._config_options["Push List"]["value"] = ""
        if option == "Go":
            self.message("Catalog Pushed", 2)
            # Filter the catalog one last time
            self.set_catalog()
            self.ui_state["observing_list"] = self._filtered_catalog
            self.ui_state["active_list"] = self.ui_state["observing_list"]
            self.ui_state["target"] = self.ui_state["active_list"][0]
            return "UILocate"
        else:
            return False

    def push_near(self, option):
        self._config_options["Push Near"]["value"] = ""
        if option != "Cncl":
            solution = self.shared_state.solution()
            if not solution:
                self.message(f"No Solve!", 1)
                return False

            # Filter the catalog one last time
            self.set_catalog()
            self.message(f"Near {option} Pushed", 2)

            if option > len(self._filtered_catalog):
                near_catalog = self._filtered_catalog
            else:
                near_catalog = get_closest_objects(
                    self._filtered_catalog, solution["RA"], solution["Dec"], option
                )
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
        logging.debug(
            f"In update_oject_info, {self.cat_object=}, {self.catalog_index=}, {self._catalog_item_index=}"
        )
        if not self.cat_object:
            self.texts["type-const"] = self.SimpleTextLayout(
                "No Object Found", font=fonts.bold, color=self.colors.get(255)
            )
            self.texts = {}
            return

        if self.object_display_mode in [DM_DESC, DM_OBS]:
            # text stuff....
            # look for AKAs
            aka_recs = self.conn.execute(
                f"""
                SELECT * from names
                where catalog = "{self.cat_object['catalog']}"
                and sequence = "{self.cat_object['sequence']}"
            """
            ).fetchall()

            self.texts = {}
            # Type / Constellation
            object_type = OBJ_TYPES.get(
                self.cat_object["obj_type"], self.cat_object["obj_type"]
            )
            # self.texts["type-const"] = self.TextLayout(
            #     f"{object_type: <14} {self.cat_object['const']: >3}",
            #     font=fonts.bold,
            #     color=self.colors.get(255),
            # )

            # layout the type - constellation line
            _, typeconst = self.space_calculator.calculate_spaces(
                object_type, self.cat_object["const"]
            )
            self.texts["type-const"] = self.SimpleTextLayout(
                typeconst,
                font=fonts.bold,
                color=self.colors.get(255),
            )
            # Magnitude / Size
            # try to get object mag to float
            try:
                obj_mag = float(self.cat_object["mag"])
            except (ValueError, TypeError):
                obj_mag = "-"

            size = str(self.cat_object["size"]).strip()
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

            self.texts["magsize"] = self.SimpleTextLayout(
                magsize, font=fonts.bold, color=self.colors.get(255)
            )

            if aka_recs:
                aka_list = []
                for rec in aka_recs:
                    if rec["common_name"].startswith("M"):
                        aka_list.insert(0, rec["common_name"])
                    else:
                        aka_list.append(rec["common_name"])
                self.texts["aka"] = self.ScrollTextLayout(
                    ", ".join(aka_list),
                    font=fonts.base,
                    scrollspeed=self._get_scrollspeed_config(),
                )

            if self.object_display_mode == DM_DESC:
                # NGC description....
                desc = self.cat_object["desc"].replace("\t", " ")
                self.descTextLayout.set_text(desc)
                self.texts["desc"] = self.descTextLayout

            if self.object_display_mode == DM_OBS:
                logs = obslog.get_logs_for_object(self.cat_object)
                if len(logs) == 0:
                    self.texts["obs"] = self.SimpleTextLayout("No Logs")
                else:
                    self.texts["obs"] = self.DescTextLayout(f"Logged {len(logs)} times")
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
                self.cat_object,
                source,
                self.fov_list[self.fov_index],
                roll,
                self.colors,
            )

    def active(self):
        # trigger refilter
        self.set_catalog()
        target = self.ui_state["target"]
        if target:
            self.cat_object = target
            assert self.__catalog_names[self.catalog_index]

    def update(self, force=True):
        # Clear Screen
        self.draw.rectangle([0, 0, 128, 128], fill=self.colors.get(0))

        if self.object_display_mode in [DM_DESC, DM_OBS] or self.cat_object == None:
            # catalog and entry field i.e. NGC-311
            self.refresh_designator()
            desig = self.texts["designator"]
            desig.draw((0, 21))

            # catalog counts....
            self.draw.text(
                (100, 21),
                f"{self._catalog_count[1]}",
                font=self.font_base,
                fill=self.colors.get(128),
            )
            self.draw.text(
                (100, 31),
                f"{self._catalog_count[0]}",
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
                if self.cat_object:
                    # check for visibility and adjust mag/size text color
                    obj_altitude = self.calc_object_altitude(self.cat_object)

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
        # d is for delete
        # self.designator = self.designatorobj.reset_number()
        # self.cat_object = None
        # self._catalog_item_index = 0
        # self.update_object_info()
        self.descTextLayout.next()

    def delete(self):
        # long d called from main
        self.designator = self.designatorobj.reset_number()
        self.cat_object = None
        self._catalog_item_index = 0
        self.update_object_info()

    def key_c(self):
        # C is for catalog
        # Reset any sequence....
        self.delete()
        self.catalog_index = self.designatorobj.next_catalog()
        logging.debug(f"after key_c, catalog index is {self.catalog_index}")
        self.set_catalog()

    def key_b(self):
        if self.cat_object == None:
            self.object_display_mode = DM_DESC
        else:
            # switch object display text
            self.object_display_mode = (
                self.object_display_mode + 1 if self.object_display_mode < 3 else 0
            )
            self.update_object_info()
            self.update()

    def load_catalogs(self):
        """
        Loads all catalogs into memory
        starts altitude calculation loop

        """
        for catalog_name in self.__catalog_names:
            logging.debug("loading " + catalog_name)
            cat_objects = self.conn.execute(
                f"""
                SELECT * from objects
                where catalog='{catalog_name}'
                order by sequence
            """
            ).fetchall()
            self.__catalogs[catalog_name] = [dict(x) for x in cat_objects]

    def set_catalog(self):
        """
        Does filtering based on params
        populates self._filtered_catalog
        from in-memory catalogs
        tries to maintain current index if applicable
        """
        self.__last_filtered = time.time()
        selected_object = None
        if self._catalog_item_index:
            selected_object = self._filtered_catalog[self._catalog_item_index]

        catalog_name = self.__catalog_names[self.catalog_index].strip()
        load_start_time = time.time()

        # first get count of full catalog
        full_count = len(self.__catalogs[catalog_name])

        self._filtered_catalog = []
        magnitude_filter = self._config_options["Magnitude"]["value"]
        type_filter = self._config_options["Obj Types"]["value"]
        altitude_filter = self._config_options["Alt Limit"]["value"]
        observed_filter = self._config_options["Observed"]["value"]

        fast_aa = None
        if altitude_filter != "None":
            # setup
            solution = self.shared_state.solution()
            location = self.shared_state.location()
            dt = self.shared_state.datetime()
            if location and dt and solution:
                fast_aa = calc_utils.FastAltAz(
                    location["lat"],
                    location["lon"],
                    dt,
                )

        if observed_filter != "Any":
            # setup
            observed_list = obslog.get_observed_objects()

        for obj in self.__catalogs[catalog_name]:
            include_obj = True

            # try to get object mag to float
            try:
                obj_mag = float(obj["mag"])
            except (ValueError, TypeError):
                obj_mag = 0

            if magnitude_filter != "None" and obj_mag >= magnitude_filter:
                include_obj = False

            if type_filter != ["None"] and obj["obj_type"] not in type_filter:
                include_obj = False

            if fast_aa:
                obj_altitude = fast_aa.radec_to_altaz(
                    obj["ra"],
                    obj["dec"],
                    alt_only=True,
                )
                if obj_altitude < altitude_filter:
                    include_obj = False

            if observed_filter != "Any":
                if (obj["catalog"], obj["sequence"]) in observed_list:
                    if observed_filter == "No":
                        include_obj = False
                else:
                    if observed_filter == "Yes":
                        include_obj = False

            if include_obj:
                self._filtered_catalog.append(obj)

        self._catalog_count = (full_count, len(self._filtered_catalog))
        if self._catalog_item_index:
            if selected_object in self._filtered_catalog:
                self._catalog_item_index = self._filtered_catalog.index(selected_object)
            else:
                self._catalog_item_index = 0

    def background_update(self):
        if time.time() - self.__last_filtered > 60:
            self.set_catalog()

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
                obj["ra"],
                obj["dec"],
                alt_only=True,
            )
            return obj_alt

        return None

    def find_by_designator(self, designator):
        """
        Searches the loaded catalog for the designator
        """
        logging.debug(f"Calling find by designator with: {designator}")
        if designator.object_number == 0:
            logging.debug("find by designartor, objectnumber is 0")
            return False

        for i, c in enumerate(self._filtered_catalog):
            logging.debug(f" searching: {c['sequence']=}{type(c['sequence'])=}")
            if c["sequence"] == designator.object_number:
                logging.debug(f"Found {c['sequence']=}, at index {i}")
                self.cat_object = c
                self._catalog_item_index = i + 1
                return True

        logging.debug("find by designator, no match found")
        self.cat_object = None
        self._catalog_item_index = 0
        return False

    def key_number(self, number):
        if self.object_display_mode in [DM_DESC, DM_OBS]:
            self.designatorobj.append_number(number)
            # Check for match
            found = self.find_by_designator(self.designatorobj)
            self.update_object_info()

    def key_enter(self):
        """
        When enter is pressed, set the
        target
        """
        if self.cat_object:
            self.ui_state["target"] = dict(self.cat_object)
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
        if len(self._filtered_catalog) == 0:
            return
        logging.debug(f"scroll object , {direction=}, {self._catalog_item_index=}")
        self._catalog_item_index += direction

        self._catalog_item_index %= self._catalog_count[1] + 1

        if self._catalog_item_index != 0:
            self.cat_object = self._filtered_catalog[self._catalog_item_index - 1]
            self.designatorobj.set_number(self.cat_object["sequence"])
        else:
            self.cat_object = None
            self.designatorobj.set_number(0)
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
