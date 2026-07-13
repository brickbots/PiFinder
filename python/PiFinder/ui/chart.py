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
import math
import time
from dataclasses import dataclass
from PIL import ImageChops, Image

from PiFinder.ui.marking_menus import MarkingMenuOption, MarkingMenu
from PiFinder.obj_types import OBJ_TYPE_MARKERS
from PiFinder import plot
from PiFinder.ui.base import UIModule
from PiFinder import calc_utils


logger = logging.getLogger("Chart")

# Smallest on-screen span (px) worth outlining. Below this the object's marker
# glyph carries the position and an outline would just be a blob.
_MIN_OUTLINE_PX = 4


def _angular_sep_deg(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    """Great-circle separation between two RA/Dec points, all in degrees."""
    d1 = math.radians(dec1)
    d2 = math.radians(dec2)
    dra = math.radians(ra2 - ra1)
    cos_sep = math.sin(d1) * math.sin(d2) + math.cos(d1) * math.cos(d2) * math.cos(dra)
    return math.degrees(math.acos(max(-1.0, min(1.0, cos_sep))))


def size_perimeter_radec(
    ra0: float,
    dec0: float,
    extents: list,
    position_angle: float,
    steps: int = 48,
) -> list:
    """Build a closed RA/Dec perimeter for a numeric-extent size.

    ``extents`` are angular sizes in arcseconds (as stored by ``SizeObject``):

    * ``[d]``            -> circle of diameter ``d``
    * ``[major, minor]`` -> ellipse, ``position_angle`` measured N through E
    * ``[r1, r2, ...]``  -> polygon of radial distances at equal angular steps

    Returns ``[[ra, dec], ...]`` in degrees, first point repeated at the end so
    the caller can draw a closed outline. Empty near the poles where the RA
    scaling blows up.
    """
    if not extents:
        return []
    cos_dec0 = math.cos(math.radians(dec0))
    if abs(cos_dec0) < 1e-6:
        return []

    pa = math.radians(position_angle)
    sin_pa = math.sin(pa)
    cos_pa = math.cos(pa)

    # Local tangent-plane offsets in arcsec: E(ast), N(orth).
    offsets = []
    if len(extents) == 1:
        r = extents[0] / 2.0
        for i in range(steps):
            t = 2.0 * math.pi * i / steps
            offsets.append((r * math.cos(t), r * math.sin(t)))
    elif len(extents) == 2:
        a = extents[0] / 2.0
        b = extents[1] / 2.0
        for i in range(steps):
            t = 2.0 * math.pi * i / steps
            u = a * math.cos(t)  # along major axis
            v = b * math.sin(t)  # along minor axis
            offsets.append((u * sin_pa + v * cos_pa, u * cos_pa - v * sin_pa))
    else:
        step = 2.0 * math.pi / len(extents)
        for i, ext in enumerate(extents):
            phi = pa + i * step  # position angle of this radial spoke, N through E
            r = ext / 2.0
            offsets.append((r * math.sin(phi), r * math.cos(phi)))

    radec = [[ra0 + (e / 3600.0) / cos_dec0, dec0 + n / 3600.0] for e, n in offsets]
    radec.append(radec[0])
    return radec


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
        outline_objects = []

        # is there a target?
        target = self.ui_state.target()
        if target:
            marker_list.append(
                (plot.Angle(degrees=target.ra)._hours, target.dec, "target")
            )
            outline_objects.append(target)

        marker_brightness = self.config_object.get_option("chart_dso", 128)
        if marker_brightness == 0:
            return

        for obs_target in self.ui_state.observing_list():
            outline_objects.append(obs_target)
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

        line_color = self.colors.get(marker_brightness)
        center = self._chart_center()
        for obj in outline_objects:
            self._draw_object_outline(obj, line_color, center)

    def _chart_center(self):
        """(RA, Dec) the chart is currently centred on, or ``None``."""
        if self.solution and self.solution.has_pointing():
            est = self.solution.pointing.aligned.estimate
            return est.RA, est.Dec
        return None

    def _draw_object_outline(self, obj, line_color, center):
        """Outline an object's true angular extent on the chart.

        Draws polyline/segment shapes as stored, and renders numeric
        circle/ellipse/polygon sizes from their major/minor axes and position
        angle. Objects well outside the field, or too small to resolve into
        more than a glyph, are skipped so the outline never degrades to a blob.
        """
        size = getattr(obj, "size", None)
        if not size or not size.extents:
            return

        # Cheap RA/Dec cull before any projection: skip anything comfortably
        # off the current field of view.
        if center is not None:
            if _angular_sep_deg(obj.ra, obj.dec, center[0], center[1]) > self.fov:
                return

        if size.is_segments:
            for seg in size.extents:
                pts = self.starfield.project_vertices(seg)
                if len(pts) >= 2:
                    self.draw.line(pts, fill=line_color, width=1)
            return

        if size.is_vertices:
            pts = self.starfield.project_vertices(size.extents)
            if len(pts) >= 2:
                self.draw.line(pts, fill=line_color, width=1)
            return

        radec = size_perimeter_radec(obj.ra, obj.dec, size.extents, size.position_angle)
        if not radec:
            return
        pts = self.starfield.project_vertices(radec)
        if len(pts) < 2:
            return
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        if (max(xs) - min(xs)) < _MIN_OUTLINE_PX and (
            max(ys) - min(ys)
        ) < _MIN_OUTLINE_PX:
            return
        self.draw.line(pts, fill=line_color, width=1)

    def _draw_orientation_indicator(self, orientation: "ChartOrientation"):
        """
        Draw a small "up" indicator at the top-left of the chart.

        Communicates which orientation the chart is using (NCP / SCP / Zenith)
        and, when GPS hasn't arrived yet but the user picked a GPS-dependent
        mode, prefixes a "!" so the user knows the orientation will flip
        once GPS comes online.
        """
        # TRANSLATORS: chart corner label, e.g. "Zenith up" — keep short
        text = _("{label} up").format(label=orientation.up_label)
        if orientation.is_fallback:
            text = "!" + text
        font = self.fonts.base
        # Brighter when fallback so the "!" reads as a hint, not noise.
        brightness = 255 if orientation.is_fallback else 128
        x = 2
        # Sit just below the title bar
        y = self.display_class.titlebar_height + 1
        self.draw.text(
            (x, y),
            text,
            font=font.font,
            fill=self.colors.get(brightness),
        )

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
                orientation = get_chart_rotation_angle(
                    aligned.RA,
                    aligned.Dec,
                    chart_coord_sys=self.config_object.get_option("chart_coord_sys"),
                    location=self.shared_state.location(),
                    dt=self.shared_state.datetime(),
                )
                chart_rot_angle = orientation.rot_deg if orientation else None
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
                if orientation is not None:
                    self._draw_orientation_indicator(orientation)

                # Display RA/DEC in selected format if enabled, anchored just
                # above the bottom edge (derived so it tracks resolution).
                radec_y = self.display_class.resY - self.fonts.base.height - 3
                if self.config_object.get_option("chart_radec") == "HH:MM":
                    ra_h, ra_m, ra_s = calc_utils.ra_to_hms(aligned.RA)
                    dec_d, dec_m, dec_s = calc_utils.dec_to_dms(aligned.Dec)
                    ra_dec_disp = f"{ra_h:02d}:{ra_m:02d}:{ra_s:02d} / {dec_d:02d}°{dec_m:02d}:{dec_s}"
                    self.draw.text(
                        (0, radec_y),
                        ra_dec_disp,
                        font=self.fonts.base.font,
                        fill=self.colors.get(255),
                    )
                if self.config_object.get_option("chart_radec") == "Degr":
                    ra_h, ra_m, ra_s = calc_utils.ra_to_hms(aligned.RA)
                    dec_d, dec_m, dec_s = calc_utils.dec_to_dms(aligned.Dec)
                    ra_dec_disp = f"{aligned.RA:0>6.2f} / {aligned.Dec:0>5.2f}"
                    self.draw.text(
                        (0, radec_y),
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


@dataclass
class ChartOrientation:
    """
    Resolved chart rotation plus what's "up" on screen.

    - ``rot_deg`` is the angle to rotate the chart by (the value previously
      returned bare by ``get_chart_rotation_angle``).
    - ``up_label`` is a short string describing what's at the top of the
      chart: ``"NCP"`` / ``"SCP"`` / ``"Zenith"``.
    - ``is_fallback`` is True when the user picked an orientation mode that
      needs GPS (horizontal, or eq-auto in the southern hemisphere) but GPS
      data isn't available yet, so the chart is showing a default NCP-up
      orientation that will change once GPS arrives. The chart UI surfaces
      this so the user isn't startled by the orientation flip.
    """

    rot_deg: float
    up_label: str
    is_fallback: bool


def get_chart_rotation_angle(
    ra_deg: float,  # Right Ascension of the target in degrees
    dec_deg: float,  # Declination of the target in degrees
    chart_coord_sys: str,
    location=None,
    dt: datetime.datetime | None = None,
) -> ChartOrientation | None:
    """
    Returns the rotation and "up" orientation for the chart, depending on
    the configured chart coordinate system. The rotation was previously
    called "roll": the chart is plotted rotated around (RA, Dec); +ve means
    anti-clockwise rotation. The RA and Dec of the target must be provided
    (in degrees); returns ``None`` if either is missing.

    Modes:

    * horiz: Display the chart in horizontal coordinates so up points at
      the Zenith. Needs a GPS location and a datetime; without either,
      falls back to NCP up and flags ``is_fallback=True``.
    * EQ (Auto): Display the chart in equatorial coordinates, NCP-up in
      the northern hemisphere and SCP-up in the southern. Without GPS
      location, defaults to NCP up and flags ``is_fallback=True``.
    * EQ (North-up), EQ (South-up): Display the chart with NCP or SCP up.
      Never a fallback — explicit user choice.
    """
    if (ra_deg is None) or (dec_deg is None):
        return None  # Can't calculate without RA/Dec

    has_gps = bool(location and getattr(location, "lock", False))

    if chart_coord_sys == "horiz":
        if has_gps and dt:
            calc_utils.sf_utils.set_location(
                location.lat, location.lon, location.altitude
            )
            # Use -parallactic_angle
            rot_deg = -calc_utils.sf_utils.radec_to_pa(ra_deg, dec_deg, dt)
            return ChartOrientation(rot_deg, "Zenith", False)
        # No location/time: default to NCP up but flag as a fallback so
        # the UI can show that the orientation will change once GPS arrives.
        return ChartOrientation(0.0, "NCP", True)
    if chart_coord_sys == "eq_auto":
        if has_gps:
            if location.lat < 0.0:
                return ChartOrientation(180.0, "SCP", False)
            return ChartOrientation(0.0, "NCP", False)
        # No location: northern-hemisphere default, but flag as fallback.
        return ChartOrientation(0.0, "NCP", True)
    if chart_coord_sys == "eq_north_up":
        return ChartOrientation(0.0, "NCP", False)
    if chart_coord_sys == "eq_south_up":
        return ChartOrientation(180.0, "SCP", False)

    logger.error(
        f"Unknown chart coordinate system: {chart_coord_sys}. Defaulting to EQ North-up."
    )
    return ChartOrientation(0.0, "NCP", False)
