"""Unit tests for the raw, four-star Focus screen renderer."""

import time
from collections import deque
from itertools import cycle
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image, ImageDraw

from PiFinder.ui import preview as preview_module
from PiFinder.displays import DisplayBase, Layout176, Layout320
from PiFinder.focus import Blob, FocusResult
from PiFinder.ui.preview import (
    DISPLAY_RAW,
    DISPLAY_SINGLE,
    DISPLAY_STARS,
    DISPLAY_STATS,
    FOCUS_NOMINAL_ZOOM,
    UIPreview,
    focus_crop_size,
)


def _blob(*, x=256.0, y=256.0, peak=200.0, extent=8) -> Blob:
    return Blob(
        x=x,
        y=y,
        peak=peak,
        background=10.0,
        extent=extent,
        size_px=max(2, extent * extent),
    )


@pytest.mark.unit
def test_focused_star_uses_calculated_ten_x_crop():
    crop_w, crop_h = focus_crop_size((512, 512), (64, 64), blob_extent=8)
    assert (crop_w, crop_h) == (26, 26)
    effective_zoom = 512 / (2 * crop_h)
    assert effective_zoom == pytest.approx(FOCUS_NOMINAL_ZOOM, rel=0.03)


@pytest.mark.unit
def test_defocused_star_reduces_zoom_instead_of_clipping():
    focused = focus_crop_size((512, 512), (64, 64), blob_extent=8)
    defocused = focus_crop_size((512, 512), (64, 64), blob_extent=40)
    assert defocused[0] == defocused[1]
    assert defocused[0] > focused[0]
    assert defocused[0] >= 40 * 1.35


@pytest.mark.unit
def test_crop_matches_rectangular_tile_aspect_ratio():
    crop_w, crop_h = focus_crop_size((512, 512), (160, 120), blob_extent=8)
    assert crop_w / crop_h == pytest.approx(4 / 3, rel=0.03)


@pytest.mark.unit
def test_display_uses_four_brightest_visual_blobs():
    preview = object.__new__(UIPreview)
    preview.last_focus_result = FocusResult(
        median_hfd=8.0,
        n_used=4,
        background=10.0,
        peak=250.0,
        too_defocused=False,
        blobs=tuple(
            _blob(x=x, y=y, peak=peak, extent=extent)
            for x, y, peak, extent in (
                (100, 100, 250, 8),
                (120, 120, 245, 8),
                (400, 100, 240, 9),
                (100, 400, 230, 10),
                (400, 400, 220, 11),
            )
        ),
    )
    assert [blob.peak for blob in preview._display_blobs()] == [250, 245, 240, 230]


@pytest.mark.unit
@pytest.mark.parametrize("layout", (DisplayBase, Layout176, Layout320))
def test_quadrants_are_centered_below_title_bar_on_every_layout(layout):
    preview = object.__new__(UIPreview)
    preview.display_class = SimpleNamespace(
        resolution=layout.resolution,
        titlebar_height=layout.titlebar_height,
        resY=layout.resolution[1],
    )

    content_top = preview.display_class.titlebar_height + 1
    boxes = preview._tile_boxes()
    top_height = boxes[0][3] - boxes[0][1]
    bottom_height = boxes[2][3] - boxes[2][1]

    assert boxes[0][1] == content_top
    assert abs(top_height - bottom_height) <= 1
    assert (
        preview._focus_center()[1]
        == content_top + (preview.display_class.resY - content_top) // 2
    )


@pytest.mark.unit
def test_renderer_preserves_raw_luminance_values():
    preview = object.__new__(UIPreview)
    preview.focus_zoom = FOCUS_NOMINAL_ZOOM
    preview.display_class = SimpleNamespace(resolution=(128, 128), titlebar_height=17)
    preview.colors = SimpleNamespace(
        red_image=Image.new("RGB", (128, 128), (255, 0, 0))
    )
    preview.last_focus_result = FocusResult(
        median_hfd=8.0,
        n_used=1,
        background=0.0,
        peak=200.0,
        too_defocused=False,
        blobs=(_blob(x=128, y=128),),
    )

    # A discrete-valued frame makes any stretch, filtering, or interpolating
    # resize visible as newly invented values.
    raw = np.zeros((512, 512), dtype=np.uint8)
    raw[240:272, 240:272] = np.tile(
        np.array([20, 80, 140, 200], dtype=np.uint8), (32, 8)
    )
    rendered = np.asarray(preview._render_focus_tiles(Image.fromarray(raw)))

    assert set(np.unique(rendered[:, :, 0])) <= {0, 20, 80, 140, 200}
    assert np.all(rendered[:, :, 1:] == 0)


