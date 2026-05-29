#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module contains the UIPreview class, a UI module for displaying and interacting with camera images.

It handles image processing and provides zoom
functionality. It also manages a marking menu for adjusting camera settings and draws reticles and star
selectors on the images.
"""

import sys
import time
from collections import deque

import numpy as np
from PIL import ImageChops

from PiFinder import focus, utils
from PiFinder.ui.marking_menus import MarkingMenuOption, MarkingMenu
from PiFinder.ui.base import UIModule
from PiFinder.ui.ui_utils import outline_text

sys.path.append(str(utils.tetra3_dir))

# Focus indicator tuning (see docs/ax/ui/CONTEXT.md "Focus indicator" and
# docs/adr/0005-focus-hfd-self-contained-in-ui.md). Starting values -- adjust
# on real hardware.
FOCUS_WINDOW_S = 10.0  # rolling V-curve window
HFD_AXIS_MIN = 1.0  # log Y-axis bottom (px)
HFD_AXIS_MAX = 50.0  # log Y-axis top (px), matches detector size cap
PAST_BEST_RATIO = 1.20  # current HFD > marker * this -> past-best cue
CUE_SMOOTHING = 3  # samples to smooth the cue decision over
STRETCH_EMA_ALPHA = 0.3  # display-stretch black/white smoothing
STRETCH_MIN_SPAN = 25.0  # min ADU span so a starless frame stays near-black


class UIPreview(UIModule):
    from PiFinder import tetra3

    __title__ = "CAMERA"
    __help_name__ = "camera"
    _STAR_ICON = "\uf005"  # NerdFont star icon (Font Awesome solid)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.reticle_mode = 2
        self.last_update = time.time()
        self.solution = None

        self.zoom_level = 0

        self.capture_prefix = f"{self.__uuid__}_diag"
        self.capture_count = 0

        # the centroiding returns an ndarray
        # so we're initialiazing one here
        self.star_list = np.empty((0, 2))
        self.highlight_count = 0

        # Focus indicator: strip on by default (square toggles it). Rolling
        # state is (re)initialised in _reset_focus_state(), also called on
        # active() so the V-curve clears each time the screen is entered.
        self.show_focus_strip = True
        self._reset_focus_state()

        # Marking menu definition
        self.marking_menu = MarkingMenu(
            left=MarkingMenuOption(
                label=_("Exposure"),
                menu_jump="camera_exposure",
            ),
            down=MarkingMenuOption(),
            right=MarkingMenuOption(),
        )

    def _reset_focus_state(self):
        """Clear rolling focus-indicator state (history, stretch EMA, cue)."""
        # (timestamp, hfd) samples over the rolling window; hfd is None for a
        # frame with no usable star (a gap -- never carried forward).
        self.focus_history: deque = deque()
        self.last_focus_result = None
        self._last_focus_frame_time = 0.0
        # Display-stretch black/white points (raw ADU), EMA-smoothed.
        self._stretch_black = None
        self._stretch_white = None
        # Recent raw past-best decisions, smoothed for display.
        self._cue_history: deque = deque(maxlen=CUE_SMOOTHING)

    def active(self):
        """Reset the rolling focus history when the screen is entered."""
        self._reset_focus_state()

    def _measure_focus(self, raw_np):
        """Run the self-contained HFD detector on a raw frame and update state.

        Appends a timestamped sample (HFD or None for a gap), prunes the rolling
        window, updates the EMA display-stretch points, and records the smoothed
        past-best cue decision. All measurement is on the raw frame.
        """
        result = focus.focus_hfd(raw_np)
        self.last_focus_result = result
        now = time.time()

        self.focus_history.append((now, result.median_hfd))
        cutoff = now - FOCUS_WINDOW_S
        while self.focus_history and self.focus_history[0][0] < cutoff:
            self.focus_history.popleft()

        # Display stretch: black = background, white = brightest detected peak,
        # with a minimum span so a starless frame stays near-black.
        black = result.background
        white = result.peak if result.peak is not None else black + STRETCH_MIN_SPAN
        white = max(white, black + STRETCH_MIN_SPAN)
        if self._stretch_black is None:
            self._stretch_black, self._stretch_white = black, white
        else:
            a = STRETCH_EMA_ALPHA
            self._stretch_black = a * black + (1 - a) * self._stretch_black
            self._stretch_white = a * white + (1 - a) * self._stretch_white

        # Past-best cue raw decision: current HFD has risen well above the window
        # minimum, and that minimum happened earlier (not on the latest sample).
        cue_raw = False
        marker, marker_ts = self._focus_marker()
        if (
            result.median_hfd is not None
            and marker is not None
            and marker_ts is not None
            and result.median_hfd > marker * PAST_BEST_RATIO
            and marker_ts < now
        ):
            cue_raw = True
        self._cue_history.append(cue_raw)

    def _focus_marker(self):
        """Return (min_hfd, timestamp_of_min) over the window, or (None, None)."""
        samples = [(t, h) for (t, h) in self.focus_history if h is not None]
        if not samples:
            return None, None
        ts, hfd = min(samples, key=lambda s: s[1])
        return hfd, ts

    def _cue_active(self):
        """Smoothed past-best cue: majority of recent raw decisions are True."""
        if not self._cue_history:
            return False
        return sum(self._cue_history) * 2 >= len(self._cue_history)

    def _apply_stretch(self, image_obj):
        """Background-anchored linear stretch of a mode-'L' image (cosmetic).

        Replaces per-frame autocontrast: black/white points come from the
        detector's EMA-smoothed background/peak, so the stretch is stable and a
        starless frame does not get its noise amplified.
        """
        if self._stretch_black is None or self._stretch_white is None:
            return image_obj
        black = self._stretch_black
        span = max(self._stretch_white - black, 1.0)
        scale = 255.0 / span
        lut = [min(255, max(0, int((i - black) * scale))) for i in range(256)]
        return image_obj.point(lut)

    def draw_reticle(self):
        """
        draw the reticle if desired
        """
        reticle_brightness = self.config_object.get_option("camera_reticle", 128)
        if reticle_brightness == 0:
            # None....
            return

        fov = 10.2
        solve_pixel = self.shared_state.solve_pixel(screen_space=True)
        for circ_deg in [4, 2, 0.5]:
            circ_rad = ((circ_deg / fov) * self.display_class.resX) / 2
            bbox = [
                solve_pixel[0] - circ_rad,
                solve_pixel[1] - circ_rad,
                solve_pixel[0] + circ_rad,
                solve_pixel[1] + circ_rad,
            ]
            self.draw.arc(bbox, 20, 70, fill=self.colors.get(reticle_brightness))
            self.draw.arc(bbox, 110, 160, fill=self.colors.get(reticle_brightness))
            self.draw.arc(bbox, 200, 250, fill=self.colors.get(reticle_brightness))
            self.draw.arc(bbox, 290, 340, fill=self.colors.get(reticle_brightness))

    def draw_star_selectors(self):
        # Draw star selectors
        if self.star_list.shape[0] > 0:
            self.highlight_count = 3
            if self.star_list.shape[0] < self.highlight_count:
                self.highlight_count = self.star_list.shape[0]

            for _i in range(self.highlight_count):
                raw_y, raw_x = self.star_list[_i]
                star_x = int(raw_x / 4)
                star_y = int(raw_y / 4)

                x_direction = 1
                x_text_offset = 6
                y_direction = 1
                y_text_offset = -12

                if star_x > 108:
                    x_direction = -1
                    x_text_offset = -10
                if star_y < 38:
                    y_direction = -1
                    y_text_offset = 1

                self.draw.line(
                    [
                        (star_x, star_y - (4 * y_direction)),
                        (star_x, star_y - (12 * y_direction)),
                    ],
                    fill=self.colors.get(128),
                )

                self.draw.line(
                    [
                        (star_x + (4 * x_direction), star_y),
                        (star_x + (12 * x_direction), star_y),
                    ],
                    fill=self.colors.get(128),
                )

                self.draw.text(
                    (star_x + x_text_offset, star_y + y_text_offset),
                    str(_i + 1),
                    font=self.fonts.small.font,
                    fill=self.colors.get(128),
                )

    def format_exposure_display(self) -> str:
        """Format exposure time for overlay display, just the number like 0.4s."""
        try:
            metadata = self.shared_state.last_image_metadata()

            # Get actual exposure from metadata
            if metadata and "exposure_time" in metadata:
                actual_exp = metadata["exposure_time"]
                exp_sec = actual_exp / 1_000_000
                if exp_sec < 0.1:
                    return f"{int(exp_sec * 1000)}ms"
                else:
                    # Truncate to 2 decimal places
                    exp_truncated = int(exp_sec * 100) / 100
                    return f"{exp_truncated:g}s"
        except Exception:
            pass
        return "N/A"

    def _matched_star_text(self):
        """Recent matched-star count (the solver's catalog matches), or '-'.

        Its 0 -> N jump signals "sharp enough to solve"; kept alongside the
        self-contained detected-star count.
        """
        try:
            solution = self.shared_state.solution()
            solve_source = solution.get("solve_source") if solution else None
            solve_time = solution.get("solve_time") if solution else None
            if solve_source in ("CAM", "CAM_FAILED") and solve_time:
                if time.time() - solve_time < 10:
                    return str(solution.get("Matches", 0))
        except Exception:
            pass
        return "-"

    def _hfd_to_y(self, hfd, plot_top, plot_bottom):
        """Map an HFD value to a screen y on the fixed log axis (low = bottom)."""
        clamped = min(max(hfd, HFD_AXIS_MIN), HFD_AXIS_MAX)
        norm = np.log(clamped / HFD_AXIS_MIN) / np.log(HFD_AXIS_MAX / HFD_AXIS_MIN)
        return int(plot_bottom - norm * (plot_bottom - plot_top))

    def draw_focus_strip(self):
        """Render the focus strip: V-curve, marker, past-best cue, and HUD.

        ~38 px bottom band, on by default; square hides it. Persists across all
        zoom levels (HFD is zoom-independent).
        """
        strip_top = 90
        res_x = self.display_class.resX
        res_y = self.display_class.resY
        plot_top = strip_top + 11
        plot_bottom = res_y - 11
        plot_left = 2
        plot_right = res_x - 3

        # Dim band so the overlay stays legible over a bright image.
        self.draw.rectangle([0, strip_top, res_x, res_y], fill=(0, 0, 0, 150))

        bright = self.colors.get(255)
        medium = self.colors.get(128)
        dim = self.colors.get(64)

        # --- V-curve + best-focus marker over the rolling window ---
        now = time.time()
        window_start = now - FOCUS_WINDOW_S
        span = plot_right - plot_left

        def x_of(ts):
            frac = (ts - window_start) / FOCUS_WINDOW_S
            return int(plot_left + min(max(frac, 0.0), 1.0) * span)

        marker, _marker_ts = self._focus_marker()
        if marker is not None:
            marker_y = self._hfd_to_y(marker, plot_top, plot_bottom)
            self.draw.line([(plot_left, marker_y), (plot_right, marker_y)], fill=dim)

        prev = None
        for ts, hfd in self.focus_history:
            if hfd is None:
                prev = None  # gap -- break the line
                continue
            point = (x_of(ts), self._hfd_to_y(hfd, plot_top, plot_bottom))
            if prev is not None:
                self.draw.line([prev, point], fill=bright)
            else:
                self.draw.point(point, fill=bright)
            prev = point

        # --- HUD text ---
        result = self.last_focus_result
        if result is not None and result.median_hfd is not None:
            hfd_text = f"HFD {result.median_hfd:.1f}"
            detected = str(result.n_used)
        elif result is not None and result.too_defocused:
            hfd_text = _("keep adjusting…")
            detected = "0"
        else:
            hfd_text = "HFD —"
            detected = "0"

        cue = self._cue_active()
        hfd_fill = bright if cue else medium
        if cue:
            hfd_text = f"↑ {hfd_text}"  # up-arrow: back up toward best focus

        outline_text(
            self.draw,
            (2, strip_top),
            hfd_text,
            align="left",
            font=self.fonts.small,
            fill=hfd_fill,
            shadow_color=(0, 0, 0),
            stroke=1,
        )
        outline_text(
            self.draw,
            (res_x - 2, strip_top),
            self.format_exposure_display(),
            align="left",
            font=self.fonts.small,
            fill=medium,
            shadow_color=(0, 0, 0),
            stroke=1,
            anchor="ra",
        )

        # Bottom row: detected-star count (left) and matched-star count (right).
        bottom_y = res_y - 9
        outline_text(
            self.draw,
            (2, bottom_y),
            _("det {n}").format(n=detected),
            align="left",
            font=self.fonts.small,
            fill=medium,
            shadow_color=(0, 0, 0),
            stroke=1,
        )
        if cue:
            outline_text(
                self.draw,
                (res_x // 2, bottom_y),
                _("BACK UP"),
                align="center",
                font=self.fonts.small,
                fill=bright,
                shadow_color=(0, 0, 0),
                stroke=1,
                anchor="ma",
            )
        outline_text(
            self.draw,
            (res_x - 2, bottom_y),
            f"{self._STAR_ICON} {self._matched_star_text()}",
            align="left",
            font=self.fonts.small,
            fill=medium,
            shadow_color=(0, 0, 0),
            stroke=1,
            anchor="ra",
        )

    def update(self, force=False):
        if force:
            self.last_update = 0
        # display an image
        metadata = self.shared_state.last_image_metadata()
        last_image_time = metadata["exposure_end"]
        image_updated = False
        if last_image_time > self.last_update:
            image_updated = True
            # camera_image is a multiprocessing-manager proxy; .copy() returns a
            # real PIL Image. Copy once, measure on the raw 512x512 frame, then
            # reuse the same copy for the (zoomed) display transform.
            raw_image = self.camera_image.copy()

            # Measure focus on the RAW frame before any display transform, and
            # only for a genuinely new frame (not a forced redraw).
            new_frame = last_image_time != self._last_focus_frame_time
            if new_frame:
                # focus_hfd needs a 2D array; convert to luminance so it works
                # for both mode-"L" hardware frames and RGB debug frames.
                self._measure_focus(np.asarray(raw_image.convert("L")))
                self._last_focus_frame_time = last_image_time

            image_obj = raw_image

            # Resize
            if self.zoom_level == 0:
                image_obj = image_obj.resize((128, 128))
            elif self.zoom_level == 1:
                image_obj = image_obj.resize((256, 256))
                image_obj = image_obj.crop((64, 64, 192, 192))
            elif self.zoom_level == 2:
                # no resize, just crop
                image_obj = image_obj.crop((192, 192, 320, 320))

            # Background-anchored linear stretch (replaces autocontrast), then RED.
            # Stretch on a single-band image so the 256-entry LUT applies cleanly
            # (debug frames are RGB; hardware frames are already mode "L").
            image_obj = image_obj.convert("L")
            image_obj = self._apply_stretch(image_obj)
            image_obj = image_obj.convert("RGB")
            image_obj = ImageChops.multiply(image_obj, self.colors.red_image)

            self.screen.paste(image_obj)
            self.last_update = last_image_time

            if self.zoom_level == 0:
                self.draw_reticle()

        # Image paste cleared the screen, so redraw overlays after a paste.
        if image_updated or force:
            if self.zoom_level > 0:
                # Zoom label relocated out of the focus-strip area (top-left,
                # just under the titlebar).
                zoom_number = self.zoom_level * 2
                self.draw.text(
                    (2, self.display_class.titlebar_height + 1),
                    _("Zoom x{zoom_number}").format(zoom_number=zoom_number),
                    font=self.fonts.bold.font,
                    fill=self.colors.get(128),
                )
            if self.show_focus_strip:
                self.draw_focus_strip()

        return self.screen_update()

    def key_plus(self):
        self.zoom_level += 1
        if self.zoom_level > 2:
            self.zoom_level = 2

    def key_minus(self):
        self.zoom_level -= 1
        if self.zoom_level < 0:
            self.zoom_level = 0

    def key_square(self):
        """Toggle the focus strip (V-curve + HUD) on/off with the square button."""
        self.show_focus_strip = not self.show_focus_strip
        self.update(force=True)
