import functools
import logging
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

    Brightness comes from three measured dimming axes (ADR 0023, revised
    2026-08 from rig photometry). The two current registers -- per-channel
    contrast (0xC1) and master current control (0xC7) -- are photometrically
    one axis, the drive product contrast * (master + 1): panel flux depends
    on the pair only through that product. The gray scale ceiling fixes how
    long a lit pixel draws its current (see ADR 0023 for why it dims by
    capping rendered pixel values rather than rewriting the gray scale LUT),
    and the pre-charge voltage (0xBB) scales the light of weakly driven
    pixels.

    The axes do not multiply: pre-charge spans 32x at the drive floor and
    1.3x at reference drive, and the ceiling's duty law bends with drive
    (docs/ax/display/ssd1333-response.md). So the policy does not model a
    separable response -- it walks three measured response tables, one per
    regime, stacked bottom to top:

    - Levels 1..KNEE_LEVEL, the pre-charge regime: ceiling at its tonal
      floor, drive at its cut-out, and the pre-charge code walks
      PRECHARGE_FLOOR..PRECHARGE_FULL one code per level. These are the
      panel's ~20 dimmest states that keep the UI's dimmest shade emitting;
      steps at the very bottom are coarse (6x, 2.5x) -- the panel's floor,
      not the curve's.
    - Levels KNEE_LEVEL+1..CEILING_TOP_LEVEL, the ceiling regime: drive
      stays at the cut-out, pre-charge full, and the ceiling walks up to
      full one step per level along its measured (concave) duty response.
    - Above, the drive regime: full ceiling and pre-charge, full tonal
      range; the level maps to a target flux by a power law and the
      measured drive response is inverted to pick the drive product.

    Flux units throughout are panel flux (ADU/s) on the photometer rig's
    scale, from the 2026-08-02 stage-3 calibration session
    (docs/ax/display/measurements/ssd1333/stage3-calibration-20260802.jsonl).
    Only ratios matter to the policy; the absolute scale is the rig's.
    """

    # Highest per-channel contrast this panel drives cleanly; above it the
    # display shows unwanted artifacts (eyeball-judged; the rig cannot see
    # spatial artifacts).
    MAX_CONTRAST = 160

    # Measured: the panel is lit iff the drive product is at least 4 --
    # confirmed at both full and floor ceilings, and every register pair
    # reaching the same product emits identically. Nothing exists between
    # dark and this cut-out on the drive axis.
    MIN_CONTRAST = 4
    MIN_DRIVE_PRODUCT = 4

    # Lowest ceiling that keeps the UI's dimmest large surface -- the title
    # bar background, pixel value 64, native gray level 8 -- rounding onto
    # an emitting level. The tonal-range rule: value 64 stays
    # photometrically distinct from value 255 at every lit setting
    # (measured ratios 0.10-0.37 across the range), so the policy never
    # programs a lower ceiling.
    MIN_TONAL_CEILING = 4

    # Pre-charge voltage code (0xBB) the init sequence programs and every
    # bright/mid constant is calibrated at; the policy never exceeds it.
    PRECHARGE_FULL = 0x17

    # Dimmest pre-charge code the policy programs. The pre-charge cut-out
    # at the dim-regime state ends at code 3 (measured; the cut-out edge
    # moves with drive), and code 4 is the panel's dimmest
    # tonal-rule-compliant state: 151 ADU/s, the policy's bottom.
    PRECHARGE_FLOOR = 4

    # Blooming cap, on the drive product: the top of the register range
    # blooms, bright pixels smearing into neighbours, so the policy never
    # drives more than 70% of the register maximum (eyeball-judged, stands
    # from the 2026-07 calibration). Not binding under MAX_TARGET_FLUX.
    MAX_DRIVE_PRODUCT = round(0.70 * MAX_CONTRAST * 16)

    # The soft top: 75% of the panel's clean maximum flux (1.39e6 ADU/s at
    # drive product 2560, measured this session). The full drive range buys
    # only 6.9x of light, so the last 25% of flux costs disproportionate
    # current -- and the top of the range is where blooming lives.
    CLEAN_MAX_FLUX = 1.39e6
    MAX_TARGET_FLUX = 0.75 * CLEAN_MAX_FLUX

    # --- Measured response tables (stage-3 calibration, 2026-08-02) ---------
    # Panel flux (ADU/s) of the pre-charge regime states: codes
    # PRECHARGE_FLOOR..PRECHARGE_FULL at contrast 4, master 0, ceiling 4.
    # Concave: the bottom steps are 6.3x and 2.5x, the top ones ~7%.
    _PRECHARGE_RESPONSE = (
        151,
        945,
        2343,
        4155,
        6228,
        8538,
        11020,
        13600,
        16340,
        19150,
        21980,
        24940,
        27910,
        30780,
        34470,
        37620,
        40780,
        43970,
        47130,
        50280,
    )

    # Panel flux of the ceiling regime states: ceilings
    # MIN_TONAL_CEILING+1..GRAY_SCALE_LEVELS at the drive cut-out,
    # pre-charge full. Concave against the nominal (n-1)/30 duty law --
    # at this weak drive the low levels emit about twice their duty share.
    _CEILING_RESPONSE = (
        64340,
        76970,
        85610,
        93760,
        101400,
        108700,
        115500,
        122000,
        128200,
        134000,
        139600,
        144900,
        150000,
        154700,
        159400,
        163900,
        168100,
        172100,
        176100,
        180000,
        183600,
        187100,
        190600,
        193900,
        197000,
        200100,
        203100,
    )

    # Panel flux vs drive product at full ceiling and pre-charge: (product,
    # flux) anchors for log-log interpolation. Flat from the cut-out to
    # ~32 (the drive floor emits 28.5% of reference), ~sqrt(product) above
    # ~128. Product 6 measured identical to 4 and is omitted.
    _DRIVE_RESPONSE = (
        (4, 203100),
        (8, 208300),
        (12, 213500),
        (16, 218400),
        (24, 228900),
        (32, 239200),
        (48, 264100),
        (64, 290400),
        (96, 324700),
        (128, 357900),
        (160, 398500),
        (192, 435500),
        (256, 496100),
        (320, 554200),
        (384, 619600),
        (448, 670000),
        (512, 715700),
        (640, 789100),
        (768, 907300),
        (896, 972200),
        (1024, 1037000),
        (1152, 1104000),
        (1280, 1157000),
    )

    # --- The level -> light curve -------------------------------------------
    # Dim-weighted knee shape (2026-07 field request, constants re-derived
    # 2026-08 from the measured surface). Settings 1..KNEE_LEVEL walk the
    # pre-charge regime -- 2.5 of the range's 3.8 decades, every level a
    # distinct panel state. The ceiling regime walks the next 27 states one
    # per level, and the knee curve's bright half is a power law in the
    # level: the UI steps the level by a percentage of itself per keypress,
    # so a power law gives a near-constant ~10-20% flux step per press from
    # the knee to the top.
    KNEE_LEVEL = 20
    CEILING_TOP_LEVEL = (
        KNEE_LEVEL + ssd1333_device.GRAY_SCALE_LEVELS - MIN_TONAL_CEILING
    )

    # Flux at the top of the ceiling regime (drive cut-out at full ceiling),
    # where the drive regime's power law anchors.
    _CEILING_TOP_FLUX = _CEILING_RESPONSE[-1]
    _BRIGHT_SLOPE = math.log(MAX_TARGET_FLUX / _CEILING_TOP_FLUX) / math.log(
        255 / CEILING_TOP_LEVEL
    )

    def __init__(self):
        # init display  (SPI hardware)
        serial = spi(device=0, port=0, bus_speed_hz=40000000)
        device_serial = ssd1333(serial, width=176, height=176, rotate=3, bgr=True)
        self.device = device_serial
        super().__init__()

    def _drive_product_for(self, target):
        """Drive product whose measured flux is ``target``, by log-log
        interpolation between the _DRIVE_RESPONSE anchors, capped at the
        blooming limit."""
        table = self._DRIVE_RESPONSE
        if target <= table[0][1]:
            return float(table[0][0])
        if target >= table[-1][1]:
            return float(min(table[-1][0], self.MAX_DRIVE_PRODUCT))
        for (product_lo, flux_lo), (product_hi, flux_hi) in zip(table, table[1:]):
            if target <= flux_hi:
                fraction = math.log(target / flux_lo) / math.log(flux_hi / flux_lo)
                product = product_lo * (product_hi / product_lo) ** fraction
                return min(product, float(self.MAX_DRIVE_PRODUCT))
        return float(self.MAX_DRIVE_PRODUCT)

    def set_brightness(self, level):
        """
        Sets oled brightness 0-255 across the panel's measured dimming axes.

        The level indexes the regime stack described on the class: the
        pre-charge regime (one measured pre-charge code per level), the
        ceiling regime (one ceiling step per level), then the drive regime,
        where the level maps to a target flux by a power law anchored at the
        ceiling regime's top and rising to MAX_TARGET_FLUX at 255, and the
        measured drive response is inverted to pick the register pair.
        Master current stays as low as the product allows so the contrast
        register keeps the drive steps fine.
        """
        level = max(0, min(255, level))
        if level == 0:
            self.device.master_brightness(0)
            self.device.contrast(0)
            return

        contrast = self.MIN_CONTRAST
        master = 0
        ceiling = self.MIN_TONAL_CEILING
        precharge = self.PRECHARGE_FULL

        if level <= self.KNEE_LEVEL:
            precharge = self.PRECHARGE_FLOOR + level - 1
        elif level <= self.CEILING_TOP_LEVEL:
            ceiling = self.MIN_TONAL_CEILING + level - self.KNEE_LEVEL
        else:
            target = min(
                self.MAX_TARGET_FLUX,
                self._CEILING_TOP_FLUX
                * (level / self.CEILING_TOP_LEVEL) ** self._BRIGHT_SLOPE,
            )
            product = self._drive_product_for(target)
            master = max(0, math.ceil(product / self.MAX_CONTRAST) - 1)
            contrast = max(
                self.MIN_CONTRAST,
                min(self.MAX_CONTRAST, round(product / (master + 1))),
            )
            ceiling = ssd1333_device.GRAY_SCALE_LEVELS

        self.device.master_brightness(master)
        self.device.contrast(contrast)
        self.device.gray_scale_ceiling(ceiling)
        self.device.precharge_voltage(precharge)


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
