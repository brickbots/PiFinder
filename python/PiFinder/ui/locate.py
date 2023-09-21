#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module contains the Locate module

"""
import time
from PIL import ImageFont
import logging

from PiFinder import integrator, obslist, config
from PiFinder.obj_types import OBJ_TYPES
from PiFinder.ui.base import UIModule
from PiFinder.ui.fonts import Fonts as fonts


class UILocate(UIModule):
    """
    Display pushto info
    """

    __title__ = "LOCATE"

    _config_options = {
        "Save": {
            "type": "enum",
            "value": "",
            "options": ["CANCEL", "History", "Observ"],
            "callback": "save_list",
        },
        "Load": {
            "type": "enum",
            "value": "",
            "options": ["CANCEL"],
            "callback": "load_list",
        },
    }

    def __init__(self, *args):
        super().__init__(*args)
        self.target_index = None
        self.object_text = ["No Object Found"]
        self.__catalog_names = self.config_object.get_option("catalogs")
        self.sf_utils = integrator.Skyfield_utils()
        self.font_huge = fonts.huge
        self.screen_direction = config.Config().get_option("screen_direction")

        available_lists = obslist.get_lists()
        self._config_options["Load"]["options"] += available_lists
        self.obs_list_write_index = 0
        self.last_update_time = time.time()

    def save_list(self, option):
        self._config_options["Load"]["value"] = ""
        if option == "CANCEL":
            return False

        if len(self.ui_state["active_list"]) == 0:
            self.message("No objects")
            return False

        filename = f"{self.__uuid__}_{option}_{self.ss_count:02d}"
        if option == "History":
            obslist.write_list(self.ui_state["history_list"], filename)
        else:
            obslist.write_list(self.ui_state["observing_list"], filename)
        self.obs_list_write_index += 1
        self.message(f"Saved list - {self.ss_count:02d}")
        return True

    def load_list(self, option):
        self._config_options["Load"]["value"] = ""
        if option == "CANCEL":
            return False

        _load_results = obslist.read_list(option)
        if _load_results["result"] == "error":
            self.message(f"Err! {_load_results['message']}")
            return False

        object_count = len(_load_results["catalog"])
        if object_count == 0:
            self.message("No matches")
            return False

        self.ui_state["observing_list"] = _load_results["catalog"]
        self.ui_state["active_list"] = self.ui_state["observing_list"]
        self.target_index = 0
        self.ui_state["target"] = self.ui_state["active_list"][self.target_index]
        self.update_object_text()
        self.message(f"Loaded {object_count} of {_load_results['objects_parsed']}")
        return True

    def key_b(self):
        """
        When B is pressed, switch target lists
        """
        self.target_index = None
        if self.ui_state["active_list"] == self.ui_state["history_list"]:
            if len(self.ui_state["observing_list"]) > 0:
                self.ui_state["active_list"] = self.ui_state["observing_list"]
                self.target_index = 0
            else:
                self.message("No Obs List", 1)
        else:
            if len(self.ui_state["history_list"]) > 0:
                self.ui_state["active_list"] = self.ui_state["history_list"]
                self.target_index = len(self.ui_state["active_list"]) - 1
            else:
                self.message("No History", 1)

        if self.target_index != None:
            self.ui_state["target"] = self.ui_state["active_list"][self.target_index]
            self.update_object_text()

    def key_enter(self):
        """
        When enter is pressed, set the
        target
        """
        self.switch_to = "UICatalog"

    def key_up(self):
        self.scroll_target_history(-1)

    def key_down(self):
        self.scroll_target_history(1)

    def delete(self):
        active_list = self.ui_state["active_list"]
        if self.target_index is not None and len(active_list) > 1:
            del active_list[self.target_index]
            self.target_index = (self.target_index + 1) % len(active_list)
            self.target = self.ui_state["active_list"][self.target_index]
            self.ui_state["target"] = self.target
            self.update_object_text()
            self.update()
        elif len(active_list) == 1:
            self.ui_state["active_list"] = []
            self.target_index = None
            self.target = None
            self.switch_to = "UICatalog"
        else:
            self.switch_to = "UICatalog"

    def update_object_text(self):
        """
        Generates object text
        """
        target = self.ui_state["target"]
        if not target:
            self.object_text = ["No Object Found"]
            return

        self.object_text = []
        try:
            # Type / Constellation
            object_type = OBJ_TYPES.get(target.obj_type, target.obj_type)
            self.object_text.append(f"{object_type: <14} {target.const}")
        except Exception as e:
            logging.error(f"Error generating object text: {e}, {target}")

    def aim_degrees(self):
        """
        Returns degrees in
        az/alt from current position
        to target
        """
        solution = self.shared_state.solution()
        location = self.shared_state.location()
        dt = self.shared_state.datetime()
        if location and dt and solution:
            if solution["Alt"]:
                # We have position and time/date!
                self.sf_utils.set_location(
                    location["lat"],
                    location["lon"],
                    location["altitude"],
                )
                target_alt, target_az = self.sf_utils.radec_to_altaz(
                    self.ui_state["target"].ra,
                    self.ui_state["target"].dec,
                    dt,
                )
                az_diff = target_az - solution["Az"]
                az_diff = (az_diff + 180) % 360 - 180
                if self.screen_direction == "flat":
                    az_diff *= -1

                alt_diff = target_alt - solution["Alt"]
                alt_diff = (alt_diff + 180) % 360 - 180

                return az_diff, alt_diff
        return None, None

    def active(self):
        try:
            self.target_index = self.ui_state["active_list"].index(
                self.ui_state["target"]
            )
        except ValueError:
            self.target_index = None
        self.update_object_text()
        self.update()

    def update(self, force=False):
        time.sleep(1 / 30)
        # Clear Screen
        self.draw.rectangle([0, 0, 128, 128], fill=self.colors.get(0))

        target = self.ui_state["target"]
        if not target:
            self.draw.text(
                (0, 20),
                "No Target Set",
                font=self.font_large,
                fill=self.colors.get(255),
            )
            return self.screen_update()

        # Target Name
        line = target.catalog_code
        line += str(target.sequence)
        self.draw.text((0, 20), line, font=self.font_large, fill=self.colors.get(255))

        # Target history index
        if self.target_index != None:
            if self.ui_state["active_list"] == self.ui_state["history_list"]:
                list_name = "Hist"
            else:
                list_name = "Obsv"
            line = f'{self.target_index + 1}/{len(self.ui_state["active_list"])}'
            line = f"{line : >9}"
            self.draw.text(
                (72, 18), line, font=self.font_base, fill=self.colors.get(255)
            )
            self.draw.text(
                (72, 28),
                f"{list_name: >9}",
                font=self.font_base,
                fill=self.colors.get(255),
            )

        # ID Line in BOld
        self.draw.text(
            (0, 40), self.object_text[0], font=self.font_bold, fill=self.colors.get(255)
        )

        # Pointing Instructions
        point_az, point_alt = self.aim_degrees()
        if not point_az:
            self.draw.text(
                (0, 50), " ---.-", font=self.font_huge, fill=self.colors.get(255)
            )
            self.draw.text(
                (0, 84), "  --.-", font=self.font_huge, fill=self.colors.get(255)
            )
        else:
            if point_az >= 0:
                self.draw.regular_polygon(
                    (10, 75, 10), 3, 90, fill=self.colors.get(255)
                )
                # self.draw.pieslice([-20,65,20,85],330, 30, fill=self.colors.get(255))
                # self.draw.text((0, 50), "+", font=self.font_huge, fill=self.colors.get(255))
            else:
                point_az *= -1
                self.draw.regular_polygon(
                    (10, 75, 10), 3, 270, fill=self.colors.get(255)
                )
                # self.draw.pieslice([0,65,40,85],150,210, fill=self.colors.get(255))
                # self.draw.text((0, 50), "-", font=self.font_huge, fill=self.colors.get(255))
            self.draw.text(
                (25, 50),
                f"{point_az : >5.1f}",
                font=self.font_huge,
                fill=self.colors.get(255),
            )

            if point_alt >= 0:
                self.draw.regular_polygon(
                    (10, 110, 10), 3, 0, fill=self.colors.get(255)
                )
                # self.draw.pieslice([0,84,20,124],60, 120, fill=self.colors.get(255))
                # self.draw.text((0, 84), "+", font=self.font_huge, fill=self.colors.get(255))
            else:
                point_alt *= -1
                self.draw.regular_polygon(
                    (10, 105, 10), 3, 180, fill=self.colors.get(255)
                )
                # self.draw.pieslice([0,104,20,144],270, 330, fill=self.colors.get(255))
                # self.draw.text((0, 84), "-", font=self.font_huge, fill=self.colors.get(255))
            self.draw.text(
                (25, 84),
                f"{point_alt : >5.1f}",
                font=self.font_huge,
                fill=self.colors.get(255),
            )

        return self.screen_update()

    def scroll_target_history(self, direction):
        if self.target_index != None:
            self.target_index += direction
            if self.target_index >= len(self.ui_state["active_list"]):
                self.target_index = len(self.ui_state["active_list"]) - 1

            if self.target_index < 0:
                self.target_index = 0

            self.target = self.ui_state["active_list"][self.target_index]
            self.ui_state["target"] = self.target
            self.update_object_text()
            self.update()
