#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is used at runtime
to handle catalog image loading
"""
import requests
import sqlite3
import os
from PIL import Image, ImageOps, ImageDraw, ImageFont
from PiFinder import image_util

BASE_IMAGE_PATH = "/home/pifinder/PiFinder_data/catalog_images"
CATALOG_PATH = "/home/pifinder/PiFinder/astro_data/pifinder_objects.db"


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
        where catalog = "{catalog_object['catalog']}"
        and sequence = "{catalog_object['sequence']}"
        and common_name like "NGC%"
    """
    ).fetchone()
    return aka_rec


def get_display_image(catalog_object, source, fov, rotation):
    """
    Returns a 128x128 image buffer for
    the catalog object/source
    Resizing/cropping as needed to achieve FOV
    in degrees
        fov: 1-.125
    rotation:
        degrees
    """
    font_base = ImageFont.truetype(
        "/home/pifinder/PiFinder/fonts/RobotoMono-Regular.ttf", 10
    )
    font_large = ImageFont.truetype(
        "/home/pifinder/PiFinder/fonts/RobotoMono-Regular.ttf", 15
    )

    object_image_path = resolve_image_name(catalog_object, source)
    if not os.path.exists(object_image_path):
        if catalog_object["catalog"] != "NGC":
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
                        rotation,
                    )
        return_image = Image.new("RGB", (128, 128))
        ri_draw = ImageDraw.Draw(return_image)
        ri_draw.text((30, 50), "No Image", font=font_large, fill=(0, 0, 128))
    else:
        return_image = Image.open(object_image_path)

        # rotate
        return_image = return_image.rotate(rotation)

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
        return_image = return_image.convert("RGB")
        return_image = image_util.make_red(return_image)

        # circle
        _circle_dim = Image.new("RGBA", (128, 128), (0, 0, 128))
        _circle_draw = ImageDraw.Draw(_circle_dim)
        _circle_draw.circle([2, 2, 126, 126], fill=(0, 0, 256))
        return_image = ImageChops.multiply(return_image, _circle_dim)

        ri_draw = ImageDraw.Draw(return_image)
        ri_draw.circle([2, 2, 126, 126], outline=(0, 0, 128), width=1)

    # Burn In
    ri_draw.rectangle([0, 108, 30, 128], fill=(0, 0, 0))
    ri_draw.text((1, 110), source, font=font_base, fill=(0, 0, 128))

    ri_draw.rectangle([98, 108, 128, 128], fill=(0, 0, 0))
    ri_draw.text((100, 110), f"{fov:0.2f}", font=font_base, fill=(0, 0, 128))

    return return_image


def resolve_image_name(catalog_object, source):
    """
    returns the image path for this objects
    """
    return f"{BASE_IMAGE_PATH}/{str(catalog_object['sequence'])[-1]}/{catalog_object['catalog']}{catalog_object['sequence']}_{source}.jpg"


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
