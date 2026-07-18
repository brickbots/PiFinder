import functools
import logging
from collections import namedtuple

import numpy as np
from PIL import Image

import luma.core.device
from luma.core.interface.serial import spi
from luma.oled.device import ssd1351
from luma.lcd.device import st7789

from PiFinder.ssd1333_device import ssd1333

from PiFinder.ui.fonts import Fonts

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
    # Number of carousel rows a UITextMenu shows at once. Must be ODD so the
    # selected item sits on the symmetric center (focus) line.
    menu_visible_items = 7
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


class DisplayPygame_128(DisplayBase):
    resolution = (128, 128)

    def __init__(self):
        from luma.emulator.device import pygame
        import pygame as pg
        from pathlib import Path

        # Set window icon to welcome splash screen before creating display
        icon_path = Path(__file__).parent.parent.parent / "images" / "welcome.png"
        if icon_path.exists():
            icon = pg.image.load(str(icon_path))
            pg.display.set_icon(icon)

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
        super().__init__()


class Layout320:
    """Shared 320x240 layout profile for the ST7789 LCD.

    Every 320 render target — the real LCD, the pygame emulator, and the
    headless dummy — must lay out identically for the emulator to faithfully
    preview the hardware (same role as ``Layout176`` for the 1.91" panel).
    """

    resolution = (320, 240)
    titlebar_height = 22
    base_font_size = 16
    bold_font_size = 19
    small_font_size = 13
    large_font_size = 24
    huge_font_size = 70