@pytest.mark.unit
def test_edge_star_crop_contains_only_source_frame_pixels():
    preview = object.__new__(UIPreview)
    preview.focus_zoom = FOCUS_NOMINAL_ZOOM
    preview.display_class = SimpleNamespace(resolution=(128, 128), titlebar_height=17)
    preview.colors = SimpleNamespace(
        red_image=Image.new("RGB", (128, 128), (255, 0, 0))
    )
    preview.last_focus_result = FocusResult(
        median_hfd=8.0,
        n_used=4,
        background=0.0,
        peak=240.0,
        too_defocused=False,
        blobs=(
            _blob(x=128, y=128, peak=240),
            _blob(x=384, y=128, peak=230),
            _blob(x=128, y=384, peak=220),
            _blob(x=511, y=511, peak=210),
        ),
    )

    rendered = np.asarray(
        preview._render_focus_tiles(
            Image.fromarray(np.full((512, 512), 73, dtype=np.uint8))
        )
    )

    content_top = preview.display_class.titlebar_height + 1
    assert np.all(rendered[:content_top, :, 0] == 0)
    assert np.all(rendered[content_top:, :, 0] == 73)
    assert np.all(rendered[:, :, 1:] == 0)


@pytest.mark.unit
def test_raw_renderer_preserves_raw_luminance_values():
    preview = object.__new__(UIPreview)
    preview.display_class = SimpleNamespace(resolution=(128, 128))
    preview.colors = SimpleNamespace(
        red_image=Image.new("RGB", (128, 128), (255, 0, 0))
    )
    raw = np.tile(np.array([0, 40, 120, 255], dtype=np.uint8), (512, 128))
    rendered = np.asarray(preview._render_raw_frame(Image.fromarray(raw)))
    assert set(np.unique(rendered[:, :, 0])) <= {0, 40, 120, 255}
    assert np.all(rendered[:, :, 1:] == 0)


@pytest.mark.unit
def test_single_star_renderer_preserves_brightest_raw_crop():
    preview = object.__new__(UIPreview)
    preview.focus_zoom = FOCUS_NOMINAL_ZOOM
    preview.display_class = SimpleNamespace(resolution=(128, 128))
    preview.colors = SimpleNamespace(
        red_image=Image.new("RGB", (128, 128), (255, 0, 0))
    )
    preview.last_focus_result = FocusResult(
        median_hfd=6.0,
        n_used=2,
        background=0.0,
        peak=220.0,
        too_defocused=False,
        blobs=(
            _blob(x=128, y=128, peak=220),
            _blob(x=384, y=384, peak=200),
        ),
    )
    raw = np.zeros((512, 512), dtype=np.uint8)
    raw[102:154, 102:154] = 73
    raw[358:410, 358:410] = 149

    rendered = np.asarray(preview._render_brightest_star(Image.fromarray(raw)))

    assert set(np.unique(rendered[:, :, 0])) <= {73}
    assert np.all(rendered[:, :, 1:] == 0)


@pytest.mark.unit
def test_focus_modes_follow_standard_square_cycle_order():
    assert UIPreview._display_mode_list == [
        DISPLAY_STARS,
        DISPLAY_RAW,
        DISPLAY_STATS,
        DISPLAY_SINGLE,
    ]

    preview = object.__new__(UIPreview)
    preview._display_mode_cycle = cycle(UIPreview._display_mode_list)
    preview.display_mode = next(preview._display_mode_cycle)
    redraws = []
    preview.update = lambda force=False: redraws.append(force)

    preview.key_square()
    assert preview.display_mode == DISPLAY_RAW
    preview.key_square()
    assert preview.display_mode == DISPLAY_STATS
    preview.key_square()
    assert preview.display_mode == DISPLAY_SINGLE
    preview.key_square()
    assert preview.display_mode == DISPLAY_STARS
    assert redraws == [True, True, True, True]


@pytest.mark.unit
def test_zoom_controls_apply_to_magnified_star_views_only():
    preview = object.__new__(UIPreview)
    preview.focus_zoom = FOCUS_NOMINAL_ZOOM
    preview.display_mode = DISPLAY_STARS
    redraws = []
    preview.update = lambda force=False: redraws.append(force)

    preview.key_plus()
    assert preview.focus_zoom == FOCUS_NOMINAL_ZOOM + 2

    preview.display_mode = DISPLAY_RAW
    preview.key_minus()
    assert preview.focus_zoom == FOCUS_NOMINAL_ZOOM + 2
    preview.display_mode = DISPLAY_SINGLE
    preview.key_minus()
    assert preview.focus_zoom == FOCUS_NOMINAL_ZOOM
    assert redraws == [True, True]


