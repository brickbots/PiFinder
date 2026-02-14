#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Abstract base class for object image providers
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Union, Generator
from PIL import Image


class ImageType(Enum):
    """Image type enumeration for object images"""
    POSS = "poss"  # Survey image from disk
    GAIA_CHART = "gaia_chart"  # Generated star chart
    LOADING = "loading"  # Loading placeholder
    ERROR = "error"  # Error placeholder


class ImageProvider(ABC):
    """
    Base class for object image providers

    Provides a common interface for different image sources:
    - POSS/survey images from disk
    - Generated Gaia star charts
    - Future: SDSS, online images, etc.
    """

    @abstractmethod
    def can_provide(self, catalog_object, **kwargs) -> bool:
        """
        Check if this provider can supply an image for the given object

        Args:
            catalog_object: The astronomical object to image
            **kwargs: Additional parameters (config, paths, etc.)

        Returns:
            True if this provider can supply an image
        """
        pass

    @abstractmethod
    def get_image(
        self,
        catalog_object,
        eyepiece_text,
        fov,
        roll,
        display_class,
        burn_in=True,
        **kwargs
    ) -> Union[Image.Image, Generator]:
        """
        Get image for catalog object

        Args:
            catalog_object: The astronomical object to image
            eyepiece_text: Eyepiece description for overlay
            fov: Field of view in degrees
            roll: Rotation angle in degrees
            display_class: Display configuration object
            burn_in: Whether to add overlays (FOV, mag, etc.)
            **kwargs: Provider-specific parameters

        Returns:
            PIL.Image for static images (POSS)
            Generator yielding progressive images (Gaia charts)
        """
        pass
