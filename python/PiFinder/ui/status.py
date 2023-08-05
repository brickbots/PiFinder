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
from PiFinder import utils


class UIStatus(UIModule):
    """
    Displays various status information
    """

    __title__ = "STATUS"

    _config_options = {
        "Key Brit": {
            "type": "enum",
            "value": "",
            "options": ["+3", "+2", "+1", "0", "-1", "-2", "-3", "Off"],
            "callback": "set_key_brightness",
        },
        "Sleep Tim": {
            "type": "enum",
            "value": "",
            "options": ["Off", "10s", "30s", "1m"],
            "callback": "set_sleep_timeout",
        },
        "WiFi Mode": {
            "type": "enum",
            "value": "UNK",
            "options": ["AP", "Cli", "CANCEL"],
            "callback": "wifi_switch",
        },
        "Mnt Side": {
            "type": "enum",
            "value": "",
            "options": ["right", "left", "flat", "CANCEL"],
            "callback": "side_switch",
        },
        "Restart": {
            "type": "enum",
            "value": "",
            "options": ["PiFi", "CANCEL"],
            "callback": "restart",
        },
        "Shutdown": {
            "type": "enum",
            "value": "",
            "options": ["System", "CANCEL"],
            "callback": "shutdown",
        },
        "Software": {
            "type": "enum",
            "value": "",
            "options": ["Update", "CANCEL"],
            "callback": "update_software",
        },
    }

    def __init__(self, *args):
        super().__init__(*args)
        self.version_txt = f"{utils.pifinder_dir}/version.txt"
        self.wifi_txt = f"{utils.pifinder_dir}/wifi_status.txt"
        with open(self.wifi_txt, "r") as wfs:
            self._config_options["WiFi Mode"]["value"] = wfs.read()
        with open(self.version_txt, "r") as ver:
            self._config_options["Software"]["value"] = ver.read()
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

        self._config_options["Mnt Side"]["value"] = self.config_object.get_option(
            "screen_direction"
        )
        self._config_options["Sleep Tim"]["value"] = self.config_object.get_option(
            "sleep_timeout"
        )
        self._config_options["Key Brit"]["value"] = self.config_object.get_option(
            "keypad_brightness"
        )

        self.last_temp_time = 0
        self.last_IP_time = 0

    def update_software(self, option):
        if option == "CANCEL":
            with open(self.version_txt, "r") as ver:
                self._config_options["Software"]["value"] = ver.read()
            return False

        self.message("Updating...", 10)
        if sys_utils.update_software():
            self.message("Ok! Restarting", 10)
            sys_utils.restart_pifinder()
        else:
            self.message("Error on Upd", 3)

    def set_key_brightness(self, option):
        self.command_queues["ui_queue"].put("set_brightness")
        self.config_object.set_option("keypad_brightness", option)
        return False

    def set_sleep_timeout(self, option):
        self.config_object.set_option("sleep_timeout", option)
        return False

    def side_switch(self, option):
        if option == "CANCEL":
            self._config_options["Mnt Side"]["value"] = self.config_object.get_option(
                "screen_direction"
            )
            return False

        self.message("Ok! Restarting", 10)
        self.config_object.set_option("screen_direction", option)
        sys_utils.restart_pifinder()

    def wifi_switch(self, option):
        with open(self.wifi_txt, "r") as wfs:
            current_state = wfs.read()
        if option == current_state or option == "CANCEL":
            self._config_options["WiFi Mode"]["value"] = current_state
            return False

        if option == "AP":
            self.message("Switch to AP", 10)
            sys_utils.go_wifi_ap()
        else:
            self.message("Switch to Cli", 10)
            sys_utils.go_wifi_cli()

    def shutdown(self, option):
        if option == "System":
            self.message("Shutting down", 10)
            sys_utils.shutdown()
        else:
            self._config_options["Shutdown"]["value"] = ""
            return False

    def restart(self, option):
        if option == "PiFi":
            self.message("Restarting", 10)
            sys_utils.restart_pifinder()
        else:
            self._config_options["Restart"]["value"] = ""
            return False

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
                f"{time.time() - solution['cam_solve_time']: >6.1f}"
                + " - "
                + str(solution["solve_source"][0])
                + f" {stars_matched: >2}"
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
            if imu["pos"] is not None:
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

        # only update some things periodically....
        if time.time() - self.last_temp_time > 5:
            # temp
            self.last_temp_time = time.time()
            try:
                with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                    raw_temp = int(f.read().strip())
                self.status_dict["CPU TMP"] = f"{raw_temp / 1000 : >13.1f}"
            except:
                self.status_dict["CPU TMP"] = "     Error"

        if time.time() - self.last_IP_time > 20:
            # temp
            self.last_IP_time = time.time()
            # IP address
            try:
                self.status_dict["IP ADDR"] = socket.gethostbyname(
                    f"{socket.gethostname()}.local"
                )
            except socket.gaierror:
                pass

    def update(self, force=False):
        self.update_status_dict()
        self.draw.rectangle([0, 0, 128, 128], fill=self.colors.get(0))
        lines = []
        for k, v in self.status_dict.items():
            line = f"{k: >7}:{v: >10}"
            lines.append(line)

        # Insert IP address here...
        lines[-1] = f'{self.status_dict["IP ADDR"]: >21}'

        for i, line in enumerate(lines):
            self.draw.text(
                (0, i * 10 + 20), line, font=self.font_base, fill=self.colors.get(255)
            )
        return self.screen_update()

    def active(self):
        """
        Called when a module becomes active
        i.e. foreground controlling display
        """
        with open(self.wifi_txt, "r") as wfs:
            self._config_options["WiFi Mode"]["value"] = wfs.read()
