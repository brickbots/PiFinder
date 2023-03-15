#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module contains all the UI Module classes

"""
import time
from PIL import Image, ImageDraw, ImageFont, ImageChops, ImageOps

from PiFinder.image_util import (
    gamma_correct_high,
    gamma_correct_med,
    gamma_correct_low,
    subtract_background,
    red_image,
)
from PiFinder.ui.base import UIModule

RED = (0, 0, 255)


class UIPreview(UIModule):
    __title__ = "PREVIEW"
    _config_options = {
        "Reticle": {
            "type": "enum",
            "value": "Low",
            "options": ["Off", "Low", "Med", "High"],
            "hotkey": "B",
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
            "hotkey": "D",
        },
        "Exposure": {
            "type": "enum",
            "value": "",
            "options": [0.2,0.4, 0.75, 1,1.25,1.5,2],
            "callback": "set_exp",
        },
        "Gain": {
            "type": "enum",
            "value": "",
            "options": [1,4,10,14,20],
            "callback": "set_gain",
        },
        "Save Exp": {
            "type": "enum",
            "value": "",
            "options": ["Save", "Exit"],
            "callback": "save_exp",
        },
        "Focus Hlp": {
            "type": "bool",
            "value": "Off",
            "options": ["On", "Off"],
        },
    }

    def __init__(self, *args):
        super().__init__(*args)

        exposure_time = cfg.get_option("camera_exp")
        analog_gain = cfg.get_option("camera_gain")
        self.config_item["Gain"]["value"] = analog_gain
        self.config_item["Exposure"]["value"] = int(exposure_time / 1000000)
        self.reticle_mode = 2
        self.last_update = time.time()
        self.solution = None

    def save_exp(self, option):
        if option == "Save":
            self.

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
        for circ_deg in [4, 2, 0.5]:
            circ_rad = ((circ_deg / fov) * 128) / 2
            bbox = [
                64 - circ_rad,
                64 - circ_rad,
                64 + circ_rad,
                64 + circ_rad,
            ]
            self.draw.arc(bbox, 20, 70, fill=(0, 0, brightness))
            self.draw.arc(bbox, 110, 160, fill=(0, 0, brightness))
            self.draw.arc(bbox, 200, 250, fill=(0, 0, brightness))
            self.draw.arc(bbox, 290, 340, fill=(0, 0, brightness))

    def update(self, force=False):
        if force:
            self.last_update = 0
        # display an image
        last_image_time = self.shared_state.last_image_time()[1]
        if last_image_time > self.last_update:
            image_obj = self.camera_image.copy()
            if self._config_options["Focus Hlp"]["value"] == "Off":
                # Resize
                image_obj = image_obj.resize((128, 128))
            else:
                image_obj = image_obj.crop((192, 192, 320, 320))
            if self._config_options["BG Sub"]["value"] == "On":
                image_obj = subtract_background(image_obj)
            image_obj = image_obj.convert("RGB")
            image_obj = ImageChops.multiply(image_obj, red_image)
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

        self.draw_reticle()
        return self.screen_update()

    def key_up(self):
        self.command_queues["camera"].put("exp_up")

    def key_down(self):
        self.command_queues["camera"].put("exp_dn")

    def key_enter(self):
        self.command_queues["camera"].put("exp_save")
