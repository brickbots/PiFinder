#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module contains all the UI Module classes

"""
import datetime
import time
import socket

from PiFinder.ui.base import UIModule
from PiFinder import sys_utils

RED = (0, 0, 255)


class UIStatus(UIModule):
    """
    Displays various status information
    """

    __title__ = "STATUS"

    _config_options = {
        "WiFi Mode": {
            "type": "enum",
            "value": "UNK",
            "options": ["AP", "Cli", "exit"],
            "callback": "wifi_switch",
        },
        "Restart": {
            "type": "enum",
            "value": "",
            "options": ["PiFi", "exit"],
            "callback": "restart",
        },
        "Shutdown": {
            "type": "enum",
            "value": "",
            "options": ["Syst", "exit"],
            "callback": "shutdown",
        },
    }

    def __init__(self, *args):
        super().__init__(*args)
        with open("/home/pifinder/PiFinder/wifi_status.txt", "r") as wfs:
            self._config_options["WiFi Mode"]["value"] = wfs.read()
        self.status_dict = {
            "LST SLV": "           --",
            "RA/DEC": "           --",
            "AZ/ALT": "           --",
            "IMU": "           --",
            "IMU PS": "           --",
            "LCL TM": "           --",
            "UTC TM": "           --",
            "CPU TMP": "           --",
            "WIFI": "           --",
            "IP ADDR": "           --",
        }

        if self._config_options["WiFi Mode"]["value"] == "Cli":
            self.status_dict["WIFI"] = "          Cli"
        else:
            self.status_dict["WIFI"] = "           AP"

        self.last_temp_time = 0

    def wifi_switch(self, option):
        with open("/home/pifinder/PiFinder/wifi_status.txt", "r") as wfs:
            current_state = wfs.read()
        if option == current_state or option == "exit":
            return False

        if option == "AP":
            sys_utils.go_wifi_ap()
        else:
            sys_utils.go_wifi_cli()

    def shutdown(self, option):
        if option == "Syst":
            sys_utils.shutdown()
        else:
            return False

    def restart(self, option):
        if option == "PiFi":
            sys_utils.restart_pifinder()
        else:
            return False

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
        # only update some things once per second....
        if time.time() - self.last_temp_time > 1:
            # temp
            self.last_temp_time = time.time()
            with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                raw_temp = int(f.read().strip())
            self.status_dict["CPU TMP"] = f"{raw_temp / 1000 : >13.1f}"

            # IP
            self.status_dict["IP ADDR"] = socket.gethostbyname("pifinder.local")

    def update(self, force=False):
        self.update_status_dict()
        self.draw.rectangle([0, 0, 128, 128], fill=(0, 0, 0))
        lines = []
        for k, v in self.status_dict.items():
            line = f"{k: >7}:{v: >10}"
            lines.append(line)

        # Insert IP address here...
        lines[-1] = f'{self.status_dict["IP ADDR"]: >21}'

        for i, line in enumerate(lines):
            self.draw.text((0, i * 10 + 20), line, font=self.font_base, fill=RED)
        return self.screen_update()

    def active(self):
        """
        Called when a module becomes active
        i.e. foreground controlling display
        """
        with open("/home/pifinder/PiFinder/wifi_status.txt", "r") as wfs:
            self._config_options["WiFi Mode"]["value"] = wfs.read()
