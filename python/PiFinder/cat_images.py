#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is used at runtime
to handle catalog image loading
"""

import os
from PIL import Image, ImageChops, ImageDraw
from PiFinder import image_util
from PiFinder import utils
import PiFinder.ui.ui_utils as ui_utils

BASE_IMAGE_PATH = f"{utils.data_dir}/catalog_images"
CATALOG_PATH = f"{utils.astro_data_dir}/pifinder_objects.db"


def get_display_image(catalog_object, source, fov, roll, display_class, burn_in=True):
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
    print(object_image_path)
    if not os.path.exists(object_image_path):
        return_image = Image.new("RGB", display_class.resolution)
        ri_draw = ImageDraw.Draw(return_image)
        if burn_in:
            ri_draw.text(
                (30, 50),
                "No Image",
                font=display_class.fonts.large.font,
                fill=display_class.colors.get(128),
            )
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
        return_image = return_image.resize(
            (display_class.fov_res, display_class.fov_res), Image.LANCZOS
        )

        # RED
        return_image = image_util.make_red(return_image, display_class.colors)

        if burn_in:
            # circle
            _circle_dim = Image.new(
                "RGB",
                (display_class.fov_res, display_class.fov_res),
                display_class.colors.get(127),
            )
            _circle_draw = ImageDraw.Draw(_circle_dim)
            _circle_draw.ellipse(
                [2, 2, display_class.fov_res - 2, display_class.fov_res - 2],
                fill=display_class.colors.get(255),
            )
            return_image = ImageChops.multiply(return_image, _circle_dim)

            ri_draw = ImageDraw.Draw(return_image)
            ri_draw.ellipse(
                [2, 2, display_class.fov_res - 2, display_class.fov_res - 2],
                outline=display_class.colors.get(64),
                width=1,
            )

        # Pad out image if needed
        if display_class.fov_res != display_class.resX:
            pad_image = Image.new("RGB", display_class.resolution)
            pad_image.paste(
                return_image,
                (
                    int((display_class.resX - display_class.fov_res) / 2),
                    0,
                ),
            )
            return_image = pad_image
            ri_draw = ImageDraw.Draw(return_image)
        if display_class.fov_res != display_class.resY:
            pad_image = Image.new("RGB", display_class.resolution)
            pad_image.paste(
                return_image,
                (
                    0,
                    int((display_class.resY - display_class.fov_res) / 2),
                ),
            )
            return_image = pad_image
            ri_draw = ImageDraw.Draw(return_image)

        if burn_in:
            # Outlined text on image source and fov
            ui_utils.shadow_outline_text(
                ri_draw,
                (1, display_class.resY - (display_class.fonts.base.height * 1.1)),
                source,
                font=display_class.fonts.base,
                align="left",
                fill=display_class.colors.get(128),
                shadow_color=display_class.colors.get(0),
                outline=2,
            )

            ui_utils.shadow_outline_text(
                ri_draw,
                (
                    display_class.resX - (display_class.fonts.base.width * 6),
                    display_class.resY - (display_class.fonts.base.height * 1.1),
                ),
                f"{fov:0.2f}°",
                align="right",
                font=display_class.fonts.base,
                fill=display_class.colors.get(254),
                shadow_color=display_class.colors.get(0),
                outline=2,
            )

    return return_image


def resolve_image_name(catalog_object, source):
    """
    returns the image path for this objects
    """
    if catalog_object.image_name == "":
        return ""

    return f"{BASE_IMAGE_PATH}/{str(catalog_object.image_name)[-1]}/{catalog_object.image_name}_{source}.jpg"


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