@pytest.mark.unit
def test_single_star_readout_stays_in_translucent_lower_third():
    preview = object.__new__(UIPreview)
    preview.display_class = DisplayBase()
    preview.colors = preview.display_class.colors
    preview.fonts = preview.display_class.fonts
    preview.screen = Image.new("RGB", preview.display_class.resolution, (100, 0, 0))
    preview.draw = ImageDraw.Draw(preview.screen, mode="RGBA")
    preview.last_focus_result = FocusResult(
        median_hfd=5.0,
        n_used=1,
        background=10.0,
        peak=220.0,
        too_defocused=False,
    )
    preview.focus_history = deque()

    preview._draw_single_focus_overlay()

    pixels = np.asarray(preview.screen)
    overlay_top = int(np.ceil(preview.display_class.resY * 2 / 3))
    assert np.all(pixels[:overlay_top, :, 0] == 100)
    assert np.any((pixels[overlay_top:, :, 0] > 0) & (pixels[overlay_top:, :, 0] < 100))


@pytest.mark.unit
def test_hfd_history_runs_on_both_sides_of_center_readout():
    preview = object.__new__(UIPreview)
    preview.display_class = DisplayBase()
    preview.colors = preview.display_class.colors
    preview.fonts = preview.display_class.fonts
    preview.screen = Image.new("RGB", preview.display_class.resolution)
    preview.draw = ImageDraw.Draw(preview.screen, mode="RGBA")
    preview.last_focus_result = FocusResult(
        median_hfd=7.5,
        n_used=4,
        background=20.0,
        peak=220.0,
        too_defocused=False,
    )
    now = time.time()
    preview.focus_history = deque(
        [
            (now - 9, 12.0),
            (now - 7, 10.0),
            (now - 3, 8.5),
            (now - 1, 7.5),
        ]
    )

    preview._draw_focus_overlay()

    red = np.asarray(preview.screen)[:, :, 0]
    center_y = preview._focus_center()[1]
    band = slice(center_y - 12, center_y + 13)
    assert np.any(red[band, :45] == 255)
    assert np.any(red[band, 83:] == 255)


@pytest.mark.unit
def test_hfd_signal_survives_gap_and_reappears_on_first_measurement(monkeypatch):
    preview = object.__new__(UIPreview)
    preview.display_class = DisplayBase()
    preview.colors = preview.display_class.colors
    preview.screen = Image.new("RGB", preview.display_class.resolution)
    preview.draw = ImageDraw.Draw(preview.screen)
    start = time.time()
    preview.focus_history = deque([(start, 6.0)])
    preview._record_focus_sample(None)
    assert list(preview.focus_history) == [(start, 6.0)]

    monkeypatch.setattr(preview_module.time, "time", lambda: start + 11)
    preview._record_focus_sample(4.5)
    assert list(preview.focus_history) == [(start + 11, 4.5)]

    preview._draw_focus_history(preview.display_class.centerY, 52, 76)

    red = np.asarray(preview.screen)[:, :, 0]
    assert np.count_nonzero(red[:, 76:] == 255) >= 2


@pytest.mark.unit
def test_hfd_signal_recedes_when_no_new_measurements_arrive(monkeypatch):
    preview = object.__new__(UIPreview)
    preview.display_class = DisplayBase()
    preview.colors = preview.display_class.colors
    preview.focus_history = deque(
        [(92.0, 5.0), (94.0, 5.0), (96.0, 5.0), (98.0, 5.0), (100.0, 5.0)]
    )

    def rightmost_signal(now: float) -> int:
        monkeypatch.setattr(preview_module.time, "time", lambda: now)
        preview.screen = Image.new("RGB", preview.display_class.resolution)
        preview.draw = ImageDraw.Draw(preview.screen)
        preview._draw_focus_history(preview.display_class.centerY, 52, 76)
        _y, x = np.where(np.asarray(preview.screen)[:, :, 0] == 255)
        return int(x.max())

    assert rightmost_signal(105.0) < rightmost_signal(100.0)


@pytest.mark.unit
def test_stats_renderer_draws_metrics_and_histogram():
    preview = object.__new__(UIPreview)
    preview.display_class = DisplayBase()
    preview.colors = preview.display_class.colors
    preview.fonts = preview.display_class.fonts
    preview.screen = Image.new("RGB", preview.display_class.resolution)
    preview.draw = ImageDraw.Draw(preview.screen, mode="RGBA")
    preview.config_object = SimpleNamespace(get_option=lambda name: "auto")
    preview.last_focus_result = FocusResult(
        median_hfd=8.2,
        median_fwhm=6.4,
        n_used=4,
        background=20.0,
        peak=220.0,
        too_defocused=False,
        blobs=tuple(_blob(peak=220 - index * 10) for index in range(6)),
    )
    raw = np.tile(np.arange(256, dtype=np.uint8), (512, 2))

    preview._draw_stats(raw, {"exposure_time": 500_000, "gain": 2.0})

    assert preview.screen.getbbox() is not None
    # The standard title bar is painted after this renderer; stats must not
    # place the large HFD glyph underneath it.
    pixels = np.asarray(preview.screen)
    assert pixels[: preview.display_class.titlebar_height].max() == 0
