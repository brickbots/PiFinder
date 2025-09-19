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
        "Screen Off": {
            "type": "enum",
            "value": "",
            "options": ["Off", "30s", "1m", "10m", "30m"],
            "callback": "set_screen_off_timeout",
        },
        "Hint Time": {
            "type": "enum",
            "value": "2s",
            "options": ["Off", "2s", "4s", "On"],
            "callback": "set_hint_timeout",
        },
        "WiFi Mode": {
            "type": "enum",
            "value": "UNK",
            "options": ["AP", "Client", "CANCEL"],
            "callback": "wifi_switch",
        },
        "Mnt Side": {
            "type": "enum",
            "value": "",
            "options": ["right", "left", "flat", "CANCEL"],
            "callback": "side_switch",
        },
        "Mnt Type": {
            "type": "enum",
            "value": "",
            "options": ["Alt/Az", "EQ", "CANCEL"],
            "callback": "mount_switch",
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.version_txt = f"{utils.pifinder_dir}/version.txt"
        self.wifi_txt = f"{utils.pifinder_dir}/wifi_status.txt"
        self._draw_pos = (0, self.display_class.titlebar_height)
        with open(self.wifi_txt, "r") as wfs:
            self._config_options["WiFi Mode"]["value"] = wfs.read()
        with open(self.version_txt, "r") as ver:
            self._config_options["Software"]["value"] = ver.read()
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

        if self._config_options["WiFi Mode"]["value"] == "Client":
            self.status_dict["WIFI"] = "Client"
        else:
            self.status_dict["WIFI"] = "AP"

        self._config_options["Mnt Type"]["value"] = self.config_object.get_option(
            "mount_type"
        )
        self._config_options["Mnt Side"]["value"] = self.config_object.get_option(
            "screen_direction"
        )
        self._config_options["Sleep Tim"]["value"] = self.config_object.get_option(
            "sleep_timeout"
        )
        self._config_options["Screen Off"]["value"] = self.config_object.get_option(
            "screen_off_timeout"
        )
        self._config_options["Hint Time"]["value"] = self.config_object.get_option(
            "hint_timeout"
        )
        self._config_options["Key Brit"]["value"] = self.config_object.get_option(
            "keypad_brightness"
        )

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

    def set_hint_timeout(self, option):
        self.config_object.set_option("hint_timeout", option)
        self.ui_state.set_hint_timeout(option)
        return False

    def set_screen_off_timeout(self, option):
        self.config_object.set_option("screen_off_timeout", option)
        return False

    def mount_switch(self, option):
        if option == "CANCEL":
            self._config_options["Mnt Type"]["value"] = self.config_object.get_option(
                "mount_type"
            )
            return False

        self.message("Ok! Restarting", 10)
        self.config_object.set_option("mount_type", option)
        sys_utils.restart_pifinder()

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
            self.message("Switch to Client", 10)
            sys_utils.go_wifi_cli()

        sys_utils.restart_system()

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
                f"{time.time() - solution['cam_solve_time']:.1f}"
                + " - "
                + str(solution["solve_source"][0])
                + f" {stars_matched: >2}"
            )
            hh, mm, _ = calc_utils.ra_to_hms(solution["RA"])
            self.status_dict["RA/DEC"] = (
                f"{hh:02.0f}h{mm:02.0f}m/{solution['Dec'] :.2f}"
            )

            if solution["Az"]:
                self.status_dict["AZ/ALT"] = (
                    f"{solution['Az'] : >6.2f}/{solution['Alt'] : >6.2f}"
                )

        imu = self.shared_state.imu()
        if imu:
            if imu["quat"] is not None:
                if imu["moving"]:
                    mtext = "Moving"
                else:
                    mtext = "Static"
                self.status_dict["IMU"] = f"{mtext : >11}" + " " + str(imu["status"])
                self.status_dict["IMU PS"] = (
                    "imu NA"
                    # f"{imu['quat'][0] : >6.1f}/{imu['quat'][2] : >6.1f}"  # TODO: Quick hack for now. This was changed from imu["pos"] and should be changed.
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
                self.status_dict["CPU TMP"] = f"{raw_temp / 1000 : >13.1f}"
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
        time.sleep(1 / 30)
        self.update_status_dict()
        self.draw.rectangle([0, 0, 128, 128], fill=self.colors.get(0))
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

    def active(self):
        """
        Called when a module becomes active
        i.e. foreground controlling display
        """
        with open(self.wifi_txt, "r") as wfs:
            self._config_options["WiFi Mode"]["value"] = wfs.read()
