"""Unit tests for the raw, four-star Focus screen renderer."""

import time
from collections import deque
from itertools import cycle
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image, ImageDraw

from PiFinder.ui import preview as preview_module
from PiFinder.displays import (
    DisplayBase,
    DisplayHeadless,
    DisplayHeadless176,
    DisplayHeadless320,
    Layout176,
    Layout320,
)
from PiFinder.focus import Blob, FocusResult
from PiFinder.ui.preview import (
    DISPLAY_IMAGE,
    DISPLAY_SINGLE,
    DISPLAY_STARS,
    DISPLAY_STATS,
    FOCUS_DEFAULT_EXPOSURE,
    FOCUS_EXPOSURE_LADDER,
    FOCUS_NOMINAL_ZOOM,
    UIPreview,
    focus_crop_size,
    step_exposure,
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
def test_solved_hip_ids_restore_stars_to_their_existing_slots():
    preview = object.__new__(UIPreview)
    # Geometry temporarily swapped these two known stars.
    hip_b_blob = _blob(x=400, y=300, peak=230)
    hip_a_blob = _blob(x=100, y=80, peak=240)
    preview._tracked_focus_blobs = (hip_b_blob, hip_a_blob)
    preview._focus_slot_catalog_ids = (32349, 71683)
    preview._last_focus_catalog_time = 0.0
    solution = SimpleNamespace(
        last_solve_success=42.0,
        matched_centroids=[(300.0, 400.0), (80.0, 100.0)],
        matched_catID=[71683, 32349],
    )
    preview.shared_state = SimpleNamespace(solution=lambda: solution)

    preview._adopt_solved_catalog_ids(42.0)

    assert preview._tracked_focus_blobs == (hip_a_blob, hip_b_blob)
    assert preview._focus_slot_catalog_ids == (32349, 71683)


@pytest.mark.unit
def test_replacement_star_does_not_inherit_departed_hip_id(monkeypatch):
    preview = object.__new__(UIPreview)
    preview._tracked_focus_blobs = (
        _blob(x=80, y=90),
        _blob(x=400, y=100),
        _blob(x=100, y=390),
        _blob(x=410, y=400),
    )
    preview._focus_slot_catalog_ids = (1, 2, 3, 4)
    preview.focus_history = deque()
    replacement = _blob(x=250, y=250)
    result = FocusResult(
        median_hfd=5.0,
        n_used=4,
        background=10.0,
        peak=240.0,
        too_defocused=False,
        blobs=(
            _blob(x=110, y=70),
            _blob(x=430, y=80),
            _blob(x=440, y=380),
            replacement,
        ),
    )
    monkeypatch.setattr(preview_module.focus, "focus_hfd", lambda _image: result)

    preview._measure_focus(np.zeros((512, 512), dtype=np.uint8), record_history=False)

    assert preview._focus_slot_catalog_ids == (1, 2, None, 4)


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
    # The status bar is reserved out of the camera area, so the quadrants
    # centre on what is left rather than on the full panel height.
    assert (
        preview._focus_center()[1]
        == content_top + (preview._content_bottom() - content_top) // 2
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
    content_bottom = preview._content_bottom()
    assert np.all(rendered[:content_top, :, 0] == 0)
    assert np.all(rendered[content_top:content_bottom, :, 0] == 73)
    # Reserved for the status bar, so no camera pixel lands here.
    assert np.all(rendered[content_bottom:, :, 0] == 0)
    assert np.all(rendered[:, :, 1:] == 0)


@pytest.mark.unit
def test_image_renderer_uses_original_display_autocontrast():
    preview = object.__new__(UIPreview)
    preview.display_class = SimpleNamespace(resolution=(128, 128), titlebar_height=17)
    preview.colors = SimpleNamespace(
        red_image=Image.new("RGB", (128, 128), (255, 0, 0))
    )
    raw = np.tile(
        np.repeat(np.array([20, 70, 120, 200], dtype=np.uint8), 128), (512, 1)
    )
    rendered = np.asarray(preview._render_image_frame(Image.fromarray(raw)))
    assert set(np.unique(rendered[:, :, 0])) == {0, 70, 141, 255}
    assert np.all(rendered[:, :, 1:] == 0)


@pytest.mark.unit
def test_single_star_renderer_preserves_brightest_raw_crop(monkeypatch):
    preview = object.__new__(UIPreview)
    preview.focus_zoom = FOCUS_NOMINAL_ZOOM
    preview.display_class = SimpleNamespace(resolution=(128, 128), titlebar_height=17)
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

    nominal_zooms = []
    original_focus_crop_size = preview_module.focus_crop_size

    def recording_focus_crop_size(*args, **kwargs):
        nominal_zooms.append(args[3])
        return original_focus_crop_size(*args, **kwargs)

    monkeypatch.setattr(preview_module, "focus_crop_size", recording_focus_crop_size)
    rendered = np.asarray(preview._render_brightest_star(Image.fromarray(raw)))

    assert set(np.unique(rendered[:, :, 0])) <= {73}
    assert np.all(rendered[:, :, 1:] == 0)
    assert nominal_zooms == [FOCUS_NOMINAL_ZOOM]


@pytest.mark.unit
def test_focus_modes_follow_standard_square_cycle_order():
    assert UIPreview._display_mode_list == [
        DISPLAY_STARS,
        DISPLAY_SINGLE,
        DISPLAY_IMAGE,
        DISPLAY_STATS,
    ]

    preview = object.__new__(UIPreview)
    preview._display_mode_cycle = cycle(UIPreview._display_mode_list)
    preview.display_mode = next(preview._display_mode_cycle)
    redraws = []
    preview.update = lambda force=False: redraws.append(force)

    preview.key_square()
    assert preview.display_mode == DISPLAY_SINGLE
    preview.key_square()
    assert preview.display_mode == DISPLAY_IMAGE
    preview.key_square()
    assert preview.display_mode == DISPLAY_STATS
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

    preview.display_mode = DISPLAY_IMAGE
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
    # Lower third of the camera area, which now stops above the status bar.
    content_bottom = preview._content_bottom()
    overlay_top = int(np.ceil(content_bottom * 2 / 3))
    assert np.all(pixels[:overlay_top, :, 0] == 100)
    band = pixels[overlay_top:content_bottom, :, 0]
    assert np.any((band > 0) & (band < 100))
    # The overlay must not reach into the reserved status bar.
    assert np.all(pixels[content_bottom:, :, 0] == 100)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (None, "?.?"),
        (
            FocusResult(
                median_hfd=None,
                n_used=0,
                background=20.0,
                peak=None,
                too_defocused=False,
            ),
            "?.?",
        ),
        (
            FocusResult(
                median_hfd=None,
                n_used=0,
                background=20.0,
                peak=255.0,
                too_defocused=True,
            ),
            "?.?",
        ),
        (
            FocusResult(
                median_hfd=5.25,
                n_used=1,
                background=20.0,
                peak=220.0,
                too_defocused=False,
            ),
            "5.2",
        ),
    ],
)
def test_focus_readout_uses_question_marks_when_hfd_is_unavailable(result, expected):
    preview = object.__new__(UIPreview)
    preview.last_focus_result = result

    assert preview._focus_readout_text() == expected
    assert ">50" not in preview._focus_readout_text()


