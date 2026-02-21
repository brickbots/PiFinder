#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Object image providers for catalog objects

Provides POSS survey images and generated Gaia star charts
"""

from typing import Union, Generator
from PIL import Image
from .poss_provider import POSSImageProvider
from .chart_provider import ChartImageProvider
from .image_base import ImageProvider


def get_display_image(
    catalog_object,
    eyepiece_text,
    fov,
    roll,
    display_class,
    burn_in=True,
    force_chart=False,
    **kwargs,
) -> Union[Image.Image, Generator]:
    """
    Get display image for catalog object

    Returns POSS image if available, otherwise generated Gaia chart.
    Use force_chart=True to prefer chart even if POSS exists.

    Args:
        catalog_object: The astronomical object to image
        eyepiece_text: Eyepiece description for overlay
        fov: Field of view in degrees
        roll: Rotation angle in degrees
        display_class: Display configuration object
        burn_in: Whether to add overlays (FOV, mag, etc.)
        force_chart: Force Gaia chart even if POSS exists
        **kwargs: Additional provider-specific parameters

    Returns:
        PIL.Image for POSS images
        Generator yielding progressive images for Gaia charts
    """
    provider: ImageProvider
    if force_chart:
        provider = ChartImageProvider(
            kwargs.get("config_object"), kwargs.get("shared_state")
        )
    else:
        poss = POSSImageProvider()
        if poss.can_provide(catalog_object):
            provider = poss
        else:
            provider = ChartImageProvider(
                kwargs.get("config_object"), kwargs.get("shared_state")
            )

    return provider.get_image(
        catalog_object,
        eyepiece_text,
        fov,
        roll,
        display_class,
        burn_in=burn_in,
        **kwargs,
    )


__all__ = ["get_display_image", "POSSImageProvider", "ChartImageProvider"]
