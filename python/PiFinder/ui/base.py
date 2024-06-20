#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module contains the base UIModule class

"""

import os
import time
import uuid
from typing import Type

from PIL import Image, ImageDraw
from PiFinder import utils
from PiFinder.displays import DisplayBase
from PiFinder.config import Config


class UIModule:
    __title__ = "BASE"
    __uuid__ = str(uuid.uuid1()).split("-")[0]
    _config_options: dict
    _CAM_ICON = ""
    _IMU_ICON = ""
    _GPS_ICON = "󰤉"
    _LEFT_ARROW = ""
    _RIGHT_ARROW = ""
    _UP_ARROW = ""
    _DOWN_ARROW = ""
    _CHECKMARK = ""
    _gps_brightness = 0
    _unmoved = False  # has the telescope moved since the last cam solve?

    def __init__(
        self,
        display_class: Type[DisplayBase],
        camera_image,
        shared_state,
        command_queues,
        config_object,
        catalogs=None,
        item_definition={},
        add_to_stack=None,
        remove_from_stack=None,
    ):
        assert shared_state is not None
        self.title = self.__title__
        self.display_class = display_class
        self.display = display_class.device
        self.colors = display_class.colors
        self.shared_state = shared_state
        self.catalogs = catalogs
        self.ui_state = shared_state.ui_state()
        self.camera_image = camera_image
        self.command_queues = command_queues
        self.add_to_stack = add_to_stack
        self.remove_from_stack = remove_from_stack

        self.screen = Image.new("RGB", display_class.resolution)
        self.draw = ImageDraw.Draw(self.screen, mode="RGBA")
        self.fonts = self.display_class.fonts

        # UI Module definition
        self.item_definition = item_definition
        self.title = item_definition.get("name", self.title)

        # screenshot stuff
        root_dir = str(utils.data_dir)
        prefix = f"{self.__uuid__}_{self.title}"
        self.ss_path = os.path.join(root_dir, "screenshots", prefix)
        self.ss_count = 0
        self.config_object: Config = config_object

        # FPS
        self.fps = 0
        self.frame_count = 0
        self.last_fps_sample_time = time.time()

    def screengrab(self):
        self.ss_count += 1
        ss_imagepath = self.ss_path + f"_{self.ss_count :0>3}.png"
        ss = self.screen.copy()
        ss.save(ss_imagepath)

    def active(self):
        """
        Called when a module becomes active
        i.e. foreground controlling display
        """
        self.button_hints_timer = time.time()
        pass

    def update(self, force=False):
        """
        Called to trigger UI Updates
        to be overloaded by subclases and shoud
        end up calling self.screen_update to
        to the actual screen draw
        retun the results of the screen_update to
        pass any signals back to main
        """
        return self.screen_update()

    def clear_screen(self):
        """
        Clears the screen (draws rectangle in black)
        """
        self.draw.rectangle(
            [
                0,
                0,
                self.display_class.resX,
                self.display_class.resY,
            ],
            fill=self.colors.get(0),
        )

    def message(self, message, timeout=2):
        """
        Creates a box with text in the center of the screen.
        Waits timeout in seconds
        """

        self.draw.rectangle(
            [10, 49, 128, 89], fill=self.colors.get(0), outline=self.colors.get(0)
        )
        self.draw.rectangle(
            [5, 44, 123, 84], fill=self.colors.get(0), outline=self.colors.get(128)
        )
        message = " " * int((16 - len(message)) / 2) + message
        self.draw.text(
            (9, 54), message, font=self.fonts.bold.font, fill=self.colors.get(255)
        )
        self.display.display(self.screen.convert(self.display.mode))
        self.ui_state.set_message_timeout(timeout + time.time())

    def screen_update(self, title_bar=True, button_hints=True):
        """
        called to trigger UI updates
        takes self.screen adds title bar and
        writes to display
        """
        if time.time() < self.ui_state.message_timeout():
            return None

        if title_bar:
            fg = self.colors.get(0)
            bg = self.colors.get(64)
            self.draw.rectangle(
                [0, 0, self.display_class.resX, self.display_class.titlebar_height],
                fill=bg,
            )
            if self.ui_state.show_fps():
                self.draw.text(
                    (6, 1), str(self.fps), font=self.fonts.bold.font, fill=fg
                )
            else:
                self.draw.text((6, 1), self.title, font=self.fonts.bold.font, fill=fg)
            imu = self.shared_state.imu()
            moving = True if imu and imu["pos"] and imu["moving"] else False

            # GPS status
            if self.shared_state.location()["gps_lock"]:
                self._gps_brightness = 0
            else:
                self._gps_brightness += 1
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
                            constellation,
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

        # FPS
        self.frame_count += 1
        if int(time.time()) - self.last_fps_sample_time > 0:
            # flipped second
            self.fps = self.frame_count
            self.frame_count = 0
            self.last_fps_sample_time = int(time.time())

        if self.shared_state:
            self.shared_state.set_screen(screen_to_display)

        return

    def check_hotkey(self, key):
        """
               Scans config for a matching
        _       hotkey and if found, cycles
               that config item.

               Returns true if hotkey found
               false if not or no config
        """
        if self._config_options is None:
            return False

        for config_item_name, config_item in self._config_options.items():
            if config_item.get("hotkey") == key:
                self.cycle_config(config_item_name)
                return True

        return False

    def key_number(self, number):
        pass

    def key_plus(self):
        pass

    def key_minus(self):
        pass

    def key_square(self):
        pass

    def key_long_up(self):
        pass

    def key_long_down(self):
        pass

    def key_long_right(self):
        pass

    def key_up(self):
        pass

    def key_down(self):
        pass

    def key_right(self):
        pass
