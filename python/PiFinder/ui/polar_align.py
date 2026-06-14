#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Polar Alignment UI

Guides the user through capturing two or three plate solves while an
equatorial platform is rotated around its polar axis, then shows the
required correction as a live target. During capture, keep the telescope
fixed relative to the platform and rotate only the platform. During
adjustment, use only the platform's altitude and azimuth adjusters until
the displayed push-to offsets reach zero.
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
    STATS = "stats"  # Read-only detail view of the last result


class UIPolarAlign(UIModule):
    """
    Polar alignment wizard for equatorial platforms.

    Steps:
    1. Aim away from the celestial pole and capture a fresh plate solve
       with SQUARE.
    2. Rotate the equatorial platform by at least about 10 degrees,
       keeping the telescope fixed on the mount, then capture point 2.
    3. Optionally rotate farther and capture point 3, or press 0 after
       point 2 to solve with two points.
    4. Adjust the platform's altitude and azimuth knobs until the live
       push-to arrows read 0,0. Do not use the telescope's normal
       pointing controls during this phase.
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
        # State to return to when leaving the STATS detail view.
        self._stats_return = PAState.ADJUST
        # RA/Dec-only axis fit, ignoring camera roll (e.g. after a camera
        # flop). A session-level preference toggled from the marking menu;
        # only affects three-point solves.
        self.ignore_roll = False

        # Marking menu (long-press square): advanced actions. The roll
        # option's label tracks the current state (see _update_roll_label).
        self.marking_menu = MarkingMenu(
            left=MarkingMenuOption(label=_("REDO PT"), callback=self.mm_redo_point),
            down=MarkingMenuOption(callback=self.mm_toggle_roll),
            right=MarkingMenuOption(label=_("STATS"), callback=self.mm_stats),
        )
        self._update_roll_label()

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

    def _camera_solve(self):
        """
        Latest camera plate-solve as (Pointing, solve_time), or
        (None, None) if no solve is available.

        ``pointing.camera.solve`` is the camera-axis RA/Dec/Roll from the
        last plate-solve and is never touched by the IMU, so it is the
        right source for polar alignment regardless of mount motion.
        ``last_solve_success`` is its time.time() epoch.
        """
        solution = self.shared_state.solution()
        if not solution or not solution.has_pointing():
            return None, None
        cam = solution.pointing.camera.solve
        solve_time = solution.last_solve_success
        if cam is None or solve_time is None or cam.RA is None:
            return None, None
        return cam, solve_time

    def _cam_solve_age(self) -> Optional[float]:
        _cam, solve_time = self._camera_solve()
        if solve_time is None:
            return None
        return time.time() - solve_time

    def _try_capture(self):
        """
        In WAIT_SOLVE: capture the first camera solve that completed
        after the user pressed square.
        """
        cam, solve_time = self._camera_solve()
        if cam is None or solve_time is None:
            return
        if solve_time > self.capture_request_time:
            self.solves.append((cam.RA, cam.Dec, cam.Roll, solve_time))
            if len(self.solves) >= MAX_POINTS:
                self._compute()
            else:
                self.state = PAState.AIM

    def _gps_ready(self) -> bool:
        """True when location/time are available to compute a result."""
        if not self.shared_state.altaz_ready():
            return False
        return self._solve_datetime(self.solves[-1][3]) is not None

    def _recompute(self) -> bool:
        """
        Run the polar alignment calculation on the captured solves and build
        the fixed ground-frame target for the adjustment phase. Sets
        self.result and self.target_altaz and returns True on success;
        returns False (leaving them unchanged) if GPS isn't ready or the
        rotation is too small to determine an axis. Silent and
        non-destructive: it does not message, change state, or mutate
        self.solves -- callers decide what to do on each failure.
        """
        if not self._gps_ready():
            return False
        location = self.shared_state.location()
        dt_last = self._solve_datetime(self.solves[-1][3])

        calc_utils.sf_utils.set_location(location.lat, location.lon, location.altitude)
        lst_deg = calc_utils.sf_utils.get_lst_hrs(dt_last) * 15.0  # 15 = 360°/24h
        t_last = calc_utils.sf_utils.ts.from_datetime(dt_last)
        jyear = 2000.0 + (t_last.tt - 2451545.0) / 365.25

        dAlt, dAz, sweep, axis_ra, axis_dec, fit_quality = get_platform_adjustments(
            self.solves,
            location.lat,
            lst_deg,
            ignore_roll=self.ignore_roll,
            observation_jyear=jyear,
        )

        if math.isnan(axis_ra):
            return False

        ra_target, dec_target, _roll_target = correction_target(
            axis_ra,
            axis_dec,
            self.solves[-1][:3],
            location.lat,
            lst_deg,
            observation_jyear=jyear,
        )

        # The correction target as a fixed ground direction at the epoch
        # of the last solve. During adjustment the user moves the boresight
        # to this target with the platform's altitude/azimuth adjusters,
        # not with the telescope's normal pointing controls.
        alt_t, az_t = calc_utils.sf_utils.radec_to_altaz(
            ra_target, dec_target, dt_last, atmos=False
        )
        self.target_altaz = (alt_t, az_t)
        self.result = {
            "dAlt": dAlt,
            "dAz": dAz,
            "sweep": sweep,
            "axis_ra": axis_ra,
            "axis_dec": axis_dec,
            "fit_quality": fit_quality,
            "n_points": len(self.solves),
            "ignore_roll": self.ignore_roll,
        }
        return True

    def _compute(self):
        """
        Capture-flow compute: on success move to the live adjustment display;
        if the rotation is too small, drop the last point so the user can
        rotate further and capture it again.
        """
        if self._recompute():
            self.state = PAState.ADJUST
        elif not self._gps_ready():
            self.message(_("Need GPS lock"), 2)
            self.state = PAState.AIM
        else:
            # Enough GPS, but too little rotation to determine an axis: drop
            # the last point so the user can rotate further and recapture.
            self.solves.pop()
            self.message(_("Rotate more"), 2)
            self.state = PAState.AIM

    def _current_offset(self) -> Optional[Tuple[float, float, float]]:
        """
        Live (point_az, point_alt, solve_age): how far to move the
        boresight with the platform adjusters to reach the correction
        target, in ground-frame degrees (push-to convention:
        target - current). (0, 0) means the platform axis is aligned.
        """
        if self.target_altaz is None:
            return None
        cam, solve_time = self._camera_solve()
        if cam is None or solve_time is None:
            return None
        dt_solve = self._solve_datetime(solve_time)
        if dt_solve is None:
            return None
        alt_c, az_c = calc_utils.sf_utils.radec_to_altaz(
            cam.RA, cam.Dec, dt_solve, atmos=False
        )
        alt_t, az_t = self.target_altaz
        return (
            wrap180(az_t - az_c),
            alt_t - alt_c,
            time.time() - solve_time,
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
        elif self.state == PAState.STATS:
            self._draw_stats()

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
                _("Do not move scope"),
                _("on the mount."),
            ],
        )
        if not self.shared_state.altaz_ready():
            self._draw_lines(y + 2, [_("GPS: waiting...")], fill=128)
        # TRANSLATORS: hint bar; {icon} is the SQUARE button glyph
        self._draw_hints(_("{icon} START").format(icon=self._SQUARE_))

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

        # TRANSLATORS: hint bar; {square} is the SQUARE button glyph, {minus}
        # is the MINUS button glyph.
        capture_hint = _("{square} CAPTURE  {minus} CANCEL").format(
            square=self._SQUARE_,
            minus=self._MINUS_,
        )
        self._draw_hints(capture_hint, _("0 SOLVE NOW") if point_number > 2 else None)

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
        # TRANSLATORS: hint bar; {icon} is the MINUS button glyph
        self._draw_hints(_("{icon} BACK").format(icon=self._MINUS_))

    def _fit_verdict(self, fit) -> str:
        """Plain-language fit-quality assessment, or "" when unavailable
        (two-solve has no residual). Shared by the adjust and stats screens."""
        if math.isnan(fit):
            return ""
        if fit < 3:
            return _("ok")
        if fit < 10:
            return _("mid")
        return _("bad")

    def _draw_adjust(self):
        y = self.display_class.titlebar_height + 4
        if self.result is not None:
            info = f"{self.result['n_points']}" + _("pt")
            info += f" {abs(self.result['sweep']):.0f}°"
            verdict = self._fit_verdict(self.result["fit_quality"])
            if verdict:
                info += " " + verdict
            self.draw.text(
                (10, y),
                info,
                font=self.fonts.bold.font,
                fill=self.colors.get(255),
            )
        y += self.fonts.bold.height + 4
        # TRANSLATORS: hint bar; {square} is the SQUARE button glyph, {minus}
        # is the MINUS button glyph.
        redo_hint = _("{square} REDO  {minus} CANCEL").format(
            square=self._SQUARE_,
            minus=self._MINUS_,
        )
        self.draw.text(
            (10, y),
            redo_hint,
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

    def _draw_stats(self):
        """Read-only detail view of the last computed result."""
        y = self.display_class.titlebar_height + 4
        r = self.result
        if r is None:
            self._draw_lines(y, [_("No result yet")])
            # TRANSLATORS: hint bar; {icon} is the SQUARE button glyph
            self._draw_hints(_("{icon} BACK").format(icon=self._SQUARE_))
            return

        # Fit method only applies to three-point solves; for two points it's
        # the basic two-solve estimate, so omit the mode label there.
        mode = ""
        if r["n_points"] >= 3:
            mode = _("RA/Dec") if r["ignore_roll"] else _("3-axis")
        fit = r["fit_quality"]
        fit_txt = "--" if math.isnan(fit) else f"{fit:.1f} {self._fit_verdict(fit)}"

        count = f"{r['n_points']}" + _("pt") + f" {abs(r['sweep']):.0f}°"
        lines = [
            count + (f"  {mode}" if mode else ""),
            _("Fit") + f" {fit_txt}",
            _("Alt") + f" {r['dAlt']:+.2f}° {r['dAlt'] * 60:+.0f}'",
            _("Az") + f"  {r['dAz']:+.2f}° {r['dAz'] * 60:+.0f}'",
            _("Axis") + f" {r['axis_ra']:.1f} {r['axis_dec']:+.1f}",
        ]
        y = self._draw_lines(y, lines)

        # Each point's capture time in seconds relative to the first (first =
        # 0); stable between frames and shows how the captures are spread out.
        ts = sorted(s[3] for s in self.solves)
        if ts:
            t0 = ts[0]
            times = "/".join(f"{t - t0:.0f}" for t in ts)
            self._draw_lines(y + 2, [_("time") + f" {times} " + _("sec")], fill=128)

        # TRANSLATORS: hint bar; {icon} is the SQUARE button glyph
        self._draw_hints(_("{icon} BACK").format(icon=self._SQUARE_))

    def key_square(self):
        if self.state == PAState.STATS:
            # Back to wherever stats was opened from.
            self.state = self._stats_return
        elif self.state == PAState.INTRO:
            self.state = PAState.AIM
        elif self.state == PAState.AIM:
            self.capture_request_time = time.time()
            self.state = PAState.WAIT_SOLVE
        elif self.state == PAState.ADJUST:
            self._reset()
            self.state = PAState.AIM
        self.update(force=True)

    def key_minus(self):
        if self.state == PAState.STATS:
            # Back to wherever stats was opened from, keep the result.
            self.state = self._stats_return
        elif self.state == PAState.WAIT_SOLVE:
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

    # ── Marking-menu actions ──────────────────────────────────────────────────

    def mm_stats(self, _marking_menu, _menu_item) -> bool:
        """
        Show the read-only detail view. With two or more points captured but
        no result yet (still aiming), compute one on demand so stats is
        available without first leaving the capture flow. A single point
        carries no axis information, so nothing can be shown.
        """
        if self.result is None and len(self.solves) >= 2:
            self._recompute()
        if self.result is None:
            # Explain why there's nothing to show, matching the capture flow.
            if len(self.solves) < 2:
                self.message(_("Need 2 points"), 2)
            elif not self._gps_ready():
                self.message(_("Need GPS lock"), 2)
            else:
                self.message(_("Rotate more"), 2)
            return True
        if self.state != PAState.STATS:
            self._stats_return = self.state
        self.state = PAState.STATS
        return True

    def _update_roll_label(self):
        """Roll option shows the current state: on = roll used in the fit."""
        self.marking_menu.down.label = (
            _("Roll Off") if self.ignore_roll else _("Roll On")
        )

    def mm_toggle_roll(self, _marking_menu, _menu_item) -> bool:
        """Toggle the RA/Dec-only (ignore camera roll) fit and recompute."""
        self.ignore_roll = not self.ignore_roll
        self._update_roll_label()
        self.message(_("Roll Off") if self.ignore_roll else _("Roll On"), 1)
        if self.result is not None and len(self.solves) >= 2:
            self._compute()
        return True

    def mm_redo_point(self, _marking_menu, _menu_item) -> bool:
        """Drop just the last captured point and re-aim it."""
        if not self.solves:
            self.message(_("No points"), 1)
            return True
        self.solves.pop()
        self.result = None
        self.target_altaz = None
        self.state = PAState.AIM
        self.message(_("Dropped point"), 1)
        return True