@pytest.mark.unit
def test_history_gap_has_equal_blank_pixels_from_rendered_outline(monkeypatch):
    preview = object.__new__(UIPreview)
    preview.display_class = DisplayBase()
    preview.colors = preview.display_class.colors
    preview.fonts = preview.display_class.fonts
    preview.screen = Image.new("RGB", preview.display_class.resolution)
    preview.draw = ImageDraw.Draw(preview.screen, mode="RGBA")
    preview.last_focus_result = FocusResult(
        median_hfd=6.1,
        n_used=4,
        background=20.0,
        peak=220.0,
        too_defocused=False,
    )
    captured_gap = []
    monkeypatch.setattr(
        preview,
        "_draw_focus_history",
        lambda center_y, gap_left, gap_right: captured_gap.append(
            (center_y, gap_left, gap_right)
        ),
    )

    preview._draw_focus_overlay()

    center = preview._focus_center()
    mask = Image.new("1", preview.display_class.resolution)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.text(
        center,
        "6.1",
        font=preview.fonts.large.font,
        fill=1,
        anchor="mm",
        stroke_width=1,
        stroke_fill=1,
    )
    ink_box = mask.getbbox()
    _, gap_left, gap_right = captured_gap[0]
    left_blank_pixels = ink_box[0] - gap_left - 1
    right_blank_pixels = gap_right - ink_box[2]
    assert left_blank_pixels == right_blank_pixels == 3


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

    at_last_measurement = rightmost_signal(100.0)
    assert rightmost_signal(105.0) < at_last_measurement


