#!/usr/bin/python
# -*- coding:utf-8 -*-
"""Raw, magnified multi-star Focus screen."""

import math
import sys
import time
from collections import deque
from typing import Optional

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageOps

from PiFinder import focus, utils
from PiFinder.ui.base import UIModule
from PiFinder.ui.marking_menus import MarkingMenu, MarkingMenuOption

sys.path.append(str(utils.tetra3_dir))

# Ten times the apparent size of the old full-frame preview. On a square panel
# this maps a 26x26 patch from the 512x512 camera frame into each half-screen
# tile. The crop expands for a broad blob so a defocused star remains visible.
FOCUS_NOMINAL_ZOOM = 10
FOCUS_MIN_ZOOM = 4
FOCUS_MAX_ZOOM = 16
FOCUS_ZOOM_STEP = 2
FOCUS_BLOB_MARGIN = 1.35
FOCUS_VISUAL_MAX_BLOB_PX = 128
FOCUS_TILE_COUNT = 4
FOCUS_WINDOW_S = 10.0
HFD_MIN_DISPLAY_SPAN = 1.0
HFD_RANGE_PADDING = 1.15
DISPLAY_STARS = "stars"
DISPLAY_IMAGE = "image"
DISPLAY_STATS = "stats"
DISPLAY_SINGLE = "single"


def focus_crop_size(
    frame_size: tuple[int, int],
    tile_size: tuple[int, int],
    blob_extent: int,
    nominal_zoom: int = FOCUS_NOMINAL_ZOOM,
) -> tuple[int, int]:
    """Return an aspect-correct native crop size for one magnified star tile.

    ``nominal_zoom`` is relative to the old full-frame preview. The nominal
    crop is used for compact, focused stars. Broad stars get a larger crop with
    a small margin, reducing the effective zoom instead of clipping the blob.
    """
    frame_w, frame_h = frame_size
    tile_w, tile_h = tile_size
    if frame_w <= 0 or frame_h <= 0 or tile_w <= 0 or tile_h <= 0:
        raise ValueError("frame and tile dimensions must be positive")
    if nominal_zoom <= 0:
        raise ValueError("nominal_zoom must be positive")

    crop_h = max(
        math.ceil(frame_h / (2 * nominal_zoom)),
        math.ceil(blob_extent * FOCUS_BLOB_MARGIN),
    )
    crop_w = math.ceil(crop_h * tile_w / tile_h)

    if crop_w > frame_w:
        crop_w = frame_w
        crop_h = max(1, round(crop_w * tile_h / tile_w))
    if crop_h > frame_h:
        crop_h = frame_h
        crop_w = max(1, round(crop_h * tile_w / tile_h))
    return crop_w, crop_h


