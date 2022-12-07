#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module handles plotting starfields
and constelleations
"""
import os
import io
import datetime
import numpy as np
import pandas
import time
from PIL import Image, ImageDraw, ImageFont, ImageChops, ImageOps

from skyfield.api import Star, load, utc, Angle
from skyfield.constants import GM_SUN_Pitjeva_2005_km3_s2 as GM_SUN
from skyfield.data import hipparcos, mpc, stellarium
from skyfield.projections import build_stereographic_projection


class Starfield:
    """
    Plots a starfield at the
    specified RA/DEC + roll
    """

    def __init__(self, mag_limit=7, fov=10.2):
        utctime = datetime.datetime(2023, 1, 1, 2, 0, 0).replace(tzinfo=utc)
        ts = load.timescale()
        self.t = ts.from_datetime(utctime)
        # An ephemeris from the JPL provides Sun and Earth positions.

        eph = load("de421.bsp")
        self.earth = eph["earth"]

        # The Hipparcos mission provides our star catalog.
        root_dir = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))
        hip_path = os.path.join(root_dir, "astro_data", "hip_main.dat")
        with load.open(hip_path) as f:
            self.raw_stars = hipparcos.load_dataframe(f)

        # constellations
        const_path = os.path.join(root_dir, "astro_data", "constellationship.fab")
        with load.open(const_path) as f:
            self.constellations = stellarium.parse_constellations(f)

        self.set_mag_limit(mag_limit)
        # Prefilter here for mag 9, just to make sure we have enough
        # for any plot.  Actual mag limit is enforced at plot time.
        bright_stars = self.raw_stars.magnitude <= 7.5
        self.stars = self.raw_stars[bright_stars]
        self.star_positions = self.earth.at(self.t).observe(
            Star.from_dataframe(self.stars)
        )
        self.set_fov(fov)

        pointer_image_path = os.path.join(root_dir, "markers", "pointer.png")
        self.pointer_image = ImageChops.multiply(
            Image.open(pointer_image_path), Image.new("RGB", (256, 256), (0, 0, 64))
        )

    def set_mag_limit(self, mag_limit):
        self.mag_limit = mag_limit

    def set_fov(self, fov):
        self.fov = fov

    def plot_markers(self, ra, dec, roll, marker_list):
        """
        Returns an image to add to another image
        Marker list should be a list of
        (RA_Hours/DEC_degrees, symbol) tuples
        """
        sky_pos = Star(
            ra=Angle(degrees=ra),
            dec_degrees=dec,
        )
        center = self.earth.at(self.t).observe(sky_pos)
        projection = build_stereographic_projection(center)

        markers = pandas.DataFrame(
            marker_list, columns=["ra_hours", "dec_degrees", "symbol"]
        )

        # required, use the same epoch as stars
        markers["epoch_year"] = 1991.25
        marker_positions = self.earth.at(self.t).observe(Star.from_dataframe(markers))

        markers["x"], markers["y"] = projection(marker_positions)

        target_size = 128
        angle = np.pi - (self.fov) / 360.0 * np.pi
        limit = np.sin(angle) / (1.0 - np.cos(angle))
        ret_image = Image.new("RGB", (target_size * 2, target_size * 2))
        idraw = ImageDraw.Draw(ret_image)

        image_scale = int(target_size / limit)
        pixel_scale = image_scale / 2

        markers_x = list(markers["x"])
        markers_y = list(markers["y"])
        markers_symbol = list(markers["symbol"])

        ret_list = []
        for i, x in enumerate(markers_x):
            x_pos = x * pixel_scale + target_size
            y_pos = markers_y[i] * -1 * pixel_scale + target_size
            symbol = markers_symbol[i]

            if symbol == "target":
                idraw.line(
                    [x_pos, y_pos - 5, x_pos, y_pos + 5],
                    fill=(0, 0, 255),
                )
                idraw.line(
                    [x_pos - 5, y_pos, x_pos + 5, y_pos],
                    fill=(0, 0, 255),
                )

                # Draw pointer....
                # if not within screen
                if x_pos > 180 or x_pos < 76 or y_pos > 180 or y_pos < 76:
                    # calc degrees to target....
                    deg_to_target = (
                        np.rad2deg(np.arctan2(y_pos - 128, x_pos - 128)) + 180
                    )
                    tmp_pointer = self.pointer_image.copy()
                    tmp_pointer = tmp_pointer.rotate(-deg_to_target)
                    ret_image = ImageChops.add(ret_image, tmp_pointer)

        return ret_image.rotate(roll).crop([64, 64, 192, 192])

    def plot_starfield(self, ra, dec, roll, const_lines=True):
        """
        Returns an image of the starfield at the
        provided RA/DEC/ROLL with or without
        constellation lines
        """
        sky_pos = Star(
            ra=Angle(degrees=ra),
            dec_degrees=dec,
        )
        center = self.earth.at(self.t).observe(sky_pos)
        projection = build_stereographic_projection(center)

        # Time to build the figure!
        stars = self.stars.copy()

        stars["x"], stars["y"] = projection(self.star_positions)
        pil_image = self.render_starfield_pil(stars, const_lines)
        return pil_image.rotate(roll).crop([64, 64, 192, 192])

    def render_starfield_pil(self, stars, const_lines):
        start_time = time.time()
        target_size = 128
        angle = np.pi - (self.fov) / 360.0 * np.pi
        limit = np.sin(angle) / (1.0 - np.cos(angle))

        image_scale = int(target_size / limit)

        ret_image = Image.new("RGB", (target_size * 2, target_size * 2))
        idraw = ImageDraw.Draw(ret_image)

        pixel_scale = image_scale / 2

        # constellation lines first
        if const_lines:
            edges = [edge for name, edges in self.constellations for edge in edges]
            edges_star1 = [star1 for star1, star2 in edges]
            edges_star2 = [star2 for star1, star2 in edges]

            # edges in plot space
            xy1 = stars[["x", "y"]].loc[edges_star1].values
            xy2 = stars[["x", "y"]].loc[edges_star2].values

            for i, start_pos in enumerate(xy1):
                end_pos = xy2[i]
                start_x = start_pos[0] * pixel_scale + target_size
                start_y = start_pos[1] * -1 * pixel_scale + target_size
                end_x = end_pos[0] * pixel_scale + target_size
                end_y = end_pos[1] * -1 * pixel_scale + target_size
                idraw.line([start_x, start_y, end_x, end_y], fill=(32, 32, 64))

        stars_x = list(stars["x"])
        stars_y = list(stars["y"])
        stars_mag = list(stars["magnitude"])

        for i, x in enumerate(stars_x):
            x_pos = x * pixel_scale + target_size
            y_pos = stars_y[i] * -1 * pixel_scale + target_size
            if x_pos > 0 and x_pos < target_size * 2 and  y_pos > 0 and y_pos < target_size *2:
            #if True:
                mag = stars_mag[i]
                if mag < self.mag_limit:
                    plot_size = (self.mag_limit - mag) / 3
                    fill = (255, 255, 255)
                    if mag > 4.5:
                        fill = (128, 128, 128)
                    if plot_size < 0.5:
                        idraw.point((x_pos, y_pos), fill=fill)
                    else:
                        idraw.ellipse(
                            [
                                x_pos - plot_size,
                                y_pos - plot_size,
                                x_pos + plot_size,
                                y_pos + plot_size,
                            ],
                            fill=(255, 255, 255),
                        )
        print("plot time" + str(time.time() - start_time))
        return ret_image
