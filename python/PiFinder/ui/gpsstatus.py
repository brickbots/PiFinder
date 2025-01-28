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

        # Header
        self.draw.text(
            (0, draw_pos),
            "GPS Status",
            font=self.fonts.base.font,
            fill=self.colors.get(128),
        )
        draw_pos += 10

        # Status message
        self.draw.text(
            (0, draw_pos),
            "Stay here for lock",
            font=self.fonts.base.font,
            fill=self.colors.get(128),
        )
        draw_pos += 10

        location = self.shared_state.location()
        sats = self.shared_state.sats()
        if sats is None:
            sats = (0, 0)

        # Satellite info
        self.draw.text(
            (0, draw_pos),
            f"sats seen: {sats[0]}",
            font=self.fonts.base.font,
            fill=self.colors.get(128),
        )
        draw_pos += 10

        self.draw.text(
            (0, draw_pos),
            f"sats used: {sats[1]}",
            font=self.fonts.base.font,
            fill=self.colors.get(128),
        )
        draw_pos += 10

        # Error display
        self.draw.text(
            (0, draw_pos),
            "Error: m",
            font=self.fonts.base.font,
            fill=self.colors.get(128),
        )
        draw_pos += 10

        # Lock status
        self.draw.text(
            (0, draw_pos),
            f"Lock?: {location.lock}",
            font=self.fonts.bold.font,
            fill=self.colors.get(192),
        )
        draw_pos += 16

        # Position data if locked
        if location.lock:
            self.draw.text(
                (0, draw_pos),
                f"lat: {location.lat:.5f}",
                font=self.fonts.base.font,
                fill=self.colors.get(128),
            )
            draw_pos += 10

            self.draw.text(
                (0, draw_pos),
                f"lon: {location.lon:.5f}",
                font=self.fonts.base.font,
                fill=self.colors.get(128),
            )
            draw_pos += 10

            self.draw.text(
                (0, draw_pos),
                f"alt: {location.altitude:.1f} m",
                font=self.fonts.base.font,
                fill=self.colors.get(128),
            )
            draw_pos += 10

            self.draw.text(
                (0, draw_pos),
                f"source: {location.source:.1f} m",
                font=self.fonts.base.font,
                fill=self.colors.get(128),
            )
            draw_pos += 10
        return self.screen_update()
