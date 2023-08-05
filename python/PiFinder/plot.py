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
from pathlib import Path
from PiFinder import utils
from PIL import Image, ImageDraw, ImageFont, ImageChops, ImageOps

from skyfield.api import Star, load, utc, Angle
from skyfield.constants import GM_SUN_Pitjeva_2005_km3_s2 as GM_SUN
from skyfield.data import hipparcos, mpc, stellarium
from skyfield.projections import build_stereographic_projection
from PiFinder.integrator import sf_utils


class Starfield:
    """
    Plots a starfield at the
    specified RA/DEC + roll
    """

    def __init__(self, colors, mag_limit=7, fov=10.2):
        self.colors = colors
        utctime = datetime.datetime(2023, 1, 1, 2, 0, 0).replace(tzinfo=utc)
        ts = sf_utils.ts
        self.t = ts.from_datetime(utctime)
        # An ephemeris from the JPL provides Sun and Earth positions.

        self.earth = sf_utils.earth

        # The Hipparcos mission provides our star catalog.
        hip_path = Path(utils.astro_data_dir, "hip_main.dat")
        with load.open(str(hip_path)) as f:
            self.raw_stars = hipparcos.load_dataframe(f)

        # constellations
        const_path = Path(utils.astro_data_dir, "constellationship.fab")
        with load.open(str(const_path)) as f:
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

        marker_path = Path(utils.pifinder_dir, "markers")
        pointer_image_path = Path(marker_path, "pointer.png")
        self.pointer_image = ImageChops.multiply(
            Image.open(str(pointer_image_path)),
            Image.new("RGB", (256, 256), colors.get(64)),
        )
        # load markers...
        self.markers = {}
        for filename in os.listdir(marker_path):
            if filename.startswith("mrk_"):
                marker_code = filename[4:-4]
                _image = Image.new("RGB", (256, 256))
                _image.paste(
                    Image.open(f"{marker_path}/mrk_{marker_code}.png"), (117, 117)
                )
                self.markers[marker_code] = ImageChops.multiply(
                    _image, Image.new("RGB", (256, 256), colors.get(256))
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
                    fill=self.colors.get(255),
                )
                idraw.line(
                    [x_pos - 5, y_pos, x_pos + 5, y_pos],
                    fill=self.colors.get(255),
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
            else:
                # if it's visible, plot it.
                if x_pos < 200 and x_pos > 60 and y_pos < 180 and y_pos > 60:
                    _image = ImageChops.offset(
                        self.markers[symbol], int(x_pos - 123), int(y_pos - 123)
                    )
                    ret_image = ImageChops.add(ret_image, _image)

        return ret_image.rotate(roll).crop([64, 64, 192, 192])

    def plot_starfield(self, ra, dec, roll, constellation_brightness=32):
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
        pil_image = self.render_starfield_pil(stars, constellation_brightness)
        return pil_image.rotate(roll).crop([64, 64, 192, 192])

    def render_starfield_pil(self, stars, constellation_brightness):
        target_size = 128
        angle = np.pi - (self.fov) / 360.0 * np.pi
        limit = np.sin(angle) / (1.0 - np.cos(angle))

        image_scale = int(target_size / limit)

        ret_image = Image.new("L", (target_size * 2, target_size * 2))
        idraw = ImageDraw.Draw(ret_image)

        pixel_scale = image_scale / 2

        # constellation lines first
        if constellation_brightness:
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
                idraw.line(
                    [start_x, start_y, end_x, end_y], fill=(constellation_brightness)
                )

        for x, y, mag in zip(stars["x"], stars["y"], stars["magnitude"]):
            x_pos = x * pixel_scale + target_size
            y_pos = y * -1 * pixel_scale + target_size
            if (
                x_pos > 0
                and x_pos < target_size * 2
                and y_pos > 0
                and y_pos < target_size * 2
            ):
                # if True:
                if mag < self.mag_limit:
                    plot_size = (self.mag_limit - mag) / 3
                    fill = 255
                    if mag > 4.5:
                        fill = 128
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
                            fill=(255),
                        )
        return ret_image
