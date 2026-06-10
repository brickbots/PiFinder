#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Shared helpers for rendering a native camera frame onto the display.

Both the Focus/Camera preview (``UIPreview``) and the daytime alignment screen
(``UIAlignDaytime``) need to take the square native camera frame and crop/zoom
it before scaling it to the (possibly non-square) display resolution. That
geometry is the part they share; the colour treatment afterwards differs
(the preview applies a background-anchored stretch + red night-vision mask;
daytime alignment shows full-brightness grayscale). These helpers cover only
the shared crop/zoom/resize step so each screen keeps its own colour pipeline.
"""

from PIL import Image


def crop_for_zoom(image: Image.Image, zoom_level: int) -> Image.Image:
    """Centre-crop the native frame for a zoom level (does not resize).

    ``zoom_level`` 0 returns the frame unchanged (full frame); 1 crops the
    centre half (2x), 2 the centre quarter (4x). The zoom factor stays 2x / 4x
    regardless of the native frame or display size because the crop is a fixed
    fraction of the native frame.
    """
    if zoom_level <= 0:
        return image

    native_w, native_h = image.size
    factor = 2**zoom_level  # 2 for level 1, 4 for level 2
    crop_w, crop_h = native_w // factor, native_h // factor
    ox, oy = (native_w - crop_w) // 2, (native_h - crop_h) // 2
    return image.crop((ox, oy, ox + crop_w, oy + crop_h))


def resize_for_display(
    image: Image.Image, resolution, zoom_level: int = 0
) -> Image.Image:
    """Crop/zoom a native camera frame and scale it to the display resolution.

    Returns an image in the input's mode (caller decides the colour pipeline).
    ``resolution`` is a ``(width, height)`` tuple.
    """
    return crop_for_zoom(image, zoom_level).resize(resolution)
