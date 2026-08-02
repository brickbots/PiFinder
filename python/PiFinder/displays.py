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

    Brightness comes from four settings that multiply together. Two are
    registers fixing the current a lit pixel draws -- per-channel contrast
    (0xC1) and master current control (0xC7, scaling by (master + 1) / 16) --
    the gray scale ceiling fixes how long it draws it for, and the pre-charge
    voltage (0xBB) scales the light a given current and duty produce.
    Brightness is expressed internally in units of
    contrast-at-full-master-and-full-ceiling, so the registers span 0 to
    MAX_CONTRAST and the UI uses 0 to MAX_BRIGHTNESS of that.

    The two current registers alone are coarse at the dim end: their product is
    always a whole number, so current-only brightness quantises to n/16 and
    cannot go below MIN_DRIVE without the panel ceasing to emit. The gray scale
    ceiling is what reaches below that, and see ADR 0023 for why it dims by
    capping rendered pixel values rather than by rewriting the gray scale LUT.
    The ceiling costs tonal range as it falls, so once it reaches
    MIN_TONAL_CEILING -- the last ceiling that keeps the UI's dimmest shade
    emitting -- the pre-charge voltage takes over the remaining dimming and
    the ceiling falls no further.
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

    # How far the registers may land from the target brightness (as a log
    # ratio) before set_brightness trades a gray scale ceiling step for a
    # better fit. Tighter costs tonal range for accuracy; looser lets
    # adjacent UI levels collide into the same output. 2% is the loosest
    # setting that keeps every UI level distinct and monotonic under the
    # knee curve, whose per-level steps run down to ~4% above the knee.
    DRIVE_FIT_TOL = math.log(1.02)

    # Most ceiling steps the fit search may trade away. Bounded because the
    # search would otherwise prefer very low ceilings outright -- the
    # contrast values they pair with are large and therefore finer-grained
    # -- surrendering the tonal range the high ceiling exists to protect.
    # With MIN_TONAL_CEILING clamping the floor, three steps is safe and
    # de-quantises the drive registers near ceiling boundaries.
    DRIVE_FIT_STEPS = 3

    # Lowest ceiling the fit search may trade down to while the target can
    # reach a higher one. Four is the lowest ceiling where the UI's dimmest
    # large surface -- the title bar background, pixel value 64, native gray
    # level 8 -- still rounds onto an emitting level. Holding it there spends
    # drive-current headroom on tone instead of fit: the affected settings
    # land up to ~11% off the brightness curve, half a keypress step.
    MIN_TONAL_CEILING = 4

    # Pre-charge voltage code (0xBB) at which every other measured constant
    # holds; the init sequence programs it and the policy never exceeds it.
    # Sweep-measured (PiFinder.precharge_sweep, 2026-07, by eye): light
    # scales linearly with the code and multiplicatively with the other
    # axes, reaching dark at code 0, so the dimming multiplier is modelled
    # as code / PRECHARGE_FULL.
    PRECHARGE_FULL = 0x17

    # Dimmest pre-charge code the policy will program: a safety margin above
    # the 0x00-0x05 region where the panel cuts out, and as low as
    # MIN_BRIGHTNESS ever needs (a 3x reduction below the drive floor at
    # MIN_TONAL_CEILING).
    PRECHARGE_FLOOR = 8

    # Brightest the UI will drive the panel, as a fraction of what the
    # registers can reach. Measured: the top of the range blooms, bright pixels
    # smearing into their neighbours, so full level is held to 70% of the
    # available current.
    MAX_BRIGHTNESS = 0.70 * MAX_CONTRAST

    # Dimmest output the policy targets: the current floor, duty-cycled down
    # to the dimmest gray scale level that still emits. Kept at this value
    # when pre-charge dimming was added, so the brightness curve is
    # unchanged; the floor is now reached as ceiling MIN_TONAL_CEILING at
    # the drive floor with a ~3x pre-charge reduction, which lands within a
    # register step of the same light.
    MIN_BRIGHTNESS = (
        MIN_CONTRAST
        / 16
        * (ssd1333_device.MIN_GRAY_SCALE_LEVEL - 1)
        / (ssd1333_device.GRAY_SCALE_LEVELS - 1)
    )

    # --- The level -> brightness curve --------------------------------------
    # Two regimes with a soft knee, reshaped (2026-07, field request) to
    # spend far more of the 0-255 range on the dim settings this display is
    # actually run at. The knee sits exactly where the pre-charge dimming
    # regime begins, so settings 1..KNEE_LEVEL walk the pre-charge range and
    # everything above climbs to MAX_BRIGHTNESS.
    KNEE_LEVEL = 20

    # Levels over which the two regimes blend (logistic width). About two
    # levels: enough that the per-press step doesn't jump abruptly crossing
    # the knee, narrow enough that neither regime's shape is disturbed.
    KNEE_BLEND = 2.0

    # Brightness at the knee: the top of the pre-charge regime, i.e. what
    # MIN_TONAL_CEILING produces at the drive floor.
    _KNEE_TARGET = (
        MIN_DRIVE * (MIN_TONAL_CEILING - 1) / (ssd1333_device.GRAY_SCALE_LEVELS - 1)
    )

    # Below the knee brightness rises by a constant ratio per level (~6%) --
    # matched to the pre-charge/contrast register grid, whose spacing runs
    # ~4-12% down there, so nearly every level is a distinct visible step.
    # Above the knee it rises by a constant ratio per *keypress*: the UI
    # steps the level by a percentage of itself, so that regime is a power
    # law in the level (~35% per press). Both rates follow from pinning the
    # curve at MIN_BRIGHTNESS, the knee, and MAX_BRIGHTNESS.
    _DIM_RATE = math.log(_KNEE_TARGET / MIN_BRIGHTNESS) / (KNEE_LEVEL - 1)
    _BRIGHT_SLOPE = math.log(MAX_BRIGHTNESS / _KNEE_TARGET) / math.log(255 / KNEE_LEVEL)

    def __init__(self):
        # init display  (SPI hardware)
        serial = spi(device=0, port=0, bus_speed_hz=40000000)
        device_serial = ssd1333(serial, width=176, height=176, rotate=3, bgr=True)
        self.device = device_serial
        super().__init__()

    def _target_for(self, level):
        """Brightness the curve aims at for a UI level (1-255).

        Log-domain blend of the two regimes: geometric-per-level below the
        knee, power-law-in-level above, crossing at exactly _KNEE_TARGET
        (both segments pass through the knee point, so the blend is exact
        there).
        """
        blend = 1 / (1 + math.exp(-(level - self.KNEE_LEVEL) / self.KNEE_BLEND))
        dim = self._DIM_RATE * (level - 1)
        bright = math.log(self._KNEE_TARGET / self.MIN_BRIGHTNESS) + (
            self._BRIGHT_SLOPE * math.log(level / self.KNEE_LEVEL)
        )
        return self.MIN_BRIGHTNESS * math.exp((1 - blend) * dim + blend * bright)

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
        Sets oled brightness 0-255 across all four brightness registers.

        The level maps onto a target brightness via the knee curve (see
        _target_for), which is then reached with drive current wherever
        drive current can reach it. Only near MIN_DRIVE, where the contrast
        register bottoms out, does the gray scale ceiling come down -- and no
        further than the target needs, since lowering it costs the UI tonal
        range. Starting from the highest ceiling whose duty cycle keeps the
        drive at or above its floor, the ceiling steps down only while the
        registers' quantised output misses the target by more than
        DRIVE_FIT_TOL, and never below MIN_TONAL_CEILING. Once that ceiling
        reaches the drive floor, the pre-charge voltage does the remaining
        dimming. So every normal brightness renders at full tonal range, and
        every dim setting keeps the UI's dimmest shade emitting.
        """
        level = max(0, min(255, level))
        if level == 0:
            self.device.master_brightness(0)
            self.device.contrast(0)
            return

        target = self._target_for(level)

        steps = ssd1333_device.GRAY_SCALE_LEVELS - 1
        gray_hi = 1 + min(steps, math.floor(target * steps / self.MIN_DRIVE))

        if gray_hi <= self.MIN_TONAL_CEILING:
            # Pre-charge regime: the ceiling is already at its tonal floor,
            # so hold it there and search the pre-charge codes for the rest
            # of the dimming, with the contrast register trimming each
            # candidate's residual. The full code range is searched because
            # the combined pre-charge x contrast grid is much denser than
            # either register alone -- that density is what keeps adjacent
            # dim settings visibly distinct.
            gray = self.MIN_TONAL_CEILING
            duty = (gray - 1) / steps
            best = None
            for precharge in range(self.PRECHARGE_FULL, self.PRECHARGE_FLOOR - 1, -1):
                dimming = precharge / self.PRECHARGE_FULL
                contrast, master = self._drive_for(target / (duty * dimming))
                actual = duty * dimming * contrast * (master + 1) / 16
                error = abs(math.log(actual / target))
                # Strict improvement, descending: near-ties keep the higher,
                # better-calibrated code.
                if best is None or error < best[0] - 1e-9:
                    best = (error, precharge, contrast, master)
            _, precharge, contrast, master = best
        else:
            precharge = self.PRECHARGE_FULL
            gray_lo = max(
                min(self.MIN_TONAL_CEILING, gray_hi),
                gray_hi - self.DRIVE_FIT_STEPS,
            )
            best = None
            for gray in range(gray_hi, gray_lo - 1, -1):
                duty = (gray - 1) / steps
                contrast, master = self._drive_for(target / duty)
                actual = duty * contrast * (master + 1) / 16
                error = abs(math.log(actual / target))
                # Strict improvement only: equal fits keep the higher ceiling.
                if best is None or error < best[0] - 1e-9:
                    best = (error, gray, contrast, master)
                if error <= self.DRIVE_FIT_TOL:
                    break
            _, gray, contrast, master = best

        self.device.master_brightness(master)
        self.device.contrast(contrast)
        self.device.gray_scale_ceiling(gray)
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
