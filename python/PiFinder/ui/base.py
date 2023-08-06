#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module contains the base UIModule class

"""
import os
import time
import uuid
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageChops, ImageOps
from PiFinder.ui.fonts import Fonts as fonts
from PiFinder import utils
from PiFinder.image_util import DeviceWrapper


class UIModule:
    __title__ = "BASE"
    __uuid__ = str(uuid.uuid1()).split("-")[0]
    _config_options = None

    def __init__(
        self,
        device_wrapper: DeviceWrapper,
        camera_image,
        shared_state,
        command_queues,
        ui_state={},
        config_object=None,
    ):
        self.title = self.__title__
        self.switch_to = None
        self.display = device_wrapper.device
        self.colors = device_wrapper.colors
        self.shared_state = shared_state
        self.camera_image = camera_image
        self.command_queues = command_queues
        self.screen = Image.new("RGB", (128, 128))
        self.draw = ImageDraw.Draw(self.screen)
        self.font_base = fonts.base
        self.font_bold = fonts.bold
        self.font_large = fonts.large

        # screenshot stuff
        root_dir = str(utils.data_dir)
        prefix = f"{self.__uuid__}_{self.__title__}"
        self.ss_path = os.path.join(root_dir, "screenshots", prefix)
        self.ss_count = 0
        self.ui_state = ui_state
        self.config_object = config_object

    def exit_config(self, option):
        """
        Handy callback for exiting
        config on option select
        """
        return True

    def update_config(self):
        """
        callback when config is updated
        """
        return True

    def cycle_config(self, config_item, direction=1):
        """
        Cycles through a config option
        wrapping if needed
        """
        current_index = self._config_options[config_item]["options"].index(
            self._config_options[config_item]["value"]
        )
        current_index += direction
        if current_index >= len(self._config_options[config_item]["options"]):
            current_index = 0

        self._config_options[config_item]["value"] = self._config_options[config_item][
            "options"
        ][current_index]

    def screengrab(self):
        self.ss_count += 1
        ss_imagepath = self.ss_path + f"_{self.ss_count :0>3}.png"
        ss = self.screen.getchannel("B")
        ss = ss.convert("RGB")
        ss = ImageChops.multiply(ss, Image.new("RGB", (128, 128), (255, 0, 0)))
        ss.save(ss_imagepath)

    def active(self):
        """
        Called when a module becomes active
        i.e. foreground controlling display
        """
        pass

    def background_update(self):
        """
        Called every 5th ui cycle on all modules
        allows background tasks, like updating
        altitude in the Catalog
        """
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
        self.draw.text((9, 54), message, font=self.font_bold, fill=self.colors.get(255))
        self.display.display(self.screen.convert(self.display.mode))
        self.ui_state["message_timeout"] = timeout + time.time()

    def screen_update(self, title_bar=True):
        """
        called to trigger UI updates
        takes self.screen adds title bar and
        writes to display
        """
        if time.time() < self.ui_state["message_timeout"]:
            return None

        if title_bar:
            self.draw.rectangle([0, 0, 128, 16], fill=self.colors.get(64))
            self.draw.text(
                (6, 1), self.title, font=self.font_bold, fill=self.colors.get(0)
            )
            if self.shared_state:
                if self.shared_state.solve_state():
                    solution = self.shared_state.solution()
                    constellation = solution["constellation"]
                    self.draw.text(
                        (70, 1),
                        constellation,
                        font=self.font_bold,
                        fill=self.colors.get(0),
                    )

                    # Solver Status
                    time_since_solve = time.time() - solution["cam_solve_time"]
                    bg = int(64 - (time_since_solve / 6 * 64))
                    if bg < 0:
                        bg = 0
                    self.draw.rectangle([115, 2, 125, 14], fill=self.colors.get(bg))
                    self.draw.text(
                        (117, 0),
                        solution["solve_source"][0],
                        font=self.font_bold,
                        fill=self.colors.get(64),
                    )
                else:
                    # no solve yet....
                    self.draw.rectangle([115, 2, 125, 14], fill=self.colors.get(0))
                    self.draw.text(
                        (117, 0), "X", font=self.font_bold, fill=self.colors.get(64)
                    )

                # GPS status
                if self.shared_state.location()["gps_lock"]:
                    fg = self.colors.get(0)
                    bg = self.colors.get(64)
                else:
                    fg = self.colors.get(64)
                    bg = self.colors.get(0)
                self.draw.rectangle([100, 2, 110, 14], fill=bg)
                self.draw.text((102, 0), "G", font=self.font_bold, fill=fg)

        screen_to_display = self.screen.convert(self.display.mode)
        self.display.display(screen_to_display)
        if self.shared_state:
            self.shared_state.set_screen(screen_to_display)

        # We can return a UIModule class name to force a switch here
        tmp_return = self.switch_to
        self.switch_to = None
        return tmp_return

    def check_hotkey(self, key):
        """
               Scans config for a matching
        _       hotkey and if found, cycles
               that config item.

               Returns true if hotkey found
               false if not or no config
        """
        if self._config_options == None:
            return False

        for config_item_name, config_item in self._config_options.items():
            if config_item.get("hotkey") == key:
                self.cycle_config(config_item_name)
                return True

        return False

    def key_number(self, number):
        pass

    def key_up(self):
        pass

    def key_down(self):
        pass

    def key_enter(self):
        pass

    def key_long_c(self):
        pass

    def delete(self):
        pass

    def key_b(self):
        if self.check_hotkey("B"):
            self.update(force=True)

    def key_c(self):
        if self.check_hotkey("C"):
            self.update(force=True)

    def key_d(self):
        if self.check_hotkey("D"):
            self.update(force=True)
