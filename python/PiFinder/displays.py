from typing import Type
import functools
from collections import namedtuple

import numpy as np
from PIL import Image

from luma.core.interface.serial import spi
from luma.oled.device import ssd1351
from luma.lcd.device import st7789


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

    def __init__(self):
        self.colors = Colors(self.color_mask, self.resolution)

    def set_brightness(self, brightness: int) -> None:
        return None


class DisplayPygame(DisplayBase):
    resolution = (128, 128)

    def __init__(self):
        from luma.emulator.device import pygame

        # init display  (SPI hardware)
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


class DisplaySSD1351(DisplayBase):
    resolution = (128, 128)

    def __init__(self):
        # init display  (SPI hardware)
        serial = spi(device=0, port=0)
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


class DisplayST7789(DisplayBase):
    resolution = (320, 240)

    def __init__(self):
        # init display  (SPI hardware)
        serial = spi(device=0, port=0)
        device_serial = st7789(serial, bgr=True)

        device_serial.capabilities(
            width=self.resolution[0], height=self.resolution[1], rotate=0, mode="RGB"
        )
        self.device = device_serial
        super().__init__()


def get_display(hardware_platform: str) -> Type[DisplayBase]:

    if hardware_platform == "Fake":
        return DisplayPygame()

    if hardware_platform == "Pi":
        return DisplaySSD1351()

    if hardware_platform == "PFPro":
        return DisplayST7789()

    else:
        print("Hardware platform not recognized")
