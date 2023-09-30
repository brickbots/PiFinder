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
import polars as pl
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
        self.earth = sf_utils.earth.at(self.t)

        # The Hipparcos mission provides our star catalog.
        hip_path = Path(utils.astro_data_dir, "hip_main.dat")
        with load.open(str(hip_path)) as f:
            self.raw_stars = pl.DataFrame(hipparcos.load_dataframe(f))

        # Image size stuff
        self.target_size = 128
        self.diag_mult = 1.422
        self.render_size = (
            int(self.target_size * self.diag_mult),
            int(self.target_size * self.diag_mult),
        )
        self.render_center = (
            int(self.render_size[0] / 2),
            int(self.render_size[1] / 2),
        )
        self.render_crop = [
            int((self.render_size[0] - self.target_size) / 2),
            int((self.render_size[1] - self.target_size) / 2),
            int((self.render_size[0] - self.target_size) / 2) + self.target_size,
            int((self.render_size[1] - self.target_size) / 2) + self.target_size,
        ]

        self.set_mag_limit(mag_limit)
        self.stars = self.raw_stars
        # Prefilter here for mag 7.5, just to make sure we have enough
        # for any plot.  Actual mag limit is enforced at plot time.
        # self.stars = self.raw_stars.filter(pl.col("magnitude") <= 7.5)
        self.stars = self.stars.with_row_count("index")
        print(self.stars.describe())
        maxstars = self.stars.select(pl.max("index"))[0]
        print(maxstars)

        self.set_fov(fov)

        # constellations data ===========================
        const_path = Path(utils.astro_data_dir, "constellationship.fab")
        with load.open(str(const_path)) as f:
            self.constellations = stellarium.parse_constellations(f)
        print("constellations", self.constellations)
        edges = [edge for name, edges in self.constellations for edge in edges]
        const_start_stars = pl.DataFrame([star1 for star1, star2 in edges]).filter(
            pl.col("column_0") <= maxstars
        )["column_0"]
        const_end_stars = pl.DataFrame([star2 for star1, star2 in edges]).filter(
            pl.col("column_0") <= maxstars
        )["column_0"]
        assert len(const_start_stars) == len(const_end_stars)
        print(
            f"min/max of constellation indexes is {min(const_start_stars)=} {max(const_start_stars)=}, {min(const_end_stars)=} {max(const_end_stars)=}"
        )

        print(
            f"const_start_stars {len(const_start_stars)} const_end_stars {len(const_end_stars)}"
        )
        # Start the main dataframe to hold edge info (start + end stars)
        print(f"length of self.stars {len(self.stars)}")
        self.const_edges_df = self.stars.filter(
            pl.col("index").is_in(const_start_stars)
        )
        print("is not in", self.stars.filter(~pl.col("index").is_in(const_start_stars)))
        print(f"length of self.stars {len(self.stars)}")
        self.const_edges_end_df = self.stars.filter(
            pl.col("index").is_in(const_end_stars)
        )
        print(
            "self.const_edges_df ",
            self.const_edges_df,
            "const_edges_end_df",
            self.const_edges_end_df,
        )

        # We need position lists for both start/end of constellation lines
        self.const_start_star_positions = self.earth.observe(
            Star.from_dataframe(self.const_edges_df.to_pandas())
        )
        self.const_end_star_positions = self.earth.observe(
            Star.from_dataframe(self.const_edges_end_df.to_pandas())
        )
        self.star_positions = self.earth.observe(
            Star.from_dataframe(self.stars.to_pandas())
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

        self.image_scale = int(self.target_size / limit)
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

    def plot_markers(self, marker_list):
        """
        Returns an image to add to another image
        Marker list should be a list of
        (RA_Hours/DEC_degrees, symbol) tuples
        """
        ret_image = Image.new("RGB", self.render_size)
        idraw = ImageDraw.Draw(ret_image)

        markers = pl.DataFrame(
            marker_list,
            schema={
                "ra_hours": pl.Float64,
                "dec_degrees": pl.Float64,
                "symbol": pl.Utf8,
            },
        )

        # required, use the same epoch as stars
        markers["epoch_year"] = 1991.25
        marker_positions = self.earth.observe(Star.from_dataframe(markers.to_pandas()))

        markers["x"], markers["y"] = self.projection(marker_positions)

        # Rasterize marker positions
        markers = markers.assign(
            x_pos=markers["x"] * self.pixel_scale + self.render_center[0],
            y_pos=markers["y"] * -1 * self.pixel_scale + self.render_center[1],
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
                    x_pos > self.render_crop[2]
                    or x_pos < self.render_crop[0]
                    or y_pos > self.render_crop[3]
                    or y_pos < self.render_crop[1]
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

        return ret_image.rotate(self.roll).crop(self.render_crop)

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
        x_array, y_array = self.projection(self.star_positions)
        self.stars = self.stars.with_columns(pl.Series("x", x_array))
        self.stars = self.stars.with_columns(pl.Series("y", y_array))

        print("self.const_edges_df", self.const_edges_df)
        # For start star positions
        sx_array, sy_array = self.projection(self.const_start_star_positions)
        print(f"len(sx_array) {len(sx_array)}, len(sy_array) {len(sy_array)}")
        print(f"{self.const_start_star_positions=}")
        self.const_edges_df = self.const_edges_df.with_columns(
            pl.Series("sx", sx_array)
        )
        self.const_edges_df = self.const_edges_df.with_columns(
            pl.Series("sy", sy_array)
        )

        print("self.const_edges_df", self.const_edges_df)
        # For end star positions
        ex_array, ey_array = self.projection(self.const_end_star_positions)
        print(f"{self.const_end_star_positions=}")
        print(f"len(ex_array) {len(ex_array)}, len(ey_array) {len(ey_array)}")
        self.const_edges_df = self.const_edges_df.with_columns(
            pl.Series("ex", ex_array[: len(sx_array)])
        )
        self.const_edges_df = self.const_edges_df.with_columns(
            pl.Series("ey", ey_array[: len(sy_array)])
        )

        pil_image = self.render_starfield_pil(constellation_brightness)
        return pil_image.rotate(self.roll).crop(self.render_crop)

    def render_starfield_pil(self, constellation_brightness):
        ret_image = Image.new("L", self.render_size)
        idraw = ImageDraw.Draw(ret_image)

        # constellation lines first
        if constellation_brightness:
            # convert projection positions to screen space
            # using pandas to interate
            const_edges = (
                self.const_edges_df.lazy()
                .with_columns(
                    pl.Series(
                        "sx_pos",
                        self.const_edges_df["sx"] * self.pixel_scale
                        + self.render_center[0],
                    )
                )
                .with_columns(
                    pl.Series(
                        "sy_pos",
                        self.const_edges_df["sy"] * -1 * self.pixel_scale
                        + self.render_center[1],
                    )
                )
                .with_columns(
                    pl.Series(
                        "ex_pos",
                        self.const_edges_df["ex"] * self.pixel_scale
                        + self.render_center[0],
                    )
                )
                .with_columns(
                    pl.Series(
                        "ey_pos",
                        self.const_edges_df["ey"] * -1 * self.pixel_scale
                        + self.render_center[1],
                    )
                )
            )

            # Now that all the star/end points are in screen space
            # remove any where both the start/end are not on screen
            # filter for visibility
            visible_edges = const_edges.filter(
                (
                    (pl.col("sx_pos") > 0)
                    & (pl.col("sx_pos") < self.render_size[0])
                    & (pl.col("sy_pos") > 0)
                    & (pl.col("sy_pos") < self.render_size[1])
                )
                | (
                    (pl.col("ex_pos") > 0)
                    & (pl.col("ex_pos") < self.render_size[0])
                    & (pl.col("ey_pos") > 0)
                    & (pl.col("ey_pos") < self.render_size[1])
                )
            ).collect()

            print("visible_edges", visible_edges)
            # This seems strange, but is one of the generally recommended
            # way to iterate through pandas frames.
            for row in visible_edges.rows():
                print(row)
                start_x = row[13]
                start_y = row[14]
                end_x = row[15]
                end_y = row[16]
                idraw.line(
                    [start_x, start_y, end_x, end_y],
                    fill=(constellation_brightness),
                )

        # filter stars by magnitude
        visible_stars = self.stars.filter(pl.col("magnitude") < self.mag_limit)

        # convert star positions to screen space
        visible_stars = visible_stars.with_columns(
            [
                (pl.col("x") * self.pixel_scale + self.render_center[0]).alias("x_pos"),
                (pl.col("y") * -1 * self.pixel_scale + self.render_center[1]).alias(
                    "y_pos"
                ),
            ]
        )

        # now filter by visibility on screen
        visible_stars = visible_stars.filter(
            (pl.col("x_pos") > 0)
            & (pl.col("x_pos") < self.render_size[0])
            & (pl.col("y_pos") > 0)
            & (pl.col("y_pos") < self.render_size[1])
        )

        # Collect the data and iterate through rows
        x_pos, y_pos, mag = visible_stars.select(["x_pos", "y_pos", "magnitude"])

        for x, y, m in zip(x_pos, y_pos, mag):
            plot_size = (self.mag_limit - m) / 3
            fill = 255 if m <= 4.5 else 128

            if plot_size < 0.5:
                idraw.point((x, y), fill=fill)
            else:
                idraw.ellipse(
                    [x - plot_size, y - plot_size, x + plot_size, y + plot_size],
                    fill=255,
                )

        return ret_image