class UIPreview(UIModule):
    from PiFinder import tetra3

    __title__ = "CAMERA"
    __help_name__ = "camera"
    _display_mode_list = [DISPLAY_STARS, DISPLAY_SINGLE, DISPLAY_IMAGE, DISPLAY_STATS]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.last_update = time.time()
        self.focus_zoom = FOCUS_NOMINAL_ZOOM
        self.last_focus_result = None
        self._tracked_focus_blobs: tuple[focus.Blob, ...] = ()
        self._focus_slot_catalog_ids: tuple[Optional[object], ...] = ()
        self._last_focus_catalog_time = 0.0
        self._last_focus_frame_time = 0.0
        self.focus_history: deque[tuple[float, float]] = deque()

        self.marking_menu = MarkingMenu(
            left=MarkingMenuOption(
                label=_("Exposure"),
                menu_jump="camera_exposure",
            ),
            down=MarkingMenuOption(),
            right=MarkingMenuOption(),
        )

    def active(self):
        """Discard stale measurements when the Focus screen is entered."""
        self.last_focus_result = None
        self._tracked_focus_blobs = ()
        self._focus_slot_catalog_ids = ()
        self._last_focus_catalog_time = 0.0
        self._last_focus_frame_time = 0.0
        self.focus_history.clear()

    def _measure_focus(
        self, raw_np: np.ndarray, *, record_history: bool = True
    ) -> None:
        """Measure HFD and locate display blobs from one raw frame."""
        self.last_focus_result = focus.focus_hfd(raw_np)
        candidates = tuple(
            blob
            for blob in self.last_focus_result.blobs
            if blob.extent <= FOCUS_VISUAL_MAX_BLOB_PX
        )
        previous_ids = self._focus_slot_catalog_ids
        tracked_slots = focus.track_blob_slots(
            self._tracked_focus_blobs,
            candidates,
            n=FOCUS_TILE_COUNT,
            max_candidates=FOCUS_TILE_COUNT,
        )
        self._tracked_focus_blobs = tuple(blob for blob, _index in tracked_slots)
        self._focus_slot_catalog_ids = tuple(
            previous_ids[previous_index]
            if previous_index is not None and previous_index < len(previous_ids)
            else None
            for _blob, previous_index in tracked_slots
        )
        if record_history:
            self._record_focus_sample(self.last_focus_result.median_hfd)

    def _adopt_solved_catalog_ids(self, frame_time: float) -> None:
        """Attach HIP identities only to blobs from the solved exposure."""
        if frame_time <= 0 or frame_time == self._last_focus_catalog_time:
            return
        solution = self.shared_state.solution()
        if solution.last_solve_success != frame_time:
            return
        centroids = solution.matched_centroids
        catalog_ids = solution.matched_catID
        if not centroids or not catalog_ids:
            return

        matched = focus.match_catalog_ids(
            self._tracked_focus_blobs, centroids, catalog_ids
        )

        # Correct a geometric slot swap whenever the solved identities prove
        # that a known HIP star has landed in another slot. Unmatched blobs keep
        # their geometric identity because focus must also work when tetra3 did
        # not use every visible star in its solution.
        previous_ids = self._focus_slot_catalog_ids
        source_for_slot: list[Optional[int]] = [None] * len(matched)
        used_sources = set()
        for slot, expected_id in enumerate(previous_ids):
            if expected_id is None:
                continue
            source = next(
                (
                    index
                    for index, solved_id in enumerate(matched)
                    if index not in used_sources and solved_id == expected_id
                ),
                None,
            )
            if source is not None:
                source_for_slot[slot] = source
                used_sources.add(source)

        remaining_sources = (
            index for index in range(len(matched)) if index not in used_sources
        )
        for slot, source in enumerate(source_for_slot):
            if source is None:
                source_for_slot[slot] = next(remaining_sources)

        old_blobs = self._tracked_focus_blobs
        self._tracked_focus_blobs = tuple(
            old_blobs[source] for source in source_for_slot if source is not None
        )
        self._focus_slot_catalog_ids = tuple(
            matched[source]
            if matched[source] is not None
            else previous_ids[source]
            if source < len(previous_ids)
            else None
            for source in source_for_slot
            if source is not None
        )
        self._last_focus_catalog_time = frame_time

    def _record_focus_sample(self, hfd: Optional[float]) -> None:
        """Record a numeric HFD; missing measurements leave history frozen."""
        if hfd is None:
            return
        now = time.time()
        self.focus_history.append((now, hfd))
        cutoff = now - FOCUS_WINDOW_S
        while self.focus_history and self.focus_history[0][0] < cutoff:
            self.focus_history.popleft()

    def _display_blobs(self) -> tuple[focus.Blob, ...]:
        """Return the four brightest visual blobs from anywhere in the frame."""
        tracked = getattr(self, "_tracked_focus_blobs", None)
        if tracked is not None:
            return tracked
        if self.last_focus_result is None:
            return ()
        return tuple(self.last_focus_result.blobs[:FOCUS_TILE_COUNT])

    def _focus_center(self) -> tuple[int, int]:
        """Return the center of the visible area below the title bar."""
        res_x, res_y = self.display_class.resolution
        content_top = min(self.display_class.titlebar_height + 1, res_y)
        return res_x // 2, content_top + (res_y - content_top) // 2

    def _tile_boxes(self) -> tuple[tuple[int, int, int, int], ...]:
        """Split the visible camera area into four equally sized quadrants."""
        res_x, res_y = self.display_class.resolution
        content_top = min(self.display_class.titlebar_height + 1, res_y)
        mid_x = res_x // 2
        mid_y = self._focus_center()[1]
        return (
            (0, content_top, mid_x, mid_y),
            (mid_x, content_top, res_x, mid_y),
            (0, mid_y, mid_x, res_y),
            (mid_x, mid_y, res_x, res_y),
        )

    def _render_focus_tiles(self, raw_image: Image.Image) -> Image.Image:
        """Render four raw star crops with nearest-neighbour enlargement.

        The camera data receives no contrast stretch, filtering, sharpening,
        or interpolating resample. Conversion to luminance only normalizes RGB
        debug frames to the hardware camera's native single-channel shape.
        """
        raw_l = raw_image.convert("L")
        res_x, res_y = self.display_class.resolution
        mosaic = Image.new("L", (res_x, res_y), 0)

        for blob, box in zip(self._display_blobs(), self._tile_boxes()):
            left, top, right, bottom = box
            tile_size = (right - left, bottom - top)
            crop_w, crop_h = focus_crop_size(
                raw_l.size,
                tile_size,
                blob.extent,
                self.focus_zoom,
            )
            # Keep the crop wholly inside the sensor frame. PIL pads an
            # out-of-bounds crop with black, which otherwise appears as a bar
            # when a selected star is close to an edge.
            crop_left = min(max(round(blob.x - crop_w / 2), 0), raw_l.width - crop_w)
            crop_top = min(max(round(blob.y - crop_h / 2), 0), raw_l.height - crop_h)
            crop = raw_l.crop(
                (crop_left, crop_top, crop_left + crop_w, crop_top + crop_h)
            )
            enlarged = crop.resize(tile_size, resample=Image.Resampling.NEAREST)
            mosaic.paste(enlarged, (left, top))

        # Apply the display's red/grey channel mask without changing luminance.
        return ImageChops.multiply(mosaic.convert("RGB"), self.colors.red_image)

    def _render_brightest_star(self, raw_image: Image.Image) -> Image.Image:
        """Fill the panel with the brightest detected star's raw crop."""
        raw_l = raw_image.convert("L")
        target_size = self.display_class.resolution
        rendered = Image.new("L", target_size, 0)
        blobs = self._display_blobs()
        if blobs:
            blob = blobs[0]
            # Reuse a tile's native crop across the full panel, giving Single
            # twice the apparent magnification selected by +/- in Stars.
            crop_w, crop_h = focus_crop_size(
                raw_l.size,
                target_size,
                blob.extent,
                self.focus_zoom,
            )
            crop_left = min(max(round(blob.x - crop_w / 2), 0), raw_l.width - crop_w)
            crop_top = min(max(round(blob.y - crop_h / 2), 0), raw_l.height - crop_h)
            crop = raw_l.crop(
                (crop_left, crop_top, crop_left + crop_w, crop_top + crop_h)
            )
            rendered = crop.resize(target_size, resample=Image.Resampling.NEAREST)

        return ImageChops.multiply(rendered.convert("RGB"), self.colors.red_image)

    def _render_image_frame(self, raw_image: Image.Image) -> Image.Image:
        """Fit and autocontrast the full camera image for display only."""
        resized = raw_image.convert("L").resize(
            self.display_class.resolution, resample=Image.Resampling.NEAREST
        )
        red = ImageChops.multiply(resized.convert("RGB"), self.colors.red_image)
        return ImageOps.autocontrast(red)

    def _focus_readout_text(self) -> str:
        """Format current HFD, using one unmistakable unavailable value."""
        result = self.last_focus_result
        if result is not None and result.median_hfd is not None:
            return f"{result.median_hfd:.1f}"
        return "?.?"

    def _focus_history_gap(self, center, text, font) -> tuple[int, int]:
        """Return signal endpoints with equal padding from rendered outline."""
        mask = Image.new("1", self.display_class.resolution)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.text(
            center,
            text,
            font=font,
            fill=1,
            anchor="mm",
            stroke_width=1,
            stroke_fill=1,
        )
        ink_box = mask.getbbox()
        if ink_box is None:
            return center[0], center[0]

        # Endpoints are inclusive. Leave exactly three blank pixels between
        # each endpoint and the first/last rendered outline pixel.
        padding = 3
        return ink_box[0] - padding - 1, ink_box[2] + padding

    def _draw_focus_overlay(self) -> None:
        """Draw quadrant separators, HFD history, and the current HFD."""
        res_x, res_y = self.display_class.resolution
        content_top = min(self.display_class.titlebar_height + 1, res_y)
        center = self._focus_center()
        separator = self.colors.get(64)
        self.draw.line(
            [(center[0], content_top), (center[0], res_y - 1)], fill=separator
        )
        self.draw.line([(0, center[1]), (res_x - 1, center[1])], fill=separator)

        text = self._focus_readout_text()

        font = self.fonts.large.font
        gap_left, gap_right = self._focus_history_gap(center, text, font)
        self._draw_focus_history(center[1], gap_left, gap_right)
        self.draw.text(
            center,
            text,
            font=font,
            fill=self.colors.get(255),
            anchor="mm",
            stroke_width=1,
            stroke_fill=self.colors.get(0),
        )

    def _draw_single_focus_overlay(self) -> None:
        """Draw HFD and history over a translucent lower-third panel."""
        res_x, res_y = self.display_class.resolution
        overlay_top = math.ceil(res_y * 2 / 3)
        center = (res_x // 2, overlay_top + (res_y - overlay_top) // 2)
        self.draw.rectangle((0, overlay_top, res_x, res_y), fill=(0, 0, 0, 128))

        text = self._focus_readout_text()

        font = self.fonts.large.font
        gap_left, gap_right = self._focus_history_gap(center, text, font)
        self._draw_focus_history(center[1], gap_left, gap_right)
        self.draw.text(
            center,
            text,
            font=font,
            fill=self.colors.get(255),
            anchor="mm",
            stroke_width=1,
            stroke_fill=self.colors.get(0),
        )

    def _draw_focus_history(self, center_y: int, gap_left: int, gap_right: int) -> None:
        """Draw the centered rolling HFD signal across the middle divider.

        The time axis passes through an omitted center interval, leaving the
        outlined numeric readout unobstructed while older and newer samples
        appear to its left and right. The recent value range is centered on the
        divider; lower HFD is below it. A minimum span prevents measurement
        noise from filling the plot height.
        """
        res_x, res_y = self.display_class.resolution
        plot_half_height = max(8, round(res_y * 10 / 128))
        left_edge = 2
        right_edge = res_x - 3
        gap_left = max(left_edge, gap_left)
        gap_right = min(right_edge, gap_right)
        left_width = max(gap_left - left_edge, 0)
        right_width = max(right_edge - gap_right, 0)
        drawable_width = left_width + right_width
        if drawable_width <= 0:
            return

        # Wall time makes stale measurements visibly recede during missing
        # frames. Missing frames add no samples; the next numeric sample prunes
        # expired history and starts drawing immediately at the right edge.
        now = time.time()
        window_start = now - FOCUS_WINDOW_S
        while self.focus_history and self.focus_history[0][0] < window_start:
            self.focus_history.popleft()
        samples = [hfd for _timestamp, hfd in self.focus_history]
        if samples:
            range_center = (min(samples) + max(samples)) / 2
            half_span = max(
                (max(samples) - min(samples)) * HFD_RANGE_PADDING / 2,
                HFD_MIN_DISPLAY_SPAN / 2,
            )
        else:
            range_center = 0.0
            half_span = HFD_MIN_DISPLAY_SPAN / 2

        def y_of(hfd: float) -> int:
            relative = min(max((hfd - range_center) / half_span, -1.0), 1.0)
            return round(center_y - relative * plot_half_height)

        def x_of(timestamp: float) -> tuple[int, bool, float]:
            fraction = min(max((timestamp - window_start) / FOCUS_WINDOW_S, 0), 1)
            offset = fraction * drawable_width
            if offset <= left_width:
                return round(left_edge + offset), False, offset
            return round(gap_right + offset - left_width), True, offset

        bright = self.colors.get(255)

        def draw_segment(start: tuple[int, int], end: tuple[int, int]) -> None:
            self.draw.line((start, end), fill=bright)

        def draw_isolated_sample(point: tuple[int, int], right_side: bool) -> None:
            """Make the first sample after a gap visible without bridging it."""
            x, y = point
            side_left = gap_right if right_side else left_edge
            side_right = right_edge if right_side else gap_left
            self.draw.line(
                (max(side_left, x - 1), y, min(side_right, x + 1), y),
                fill=bright,
            )

        previous: Optional[tuple[tuple[int, int], bool, float]] = None
        for timestamp, hfd in self.focus_history:
            x, right_side, offset = x_of(timestamp)
            current = (
                (x, y_of(hfd)),
                right_side,
                offset,
            )
            if previous is not None and previous[1] == right_side:
                draw_segment(previous[0], current[0])
            elif previous is not None:
                # Clip a segment crossing the number at equal left/right gap
                # boundaries. Dropping the whole segment makes the apparent
                # spacing depend on the camera sample interval.
                span = current[2] - previous[2]
                fraction = (left_width - previous[2]) / span
                crossing_y = round(
                    previous[0][1] + fraction * (current[0][1] - previous[0][1])
                )
                draw_segment(previous[0], (gap_left, crossing_y))
                draw_segment((gap_right, crossing_y), current[0])
            else:
                draw_isolated_sample(current[0], right_side)
            previous = current

    @staticmethod
    def _format_exposure(exposure_us) -> str:
        try:
            exposure_us = float(exposure_us)
        except (TypeError, ValueError):
            return "—"
        if exposure_us < 1000:
            return f"{exposure_us:.0f}us"
        if exposure_us < 100_000:
            return f"{exposure_us / 1000:g}ms"
        return f"{exposure_us / 1_000_000:g}s"

    def _draw_stats(self, raw_np: np.ndarray, metadata: dict) -> None:
        """Draw focus/exposure statistics and a raw histogram."""
        res_x, res_y = self.display_class.resolution
        self.draw.rectangle((0, 0, res_x, res_y), fill=self.colors.get(0))
        bright = self.colors.get(255)
        medium = self.colors.get(128)
        dim = self.colors.get(64)
        result = self.last_focus_result

        hfd = self._focus_readout_text()
        fwhm = (
            f"{result.median_fwhm:.1f} px"
            if result is not None and result.median_fwhm is not None
            else "—"
        )
        detected = len(result.blobs) if result is not None else 0
        exposure_setting = self.config_object.get_option("camera_exp")
        exposure_mode = "AUTO" if str(exposure_setting).lower() == "auto" else "MANUAL"
        exposure = self._format_exposure(metadata.get("exposure_time"))
        gain = metadata.get("gain")
        gain_text = f"{gain:g}" if isinstance(gain, (int, float)) else "—"

        # screen_update() draws the standard title bar after this method. Keep
        # the hero value below it so the bar never masks the HFD number.
        top = self.display_class.titlebar_height + 4
        self.draw.text((2, top), "HFD", font=self.fonts.base.font, fill=medium)
        self.draw.text(
            (res_x - 2, top),
            hfd,
            font=self.fonts.huge.font,
            fill=bright,
            anchor="rt",
        )

        line_h = self.fonts.small.height + 1
        stats_y = top + self.fonts.huge.height
        lines = (
            f"FWHM {fwhm}  Stars {detected}",
            f"{exposure_mode} {exposure}  Gain {gain_text}",
        )
        for line in lines:
            self.draw.text((2, stats_y), line, font=self.fonts.small.font, fill=medium)
            stats_y += line_h

        label_h = self.fonts.small.height
        plots_top = min(stats_y + 1, res_y - label_h - 4)
        label_xy = (2, plots_top)
        self.draw.text(label_xy, "RAW HIST", font=self.fonts.small.font, fill=dim)
        label_box = self.draw.textbbox(label_xy, "RAW HIST", font=self.fonts.small.font)
        plot_left, plot_top, plot_right, plot_bottom = (
            2,
            min(label_box[3] + 2, res_y - 2),
            res_x - 2,
            res_y - 1,
        )
        plot_height = max(plot_bottom - plot_top, 1)
        plot_width = max(plot_right - plot_left + 1, 1)
        bins = min(32, plot_width)
        counts, _bin_edges = np.histogram(raw_np, bins=bins, range=(0, 256))
        heights = np.log1p(counts.astype(np.float64))
        peak = float(heights.max())
        if peak > 0:
            heights *= plot_height / peak
        for index, height in enumerate(heights):
            x0 = plot_left + round(index * plot_width / bins)
            x1 = max(x0, plot_left + round((index + 1) * plot_width / bins) - 1)
            y = plot_bottom - round(float(height))
            self.draw.rectangle((x0, y, x1, plot_bottom), fill=medium)

    def update(self, force: bool = False):
        if force:
            self.last_update = 0

        metadata = self.shared_state.last_image_metadata()
        last_image_time = metadata["exposure_end"]
        image_updated = False
        if last_image_time > self.last_update:
            image_updated = True
            raw_image = self.camera_image.copy()

            raw_np = np.asarray(raw_image.convert("L"))
            if last_image_time != self._last_focus_frame_time:
                # A solve normally arrives after its image was first rendered.
                # Identify those retained previous-frame blobs before tracking
                # their slots onto the newly arrived frame.
                self._adopt_solved_catalog_ids(self._last_focus_frame_time)
                self._measure_focus(raw_np)
                self._last_focus_frame_time = last_image_time
                # Also handle the less common case where the solver won the
                # race and published this exposure before the UI copied it.
                self._adopt_solved_catalog_ids(last_image_time)
            elif force:
                # A forced redraw can race the separately published camera
                # metadata. Re-measure this exact display copy, but do not add
                # a duplicate point to the time history.
                self._measure_focus(raw_np, record_history=False)

            if self.display_mode == DISPLAY_STARS:
                self.screen.paste(self._render_focus_tiles(raw_image))
            elif self.display_mode == DISPLAY_IMAGE:
                self.screen.paste(self._render_image_frame(raw_image))
            elif self.display_mode == DISPLAY_STATS:
                self._draw_stats(raw_np, metadata)
            else:
                self.screen.paste(self._render_brightest_star(raw_image))
            self.last_update = last_image_time

        if (image_updated or force) and self.display_mode == DISPLAY_STARS:
            self._draw_focus_overlay()
        elif (image_updated or force) and self.display_mode == DISPLAY_SINGLE:
            self._draw_single_focus_overlay()

        return self.screen_update()

    def key_plus(self):
        """Increase the nominal focused-star magnification."""
        if self.display_mode not in (DISPLAY_STARS, DISPLAY_SINGLE):
            return
        self.focus_zoom = min(FOCUS_MAX_ZOOM, self.focus_zoom + FOCUS_ZOOM_STEP)
        self.update(force=True)

    def key_minus(self):
        """Decrease the nominal focused-star magnification."""
        if self.display_mode not in (DISPLAY_STARS, DISPLAY_SINGLE):
            return
        self.focus_zoom = max(FOCUS_MIN_ZOOM, self.focus_zoom - FOCUS_ZOOM_STEP)
        self.update(force=True)

    def key_square(self):
        """Cycle Stars -> Single -> Image -> Stats using the display-mode key."""
        self.cycle_display_mode()
        self.update(force=True)
