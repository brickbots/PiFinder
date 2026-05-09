#!/usr/bin/python
# -*- coding:utf-8 -*-
# mypy: ignore-errors
"""
This module contains all the UI Module classes

"""

import os
import datetime
import time

from PIL import Image
from PiFinder.ui.base import UIModule
from PiFinder.image_util import convert_image_to_mode


def singleton(class_):
    instances = {}

    def getinstance(*args, **kwargs):
        if class_ not in instances:
            instances[class_] = class_(*args, **kwargs)
        return instances[class_]

    return getinstance


@singleton
class UIConsole(UIModule):
    __title__ = "CONSOLE"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.dirty = True
        self.welcome = True

        # load welcome image to screen
        root_dir = os.path.realpath(
            os.path.join(os.path.dirname(__file__), "..", "..", "..")
        )
        welcome_image_path = os.path.join(root_dir, "images", "welcome.png")
        welcome_image = Image.open(welcome_image_path)
        welcome_image = convert_image_to_mode(welcome_image, self.colors.mode)
        self.screen.paste(welcome_image)

        self.lines = ["---- TOP ---", "Sess UUID:" + self.__uuid__]
        self.scroll_offset = 0
        self.debug_mode = False

    def set_shared_state(self, shared_state):
        self.shared_state = shared_state

    def key_number(self, number):
        if number == 0:
            self.command_queues["camera"].put("debug")
            if self.debug_mode:
                self.debug_mode = False
            else:
                self.debug_mode = True
            self.command_queues["console"].put("Debug: " + str(self.debug_mode))
        dt = datetime.datetime(2022, 11, 15, 2, 0, 0)
        self.shared_state.set_datetime(dt)

    def key_enter(self):
        # reset scroll offset
        self.scroll_offset = 0
        self.dirty = True

    def key_up(self):
        self.scroll_offset += 1
        self.dirty = True

    def key_down(self):
        self.scroll_offset -= 1
        if self.scroll_offset < 0:
            self.scroll_offset = 0
        self.dirty = True

    def write(self, line):
        """
        Writes a new line to the console.
        """
        print(f"Write: {line}")
        self.lines.append(line)
        # reset scroll offset
        self.scroll_offset = 0
        self.dirty = True

    def active(self):
        self.welcome = False
        self.dirty = True
        self.update()

    def update(self, force=False):
        if self.dirty:
            if self.welcome:
                # Clear / write just top line
                self.draw.rectangle(
                    [0, 0, self.display_class.resX, self.display_class.titlebar_height],
                    fill=self.colors.get(0),
                )
                self.draw.text(
                    (0, 1),
                    self.lines[-1],
                    font=self.fonts.base.font,
                    fill=self.colors.get(255),
                )
                return self.screen_update(title_bar=False)
            else:
                self.clear_screen()
                for i, line in enumerate(self.lines[-10 - self.scroll_offset :][:10]):
                    self.draw.text(
                        (0, i * 10 + 20),
                        line,
                        font=self.fonts.base.font,
                        fill=self.colors.get(255),
                    )
                self.dirty = False
                return self.screen_update()

    def screen_update(self, title_bar=True, button_hints=True):
        """
        called to trigger UI updates
        takes self.screen adds title bar and
        writes to display
        """

        if title_bar:
            fg = self.colors.get(0)
            bg = self.colors.get(64)
            self.draw.rectangle(
                [0, 0, self.display_class.resX, self.display_class.titlebar_height],
                fill=bg,
            )
            self.draw.text((6, 1), self.title, font=self.fonts.bold.font, fill=fg)
            imu = self.shared_state.imu()
            moving = True if imu and imu["quat"] and imu["moving"] else False

            # GPS status
            if self.shared_state.altaz_ready():
                self._gps_brightness = 0
            else:
                gps_anim = int(128 * (time.time() - self.last_update_time)) + 1
                self._gps_brightness += gps_anim
                if self._gps_brightness > 64:
                    self._gps_brightness = -128

            _gps_color = self.colors.get(
                self._gps_brightness if self._gps_brightness > 0 else 0
            )
            self.draw.text(
                (self.display_class.resX * 0.8, -2),
                self._GPS_ICON,
                font=self.fonts.icon_bold_large.font,
                fill=_gps_color,
            )

            if moving:
                self._unmoved = False

            if self.shared_state:
                if self.shared_state.solve_state():
                    solution = self.shared_state.solution()
                    cam_active = solution["solve_time"] == solution["cam_solve_time"]
                    # a fresh cam solve sets unmoved to True
                    self._unmoved = True if cam_active else self._unmoved
                    if self._unmoved:
                        time_since_cam_solve = time.time() - solution["cam_solve_time"]
                        var_fg = min(64, int(time_since_cam_solve / 6 * 64))
                    # self.draw.rectangle([115, 2, 125, 14], fill=bg)

                    if self._unmoved:
                        self.draw.text(
                            (self.display_class.resX * 0.91, -2),
                            self._CAM_ICON,
                            font=self.fonts.icon_bold_large.font,
                            fill=var_fg,
                        )

                    if len(self.title) < 9:
                        # draw the constellation
                        constellation = solution["constellation"]
                        self.draw.text(
                            (self.display_class.resX * 0.54, 1),
                            constellation,  # Should this be translated or not?
                            font=self.fonts.bold.font,
                            fill=fg if self._unmoved else self.colors.get(32),
                        )
                else:
                    # no solve yet....
                    self.draw.text(
                        (self.display_class.resX * 0.91, 0),
                        "X",
                        font=self.fonts.bold.font,
                        fill=fg,
                    )

        screen_to_display = self.screen.convert(self.display.mode)
        self.display.display(screen_to_display)

        if self.shared_state:
            self.shared_state.set_screen(screen_to_display)

        return
