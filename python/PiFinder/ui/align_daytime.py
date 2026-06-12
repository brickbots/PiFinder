#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Daytime alignment screen (issue #455).

A purely manual alignment that works in daylight, with no plate solve. The user
centres a distant object in the eyepiece; the rigidly-mounted camera sees that
object somewhere in its frame; the user marks that pixel by eye and we write it
straight to ``target_pixel`` -- the same destination the solve-based
``ui/align.py::align_on_radec`` writes (``shared_state.set_target_pixel`` +
``config.set_option("target_pixel", ...)``), reached by hand.

See docs/ax/positioning/CONTEXT.md ("Daytime alignment" vs "Solve-based
alignment") for the vocabulary. Both write the same ``target_pixel``, stored as
(Y, X) in the square 512px native camera frame.

Interaction (the screen starts inactive, like the solve-based Align screen):

* SQUARE starts the alignment process.
* Coarse selection: up to three rounds of 2x2 quadrant picks using the keypad
  corners (7 = top-left, 9 = top-right, 1 = bottom-left, 3 = bottom-right),
  each round shrinking the selected region. The first arrow press (or the third
  round) switches to fine mode.
* Fine mode: arrow keys nudge the selector one display pixel at a time.
* ``+`` / ``-`` override the exposure manually; the long-press marking menu can
  recentre the selector or hand exposure back to auto.
* SQUARE saves (writes ``target_pixel`` and exits); ``0`` cancels.
"""

from PIL import ImageOps

from PiFinder.ui.base import UIModule
from PiFinder.ui.camera_render import resize_for_display
from PiFinder.ui.marking_menus import MarkingMenuOption, MarkingMenu

# Native camera/solver frame size. target_pixel is stored in this (square)
# pixel space (see SharedStateObj.target_pixel, documented as 512x512); the
# daytime screen tracks the selector in display space and converts on save.
CAMERA_NATIVE_RES = 512

# Keypad corners that pick a quadrant, matching the TKL layout (789 is the top
# row): 7 = top-left, 9 = top-right, 1 = bottom-left, 3 = bottom-right.
QUADRANT_KEYS = (7, 9, 1, 3)

# Coarse rounds before fine mode is forced. Three rounds shrink a full-frame
# region to ~1/8 of the display width (16px cells on the 128 panel, ~22px on
# 176) -- the legibility floor for the on-screen quadrant labels.
MAX_QUADRANT_ROUNDS = 3

WHITE = (255, 255, 255)
GRID = (128, 128, 128)


def quadrant_subrect(region, corner):
    """Return the sub-rectangle for a keypad corner within ``region``.

    ``region`` is ``(x0, y0, x1, y1)`` in display space; ``corner`` is one of
    7/9/1/3 (top-left, top-right, bottom-left, bottom-right). Coordinates are
    kept as floats so repeated subdivision doesn't accumulate rounding error.
    """
    x0, y0, x1, y1 = region
    mx = (x0 + x1) / 2
    my = (y0 + y1) / 2
    if corner == 7:  # top-left
        return (x0, y0, mx, my)
    if corner == 9:  # top-right
        return (mx, y0, x1, my)
    if corner == 1:  # bottom-left
        return (x0, my, mx, y1)
    if corner == 3:  # bottom-right
        return (mx, my, x1, y1)
    raise ValueError(f"Not a quadrant corner key: {corner!r}")


def rect_center(region):
    """Centre point ``(x, y)`` of a ``(x0, y0, x1, y1)`` display-space rect."""
    x0, y0, x1, y1 = region
    return ((x0 + x1) / 2, (y0 + y1) / 2)


def display_to_native(selector, resolution, native_res=CAMERA_NATIVE_RES):
    """Convert a display-space ``(x, y)`` selector to a native ``(Y, X)`` pixel.

    ``target_pixel`` is stored as (Y, X) in the square native camera frame; the
    daytime image fills the whole display, so the mapping is a straight per-axis
    scale from the display resolution to the native frame.
    """
    res_x, res_y = resolution
    sel_x, sel_y = selector
    native_x = sel_x * native_res / res_x
    native_y = sel_y * native_res / res_y
    return (native_y, native_x)


class UIAlignDaytime(UIModule):
    __title__ = "ALIGN DAY"
    __help_name__ = ""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Exposure config in effect before we entered, restored on inactive().
        self._saved_camera_exp = None
        # "auto" = native (driver) auto-exposure; "manual" = user +/- override.
        self.exposure_mode = "auto"

        self._reset_alignment_state()
        self.last_update = 0.0

        # Long-press marking menu: recentre the selector / hand exposure back to
        # the camera's auto-exposure.
        self.marking_menu = MarkingMenu(
            left=MarkingMenuOption(
                label=_("Center"),
                callback=self._mm_reset_center,
            ),
            down=MarkingMenuOption(),
            right=MarkingMenuOption(
                label=_("Exp Auto"),
                callback=self._mm_exposure_auto,
            ),
        )

    # ------------------------------------------------------------------ #
    # State
    # ------------------------------------------------------------------ #

    def _reset_alignment_state(self):
        """Return to the inactive, full-frame starting state."""
        self.started = False
        self.fine_mode = False
        self.quadrant_round = 0
        self.region = (0, 0, self.display_class.resX, self.display_class.resY)
        self.selector = (self.display_class.centerX, self.display_class.centerY)

    def active(self):
        """Switch the camera to a daylight exposure and reset the screen.

        The live preview is daytime-exposed immediately so the user can frame a
        distant object; SQUARE then engages the selector. The prior exposure
        mode is restored in inactive().
        """
        self._saved_camera_exp = self.config_object.get_option("camera_exp")
        self.command_queues["camera"].put("set_exp:native")
        self.exposure_mode = "auto"
        self._reset_alignment_state()
        self.last_update = 0.0
        self.update(force=True)

    def inactive(self):
        """Restore the exposure mode that was in effect before we entered."""
        saved = self._saved_camera_exp
        if saved == "auto":
            self.command_queues["camera"].put("set_exp:auto")
        elif saved is not None:
            self.command_queues["camera"].put(f"set_exp:{saved}")
        else:
            # No saved value -- re-enable solver auto-exposure as a safe default.
            self.command_queues["camera"].put("set_exp:auto")

    # ------------------------------------------------------------------ #
    # Rendering
    # ------------------------------------------------------------------ #

    def update(self, force=False):
        if force:
            self.last_update = 0.0

        metadata = self.shared_state.last_image_metadata()
        last_image_time = metadata["exposure_end"]

        if last_image_time > self.last_update or force:
            raw_image = self.camera_image.copy()
            frame = resize_for_display(
                raw_image, (self.display_class.resX, self.display_class.resY)
            )
            # Full-brightness grayscale: dark adaptation is irrelevant in
            # daylight, so skip the red night-vision mask. autocontrast lifts a
            # distant object out of a bright sky.
            frame = ImageOps.autocontrast(frame.convert("L")).convert("RGB")
            self.screen.paste(frame)

            self._draw_overlay()
            self.last_update = last_image_time

        # Hide the title bar once alignment is engaged (full-frame image, like
        # the solve-based align screen); show it in the inactive state.
        return self.screen_update(title_bar=not self.started)

    def _draw_overlay(self):
        if not self.started:
            self._draw_inactive_overlay()
            return

        if not self.fine_mode:
            self._draw_quadrant_grid()
        self._draw_crosshair(self.selector)
        self._draw_exposure_label()
        self._draw_hint(_("{icon} SAVE  0 CANCEL").format(icon=self._SQUARE_))

    def _draw_inactive_overlay(self):
        # Show the current saved alignment point for context, then the start hint.
        target = self.config_object.get_option("target_pixel", None)
        if target:
            sx = target[1] * self.display_class.resX / CAMERA_NATIVE_RES
            sy = target[0] * self.display_class.resY / CAMERA_NATIVE_RES
            self._draw_crosshair((sx, sy))
        # TRANSLATORS: hint bar; preserve leading spaces for layout
        self._draw_hint(_("  {icon} START ALIGN").format(icon=self._SQUARE_))

    def _draw_quadrant_grid(self):
        """Draw the 2x2 grid over the current region with corner labels."""
        x0, y0, x1, y1 = (round(v) for v in self.region)
        mx = round((x0 + x1) / 2)
        my = round((y0 + y1) / 2)

        self.draw.rectangle([x0, y0, x1 - 1, y1 - 1], outline=GRID)
        self.draw.line([mx, y0, mx, y1], fill=GRID)
        self.draw.line([x0, my, x1, my], fill=GRID)

        # Corner digit in the top-left of each cell.
        cells = {7: (x0, y0), 9: (mx, y0), 1: (x0, my), 3: (mx, my)}
        for digit, (cx, cy) in cells.items():
            self.draw.text(
                (cx + 3, cy + 2),
                str(digit),
                font=self.fonts.bold.font,
                fill=WHITE,
            )

    def _draw_crosshair(self, pos):
        """Draw a centred cross (with a gap) at a display-space point."""
        x = round(pos[0])
        y = round(pos[1])
        self.draw.line([x, y - 8, x, y - 3], fill=WHITE)
        self.draw.line([x, y + 3, x, y + 8], fill=WHITE)
        self.draw.line([x - 8, y, x - 3, y], fill=WHITE)
        self.draw.line([x + 3, y, x + 8, y], fill=WHITE)

    def _exposure_text(self):
        if self.exposure_mode == "auto":
            return _("AUTO")
        metadata = self.shared_state.last_image_metadata()
        exp = metadata.get("exposure_time")
        if exp:
            exp_sec = exp / 1_000_000
            if exp_sec < 0.1:
                return f"{int(exp_sec * 1000)}ms"
            return f"{exp_sec:.2g}s"
        return "?"

    def _draw_exposure_label(self):
        self.draw.text(
            (2, 1),
            self._exposure_text(),
            font=self.fonts.small.font,
            fill=GRID,
        )

    def _draw_hint(self, text):
        self.draw.text(
            (15, self.display_class.resY - self.fonts.base.height - 2),
            text,
            font=self.fonts.base.font,
            fill=WHITE,
        )

    # ------------------------------------------------------------------ #
    # Selector movement
    # ------------------------------------------------------------------ #

    def _select_quadrant(self, corner):
        self.region = quadrant_subrect(self.region, corner)
        self.selector = rect_center(self.region)
        self.quadrant_round += 1
        if self.quadrant_round >= MAX_QUADRANT_ROUNDS:
            # Cells are at the legibility floor -- finish with fine nudges.
            self.fine_mode = True
        self.update(force=True)

    def _move_selector(self, dx, dy):
        x = min(max(self.selector[0] + dx, 0), self.display_class.resX - 1)
        y = min(max(self.selector[1] + dy, 0), self.display_class.resY - 1)
        self.selector = (x, y)

    def _arrow(self, dx, dy):
        """Handle an arrow press: first one switches to fine mode, then nudges."""
        if not self.started:
            return
        if not self.fine_mode:
            # First arrow press switches to fine mode without moving, so the
            # quadrant centre isn't nudged off by accident.
            self.fine_mode = True
        else:
            self._move_selector(dx, dy)
        self.update(force=True)

    # ------------------------------------------------------------------ #
    # Save / cancel
    # ------------------------------------------------------------------ #

    def _save_alignment(self):
        target_pixel = display_to_native(
            self.selector,
            (self.display_class.resX, self.display_class.resY),
        )
        self.shared_state.set_target_pixel(target_pixel)
        self.config_object.set_option("target_pixel", target_pixel)
        self.started = False
        self.message(_("Aligned!"), 1)
        if self.remove_from_stack:
            self.remove_from_stack()

    def _cancel(self):
        self.started = False
        if self.remove_from_stack:
            self.remove_from_stack()

    # ------------------------------------------------------------------ #
    # Key handlers
    # ------------------------------------------------------------------ #

    def key_square(self):
        if not self.started:
            self.started = True
            self.fine_mode = False
            self.quadrant_round = 0
            self.region = (0, 0, self.display_class.resX, self.display_class.resY)
            self.selector = (self.display_class.centerX, self.display_class.centerY)
            self.update(force=True)
        else:
            self._save_alignment()

    def key_number(self, number):
        if number == 0:
            # Cancel / exit without changing the alignment.
            self._cancel()
            return
        if self.started and not self.fine_mode and number in QUADRANT_KEYS:
            self._select_quadrant(number)

    def key_up(self):
        self._arrow(0, -1)

    def key_down(self):
        self._arrow(0, 1)

    def key_right(self):
        self._arrow(1, 0)

    def key_left(self):
        if not self.started:
            # Inactive: allow normal back-out navigation.
            return True
        # Active: left arrow is consumed for selector movement, don't pop.
        self._arrow(-1, 0)
        return False

    def key_plus(self):
        self.command_queues["camera"].put("exp_up")
        self.exposure_mode = "manual"

    def key_minus(self):
        self.command_queues["camera"].put("exp_dn")
        self.exposure_mode = "manual"

    # ------------------------------------------------------------------ #
    # Marking menu callbacks
    # ------------------------------------------------------------------ #

    def _mm_reset_center(self, marking_menu, menu_item):
        self.region = (0, 0, self.display_class.resX, self.display_class.resY)
        self.selector = (self.display_class.centerX, self.display_class.centerY)
        self.quadrant_round = 0
        self.fine_mode = False
        self.update(force=True)
        return True  # exit the marking menu

    def _mm_exposure_auto(self, marking_menu, menu_item):
        self.command_queues["camera"].put("set_exp:native")
        self.exposure_mode = "auto"
        return True  # exit the marking menu
