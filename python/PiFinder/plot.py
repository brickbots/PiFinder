#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module handles plotting starfields
and constelleations
"""
import os
import io
import time
import datetime
import numpy as np
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
        root_dir = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))
        const_path = os.path.join(root_dir, "astro_data", "constellationship.fab")
        with load.open(const_path) as f:
            self.constellations = stellarium.parse_constellations(f)

        self.set_mag_limit(mag_limit)
        self.set_fov(fov)

    def set_mag_limit(self, mag_limit):
        self.mag_limit = mag_limit
        bright_stars = self.raw_stars.magnitude <= mag_limit
        self.stars = self.raw_stars[bright_stars]
        self.star_positions = self.earth.at(self.t).observe(
            Star.from_dataframe(self.stars)
        )

    def set_fov(self, fov):
        self.fov = fov

    def plot_starfield(self, ra, dec, roll, const_lines=True):
        start_time = time.time()

        sky_pos = Star(
            ra=Angle(degrees=ra),
            dec_degrees=dec,
        )
        center = self.earth.at(self.t).observe(sky_pos)
        projection = build_stereographic_projection(center)

        # Time to build the figure!
        stars = self.stars.copy()

        stars["x"], stars["y"] = projection(self.star_positions)
        print(f"Plot prep: {time.time() - start_time}")
        pil_image = self.render_starfield_pil(stars, const_lines)
        return pil_image.rotate(roll).crop([64, 64, 192, 192])

    def render_starfield_pil(self, stars, const_lines):
        target_size = 128
        start_time = time.time()
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
            idraw.line([start_x, start_y, end_x, end_y], fill=(32, 32, 32))

        stars_x = list(stars["x"])
        stars_y = list(stars["y"])
        stars_mag = list(stars["magnitude"])

        for i, x in enumerate(stars_x):
            x_pos = x * pixel_scale + target_size
            y_pos = stars_y[i] * -1 * pixel_scale + target_size
            mag = stars_mag[i]
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

        # ret_image = ret_image.resize((256, 256))
        print(f"Plot plot: {time.time() - start_time}")
        return ret_image
