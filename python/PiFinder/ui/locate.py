#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module contains the Locate module

"""
import datetime
import time
import os
from PIL import ImageFont

from PiFinder import solver
from PiFinder.obj_types import OBJ_TYPES
from PiFinder.ui.base import UIModule

RED = (0, 0, 255)


class UILocate(UIModule):
    """
    Display pushto info
    """

    __title__ = "LOCATE"

    def __init__(self, *args):
        super().__init__(*args)
        self.target = None
        self.ui_state["target_list"] = []
        self.target_index = None
        self.object_text = ["No Object Found"]
        self.__catalog_names = self.config_object.get_option("catalogs")
        self.sf_utils = solver.Skyfield_utils()
        self.font_huge = ImageFont.truetype(
            "/usr/share/fonts/truetype/Roboto_Mono/static/RobotoMono-Bold.ttf", 35
        )

    def resolve_catalog_name(self, catalog_id):
        """
        Takes catalog_id (single letter) and returns name
        """
        for catalog_name in self.__catalog_names:
            if catalog_name.startswith(catalog_id):
                return catalog_name
        return "UNKN"

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

    def update_object_text(self):
        """
        Generates object text
        """
        if not self.target:
            self.object_text = ["No Object Found"]
            return

        self.object_text = []

        # Type / Constellation
        object_type = OBJ_TYPES.get(self.target["obj_type"], self.target["obj_type"])
        self.object_text.append(f"{object_type: <14} {self.target['const']}")

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
                    self.target["ra"],
                    self.target["dec"],
                    dt,
                )
                az_diff = target_az - solution["Az"]
                az_diff = (az_diff + 180) % 360 - 180

                alt_diff = target_alt - solution["Alt"]
                alt_diff = (alt_diff + 180) % 360 - 180

                return az_diff, alt_diff
        else:
            return None, None

    def active(self):
        state_target = self.shared_state.target()
        if state_target != self.target:
            self.target = state_target
            self.ui_state["target_list"].append(state_target)
            self.target_index = len(self.ui_state["target_list"]) - 1
        self.update_object_text()
        self.update()

    def update(self, force=False):
        # Clear Screen
        self.draw.rectangle([0, 0, 128, 128], fill=(0, 0, 0))

        if not self.target:
            self.draw.text((0, 20), "No Target Set", font=self.font_large, fill=RED)
            return self.screen_update()

        # Target Name
        line = self.resolve_catalog_name(self.target["catalog"])
        line += str(self.target["designation"])
        self.draw.text((0, 20), line, font=self.font_large, fill=RED)

        # Target history index
        if self.target_index != None:
            line = f"{self.target_index + 1}/{len(self.ui_state['target_list'])}"
            line = f"{line : >7}"
            self.draw.text((85, 20), line, font=self.font_base, fill=RED)

        # ID Line in BOld
        self.draw.text((0, 40), self.object_text[0], font=self.font_bold, fill=RED)

        # Pointing Instructions
        point_az, point_alt = self.aim_degrees()
        if not point_az:
            self.draw.text((0, 50), " ---.-", font=self.font_huge, fill=RED)
            self.draw.text((0, 84), "  --.-", font=self.font_huge, fill=RED)
        else:
            if point_az >= 0:
                self.draw.regular_polygon((10, 75, 10), 3, 90, fill=RED)
                # self.draw.pieslice([-20,65,20,85],330, 30, fill=RED)
                # self.draw.text((0, 50), "+", font=self.font_huge, fill=RED)
            else:
                point_az *= -1
                self.draw.regular_polygon((10, 75, 10), 3, 270, fill=RED)
                # self.draw.pieslice([0,65,40,85],150,210, fill=RED)
                # self.draw.text((0, 50), "-", font=self.font_huge, fill=RED)
            self.draw.text(
                (25, 50), f"{point_az : >5.1f}", font=self.font_huge, fill=RED
            )

            if point_alt >= 0:
                self.draw.regular_polygon((10, 110, 10), 3, 0, fill=RED)
                # self.draw.pieslice([0,84,20,124],60, 120, fill=RED)
                # self.draw.text((0, 84), "+", font=self.font_huge, fill=RED)
            else:
                point_alt *= -1
                self.draw.regular_polygon((10, 105, 10), 3, 180, fill=RED)
                # self.draw.pieslice([0,104,20,144],270, 330, fill=RED)
                # self.draw.text((0, 84), "-", font=self.font_huge, fill=RED)
            self.draw.text(
                (25, 84), f"{point_alt : >5.1f}", font=self.font_huge, fill=RED
            )

        return self.screen_update()

    def scroll_target_history(self, direction):
        if self.target_index != None:
            self.target_index += direction
            if self.target_index >= len(self.ui_state["target_list"]):
                self.target_index = len(self.ui_state["target_list"]) - 1

            if self.target_index < 0:
                self.target_index = 0

            self.target = self.ui_state["target_list"][self.target_index]
            self.shared_state.set_target(self.target)
            self.update_object_text()
            self.update()