@pytest.mark.unit
def test_hfd_signal_disappears_after_history_window(monkeypatch):
    preview = object.__new__(UIPreview)
    preview.display_class = DisplayBase()
    preview.colors = preview.display_class.colors
    preview.screen = Image.new("RGB", preview.display_class.resolution)
    preview.draw = ImageDraw.Draw(preview.screen)
    preview.focus_history = deque(
        [(92.0, 5.0), (94.0, 5.0), (96.0, 5.0), (98.0, 5.0), (100.0, 5.0)]
    )
    monkeypatch.setattr(preview_module.time, "time", lambda: 111.0)

    preview._draw_focus_history(preview.display_class.centerY, 52, 76)

    assert not preview.focus_history
    assert np.asarray(preview.screen).max() == 0


@pytest.mark.unit
def test_stats_renderer_draws_metrics_and_histogram():
    preview = object.__new__(UIPreview)
    preview.display_class = DisplayBase()
    preview.colors = preview.display_class.colors
    preview.fonts = preview.display_class.fonts
    preview.screen = Image.new("RGB", preview.display_class.resolution)
    preview.draw = ImageDraw.Draw(preview.screen, mode="RGBA")
    preview.config_object = SimpleNamespace(get_option=lambda name: "auto")
    preview._exposure_hold_active = False
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

    top = preview.display_class.titlebar_height + 4
    stats_y = top + preview.fonts.huge.height
    plots_top = stats_y + 2 * (preview.fonts.small.height + 1) + 1
    label_box = preview.draw.textbbox(
        (2, plots_top), "RAW HIST", font=preview.fonts.small.font
    )
    assert pixels[label_box[3] : label_box[3] + 2].max() == 0


@pytest.mark.unit
def test_stats_hfd_uses_question_marks_when_measurement_is_unavailable(monkeypatch):
    preview = object.__new__(UIPreview)
    preview.display_class = DisplayBase()
    preview.colors = preview.display_class.colors
    preview.fonts = preview.display_class.fonts
    preview.screen = Image.new("RGB", preview.display_class.resolution)
    preview.draw = ImageDraw.Draw(preview.screen, mode="RGBA")
    preview.config_object = SimpleNamespace(get_option=lambda name: "auto")
    preview._exposure_hold_active = False
    preview.last_focus_result = None
    drawn_text = []
    original_text = preview.draw.text

    def recording_text(xy, text, *args, **kwargs):
        drawn_text.append(text)
        return original_text(xy, text, *args, **kwargs)

    monkeypatch.setattr(preview.draw, "text", recording_text)
    preview._draw_stats(
        np.zeros((512, 512), dtype=np.uint8),
        {"exposure_time": None, "gain": None},
    )

    assert "?.?" in drawn_text
    assert ">50" not in drawn_text


