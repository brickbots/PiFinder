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

# Exposures the screen steps between while it holds the exposure, in
# microseconds. These are exactly the values the Camera Exp menu offers, so a
# nudge here always lands on one the user can also select -- and persist --
# from that menu. tests/test_focus_preview.py pins the two lists together.
FOCUS_EXPOSURE_LADDER = (
    25_000,
    50_000,
    100_000,
    200_000,
    400_000,
    800_000,
    1_000_000,
)
# Exposure to hold when no exposure is known yet. Matches the starting point
# the camera processes use for auto-exposure.
FOCUS_DEFAULT_EXPOSURE = 400_000
# Height of the bottom status bar at 128px, scaled with the panel. Derived from
# the resolution rather than the small font so that tile geometry stays
# independent of font metrics; tests/test_focus_preview.py pins that this is
# still tall enough for the small font on every shipped layout.
#
# The bar is reserved out of the camera area rather than drawn over it, so no
# raw pixel is ever hidden by it -- the whole point of the star tiles is that
# what you see is the sensor.
FOCUS_STATUS_BAR_H_128 = 13


def step_exposure(
    current_us: int,
    direction: int,
    ladder: tuple[int, ...] = FOCUS_EXPOSURE_LADDER,
) -> int:
    """Return the adjacent ladder rung above (+1) or below (-1) ``current_us``.

    Stepping to a neighbouring rung rather than by a fixed multiple means the
    first nudge away from an auto-settled exposure -- which sits wherever the
    controller left it -- lands on a value the Camera Exp menu also offers. At
    either end of the ladder the exposure holds where it is.
    """
    if direction > 0:
        return next((rung for rung in ladder if rung > current_us), current_us)
    return next((rung for rung in reversed(ladder) if rung < current_us), current_us)


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

        # Exposure hold state. See _begin_exposure_hold for why the screen
        # takes the exposure away from auto-exposure while it is open.
        self._exposure_hold_active = False
        self._saved_camera_exp: Optional[object] = None
        self._held_exposure_us: Optional[int] = None

        self.marking_menu = self._build_marking_menu()

    @staticmethod
    def _build_marking_menu() -> MarkingMenu:
        """The Quick Menu for this screen: help only, no Exposure jump.

        UP/DOWN adjust the exposure directly here, so the jump was a second,
        slower route to the same thing -- and taking it buried this screen
        without ``inactive()``, stranding the exposure hold and with it
        auto-exposure for the rest of the session. The status bar advertises
        the keys that replaced it.

        The menu itself stays rather than becoming None: ``MarkingMenu.up``
        defaults to HELP and this screen has help pages
        (``__help_name__ = "camera"``), so dropping the menu would take the
        help with it.
        """
        return MarkingMenu(
            left=MarkingMenuOption(),
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
        self._begin_exposure_hold()

    def inactive(self):
        """Hand the exposure regime back to whatever was in effect on entry.

        MenuManager calls this twice when the screen is left with LEFT (once
        directly, once again from remove_from_stack), so releasing the hold
        has to be idempotent.
        """
        if not self._exposure_hold_active:
            return
        self._exposure_hold_active = False
        saved = self._saved_camera_exp
        if saved is None or saved == "auto":
            # No saved value means no exposure was ever chosen; solver-driven
            # auto-exposure is the safe regime to land back in either way.
            self.command_queues["camera"].put("set_exp:auto")
        else:
            # Transient: this is a restore, not a fresh choice, so it must not
            # rewrite the camera_exp the user already had.
            self.command_queues["camera"].put(f"set_exp_transient:{saved}")

    # ------------------------------------------------------------------ #
    # Exposure hold
    # ------------------------------------------------------------------ #

    def _begin_exposure_hold(self) -> None:
        """Take the exposure away from auto-exposure for this visit.

        Solver-driven auto-exposure steers on the solver's match count, and
        defocus -- the reason to be on this screen at all -- is exactly what
        starves the solver of matches. Left running, the controller walks the
        exposure (and eventually hands over to zero-match recovery, which
        walks it much further) while the user is trying to read a change in
        HFD out of those same frames. Both the readout and which stars are
        bright enough to appear would move for reasons that have nothing to do
        with the lens they just turned.

        The hold is transient throughout: ``camera_exp`` is read but never
        written, so ``inactive`` can put the previous regime back.
        """
        self._saved_camera_exp = self.config_object.get_option("camera_exp")
        self._apply_hold_exposure(self._entry_exposure())

    def _entry_exposure(self) -> int:
        """Pick the exposure to hold when the screen opens.

        A numeric ``camera_exp`` is the exposure the user chose, so hold that
        -- and prefer it over the last frame's metadata, which still reports
        the previous exposure until the camera process works through its
        command queue. Under auto-exposure there is no chosen value, so hold
        wherever the controller has settled.
        """
        saved = self._saved_camera_exp
        if isinstance(saved, (int, float)) and saved > 0:
            return int(saved)
        metadata = self.shared_state.last_image_metadata() or {}
        exposure = metadata.get("exposure_time")
        if isinstance(exposure, (int, float)) and exposure > 0:
            return int(exposure)
        return FOCUS_DEFAULT_EXPOSURE

    def _apply_hold_exposure(self, exposure_us: int) -> None:
        """Hold the camera at one exposure and show the value on screen."""
        self._held_exposure_us = int(exposure_us)
        self._exposure_hold_active = True
        self.command_queues["camera"].put(f"set_exp_transient:{self._held_exposure_us}")

    def _nudge_exposure(self, direction: int) -> None:
        """Step the held exposure one rung along the Camera Exp ladder."""
        if not self._exposure_hold_active or self._held_exposure_us is None:
            return
        new_exposure = step_exposure(self._held_exposure_us, direction)
        if new_exposure != self._held_exposure_us:
            self._apply_hold_exposure(new_exposure)
        # Redraw either way. At the end of the ladder the value is unchanged,
        # but the status bar is standing so there is nothing to re-flash --
        # the repaint just keeps the screen current with the key press.
        self.update(force=True)

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

    def _status_bar_height(self) -> int:
        """Rows reserved at the bottom for the exposure and key readout."""
        res_y = self.display_class.resolution[1]
        return max(FOCUS_STATUS_BAR_H_128, round(res_y * FOCUS_STATUS_BAR_H_128 / 128))

    def _content_bottom(self) -> int:
        """First row belonging to the status bar rather than the camera.

        Every camera-area layout measures down to this instead of the panel
        height, so the bar takes its space from the render rather than
        covering it.
        """
        res_y = self.display_class.resolution[1]
        content_top = min(self.display_class.titlebar_height + 1, res_y)
        return max(content_top + 1, res_y - self._status_bar_height())

    def _focus_center(self) -> tuple[int, int]:
        """Return the center of the visible area below the title bar."""
        res_x, res_y = self.display_class.resolution
        content_top = min(self.display_class.titlebar_height + 1, res_y)
        content_bottom = self._content_bottom()
        return res_x // 2, content_top + (content_bottom - content_top) // 2

    def _tile_boxes(self) -> tuple[tuple[int, int, int, int], ...]:
        """Split the visible camera area into four equally sized quadrants."""
        res_x, res_y = self.display_class.resolution
        content_top = min(self.display_class.titlebar_height + 1, res_y)
        content_bottom = self._content_bottom()
        mid_x = res_x // 2
        mid_y = self._focus_center()[1]
        return (
            (0, content_top, mid_x, mid_y),
            (mid_x, content_top, res_x, mid_y),
            (0, mid_y, mid_x, content_bottom),
            (mid_x, mid_y, res_x, content_bottom),
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
        # Stops above the status bar for the same reason the tiles do: these
        # are raw sensor pixels and the bar must not sit on any of them.
        target_size = (self.display_class.resolution[0], self._content_bottom())
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
            (self.display_class.resolution[0], self._content_bottom()),
            resample=Image.Resampling.NEAREST,
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
        content_bottom = self._content_bottom()
        center = self._focus_center()
        separator = self.colors.get(64)
        self.draw.line(
            [(center[0], content_top), (center[0], content_bottom - 1)], fill=separator
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
        res_x = self.display_class.resolution[0]
        content_bottom = self._content_bottom()
        overlay_top = math.ceil(content_bottom * 2 / 3)
        center = (res_x // 2, overlay_top + (content_bottom - overlay_top) // 2)
        self.draw.rectangle(
            # rectangle() includes its far corner, so stop one row short of the
            # reserved status bar rather than shading its first row.
            (0, overlay_top, res_x, content_bottom - 1),
            fill=(0, 0, 0, 128),
        )

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

    def _status_bar_hint(self) -> str:
        """Keys worth advertising in the view currently showing.

        Only keys that do something here. ``+``/``-`` return early outside the
        magnified views, so offering zoom on the full-frame Image view would
        teach a key that does nothing.
        """
        hint = f"{self._UP_ARROW}{self._DOWN_ARROW}EXP"
        if self.display_mode in (DISPLAY_STARS, DISPLAY_SINGLE):
            hint = f"{hint} +/-ZOOM"
        return hint

    def _draw_status_bar(self) -> None:
        """Draw the standing exposure and key readout along the bottom.

        Persistent rather than a flash, and one bar rather than a value in one
        corner and a legend in another: the exposure is worth watching for as
        long as the screen is open, and the keys that change it are not
        discoverable any other way now that the Quick Menu jump is gone.

        Stats is excluded because it already reports the exposure and its
        regime in full, and its histogram owns the bottom of the panel.
        """
        if self.display_mode == DISPLAY_STATS:
            return
        res_x, res_y = self.display_class.resolution
        bar_top = self._content_bottom()
        font = self.fonts.small.font
        # Opaque, so the bar stays legible whatever the view under it renders.
        self.draw.rectangle((0, bar_top, res_x, res_y), fill=self.colors.get(0))

        text_y = bar_top + max(
            0, (self._status_bar_height() - self.fonts.small.height) // 2
        )
        exposure = (
            self._format_exposure(self._held_exposure_us)
            if self._held_exposure_us is not None
            else ""
        )
        hint = self._status_bar_hint()

        # The exposure changes width as it changes value, so it is pinned left
        # and the hint pinned right rather than laid out as one string. If a
        # long off-ladder exposure would collide with the hint on a narrow
        # panel, the hint gives way -- the measurement outranks the legend.
        exposure_w = self.draw.textlength(exposure, font=font) if exposure else 0
        hint_w = self.draw.textlength(hint, font=font)
        if exposure_w + hint_w + 6 > res_x:
            hint = f"{self._UP_ARROW}{self._DOWN_ARROW}EXP"
            hint_w = self.draw.textlength(hint, font=font)
        if exposure:
            self.draw.text((2, text_y), exposure, font=font, fill=self.colors.get(255))
        if exposure_w + hint_w + 6 <= res_x:
            self.draw.text(
                (res_x - 2, text_y),
                hint,
                font=font,
                fill=self.colors.get(128),
                anchor="ra",
            )

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
        if self._exposure_hold_active:
            # The saved setting still reads "auto" during the hold; reporting
            # it would contradict the exposure sitting next to it.
            exposure_mode = "HOLD"
        else:
            exposure_setting = self.config_object.get_option("camera_exp")
            exposure_mode = (
                "AUTO" if str(exposure_setting).lower() == "auto" else "MANUAL"
            )
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

        if image_updated or force:
            self._draw_status_bar()

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

    def key_up(self):
        """Hold a longer exposure, one rung up the Camera Exp ladder."""
        self._nudge_exposure(1)

    def key_down(self):
        """Hold a shorter exposure, one rung down the Camera Exp ladder."""
        self._nudge_exposure(-1)

    def key_square(self):
        """Cycle Stars -> Single -> Image -> Stats using the display-mode key."""
        self.cycle_display_mode()
        self.update(force=True)
