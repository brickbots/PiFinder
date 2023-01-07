#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module contains all the UI Module classes

"""
import datetime
import time

from PiFinder.ui.base import UIModule

RED = (0, 0, 255)


class UIStatus(UIModule):
    """
    Displays various status information
    """

    __title__ = "STATUS"

    def __init__(self, *args):
        self.status_dict = {
            "LST SLV": "           --",
            "RA/DEC": "           --",
            "AZ/ALT": "           --",
            "GPS": "           --",
            "IMU": "           --",
            "IMU PS": "           --",
            "LCL TM": "           --",
            "UTC TM": "           --",
            "CPU TMP": "           --",
        }
        self.last_temp_time = 0
        super().__init__(*args)

    def update_status_dict(self):
        """
        Updates all the
        status dict values
        """
        if self.shared_state.solve_state():
            solution = self.shared_state.solution()
            # last solve time
            self.status_dict["LST SLV"] = (
                f"{time.time() - solution['solve_time']: >7.1f}"
                + " - "
                + str(solution["solve_source"])
            )

            self.status_dict[
                "RA/DEC"
            ] = f"{solution['RA'] : >6.2f}/{solution['Dec'] : >6.2f}"

            if solution["Az"]:
                self.status_dict[
                    "AZ/ALT"
                ] = f"{solution['Az'] : >6.2f}/{solution['Alt'] : >6.2f}"

        location = self.shared_state.location()
        if location["gps_lock"]:
            self.status_dict["GPS"] = "         LOCK"

        imu = self.shared_state.imu()
        if imu:
            if imu["pos"] != None:
                if imu["moving"]:
                    mtext = "Moving"
                else:
                    mtext = "Static"
                self.status_dict["IMU"] = f"{mtext : >11}" + " " + str(imu["status"])
                self.status_dict[
                    "IMU PS"
                ] = f"{imu['pos'][0] : >6.1f}/{imu['pos'][2] : >6.1f}"

        dt = self.shared_state.datetime()
        local_dt = self.shared_state.local_datetime()
        if dt:
            self.status_dict["LCL TM"] = "     " + local_dt.time().isoformat()[:8]
            self.status_dict["UTC TM"] = "     " + dt.time().isoformat()[:8]
        # only update temp once per second....
        if time.time() - self.last_temp_time > 1:
            self.last_temp_time = time.time()
            with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                raw_temp = int(f.read().strip())
            self.status_dict["CPU TMP"] = f"{raw_temp / 1000 : >13.1f}"

    def update(self, force=False):
        self.update_status_dict()
        self.draw.rectangle([0, 0, 128, 128], fill=(0, 0, 0))
        lines = []
        for k, v in self.status_dict.items():
            line = " " * (7 - len(k)) + k
            line += ":"
            line += " " * (10 - len(v))
            line += v
            lines.append(line)

        for i, line in enumerate(lines):
            self.draw.text((0, i * 10 + 20), line, font=self.font_base, fill=RED)
        return self.screen_update()
