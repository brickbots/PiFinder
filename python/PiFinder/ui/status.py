#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module contains the UI Status class

"""

import time

from PiFinder.ui.base import UIModule
from PiFinder import calc_utils
from PiFinder import utils
from PiFinder.ui.ui_utils import TextLayouter, TextLayouterScroll, SpaceCalculatorFixed
from PiFinder.ui.layout import rows_below_titlebar

sys_utils = utils.get_sys_utils()


class UIStatus(UIModule):
    """
    Displays various status information
    """

    __title__ = "STATUS"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._draw_pos = (0, self.display_class.titlebar_height)
        self.spacecalc = SpaceCalculatorFixed(self.fonts.base.line_length)
        # Horizontal scrollers for values too long for their column (e.g. a long
        # IP address), keyed by status_dict key. Created lazily on overflow so
        # the value scrolls instead of being truncated off the right edge.
        self.value_scrollers = {}
        self.status_dict = {
            "LAST SLV": "--",
            "RA/DEC": "--",
            "AZ/ALT": "--",
            "WIFI": "--",
            "IP": "--",
            "SSID": "--",
            "IMU": "--",
            "IMU qw,qx": "--",
            "IMU qy,qz": "--",
            "GPS": "--",
            "GPS ALT": "--",
            "GPS LCK": "--",
            "LCL TM": "--",
            "UTC TM": "--",
            "CPU TMP": "--",
        }

        self.last_temp_time = 0
        self.last_IP_time = 0
        self.net = sys_utils.Network()
        self.text_layout = TextLayouter(
            "",
            draw=self.draw,
            color=self.colors.get(255),
            colors=self.colors,
            font=self.fonts.base,
            # As many base-font rows as fit below the title bar (9 on the 128
            # panel, more on taller displays).
            available_lines=rows_below_titlebar(self.display_class, gap=1).max_visible,
        )

    def update_status_dict(self):
        """
        Updates all the status dict values
        """
        if self.shared_state.solve_state():
            solution = self.shared_state.solution()

            # Time since last solve
            if solution.last_solve_success:
                time_since_solve = f"{time.time() - solution.last_solve_success:.1f}"
            else:
                time_since_solve = "--"
            # Number of matched stars
            if solution.is_camera_solve():
                stars_matched = solution.diagnostics.Matches
            else:
                stars_matched = "--"
            # Solve source
            source = solution.solve_source
            if source is None:
                solve_source = "-"
            elif source == "CAM":
                solve_source = "C"
            elif source == "CAM_FAILED":
                solve_source = "F"
            else:
                solve_source = str(source.value[0])
            # Collect togethers
            self.status_dict["LAST SLV"] = (
                time_since_solve + "s " + solve_source + f" {stars_matched: >2}"
            )

            # RA/DEC
            aligned = solution.pointing.aligned.estimate
            if aligned is None:
                self.status_dict["RA/DEC"] = "--/--"
            else:
                hh, mm, _ = calc_utils.ra_to_hms(aligned.RA)
                self.status_dict["RA/DEC"] = f"{hh:02.0f}h{mm:02.0f}m/{aligned.Dec:.2f}"

            # AZ/ALT
            if solution.Az is None or solution.Alt is None:
                self.status_dict["AZ/ALT"] = "--/--"
            else:
                self.status_dict["AZ/ALT"] = (
                    f"{solution.Az: >6.2f}/{solution.Alt: >6.2f}"
                )

        imu = self.shared_state.imu()
        # IMU Status & reading
        if imu:
            if imu.quat is not None:
                if imu.moving:
                    mtext = "Moving"
                else:
                    mtext = "Static"
                self.status_dict["IMU"] = f"{mtext: >11}" + " " + str(imu.status)

                self.status_dict["IMU qw,qx"] = f"{imu.quat.w:>.2f},{imu.quat.x: >.2f}"
                self.status_dict["IMU qy,qz"] = f"{imu.quat.y:>.2f},{imu.quat.z: >.2f}"
        else:
            self.status_dict["IMU"] = "--"
            self.status_dict["IMU qw,qx"] = "--"
            self.status_dict["IMU qy,qz"] = "--"

        location = self.shared_state.location()
        sats = self.shared_state.sats()
        self.status_dict["GPS"] = [
            f"GPS {sats[0]}/{sats[1]}" if sats else "GPS 0/0",
            f"{location.lat:.2f}/{location.lon:.2f}",
        ]

        self.status_dict["GPS ALT"] = f"{location.altitude:.1f}m"
        last_lock = location.last_gps_lock
        self.status_dict["GPS LCK"] = last_lock if last_lock else "--"

        # use datetimes explictly converted to the timezone we want to print
        # datetime() can be in any timezone and time() will just ignore TZ
        utc_dt = self.shared_state.utc_datetime()
        local_dt = self.shared_state.local_datetime()
        if utc_dt:
            self.status_dict["UTC TM"] = utc_dt.time().isoformat()[:8]
        if local_dt:
            self.status_dict["LCL TM"] = local_dt.time().isoformat()[:8]

        # only update some things periodically....
        if time.time() - self.last_temp_time > 5:
            # temp
            self.last_temp_time = time.time()
            try:
                with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                    raw_temp = int(f.read().strip())
                self.status_dict["CPU TMP"] = f"{raw_temp / 1000: >13.1f}"
            except FileNotFoundError:
                self.status_dict["CPU TMP"] = "Error"

        if time.time() - self.last_IP_time > 20:
            self.last_IP_time = time.time()
            # Live network state: WIFI radio mode, the reachable IP, and the
            # active-uplink label (Ethernet when wired, else SSID / AP name).
            self.status_dict["WIFI"] = self.net.wifi_mode()
            self.status_dict["IP"] = self.net.local_ip()
            self.status_dict["SSID"] = self.net.get_active_label()

    def update(self, force=False):
        self.update_status_dict()
        self.clear_screen()
        lines = [self._render_row(k, v) for k, v in self.status_dict.items()]
        self.text_layout.set_text("\n".join(lines), reset_pointer=False)
        self.text_layout.draw(pos=self._draw_pos)
        return self.screen_update()

    def _render_row(self, k, v) -> str:
        """
        Render one status row as ``key`` followed by its value.

        The value is justified into its column with SpaceCalculatorFixed when it
        fits, or rendered through a per-row horizontal scroller (see
        _scrolled_value) when it overflows, so long values (a long IP address or
        SSID) stay readable instead of being truncated. The scroller is dropped
        again as soon as the value fits, so a row flips between static and
        scrolling as its value changes.
        """
        key = f"{k:<7}"
        if isinstance(v, list):
            # Rows with a runtime-computed label (e.g. GPS, whose label embeds
            # the live satellite count) carry [label, value] and supply their
            # own label instead of the padded dict key.
            key = v[0]
            v = v[1]
        value = str(v)
        field = self.spacecalc.width - len(key)
        if 0 < field < len(value):
            return key + self._scrolled_value(k, value, field)
        self.value_scrollers.pop(k, None)
        _, result = self.spacecalc.calculate_spaces(key, v, empty_if_exceeds=False)
        return result

    def _scrolled_value(self, row_key: str, value: str, field: int) -> str:
        """
        Return a `field`-wide window of `value` that advances each frame so a
        long value scrolls horizontally within its column. Reuses one
        TextLayouterScroll per row, recreated when the value or column width
        changes.
        """
        scroller = self.value_scrollers.get(row_key)
        if scroller is None or scroller.text != value or scroller.width != field:
            scroller = TextLayouterScroll(
                value,
                draw=self.draw,
                color=self.colors.get(255),
                font=self.fonts.base,
                width=field,
                scrollspeed=TextLayouterScroll.MEDIUM,
            )
            self.value_scrollers[row_key] = scroller
        scroller.layout()
        return scroller.object_text[0] if scroller.object_text else value[:field]

    def key_up(self):
        self.text_layout.previous()

    def key_down(self):
        self.text_layout.next()
