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
    _lock_type_dict = {
        0: "poor lock",
        1: "good lock",
        2: "great lock"
    }

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

    def _get_error_string(self, error: float) -> str:
        if error > 1000:
            return f"{error/1000:.1f} km"
        else:
            return f"{error:.0f} m"

    def update(self, force=False):
        state_utils.sleep_for_framerate(self.shared_state)
        self.clear_screen()
        draw_pos = self.display_class.titlebar_height + 2

        # Status message
        self.draw.text(
            (0, draw_pos),
            "Stay here for lock",
            font=self.fonts.bold.font,
            fill=self.colors.get(128),
        )
        draw_pos += 16

        location = self.shared_state.location()
        sats = self.shared_state.sats()
        if sats is None:
            sats = (0, 0)

        # Satellite info
        self.draw.text(
            (0, draw_pos),
            f"Sats seen/used: {sats[0]}/{sats[1]}",
            font=self.fonts.base.font,
            fill=self.colors.get(128),
        )
        draw_pos += 10

        # Error display
        self.draw.text(
            (0, draw_pos),
            f"Error: {self._get_error_string(location.error_in_m)}",
            font=self.fonts.base.font,
            fill=self.colors.get(128),
        )
        draw_pos += 10

        # Lock status
        self.draw.text(
            (0, draw_pos),
            f"Lock: {'No' if not location.lock else self._lock_type_dict[location.lock_type]}",
            font=self.fonts.base.font,
            fill=self.colors.get(128),
        )
        draw_pos += 10

        # Position data if locked
        self.draw.text(
            (0, draw_pos),
            f"Lat: {location.lat:.5f}",
            font=self.fonts.base.font,
            fill=self.colors.get(128),
        )
        draw_pos += 10

        self.draw.text(
            (0, draw_pos),
            f"Lon: {location.lon:.5f}",
            font=self.fonts.base.font,
            fill=self.colors.get(128),
        )
        draw_pos += 10

        self.draw.text(
            (0, draw_pos),
            f"Alt: {location.altitude:.1f} m",
            font=self.fonts.base.font,
            fill=self.colors.get(128),
        )
        draw_pos += 10

        self.draw.text(
            (0, draw_pos),
            f"Source: {location.source}",
            font=self.fonts.base.font,
            fill=self.colors.get(128),
        )
        draw_pos += 10
        return self.screen_update()
