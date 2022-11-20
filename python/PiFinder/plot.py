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

from matplotlib import pyplot as plt
from skyfield.api import Star, load, utc, Angle
from skyfield.constants import GM_SUN_Pitjeva_2005_km3_s2 as GM_SUN
from skyfield.data import hipparcos, mpc, stellarium
from skyfield.projections import build_stereographic_projection


class Starfield:
    """
    Plots a starfield at the
    specified RA/DEC + roll
    """

    def __init__(self, mag_limit=5, fov=10.2):
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

    def plot_starfield(self, ra, dec, roll):
        start_time = time.time()

        # And the constellation outlines come from Stellarium.  We make a list
        # of the stars at which each edge stars, and the star at which each edge
        # ends.

        """
        url = ('https://raw.githubusercontent.com/Stellarium/stellarium/master'
               '/skycultures/western_SnT/constellationship.fab')

        with load.open(url) as f:
            constellations = stellarium.parse_constellations(f)

        edges = [edge for name, edges in constellations for edge in edges]
        edges_star1 = [star1 for star1, star2 in edges]
        edges_star2 = [star2 for star1, star2 in edges]
        """

        # We will center the chart on the comet's middle position.

        sky_pos = Star(
            ra=Angle(degrees=ra),
            dec_degrees=dec,
        )
        center = self.earth.at(self.t).observe(sky_pos)
        projection = build_stereographic_projection(center)
        field_of_view_degrees = self.fov

        # Now that we have constructed our projection, compute the x and y
        # coordinates that each star and the comet will have on the plot.

        """
        # The constellation lines will each begin at the x,y of one star and end
        # at the x,y of another.  We have to "rollaxis" the resulting coordinate
        # array into the shape that matplotlib expects.

        xy1 = stars[['x', 'y']].loc[edges_star1].values
        xy2 = stars[['x', 'y']].loc[edges_star2].values
        lines_xy = np.rollaxis(np.array([xy1, xy2]), 1)
        """

        # Time to build the figure!

        """
        # Draw the constellation lines.

        ax.add_collection(LineCollection(lines_xy, colors='#00f2'))
        """
        stars = self.stars.copy()

        stars["x"], stars["y"] = projection(self.star_positions)
        print(f"Plot prep: {time.time() - start_time}")
        pil_image = self.render_starfield_mp(stars)
        return pil_image.rotate(roll).crop([64, 64, 192, 192])

    def render_starfield_mp(self, stars):
        start_time = time.time()

        magnitude = stars["magnitude"]
        marker_size = (0.5 + self.mag_limit - magnitude) ** 2.0

        # Time to build the figure!

        fig, ax = plt.subplots(figsize=[9, 9])

        # Draw the stars.

        ax.scatter(stars["x"], stars["y"], s=marker_size, color="k")

        # Finally, title the plot and set some final parameters.
        angle = np.pi - (self.fov * 2) / 360.0 * np.pi
        limit = np.sin(angle) / (1.0 - np.cos(angle))

        ax.set_xlim(-limit, limit)
        ax.set_ylim(-limit, limit)
        ax.xaxis.set_visible(False)
        ax.yaxis.set_visible(False)
        ax.set_aspect(1.0)

        st = time.time()
        """
        canvas = plt.get_current_fig_manager().canvas
        canvas.draw()
        pil_image = Image.frombytes(
                'RGB', canvas.get_width_height(), canvas.tostring_rgb())
        print(time.time() - st)
        return pil_image.resize((256,256)).rotate(roll).crop([64,64,192,192])
        """

        tmp_buff = io.BytesIO()

        fig.savefig(tmp_buff, bbox_inches="tight")
        plt.close()
        pil_image = ImageOps.invert(
            Image.open(tmp_buff).convert("RGB").resize((256, 256))
        )
        print(f"Plot plot: {time.time() - start_time}")
        return pil_image

    def render_starfield_pil(self, stars):
        target_size = 128
        start_time = time.time()
        angle = np.pi - (self.fov) / 360.0 * np.pi
        limit = np.sin(angle) / (1.0 - np.cos(angle))

        #image_size = int((180 / self.fov) * 128)
        image_scale = int(target_size/limit)
        print(image_scale)

        ret_image = Image.new("RGB", (target_size * 2, target_size * 2))
        idraw = ImageDraw.Draw(ret_image)

        pixel_scale = image_scale / 2

        stars_x = list(stars["x"])
        stars_y = list(stars["y"])
        stars_mag = list(stars["magnitude"])

        for i, x in enumerate(stars_x):
            x_pos = x * pixel_scale + target_size
            y_pos = stars_y[i] * -1 * pixel_scale + target_size
            mag = stars_mag[i]
            plot_size = (self.mag_limit - mag)/2
            if plot_size < .5:
                idraw.point((x_pos, y_pos), fill = (255,255,255))
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

        #ret_image = ret_image.resize((256, 256))
        print(f"Plot plot: {time.time() - start_time}")
        return ret_image