def _hold_preview(*, camera_exp="auto", exposure_time=437_000):
    """A UIPreview with just enough wired up to exercise the exposure hold."""
    preview = object.__new__(UIPreview)
    preview._exposure_hold_active = False
    preview._saved_camera_exp = None
    preview._held_exposure_us = None
    preview.config_object = SimpleNamespace(get_option=lambda _name: camera_exp)
    preview.shared_state = SimpleNamespace(
        last_image_metadata=lambda: {"exposure_time": exposure_time}
    )
    preview.camera_commands = []
    preview.command_queues = {
        "camera": SimpleNamespace(put=preview.camera_commands.append)
    }
    return preview


@pytest.mark.unit
@pytest.mark.parametrize(
    ("current", "direction", "expected"),
    [
        # An auto-settled exposure sits between rungs; one nudge lands on one.
        (437_000, -1, 400_000),
        (437_000, 1, 800_000),
        # From a rung, step to its neighbour rather than standing still.
        (400_000, 1, 800_000),
        (400_000, -1, 200_000),
        # The ladder ends hold instead of wrapping or clamping the other way.
        (1_000_000, 1, 1_000_000),
        (25_000, -1, 25_000),
        # An exposure left outside the ladder is walked back into it.
        (1_500_000, -1, 1_000_000),
        (10_000, 1, 25_000),
    ],
)
def test_exposure_steps_land_on_camera_exposure_menu_rungs(
    current, direction, expected
):
    assert step_exposure(current, direction) == expected


@pytest.mark.unit
def test_focus_exposure_ladder_matches_the_camera_exposure_menu():
    """The Focus screen must only offer exposures the menu can also set."""
    import PiFinder.i18n  # noqa: F401
    from PiFinder.ui import menu_structure

    def find_camera_exposure(node):
        if isinstance(node, dict):
            if node.get("label") == "camera_exposure":
                return node
            for child in node.get("items", []):
                found = find_camera_exposure(child)
                if found is not None:
                    return found
        return None

    menu = find_camera_exposure(menu_structure.pifinder_menu)
    assert menu is not None, "Camera Exp menu not found"
    menu_exposures = tuple(
        item["value"] for item in menu["items"] if item["value"] != "auto"
    )
    assert menu_exposures == FOCUS_EXPOSURE_LADDER


@pytest.mark.unit
def test_entering_focus_holds_the_exposure_auto_exposure_settled_on():
    preview = _hold_preview(camera_exp="auto", exposure_time=437_000)

    preview._begin_exposure_hold()

    # Transient, so the saved "auto" setting survives to be restored on exit.
    assert preview.camera_commands == ["set_exp_transient:437000"]
    assert preview._exposure_hold_active
    assert preview._held_exposure_us == 437_000
    assert preview._saved_camera_exp == "auto"


@pytest.mark.unit
def test_entering_focus_prefers_a_chosen_exposure_over_stale_frame_metadata():
    """The camera process may not have applied a just-selected exposure yet."""
    preview = _hold_preview(camera_exp=200_000, exposure_time=437_000)

    preview._begin_exposure_hold()

    assert preview.camera_commands == ["set_exp_transient:200000"]
    assert preview._held_exposure_us == 200_000


@pytest.mark.unit
def test_entering_focus_without_a_known_exposure_falls_back_to_the_default():
    preview = _hold_preview(camera_exp="auto", exposure_time=None)

    preview._begin_exposure_hold()

    assert preview.camera_commands == [f"set_exp_transient:{FOCUS_DEFAULT_EXPOSURE}"]


@pytest.mark.unit
def test_leaving_focus_hands_auto_exposure_back_exactly_once():
    """MenuManager calls inactive() twice on a LEFT back-out."""
    preview = _hold_preview(camera_exp="auto")
    preview._begin_exposure_hold()
    preview.camera_commands.clear()

    preview.inactive()
    preview.inactive()

    assert preview.camera_commands == ["set_exp:auto"]
    assert not preview._exposure_hold_active


