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
    config_object=None,
    shared_state=None,
    chart_generator=None,  # Pass in from UI layer instead of creating here
    force_deep_chart=False,  # Toggle: force deep chart even if POSS image exists
):
    """
    Returns a 128x128 image buffer for
    the catalog object/source
    Resizing/cropping as needed to achieve FOV
    in degrees
        fov: 1-.125
    roll:
        degrees
    config_object:
        Required for deep chart generation
    shared_state:
        Required for deep chart generation
    """

    logger.info(f">>> get_display_image() called for {catalog_object.display_name if catalog_object else 'None'}")
    logger.info(f">>> force_deep_chart={force_deep_chart}, chart_generator={chart_generator is not None}")

    object_image_path = resolve_image_name(catalog_object, source="POSS")
    logger.info(f">>> POSS image path: {object_image_path}, exists: {os.path.exists(object_image_path)}")

    # If force_deep_chart is True, skip POSS image even if it exists
    if force_deep_chart or not os.path.exists(object_image_path):
        logger.info(f">>> Will use deep chart (force={force_deep_chart}, poss_missing={not os.path.exists(object_image_path)})")
        # Try to generate deep chart if catalog available
        return_image = None

        if config_object and shared_state:
            from pathlib import Path
            from PiFinder import utils

            deep_catalog_path = Path(utils.astro_data_dir, "deep_stars", "metadata.json")

            logger.info(f">>> Deep chart request: chart_generator={chart_generator is not None}, catalog_exists={deep_catalog_path.exists()}, path={deep_catalog_path}")

            # Try to generate deep chart if chart_generator was passed in
            if chart_generator is not None and deep_catalog_path.exists():
                logger.info(">>> chart_generator and deep catalog available, generating chart...")
                try:
                    from PiFinder.image_utils import create_loading_image

                    # Ensure catalog loading started
                    logger.info(">>> Calling chart_generator.ensure_catalog_loading()...")
                    chart_generator.ensure_catalog_loading()
                    logger.info(f">>> Catalog state: {chart_generator.get_catalog_state()}")

                    # Try to generate chart (progressive generator - consume all yields)
                    # The generator yields intermediate images as magnitude bands load
                    # We'll use the final (most complete) image
                    chart_image = None
                    logger.info(">>> Starting to consume chart generator yields...")
                    yield_count = 0
                    for image in chart_generator.generate_chart(
                        catalog_object,
                        (display_class.fov_res, display_class.fov_res),
                        burn_in=burn_in,
                        display_class=display_class,
                        roll=roll
                    ):
                        yield_count += 1
                        logger.info(f">>> Received yield #{yield_count}: {type(image)}")
                        chart_image = image  # Keep updating to latest
                        # TODO: Could potentially display intermediate images here for faster feedback

                    logger.info(f">>> Chart generation complete: {yield_count} yields, final image: {type(chart_image)}")

                    if chart_image is None:
                        logger.info(">>> Chart is None, creating loading placeholder...")
                        # Catalog not ready yet, show "Loading..." with progress
                        if chart_generator.catalog:
                            progress_text = chart_generator.catalog.load_progress
                            progress_percent = chart_generator.catalog.load_percent
                        else:
                            progress_text = "Initializing..."
                            progress_percent = 0

                        return_image = create_loading_image(
                            display_class,
                            message="Loading Chart...",
                            progress_text=progress_text,
                            progress_percent=progress_percent
                        )
                        # Mark image as "loading" so UI knows to refresh
                        return_image.is_loading_placeholder = True
                        logger.info(f">>> Returning loading placeholder: {type(return_image)}")
                    else:
                        logger.info(">>> Chart ready, converting to red...")
                        # Chart ready, convert to red
                        return_image = ImageChops.multiply(
                            chart_image.convert("RGB"),
                            display_class.colors.red_image
                        )
                        return_image.is_loading_placeholder = False
                        logger.info(f">>> Returning final chart image: {type(return_image)}")
                except Exception as e:
                    logger.error(f">>> Chart generation failed: {e}", exc_info=True)
                    return_image = None
            else:
                if chart_generator is None:
                    logger.warning(">>> Deep chart requested but chart_generator is None")
                if not deep_catalog_path.exists():
                    logger.warning(f">>> Deep star catalog not found at {deep_catalog_path}")

        # Fallback: "No Image" placeholder
        if return_image is None:
            logger.info(">>> No chart generated, creating 'No Image' placeholder")
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
        logger.info(">>> Using POSS image")
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
        # Use shared overlay utility for consistency with generated charts
        # Create fake eyepiece object from text if needed
        from PiFinder.image_utils import add_image_overlays

        # Parse eyepiece text to get eyepiece object
        # If we have config_object, use actual eyepiece
        if config_object and hasattr(config_object, 'equipment'):
            eyepiece_obj = config_object.equipment.active_eyepiece
        else:
            # Create minimal eyepiece object from text for overlay
            class FakeEyepiece:
                def __init__(self, text):
                    self.focal_length_mm = 0
                    self.name = text
            eyepiece_obj = FakeEyepiece(eyepiece_text)

        return_image = add_image_overlays(
            return_image,
            display_class,
            fov,
            magnification,
            eyepiece_obj,
            burn_in=True
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
