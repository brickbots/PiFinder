"""
Unit tests for the daytime alignment screen (issue #455).

Covers the pure geometry the screen relies on -- quadrant subdivision, the
display-space -> native (Y, X) conversion that produces ``target_pixel``, and
the shared camera-render crop/zoom helper -- without constructing the full UI
module (no display/camera needed).
"""

import pytest
from PIL import Image

from PiFinder.ui.align_daytime import (
    QUADRANT_KEYS,
    MAX_QUADRANT_ROUNDS,
    CAMERA_NATIVE_RES,
    quadrant_subrect,
    rect_center,
    display_to_native,
)
from PiFinder.ui.camera_render import crop_for_zoom, resize_for_display

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# Quadrant subdivision math
# --------------------------------------------------------------------------- #


def test_quadrant_corners_partition_the_region():
    """7/9/1/3 map to the four corners and together tile the region exactly."""
    region = (0, 0, 128, 128)
    assert quadrant_subrect(region, 7) == (0, 0, 64, 64)  # top-left
    assert quadrant_subrect(region, 9) == (64, 0, 128, 64)  # top-right
    assert quadrant_subrect(region, 1) == (0, 64, 64, 128)  # bottom-left
    assert quadrant_subrect(region, 3) == (64, 64, 128, 128)  # bottom-right


def test_quadrant_subrect_is_a_quarter_of_the_area():
    region = (0, 0, 176, 176)
    for corner in QUADRANT_KEYS:
        x0, y0, x1, y1 = quadrant_subrect(region, corner)
        assert (x1 - x0) == pytest.approx(88)
        assert (y1 - y0) == pytest.approx(88)


def test_quadrant_subrect_works_on_an_offset_region():
    """Subdividing an already-narrowed (non-origin) region stays correct."""
    region = (64, 64, 128, 128)  # the bottom-right quarter of a 128 frame
    assert quadrant_subrect(region, 7) == (64, 64, 96, 96)
    assert quadrant_subrect(region, 3) == (96, 96, 128, 128)


def test_quadrant_subrect_rejects_non_corner_keys():
    for bad in (0, 2, 4, 5, 6, 8):
        with pytest.raises(ValueError):
            quadrant_subrect((0, 0, 128, 128), bad)


def test_three_rounds_reach_the_legibility_floor():
    """MAX_QUADRANT_ROUNDS of quartering shrink the frame to ~1/8 of its width.

    Each pick makes the chosen quadrant the new region, so after three picks the
    region (= the last cell the user selected) is res / 8 wide: 16px on the 128
    panel, ~22px on 176 -- the floor the on-screen quadrant labels read at.
    """
    for res, expected_cell in ((128, 16), (176, 22)):
        region = (0, 0, res, res)
        for _ in range(MAX_QUADRANT_ROUNDS):
            region = quadrant_subrect(region, 7)  # keep picking top-left
        x0, _y0, x1, _y1 = region
        assert (x1 - x0) == pytest.approx(res / 8)
        assert round(x1 - x0) == expected_cell


def test_rect_center():
    assert rect_center((0, 0, 128, 128)) == (64, 64)
    assert rect_center((64, 64, 128, 128)) == (96, 96)
    assert rect_center((0, 0, 176, 100)) == (88, 50)


# --------------------------------------------------------------------------- #
# display-space -> native (Y, X) conversion (this is what target_pixel stores)
# --------------------------------------------------------------------------- #


def test_display_to_native_center_maps_to_frame_center():
    # Centre of a 128 display -> centre of the 512 native frame, as (Y, X).
    assert display_to_native((64, 64), (128, 128)) == (256.0, 256.0)


def test_display_to_native_returns_y_x_order():
    """A point that is *not* on the diagonal proves the (Y, X) ordering."""
    # display x=96 (3/4 across), y=32 (1/4 down) on a 128 panel.
    y, x = display_to_native((96, 32), (128, 128))
    assert x == pytest.approx(96 * CAMERA_NATIVE_RES / 128)  # 384
    assert y == pytest.approx(32 * CAMERA_NATIVE_RES / 128)  # 128


def test_display_to_native_scales_for_176_panel():
    # 44px on a 176 panel is a quarter across -> 128 in native space.
    assert display_to_native((44, 44), (176, 176)) == (128.0, 128.0)
    assert display_to_native((88, 88), (176, 176)) == (256.0, 256.0)


def test_display_to_native_corners():
    # Top-left display corner -> native origin; bottom-right -> full extent.
    assert display_to_native((0, 0), (128, 128)) == (0.0, 0.0)
    y, x = display_to_native((128, 128), (128, 128))
    assert (y, x) == (CAMERA_NATIVE_RES, CAMERA_NATIVE_RES)


# --------------------------------------------------------------------------- #
# Shared camera-render helper (crop/zoom/resize)
# --------------------------------------------------------------------------- #


def test_crop_for_zoom_level_0_is_identity():
    img = Image.new("L", (512, 512))
    assert crop_for_zoom(img, 0) is img


def test_crop_for_zoom_centre_crops():
    img = Image.new("L", (512, 512))
    assert crop_for_zoom(img, 1).size == (256, 256)  # 2x
    assert crop_for_zoom(img, 2).size == (128, 128)  # 4x


def test_resize_for_display_targets_display_resolution():
    img = Image.new("L", (512, 512))
    for res in ((128, 128), (176, 176)):
        assert resize_for_display(img, res, 0).size == res
        assert resize_for_display(img, res, 2).size == res


def test_resize_for_display_preserves_mode():
    """The helper leaves the colour pipeline to the caller (keeps input mode)."""
    assert resize_for_display(Image.new("L", (512, 512)), (128, 128)).mode == "L"
    assert resize_for_display(Image.new("RGB", (512, 512)), (128, 128)).mode == "RGB"
