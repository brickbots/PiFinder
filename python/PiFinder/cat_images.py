#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is used at runtime
to handle catalog image loading
"""
import sqlite3
import os
from PIL import Image, ImageChops, ImageDraw
from PiFinder import image_util
from PiFinder.ui.fonts import Fonts as fonts
from PiFinder import utils
import PiFinder.ui.ui_utils as ui_utils

BASE_IMAGE_PATH = f"{utils.data_dir}/catalog_images"
CATALOG_PATH = f"{utils.astro_data_dir}/pifinder_objects.db"


def get_ngc_aka(catalog_object):
    """
    returns the NGC aka for this object
    if available
    """
    conn = sqlite3.connect(CATALOG_PATH)
    conn.row_factory = sqlite3.Row
    db_c = conn.cursor()

    aka_rec = conn.execute(
        f"""
        SELECT common_name from names
        where catalog_code = "{catalog_object.catalog_code}"
        and sequence = "{catalog_object.sequence}"
        and common_name like "NGC%"
    """
    ).fetchone()
    return aka_rec


def get_display_image(catalog_object, source, fov, roll, colors):
    """
    Returns a 128x128 image buffer for
    the catalog object/source
    Resizing/cropping as needed to achieve FOV
    in degrees
        fov: 1-.125
    roll:
        degrees
    """

    object_image_path = resolve_image_name(catalog_object, source)
    if not os.path.exists(object_image_path):
        if catalog_object.catalog_code != "NGC":
            # look for any NGC aka
            aka_rec = get_ngc_aka(catalog_object)
            if aka_rec:
                try:
                    aka_sequence = int(aka_rec["common_name"][3:].strip())
                except ValueError:
                    aka_sequence = None
                    pass

                if aka_sequence:
                    return get_display_image(
                        {"catalog": "NGC", "sequence": aka_sequence},
                        source,
                        fov,
                        roll,
                        colors,
                    )
        return_image = Image.new("RGB", (128, 128))
        ri_draw = ImageDraw.Draw(return_image)
        ri_draw.text((30, 50), "No Image", font=fonts.large, fill=colors.get(128))
    else:
        return_image = Image.open(object_image_path)

        # rotate for roll / newtonian orientation
        return_image = return_image.rotate(roll + 180)

        # FOV
        fov_size = int(1024 * fov / 2)
        return_image = return_image.crop(
            (
                512 - fov_size,
                512 - fov_size,
                512 + fov_size,
                512 + fov_size,
            )
        )
        return_image = return_image.resize((128, 128), Image.LANCZOS)

        # RED
        return_image = image_util.make_red(return_image, colors)

        # circle
        _circle_dim = Image.new("RGB", (128, 128), colors.get(127))
        _circle_draw = ImageDraw.Draw(_circle_dim)
        _circle_draw.ellipse([2, 2, 126, 126], fill=colors.get(255))
        return_image = ImageChops.multiply(return_image, _circle_dim)

        ri_draw = ImageDraw.Draw(return_image)
        ri_draw.ellipse([2, 2, 126, 126], outline=colors.get(64), width=1)

        # Outlined text on image source and fov
        ui_utils.shadow_outline_text(
            ri_draw,
            (1, 110),
            source,
            font=fonts.base,
            align="left",
            fill=colors.get(128),
            shadow_color=colors.get(0),
            outline=2,
        )

        ui_utils.shadow_outline_text(
            ri_draw,
            (98, 110),
            f"{fov:0.2f}°",
            align="right",
            font=fonts.base,
            fill=colors.get(254),
            shadow_color=colors.get(0),
            outline=2,
        )

    return return_image


def resolve_image_name(catalog_object, source):
    """
    returns the image path for this objects
    """
    return f"{BASE_IMAGE_PATH}/{str(catalog_object.sequence)[-1]}/{catalog_object.catalog_code}{catalog_object.sequence}_{source}.jpg"


def create_catalog_image_dirs():
    """
    Checks for and creates catalog_image dirs
    """
    if not os.path.exists(BASE_IMAGE_PATH):
        os.makedirs(BASE_IMAGE_PATH)

    for i in range(0, 10):
        _image_dir = f"{BASE_IMAGE_PATH}/{i}"
        if not os.path.exists(_image_dir):
            os.makedirs(_image_dir)
