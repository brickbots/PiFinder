#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module contains all the UI Module classes

"""
import time
from PIL import Image, ImageDraw, ImageFont, ImageChops, ImageOps

from PiFinder.image_util import gamma_correct_low, subtract_background, red_image
from PiFinder.ui.base import UIModule

RED = (0, 0, 255)


class UIPreview(UIModule):
    __title__ = "PREVIEW"

    def __init__(self, *args):
        self.reticle_mode = 2
        self.last_update = time.time()
        self.solution = None
        super().__init__(*args)

    def draw_reticle(self):
        """
        draw the reticle if desired
        """
        if self.reticle_mode == 0:
            # None....
            return

        brightness = 64
        if self.reticle_mode == 1:
            brightness = 32

        bboxes = [
            [39, 39, 89, 89],
            [52, 52, 76, 76],
            [61, 61, 67, 67],
        ]
        for bbox in bboxes:
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
            image_obj = image_obj.resize((128, 128), Image.LANCZOS)
            image_obj = subtract_background(image_obj)
            image_obj = image_obj.convert("RGB")
            image_obj = ImageChops.multiply(image_obj, red_image)
            image_obj = ImageOps.autocontrast(image_obj)
            image_obj = Image.eval(image_obj, gamma_correct_low)
            self.screen.paste(image_obj)
            self.last_update = last_image_time

            self.title = "PREVIEW"

        self.draw_reticle()
        return self.screen_update()

    def key_c(self):
        self.reticle_mode += 1
        if self.reticle_mode > 2:
            self.reticle_mode = 0
        self.update(force=True)

    def key_up(self):
        self.command_queues["camera"].put("exp_up")

    def key_down(self):
        self.command_queues["camera"].put("exp_dn")

    def key_enter(self):
        self.command_queues["camera"].put("exp_save")