class DisplayPygame_320(Layout320, DisplayBase):
    """Pygame emulator at 320x240 with the ST7789 layout profile.

    Lets the LCD UI be previewed on a dev machine with no Pi/panel; the
    ``Layout320`` profile means it renders with the same fonts/spacing as the
    real LCD. Select with ``--display pg_320``.
    """

    def __init__(self):
        from luma.emulator.device import pygame
        import pygame as pg
        from pathlib import Path

        # Set window icon to welcome splash screen before creating display
        icon_path = Path(__file__).parent.parent.parent / "images" / "welcome.png"
        if icon_path.exists():
            icon = pg.image.load(str(icon_path))
            pg.display.set_icon(icon)

        pygame = pygame(
            width=self.resolution[0],
            height=self.resolution[1],
            rotate=0,
            mode="RGB",
            frame_rate=60,
        )
        self.device = pygame
        super().__init__()


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
        Sets oled brightness 0-255, combining master brightness (0xC7)
        and per-channel contrast (0xC1) for maximum dimming range.

        Levels 0-15:  both master and contrast scale together, giving
                      very dim output below what contrast alone can achieve.
        Levels 16-255: master at full, contrast varies linearly.
        """
        level = max(0, min(255, level))
        if level <= 15:
            self.device.command(0xC7, level)
            self.device.contrast(level)
        else:
            self.device.command(0xC7, 0x0F)
            self.device.contrast(level)


class Layout176:
    """Shared 176x176 layout profile for the 1.91" panel.

    The SSD1333 controller only addresses 176x176 (see ``ssd1333_device``), so
    every 176 render target — the real OLED, the pygame emulator, and the
    headless dummy — must lay out identically for the emulator to faithfully
    preview the hardware. These knobs are the hand-tuned half of the
    resolution-flexible UI (geometry derives from them + font metrics):
    fonts run ~15-20% larger than the 128 panel for slightly bigger glyphs at
    near-identical pixel density, and the carousel shows two extra rows.
    """

    resolution = (176, 176)
    titlebar_height = 20
    base_font_size = 12
    bold_font_size = 14
    small_font_size = 10
    large_font_size = 18
    huge_font_size = 42
    menu_visible_items = 9


class DisplaySSD1333(Layout176, DisplayBase):
    def __init__(self):
        # init display  (SPI hardware)
        serial = spi(device=0, port=0, bus_speed_hz=40000000)
        device_serial = ssd1333(serial, width=176, height=176, rotate=3, bgr=True)
        self.device = device_serial
        super().__init__()

    def set_brightness(self, level):
        """
        Sets oled brightness 0-255, combining master brightness (0xC7)
        and per-channel contrast (0xC1) for maximum dimming range.

        Levels 0-15:  both master and contrast scale together, giving
                      very dim output below what contrast alone can achieve.
        Levels 16-255: master at full, contrast varies linearly.
        """
        level = max(0, min(255, level))
        if level <= 15:
            self.device.master_brightness(level)
            self.device.contrast(level)
        else:
            self.device.master_brightness(15)
            self.device.contrast(level)


class DisplayPygame_176(Layout176, DisplayBase):
    """Pygame emulator at 176x176 with the SSD1333 layout profile.

    Lets the 1.91" UI be previewed on a dev machine with no Pi/panel; the
    ``Layout176`` profile means it renders with the same fonts/spacing as the
    real OLED. Select with ``--display pg_176``.
    """

    def __init__(self):
        from luma.emulator.device import pygame

        pygame = pygame(
            width=self.resolution[0],
            height=self.resolution[1],
            rotate=0,
            mode="RGB",
            transform="scale2x",
            scale=2,
            frame_rate=60,
        )
        self.device = pygame
        super().__init__()


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


class DisplayST7789(Layout320, DisplayBase):
    def __init__(self):
        # init display  (SPI hardware)
        serial = spi(device=0, port=0, bus_speed_hz=52000000)
        device_serial = st7789(serial, bgr=True)

        device_serial.capabilities(
            width=self.resolution[0], height=self.resolution[1], rotate=0, mode="RGB"
        )
        self.device = device_serial
        super().__init__()


class DisplayHeadless(DisplayBase):
    """In-memory display for remote control / automation.

    Renders to a luma ``dummy`` device, which keeps the most recent frame as a
    PIL image but draws no window and talks to no SPI hardware. This lets
    PiFinder run on a machine with no physical display and no SDL/X session
    (e.g. a CI box or a headless dev session) without pulling in pygame.

    Nothing here feeds the API directly: the UI render loop already calls
    ``shared_state.set_screen()`` right beside ``device.display()``, so the
    current screen stays available over ``GET /api/screen`` no matter which
    display driver is active. This driver simply makes the hardware-facing
    half of that pair a no-op.
    """

    resolution = (128, 128)
    color_mask = RED_RGB

    def __init__(self):
        # luma.core.device.dummy lives in luma.core (not the emulator package),
        # so importing it does not require pygame to be installed.
        from luma.core.device import dummy

        self.device = dummy(
            width=self.resolution[0],
            height=self.resolution[1],
            mode="RGB",
        )
        super().__init__()


class DisplayHeadless176(Layout176, DisplayHeadless):
    """Headless (luma ``dummy``) display at 176x176 with the SSD1333 layout.

    The no-hardware target for driving/screenshotting the 1.91" UI over the
    HTTP API (``/api/screen`` serves whatever resolution the UI publishes).
    Select with ``--display headless_176``.
    """


class DisplayHeadless320(Layout320, DisplayHeadless):
    """Headless (luma ``dummy``) display at 320x240 with the ST7789 layout.

    The no-hardware target for driving/screenshotting the LCD UI over the
    HTTP API. Select with ``--display headless_320``.
    """


def get_display(display_hardware: str) -> DisplayBase:
    if display_hardware == "headless":
        return DisplayHeadless()

    if display_hardware == "headless_176":
        return DisplayHeadless176()

    if display_hardware == "headless_320":
        return DisplayHeadless320()

    if display_hardware == "pg_128":
        return DisplayPygame_128()

    if display_hardware == "pg_176":
        return DisplayPygame_176()

    if display_hardware == "pg_320":
        return DisplayPygame_320()

    if display_hardware == "ssd1351":
        return DisplaySSD1351()

    if display_hardware == "ssd1333":
        return DisplaySSD1333()

    if display_hardware == "st7789":
        return DisplayST7789()

    else:
        print("Hardware platform not recognized")
        return DisplaySSD1351()
