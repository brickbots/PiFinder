#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module contains the UIPreview class, a UI module for displaying and interacting with camera images.

It handles image processing, including background subtraction and gamma correction, and provides zoom
functionality. It also manages a marking menu for adjusting camera settings and draws reticles and star
selectors on the images.
"""

import sys
import numpy as np
import time

from PIL import Image, ImageChops, ImageOps

from PiFinder.ui.marking_menus import MarkingMenuOption, MarkingMenu
from PiFinder import utils
from PiFinder.ui.base import UIModule
from PiFinder.ui.ui_utils import outline_text
from PiFinder.image_util import (
    gamma_correct_high,
    gamma_correct_med,
    gamma_correct_low,
    subtract_background,
)

sys.path.append(str(utils.tetra3_dir))


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

        # Info overlay toggle (use square button)
        self.show_info_overlay = False

        # Marking menu definition
        self.marking_menu = MarkingMenu(
            left=MarkingMenuOption(
                label=_("Exposure"),
                menu_jump="camera_exposure",
            ),
            down=MarkingMenuOption(
                label=_("Gamma"),
                callback=MarkingMenu(
                    up=MarkingMenuOption(label=_("Off"), callback=self.mm_change_gamma),
                    left=MarkingMenuOption(
                        label=_("High"), callback=self.mm_change_gamma
                    ),
                    down=MarkingMenuOption(
                        label=_("Medium"),
                        callback=self.mm_change_gamma,
                        selected=True,  # TODO Selected item should be read from config.
                    ),
                    right=MarkingMenuOption(
                        label=_("Low"), callback=self.mm_change_gamma
                    ),
                ),
            ),
            right=MarkingMenuOption(
                label=_("BG Sub"),  # TRANSLATE: Background Subtraction context menu
                callback=MarkingMenu(
                    up=MarkingMenuOption(label=_("Off"), callback=self.mm_change_bgsub),
                    left=MarkingMenuOption(
                        label=_("Full"), callback=self.mm_change_bgsub
                    ),
                    down=MarkingMenuOption(),
                    right=MarkingMenuOption(
                        label=_("Half"),
                        callback=self.mm_change_bgsub,
                        selected=True,  # TODO Selected item should be read from config.
                    ),
                ),
            ),
        )

    def mm_change_gamma(self, marking_menu, menu_item):
        """
        Called to change gamma adjust value
        """
        marking_menu.select_none()
        menu_item.selected = True

        self.config_object.set_option(
            "session.camera_gamma", menu_item.label
        )  # TODO I18N: context menu need display names
        return True

    def mm_change_bgsub(self, marking_menu, menu_item):
        """
        Called to change bg sub amount
        """
        marking_menu.select_none()
        menu_item.selected = True

        self.config_object.set_option("session.camera_bg_sub", menu_item.label)
        return True

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
                    return f"{exp_sec:g}s"
        except Exception:
            pass
        return "N/A"

    def draw_info_overlay(self):
        """Draw info overlay with exposure time and star count."""
        if not self.show_info_overlay:
            return

        # Get exposure info
        exposure_text = self.format_exposure_display()

        # Get star count from solution
        star_count_text = "---"
        try:
            solution = self.shared_state.solution()
            solve_source = solution.get("solve_source") if solution else None

            # Show star count for camera solves (successful or failed)
            if solve_source in ("CAM", "CAM_FAILED"):
                matched_stars = solution.get("Matches", 0)
                star_count_text = str(matched_stars)
        except Exception:
            pass

        # Position below title bar (titlebar_height is typically 17)
        y_offset = self.display_class.titlebar_height + 2

        # Draw exposure text with black outline using utility function
        outline_text(
            self.draw,
            (2, y_offset),
            exposure_text,
            align="left",
            font=self.fonts.bold,
            fill=(192, 0, 0),  # Medium bright red
            shadow_color=(0, 0, 0),  # Black outline
            stroke=1,
        )

        # Draw star count with NerdFont icon - right-aligned to prevent jitter
        stars_text = f"{self._STAR_ICON} {star_count_text}"

        outline_text(
            self.draw,
            (126, y_offset),
            stars_text,
            align="left",
            font=self.fonts.bold,
            fill=(192, 0, 0),  # Medium bright red
            shadow_color=(0, 0, 0),  # Black outline
            stroke=1,
            anchor="ra",  # Right-anchor: right edge at x=126
        )

    def update(self, force=False):
        if force:
            self.last_update = 0
        # display an image
        last_image_time = self.shared_state.last_image_metadata()["exposure_end"]
        image_updated = False
        if last_image_time > self.last_update:
            image_updated = True
            image_obj = self.camera_image.copy()

            # Resize
            if self.zoom_level == 0:
                image_obj = image_obj.resize((128, 128))
            elif self.zoom_level == 1:
                image_obj = image_obj.resize((256, 256))
                image_obj = image_obj.crop((64, 64, 192, 192))
            elif self.zoom_level == 2:
                # no resize, just crop
                image_obj = image_obj.crop((192, 192, 320, 320))

            bg_sub = self.config_object.get_option("session.camera_bg_sub", "Half")
            if bg_sub == "Half":
                image_obj = subtract_background(image_obj, percent=0.5)
            elif bg_sub == "Full":
                image_obj = subtract_background(image_obj, percent=1)
            image_obj = image_obj.convert("RGB")
            image_obj = ImageChops.multiply(image_obj, self.colors.red_image)
            image_obj = ImageOps.autocontrast(image_obj)

            gamma_adjust = self.config_object.get_option("session.camera_gamma", "Med")
            if gamma_adjust == "Low":
                image_obj = Image.eval(image_obj, gamma_correct_low)
            elif gamma_adjust == "Medium":
                image_obj = Image.eval(image_obj, gamma_correct_med)
            elif gamma_adjust == "High":
                image_obj = Image.eval(image_obj, gamma_correct_high)

            self.screen.paste(image_obj)
            self.last_update = last_image_time

            if self.zoom_level > 0:
                zoom_number = self.zoom_level * 2
                self.draw.text(
                    (75, 112),
                    _("Zoom x{zoom_number}").format(zoom_number=zoom_number),
                    font=self.fonts.bold.font,
                    fill=self.colors.get(128),
                )
            else:
                self.draw_reticle()

        # Draw info overlay if enabled and image was updated
        # (image paste cleared the screen, so we need to redraw overlay)
        if image_updated or force:
            self.draw_info_overlay()

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
        """Toggle info overlay on/off with square button."""
        self.show_info_overlay = not self.show_info_overlay
        self.update(force=True)
