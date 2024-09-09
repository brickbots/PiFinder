#!/usr/bin/python
# -*- coding:utf-8 -*-
# mypy: ignore-errors
"""
This module contains all the UI Module classes

"""

import time
import numpy as np
from PIL import ImageChops

from PiFinder.ui.marking_menus import MarkingMenuOption, MarkingMenu
from PiFinder import plot
from PiFinder.ui.base import UIModule


class UIAlign(UIModule):
    __title__ = "ALIGN"
    __help_name__ = "align"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.last_update = time.time()
        self.starfield = plot.Starfield(self.colors, self.display_class.resolution)
        self.solution = None
        self.fov_list = [5, 10.2, 20, 30, 60]
        self.fov_index = 1
        self.fov_set_time = time.time()
        self.fov_target_time = None
        self.desired_fov = self.fov_list[self.fov_index]
        self.fov = self.desired_fov
        self.set_fov(self.desired_fov)
        self.align_mode = False
        self.visible_stars = None
        self.star_list = np.empty((0, 2))
        self.alignment_star = None
        self.reticle_position = (
            self.config_object.get_option("solve_pixel", (256, 256))[0] / 4,
            self.config_object.get_option("solve_pixel", (256, 256))[1] / 4,
        )

        # Marking menu definition
        self.marking_menu = MarkingMenu(
            left=MarkingMenuOption(),
            down=MarkingMenuOption(
                label="Options",
                menu_jump="chart_settings",
            ),
            right=MarkingMenuOption(),
        )

    def draw_reticle(self):
        """
        draw the reticle if desired
        """
        if not self.solution:
            return

        if not self.align_mode:
            self.reticle_position = self.starfield.radec_to_xy(
                self.solution["RA"], self.solution["Dec"]
            )

        x_pos = round(self.reticle_position[0])
        y_pos = round(self.reticle_position[1])

        # Draw cross
        self.draw.line(
            [x_pos, y_pos - 8, x_pos, y_pos - 3],
            fill=self.colors.get(255),
        )
        self.draw.line(
            [x_pos, y_pos + 3, x_pos, y_pos + 8],
            fill=self.colors.get(255),
        )
        self.draw.line(
            [x_pos - 8, y_pos, x_pos - 3, y_pos],
            fill=self.colors.get(255),
        )

        self.draw.line(
            [x_pos + 3, y_pos, x_pos + 8, y_pos],
            fill=self.colors.get(255),
        )

    def set_fov(self, fov):
        self.fov = fov
        self.starfield.set_fov(fov)
        return

        # TODO: Fix zoom animation
        self.starting_fov = self.fov
        self.fov_starting_time = time.time()
        self.desired_fov = fov

    def animate_fov(self):
        # TODO: Fix zoom animation
        return
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
            constellation_brightness = self.config_object.get_option(
                "chart_constellations", 64
            )
            self.solution = self.shared_state.solution()
            last_solve_time = self.solution["solve_time"]
            if (
                last_solve_time > self.last_update
                and self.solution["Roll"] is not None
                and self.solution["RA"] is not None
                and self.solution["Dec"] is not None
            ) or force:
                # This needs to be called first to set RA/DEC/ROLL
                # We want to use the CAMERA center here as we'll be moving
                # the reticle to the star
                image_obj, self.visible_stars = self.starfield.plot_starfield(
                    self.solution["RA_camera"],
                    self.solution["Dec_camera"],
                    self.solution["Roll_camera"],
                    constellation_brightness,
                )
                image_obj = ImageChops.multiply(
                    image_obj.convert("RGB"), self.colors.red_image
                )
                self.screen.paste(image_obj)

                self.last_update = last_solve_time
            self.draw_reticle()

        else:
            self.draw.rectangle(
                [0, 0, self.display_class.resX, self.display_class.resY],
                fill=self.colors.get(0),
            )
            self.draw.text(
                (self.display_class.titlebar_height + 2, 20),
                "Can't plot",
                font=self.fonts.large.font,
                fill=self.colors.get(255),
            )
            self.draw.text(
                (self.display_class.titlebar_height + 2 + self.fonts.large.height, 50),
                "No Solve Yet",
                font=self.fonts.base.font,
                fill=self.colors.get(255),
            )

        return self.screen_update(title_bar=not self.align_mode)

    def change_fov(self, direction):
        self.fov_index += direction
        if self.fov_index < 0:
            self.fov_index = 0
        if self.fov_index >= len(self.fov_list):
            self.fov_index = len(self.fov_list) - 1
        self.set_fov(self.fov_list[self.fov_index])
        self.update(force=True)

    def radec_to_cam_pixel(self, ra: float, dec: float) -> tuple[int, int]:
        self.command_queues["solver"].put(["align_on_radec", ra, dec])
        # for expediency, just return the selected star pixels
        return (self.alignment_star["x_pos"], self.alignment_star["y_pos"])

    def switch_align_star(self, direction: str) -> None:
        # iterate through all stars with screen coord on the requested
        # side of the screen, find the closest, set thos coordinates
        mag_limit = 5.5

        # This 'pushes' the target in the direction of the
        # arrow press to bias the closeness in that direction
        offset_bias = 1

        # filter with numpy
        # mag /screen limits
        candidate_stars = self.visible_stars
        candidate_stars = candidate_stars[
            (
                (candidate_stars["x_pos"] > 0)
                & (candidate_stars["x_pos"] < self.display_class.resolution[0])
                & (candidate_stars["y_pos"] > 0)
                & (candidate_stars["y_pos"] < self.display_class.resolution[1])
                & (candidate_stars["magnitude"] < mag_limit)
            )
        ]
        if direction == "up":
            candidate_stars = candidate_stars[
                (candidate_stars["y_pos"] < self.reticle_position[1] - offset_bias)
            ]
        if direction == "down":
            candidate_stars = candidate_stars[
                (candidate_stars["y_pos"] > self.reticle_position[1] + offset_bias)
            ]
        if direction == "left":
            candidate_stars = candidate_stars[
                (candidate_stars["x_pos"] < self.reticle_position[0] - offset_bias)
            ]

        if direction == "right":
            candidate_stars = candidate_stars[
                (candidate_stars["x_pos"] > self.reticle_position[0] + offset_bias)
            ]

        if len(candidate_stars) == 0:
            return

        # calculate distance in screen space
        candidate_stars = candidate_stars.assign(
            distance=np.hypot(
                candidate_stars["x_pos"] - self.reticle_position[0],
                candidate_stars["y_pos"] - self.reticle_position[1],
            )
        )

        candidate_stars = candidate_stars.sort_values("distance")

        self.alignment_star = candidate_stars.iloc[0]

        self.reticle_position = (
            self.alignment_star["x_pos"],
            self.alignment_star["y_pos"],
        )

        # Send command to solver to work out the camera pixel for this target
        self.command_queues["solver"].put(
            [
                "align_on_radec",
                self.alignment_star["ra_degrees"],
                self.alignment_star["dec_degrees"],
            ]
        )

        self.update(force=True)

        return

    def key_plus(self):
        self.change_fov(-1)

    def key_minus(self):
        self.change_fov(1)

    def key_square(self):
        self.align_mode = not self.align_mode
        self.update(force=True)

    def key_up(self):
        if self.align_mode:
            self.switch_align_star("up")

    def key_down(self):
        if self.align_mode:
            self.switch_align_star("down")

    def key_right(self):
        if self.align_mode:
            self.switch_align_star("right")

    def key_left(self):
        if self.align_mode:
            self.switch_align_star("left")
            return False
        return True

    def key_number(self, number):
        if self.align_mode:
            if number == 0:
                # reset reticle
                self.shared_state.set_solve_pixel((256, 256))
                self.config_object.set_option("solve_pixel", (256, 256))
                self.reticle_position = (64, 64)
                self.align_mode = False
                self.update(force=True)
