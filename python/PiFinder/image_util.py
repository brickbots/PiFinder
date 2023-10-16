#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module has some general
image processing utils
mainly related to the preview
function

"""
from PIL import Image, ImageChops
import numpy as np
import scipy.ndimage
from enum import Enum
import functools
from collections import namedtuple
import logging


ColorMask = namedtuple("ColorMask", ["mask", "mode"])
RED_RGB: ColorMask = ColorMask(np.array([1, 0, 0]), "RGB")
RED_BGR: ColorMask = ColorMask(np.array([0, 0, 1]), "BGR")
GREY: ColorMask = ColorMask(np.array([1, 1, 1]), "RGB")


class Colors:
    def __init__(self, color_mask: ColorMask):
        self.color_mask = color_mask[0]
        self.mode = color_mask[1]
        self.red_image = Image.new("RGB", (128, 128), self.get(255))

    @functools.cache
    def get(self, color_intensity):
        arr = self.color_mask * color_intensity
        result = tuple(arr)
        return result


class DeviceWrapper:
    colors: Colors

    def __init__(self, device, color_mask: ColorMask):
        self.device = device
        self.colors = Colors(color_mask)

    def set_brightness(self, level):
        """
        Sets oled brightness
        0-255
        """
        self.device.contrast(level)


def make_red(in_image, colors):
    return ImageChops.multiply(in_image.convert("RGB"), colors.red_image)


def gamma_correct_low(in_value):
    return gamma_correct(in_value, 0.9)


def gamma_correct_med(in_value):
    return gamma_correct(in_value, 0.7)


def gamma_correct_high(in_value):
    return gamma_correct(in_value, 0.5)


def gamma_correct(in_value, gamma):
    in_value = float(in_value) / 255
    out_value = pow(in_value, gamma)
    out_value = int(255 * out_value)
    return out_value


def subtract_background(image, percent=1):
    image = np.asarray(image, dtype=np.float32)
    if image.ndim == 3:
        assert image.shape[2] in (1, 3), "Colour image must have 1 or 3 colour channels"
        if image.shape[2] == 3:
            # Convert to greyscale
            image = (
                image[:, :, 0] * 0.299 + image[:, :, 1] * 0.587 + image[:, :, 2] * 0.114
            )
        else:
            # Delete empty dimension
            image = image.squeeze(axis=2)
    else:
        assert image.ndim == 2, "Image must be 2D or 3D array"

    image = image - (
        scipy.ndimage.filters.uniform_filter(image, size=25, output=image.dtype)
        * percent
    )
    return Image.fromarray(image)


def convert_image_to_mode(image: Image.Image, mode: str):
    if mode == "RGB":
        return Image.fromarray(np.array(image)[:, :, ::-1])
    return image
