#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module contains all the UI Module classes

"""

import time
from PiFinder import state_utils
from PiFinder.ui.base import UIModule


class UIGPSStatus(UIModule):
    """
    UI for seeing GPS status
    """

    __title__ = "GPS"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

    def update(self, force=False):
        state_utils.sleep_for_framerate(self.shared_state)
        self.clear_screen()
        draw_pos = self.display_class.titlebar_height + 2
        location = self.shared_state.location()
        sats = self.shared_state.sats()
        if sats is None:
            sats = (0, 0)
        self.draw.text(
            (0, draw_pos),
            f"Sats seen: {sats[0]}",
            font=self.fonts.base.font,
            fill=self.colors.get(128),
        )
        draw_pos += 10

        self.draw.text(
            (0, draw_pos),
            f"Sats used: {sats[1]}",
            font=self.fonts.base.font,
            fill=self.colors.get(128),
        )
        draw_pos += 10

        self.draw.text(
            (10, draw_pos),
            f"Lock: {location.lock}",
            font=self.fonts.bold.font,
            fill=self.colors.get(192),
        )
        draw_pos += 16

        if location.lock:
            self.draw.text(
                (0, draw_pos),
                f"Source: {location.source}",
                font=self.fonts.base.font,
                fill=self.colors.get(128),
            )
            draw_pos += 10

        # self.draw.text(
        #     (10, draw_pos),
        #     f"{self._release_version}",
        #     font=self.fonts.bold.font,
        #     fill=self.colors.get(192),
        # )
        #
        # if self._wifi_mode != "Client":
        #     self.draw.text(
        #         (10, 90),
        #         "WiFi must be",
        #         font=self.fonts.large.font,
        #         fill=self.colors.get(255),
        #     )
        #     self.draw.text(
        #         (10, 105),
        #         "client mode",
        #         font=self.fonts.large.font,
        #         fill=self.colors.get(255),
        #     )
        #     return self.screen_update()
        #
        # if self._release_version == "-.-.-":
        #     self.draw.text(
        #         (10, 90),
        #         "Checking for",
        #         font=self.fonts.large.font,
        #         fill=self.colors.get(255),
        #     )
        #     self.draw.text(
        #         (10, 105),
        #         f"updates{'.' * int(self._elipsis_count / 10)}",
        #         font=self.fonts.large.font,
        #         fill=self.colors.get(255),
        #     )
        #     self._elipsis_count += 1
        #     if self._elipsis_count > 39:
        #         self._elipsis_count = 0
        #     return self.screen_update()
        #
        # if self._release_version.strip() == self._software_version.strip():
        #     self.draw.text(
        #         (10, 90),
        #         "No Update",
        #         font=self.fonts.large.font,
        #         fill=self.colors.get(255),
        #     )
        #     self.draw.text(
        #         (10, 105),
        #         "needed",
        #         font=self.fonts.large.font,
        #         fill=self.colors.get(255),
        #     )
        #     return self.screen_update()
        #
        # # If we are here, go for update!
        # self._go_for_update = True
        # self.draw.text(
        #     (10, 90),
        #     "Update Now",
        #     font=self.fonts.large.font,
        #     fill=self.colors.get(255),
        # )
        # self.draw.text(
        #     (10, 105),
        #     "Cancel",
        #     font=self.fonts.large.font,
        #     fill=self.colors.get(255),
        # )
        # if self._option_select == "Update":
        #     ind_pos = 90
        # else:
        #     ind_pos = 105
        # self.draw.text(
        #     (0, ind_pos),
        #     self._RIGHT_ARROW,
        #     font=self.fonts.large.font,
        #     fill=self.colors.get(255),
        # )

        return self.screen_update()

    # def toggle_option(self):
    #     if not self._go_for_update:
    #         return
    #     if self._option_select == "Update":
    #         self._option_select = "Cancel"
    #     else:
    #         self._option_select = "Update"
    #
    # def key_up(self):
    #     self.toggle_option()
    #
    # def key_down(self):
    #     self.toggle_option()
    #
    # def key_right(self):
    #     if self._option_select == "Cancel":
    #         self.remove_from_stack()
    #     else:
    #         self.update_software()
