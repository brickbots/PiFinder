#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module contains all the UI Module classes

"""

import sys
import numpy as np
import time

from PIL import Image, ImageChops, ImageOps

from PiFinder.ui.marking_menus import MarkingMenuOption, MarkingMenu
from PiFinder import utils
from PiFinder.ui.base import UIModule
from PiFinder.image_util import (
    gamma_correct_high,
    gamma_correct_med,
    gamma_correct_low,
    subtract_background,
)

sys.path.append(str(utils.tetra3_dir))


class UIPreview(UIModule):
    from PiFinder import tetra3

    __title__ = "CAMERA"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.reticle_mode = 2
        self.last_update = time.time()
        self.solution = None

        self.capture_prefix = f"{self.__uuid__}_diag"
        self.capture_count = 0

        self.align_mode = False

        # the centroiding returns an ndarray
        # so we're initialiazing one here
        self.star_list = np.empty((0, 2))
        self.highlight_count = 0

        # Marking menu definition
        self.marking_menu = MarkingMenu(
            left=MarkingMenuOption(
                label="Exposure",
                menu_jump="camera_exposure",
            ),
            down=MarkingMenuOption(
                label="Gamma",
                callback=MarkingMenu(
                    up=MarkingMenuOption(label="Off", callback=self.mm_change_gamma),
                    left=MarkingMenuOption(label="High", callback=self.mm_change_gamma),
                    down=MarkingMenuOption(
                        label="Medium",
                        callback=self.mm_change_gamma,
                        selected=True,
                    ),
                    right=MarkingMenuOption(label="Low", callback=self.mm_change_gamma),
                ),
            ),
            right=MarkingMenuOption(
                label="BG Sub",
                callback=MarkingMenu(
                    up=MarkingMenuOption(label="Off", callback=self.mm_change_bgsub),
                    left=MarkingMenuOption(label="Full", callback=self.mm_change_bgsub),
                    down=MarkingMenuOption(),
                    right=MarkingMenuOption(
                        label="Half", callback=self.mm_change_bgsub, selected=True
                    ),
                ),
            ),
        )

    def mm_change_gamma(self, marking_menu, menu_item):
        """
        Called to change gamma adjust value
        """
        marking_menu.select_none()
        menu_item.selected = True

        self.config_object.set_option("session.camera_gamma", menu_item.label)
        return True

    def mm_change_bgsub(self, marking_menu, menu_item):
        """
        Called to change bg sub amount
        """
        marking_menu.select_none()
        menu_item.selected = True

        self.config_object.set_option("session.camera_bg_sub", menu_item.label)
        return True

    def draw_reticle(self):
        """
        draw the reticle if desired
        """
        reticle_brightness = self.config_object.get_option("camera_reticle", 128)
        if reticle_brightness == 0:
            # None....
            return

        fov = 10.2
        solve_pixel = self.shared_state.solve_pixel(screen_space=True)
        for circ_deg in [4, 2, 0.5]:
            circ_rad = ((circ_deg / fov) * self.display_class.resX) / 2
            bbox = [
                solve_pixel[0] - circ_rad,
                solve_pixel[1] - circ_rad,
                solve_pixel[0] + circ_rad,
                solve_pixel[1] + circ_rad,
            ]
            self.draw.arc(bbox, 20, 70, fill=self.colors.get(reticle_brightness))
            self.draw.arc(bbox, 110, 160, fill=self.colors.get(reticle_brightness))
            self.draw.arc(bbox, 200, 250, fill=self.colors.get(reticle_brightness))
            self.draw.arc(bbox, 290, 340, fill=self.colors.get(reticle_brightness))

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
                    font=self.fonts.small.font,
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
            if self.align_mode and self.shared_state and self.shared_state.solution():
                matched_centroids = self.shared_state.solution()["matched_centroids"]
                self.star_list = np.array(matched_centroids)

            # Resize
            image_obj = image_obj.resize((128, 128))
            bg_sub = self.config_object.get_option("session.camera_bg_sub", "Half")
            if bg_sub == "Half":
                image_obj = subtract_background(image_obj, percent=0.5)
            elif bg_sub == "Full":
                image_obj = subtract_background(image_obj, percent=1)
            image_obj = image_obj.convert("RGB")
            image_obj = ImageChops.multiply(image_obj, self.colors.red_image)
            image_obj = ImageOps.autocontrast(image_obj)

            gamma_adjust = self.config_object.get_option("session.camera_gamma", "Med")
            if gamma_adjust == "Low":
                image_obj = Image.eval(image_obj, gamma_correct_low)
            elif gamma_adjust == "Medium":
                image_obj = Image.eval(image_obj, gamma_correct_med)
            elif gamma_adjust == "High":
                image_obj = Image.eval(image_obj, gamma_correct_high)

            self.screen.paste(image_obj)
            self.last_update = last_image_time

            if self.align_mode:
                self.draw_star_selectors()
            else:
                self.draw_reticle()

        return self.screen_update(
            title_bar=not self.align_mode, button_hints=not self.align_mode
        )

    def key_up(self):
        """
        leave bright star alignment mode
        """
        if not self.align_mode:
            return

        self.align_mode = False
        self.shared_state.set_camera_align(self.align_mode)
        self.update(force=True)

    def key_down(self):
        """
        Enter bright star alignment mode
        """
        if self.align_mode:
            return

        self.align_mode = True
        self.shared_state.set_camera_align(self.align_mode)
        self.update(force=True)

    def key_number(self, number):
        if self.align_mode:
            if number == 0:
                # reset reticle
                self.shared_state.set_solve_pixel((256, 256))
                self.config_object.set_option("solve_pixel", (256, 256))
                self.align_mode = False
            if number in list(range(1, self.highlight_count + 1)):
                # They picked a star to align....
                star_index = number - 1
                if self.star_list.shape[0] > star_index:
                    star_cam_x = self.star_list[star_index][0]
                    star_cam_y = self.star_list[star_index][1]
                    self.shared_state.set_solve_pixel((star_cam_x, star_cam_y))
                    self.config_object.set_option(
                        "solve_pixel",
                        (star_cam_x, star_cam_y),
                    )
                self.align_mode = False

            self.shared_state.set_camera_align(self.align_mode)
            self.update(force=True)
