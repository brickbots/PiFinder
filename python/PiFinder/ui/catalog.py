#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module contains all the UI Module classes

"""
import datetime
import time
import os
import sqlite3
from PIL import ImageFont

from PiFinder import solver
from PiFinder.obj_types import OBJ_TYPES
from PiFinder.ui.base import UIModule

RED = (0, 0, 255)


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
        "Push List": {
            "type": "enum",
            "value": "",
            "options": ["Go", "Cncl"],
            "callback": "push_list",
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
        self.db_c = self.conn.cursor()
        self.sf_utils = solver.Skyfield_utils()
        self.font_large = ImageFont.truetype(
            "/home/pifinder/PiFinder/fonts/RobotoMono-Regular.ttf", 20
        )

        self._catalog_item_index = 0

        # Counters for the constantly running altitude
        # calculations
        self.__alt_catalog_index = 2
        self.__alt_object_index = 0
        self.__alt_dict = {}

        self.load_catalogs()
        self.set_catalog()

    def update_config(self):
        # call load catalog to re-filter if needed
        self.set_catalog()
        self._catalog_item_index = 0

        # Reset any designations....
        self.key_d()

    def push_list(self, option):
        self._config_options["Push List"]["value"] = ""
        if option == "Go":
            print("GOGOGOGOGOG")
            self.set_catalog()

            return True
        else:
            return False

    def update_object_text(self):
        """
        Generates object text
        """
        if not self.cat_object:
            self.object_text = ["No Object Found", ""]
            return

        # look for AKAs
        aka_recs = self.conn.execute(
            f"""
            SELECT * from names
            where catalog = "{self.cat_object['catalog']}"
            and designation = "{self.cat_object['designation']}"
        """
        ).fetchall()

        self.object_text = []
        # Type / Constellation
        object_type = OBJ_TYPES.get(
            self.cat_object["obj_type"], self.cat_object["obj_type"]
        )
        self.object_text.append(f"{object_type: <14} {self.cat_object['const']}")

        # Magnitude / Size
        self.object_text.append(
            f"Mag:{self.cat_object['mag'] : <4}"
            + " " * 3
            + f"Sz:{self.cat_object['size']}"
        )

        if aka_recs:
            aka_list = []
            for rec in aka_recs:
                if rec["common_name"].startswith("M"):
                    aka_list.insert(0, rec["common_name"])
                else:
                    aka_list.append(rec["common_name"])
            self.object_text.append(", ".join(aka_list))

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

    def active(self):
        target = self.ui_state["target"]
        if target:
            self.cat_object = target
            self.catalog_index = ["N", "I", "M"].index(target["catalog"])
            self.designator = list(str(target["designation"]))
            if self.catalog_index == 2:
                self.designator = ["-"] * (3 - len(self.designator)) + self.designator
            else:
                self.designator = ["-"] * (4 - len(self.designator)) + self.designator

        self.update_object_text()
        self.update()

    def update(self, force=True):
        # Calc some altitude!
        for _ in range(2):
            self.calc_altitude()

        # Clear Screen
        self.draw.rectangle([0, 0, 128, 128], fill=(0, 0, 0))

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
            (100, 31), f"{self._catalog_count[0]}", font=self.font_base, fill=(0, 0, 96)
        )

        # ID Line in BOld
        self.draw.text((0, 48), self.object_text[0], font=self.font_bold, fill=RED)

        # mag/size in bold
        text_color = RED
        if self.cat_object:
            # check for visibility and adjust mag/size text color
            obj_altitude = self.__alt_dict.get(
                self.cat_object["catalog"] + str(self.cat_object["designation"])
            )
            if not obj_altitude:
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
        self.update_object_text()

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

        # Reset any designations....
        self.key_d()

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
                where catalog='{catalog_name[0]}'
                order by designation
            """
            ).fetchall()
            self.__catalogs[catalog_name] = [dict(x) for x in cat_objects]

    def set_catalog(self):
        """
        Does filtering based on params
        populates self._filtered_catalog
        from in-memory catalogs
        """
        catalog_name = self.__catalog_names[self.catalog_index].strip()
        load_start_time = time.time()

        # first get count of full catalog
        full_count = len(self.__catalogs[catalog_name])

        self._filtered_catalog = []
        magnitude_filter = self._config_options["Magnitude"]["value"]
        type_filter = self._config_options["Obj Types"]["value"]
        altitude_filter = self._config_options["Alt Limit"]["value"]
        for obj in self.__catalogs[catalog_name]:
            include_obj = True

            # try to get object mag to float
            try:
                obj_mag = float(obj["mag"])
            except ValueError:
                obj_mag = 0

            if magnitude_filter != "None" and obj_mag >= magnitude_filter:
                include_obj = False

            if type_filter != ["None"] and obj["obj_type"] not in type_filter:
                include_obj = False

            obj_altitude = self.__alt_dict.get(obj["catalog"] + str(obj["designation"]))
            if (
                obj_altitude != None
                and altitude_filter != "None"
                and obj_altitude < altitude_filter
            ):
                include_obj = False

            if include_obj:
                self._filtered_catalog.append(obj)

        self._catalog_count = (full_count, len(self._filtered_catalog))
        if self._catalog_item_index >= len(self._filtered_catalog):
            self._catalog_item_index = 0

    def background_update(self):
        self.calc_altitude()

    def calc_object_altitude(self, obj):
        solution = self.shared_state.solution()
        location = self.shared_state.location()
        dt = self.shared_state.datetime()
        if location and dt and solution:
            self.sf_utils.set_location(
                location["lat"],
                location["lon"],
                location["altitude"],
            )
            obj_alt, obj_az = self.sf_utils.radec_to_altaz(
                obj["ra"],
                obj["dec"],
                dt,
                atmos=False,
            )
            self.__alt_dict[obj["catalog"] + str(obj["designation"])] = obj_alt
            return obj_alt

        return None

    def calc_altitude(self):
        """
        Called each update of the ui
        this calculates the next item
        in the list of objects to calculate
        """
        current_catalog = self.__catalogs[
            self.__catalog_names[self.__alt_catalog_index]
        ]
        obj = current_catalog[self.__alt_object_index]
        obj_alt = self.calc_object_altitude(obj)
        if obj_alt:
            self.__alt_object_index += 1
            if self.__alt_object_index >= len(current_catalog):
                print("AF: Finished " + self.__catalog_names[self.__alt_catalog_index])
                if self.__alt_object_index == self.catalog_index:
                    # call set catalog to re-filter display....
                    self.set_catalog()

                self.__alt_object_index = 0
                self.__alt_catalog_index += 1
                if self.__alt_catalog_index >= len(self.__catalog_names):
                    self.__alt_catalog_index = 0

    def find_by_designator(self, designator):
        """
        Searches the loaded catalog for the designator
        """
        if designator == "":
            return False

        for i, c in enumerate(self._filtered_catalog):
            if c["designation"] == int(designator):
                self.cat_object = c
                self._catalog_item_index = i
                return True

        self.cat_object = None
        self._catalog_item_index = 0
        return False

    def key_number(self, number):
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
        self.update_object_text()

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
        sets the designation and object
        """
        self._catalog_item_index += direction
        if self._catalog_item_index < 0:
            self._catalog_item_index = 0

        if self._catalog_item_index >= self._catalog_count[1]:
            self._catalog_item_index = self._catalog_count[1] - 1

        self.cat_object = self._filtered_catalog[self._catalog_item_index]
        desig = str(self.cat_object["designation"])
        desig = list(desig)
        if self.catalog_index == 2:
            desig = ["-"] * (3 - len(desig)) + desig
        else:
            desig = ["-"] * (4 - len(desig)) + desig

        self.designator = desig
        self.update_object_text()

    def key_up(self):
        self.scroll_obj(-1)

    def key_down(self):
        self.scroll_obj(1)
