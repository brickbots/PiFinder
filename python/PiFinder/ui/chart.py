#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module contains all the UI Module classes

"""
import time
from PIL import ImageChops, Image

from PiFinder.obj_types import OBJ_TYPE_MARKERS
from PiFinder import plot
from PiFinder.ui.base import UIModule


class UIChart(UIModule):
    __title__ = "CHART"
    _config_options = {
        "Reticle": {
            "type": "enum",
            "value": "Med",
            "options": ["Off", "Low", "Med", "High"],
            "hotkey": "B",
        },
        "Constellations": {
            "type": "enum",
            "value": "Med",
            "options": ["Off", "Low", "Med", "High"],
            "hotkey": "C",
        },
        "Obs List": {
            "type": "enum",
            "value": "Med",
            "options": ["Off", "Low", "Med", "High"],
            "hotkey": "D",
        },
    }

    def __init__(self, *args):
        super().__init__(*args)
        self.last_update = time.time()
        self.starfield = plot.Starfield(self.colors)
        self.solution = None
        self.fov_list = [5, 10.2, 20, 30, 60]
        self.fov_index = 1
        self.fov_set_time = time.time()
        self.fov_target_time = None
        self.desired_fov = self.fov_list[self.fov_index]
        self.fov = self.desired_fov
        self.set_fov(self.desired_fov)

    def plot_markers(self):
        """
        Plot the contents of the observing list
        and target if there is one
        """
        if not self.solution:
            return

        marker_list = []

        # is there a target?
        target = self.ui_state["target"]
        if target:
            marker_list.append(
                (plot.Angle(degrees=target.ra)._hours, target.dec, "target")
            )

        if self._config_options["Obs List"]["value"] != "Off":
            for obs_target in self.ui_state["observing_list"]:
                marker = OBJ_TYPE_MARKERS.get(obs_target.obj_type)
                if marker:
                    marker_list.append(
                        (
                            plot.Angle(degrees=obs_target.ra)._hours,
                            obs_target.dec,
                            marker,
                        )
                    )

        if marker_list != []:
            marker_image = self.starfield.plot_markers(
                marker_list,
            )
            marker_brightness = 255
            if self._config_options["Obs List"]["value"] == "Low":
                marker_brightness = 64
            if self._config_options["Obs List"]["value"] == "Med":
                marker_brightness = 128

            marker_image = ImageChops.multiply(
                marker_image,
                Image.new("RGB", (128, 128), self.colors.get(marker_brightness)),
            )
            self.screen.paste(ImageChops.add(self.screen, marker_image))

    def draw_reticle(self):
        """
        draw the reticle if desired
        """
        if self._config_options["Reticle"]["value"] == "Off":
            # None....
            return

        brightness = (
            self._config_options["Reticle"]["options"].index(
                self._config_options["Reticle"]["value"]
            )
            * 32
        )

        fov = self.fov
        for circ_deg in [4, 2, 0.5]:
            circ_rad = ((circ_deg / fov) * 128) / 2
            bbox = [
                64 - circ_rad,
                64 - circ_rad,
                64 + circ_rad,
                64 + circ_rad,
            ]
            self.draw.arc(bbox, 20, 70, fill=self.colors.get(brightness))
            self.draw.arc(bbox, 110, 160, fill=self.colors.get(brightness))
            self.draw.arc(bbox, 200, 250, fill=self.colors.get(brightness))
            self.draw.arc(bbox, 290, 340, fill=self.colors.get(brightness))

    def set_fov(self, fov):
        self.starting_fov = self.fov
        self.fov_starting_time = time.time()
        self.desired_fov = fov

    def animate_fov(self):
        if self.fov == self.desired_fov:
            return

        fov_progress = (time.time() - self.fov_starting_time) * 20
        if self.desired_fov > self.starting_fov:
            current_fov = self.starting_fov + fov_progress
            if current_fov > self.desired_fov:
                current_fov = self.desired_fov
        else:
            current_fov = self.starting_fov - fov_progress
            if current_fov < self.desired_fov:
                current_fov = self.desired_fov
        self.fov = current_fov
        self.starfield.set_fov(current_fov)

    def update(self, force=False):
        if force:
            self.last_update = 0

        if self.shared_state.solve_state():
            self.animate_fov()
            constellation_brightness = (
                self._config_options["Constellations"]["options"].index(
                    self._config_options["Constellations"]["value"]
                )
                * 32
            )
            self.solution = self.shared_state.solution()
            last_solve_time = self.solution["solve_time"]
            if (
                last_solve_time > self.last_update
                and self.solution["Roll"] != None
                and self.solution["RA"] != None
                and self.solution["Dec"] != None
            ):
                # This needs to be called first to set RA/DEC/ROLL
                image_obj = self.starfield.plot_starfield(
                    self.solution["RA"],
                    self.solution["Dec"],
                    self.solution["Roll"],
                    constellation_brightness,
                )
                image_obj = ImageChops.multiply(
                    image_obj.convert("RGB"), self.colors.red_image
                )
                self.screen.paste(image_obj)

                self.plot_markers()
                self.last_update = last_solve_time

        else:
            self.draw.rectangle([0, 0, 128, 128], fill=self.colors.get(0))
            self.draw.text(
                (18, 20), "Can't plot", font=self.font_large, fill=self.colors.get(255)
            )
            self.draw.text(
                (25, 50), "No Solve Yet", font=self.font_base, fill=self.colors.get(255)
            )

        self.draw_reticle()
        return self.screen_update()

    def change_fov(self, direction):
        self.fov_index += direction
        if self.fov_index < 0:
            self.fov_index = 0
        if self.fov_index >= len(self.fov_list):
            self.fov_index = len(self.fov_list) - 1
        self.set_fov(self.fov_list[self.fov_index])
        self.update(force=True)

    def key_up(self):
        self.change_fov(-1)

    def key_down(self):
        self.change_fov(1)

    def key_enter(self):
        # Set back to 10.2 to match the camera view
        self.fov_index = 1
        self.set_fov(self.fov_list[self.fov_index])
        self.update()
