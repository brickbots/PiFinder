#!/usr/bin/python
# -*- coding:utf-8 -*-
# mypy: ignore-errors
"""
This module contains all the UI Module classes

"""

import time
from PIL import ImageChops, Image

from PiFinder.ui.marking_menus import MarkingMenuOption, MarkingMenu
from PiFinder.obj_types import OBJ_TYPE_MARKERS
from PiFinder import plot
from PiFinder.ui.base import UIModule
from PiFinder import calc_utils


class UIChart(UIModule):
    __title__ = "CHART"
    __help_name__ = "chart"

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

        # Marking menu definition
        self.marking_menu = MarkingMenu(
            left=MarkingMenuOption(),
            down=MarkingMenuOption(),
            right=MarkingMenuOption(),
        )

    def plot_markers(self):
        """
        Plot the contents of the observing list
        and target if there is one
        """
        if not self.solution:
            return

        marker_list = []

        # is there a target?
        target = self.ui_state.target()
        if target:
            marker_list.append(
                (plot.Angle(degrees=target.ra)._hours, target.dec, "target")
            )

        marker_brightness = self.config_object.get_option("chart_dso", 128)
        if marker_brightness == 0:
            return

        for obs_target in self.ui_state.observing_list():
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

            marker_image = ImageChops.multiply(
                marker_image,
                Image.new(
                    "RGB",
                    self.display_class.resolution,
                    self.colors.get(marker_brightness),
                ),
            )
            self.screen.paste(ImageChops.add(self.screen, marker_image))

    def draw_reticle(self):
        """
        draw the reticle if desired
        """
        brightness = self.config_object.get_option("chart_reticle", 128)
        if brightness == 0:
            # None....
            return

        fov = self.fov
        for circ_deg in [4, 2, 0.5]:
            circ_rad = ((circ_deg / fov) * self.display_class.fov_res) / 2
            bbox = [
                self.display_class.centerX - circ_rad,
                self.display_class.centerY - circ_rad,
                self.display_class.centerX + circ_rad,
                self.display_class.centerY + circ_rad,
            ]
            self.draw.arc(bbox, 20, 70, fill=self.colors.get(brightness))
            self.draw.arc(bbox, 110, 160, fill=self.colors.get(brightness))
            self.draw.arc(bbox, 200, 250, fill=self.colors.get(brightness))
            self.draw.arc(bbox, 290, 340, fill=self.colors.get(brightness))

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
            ):
                # This needs to be called first to set RA/DEC/ROLL
                image_obj, _visible_stars = self.starfield.plot_starfield(
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

                # Display RA/DEC in selected format if enabled
                if self.config_object.get_option("chart_radec") == "HH:MM":
                    ra_h, ra_m, ra_s = calc_utils.ra_to_hms(self.solution["RA"])
                    dec_d, dec_m, dec_s = calc_utils.dec_to_dms(self.solution["Dec"])
                    ra_dec_disp = f"{ra_h:02d}:{ra_m:02d}:{ra_s:02d} / {dec_d:02d}°{dec_m:02d}:{dec_s}"
                    self.draw.text(
                        (0, 114),
                        ra_dec_disp,
                        font=self.fonts.base.font,
                        fill=self.colors.get(255),
                    )
                if self.config_object.get_option("chart_radec") == "Degr":
                    ra_h, ra_m, ra_s = calc_utils.ra_to_hms(self.solution["RA"])
                    dec_d, dec_m, dec_s = calc_utils.dec_to_dms(self.solution["Dec"])
                    ra_dec_disp = (
                        f"{self.solution['RA']:0>6.2f} / {self.solution['Dec']:0>5.2f}"
                    )
                    self.draw.text(
                        (0, 114),
                        ra_dec_disp,
                        font=self.fonts.base.font,
                        fill=self.colors.get(255),
                    )

                self.last_update = last_solve_time

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

    def key_plus(self):
        self.change_fov(-1)

    def key_minus(self):
        self.change_fov(1)

    def key_square(self):
        # Set back to 10.2 to match the camera view
        self.fov_index = 1
        self.set_fov(self.fov_list[self.fov_index])
        self.update()
