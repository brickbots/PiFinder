#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Coordinate mapping between the production solver frame and the
full-sensor frame used by SEP detection.

The production solver frame is the 512x512 processed image: the sensor
frame cropped to a centred square, resized, then rotated per
screen_direction / camera_rotation (camera_interface stage 5). Plate
solutions -- including ``target_pixel``, the persisted eyepiece
alignment point -- live in that space.

The SEP path detects on the *uncropped* raw frame. To keep RA/Dec/Roll
and the alignment semantics identical, its solve runs in a frame with
the SAME rotation applied ("the rotated full frame"). Because the crop
is centred and the resize is isotropic, mapping the alignment point
between the two rotated frames reduces to a scale about the frame
centre -- the rotations cancel (proof: both rotations are about their
frame centres and the optical centre coincides with both).

Rotation conventions are pinned by tests against PIL's ``Image.rotate``
(counterclockwise, expand=False), which is what stage 5 uses.
"""

import math
from typing import Tuple

import numpy as np

# The production solve calls tetra3 with (512, 512) and fov_estimate 12.0
# (solver.py). That makes the plate scale 12 deg across the cropped
# square, whatever the crop width in sensor pixels.
SOLVER_FRAME_PX = 512
SOLVER_FOV_DEG = 12.0


def stage5_rotation_deg(screen_direction, camera_rotation) -> float:
    """The rotation camera_interface stage 5 applies, in PIL CCW degrees.

    Reads ``SCREEN_ROTATE_AMOUNTS`` from camera_interface (the single
    source of the per-variant rotation) via a lazy import so this module
    stays cheap to import in tests and offline tools.
    """
    if camera_rotation is not None:
        return (-int(camera_rotation)) % 360
    from PiFinder.camera_interface import SCREEN_ROTATE_AMOUNTS

    return float(SCREEN_ROTATE_AMOUNTS.get(screen_direction, 270))


def rotate_centroids(
    centroids: np.ndarray, frame_hw: Tuple[int, int], angle_deg: float
) -> Tuple[np.ndarray, Tuple[int, int]]:
    """
    Rotate (y, x) centroids the way stage 5 rotates the image (CCW).

    Quarter turns use the exact integer mapping with the canvas dims
    swapped (np.rot90-style, no pixels lost). Other angles rotate about
    the canvas centre with the canvas size unchanged (PIL expand=False
    semantics; verified empirically against Image.rotate).

    Returns (rotated centroids, rotated canvas (h, w)).
    """
    cents = np.asarray(centroids, dtype=np.float64).reshape(-1, 2)
    h, w = frame_hw
    angle = angle_deg % 360
    if angle == 0:
        return cents.copy(), (h, w)

    if angle % 90 == 0:
        out = cents.copy()
        hh, ww = h, w
        for _ in range(int(angle // 90) % 4):
            y, x = out[:, 0], out[:, 1]
            out = np.column_stack((ww - 1 - x, y))
            hh, ww = ww, hh
        return out, (hh, ww)

    cy, cx = (h - 1) / 2.0, (w - 1) / 2.0
    rad = math.radians(angle)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    dy = cents[:, 0] - cy
    dx = cents[:, 1] - cx
    new_x = cx + dx * cos_a + dy * sin_a
    new_y = cy - dx * sin_a + dy * cos_a
    return np.column_stack((new_y, new_x)), (h, w)


def map_target_pixel_to_frame(
    target_pixel_yx, frame_hw: Tuple[int, int], crop_width_px: int
) -> Tuple[float, float]:
    """
    Map ``target_pixel`` (stored in rotated-512 space) into a rotated
    full-frame canvas of size ``frame_hw``.

    Scale about the centre by crop_width/512; the rotations cancel (see
    module docstring). ``crop_width_px`` is the cropped square's width
    in sensor pixels (e.g. 980 for imx462).
    """
    scale = crop_width_px / float(SOLVER_FRAME_PX)
    c512 = (SOLVER_FRAME_PX - 1) / 2.0
    cy, cx = (frame_hw[0] - 1) / 2.0, (frame_hw[1] - 1) / 2.0
    ty, tx = float(target_pixel_yx[0]), float(target_pixel_yx[1])
    return (cy + (ty - c512) * scale, cx + (tx - c512) * scale)


def map_frame_pixel_to_target(
    pixel_yx, frame_hw: Tuple[int, int], crop_width_px: int
) -> Tuple[float, float]:
    """Inverse of :func:`map_target_pixel_to_frame`: a pixel in the rotated
    full-frame canvas back into rotated-512 ``target_pixel`` space.

    Used by the SEP-path alignment: tetra3 returns the alignment target's
    y/x in the full-frame canvas, but the production chain stores and
    consumes target pixels in 512 space, so the result must come back
    through the same centre-scale relation (same proof as the forward
    mapping -- centre-symmetric crop, isotropic resize).
    """
    scale = SOLVER_FRAME_PX / float(crop_width_px)
    c512 = (SOLVER_FRAME_PX - 1) / 2.0
    cy, cx = (frame_hw[0] - 1) / 2.0, (frame_hw[1] - 1) / 2.0
    py, px = float(pixel_yx[0]), float(pixel_yx[1])
    return (c512 + (py - cy) * scale, c512 + (px - cx) * scale)


def fov_estimate_deg(frame_width_px: int, crop_width_px: int) -> float:
    """FOV across ``frame_width_px`` sensor pixels, from the production
    calibration of SOLVER_FOV_DEG across the cropped square."""
    return SOLVER_FOV_DEG * frame_width_px / float(crop_width_px)
