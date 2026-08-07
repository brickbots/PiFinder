#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Unit tests for the SEP full-frame detection path and its coordinate
mapping into the production solver frame.

The rotation conventions are pinned against PIL's Image.rotate (what
camera_interface stage 5 actually uses) so the SEP solve produces the
same Roll / target-pixel semantics as the production path.
"""

import numpy as np
import pytest
from PIL import Image

from PiFinder import solver_frame_map as sfm

sep = pytest.importorskip("sep")

from PiFinder import sep_detect  # noqa: E402


def _synthetic_frame(stars, shape=(540, 960), bg=1200.0, peak=400.0):
    """Raw-like uint16 mosaic with a gradient background and gaussian stars.

    The checkerboard gain below is a worst-case robustness input: a
    mono sensor has no phase response, so field frames are easier than
    this fixture.
    """
    h, w = shape
    yy, xx = np.mgrid[0:h, 0:w]
    frame = bg + 300.0 * (xx / w) + np.random.default_rng(3).normal(0, 8, (h, w))
    bayer = np.ones((h, w))
    bayer[::2, ::2] = 1.1
    bayer[1::2, 1::2] = 0.92
    frame *= bayer
    for sy, sx in stars:
        frame += peak * np.exp(-((xx - sx) ** 2 + (yy - sy) ** 2) / (2 * 1.5**2))
    return np.clip(frame, 0, 4095).astype(np.uint16)


@pytest.mark.unit
class TestSepDetect:
    def test_detects_planted_stars_in_full_frame_coords(self):
        stars = [(100, 200), (300, 700), (450, 120), (250, 480)]
        frame = _synthetic_frame(stars)
        result = sep_detect.detect_stars(frame, sigma=4.0)
        assert result is not None
        assert len(result.centroids) >= len(stars)
        for sy, sx in stars:
            d = np.hypot(result.centroids[:, 0] - sy, result.centroids[:, 1] - sx)
            # full-frame coordinates: within 2 px of the planted position
            assert d.min() < 2.0
        # flux-descending order
        assert np.all(np.diff(result.fluxes) <= 0)

    def test_max_stars_cap(self):
        stars = [(50 + 40 * i, 60 + 70 * (i % 12)) for i in range(30)]
        frame = _synthetic_frame(stars)
        result = sep_detect.detect_stars(frame, sigma=4.0, max_stars=10)
        assert result is not None
        assert len(result.centroids) <= 10

    def test_unusable_frame_returns_none(self):
        assert sep_detect.detect_stars(np.zeros((4, 4), dtype=np.uint16)) is None
        assert sep_detect.detect_stars(np.zeros((10, 10, 3), dtype=np.uint16)) is None

    def test_bin2x2_geometry(self):
        arr = np.arange(16, dtype=np.uint16).reshape(4, 4)
        binned = sep_detect.bin2x2(arr)
        assert binned.shape == (2, 2)
        assert binned[0, 0] == pytest.approx((0 + 1 + 4 + 5) / 4)

    def test_edge_margin_drops_border_detections(self):
        """Vignetted-border artifacts are excluded (field lesson: on a
        saturated-interior frame every 'detection' hugged the frame edge)."""
        stars = [(20, 300), (300, 20), (270, 480)]  # two in the border zone
        frame = _synthetic_frame(stars)
        result = sep_detect.detect_stars(frame, sigma=4.0, edge_margin_px=48)
        assert result is not None
        for y, x in result.centroids:
            assert 48 <= y < 540 - 48
            assert 48 <= x < 960 - 48
        # the interior star survives
        d = np.hypot(result.centroids[:, 0] - 270, result.centroids[:, 1] - 480)
        assert d.min() < 2.0

    def test_saturated_interior_returns_zero_detections(self):
        frame = np.full((540, 960), 4095, dtype=np.uint16)
        # borders darker (vignette) so naive extraction would find edges
        frame[:40, :] = 2000
        frame[-40:, :] = 2000
        result = sep_detect.detect_stars(frame, sigma=3.5, saturation_level=4095)
        assert result is not None
        assert len(result.centroids) == 0


@pytest.mark.unit
class TestWarmPixelMap:
    """Static single-pixel defects dominated SEP counts on empty sky
    (2026-07-28 bench); the map removes them without touching stars."""

    def test_excess_isolates_single_pixel_spike(self):
        frame = np.full((64, 64), 1000.0, dtype=np.float32)
        frame[20, 30] += 80.0  # warm pixel
        excess = sep_detect.warm_pixel_excess(frame)
        assert excess[20, 30] == pytest.approx(80.0)
        # neighbours of the spike are not implicated
        assert abs(excess[22, 30]) < 1.0
        assert abs(excess[20, 32]) < 1.0

    def test_build_map_keeps_static_defects_drops_moving_star(self):
        rng = np.random.default_rng(7)
        warm = [(20, 30), (100, 200)]
        frames = []
        for i in range(6):
            f = 1000.0 + rng.normal(0, 5, (128, 256))
            for wy, wx in warm:
                f[wy, wx] += 60.0
            f[50, 40 + 20 * i] += 300.0  # bright star drifting with the sky
            frames.append(f.astype(np.uint16))
        pts = sep_detect.build_warm_pixel_map(frames, min_excess_adu=25.0)
        assert {tuple(p) for p in pts} == set(warm)

    def test_build_map_empty_input(self):
        assert len(sep_detect.build_warm_pixel_map([])) == 0

    def test_detect_stars_masks_mapped_position_and_counts(self):
        stars = [(100, 200), (300, 700), (450, 120), (250, 480)]
        frame = _synthetic_frame(stars)
        warm_map = np.array([[300, 700]])  # mask one planted "star"
        result = sep_detect.detect_stars(frame, sigma=4.0, warm_pixel_map=warm_map)
        assert result is not None
        assert result.masked_count >= 1
        d = np.hypot(result.centroids[:, 0] - 300, result.centroids[:, 1] - 700)
        assert len(d) == 0 or d.min() > 4.0
        # the unmasked stars all survive
        for sy, sx in [(100, 200), (450, 120), (250, 480)]:
            d = np.hypot(result.centroids[:, 0] - sy, result.centroids[:, 1] - sx)
            assert d.min() < 2.0

    def test_detect_stars_no_map_reports_zero_masked(self):
        frame = _synthetic_frame([(100, 200)])
        result = sep_detect.detect_stars(frame, sigma=4.0)
        assert result is not None
        assert result.masked_count == 0


@pytest.mark.unit
class TestRotationConvention:
    """rotate_centroids must match what PIL does to the image."""

    @pytest.mark.parametrize("angle", [0, 90, 180, 270])
    def test_quarter_turns_match_pil_on_square(self, angle):
        h = w = 64
        y0, x0 = 10, 45
        img = np.zeros((h, w), dtype=np.uint8)
        img[y0, x0] = 255
        rotated = np.asarray(Image.fromarray(img).rotate(angle))
        expect = np.unravel_index(rotated.argmax(), rotated.shape)
        got, (nh, nw) = sfm.rotate_centroids(
            np.array([[y0, x0]], dtype=float), (h, w), angle
        )
        assert (round(got[0, 0]), round(got[0, 1])) == expect
        assert (nh, nw) == (h, w)

    def test_quarter_turn_swaps_rect_canvas(self):
        got, (nh, nw) = sfm.rotate_centroids(np.array([[0.0, 0.0]]), (1080, 1920), 90)
        assert (nh, nw) == (1920, 1080)
        # top-left pixel goes to bottom-left under CCW
        assert got[0, 0] == pytest.approx(1919.0)
        assert got[0, 1] == pytest.approx(0.0)

    def test_arbitrary_angle_matches_pil_blob(self):
        h = w = 101
        y0, x0 = 30, 70
        img = np.zeros((h, w), dtype=np.float32)
        yy, xx = np.mgrid[0:h, 0:w]
        img += 255 * np.exp(-((xx - x0) ** 2 + (yy - y0) ** 2) / (2 * 2.0**2))
        rotated = np.asarray(
            Image.fromarray(img.astype(np.uint8)).rotate(30, resample=Image.BILINEAR)
        )
        py, px = np.unravel_index(rotated.argmax(), rotated.shape)
        got, _ = sfm.rotate_centroids(np.array([[y0, x0]], dtype=float), (h, w), 30)
        assert got[0, 0] == pytest.approx(py, abs=1.5)
        assert got[0, 1] == pytest.approx(px, abs=1.5)


@pytest.mark.unit
class TestTargetPixelMapping:
    def test_center_is_invariant(self):
        # (255.5, 255.5) is the 512-frame centre -> maps to the canvas centre
        y, x = sfm.map_target_pixel_to_frame((255.5, 255.5), (1920, 1080), 980)
        assert y == pytest.approx((1920 - 1) / 2)
        assert x == pytest.approx((1080 - 1) / 2)

    def test_offset_scales_by_crop_ratio(self):
        # 100 px right of centre in 512-space = 100 * 980/512 sensor px
        y, x = sfm.map_target_pixel_to_frame((255.5, 355.5), (1080, 1920), 980)
        assert y == pytest.approx((1080 - 1) / 2)
        assert x == pytest.approx((1920 - 1) / 2 + 100 * 980 / 512)

    def test_fov_scales_with_width(self):
        assert sfm.fov_estimate_deg(980, 980) == pytest.approx(12.0)
        assert sfm.fov_estimate_deg(1920, 980) == pytest.approx(23.51, abs=0.01)

    def test_stage5_rotation_matches_camera_interface_rules(self):
        from PiFinder.camera_interface import SCREEN_ROTATE_AMOUNTS

        # camera_rotation overrides the screen_direction map entirely
        assert sfm.stage5_rotation_deg("right", 45) == 315.0
        assert sfm.stage5_rotation_deg(None, 0) == 0.0
        # every mapped variant, plus the documented 270 fallback
        for direction, rotation in SCREEN_ROTATE_AMOUNTS.items():
            assert sfm.stage5_rotation_deg(direction, None) == float(rotation)
        assert sfm.stage5_rotation_deg("no_such_variant", None) == 270.0
