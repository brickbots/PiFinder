#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module contains all the UI Module classes

"""

import time
import requests

from PiFinder import utils
from PiFinder.ui.base import UIModule
sys_utils = utils.get_sys_utils()


class UISoftware(UIModule):
    """
    UI for updating software versions
    """

    __title__ = "SOFTWARE"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.version_txt = f"{utils.pifinder_dir}/version.txt"
        self.wifi_txt = f"{utils.pifinder_dir}/wifi_status.txt"
        with open(self.wifi_txt, "r") as wfs:
            self._wifi_mode = wfs.read()
        with open(self.version_txt, "r") as ver:
            self._software_version = ver.read()

        self._release_version = "-.-.-"
        self._elipsis_count = 0
        self._go_for_update = False
        self._option_select = "Update"

    def get_release_version(self):
        """
        Fetches current release version from
        github, sets class variable if found
        """

        try:
            res = requests.get(
                "https://raw.githubusercontent.com/brickbots/PiFinder/release/version.txt"
            )
        except requests.exceptions.ConnectionError:
            print("Could not connect to github")
            self._release_version = "Unknown"
            return

        if res.status_code == 200:
            self._release_version = res.text[:-1]
        else:
            self._release_version = "Unknown"

    def update_software(self):
        self.message("Updating...", 10)
        if sys_utils.update_software():
            self.message("Ok! Restarting", 10)
            sys_utils.restart_system()
        else:
            self.message("Error on Upd", 3)

    def update(self, force=False):
        # check elipsis count here... if we are at >30 check for
        # release versions
        if self._elipsis_count > 30:
            self.get_release_version()

        time.sleep(1 / 30)
        self.clear_screen()
        draw_pos = self.display_class.titlebar_height + 2
        self.draw.text(
            (0, draw_pos),
            f"Wifi Mode: {self._wifi_mode}",
            font=self.fonts.base.font,
            fill=self.colors.get(128),
        )
        draw_pos += 15

        self.draw.text(
            (0, draw_pos),
            "Current Version",
            font=self.fonts.bold.font,
            fill=self.colors.get(128),
        )
        draw_pos += 10

        self.draw.text(
            (10, draw_pos),
            f"{self._software_version}",
            font=self.fonts.bold.font,
            fill=self.colors.get(192),
        )
        draw_pos += 16

        self.draw.text(
            (0, draw_pos),
            "Release Version",
            font=self.fonts.bold.font,
            fill=self.colors.get(128),
        )
        draw_pos += 10

        self.draw.text(
            (10, draw_pos),
            f"{self._release_version}",
            font=self.fonts.bold.font,
            fill=self.colors.get(192),
        )

        if self._wifi_mode != "Client":
            self.draw.text(
                (10, 90),
                "WiFi must be",
                font=self.fonts.large.font,
                fill=self.colors.get(255),
            )
            self.draw.text(
                (10, 105),
                "client mode",
                font=self.fonts.large.font,
                fill=self.colors.get(255),
            )
            return self.screen_update()

        if self._release_version == "-.-.-":
            self.draw.text(
                (10, 90),
                "Checking for",
                font=self.fonts.large.font,
                fill=self.colors.get(255),
            )
            self.draw.text(
                (10, 105),
                f"updates{'.' * int(self._elipsis_count / 10)}",
                font=self.fonts.large.font,
                fill=self.colors.get(255),
            )
            self._elipsis_count += 1
            if self._elipsis_count > 39:
                self._elipsis_count = 0
            return self.screen_update()

        if self._release_version.strip() == self._software_version.strip():
            self.draw.text(
                (10, 90),
                "No Update",
                font=self.fonts.large.font,
                fill=self.colors.get(255),
            )
            self.draw.text(
                (10, 105),
                "needed",
                font=self.fonts.large.font,
                fill=self.colors.get(255),
            )
            return self.screen_update()

        # If we are here, go for update!
        self._go_for_update = True
        self.draw.text(
            (10, 90),
            "Update Now",
            font=self.fonts.large.font,
            fill=self.colors.get(255),
        )
        self.draw.text(
            (10, 105),
            "Cancel",
            font=self.fonts.large.font,
            fill=self.colors.get(255),
        )
        if self._option_select == "Update":
            ind_pos = 90
        else:
            ind_pos = 105
        self.draw.text(
            (0, ind_pos),
            self._RIGHT_ARROW,
            font=self.fonts.large.font,
            fill=self.colors.get(255),
        )

        return self.screen_update()

    def toggle_option(self):
        if not self._go_for_update:
            return
        if self._option_select == "Update":
            self._option_select = "Cancel"
        else:
            self._option_select = "Update"

    def key_up(self):
        self.toggle_option()

    def key_down(self):
        self.toggle_option()

    def key_right(self):
        if self._option_select == "Cancel":
            self.remove_from_stack()
        else:
            self.update_software()