@pytest.mark.unit
def test_leaving_focus_restores_a_manual_exposure_without_rewriting_it():
    preview = _hold_preview(camera_exp=200_000)
    preview._begin_exposure_hold()
    preview._nudge_exposure = lambda direction: None
    preview.update = lambda force=False: None
    preview.camera_commands.clear()

    preview.inactive()

    # set_exp_transient, not set_exp: restoring must not persist camera_exp.
    assert preview.camera_commands == ["set_exp_transient:200000"]


@pytest.mark.unit
def test_leaving_focus_before_a_hold_started_touches_nothing():
    preview = _hold_preview()

    preview.inactive()

    assert preview.camera_commands == []


@pytest.mark.unit
def test_arrow_keys_nudge_the_held_exposure_along_the_ladder():
    preview = _hold_preview(camera_exp="auto", exposure_time=437_000)
    preview._begin_exposure_hold()
    redraws = []
    preview.update = lambda force=False: redraws.append(force)
    preview.camera_commands.clear()

    preview.key_down()
    assert preview._held_exposure_us == 400_000
    preview.key_down()
    assert preview._held_exposure_us == 200_000
    preview.key_up()
    assert preview._held_exposure_us == 400_000

    assert preview.camera_commands == [
        "set_exp_transient:400000",
        "set_exp_transient:200000",
        "set_exp_transient:400000",
    ]
    assert redraws == [True, True, True]


@pytest.mark.unit
def test_nudging_past_the_end_of_the_ladder_holds_and_sends_nothing():
    preview = _hold_preview(camera_exp=1_000_000)
    preview._begin_exposure_hold()
    preview.update = lambda force=False: None
    preview.camera_commands.clear()

    preview.key_up()

    assert preview._held_exposure_us == 1_000_000
    assert preview.camera_commands == []


@pytest.mark.unit
def test_stats_reports_a_held_exposure_as_hold_not_the_saved_setting(monkeypatch):
    preview = object.__new__(UIPreview)
    preview.display_class = DisplayBase()
    preview.colors = preview.display_class.colors
    preview.fonts = preview.display_class.fonts
    preview.screen = Image.new("RGB", preview.display_class.resolution)
    preview.draw = ImageDraw.Draw(preview.screen, mode="RGBA")
    # The saved setting still reads "auto" throughout the hold.
    preview.config_object = SimpleNamespace(get_option=lambda _name: "auto")
    preview._exposure_hold_active = True
    preview.last_focus_result = None
    drawn_text = []
    original_text = preview.draw.text

    def recording_text(xy, text, *args, **kwargs):
        drawn_text.append(text)
        return original_text(xy, text, *args, **kwargs)

    monkeypatch.setattr(preview.draw, "text", recording_text)
    preview._draw_stats(
        np.zeros((512, 512), dtype=np.uint8),
        {"exposure_time": 400_000, "gain": 1.0},
    )

    assert any("HOLD 0.4s" in text for text in drawn_text)
    assert not any("AUTO" in text for text in drawn_text)


def _bar_preview(display_class, display_mode, camera_exp=400_000):
    preview = _hold_preview(camera_exp=camera_exp)
    preview.display_class = display_class
    preview.colors = display_class.colors
    preview.fonts = display_class.fonts
    preview.display_mode = display_mode
    preview.screen = Image.new("RGB", display_class.resolution)
    preview.draw = ImageDraw.Draw(preview.screen, mode="RGBA")
    return preview


