#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module handles plotting starfields
and constelleations
"""

import logging
import os
import numpy as np
import pandas
from pathlib import Path
from PiFinder import utils
from PiFinder import timez
from PIL import Image, ImageDraw, ImageChops

from skyfield.api import Star, load, Angle
from skyfield.data import hipparcos, stellarium
from skyfield.projections import build_stereographic_projection
from PiFinder.calc_utils import sf_utils


logger = logging.getLogger("Plot")

_RAW_STARS_DF = None


def _load_raw_stars():
    """
    Lazy-load the Hipparcos catalogue, cached in-process and on disk.

    The fixed-width parse of hip_main.dat takes ~1.4s on a Pi; reading
    the pickled DataFrame instead takes ~10ms. The on-disk cache lives at
    ~/PiFinder_data/cache/hip_main.pkl and is rebuilt when hip_main.dat
    is newer or when the pickle fails to load (e.g. pandas version skew).
    """
    global _RAW_STARS_DF
    if _RAW_STARS_DF is not None:
        return _RAW_STARS_DF

    dat_path = Path(utils.astro_data_dir, "hip_main.dat")
    cache_dir = Path(utils.data_dir, "cache")
    pkl_path = cache_dir / "hip_main.pkl"

    if pkl_path.exists() and pkl_path.stat().st_mtime >= dat_path.stat().st_mtime:
        try:
            _RAW_STARS_DF = pandas.read_pickle(pkl_path)
            logger.info("Loaded Hipparcos catalog from cache: %s", pkl_path)
            return _RAW_STARS_DF
        except Exception as e:
            logger.warning("Hipparcos cache unreadable, reparsing %s: %s", dat_path, e)

    logger.info("Parsing Hipparcos catalog from %s", dat_path)
    with load.open(str(dat_path)) as f:
        _RAW_STARS_DF = hipparcos.load_dataframe(f)

    utils.create_path(cache_dir)
    try:
        _RAW_STARS_DF.to_pickle(pkl_path)
        logger.info("Wrote Hipparcos cache: %s", pkl_path)
    except OSError as e:
        logger.warning("Failed to write Hipparcos cache %s: %s", pkl_path, e)
    return _RAW_STARS_DF


class Starfield:
    """
    Plots a starfield at the
    specified RA/DEC + roll
    """

    def __init__(self, colors, resolution, mag_limit=7, fov=10.2):
        self.colors = colors
        self.resolution = resolution
        utctime = timez.utc(2023, 1, 1, 2, 0, 0)
        ts = sf_utils.ts
        self.t = ts.from_datetime(utctime)
        # An ephemeris from the JPL provides Sun and Earth positions.

        self.earth = sf_utils.earth.at(self.t)

        # The Hipparcos mission provides our star catalog.
        self.raw_stars = _load_raw_stars()

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

        # Per-frame projection math runs on numpy arrays (much cheaper than
        # the equivalent pandas .assign() chain). Cache the catalog's
        # magnitude column once; the projected x/y arrays are refreshed in
        # plot_starfield().
        self._star_magnitudes = self.stars["magnitude"].to_numpy(dtype=np.float64)
        self._stars_x = None
        self._stars_y = None

        self.star_positions = self.earth.observe(Star.from_dataframe(self.stars))
        self.set_fov(fov)

        # constellations data ===========================
        const_path = Path(utils.astro_data_dir, "constellationship.fab")
        with load.open(str(const_path)) as f:
            self.constellations = stellarium.parse_constellations(f)
        edges = [edge for name, edges in self.constellations for edge in edges]
        const_start_stars = [star1 for star1, star2 in edges]
        const_end_stars = [star2 for star1, star2 in edges]

        # Constellation start/end positions are projected per-frame; their
        # x/y arrays live as instance attributes (initialised lazily).
        self._const_sx = None
        self._const_sy = None
        self._const_ex = None
        self._const_ey = None

        # We need position lists for both start/end of constellation lines
        self.const_start_star_positions = self.earth.observe(
            Star.from_dataframe(self.stars.loc[const_start_stars])
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
        # Skyfield needs a DataFrame to build the Star; rotate/screen-space
        # math is scalar numpy/python after that point.
        marker_df = pandas.DataFrame(
            {
                "ra_hours": [Angle(degrees=ra)._hours],
                "dec_degrees": [dec],
                "epoch_year": 1991.25,
            }
        )
        marker_position = self.earth.observe(Star.from_dataframe(marker_df))
        x_arr, y_arr = self.projection(marker_position)
        x = float(x_arr[0])
        y = float(y_arr[0])

        roll_rad = self.roll * (np.pi / 180.0)
        roll_sin = np.sin(roll_rad)
        roll_cos = np.cos(roll_rad)
        xr = x * roll_cos - y * roll_sin
        yr = y * roll_cos + x * roll_sin

        x_pos = xr * self.pixel_scale + self.render_center[0]
        y_pos = -yr * self.pixel_scale + self.render_center[1]
        return x_pos, y_pos

    def plot_markers(self, marker_list):
        """
        Returns an image to add to another image
        Marker list should be a list of
        (RA_Hours/DEC_degrees, symbol) tuples
        """
        ret_image = Image.new("RGB", self.render_size)
        idraw = ImageDraw.Draw(ret_image)

        if not marker_list:
            return ret_image

        # Skyfield needs a DataFrame to build Star objects. Build the
        # smallest one possible and drop pandas after that point; the per-
        # frame rotate/screen-space/visibility work below runs in numpy.
        ra_hours = np.fromiter(
            (m[0] for m in marker_list), dtype=np.float64, count=len(marker_list)
        )
        dec_degrees = np.fromiter(
            (m[1] for m in marker_list), dtype=np.float64, count=len(marker_list)
        )
        symbols = [m[2] for m in marker_list]
        markers_df = pandas.DataFrame(
            {
                "ra_hours": ra_hours,
                "dec_degrees": dec_degrees,
                "epoch_year": 1991.25,
            }
        )
        marker_positions = self.earth.observe(Star.from_dataframe(markers_df))
        x, y = self.projection(marker_positions)

        # Roll rotation in numpy.
        roll_rad = self.roll * (np.pi / 180.0)
        roll_sin = np.sin(roll_rad)
        roll_cos = np.cos(roll_rad)
        xr = x * roll_cos - y * roll_sin
        yr = y * roll_cos + x * roll_sin

        # Convert to screen-space pixel coordinates.
        x_pos = xr * self.pixel_scale + self.render_center[0]
        y_pos = -yr * self.pixel_scale + self.render_center[1]

        # Visibility: keep on-screen markers; always keep "target" markers
        # since they may need their off-screen pointer drawn.
        on_screen = (
            (x_pos > 0)
            & (x_pos < self.render_size[0])
            & (y_pos > 0)
            & (y_pos < self.render_size[1])
        )
        is_target = np.array([s == "target" for s in symbols], dtype=bool)
        visible = on_screen | is_target

        cx, cy = self.render_center
        for i in np.flatnonzero(visible):
            symbol = symbols[i]
            xp = float(x_pos[i])
            yp = float(y_pos[i])

            if symbol == "target":
                # Draw cross
                idraw.line(
                    [xp, yp - 5, xp, yp + 5],
                    fill=self.colors.get(255),
                )
                idraw.line(
                    [xp - 5, yp, xp + 5, yp],
                    fill=self.colors.get(255),
                )

                # Draw pointer.
                # Note: the original condition below is tautological for any
                # finite xp/yp (any reasonable coord is > 0 OR < W); preserved
                # verbatim to keep behaviour identical for this refactor.
                if (
                    xp > 0
                    or xp < self.render_size[0]
                    or yp > 0
                    or yp < self.render_size[1]
                ):
                    deg_to_target = np.rad2deg(np.arctan2(yp - cy, xp - cx)) + 180
                    tmp_pointer = self.pointer_image.copy()
                    tmp_pointer = tmp_pointer.rotate(-deg_to_target)
                    ret_image = ImageChops.add(ret_image, tmp_pointer)
            else:
                _image = ImageChops.offset(
                    self.markers[symbol],
                    int(xp) - (cx - 5),
                    int(yp) - (cy - 5),
                )
                ret_image = ImageChops.add(ret_image, _image)

        return ret_image

    def project_vertices(self, vertices):
        """Project RA/Dec vertex pairs to screen pixel coords.

        vertices: list of [ra_deg, dec_deg] pairs.
        Returns list of (x, y) screen tuples.
        """
        rows = [(Angle(degrees=ra)._hours, dec) for ra, dec in vertices]
        df = pandas.DataFrame(rows, columns=["ra_hours", "dec_degrees"])
        df["epoch_year"] = 1991.25
        positions = self.earth.observe(Star.from_dataframe(df))
        df["x"], df["y"] = self.projection(positions)

        roll_rad = self.roll * (np.pi / 180)
        roll_sin = np.sin(roll_rad)
        roll_cos = np.cos(roll_rad)

        df = df.assign(
            xr=df["x"] * roll_cos - df["y"] * roll_sin,
            yr=df["y"] * roll_cos + df["x"] * roll_sin,
        )
        df = df.assign(
            x_pos=df["xr"] * self.pixel_scale + self.render_center[0],
            y_pos=df["yr"] * -1 * self.pixel_scale + self.render_center[1],
        )
        return list(zip(df["x_pos"], df["y_pos"]))

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

    def plot_starfield(
        self, ra, dec, roll, constellation_brightness=32, shade_frustrum: bool = False
    ):
        """
        Returns an image of the starfield at the
        provided RA/DEC/ROLL with or without
        constellation lines
        """
        self.update_projection(ra, dec)
        self.roll = roll

        # Project stars + constellation edges into the unit "sky" plane
        # centred on the current RA/Dec. Results are numpy arrays; the
        # per-frame rotate/screen-space math lives in render_starfield_pil.
        self._stars_x, self._stars_y = self.projection(self.star_positions)
        self._const_sx, self._const_sy = self.projection(
            self.const_start_star_positions
        )
        self._const_ex, self._const_ey = self.projection(self.const_end_star_positions)

        pil_image, visible_stars = self.render_starfield_pil(
            constellation_brightness, shade_frustrum
        )
        return pil_image, visible_stars

    def render_starfield_pil(
        self, constellation_brightness: int, shade_frustrum: bool = False
    ):
        """
        constellation_brightness: intensity of constellation lines
        shade_frustrum: Shade areas of the chart that are outside of the actual camera FOV

        returns (image, visible_stars)
        """
        ret_image = Image.new("L", self.render_size)
        idraw = ImageDraw.Draw(ret_image)

        W, H = self.render_size
        cx, cy = self.render_center

        frustrum_perc = 9.5 / self.fov
        if shade_frustrum and frustrum_perc < 0.99:
            idraw.rectangle([0, 0, W, H], fill=32)

            # Calc square for in-frustrum
            frustrum_offset = (W - frustrum_perc * W) / 2
            idraw.rectangle(
                [
                    frustrum_offset,
                    frustrum_offset,
                    W - frustrum_offset,
                    H - frustrum_offset,
                ],
                fill=0,
            )

        # prep rotate by roll....
        roll_rad = self.roll * (np.pi / 180.0)
        roll_sin = np.sin(roll_rad)
        roll_cos = np.cos(roll_rad)

        # constellation lines first
        if constellation_brightness:
            # Rotate each endpoint by roll, then project to screen-space.
            # All in numpy -- the previous pandas .assign chain dominated
            # the per-frame cost.
            sx = self._const_sx
            sy = self._const_sy
            ex = self._const_ex
            ey = self._const_ey
            sxr = sx * roll_cos - sy * roll_sin
            syr = sy * roll_cos + sx * roll_sin
            exr = ex * roll_cos - ey * roll_sin
            eyr = ey * roll_cos + ex * roll_sin
            sx_pos = sxr * self.pixel_scale + cx
            sy_pos = -syr * self.pixel_scale + cy
            ex_pos = exr * self.pixel_scale + cx
            ey_pos = -eyr * self.pixel_scale + cy

            # Keep edges where at least one endpoint is on-screen.
            start_on = (sx_pos > 0) & (sx_pos < W) & (sy_pos > 0) & (sy_pos < H)
            end_on = (ex_pos > 0) & (ex_pos < W) & (ey_pos > 0) & (ey_pos < H)
            for i in np.flatnonzero(start_on | end_on):
                idraw.line(
                    [sx_pos[i], sy_pos[i], ex_pos[i], ey_pos[i]],
                    fill=constellation_brightness,
                )

        # Star filter: by magnitude, then by visibility in projection space.
        # We track the surviving indices into self.stars so we can rebuild
        # the visible_stars DataFrame at the end (align.py consumes its
        # catalog columns like ra_degrees / dec_degrees / magnitude).
        sx = self._stars_x
        sy = self._stars_y
        mag = self._star_magnitudes
        keep = (
            (mag < self.mag_limit)
            & (sx > -self.limit)
            & (sx < self.limit)
            & (sy > -self.limit)
            & (sy < self.limit)
        )
        visible_idx = np.flatnonzero(keep)
        sx = sx[visible_idx]
        sy = sy[visible_idx]
        mag = mag[visible_idx]

        # Rotate and convert to screen space.
        xr = sx * roll_cos - sy * roll_sin
        yr = sy * roll_cos + sx * roll_sin
        x_pos = xr * self.pixel_scale + cx
        y_pos = -yr * self.pixel_scale + cy

        # Draw each visible star.
        mag_limit = self.mag_limit
        for i in range(len(x_pos)):
            m = mag[i]
            plot_size = (mag_limit - m) / 3
            fill = 128 if m > 4.5 else 255
            xp = x_pos[i]
            yp = y_pos[i]
            if plot_size < 0.5:
                idraw.point((xp, yp), fill=fill)
            else:
                idraw.circle(
                    (round(xp), round(yp)),
                    radius=plot_size,
                    fill=255,
                    width=0,
                )

        # Frustrum filter for the returned visible_stars set.
        if frustrum_perc < 0.99:
            frustrum_offset = (W - frustrum_perc * W) / 2
            in_frustrum = (
                (x_pos > frustrum_offset)
                & (x_pos < W - frustrum_offset)
                & (y_pos > frustrum_offset)
                & (y_pos < H - frustrum_offset)
            )
            visible_idx = visible_idx[in_frustrum]
            x_pos = x_pos[in_frustrum]
            y_pos = y_pos[in_frustrum]

        # Rebuild visible_stars as a DataFrame for align.py compatibility:
        # it expects pandas semantics (.iloc, .sort_values, .assign) and
        # accesses catalog columns like ra_degrees / dec_degrees in addition
        # to x_pos / y_pos / magnitude.
        visible_stars = self.stars.iloc[visible_idx].copy()
        visible_stars["x_pos"] = x_pos
        visible_stars["y_pos"] = y_pos

        return ret_image, visible_stars
