import functools
import math
from collections import namedtuple

import numpy as np
from PIL import Image

import luma.core.device
from luma.core.interface.serial import spi
from luma.oled.device import ssd1351
from luma.lcd.device import st7789

from PiFinder import ssd1333_device
from PiFinder.ssd1333_device import ssd1333

from PiFinder.ui.fonts import Fonts


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
    """1.91" 176x176 OLED.

    Brightness comes from three settings that multiply together. Two are
    registers fixing the current a lit pixel draws -- per-channel contrast
    (0xC1) and master current control (0xC7, scaling by (master + 1) / 16) --
    and the gray scale ceiling fixes how long it draws it for. Brightness is
    expressed internally in units of contrast-at-full-master-and-full-ceiling,
    so the registers span 0 to MAX_CONTRAST and the UI uses 0 to
    MAX_BRIGHTNESS of that.

    The two current registers alone are coarse at the dim end: their product is
    always a whole number, so current-only brightness quantises to n/16 and
    cannot go below MIN_DRIVE without the panel ceasing to emit. The gray scale
    ceiling is what reaches below that, and see ADR 0023 for why it dims by
    capping rendered pixel values rather than by rewriting the gray scale LUT.
    """

    # Highest per-channel contrast this panel drives cleanly; above it the
    # display shows unwanted artifacts, so the UI's 0-255 brightness scale is
    # remapped onto 0-MAX_CONTRAST rather than passed through.
    MAX_CONTRAST = 160

    # Measured: at master 0 the panel first emits at contrast 4, and nothing
    # below it lights at all however the two current registers are arranged.
    MIN_CONTRAST = 4

    # Dimmest drive current the panel will light at, in the same units as
    # MAX_CONTRAST. Below this the contrast register simply stops emitting.
    MIN_DRIVE = MIN_CONTRAST / 16

    # Drive current to aim for once the gray scale ceiling is doing the
    # dimming. Sitting above the floor rather than on it leaves the contrast
    # register room to interpolate between ceiling steps, which are coarse down
    # there -- worth about a third off the largest jump between adjacent
    # brightness settings, for a little tonal range at the very dim end.
    DIM_DRIVE = 2 * MIN_DRIVE

    # Brightest the UI will drive the panel, as a fraction of what the
    # registers can reach. Measured: the top of the range blooms, bright pixels
    # smearing into their neighbours, so full level is held to 70% of the
    # available current.
    MAX_BRIGHTNESS = 0.70 * MAX_CONTRAST

    # Dimmest visible output: the current floor, duty-cycled down to the
    # dimmest gray scale level that still emits.
    MIN_BRIGHTNESS = (
        MIN_CONTRAST
        / 16
        * (ssd1333_device.MIN_GRAY_SCALE_LEVEL - 1)
        / (ssd1333_device.GRAY_SCALE_LEVELS - 1)
    )

    # Brightness rises as this power of the UI level. The UI adjusts level by a
    # percentage rather than a fixed step, so a power law makes each keypress a
    # roughly constant change all the way along -- here about 23%, against the
    # 19% floor for covering a 13400:1 range in the ~45 presses the UI takes to
    # cross it. Anything shallower cannot reach MIN_BRIGHTNESS at level 1 and
    # strands the dim settings this display is usually run at; anything steeper
    # starts repeating brightnesses on adjacent levels.
    GAMMA = 2.5

    def __init__(self):
        # init display  (SPI hardware)
        serial = spi(device=0, port=0, bus_speed_hz=40000000)
        device_serial = ssd1333(serial, width=176, height=176, rotate=3, bgr=True)
        self.device = device_serial
        super().__init__()

    def _drive_for(self, target):
        """Register pair whose current drive lands closest to ``target``.

        Master brightness is kept as low as it will go so the contrast
        register stays high, which both keeps its DAC clear of the floor and
        leaves the drive steps as fine as possible.
        """
        master = max(0, min(15, math.ceil(target * 16 / self.MAX_CONTRAST) - 1))
        contrast = round(target * 16 / (master + 1))
        return max(self.MIN_CONTRAST, min(self.MAX_CONTRAST, contrast)), master

    def set_brightness(self, level):
        """
        Sets oled brightness 0-255 across all three brightness registers.

        The level maps onto a target brightness over MIN_BRIGHTNESS to
        MAX_BRIGHTNESS, which is then reached with drive current wherever
        drive current can reach it. Only near MIN_DRIVE, where the contrast
        register bottoms out, does the gray scale ceiling come down -- pulled
        no further than the target needs, since lowering it costs the UI tonal
        range. So every normal brightness renders at full tonal range, and the
        ceiling takes over for the dim settings below.
        """
        level = max(0, min(255, level))
        if level == 0:
            self.device.master_brightness(0)
            self.device.contrast(0)
            return

        span = self.MAX_BRIGHTNESS - self.MIN_BRIGHTNESS
        target = self.MIN_BRIGHTNESS + span * (level / 255) ** self.GAMMA

        # Highest ceiling whose duty cycle still leaves the drive around
        # DIM_DRIVE; full ceiling for anything at DIM_DRIVE or brighter.
        steps = ssd1333_device.GRAY_SCALE_LEVELS - 1
        gray = 1 + min(steps, math.floor(target * steps / self.DIM_DRIVE))
        gray = max(ssd1333_device.MIN_GRAY_SCALE_LEVEL, gray)

        duty = (gray - 1) / steps
        contrast, master = self._drive_for(target / duty)

        self.device.master_brightness(master)
        self.device.contrast(contrast)
        self.device.gray_scale_ceiling(gray)


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
