import functools
import logging
from collections import namedtuple

import numpy as np
from PIL import Image

import luma.core.device
from luma.core.interface.serial import spi
from luma.oled.device import ssd1351
from luma.lcd.device import st7789

from PiFinder.ui.fonts import Fonts
from PiFinder.keyboard_interface import KeyboardInterface

logger = logging.getLogger("Display")

ColorMask = namedtuple("ColorMask", ["mask", "mode"])
RED_RGB: ColorMask = ColorMask(np.array([1, 0, 0]), "RGB")
RED_BGR: ColorMask = ColorMask(np.array([0, 0, 1]), "BGR")
GREY: ColorMask = ColorMask(np.array([1, 1, 1]), "RGB")


class Colors:
    def __init__(self, color_mask: ColorMask, resolution: tuple[int, int]):
        self.color_mask = color_mask[0]
        self.mode = color_mask[1]
        self.red_image = Image.new("RGB", (resolution[0], resolution[1]), self.get(255))

    @functools.cache
    def get(self, color_intensity):
        arr = self.color_mask * color_intensity
        result = tuple(arr)
        return result


class DisplayBase:
    resolution = (128, 128)
    color_mask = RED_RGB
    titlebar_height = 17
    base_font_size = 10
    bold_font_size = 12
    small_font_size = 8
    large_font_size = 15
    huge_font_size = 35
    device = luma.core.device.device

    def __init__(self):
        self.colors = Colors(self.color_mask, self.resolution)
        self.fonts = Fonts(
            self.base_font_size,
            self.bold_font_size,
            self.small_font_size,
            self.large_font_size,
            self.huge_font_size,
            self.resolution[0],
        )

        # calculated display params
        self.centerX = int(self.resolution[0] / 2)
        self.centerY = int(self.resolution[1] / 2)
        self.fov_res = min(self.resolution[0], self.resolution[1])

        self.resX = self.resolution[0]
        self.resY = self.resolution[1]

    def set_brightness(self, brightness: int) -> None:
        return None

    def set_keyboard_queue(self, q) -> None:
        pass


# Pygame key → PiFinder keycode mapping (mirrors keyboard_local.py)
_PYGAME_KEY_MAP: dict[int, int] = {}


def _build_key_map(pg) -> dict[int, int]:
    if _PYGAME_KEY_MAP:
        return _PYGAME_KEY_MAP
    KI = KeyboardInterface
    m = {
        pg.K_LEFT: KI.LEFT,
        pg.K_UP: KI.UP,
        pg.K_DOWN: KI.DOWN,
        pg.K_RIGHT: KI.RIGHT,
        pg.K_q: KI.PLUS,
        pg.K_a: KI.MINUS,
        pg.K_z: KI.SQUARE,
        pg.K_w: KI.ALT_PLUS,
        pg.K_s: KI.ALT_MINUS,
        pg.K_d: KI.ALT_LEFT,
        pg.K_r: KI.ALT_UP,
        pg.K_f: KI.ALT_DOWN,
        pg.K_g: KI.ALT_RIGHT,
        pg.K_e: KI.ALT_0,
        pg.K_j: KI.LNG_LEFT,
        pg.K_i: KI.LNG_UP,
        pg.K_k: KI.LNG_DOWN,
        pg.K_l: KI.LNG_RIGHT,
        pg.K_m: KI.LNG_SQUARE,
        pg.K_0: 0,
        pg.K_1: 1,
        pg.K_2: 2,
        pg.K_3: 3,
        pg.K_4: 4,
        pg.K_5: 5,
        pg.K_6: 6,
        pg.K_7: 7,
        pg.K_8: 8,
        pg.K_9: 9,
    }
    _PYGAME_KEY_MAP.update(m)
    return _PYGAME_KEY_MAP


def _patch_pygame_keyboard(display_obj):
    """Replace luma's _abort on the pygame device to capture keyboard events."""
    device = display_obj.device
    pg = device._pygame
    key_map = _build_key_map(pg)

    def _abort_with_keys():
        for event in pg.event.get():
            if event.type == pg.QUIT:
                return True
            if event.type == pg.KEYDOWN:
                if event.key == pg.K_ESCAPE:
                    return True
                q = display_obj._keyboard_queue
                if q is not None:
                    keycode = key_map.get(event.key)
                    if keycode is not None:
                        q.put(keycode)
        return False

    device._abort = _abort_with_keys


class DisplayPygame_128(DisplayBase):
    resolution = (128, 128)

    def __init__(self):
        from luma.emulator.device import pygame

        self._keyboard_queue = None
        pygame = pygame(
            width=128,
            height=128,
            rotate=0,
            mode="RGB",
            transform="scale2x",
            scale=2,
            frame_rate=60,
        )
        self.device = pygame
        _patch_pygame_keyboard(self)
        super().__init__()

    def set_keyboard_queue(self, q) -> None:
        self._keyboard_queue = q


class DisplayPygame_320(DisplayBase):
    resolution = (320, 240)

    def __init__(self):
        from luma.emulator.device import pygame

        self._keyboard_queue = None
        pygame = pygame(
            width=320,
            height=240,
            rotate=0,
            mode="RGB",
            frame_rate=60,
        )
        self.device = pygame
        _patch_pygame_keyboard(self)
        super().__init__()

    def set_keyboard_queue(self, q) -> None:
        self._keyboard_queue = q


class DisplaySSD1351(DisplayBase):
    resolution = (128, 128)

    def __init__(self):
        # init display  (SPI hardware)
        serial = spi(device=0, port=0, bus_speed_hz=40000000)
        device_serial = ssd1351(serial, rotate=0, bgr=True)

        device_serial.capabilities(
            width=self.resolution[0], height=self.resolution[1], rotate=0, mode="RGB"
        )
        self.device = device_serial
        super().__init__()

    def set_brightness(self, level):
        """
        Sets oled brightness
        0-255
        """
        self.device.contrast(level)


class DisplayST7789_128(DisplayBase):
    resolution = (128, 128)

    def __init__(self):
        # init display  (SPI hardware)
        serial = spi(device=0, port=0, bus_speed_hz=52000000)
        device_serial = st7789(serial, bgr=True)

        device_serial.capabilities(
            width=self.resolution[0], height=self.resolution[1], rotate=0, mode="RGB"
        )
        self.device = device_serial
        super().__init__()


class DisplayST7789(DisplayBase):
    resolution = (320, 240)
    titlebar_height = 22
    base_font_size = 16
    bold_font_size = 19
    small_font_size = 13
    large_font_size = 24
    huge_font_size = 70

    def __init__(self):
        # init display  (SPI hardware)
        serial = spi(device=0, port=0, bus_speed_hz=52000000)
        device_serial = st7789(serial, bgr=True)

        device_serial.capabilities(
            width=self.resolution[0], height=self.resolution[1], rotate=0, mode="RGB"
        )
        self.device = device_serial
        super().__init__()


def get_display(display_hardware: str) -> DisplayBase:
    if display_hardware == "pg_128":
        return DisplayPygame_128()

    if display_hardware == "pg_320":
        return DisplayPygame_320()

    if display_hardware == "ssd1351":
        return DisplaySSD1351()

    if display_hardware == "st7789":
        return DisplayST7789()

    else:
        print("Hardware platform not recognized")
        return DisplaySSD1351()
