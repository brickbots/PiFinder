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
import logging

BASE_IMAGE_PATH = f"{utils.data_dir}/catalog_images"
CATALOG_PATH = f"{utils.astro_data_dir}/pifinder_objects.db"


logger = logging.getLogger("Catalog.Images")


def get_display_image(
    catalog_object,
    eyepiece_text,
    fov,
    roll,
    display_class,
    burn_in=True,
    magnification=None,
):
    """
    Returns a 128x128 image buffer for
    the catalog object/source
    Resizing/cropping as needed to achieve FOV
    in degrees
        fov: 1-.125
    roll:
        degrees
    """

    object_image_path = resolve_image_name(catalog_object, source="POSS")
    logger.debug("object_image_path = %s", object_image_path)
    if not os.path.exists(object_image_path):
        return_image = Image.new("RGB", display_class.resolution)
        ri_draw = ImageDraw.Draw(return_image)
        if burn_in:
            ri_draw.text(
                (30, 50),
                _("No Image"),
                font=display_class.fonts.large.font,
                fill=display_class.colors.get(128),
            )
    else:
        return_image = Image.open(object_image_path)

        # rotate for roll / newtonian orientation
        image_rotate = 180
        if roll is not None:
            image_rotate += roll

        return_image = return_image.rotate(image_rotate)

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
        # Top text - FOV on left, magnification on right
        ui_utils.shadow_outline_text(
            ri_draw,
            (1, display_class.titlebar_height - 1),
            f"{fov:0.2f}°",
            font=display_class.fonts.base,
            align="left",
            fill=display_class.colors.get(254),
            shadow_color=display_class.colors.get(0),
            outline=2,
        )

        magnification_text = (
            f"{magnification:.0f}x" if magnification and magnification > 0 else "?x"
        )
        ui_utils.shadow_outline_text(
            ri_draw,
            (
                display_class.resX - (display_class.fonts.base.width * 4),
                display_class.titlebar_height - 1,
            ),
            magnification_text,
            font=display_class.fonts.base,
            align="right",
            fill=display_class.colors.get(254),
            shadow_color=display_class.colors.get(0),
            outline=2,
        )

        # Bottom text - only eyepiece information
        ui_utils.shadow_outline_text(
            ri_draw,
            (1, display_class.resY - (display_class.fonts.base.height * 1.1)),
            eyepiece_text,
            font=display_class.fonts.base,
            align="left",
            fill=display_class.colors.get(128),
            shadow_color=display_class.colors.get(0),
            outline=2,
        )

    return return_image


def resolve_image_name(catalog_object, source):
    """
    returns the image path for this object
    """

    def create_image_path(image_name):
        last_char = str(image_name)[-1]
        image = f"{BASE_IMAGE_PATH}/{last_char}/{image_name}_{source}.jpg"
        exists = os.path.exists(image)
        return exists, image

    # Try primary name
    image_name = f"{catalog_object.catalog_code}{catalog_object.sequence}"
    ok, image = create_image_path(image_name)

    if ok:
        catalog_object.image_name = image
        return image

    # Try alternatives
    for name in catalog_object.names:
        alt_image_name = f"{''.join(name.split())}"
        ok, image = create_image_path(alt_image_name)
        if ok:
            catalog_object.image_name = image
            return image

    return ""


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
