#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is used at runtime
to handle catalog image loading
"""

import math
import os
from PIL import Image, ImageChops, ImageDraw
from PiFinder import image_util
from PiFinder import utils
import PiFinder.ui.ui_utils as ui_utils
import logging

BASE_IMAGE_PATH = f"{utils.data_dir}/catalog_images"
CATALOG_PATH = f"{utils.astro_data_dir}/pifinder_objects.db"


logger = logging.getLogger("Catalog.Images")


def cardinal_vectors(image_rotate, fx=1, fy=1):
    """Return (nx, ny), (ex, ey) unit vectors for North and East.

    image_rotate: degrees the POSS image was rotated (180 + roll).
    fx, fy: -1 to mirror that axis (flip/flop), +1 otherwise.
    """
    theta = math.radians(image_rotate)
    n = (fx * math.sin(theta), fy * -math.cos(theta))
    e = (-fx * math.cos(theta), -fy * math.sin(theta))
    return n, e


def size_overlay_points(extents, pa, image_rotate, px_per_arcsec, cx, cy, fx=1, fy=1):
    """Compute outline points for the size overlay.

    Returns a list of (x, y) tuples.
    For 1 extent returns None (caller should use native ellipse).
    """
    if not extents or len(extents) == 1:
        return None

    theta = math.radians(image_rotate - pa - 90)
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)

    points = []
    if len(extents) == 2:
        rx = extents[0] * px_per_arcsec / 2
        ry = extents[1] * px_per_arcsec / 2
        for i in range(36):
            t = 2 * math.pi * i / 36
            x = rx * math.cos(t)
            y = ry * math.sin(t)
            points.append(
                (cx + fx * (x * cos_t - y * sin_t), cy + fy * (x * sin_t + y * cos_t))
            )
    else:
        step = 2 * math.pi / len(extents)
        for i, ext in enumerate(extents):
            angle = i * step - math.pi / 2
            r = ext * px_per_arcsec / 2
            x = r * math.cos(angle)
            y = r * math.sin(angle)
            points.append(
                (cx + fx * (x * cos_t - y * sin_t), cy + fy * (x * sin_t + y * cos_t))
            )
    return points


def get_display_image(
    catalog_object,
    eyepiece_text,
    fov,
    roll,
    display_class,
    burn_in=True,
    magnification=None,
    telescope=None,
    show_nsew=True,
    show_bbox=True,
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
    flip = telescope.flip_image if telescope else False
    flop = telescope.flop_image if telescope else False

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
        if flip:
            return_image = return_image.transpose(Image.FLIP_LEFT_RIGHT)
        if flop:
            return_image = return_image.transpose(Image.FLIP_TOP_BOTTOM)

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

            cx = display_class.fov_res / 2
            cy = display_class.fov_res / 2
            fx = -1 if flip else 1
            fy = -1 if flop else 1

            # NSEW cardinal labels
            if show_nsew:
                (nx, ny), (ex, ey) = cardinal_vectors(image_rotate, fx, fy)
                label_font = display_class.fonts.base
                label_color = display_class.colors.get(64)
                r_label = display_class.fov_res / 2 - 2
                top_limit = display_class.titlebar_height
                bottom_limit = display_class.fov_res - label_font.height * 2

                for label, dx, dy in [
                    ("N", nx, ny),
                    ("S", -nx, -ny),
                    ("E", ex, ey),
                    ("W", -ex, -ey),
                ]:
                    lx = cx + dx * r_label - label_font.width / 2
                    ly = cy + dy * r_label - label_font.height / 2
                    lx = max(0, min(lx, display_class.fov_res - label_font.width))
                    ly = max(top_limit, min(ly, bottom_limit))
                    ui_utils.shadow_outline_text(
                        ri_draw,
                        (lx, ly),
                        label,
                        font=label_font,
                        align="left",
                        fill=label_color,
                        shadow_color=display_class.colors.get(0),
                        outline=1,
                    )

            # Size overlay
            extents = catalog_object.size.extents
            if show_bbox and extents and fov > 0:
                px_per_arcsec = display_class.fov_res / (fov * 3600)
                overlay_color = display_class.colors.get(100)

                if len(extents) == 1:
                    r = extents[0] * px_per_arcsec / 2
                    ri_draw.ellipse(
                        [cx - r, cy - r, cx + r, cy + r],
                        outline=overlay_color,
                        width=1,
                    )
                else:
                    points = size_overlay_points(
                        extents,
                        catalog_object.size.position_angle,
                        image_rotate,
                        px_per_arcsec,
                        cx,
                        cy,
                        fx,
                        fy,
                    )
                    if points:
                        ri_draw.polygon(points, outline=overlay_color)

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
