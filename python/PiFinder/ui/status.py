#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module contains the UI Status class

"""

import time

from PiFinder.ui.base import UIModule
from PiFinder import calc_utils
from PiFinder import utils
from PiFinder.ui.ui_utils import TextLayouter, SpaceCalculatorFixed

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
        self.status_dict = {
            "LST SLV": "--",
            "RA/DEC": "--",
            "AZ/ALT": "--",
            "WIFI": "--",
            "IP": "--",
            "SSID": "--",
            "IMU": "--",
            "IMU PS": "--",
            "GPS": "--",
            "GPS ALT": "--",
            "GPS LST": "--",
            "LCL TM": "--",
            "UTC TM": "--",
            "CPU TMP": "--",
        }

        with open(f"{utils.pifinder_dir}/wifi_status.txt", "r") as wfs:
            wifi_mode = wfs.read()
        self.status_dict["WIFI"] = "Client" if wifi_mode == "Client" else "AP"

        self.last_temp_time = 0
        self.last_IP_time = 0
        self.net = sys_utils.Network()
        self.text_layout = TextLayouter(
            "",
            draw=self.draw,
            color=self.colors.get(255),
            colors=self.colors,
            font=self.fonts.base,
            available_lines=9,
        )

    def update_status_dict(self):
        """
        Updates all the
        status dict values
        """
        if self.shared_state.solve_state():
            solution = self.shared_state.solution()
            # last solve time
            if solution["solve_source"] == "CAM":
                stars_matched = solution["Matches"]
            else:
                stars_matched = "--"
            self.status_dict["LST SLV"] = (
                f"{time.time() - solution['cam_solve_time']:.1f}"
                + " - "
                + str(solution["solve_source"][0])
                + f" {stars_matched: >2}"
            )
            hh, mm, _ = calc_utils.ra_to_hms(solution["RA"])
            self.status_dict["RA/DEC"] = f"{hh:02.0f}h{mm:02.0f}m/{solution['Dec']:.2f}"

            if solution["Az"]:
                self.status_dict["AZ/ALT"] = (
                    f"{solution['Az']: >6.2f}/{solution['Alt']: >6.2f}"
                )

        imu = self.shared_state.imu()
        if imu:
            if imu["pos"] is not None:
                if imu["moving"]:
                    mtext = "Moving"
                else:
                    mtext = "Static"
                self.status_dict["IMU"] = f"{mtext: >11}" + " " + str(imu["status"])
                self.status_dict["IMU PS"] = (
                    f"{imu['pos'][0]: >6.1f}/{imu['pos'][2]: >6.1f}"
                )
        location = self.shared_state.location()
        sats = self.shared_state.sats()
        self.status_dict["GPS"] = [
            f"GPS {sats[0]}/{sats[1]}" if sats else "GPS 0/0",
            f"{location.lat:.2f}/{location.lon:.2f}",
        ]

        self.status_dict["GPS ALT"] = f"{location.altitude:.1f}m"
        last_lock = location.last_gps_lock
        self.status_dict["GPS LST"] = last_lock if last_lock else "--"

        dt = self.shared_state.datetime()
        local_dt = self.shared_state.local_datetime()
        if dt:
            self.status_dict["LCL TM"] = local_dt.time().isoformat()[:8]
            self.status_dict["UTC TM"] = dt.time().isoformat()[:8]

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
            # IP address
            self.status_dict["IP"] = self.net.local_ip()
            if self.net.wifi_mode() == "AP":
                self.status_dict["SSID"] = self.net.get_ap_name()
            else:
                self.status_dict["SSID"] = self.net.get_connected_ssid()

    def update(self, force=False):
        self.update_status_dict()
        self.draw.rectangle(
            [0, 0, self.display_class.resX, self.display_class.resY],
            fill=self.colors.get(0),
        )
        lines = []
        # Insert IP address here...
        for k, v in self.status_dict.items():
            key = f"{k:<7}"
            if isinstance(v, list):
                key = v[0]
                v = v[1]
            _, result = self.spacecalc.calculate_spaces(key, v, empty_if_exceeds=False)
            lines.append(result)
        outline = "\n".join(lines)
        self.text_layout.set_text(outline, reset_pointer=False)
        self.text_layout.draw(pos=self._draw_pos)
        return self.screen_update()

    def key_up(self):
        self.text_layout.previous()

    def key_down(self):
        self.text_layout.next()
