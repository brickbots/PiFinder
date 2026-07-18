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
from PiFinder.types.hardware import ChargeStatus
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:

    def _(a) -> Any:
        return a


# Rate (brightness units per second of elapsed time) for the pulsing GPS
# "searching" animation in the title bar. This is an animation speed, not a
# geometry value — it must NOT scale with display resolution (it previously
# read as a bare ``128`` which looked resolution-derived).
GPS_ANIM_RATE = 128


class RotatingInfoDisplay:
    """Alternates between constellation and SQM with cross-fade animation."""

    def __init__(self, shared_state, interval=3.0, fade_speed=0.15):
        self.shared_state = shared_state
        self.interval = interval
        self.fade_speed = fade_speed
        self.show_sqm = False
        self.last_switch = time.time()
        self.progress = 1.0  # 1.0 = stable, <1.0 = transitioning

    def _get_text(self, use_sqm):
        if use_sqm:
            sqm = self.shared_state.sqm()
            return f"{sqm.value:.1f}" if sqm and sqm.value else "---"
        else:
            sol = self.shared_state.solution()
            return sol.constellation if sol and sol.constellation else "---"

    def update(self):
        """Update state, returns (current_text, previous_text, progress)."""
        now = time.time()
        if now - self.last_switch >= self.interval:
            self.show_sqm = not self.show_sqm
            self.last_switch = now
            self.progress = 0.0
        if self.progress < 1.0:
            self.progress = min(1.0, self.progress + self.fade_speed)
        return (
            self._get_text(self.show_sqm),
            self._get_text(not self.show_sqm),
            self.progress,
        )

    def draw(self, draw, x, y, font, colors, max_brightness=255, inverted=False):
        """Draw with cross-fade animation. inverted=True for dark text on light bg."""
        current, previous, progress = self.update()
        if progress < 1.0:
            fade_out = progress < 0.5
            t = progress * 2 if fade_out else (progress - 0.5) * 2
            if inverted:
                brightness = (
                    int(max_brightness * t)
                    if fade_out
                    else int(max_brightness * (1 - t))
                )
            else:
                brightness = (
                    int(max_brightness * (1 - t))
                    if fade_out
                    else int(max_brightness * t)
                )
            text = previous if fade_out else current
            draw.text((x, y), text, font=font, fill=colors.get(brightness))
        else:
            draw.text(
                (x, y),
                current,
                font=font,
                fill=colors.get(0 if inverted else max_brightness),
            )


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
    # Battery title-bar icons (Material Design glyphs in the bundled Nerd Font).
    # Charging shows a single bolt glyph; otherwise the level is quantized into
    # ~20% buckets with an "empty" glyph at <=10%.  See _battery_icon().
    _BATT_CHARGING = "󰂄"  # F0084 battery + bolt
    _BATT_EMPTY = "󰂎"  # F008E empty outline (<=10%)
    _BATT_20 = "󰁻"  # F007B
    _BATT_40 = "󰁽"  # F007D
    _BATT_60 = "󰁿"  # F007F
    _BATT_80 = "󰂁"  # F0081
    _BATT_FULL = "󰁹"  # F0079
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

        # Rotating info: alternates between constellation and SQM value
        self._rotating_display = RotatingInfoDisplay(self.shared_state)

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

            red_help_image = make_red(help_image, self.colors)

            # Help PNGs are authored at 128x128, but luma requires every
            # displayed image to match the device resolution. Normalise each
            # frame onto a black resX x resY canvas (centred) so it renders on
            # any panel; scale down first if a frame is larger than the display
            # so it always fits. Derived from the display, not special-cased to
            # 176.
            res = (self.display_class.resX, self.display_class.resY)
            if red_help_image.size != res:
                if red_help_image.width > res[0] or red_help_image.height > res[1]:
                    red_help_image = red_help_image.copy()
                    red_help_image.thumbnail(res)
                frame = Image.new("RGB", res, self.colors.get(0))
                frame.paste(
                    red_help_image,
                    (
                        (res[0] - red_help_image.width) // 2,
                        (res[1] - red_help_image.height) // 2,
                    ),
                )
                red_help_image = frame

            help_image_list.append(red_help_image)

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

    def draw_gate_message(self, message: str) -> None:
        """Render a full-screen "precondition not met" notice into ``self.screen``.

        A module that gates itself on a runtime precondition (e.g. a location
        fix) draws this from ``update`` in place of its normal UI and returns
        early; the user reads it and backs out with LEFT/Cancel rather than
        being blocked from opening the screen at all (see ADR 0019). Newlines
        in ``message`` split it into centred lines; a Cancel hint is pinned to
        the bottom-left, mirroring the entry screens' legends.
        """
        self.clear_screen()
        font = self.fonts.bold
        lines = message.split("\n")
        line_h = font.height + 2
        top = self.display_class.titlebar_height
        block_h = line_h * len(lines)
        y = top + max(4, (self.display_class.resY - top - block_h) // 2)
        for line in lines:
            text_w = font.font.getbbox(line)[2]
            x = max(0, (self.display_class.resX - text_w) // 2)
            self.draw.text((x, y), line, font=font.font, fill=self.colors.get(255))
            y += line_h
        self.draw.text(
            (10, self.display_class.resY - self.fonts.base.height - 2),
            _(" Cancel"),
            font=self.fonts.base.font,
            fill=self.colors.get(255),
        )

    def message(self, message, timeout: float = 2, size=None):
        """
        Creates a box with text in the center of the screen.
        Waits timeout in seconds
        """
        if size is None:
            # Centre the popup box on the screen, deriving from the display
            # resolution (was hardcoded to 128: (5, 44, 123, 84)).
            box_w = self.display_class.resX - 10
            box_h = round(self.display_class.resY * 40 / 128)
            x0 = 5
            y0 = (self.display_class.resY - box_h) // 2
            size = (x0, y0, x0 + box_w, y0 + box_h)

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

    def _battery_icon(self, battery) -> str:
        """Pick the title-bar battery glyph for a ``BatteryState``.

        Charging (the charger pulls voltage up, so ``state_of_charge_pct`` is
        ``None``) shows a bolt; ADC-blind on battery (below the blind floor —
        shutdown imminent, ADR 0021) shows empty; otherwise the state of
        charge is quantized into ~20% buckets, with the empty glyph at <=10%
        remaining.
        """
        if battery.charge_status in (
            ChargeStatus.PRE_CHARGE,
            ChargeStatus.FAST_CHARGING,
        ):
            return self._BATT_CHARGING

        if battery.adc_blind:
            return self._BATT_EMPTY

        soc = battery.state_of_charge_pct
        if soc is None:
            # Not charging, not blind, yet no estimate (shouldn't happen) —
            # fail safe to full.
            return self._BATT_FULL
        if soc <= 10:
            return self._BATT_EMPTY
        if soc <= 30:
            return self._BATT_20
        if soc <= 50:
            return self._BATT_40
        if soc <= 70:
            return self._BATT_60
        if soc <= 90:
            return self._BATT_80
        return self._BATT_FULL

    def _draw_battery_icon(self, fg) -> bool:
        """Draw the battery indicator to the left of the GPS/solver icons.

        Only rendered on battery-enabled hardware once a real reading exists;
        ``shared_state.battery()`` is ``None`` both on non-battery boards and in
        the brief window before the monitor's first sample, so we show nothing
        rather than a fake level.

        returns True if the battery indicator was drawn (has battery)
                False if no battery hardware
        """
        hardware = self.shared_state.hardware()
        if not (hardware and hardware.has_bq25895):
            return False
        battery = self.shared_state.battery()
        if battery is None:
            return False

        icon = self._battery_icon(battery)
        font = self.fonts.icon_bold_large.font
        # Sit just left of the GPS icon (resX * 0.8) with a small, proportional
        # gap so the battery reads as its own group.  Battery hardware is always
        # paired with a 176px+ display, so this clears the rotating
        # constellation/SQM without needing to reflow it.
        gps_x = self.display_class.resX * 0.8
        icon_w = font.getlength(icon)
        gap = self.display_class.resX * 0.035
        self.draw.text(
            (gps_x - icon_w - gap, -2),
            icon,
            font=font,
            fill=fg,
        )

        return True

    def _draw_titlebar_rotating_info(self, x, y, fg):
        """Draw rotating constellation/SQM in title bar (dark text on gray bg)."""
        self._rotating_display.draw(
            self.draw,
            x,
            y,
            self.fonts.bold.font,
            self.colors,
            max_brightness=64,
            inverted=True,
        )

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
            tb_height = self.display_class.titlebar_height
            self.draw.rectangle(
                [0, 0, self.display_class.resX, tb_height],
                fill=bg,
            )
            # Vertically centre the title-bar text / icons in the bar so they
            # track titlebar_height across displays (was hardcoded for 128).
            title_y = max(0, (tb_height - self.fonts.bold.height) // 2)
            icon_y = (tb_height - self.fonts.icon_bold_large.height) // 2
            title_text = str(self.fps) if self.ui_state.show_fps() else _(self.title)
            # Truncate so the title never runs under the right-side status icons.
            # They start at the GPS icon (~0.8*resX); leave a small gap. Derived
            # from the screen size + bold font, so it adapts to 128/176/320.
            title_max_px = int(self.display_class.resX * 0.8) - 6 - 4
            title_max_chars = max(1, title_max_px // self.fonts.bold.width)
            if len(title_text) > title_max_chars:
                title_text = title_text[: title_max_chars - 1] + "…"
            self.draw.text((6, title_y), title_text, font=self.fonts.bold.font, fill=fg)
            imu = self.shared_state.imu()
            moving = True if imu and imu.quat and imu.moving else False

            # GPS status
            if self.shared_state.altaz_ready():
                self._gps_brightness = 0
            else:
                gps_anim = (
                    int(GPS_ANIM_RATE * (time.time() - self.last_update_time)) + 1
                )
                self._gps_brightness += gps_anim
                if self._gps_brightness > 64:
                    self._gps_brightness = -128

            _gps_color = self.colors.get(
                self._gps_brightness if self._gps_brightness > 0 else 0
            )
            self.draw.text(
                (self.display_class.resX * 0.8, icon_y),
                self._GPS_ICON,
                font=self.fonts.icon_bold_large.font,
                fill=_gps_color,
            )

            # Battery indicator (battery-enabled hardware only), just left of GPS
            battery_drawn = self._draw_battery_icon(fg)

            if moving:
                self._unmoved = False

            if self.shared_state:
                if self.shared_state.solve_state():
                    solution = self.shared_state.solution()
                    cam_active = solution.is_camera_solve()
                    # a fresh cam solve sets unmoved to True
                    self._unmoved = True if cam_active else self._unmoved
                    if self._unmoved:
                        time_since_cam_solve = time.time() - (
                            solution.last_solve_success or 0.0
                        )
                        var_fg = min(64, int(time_since_cam_solve / 3 * 64))
                    # self.draw.rectangle([115, 2, 125, 14], fill=bg)

                    if self._unmoved:
                        self.draw.text(
                            (self.display_class.resX * 0.91, icon_y),
                            self._CAM_ICON,
                            font=self.fonts.icon_bold_large.font,
                            fill=var_fg,
                        )

                    if len(self.title) < 9:
                        # Draw rotating constellation/SQM wheel (replaces static constellation)

                        # Adjust spacing a bit if the battery indicator is present
                        titlebar_position = 0.50 if battery_drawn else 0.54

                        self._draw_titlebar_rotating_info(
                            x=int(self.display_class.resX * titlebar_position),
                            y=title_y,
                            fg=fg if self._unmoved else self.colors.get(32),
                        )
                else:
                    # no solve yet....
                    self.draw.text(
                        (self.display_class.resX * 0.91, title_y),
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

    def key_power(self):
        """
        Power button.  Default behaviour for every module is to jump
        straight to the shutdown confirmation menu.  The shutdown screen
        itself (a UITextMenu) overrides this to act as a select, so a
        first press raises the confirmation and a second press confirms.
        """
        self.jump_to_label("shutdown")
