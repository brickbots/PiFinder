#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module contains all the UI Module classes

"""
import datetime
import time
import pytz
import os
import math
import sqlite3
import pandas as pd
import numpy as np
from sklearn.neighbors import BallTree
from PIL import ImageFont

from PiFinder import solver, obslog, cat_images
from PiFinder.obj_types import OBJ_TYPES
from PiFinder.ui.base import UIModule

RED = (0, 0, 255)

# Constants for display modes
DM_DESC = 0
DM_OBS = 1
DM_POSS = 2
DM_SDSS = 3


class FastAltAz:
    """
    Adapted from example at:
    http://www.stargazing.net/kepler/altaz.html
    """

    def __init__(self, lat, lon, dt):
        self.lat = lat
        self.lon = lon
        self.dt = dt

        j2000 = datetime.datetime(2000, 1, 1, 12, 0, 0)
        utc_tz = pytz.timezone("UTC")
        j2000 = utc_tz.localize(j2000)
        _d = self.dt - j2000
        days_since_j2000 = _d.total_seconds() / 60 / 60 / 24

        dec_hours = self.dt.hour + (self.dt.minute / 60)

        lst = 100.46 + 0.985647 * days_since_j2000 + self.lon + 15 * dec_hours

        self.local_siderial_time = lst % 360

    def radec_to_altaz(self, ra, dec, alt_only=False):
        hour_angle = (self.local_siderial_time - ra) % 360

        _alt = math.sin(dec * math.pi / 180) * math.sin(
            self.lat * math.pi / 180
        ) + math.cos(dec * math.pi / 180) * math.cos(
            self.lat * math.pi / 180
        ) * math.cos(
            hour_angle * math.pi / 180
        )

        alt = math.asin(_alt) * 180 / math.pi
        if alt_only:
            return alt

        _az = (
            math.sin(dec * math.pi / 180)
            - math.sin(alt * math.pi / 180) * math.sin(self.lat * math.pi / 180)
        ) / (math.cos(alt * math.pi / 180) * math.cos(self.lat * math.pi / 180))

        _az = math.acos(_az) * 180 / math.pi

        if math.sin(hour_angle * math.pi / 180) < 0:
            az = _az
        else:
            az = 360 - _az
        return alt, az


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
        self.designator = ["-"] * 4
        self.cat_object = None
        self.object_text = ["No Object Found"]
        root_dir = os.path.realpath(
            os.path.join(os.path.dirname(__file__), "..", "..", "..")
        )
        db_path = os.path.join(root_dir, "astro_data", "pifinder_objects.db")
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.font_large = ImageFont.truetype(
            "/home/pifinder/PiFinder/fonts/RobotoMono-Regular.ttf", 20
        )

        self.object_display_mode = DM_DESC
        self.object_image = None

        self._catalog_item_index = 0
        self.fov_list = [1, 0.5, 0.25, 0.125]
        self.fov_index = 0

        self.load_catalogs()
        self.set_catalog()

    def update_config(self):
        # call load catalog to re-filter if needed
        self.set_catalog()

        # Reset any sequence....
        if not self._catalog_item_index:
            self.key_d()

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
        if not self.cat_object:
            self.object_text = ["No Object Found", ""]
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

            self.object_text = []
            # Type / Constellation
            object_type = OBJ_TYPES.get(
                self.cat_object["obj_type"], self.cat_object["obj_type"]
            )
            self.object_text.append(f"{object_type: <14} {self.cat_object['const']}")

            # Magnitude / Size
            # try to get object mag to float
            try:
                obj_mag = float(self.cat_object["mag"])
            except (ValueError, TypeError):
                obj_mag = 0
            self.object_text.append(
                f"Mag:{obj_mag : <4}" + " " * 3 + f"Sz:{self.cat_object['size']}"
            )

            if aka_recs:
                aka_list = []
                for rec in aka_recs:
                    if rec["common_name"].startswith("M"):
                        aka_list.insert(0, rec["common_name"])
                    else:
                        aka_list.append(rec["common_name"])
                self.object_text.append(", ".join(aka_list))

            if self.object_display_mode == DM_DESC:
                # NGC description....
                max_line = 20
                line = ""
                desc_tokens = self.cat_object["desc"].split(" ")
                for token in desc_tokens:
                    if len(line) + len(token) + 1 > max_line:
                        self.object_text.append(line)
                        line = token
                    else:
                        line = line + " " + token

            if self.object_display_mode == DM_OBS:
                self.object_text.append("")
                logs = obslog.get_logs_for_object(self.cat_object)
                if len(logs) == 0:
                    self.object_text.append("No Logs")
                else:
                    self.object_text.append(f"Logged {len(logs)} times")
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
            )

    def active(self):
        # trigger refilter
        self.set_catalog()
        target = self.ui_state["target"]
        if target:
            self.cat_object = target
            self.catalog_index = self.__catalog_names.index(target["catalog"])
            self.designator = list(str(target["sequence"]))
            if self.catalog_index == 2:
                self.designator = ["-"] * (3 - len(self.designator)) + self.designator
            else:
                self.designator = ["-"] * (4 - len(self.designator)) + self.designator

        self.update_object_info()
        self.update()

    def update(self, force=True):
        # Clear Screen
        self.draw.rectangle([0, 0, 128, 128], fill=(0, 0, 0))

        if self.object_display_mode in [DM_DESC, DM_OBS] or self.cat_object == None:
            # catalog and entry field
            line = f"{self.__catalog_names[self.catalog_index]: >3}"
            line += "".join(self.designator)
            self.draw.text((0, 21), line, font=self.font_large, fill=RED)

            # catalog counts....
            self.draw.text(
                (100, 21),
                f"{self._catalog_count[1]}",
                font=self.font_base,
                fill=(0, 0, 128),
            )
            self.draw.text(
                (100, 31),
                f"{self._catalog_count[0]}",
                font=self.font_base,
                fill=(0, 0, 96),
            )

            # ID Line in BOld
            self.draw.text((0, 48), self.object_text[0], font=self.font_bold, fill=RED)

            # mag/size in bold
            text_color = RED
            if self.cat_object:
                # check for visibility and adjust mag/size text color
                obj_altitude = self.calc_object_altitude(self.cat_object)

                if obj_altitude:
                    if obj_altitude < 10:
                        # Not really visible
                        text_color = (0, 0, 128)

            self.draw.text(
                (0, 62), self.object_text[1], font=self.font_bold, fill=text_color
            )

            # Remaining lines
            for i, line in enumerate(self.object_text[2:]):
                self.draw.text((0, i * 11 + 82), line, font=self.font_base, fill=RED)
        else:
            self.screen.paste(self.object_image)
        return self.screen_update()

    def key_d(self):
        # d is for delete
        if self.catalog_index == 2:
            # messier
            self.designator = ["-"] * 3
        else:
            self.designator = ["-"] * 4
        self.cat_object = None
        self._catalog_item_index = 0
        self.update_object_info()

    def key_c(self):
        # C is for catalog
        self.catalog_index += 1
        if self.catalog_index >= len(self.__catalog_names):
            self.catalog_index = 0
        if self.catalog_index == 2:
            # messier
            self.designator = ["-"] * 3
        else:
            self.designator = ["-"] * 4

        self.set_catalog()
        self._catalog_item_index = 0

        # Reset any sequence....
        self.key_d()

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
            print("loading " + catalog_name)
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
                fast_aa = FastAltAz(
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
            aa = FastAltAz(
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
        if designator == "":
            return False

        for i, c in enumerate(self._filtered_catalog):
            if c["sequence"] == int(designator):
                self.cat_object = c
                self._catalog_item_index = i
                return True

        self.cat_object = None
        self._catalog_item_index = 0
        return False

    def key_number(self, number):
        if self.object_display_mode in [DM_DESC, DM_OBS]:
            self.designator = self.designator[1:]
            self.designator.append(str(number))
            if self.designator[0] in ["0", "-"]:
                index = 0
                go = True
                while go:
                    self.designator[index] = "-"
                    index += 1
                    if index >= len(self.designator) or self.designator[index] not in [
                        "0",
                        "-",
                    ]:
                        go = False
            # Check for match
            designator = "".join(self.designator).replace("-", "")
            found = self.find_by_designator(designator)
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

        self._catalog_item_index += direction
        if self._catalog_item_index < 0:
            self._catalog_item_index = 0

        if self._catalog_item_index >= self._catalog_count[1]:
            self._catalog_item_index = self._catalog_count[1] - 1

        self.cat_object = self._filtered_catalog[self._catalog_item_index]
        desig = str(self.cat_object["sequence"])
        desig = list(desig)
        if self.catalog_index == 2:
            desig = ["-"] * (3 - len(desig)) + desig
        else:
            desig = ["-"] * (4 - len(desig)) + desig

        self.designator = desig
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
