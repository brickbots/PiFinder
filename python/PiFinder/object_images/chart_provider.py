#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Gaia chart provider - generates star charts from Gaia catalog
"""

from pathlib import Path
from typing import Generator
from PIL import ImageChops
from PiFinder import utils
from .image_base import ImageProvider, ImageType
import logging

logger = logging.getLogger("PiFinder.ChartProvider")


class ChartImageProvider(ImageProvider):
    """
    Provides dynamically generated Gaia star charts

    Uses the GaiaChartGenerator to create on-demand star charts
    from the HEALPix-indexed Gaia star catalog. Returns a generator
    that yields progressive updates as magnitude bands load.
    """

    def __init__(self, config_object, shared_state):
        """
        Initialize chart provider

        Args:
            config_object: PiFinder config object
            shared_state: Shared state object
        """
        self.config_object = config_object
        self.shared_state = shared_state
        self._chart_generator = None

    def can_provide(self, catalog_object, **kwargs) -> bool:
        """
        Check if Gaia chart can be generated

        Returns True if Gaia star catalog exists
        """
        gaia_catalog_path = Path(utils.astro_data_dir, "gaia_stars", "metadata.json")
        return gaia_catalog_path.exists()

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
        shared_state=None,
        **kwargs
    ) -> Generator:
        """
        Generate Gaia star chart

        Yields progressive chart updates as magnitude bands load.
        Each yielded image has an `is_loading_placeholder` attribute
        indicating whether it's a loading screen or actual chart.

        Returns:
            Generator yielding PIL.Image objects
        """
        from .image_utils import create_loading_image, create_no_image_placeholder

        # Get chart generator (singleton)
        if self._chart_generator is None:
            from .gaia_chart import get_gaia_chart_generator

            self._chart_generator = get_gaia_chart_generator(
                self.config_object, self.shared_state
            )

        gaia_catalog_path = Path(utils.astro_data_dir, "gaia_stars", "metadata.json")

        if not gaia_catalog_path.exists():
            logger.warning(f"Gaia star catalog not found at {gaia_catalog_path}")
            placeholder = create_no_image_placeholder(display_class, burn_in=burn_in)
            yield placeholder
            return

        try:
            # Ensure catalog loading started
            logger.debug("Calling chart_generator.ensure_catalog_loading()...")
            self._chart_generator.ensure_catalog_loading()
            logger.debug(
                f"Catalog state: {self._chart_generator.get_catalog_state()}"
            )

            # Create generator that yields converted images
            for image in self._chart_generator.generate_chart(
                catalog_object,
                (display_class.fov_res, display_class.fov_res),
                burn_in=burn_in,
                display_class=display_class,
                roll=roll,
            ):
                if image is None:
                    # Catalog not ready yet, show "Loading..." with progress
                    if self._chart_generator.catalog:
                        progress_text = self._chart_generator.catalog.load_progress
                        progress_percent = self._chart_generator.catalog.load_percent
                    else:
                        progress_text = "Initializing..."
                        progress_percent = 0

                    loading_image = create_loading_image(
                        display_class,
                        message="Loading...",
                        progress_text=progress_text,
                        progress_percent=progress_percent,
                    )
                    loading_image.image_type = ImageType.LOADING
                    yield loading_image
                else:
                    # Convert chart to red and yield it
                    red_image = ImageChops.multiply(
                        image.convert("RGB"), display_class.colors.red_image
                    )
                    # Mark as Gaia chart image
                    red_image.image_type = ImageType.GAIA_CHART  # type: ignore[attr-defined]
                    yield red_image

        except Exception as e:
            logger.error(f"Gaia chart generation failed: {e}", exc_info=True)
            placeholder = create_no_image_placeholder(display_class, burn_in=burn_in)
            placeholder.image_type = ImageType.ERROR
            yield placeholder
