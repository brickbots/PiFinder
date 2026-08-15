"""Tests for the chart frustum: the box marking what the camera images.

Two angles meet in ``plot``: the chart's zoom level, which the user changes,
and the camera's field of view, which follows the fitted optical train. The
frustum is the second drawn inside the first, and it decides two things at
once -- what gets shaded, and which stars come back as ``visible_stars`` (the
set the align screen picks an alignment star from). Both hang off
``frustum_box`` returning None or not, which is what these pin.
"""

import pytest

from PiFinder.optics import build_optical_train
from PiFinder.plot import frustum_box


RENDER_SIZE = (128, 128)


@pytest.mark.unit
class TestNoFrustum:
    """No stated camera means no frustum -- not a default one."""

    def test_absent_camera_fov_means_no_frustum(self):
        # There is no honest stand-in: the answer is a property of the
        # hardware in front of this device. A caller that has not said gets
        # the whole chart, shaded nowhere and filtered nowhere.
        assert frustum_box(RENDER_SIZE, 10.2, None) is None

    def test_a_camera_wider_than_the_chart_has_no_frustum(self):
        # Zoomed in past what the camera images: everything on the chart is
        # inside the camera's field, so there is nothing to mark.
        assert frustum_box(RENDER_SIZE, 10.2, 13.71) is None

    def test_a_camera_matching_the_chart_has_no_frustum(self):
        # A box within a pixel of the chart edge shades nothing and excludes
        # nothing; drawing it would just be a border.
        assert frustum_box(RENDER_SIZE, 10.2, 10.2) is None
        assert frustum_box(RENDER_SIZE, 10.2, 10.15) is None


@pytest.mark.unit
class TestFrustumGeometry:
    def test_the_box_is_centred_and_scales_with_the_camera_field(self):
        left, top, right, bottom = frustum_box(RENDER_SIZE, 20.0, 10.0)

        width, height = RENDER_SIZE
        # Half the chart's field of view, so half its width, centred.
        assert right - left == pytest.approx(width / 2)
        assert bottom - top == pytest.approx(height / 2)
        assert left == pytest.approx(width - right)
        assert top == pytest.approx(height - bottom)

    def test_a_narrower_camera_gives_a_smaller_box(self):
        wide = frustum_box(RENDER_SIZE, 30.0, 13.71)
        narrow = frustum_box(RENDER_SIZE, 30.0, 10.33)
        assert narrow[2] - narrow[0] < wide[2] - wide[0]

    def test_the_shipped_trains_all_produce_a_box_at_chart_zoom(self):
        # Every sensor on its shipped lens images less than the 20 degree
        # chart step, so each has a frustum to mark -- and a different one,
        # which is the whole reason it cannot be a constant.
        widths = set()
        for camera_type in ("imx296", "imx462", "imx290", "hq"):
            box = frustum_box(
                RENDER_SIZE, 20.0, build_optical_train(camera_type).fov_degrees
            )
            assert box is not None, camera_type
            widths.add(round(box[2] - box[0], 3))
        assert len(widths) > 1
