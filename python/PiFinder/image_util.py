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

red_image = Image.new("RGB", (128, 128), (0, 0, 255))


def make_red(in_image):
    return ImageChops.multiply(in_image, red_image)


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


def subtract_background(image):
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

    image = image - scipy.ndimage.filters.uniform_filter(
        image, size=25, output=image.dtype
    )
    return Image.fromarray(image)
