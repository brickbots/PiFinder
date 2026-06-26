#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module contains the UIPreview class, a UI module for displaying and interacting with camera images.

It handles image processing and provides zoom
functionality. It also manages a marking menu for adjusting camera settings and draws the focus
strip and star selectors on the images.
"""

import sys
import time
from collections import deque

import numpy as np
from PIL import Image, ImageChops

from PiFinder import focus, utils
from PiFinder.ui.camera_render import resize_for_display
from PiFinder.ui.marking_menus import MarkingMenuOption, MarkingMenu
from PiFinder.ui.base import UIModule
from PiFinder.ui.ui_utils import outline_text

sys.path.append(str(utils.tetra3_dir))

# Focus indicator tuning (see docs/ax/ui/CONTEXT.md "Focus indicator" and
# docs/adr/0005-focus-hfd-self-contained-in-ui.md). Starting values -- adjust
# on real hardware.
FOCUS_WINDOW_S = 10.0  # rolling V-curve window
# V-curve axis: 4 px is about the best a real camera/lens can hit, so it anchors
# the bottom; 20 px is "clearly defocused". Readings outside [4, 20] clamp to the
# axis ends (the big numeric readout still shows the true value).
HFD_AXIS_MIN = 4.0  # log Y-axis bottom (px) -- best achievable focus
HFD_AXIS_MAX = 20.0  # log Y-axis top (px) -- clearly defocused
# Display-stretch: smaller alpha + larger min span keep the preview calm (the
# stretch was over-reacting frame to frame); the dither breaks 8-bit banding.
STRETCH_EMA_ALPHA = 0.15  # display-stretch black/white smoothing (lower = calmer)
STRETCH_MIN_SPAN = 50.0  # min ADU span so a faint frame isn't stretched hard
STRETCH_DITHER_FRAC = 0.5  # uniform dither amplitude as a fraction of one step
STRETCH_BRIGHT_BACKGROUND = 220.0  # show saturated/daylit focus frames directly

# Native camera frame size. target_pixel and centroid coordinates live in this
# (square) pixel space (see SharedStateObj.target_pixel, documented 512x512);
# the preview scales them down to the display resolution.
CAMERA_NATIVE_RES = 512


class UIPreview(UIModule):
    from PiFinder import tetra3

    __title__ = "CAMERA"
    __help_name__ = "camera"
    _STAR_ICON = "\uf005"  # NerdFont star icon (Font Awesome solid)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

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
            right=MarkingMenuOption(
                label=_("Gain"),
                menu_jump="camera_gain",
            ),
        )

    def _reset_focus_state(self):
        """Clear rolling focus-indicator state (history, stretch EMA points)."""
        # (timestamp, hfd) samples over the rolling window; hfd is None for a
        # frame with no usable star (a gap -- never carried forward).
        self.focus_history: deque = deque()
        self.last_focus_result = None
        self._last_focus_frame_time = 0.0
        # Display-stretch black/white points (raw ADU), EMA-smoothed.
        self._stretch_black = None
        self._stretch_white = None

    def active(self):
        """Reset the rolling focus history when the screen is entered."""
        self._reset_focus_state()

    def _measure_focus(self, raw_np):
        """Run the self-contained HFD detector on a raw frame and update state.

        Appends a timestamped sample (HFD or None for a gap), prunes the rolling
        window, and updates the EMA display-stretch points. All measurement is on
        the raw frame.
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

    def _focus_marker(self):
        """Return the best (min) HFD over the window, or None if no samples."""
        samples = [h for (_t, h) in self.focus_history if h is not None]
        return min(samples) if samples else None

    def _apply_stretch(self, image_obj):
        """Background-anchored linear stretch of a mode-'L' image (cosmetic).

        Replaces per-frame autocontrast: black/white points come from the
        detector's EMA-smoothed background/peak, so the stretch is stable and a
        starless frame does not get its noise amplified. The minimum span keeps
        a faint frame from being stretched hard, and a little uniform dither is
        added before quantising back to 8-bit so a narrow stretch doesn't band
        into visible contour steps. Cosmetic only -- HFD is measured on the raw
        frame, never on this.
        """
        if self._stretch_black is None or self._stretch_white is None:
            return image_obj
        black = self._stretch_black

        # The normal focus preview stretch assumes a dark sky: it maps the
        # measured background to black so faint stars stand out. With daytime or
        # saturated frames the background can already be near white; applying
        # that same mapping turns the whole preview black. Keep the current
        # exposure/gain intact and render those bright frames directly.
        if black >= STRETCH_BRIGHT_BACKGROUND:
            return image_obj

        span = max(self._stretch_white - black, STRETCH_MIN_SPAN)
        scale = 255.0 / span

        arr = np.asarray(image_obj, dtype=np.float32)
        stretched = (arr - black) * scale
        # Uniform dither, peak-to-peak ~ one output step, so a narrow stretch
        # blends across band boundaries instead of posterising into contours.
        dither = scale * STRETCH_DITHER_FRAC
        stretched += np.random.uniform(-dither, dither, size=arr.shape)
        np.clip(stretched, 0, 255, out=stretched)
        return Image.fromarray(stretched.astype(np.uint8), mode="L")

    def _orient_camera_image(self, image_obj):
        camera_rotation = self.config_object.get_option("camera_rotation")
        if camera_rotation is not None:
            return image_obj.rotate(int(camera_rotation) * -1)

        screen_direction = self.config_object.get_option("screen_direction")
        if screen_direction in ["right", "straight", "flat3", "as_bloom"]:
            return image_obj.rotate(90)
        return image_obj.rotate(270)

    def _raw_display_image(self):
        raw = self.shared_state.cam_raw()
        if raw is None:
            return None

        arr = np.asarray(raw)
        if arr.ndim != 2:
            return None

        arr = arr.astype(np.float32, copy=False)
        arr = arr[: arr.shape[0] // 2 * 2, : arr.shape[1] // 2 * 2]
        if arr.shape[0] >= 2 and arr.shape[1] >= 2:
            # Average the nominal Bayer quad. This also reduces the checker
            # pattern on mono sensors reported through an RGGB driver.
            arr = (
                arr[0::2, 0::2]
                + arr[0::2, 1::2]
                + arr[1::2, 0::2]
                + arr[1::2, 1::2]
            ) * 0.25

        low = float(np.percentile(arr, 1.0))
        high = float(np.percentile(arr, 99.5))
        if high <= low + 1.0:
            # This helper is only used after the processed preview has already
            # been classified as bright. A saturated or nearly flat bright raw
            # frame has no percentile span; stretching it from low to low+1
            # would map the whole image to black. Keep it bright instead.
            scaled = np.full(arr.shape, 255, dtype=np.float32)
        else:
            scaled = (arr - low) * (255.0 / (high - low))
        np.clip(scaled, 0, 255, out=scaled)
        image_obj = Image.fromarray(scaled.astype(np.uint8), mode="L")
        return self._orient_camera_image(image_obj)

    def draw_star_selectors(self):
        # Draw star selectors
        if self.star_list.shape[0] > 0:
            self.highlight_count = 3
            if self.star_list.shape[0] < self.highlight_count:
                self.highlight_count = self.star_list.shape[0]

            for _i in range(self.highlight_count):
                raw_y, raw_x = self.star_list[_i]
                # centroids are in native camera space; scale to the display
                star_x = int(raw_x * self.display_class.resX / CAMERA_NATIVE_RES)
                star_y = int(raw_y * self.display_class.resY / CAMERA_NATIVE_RES)

                x_direction = 1
                x_text_offset = 6
                y_direction = 1
                y_text_offset = -12

                # flip the marker/label when too close to the right edge or top
                if star_x > self.display_class.resX - 20:
                    x_direction = -1
                    x_text_offset = -10
                if star_y < self.display_class.titlebar_height + 21:
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
            solve_source = solution.solve_source if solution else None
            estimate_time = solution.estimate_time if solution else None
            if solve_source in ("CAM", "CAM_FAILED") and estimate_time:
                if time.time() - estimate_time < 10:
                    return str(solution.diagnostics.Matches)
        except Exception:
            pass
        return "-"

    def _hfd_to_y(self, hfd, plot_top, plot_bottom):
        """Map an HFD value to a screen y on the fixed log axis (low = bottom)."""
        clamped = min(max(hfd, HFD_AXIS_MIN), HFD_AXIS_MAX)
        norm = np.log(clamped / HFD_AXIS_MIN) / np.log(HFD_AXIS_MAX / HFD_AXIS_MIN)
        return int(plot_bottom - norm * (plot_bottom - plot_top))

    def draw_focus_strip(self):
        """Render the focus strip: big HFD readout, V-curve, marker, and HUD.

        Bottom band, on by default; square hides it. Persists across all zoom
        levels (HFD is zoom-independent). Layout: a large right-justified HFD
        number (the hero readout) fills the strip height; the V-curve and small
        labels sit in the freed left region.

        Geometry is resolution-flexible (ADR 0009): the band is a fixed fraction
        of the screen height (~38 px on the 128 panel, proportionally taller on
        a larger panel) and the label clearances derive from the small-font
        height, so the rows never collide with the V-curve as the font grows.
        """
        res_x = self.display_class.resX
        res_y = self.display_class.resY
        # Bottom band height scales with the screen (38 px / 128 px on the
        # 128 panel); strip_top was a 128-only literal (90) before #453.
        strip_top = res_y - round(res_y * 38 / 128)
        # Small-font height drives the label-row clearances (9 px on the 128
        # panel); deriving them keeps the rows clear of the V-curve at 176.
        small_h = self.fonts.small.height

        # Dim band so the overlay stays legible over a bright image.
        self.draw.rectangle([0, strip_top, res_x, res_y], fill=(0, 0, 0, 150))

        bright = self.colors.get(255)
        medium = self.colors.get(128)
        dim = self.colors.get(64)

        result = self.last_focus_result
        detected = str(result.n_used) if result is not None else "0"

        # --- HFD readout: right-justified in a fixed-width slot so the V-curve's
        # right edge never shifts as the value changes. A real reading is the big
        # hero number (filling the strip height); the no-reading states fall back
        # to a small dim hint rather than a giant placeholder glyph. ---
        big_font = self.fonts.huge
        slot_w = int(self.draw.textlength("00.0", font=big_font.font))
        num_right = res_x - 2
        num_left = num_right - slot_w
        num_mid_y = (strip_top + res_y) // 2 - 1

        if result is not None and result.median_hfd is not None:
            self.draw.text(
                (num_right, num_mid_y),
                f"{result.median_hfd:.1f}",
                font=big_font.font,
                fill=bright,
                anchor="rm",
            )
        else:
            # too_defocused = a star is there but too broad to measure (keep
            # adjusting toward focus); otherwise nothing usable was found.
            hint = _("keep going") if (result and result.too_defocused) else "—"
            outline_text(
                self.draw,
                (num_right, num_mid_y),
                hint,
                align="right",
                font=self.fonts.base,
                fill=dim,
                shadow_color=(0, 0, 0),
                stroke=1,
                anchor="rm",
            )

        # --- Left region: V-curve framed by small labels ---
        # plot_top clears the top label row; plot_bottom sits just above the
        # bottom label row -- both derived from the small-font height so they
        # track the font across resolutions (9 / 10 px on the 128 panel).
        plot_left = 2
        plot_right = num_left - 3
        plot_top = strip_top + small_h
        plot_bottom = res_y - small_h - 1

        # Top labels: exposure (left), matched-star count (right of the graph).
        # The matched 0 -> N jump still signals "sharp enough to solve".
        outline_text(
            self.draw,
            (plot_left, strip_top),
            self.format_exposure_display(),
            align="left",
            font=self.fonts.small,
            fill=medium,
            shadow_color=(0, 0, 0),
            stroke=1,
        )
        outline_text(
            self.draw,
            (plot_right, strip_top),
            f"{self._STAR_ICON}{self._matched_star_text()}",
            align="left",
            font=self.fonts.small,
            fill=medium,
            shadow_color=(0, 0, 0),
            stroke=1,
            anchor="ra",
        )

        # Bottom label: detected-star count (the self-contained detector).
        outline_text(
            self.draw,
            (plot_left, res_y - small_h),
            _("det {n}").format(n=detected),
            align="left",
            font=self.fonts.small,
            fill=medium,
            shadow_color=(0, 0, 0),
            stroke=1,
        )

        # --- V-curve + best-focus marker over the rolling window ---
        now = time.time()
        window_start = now - FOCUS_WINDOW_S
        span = max(plot_right - plot_left, 1)

        def x_of(ts):
            frac = (ts - window_start) / FOCUS_WINDOW_S
            return int(plot_left + min(max(frac, 0.0), 1.0) * span)

        marker = self._focus_marker()
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

            resX, resY = self.display_class.resX, self.display_class.resY
            display_image = raw_image
            stretch_display = True
            if (
                self._stretch_black is not None
                and self._stretch_black >= STRETCH_BRIGHT_BACKGROUND
            ):
                raw_display = self._raw_display_image()
                if raw_display is not None:
                    display_image = raw_display
                    stretch_display = False

            # Resize / zoom. Zoom crops a centred region of the native camera
            # frame (half of it for 2x, a quarter for 4x) then scales to the
            # display, so the zoom factor stays 2x / 4x at any resolution.
            # (Shared with the daytime-align screen via ui.camera_render.)
            image_obj = resize_for_display(
                display_image, (resX, resY), self.zoom_level
            )

            # Background-anchored linear stretch (replaces autocontrast), then RED.
            # Stretch on a single luminance band (debug frames are RGB; hardware
            # frames are already mode "L").
            image_obj = image_obj.convert("L")
            if stretch_display:
                image_obj = self._apply_stretch(image_obj)
            image_obj = image_obj.convert("RGB")
            image_obj = ImageChops.multiply(image_obj, self.colors.red_image)

            self.screen.paste(image_obj)
            self.last_update = last_image_time

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
