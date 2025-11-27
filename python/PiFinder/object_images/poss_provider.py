#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
POSS image provider - loads pre-downloaded survey images from disk
"""

import os
from PIL import Image
from PiFinder import utils
from PiFinder import image_util
from .image_base import ImageProvider, ImageType
import logging

logger = logging.getLogger("PiFinder.POSSProvider")

BASE_IMAGE_PATH = f"{utils.data_dir}/catalog_images"


class POSSImageProvider(ImageProvider):
    """
    Provides POSS (Palomar Observatory Sky Survey) images from disk

    POSS images are pre-downloaded 1024x1024 JPG files stored in
    subdirectories by object ID. This provider:
    - Loads image from disk
    - Rotates for telescope orientation
    - Crops to field of view
    - Resizes to display resolution
    - Converts to red
    - Adds circular vignette (optional)
    - Adds text overlays (optional)
    """

    def can_provide(self, catalog_object, **kwargs) -> bool:
        """Check if POSS image exists on disk"""
        image_path = self._resolve_image_name(catalog_object, source="POSS")
        return os.path.exists(image_path)

    def get_image(
        self,
        catalog_object,
        eyepiece_text,
        fov,
        roll,
        display_class,
        burn_in=True,
        magnification=None,
        config_object=None,
        **kwargs
    ) -> Image.Image:
        """
        Load and process POSS image

        Returns:
            PIL.Image with POSS image processed and overlayed
        """
        from .image_utils import (
            apply_circular_vignette,
            pad_to_display_resolution,
            add_image_overlays,
        )

        # Load image from disk
        image_path = self._resolve_image_name(catalog_object, source="POSS")
        return_image = Image.open(image_path)

        # Rotate for roll / newtonian orientation
        image_rotate = 180
        if roll is not None:
            image_rotate += roll
        return_image = return_image.rotate(image_rotate)  # type: ignore[assignment]

        # Crop to FOV
        fov_size = int(1024 * fov / 2)
        return_image = return_image.crop(  # type: ignore[assignment]
            (
                512 - fov_size,
                512 - fov_size,
                512 + fov_size,
                512 + fov_size,
            )
        )

        # Resize to display resolution
        return_image = return_image.resize(  # type: ignore[assignment]
            (display_class.fov_res, display_class.fov_res), Image.Resampling.LANCZOS
        )

        # Convert to red
        return_image = image_util.make_red(return_image, display_class.colors)

        # Add circular vignette if burn_in
        if burn_in:
            return_image = apply_circular_vignette(return_image, display_class)

        # Pad to display resolution if needed
        return_image = pad_to_display_resolution(return_image, display_class)

        # Add text overlays if burn_in
        if burn_in:
            # Get eyepiece object for overlay
            if config_object and hasattr(config_object, "equipment"):
                eyepiece_obj = config_object.equipment.active_eyepiece
            else:
                # Create minimal eyepiece object from text
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
                burn_in=True,
            )

        # Mark as POSS image
        return_image.image_type = ImageType.POSS  # type: ignore[attr-defined]
        return return_image

    def _resolve_image_name(self, catalog_object, source):
        """
        Resolve image path for this object

        Checks primary name and alternatives

        Args:
            catalog_object: Object to find image for
            source: Image source ("POSS", "SDSS", etc.)

        Returns:
            Path to image file, or empty string if not found
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
