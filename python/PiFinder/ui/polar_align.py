#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Polar Alignment UI

Guides the user through capturing two or three plate solves while an
equatorial platform is rotated around its polar axis, then shows the
required correction as a live target: drive the marker to (0,0) using
the platform's alt/az adjusters and the polar axis is aligned.
"""

import math
import time
from datetime import timedelta
from enum import Enum
from typing import Any, List, Optional, Tuple, TYPE_CHECKING

from PiFinder import calc_utils
from PiFinder.polar_alignment import (
    correction_target,
    get_platform_adjustments,
)
from PiFinder.ui.base import UIModule
from PiFinder.ui.marking_menus import MarkingMenu, MarkingMenuOption
from PiFinder.ui.ui_utils import draw_pointing_instructions

if TYPE_CHECKING:

    def _(a) -> Any:
        return a


MAX_POINTS = 3
# A camera solve older than this is considered stale for capture/guidance
SOLVE_FRESH_SECS = 5.0


def wrap180(angle: float) -> float:
    """Wrap angle in degrees to (-180, +180]."""
    return (angle + 180.0) % 360.0 - 180.0


class PAState(Enum):
    """Polar alignment wizard states"""

    INTRO = "intro"  # Explain the procedure
    AIM = "aim"  # Waiting for user to confirm a capture
    WAIT_SOLVE = "wait_solve"  # Waiting for a fresh camera solve
    ADJUST = "adjust"  # Live target display for the alt/az knobs


class UIPolarAlign(UIModule):
    """
    Polar alignment wizard for equatorial platforms.

    Steps:
    1. Capture a plate solve (square)
    2. Rotate the platform, capture a second solve
    3. Optionally rotate further and capture a third solve (or 0 to
       solve with two points)
    4. Adjust the platform alt/az knobs until the arrows read 0,0
    """

    __title__ = "POLAR ALIGN"
    __help_name__ = ""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.state = PAState.INTRO
        self.solves: List[Tuple[float, float, float, float]] = []
        self.capture_request_time = 0.0
        self.result: Optional[dict] = None
        self.target_altaz: Optional[Tuple[float, float]] = None

        # Marking menu definition
        self.marking_menu = MarkingMenu(
            left=MarkingMenuOption(),
            down=MarkingMenuOption(),
            right=MarkingMenuOption(),
        )

    def active(self):
        self.update(force=True)

    def _reset(self):
        self.state = PAState.INTRO
        self.solves = []
        self.result = None
        self.target_altaz = None

    def _solve_datetime(self, timestamp: float):
        """UTC datetime of a time.time()-based solve timestamp."""
        dt = self.shared_state.datetime()
        if dt is None:
            return None
        return dt - timedelta(seconds=time.time() - timestamp)

    def _cam_solve_age(self) -> Optional[float]:
        solution = self.shared_state.solution()
        if not solution or not solution.get("cam_solve_time"):
            return None
        return time.time() - solution["cam_solve_time"]

    def _try_capture(self):
        """
        In WAIT_SOLVE: capture the first camera solve that completed
        after the user pressed square.
        """
        solution = self.shared_state.solution()
        if not solution:
            return
        cam_time = solution.get("cam_solve_time")
        cam = solution.get("camera_solve", {})
        if (
            cam_time
            and cam_time > self.capture_request_time
            and cam.get("RA") is not None
        ):
            self.solves.append((cam["RA"], cam["Dec"], cam["Roll"], cam_time))
            if len(self.solves) >= MAX_POINTS:
                self._compute()
            else:
                self.state = PAState.AIM

    def _compute(self):
        """
        Run the polar alignment calculation on the captured solves and
        build the fixed ground-frame target for the adjustment phase.
        """
        location = self.shared_state.location()
        dt_last = self._solve_datetime(self.solves[-1][3])
        if not self.shared_state.altaz_ready() or dt_last is None:
            self.message(_("Need GPS lock"), 2)
            self.state = PAState.AIM
            return

        calc_utils.sf_utils.set_location(location.lat, location.lon, location.altitude)
        lst_deg = calc_utils.sf_utils.get_lst_hrs(dt_last) * 15.0
        t_last = calc_utils.sf_utils.ts.from_datetime(dt_last)
        jyear = 2000.0 + (t_last.tt - 2451545.0) / 365.25

        dAlt, dAz, sweep, axis_ra, axis_dec, fit_quality = get_platform_adjustments(
            self.solves, location.lat, lst_deg, observation_jyear=jyear
        )

        if math.isnan(axis_ra):
            # Not enough rotation between solves: drop the last point so
            # the user can rotate further and capture it again.
            self.solves.pop()
            self.message(_("Rotate more"), 2)
            self.state = PAState.AIM
            return

        ra_target, dec_target, _roll_target = correction_target(
            axis_ra, axis_dec, self.solves[-1][:3], observation_jyear=jyear
        )
        # The correction target as a fixed ground direction at the epoch
        # of the last solve: where the boresight must end up after the
        # alt/az knobs are adjusted.
        alt_t, az_t = calc_utils.sf_utils.radec_to_altaz(
            ra_target, dec_target, dt_last, atmos=False
        )
        self.target_altaz = (alt_t, az_t)
        self.result = {
            "dAlt": dAlt,
            "dAz": dAz,
            "sweep": sweep,
            "fit_quality": fit_quality,
            "n_points": len(self.solves),
        }
        self.state = PAState.ADJUST

    def _current_offset(self) -> Optional[Tuple[float, float, float]]:
        """
        Live (point_az, point_alt, solve_age): how far to move the
        boresight with the knobs to reach the correction target, in
        ground-frame degrees (push-to convention: target - current).
        (0, 0) means the knobs are set correctly.
        """
        solution = self.shared_state.solution()
        if not solution or self.target_altaz is None:
            return None
        cam_time = solution.get("cam_solve_time")
        cam = solution.get("camera_solve", {})
        if not cam_time or cam.get("RA") is None:
            return None
        dt_solve = self._solve_datetime(cam_time)
        if dt_solve is None:
            return None
        alt_c, az_c = calc_utils.sf_utils.radec_to_altaz(
            cam["RA"], cam["Dec"], dt_solve, atmos=False
        )
        alt_t, az_t = self.target_altaz
        return (
            wrap180(az_t - az_c),
            alt_t - alt_c,
            time.time() - cam_time,
        )

    def update(self, force=False):
        self.clear_screen()

        if self.state == PAState.WAIT_SOLVE:
            self._try_capture()

        if self.state == PAState.INTRO:
            self._draw_intro()
        elif self.state == PAState.AIM:
            self._draw_aim()
        elif self.state == PAState.WAIT_SOLVE:
            self._draw_wait_solve()
        elif self.state == PAState.ADJUST:
            self._draw_adjust()

        return self.screen_update()

    def _draw_lines(self, y, lines, fill=192):
        for line in lines:
            self.draw.text(
                (10, y),
                line,
                font=self.fonts.base.font,
                fill=self.colors.get(fill),
            )
            y += self.fonts.base.height + 2
        return y

    def _draw_hints(self, line1, line2=None):
        y = self.display_class.resY - self.fonts.base.height - 2
        if line2 is not None:
            self.draw.text(
                (10, y),
                line2,
                font=self.fonts.base.font,
                fill=self.colors.get(128),
            )
            y -= self.fonts.base.height + 2
        self.draw.text(
            (10, y),
            line1,
            font=self.fonts.base.font,
            fill=self.colors.get(255),
        )

    def _draw_intro(self):
        y = self.display_class.titlebar_height + 6
        self.draw.text(
            (10, y),
            _("PLATFORM PA"),
            font=self.fonts.bold.font,
            fill=self.colors.get(255),
        )
        y += self.fonts.bold.height + 6
        y = self._draw_lines(
            y,
            [
                _("Solve 2-3 points,"),
                _("rotating platform"),
                _("between them."),
                _("Keep scope fixed"),
                _("on the mount."),
            ],
        )
        if not self.shared_state.altaz_ready():
            self._draw_lines(y + 2, [_("GPS: waiting...")], fill=128)
        self._draw_hints(_(f"{self._SQUARE_} START"))

    def _draw_aim(self):
        point_number = len(self.solves) + 1
        y = self.display_class.titlebar_height + 6
        self.draw.text(
            (10, y),
            _("POINT") + f" {point_number}/{MAX_POINTS}",
            font=self.fonts.bold.font,
            fill=self.colors.get(255),
        )
        y += self.fonts.bold.height + 6

        if point_number == 1:
            guidance = [
                _("Aim away from"),
                _("the pole, wait"),
                _("for a solve."),
            ]
        elif point_number == 2:
            guidance = [
                _("Rotate platform"),
                _("10° or more."),
            ]
        else:
            guidance = [
                _("Rotate further"),
                _("or solve now."),
            ]
        y = self._draw_lines(y, guidance)

        age = self._cam_solve_age()
        if age is not None and age < SOLVE_FRESH_SECS:
            solve_text = _("Solve") + f" {age:.0f}s"
            solve_fill = 255
        else:
            solve_text = _("No recent solve")
            solve_fill = 96
        self._draw_lines(y + 4, [solve_text], fill=solve_fill)

        self._draw_hints(
            _(f"{self._SQUARE_} CAPTURE  {self._MINUS_} CANCEL"),
            _("0 SOLVE NOW") if point_number > 2 else None,
        )

    def _draw_wait_solve(self):
        y = self.display_class.titlebar_height + 6
        dots = "." * (int(time.time() * 2) % 4)
        self.draw.text(
            (10, y),
            _("CAPTURING") + dots,
            font=self.fonts.bold.font,
            fill=self.colors.get(255),
        )
        y += self.fonts.bold.height + 6
        self._draw_lines(
            y,
            [
                _("Hold still,"),
                _("waiting for"),
                _("camera solve."),
            ],
        )
        self._draw_hints(_(f"{self._MINUS_} BACK"))

    def _draw_adjust(self):
        y = self.display_class.titlebar_height + 4
        if self.result is not None:
            info = f"{self.result['n_points']}" + _("pt")
            info += f" {abs(self.result['sweep']):.0f}°"
            fit_quality = self.result["fit_quality"]
            if not math.isnan(fit_quality):
                info += " " + _("fit") + f" {fit_quality:.1f}"
                if fit_quality > 3.0:
                    info += "!"
            self.draw.text(
                (10, y),
                info,
                font=self.fonts.bold.font,
                fill=self.colors.get(255),
            )
        y += self.fonts.bold.height + 4
        self.draw.text(
            (10, y),
            _(f"{self._SQUARE_} REDO  {self._MINUS_} CANCEL"),
            font=self.fonts.base.font,
            fill=self.colors.get(128),
        )

        offset = self._current_offset()
        if offset is None:
            dots = "." * (int(time.time() * 2) % 4)
            self.draw.text(
                (10, self.display_class.resY - (self.fonts.huge.height * 1.5)),
                _("No solve") + dots,
                font=self.fonts.large.font,
                fill=self.colors.get(255),
            )
            return

        point_az, point_alt, age = offset
        brightness = 255 if age < SOLVE_FRESH_SECS else 128
        draw_pointing_instructions(self, point_az, point_alt, brightness)

    def key_square(self):
        if self.state == PAState.INTRO:
            self.state = PAState.AIM
        elif self.state == PAState.AIM:
            self.capture_request_time = time.time()
            self.state = PAState.WAIT_SOLVE
        elif self.state == PAState.ADJUST:
            self._reset()
            self.state = PAState.AIM
        self.update(force=True)

    def key_minus(self):
        if self.state == PAState.WAIT_SOLVE:
            # Abort just this capture, keep earlier points
            self.state = PAState.AIM
        elif self.state != PAState.INTRO:
            self._reset()
            self.message(_("Cancelled"), 1)
        self.update(force=True)

    def key_number(self, number):
        if number == 0 and self.state == PAState.AIM and len(self.solves) >= 2:
            self._compute()
            self.update(force=True)