@pytest.mark.unit
def test_status_bar_persists_on_the_star_views(monkeypatch):
    """The bar is standing, not a flash: it must not time out."""
    preview = _bar_preview(DisplayBase(), DISPLAY_STARS)
    monkeypatch.setattr(preview_module.time, "time", lambda: 100.0)
    preview._begin_exposure_hold()

    def rendered(now: float) -> int:
        monkeypatch.setattr(preview_module.time, "time", lambda: now)
        preview.screen = Image.new("RGB", preview.display_class.resolution)
        preview.draw = ImageDraw.Draw(preview.screen, mode="RGBA")
        preview._draw_status_bar()
        return int(np.count_nonzero(np.asarray(preview.screen)))

    assert rendered(100.5) > 0
    # Far past any old flash deadline, and still drawn.
    assert rendered(100.0 + 3600.0) > 0


@pytest.mark.unit
def test_status_bar_carries_the_held_exposure_and_the_keys(monkeypatch):
    preview = _bar_preview(DisplayBase(), DISPLAY_STARS)
    monkeypatch.setattr(preview_module.time, "time", lambda: 100.0)
    preview._begin_exposure_hold()

    drawn = []
    original = preview.draw.text
    preview.draw.text = lambda xy, text, **kw: (
        drawn.append(text),
        original(xy, text, **kw),
    )[1]
    preview._draw_status_bar()

    assert any("0.4s" in text for text in drawn)
    assert any(preview._UP_ARROW in text and "EXP" in text for text in drawn)
    assert any("ZOOM" in text for text in drawn)


@pytest.mark.unit
def test_status_bar_drops_zoom_on_the_image_view_where_it_does_nothing():
    """+/- return early outside the magnified views, so do not advertise them."""
    preview = _bar_preview(DisplayBase(), DISPLAY_IMAGE)

    assert "ZOOM" not in preview._status_bar_hint()
    assert "EXP" in preview._status_bar_hint()


@pytest.mark.unit
def test_status_bar_stays_off_the_stats_view_which_already_shows_it(monkeypatch):
    preview = _bar_preview(DisplayBase(), DISPLAY_STATS)
    monkeypatch.setattr(preview_module.time, "time", lambda: 100.0)
    preview._begin_exposure_hold()

    preview._draw_status_bar()

    assert preview.screen.getbbox() is None


@pytest.mark.unit
@pytest.mark.parametrize(
    "display_cls",
    (DisplayHeadless, DisplayHeadless176, DisplayHeadless320),
    ids=lambda cls: cls.__name__,
)
def test_status_bar_is_tall_enough_for_the_small_font(display_cls):
    """The bar height is derived from resolution, not font metrics.

    That keeps tile geometry independent of fonts, but it is only safe while
    the derived height still clears the small font on every shipped panel.
    """
    display_class = display_cls()
    preview = _bar_preview(display_class, DISPLAY_STARS)

    assert preview._status_bar_height() >= display_class.fonts.small.height


@pytest.mark.unit
@pytest.mark.parametrize("layout", (DisplayBase, Layout176, Layout320))
def test_status_bar_never_covers_camera_pixels(layout):
    """The bar is reserved out of the camera area, not drawn over it."""
    preview = object.__new__(UIPreview)
    preview.display_class = SimpleNamespace(
        resolution=layout.resolution,
        titlebar_height=layout.titlebar_height,
        resY=layout.resolution[1],
    )
    bar_top = preview._content_bottom()

    # No tile, and no part of the focus overlay, may reach into the bar.
    assert bar_top < layout.resolution[1]
    assert all(box[3] <= bar_top for box in preview._tile_boxes())
    assert preview._focus_center()[1] < bar_top


@pytest.mark.unit
def test_focus_screen_offers_no_exposure_jump_but_keeps_its_help():
    """Leaving via the jump stranded the hold; HELP rides the same menu."""
    menu = UIPreview._build_marking_menu()

    jumps = [option.menu_jump for option in (menu.left, menu.down, menu.right, menu.up)]
    assert jumps == [None, None, None, None]
    # up defaults to HELP, and this screen has help pages to show.
    assert menu.up.label == "HELP"
    assert UIPreview.__help_name__ == "camera"
