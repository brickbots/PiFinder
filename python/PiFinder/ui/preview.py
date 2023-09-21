#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module contains all the UI Module classes

"""
import uuid
import os
import time
from PIL import Image, ImageDraw, ImageFont, ImageChops, ImageOps
from PiFinder.ui.fonts import Fonts as fonts
from PiFinder import tetra3
from numpy import ndarray

from PiFinder.image_util import (
    gamma_correct_high,
    gamma_correct_med,
    gamma_correct_low,
    subtract_background,
)
from PiFinder.ui.base import UIModule


class UIPreview(UIModule):
    __title__ = "PREVIEW"
    _config_options = {
        "Reticle": {
            "type": "enum",
            "value": "Low",
            "options": ["Off", "Low", "Med", "High"],
            "hotkey": "D",
            "callback": "exit_config",
        },
        "BG Sub": {
            "type": "bool",
            "value": "On",
            "options": ["On", "Off"],
            "hotkey": "C",
        },
        "Gamma Adj": {
            "type": "enum",
            "value": "Low",
            "options": ["Off", "Low", "Med", "High"],
        },
        "Exposure": {
            "type": "enum",
            "value": "",
            "options": [0.05, 0.2, 0.4, 0.75, 1, 1.25, 1.5, 2],
            "callback": "set_exp",
        },
        "Gain": {
            "type": "enum",
            "value": "",
            "options": [1, 4, 10, 14, 20],
            "callback": "set_gain",
        },
        "Save Exp": {
            "type": "enum",
            "value": "",
            "options": ["Save", "Exit"],
            "callback": "save_exp",
        },
    }

    def __init__(self, *args):
        super().__init__(*args)

        exposure_time = self.config_object.get_option("camera_exp")
        analog_gain = self.config_object.get_option("camera_gain")
        self._config_options["Gain"]["value"] = analog_gain
        self._config_options["Exposure"]["value"] = exposure_time / 1000000
        self.reticle_mode = 2
        self.last_update = time.time()
        self.solution = None

        self.capture_prefix = f"{self.__uuid__}_diag"
        self.capture_count = 0

        self.align_mode = False

        # the centroiding returns an ndarray
        # so we're initialiazing one here
        self.star_list = ndarray((0, 2))

    def set_exp(self, option):
        new_exposure = int(option * 1000000)
        self.command_queues["camera"].put(f"set_exp:{new_exposure}")
        self.message("Exposure Set")
        return False

    def set_gain(self, option):
        self.command_queues["camera"].put(f"set_gain:{option}")
        self.message("Gain Set")
        return False

    def save_exp(self, option):
        if option == "Save":
            self.command_queues["camera"].put("exp_save")
            self.message("Exposure Saved")
            return True
        return False

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

        fov = 10.2
        solve_pixel = self.shared_state.solve_pixel(screen_space=True)
        for circ_deg in [4, 2, 0.5]:
            circ_rad = ((circ_deg / fov) * 128) / 2
            bbox = [
                solve_pixel[0] - circ_rad,
                solve_pixel[1] - circ_rad,
                solve_pixel[0] + circ_rad,
                solve_pixel[1] + circ_rad,
            ]
            self.draw.arc(bbox, 20, 70, fill=self.colors.get(brightness))
            self.draw.arc(bbox, 110, 160, fill=self.colors.get(brightness))
            self.draw.arc(bbox, 200, 250, fill=self.colors.get(brightness))
            self.draw.arc(bbox, 290, 340, fill=self.colors.get(brightness))

    def draw_star_selectors(self):
        # Draw star selectors
        if self.star_list.shape[0] > 0:
            self.highlight_count = 3
            if self.star_list.shape[0] < self.highlight_count:
                self.highlight_count = self.star_list.shape[0]

            for _i in range(self.highlight_count):
                raw_y, raw_x = self.star_list[_i]
                star_x = int(raw_x / 4)
                star_y = int(raw_y / 4)

                x_direction = 1
                x_text_offset = 6
                y_direction = 1
                y_text_offset = -12

                if star_x > 108:
                    x_direction = -1
                    x_text_offset = -10
                if star_y < 38:
                    y_direction = -1
                    y_text_offset = 1

                self.draw.line(
                    [
                        (star_x, star_y - (4 * y_direction)),
                        (star_x, star_y - (12 * y_direction)),
                    ],
                    fill=self.colors.get(128),
                )

                self.draw.line(
                    [
                        (star_x + (4 * x_direction), star_y),
                        (star_x + (12 * x_direction), star_y),
                    ],
                    fill=self.colors.get(128),
                )

                self.draw.text(
                    (star_x + x_text_offset, star_y + y_text_offset),
                    str(_i + 1),
                    font=fonts.small,
                    fill=self.colors.get(128),
                )

    def update(self, force=False):
        if force:
            self.last_update = 0
        # display an image
        last_image_time = self.shared_state.last_image_metadata()["exposure_end"]
        if last_image_time > self.last_update:
            image_obj = self.camera_image.copy()

            # Fetch Centroids before image is altered
            # Do this at least once to get a numpy array in
            # star_list
            if self.align_mode:
                self.star_list = tetra3.get_centroids_from_image(image_obj)

            # Resize
            image_obj = image_obj.resize((128, 128))
            if self._config_options["BG Sub"]["value"] == "On":
                image_obj = subtract_background(image_obj)
            image_obj = image_obj.convert("RGB")
            image_obj = ImageChops.multiply(image_obj, self.colors.red_image)
            image_obj = ImageOps.autocontrast(image_obj)

            if self._config_options["Gamma Adj"]["value"] == "Low":
                image_obj = Image.eval(image_obj, gamma_correct_low)
            if self._config_options["Gamma Adj"]["value"] == "Med":
                image_obj = Image.eval(image_obj, gamma_correct_med)
            if self._config_options["Gamma Adj"]["value"] == "High":
                image_obj = Image.eval(image_obj, gamma_correct_high)

            self.screen.paste(image_obj)
            self.last_update = last_image_time

            self.title = "PREVIEW"

            if self.align_mode:
                self.draw_star_selectors()

        self.draw_reticle()
        return self.screen_update()

    def key_b(self):
        """
        Enter bright star alignment mode
        """
        if self.align_mode:
            self.align_mode = False
        else:
            self.align_mode = True

        self.update(force=True)

    def key_number(self, number):
        if self.align_mode:
            if number == 0:
                # reset reticle
                self.shared_state.set_solve_pixel((256, 256))
                self.config_object.set_option("solve_pixel", (256, 256))
                self.align_mode = False
                self.update(force=True)
            if number in list(range(1, self.highlight_count + 1)):
                # They picked a star to align....
                star_index = number - 1
                if self.star_list.shape[0] > star_index:
                    self.shared_state.set_solve_pixel(
                        (self.star_list[star_index][0], self.star_list[star_index][1])
                    )
                    self.config_object.set_option(
                        "solve_pixel",
                        (
                            float(self.star_list[star_index][0]),
                            float(self.star_list[star_index][1]),
                        ),
                    )
                self.align_mode = False
                self.update(force=True)
