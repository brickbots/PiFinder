#!/usr/bin/python
# -*- coding:utf-8 -*-
# mypy: ignore-errors
"""
This module contains the chart (starfield + constellation lines) UI Module class

"""

from __future__ import (
    annotations,
)  # To support | in typehints (remove this for Python 3.10+)

import datetime
import logging
import time
from PIL import ImageChops, Image

from PiFinder.ui.marking_menus import MarkingMenuOption, MarkingMenu
from PiFinder.obj_types import OBJ_TYPE_MARKERS
from PiFinder import plot
from PiFinder.ui.base import UIModule
from PiFinder import calc_utils


logger = logging.getLogger("Chart")


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
            down=MarkingMenuOption(
                label=_("Settings"),
                menu_jump="chart_settings",
            ),
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
            last_estimate_time = self.solution.estimate_time

            if last_estimate_time is None:
                self.plot_no_solve()
            elif self.solution_is_new(last_estimate_time):
                aligned = self.solution.pointing.aligned.estimate
                # Solution is new so plot the updated chart
                chart_rot_angle = get_chart_rotation_angle(
                    aligned.RA,
                    aligned.Dec,
                    chart_coord_sys=self.config_object.get_option("chart_coord_sys"),
                    location=self.shared_state.location(),
                    dt=self.shared_state.datetime(),
                )
                # This needs to be called first to set RA/DEC/chart_rot_angle
                image_obj, _visible_stars = self.starfield.plot_starfield(
                    aligned.RA,
                    aligned.Dec,
                    chart_rot_angle,
                    constellation_brightness,
                )
                image_obj = ImageChops.multiply(
                    image_obj.convert("RGB"), self.colors.red_image
                )
                self.screen.paste(image_obj)

                self.plot_markers()

                # Display RA/DEC in selected format if enabled
                if self.config_object.get_option("chart_radec") == "HH:MM":
                    ra_h, ra_m, ra_s = calc_utils.ra_to_hms(aligned.RA)
                    dec_d, dec_m, dec_s = calc_utils.dec_to_dms(aligned.Dec)
                    ra_dec_disp = f"{ra_h:02d}:{ra_m:02d}:{ra_s:02d} / {dec_d:02d}°{dec_m:02d}:{dec_s}"
                    self.draw.text(
                        (0, 114),
                        ra_dec_disp,
                        font=self.fonts.base.font,
                        fill=self.colors.get(255),
                    )
                if self.config_object.get_option("chart_radec") == "Degr":
                    ra_h, ra_m, ra_s = calc_utils.ra_to_hms(aligned.RA)
                    dec_d, dec_m, dec_s = calc_utils.dec_to_dms(aligned.Dec)
                    ra_dec_disp = f"{aligned.RA:0>6.2f} / {aligned.Dec:0>5.2f}"
                    self.draw.text(
                        (0, 114),
                        ra_dec_disp,
                        font=self.fonts.base.font,
                        fill=self.colors.get(255),
                    )

                self.last_update = last_estimate_time

                self.draw_reticle()
        else:
            self.plot_no_solve()

        return self.screen_update()

    def plot_no_solve(self):
        """Plot message: Can't plot No solve yet"""
        self.draw.rectangle(
            [0, 0, self.display_class.resX, self.display_class.resY],
            fill=self.colors.get(0),
        )
        self.draw.text(
            (16, self.display_class.titlebar_height + 10),
            _("Can't plot"),
            font=self.fonts.large.font,
            fill=self.colors.get(255),
        )
        self.draw.text(
            (
                26,
                self.display_class.titlebar_height + 10 + self.fonts.large.height + 4,
            ),
            _("No Solve Yet"),
            font=self.fonts.base.font,
            fill=self.colors.get(255),
        )

    def solution_is_new(self, last_estimate_time):
        """
        Returns True if the solution (coordinates) is valid and new since
        last_estimate_time.
        """
        if last_estimate_time is None or self.last_update is None:
            return False
        if last_estimate_time <= self.last_update:
            return False
        if not self.solution.has_pointing():
            return False

        return True  # Solution is valid and new

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


def get_chart_rotation_angle(
    ra_deg: float,  # Right Ascension of the target in degrees
    dec_deg: float,  # Declination of the target in degrees
    chart_coord_sys: str,
    location=None,
    dt: datetime.datetime | None = None,
) -> float:
    """
    Returns angle (in degrees) to rotate the chart by depending on the
    configured chart coordinate system. This was previously called "roll".
    Chart will be plotted rotated around (RA, Dec); +ve means anti-clockwise
    rotation. The RA and Dec of the target should be provided (in degrees).

    * horiz: Display the chart in the horizontal coordinate so that up in the
    chart points to the Zenith.
    * EQ (Auto): Display the chart in the equatorial coordinate system.
    Automatically select NCP or SCP-up based on location.
    * EQ (North-up), EQ (South-up): Display chart in the equatorial coordinate
    system with NCP or SCP up.
    """
    if (ra_deg is None) or (dec_deg is None):
        return None  # Can't calculate without RA/Dec

    if chart_coord_sys == "horiz":
        # Horizontal coordinates (alt/az):
        if location and dt:
            calc_utils.sf_utils.set_location(
                location.lat, location.lon, location.altitude
            )
            # Use -parallactic_angle
            rot_deg = -calc_utils.sf_utils.radec_to_pa(ra_deg, dec_deg, dt)
        else:
            # No position or time/date available. Default to display in equatorial coordinate
            rot_deg = 0.0  # NCP up
    elif chart_coord_sys == "eq_auto":
        # Equatorial coordinates: (North-up/south-up depending on latitude)
        rot_deg = 0.0  # NCP up (default & northern hemisphere)
        if location:
            if location.lat < 0.0:
                rot_deg = 180.0  # SCP up (for southern hemisphere)
    elif chart_coord_sys == "eq_north_up":
        rot_deg = 0.0
    elif chart_coord_sys == "eq_south_up":
        rot_deg = 180.0
    else:
        logger.error(
            f"Unknown chart coordinate system: {chart_coord_sys}. Defaulting to EQ North-up."
        )
        rot_deg = 0.0  # NCP up

    return rot_deg
