#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module handles plotting starfields
and constelleations
"""

import os
import datetime
import numpy as np
import pandas
from pathlib import Path
from PiFinder import utils
from PIL import Image, ImageDraw, ImageChops

from skyfield.api import Star, load, utc, Angle
from skyfield.data import hipparcos, stellarium
from skyfield.projections import build_stereographic_projection
from PiFinder.calc_utils import sf_utils


class Starfield:
    """
    Plots a starfield at the
    specified RA/DEC + roll
    """

    def __init__(self, colors, resolution, mag_limit=7, fov=10.2):
        self.colors = colors
        self.resolution = resolution
        utctime = datetime.datetime(2023, 1, 1, 2, 0, 0).replace(tzinfo=utc)
        ts = sf_utils.ts
        self.t = ts.from_datetime(utctime)
        # An ephemeris from the JPL provides Sun and Earth positions.

        self.earth = sf_utils.earth.at(self.t)

        # The Hipparcos mission provides our star catalog.
        hip_path = Path(utils.astro_data_dir, "hip_main.dat")
        with load.open(str(hip_path)) as f:
            self.raw_stars = hipparcos.load_dataframe(f)

        # Image size stuff
        self.render_size = resolution
        self.render_center = (
            int(self.render_size[0] / 2),
            int(self.render_size[1] / 2),
        )

        self.set_mag_limit(mag_limit)
        # Prefilter here for mag 7.5, just to make sure we have enough
        # for any plot.  Actual mag limit is enforced at plot time.
        bright_stars = self.raw_stars.magnitude <= 7.5
        self.stars = self.raw_stars[bright_stars].copy()

        self.star_positions = self.earth.observe(Star.from_dataframe(self.stars))
        self.set_fov(fov)

        # constellations data ===========================
        const_path = Path(utils.astro_data_dir, "constellationship.fab")
        with load.open(str(const_path)) as f:
            self.constellations = stellarium.parse_constellations(f)
        edges = [edge for name, edges in self.constellations for edge in edges]
        const_start_stars = [star1 for star1, star2 in edges]
        const_end_stars = [star2 for star1, star2 in edges]

        # Start the main dataframe to hold edge info (start + end stars)
        self.const_edges_df = self.stars.loc[const_start_stars]

        # We need position lists for both start/end of constellation lines
        self.const_start_star_positions = self.earth.observe(
            Star.from_dataframe(self.const_edges_df)
        )
        self.const_end_star_positions = self.earth.observe(
            Star.from_dataframe(self.stars.loc[const_end_stars])
        )

        marker_path = Path(utils.pifinder_dir, "markers")
        pointer_image_path = Path(marker_path, "pointer.png")
        _pointer_image = Image.open(str(pointer_image_path)).crop(
            [
                int((256 - self.render_size[0]) / 2),
                int((256 - self.render_size[1]) / 2),
                int((256 - self.render_size[0]) / 2) + self.render_size[0],
                int((256 - self.render_size[1]) / 2) + self.render_size[1],
            ]
        )
        self.pointer_image = ImageChops.multiply(
            _pointer_image,
            Image.new("RGB", self.render_size, colors.get(64)),
        )
        # load markers...
        self.markers = {}
        for filename in os.listdir(marker_path):
            if filename.startswith("mrk_"):
                marker_code = filename[4:-4]
                _image = Image.new("RGB", self.render_size)
                _image.paste(
                    Image.open(f"{marker_path}/mrk_{marker_code}.png"),
                    (self.render_center[0] - 11, self.render_center[1] - 11),
                )
                self.markers[marker_code] = ImageChops.multiply(
                    _image, Image.new("RGB", self.render_size, colors.get(256))
                )

    def set_mag_limit(self, mag_limit):
        self.mag_limit = mag_limit

    def set_fov(self, fov):
        self.fov = fov
        angle = np.pi - (self.fov) / 360.0 * np.pi
        limit = np.sin(angle) / (1.0 - np.cos(angle))

        # Used for vis culling in projection space
        self.limit = limit

        self.image_scale = int(self.render_size[0] / limit)
        self.pixel_scale = self.image_scale / 2

        # figure out magnitude limit for fov
        mag_range = (7.5, 5)
        fov_range = (5, 40)
        perc_fov = (fov - fov_range[0]) / (fov_range[1] - fov_range[0])
        if perc_fov > 1:
            perc_fov = 1
        if perc_fov < 0:
            perc_fov = 0

        mag_setting = mag_range[0] - ((mag_range[0] - mag_range[1]) * perc_fov)
        self.set_mag_limit(mag_setting)

    def radec_to_xy(self, ra: float, dec: float) -> tuple[float, float]:
        """
        Converts and RA/DEC to screen space x/y for the current projection
        """
        markers = pandas.DataFrame(
            [(Angle(degrees=ra)._hours, dec)], columns=["ra_hours", "dec_degrees"]
        )

        # required, use the same epoch as stars
        markers["epoch_year"] = 1991.25
        marker_positions = self.earth.observe(Star.from_dataframe(markers))

        markers["x"], markers["y"] = self.projection(marker_positions)

        # prep rotate by roll....
        roll_rad = (self.roll) * (np.pi / 180)
        roll_sin = np.sin(roll_rad)
        roll_cos = np.cos(roll_rad)

        # Rotate them
        markers = markers.assign(
            xr=((markers["x"]) * roll_cos - (markers["y"]) * roll_sin),
            yr=((markers["y"]) * roll_cos + (markers["x"]) * roll_sin),
        )

        # Rasterize marker positions
        markers = markers.assign(
            x_pos=markers["xr"] * self.pixel_scale + self.render_center[0],
            y_pos=markers["yr"] * -1 * self.pixel_scale + self.render_center[1],
        )

        return markers["x_pos"][0], markers["y_pos"][0]

    def plot_markers(self, marker_list):
        """
        Returns an image to add to another image
        Marker list should be a list of
        (RA_Hours/DEC_degrees, symbol) tuples
        """
        ret_image = Image.new("RGB", self.render_size)
        idraw = ImageDraw.Draw(ret_image)

        markers = pandas.DataFrame(
            marker_list, columns=["ra_hours", "dec_degrees", "symbol"]
        )

        # required, use the same epoch as stars
        markers["epoch_year"] = 1991.25
        marker_positions = self.earth.observe(Star.from_dataframe(markers))

        markers["x"], markers["y"] = self.projection(marker_positions)

        # prep rotate by roll....
        roll_rad = (self.roll) * (np.pi / 180)
        roll_sin = np.sin(roll_rad)
        roll_cos = np.cos(roll_rad)

        # Rotate them
        markers = markers.assign(
            xr=((markers["x"]) * roll_cos - (markers["y"]) * roll_sin),
            yr=((markers["y"]) * roll_cos + (markers["x"]) * roll_sin),
        )

        # Rasterize marker positions
        markers = markers.assign(
            x_pos=markers["xr"] * self.pixel_scale + self.render_center[0],
            y_pos=markers["yr"] * -1 * self.pixel_scale + self.render_center[1],
        )
        # now filter by visiblity
        markers = markers[
            (
                (markers["x_pos"] > 0)
                & (markers["x_pos"] < self.render_size[0])
                & (markers["y_pos"] > 0)
                & (markers["y_pos"] < self.render_size[1])
            )
            | (markers["symbol"] == "target")
        ]

        for x_pos, y_pos, symbol in zip(
            markers["x_pos"], markers["y_pos"], markers["symbol"]
        ):
            if symbol == "target":
                # Draw cross
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
                if (
                    x_pos > 0
                    or x_pos < self.render_size[0]
                    or y_pos > 0
                    or y_pos < self.render_size[1]
                ):
                    # calc degrees to target....
                    deg_to_target = (
                        np.rad2deg(
                            np.arctan2(
                                y_pos - self.render_center[1],
                                x_pos - self.render_center[0],
                            )
                        )
                        + 180
                    )
                    tmp_pointer = self.pointer_image.copy()
                    tmp_pointer = tmp_pointer.rotate(-deg_to_target)
                    ret_image = ImageChops.add(ret_image, tmp_pointer)

            else:
                _image = ImageChops.offset(
                    self.markers[symbol],
                    int(x_pos) - (self.render_center[0] - 5),
                    int(y_pos) - (self.render_center[1] - 5),
                )
                ret_image = ImageChops.add(ret_image, _image)

        return ret_image

    def update_projection(self, ra, dec):
        """
        Updates the shared projection used for various plotting
        routines
        """
        sky_pos = Star(
            ra=Angle(degrees=ra),
            dec_degrees=dec,
        )
        center = self.earth.observe(sky_pos)
        self.projection = build_stereographic_projection(center)

    def plot_starfield(self, ra, dec, roll, constellation_brightness=32):
        """
        Returns an image of the starfield at the
        provided RA/DEC/ROLL with or without
        constellation lines
        """
        self.update_projection(ra, dec)
        self.roll = roll

        # Set star x/y for projection
        # This is in a -1 to 1 space for the entire sky
        # with 0,0 being the provided RA/DEC
        self.stars["x"], self.stars["y"] = self.projection(self.star_positions)

        # set start/end star x/y for const
        self.const_edges_df["sx"], self.const_edges_df["sy"] = self.projection(
            self.const_start_star_positions
        )
        self.const_edges_df["ex"], self.const_edges_df["ey"] = self.projection(
            self.const_end_star_positions
        )

        pil_image, visible_stars = self.render_starfield_pil(constellation_brightness)
        return pil_image, visible_stars

    def render_starfield_pil(self, constellation_brightness):
        """
        If return_plotted_stars this will return a tuple:
        (image, visible_stars)

        Mainly for the new alignment system
        """
        ret_image = Image.new("L", self.render_size)
        idraw = ImageDraw.Draw(ret_image)

        # prep rotate by roll....
        roll_rad = (self.roll) * (np.pi / 180)
        roll_sin = np.sin(roll_rad)
        roll_cos = np.cos(roll_rad)

        # constellation lines first
        if constellation_brightness:
            # convert projection positions to screen space
            # using pandas to interate

            # roll the constellation lines
            self.const_edges_df = self.const_edges_df.assign(
                sxr=(
                    (self.const_edges_df["sx"]) * roll_cos
                    - (self.const_edges_df["sy"]) * roll_sin
                ),
                syr=(
                    (self.const_edges_df["sy"]) * roll_cos
                    + (self.const_edges_df["sx"]) * roll_sin
                ),
                exr=(
                    (self.const_edges_df["ex"]) * roll_cos
                    - (self.const_edges_df["ey"]) * roll_sin
                ),
                eyr=(
                    (self.const_edges_df["ey"]) * roll_cos
                    + (self.const_edges_df["ex"]) * roll_sin
                ),
            )

            const_edges = self.const_edges_df.assign(
                sx_pos=self.const_edges_df["sxr"] * self.pixel_scale
                + self.render_center[0],
                sy_pos=self.const_edges_df["syr"] * -1 * self.pixel_scale
                + self.render_center[1],
                ex_pos=self.const_edges_df["exr"] * self.pixel_scale
                + self.render_center[0],
                ey_pos=self.const_edges_df["eyr"] * -1 * self.pixel_scale
                + self.render_center[1],
            )

            # Now that all the star/end points are in screen space
            # remove any where both the start/end are not on screen
            # filter for visibility
            visible_edges = const_edges[
                (
                    (const_edges["sx_pos"] > 0)
                    & (const_edges["sx_pos"] < self.render_size[0])
                    & (const_edges["sy_pos"] > 0)
                    & (const_edges["sy_pos"] < self.render_size[1])
                )
                | (
                    (const_edges["ex_pos"] > 0)
                    & (const_edges["ex_pos"] < self.render_size[0])
                    & (const_edges["ey_pos"] > 0)
                    & (const_edges["ey_pos"] < self.render_size[1])
                )
            ]

            # This seems strange, but is one of the generally recommended
            # way to iterate through pandas frames.
            for start_x, start_y, end_x, end_y in zip(
                visible_edges["sx_pos"],
                visible_edges["sy_pos"],
                visible_edges["ex_pos"],
                visible_edges["ey_pos"],
            ):
                idraw.line(
                    [start_x, start_y, end_x, end_y],
                    fill=(constellation_brightness),
                )

        # filter stars by magnitude
        visible_stars = self.stars[self.stars["magnitude"] < self.mag_limit]

        # now filter by visiblity on screen in projection space
        visible_stars = visible_stars[
            (visible_stars["x"] > -self.limit)
            & (visible_stars["x"] < self.limit)
            & (visible_stars["y"] > -self.limit)
            & (visible_stars["y"] < self.limit)
        ]

        # Rotate them
        visible_stars = visible_stars.assign(
            xr=((visible_stars["x"]) * roll_cos - (visible_stars["y"]) * roll_sin),
            yr=((visible_stars["y"]) * roll_cos + (visible_stars["x"]) * roll_sin),
        )

        # convert star positions to screen space
        visible_stars = visible_stars.assign(
            x_pos=visible_stars["xr"] * self.pixel_scale + self.render_center[0],
            y_pos=visible_stars["yr"] * -1 * self.pixel_scale + self.render_center[1],
        )

        for x_pos, y_pos, mag in zip(
            visible_stars["x_pos"], visible_stars["y_pos"], visible_stars["magnitude"]
        ):
            # This could be moved to a pandas assign after filtering
            # for vis for a small boost
            plot_size = (self.mag_limit - mag) / 3
            fill = 255
            if mag > 4.5:
                fill = 128
            if plot_size < 0.5:
                idraw.point((x_pos, y_pos), fill=fill)
            else:
                idraw.circle(
                    (round(x_pos), round(y_pos)),
                    radius=plot_size,
                    fill=(255),
                    width=0,
                )

        return ret_image, visible_stars
