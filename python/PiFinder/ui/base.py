#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module contains the base UIModule class

"""

import time
import uuid
from itertools import cycle
from typing import Type, Union

from PIL import Image, ImageDraw
from PiFinder import utils
from PiFinder.image_util import make_red
from PiFinder.displays import DisplayBase
from PiFinder.config import Config
from PiFinder.ui.marking_menus import MarkingMenu
from PiFinder.catalogs import Catalogs
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:

    def _(a) -> Any:
        return a


class UIModule:
    __title__ = "BASE"
    __help_name__ = ""
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
    _SQUARE_ = "󰝤"
    _ARROWS_ = ""
    _PLUS_ = "󰐕"
    _MINUS_ = "󰍴"
    _PLUSMINUS_ = "󰐕/󰍴"
    _gps_brightness = 0
    _unmoved = False  # has the telescope moved since the last cam solve?
    _display_mode_list: Union[list[None], list[str]] = [None]  # List of display modes
    marking_menu: Union[None, MarkingMenu] = None

    def __init__(
        self,
        display_class: Type[DisplayBase],
        camera_image,
        shared_state,
        command_queues,
        config_object,
        catalogs: Catalogs,
        item_definition={},
        add_to_stack=None,
        remove_from_stack=None,
        jump_to_label=None,
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
        self.jump_to_label = jump_to_label

        # mode stuff
        self._display_mode_cycle = cycle(self._display_mode_list)
        self.display_mode = next(self._display_mode_cycle)

        self.screen = Image.new("RGB", display_class.resolution)
        self.draw = ImageDraw.Draw(self.screen, mode="RGBA")
        self.fonts = self.display_class.fonts

        # UI Module definition
        self.item_definition = item_definition
        self.title = item_definition.get("name", self.title)

        self.config_object: Config = config_object

        # FPS
        self.fps = 0
        self.frame_count = 0
        self.last_fps_sample_time = time.time()

        # anim timer stuff
        self.last_update_time = time.time()

    def active(self):
        """
        Called when a module becomes active
        i.e. foreground controlling display
        """
        pass

    def inactive(self):
        """
        Called when a module becomes inactive
        i.e. leaving a UI screen
        """
        pass

    def help(self) -> Union[None, list[Image.Image]]:
        """
        Called when help is selected from the
        marking menu.  Should render the
        help screens as a list of images to be displayed
        up/down arrow will scroll through images
        """
        if self.__help_name__ == "":
            return None

        help_image_list = []
        help_image_path = utils.pifinder_dir / "help" / self.__help_name__
        for i in range(1, 10):
            try:
                help_image = Image.open(help_image_path / f"{i}.png")
            except FileNotFoundError:
                break

            # help_image_list.append(
            #    convert_image_to_mode(help_image, self.colors.mode)
            # )

            help_image_list.append(make_red(help_image, self.colors))

        if help_image_list == []:
            return None
        return help_image_list

    def update(self, force=False) -> None:
        """
        Called to trigger UI Updates
        to be overloaded by subclases and shoud
        end up calling self.screen_update to
        to the actual screen draw
        retun the results of the screen_update to
        pass any signals back to main
        """
        self.screen_update()

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

    def message(self, message, timeout: float = 2, size=(5, 44, 123, 84)):
        """
        Creates a box with text in the center of the screen.
        Waits timeout in seconds
        """

        # shadow
        self.draw.rectangle(
            (size[0] + 5, size[1] + 5, size[2] + 5, size[3] + 5),
            fill=self.colors.get(0),
            outline=self.colors.get(0),
        )
        self.draw.rectangle(size, fill=self.colors.get(0), outline=self.colors.get(128))

        line_length = int((size[2] - size[0]) / self.fonts.bold.width)
        message = " " * int((line_length - len(message)) / 2) + message

        self.draw.text(
            (size[0] + 4, size[1] + 5),
            message,
            font=self.fonts.bold.font,
            fill=self.colors.get(255),
        )
        screen_to_display = self.screen.convert(self.display.mode)
        self.display.display(screen_to_display)

        # Update shared state so web interface shows the popup message
        if self.shared_state:
            self.shared_state.set_screen(screen_to_display)

        self.ui_state.set_message_timeout(timeout + time.time())

    def screen_update(self, title_bar=True, button_hints=True) -> None:
        """
        called to trigger UI updates
        takes self.screen adds title bar and
        writes to display
        """

        # Don't redraw screen if message popup is active
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
                self.draw.text(
                    (6, 1), _(self.title), font=self.fonts.bold.font, fill=fg
                )
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

        # FPS
        self.frame_count += 1
        if int(time.time()) - self.last_fps_sample_time > 0:
            # flipped second
            self.fps = self.frame_count
            self.frame_count = 0
            self.last_fps_sample_time = int(time.time())

        self.last_update_time = time.time()

    # Marking menu items
    def cycle_display_mode(self):
        """
        Cycle through available display modes
        for a module.  Invoked when the square
        key is pressed
        """
        self.display_mode = next(self._display_mode_cycle)

    def key_number(self, number):
        pass

    def key_plus(self):
        pass

    def key_minus(self):
        pass

    def key_square(self):
        self.cycle_display_mode()
        self.update()

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

    def key_left(self) -> bool:
        """
        This is passed through from menu_manager
        and normally results in the module being
        removed from the stack.  Return False to
        override the remove from stack behavior
        """
        return True
