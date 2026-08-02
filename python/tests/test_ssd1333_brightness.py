"""
Unit tests for SSD1333 brightness: the three-axis register policy in
``DisplaySSD1333.set_brightness`` and the gray scale ceiling LUT in
``ssd1333_device`` (see ADR 0023).

The panel itself can't be asserted on, but the register maths can: the tests
model emitted light as ``duty * contrast * (master + 1) / 16`` with duty
``(gray - 1) / 30`` -- the same model the driver uses, taken from the
datasheet's built-in linear LUT -- and check the invariants the dimming
design promises. No hardware: the display object is built with ``__new__``
and handed a recording stub device.
"""

import math

import pytest

from PiFinder import ssd1333_device
from PiFinder.displays import DisplaySSD1333

pytestmark = pytest.mark.unit

STEPS = ssd1333_device.GRAY_SCALE_LEVELS - 1

# The title bar background renders at pixel value 64 (ui/base.py
# screen_update), the dimmest large surface in the UI and the first thing to
# vanish if the ceiling LUT crushes dark shades.
TITLEBAR_VALUE = 64


class RecordingDevice:
    """Stub ssd1333 capturing the four brightness registers."""

    def __init__(self):
        self.master = None
        self.contrast_level = None
        self.gray = ssd1333_device.GRAY_SCALE_LEVELS
        self.precharge = DisplaySSD1333.PRECHARGE_FULL

    def master_brightness(self, level):
        self.master = level

    def contrast(self, level):
        self.contrast_level = level

    def gray_scale_ceiling(self, level):
        self.gray = level

    def precharge_voltage(self, level):
        self.precharge = level


def make_display():
    display = DisplaySSD1333.__new__(DisplaySSD1333)
    display.device = RecordingDevice()
    return display


def registers_for(level):
    display = make_display()
    display.set_brightness(level)
    return display.device


def emitted_light(device):
    """Relative light of a full-intensity pixel for a register state."""
    duty = (device.gray - 1) / STEPS
    dimming = device.precharge / DisplaySSD1333.PRECHARGE_FULL
    return duty * dimming * device.contrast_level * (device.master + 1) / 16


def lut_gray_level(value, ceiling):
    """Gray level a pixel value lands on under a gray scale ceiling."""
    device = ssd1333_device.ssd1333.__new__(ssd1333_device.ssd1333)
    device.gray_scale_ceiling(ceiling)
    if device._gray_scale_lut is None:
        return value // 8
    return device._gray_scale_lut[value] // 8


# --------------------------------------------------------------------------- #
# set_brightness register policy
# --------------------------------------------------------------------------- #


def test_level_zero_turns_display_off():
    device = registers_for(0)
    assert device.master == 0
    assert device.contrast_level == 0


def test_brightness_is_monotonic_with_no_dead_steps():
    # Every UI level must be dimmer than the next. In the bottom octave the
    # register grid is coarser (~11%) than the curve's 6% per level, so a
    # few adjacent levels there are allowed to collide; above level 6 a
    # repeat is a dead keypress.
    outputs = [emitted_light(registers_for(level)) for level in range(1, 256)]
    for i, (a, b) in enumerate(zip(outputs, outputs[1:]), start=1):
        assert b >= a, f"brightness decreases from level {i} to {i + 1}"
        if i > 6:
            assert b > a, f"levels {i} and {i + 1} produce identical output"


def test_curve_hits_its_anchors():
    # The knee curve is pinned at three points: MIN_BRIGHTNESS at level 1,
    # the top of the pre-charge regime at KNEE_LEVEL (both segments pass
    # through it, so the blend is exact there), and MAX_BRIGHTNESS at 255.
    display = make_display()
    assert display._target_for(1) == pytest.approx(
        DisplaySSD1333.MIN_BRIGHTNESS, rel=0.005
    )
    assert display._target_for(DisplaySSD1333.KNEE_LEVEL) == pytest.approx(
        DisplaySSD1333._KNEE_TARGET, rel=1e-6
    )
    assert display._target_for(255) == pytest.approx(
        DisplaySSD1333.MAX_BRIGHTNESS, rel=0.005
    )


def test_registers_land_on_target():
    # The quantised registers must track the brightness curve within 6% --
    # under half the smallest per-press step -- at every level.
    display = make_display()
    for level in range(1, 256):
        target = display._target_for(level)
        actual = emitted_light(registers_for(level))
        assert abs(math.log(actual / target)) <= math.log(1.06), f"level {level}"


def test_ceiling_holds_tonal_floor():
    # The ceiling never drops below MIN_TONAL_CEILING at any lit setting --
    # that ceiling is what keeps the title bar's shade emitting. Below what
    # it can reach at the drive floor, pre-charge dimming takes over instead.
    for level in range(1, 256):
        assert registers_for(level).gray >= DisplaySSD1333.MIN_TONAL_CEILING


def test_precharge_only_dims_the_bottom_settings():
    # Pre-charge stays at the init value (where all other panel constants
    # were measured) everywhere the ceiling can do the job, and only comes
    # down inside the pre-charge regime below the knee -- never under
    # PRECHARGE_FLOOR, the safety margin above the 0x00-0x05 region where
    # the panel cuts out.
    for level in range(1, 256):
        precharge = registers_for(level).precharge
        if level >= 23:
            assert precharge == DisplaySSD1333.PRECHARGE_FULL
        else:
            assert (
                DisplaySSD1333.PRECHARGE_FLOOR
                <= precharge
                <= DisplaySSD1333.PRECHARGE_FULL
            )


def test_ceiling_stays_full_at_normal_brightness():
    # Tonal range is only sacrificed once drive current alone cannot reach
    # the target: at level 39 and above the ceiling must not drop more than
    # the few steps the fit search is allowed to trade away.
    for level in range(39, 256):
        assert registers_for(level).gray >= 28


def test_drive_never_below_panel_floor():
    for level in range(1, 256):
        device = registers_for(level)
        assert device.contrast_level >= DisplaySSD1333.MIN_CONTRAST


# --------------------------------------------------------------------------- #
# Gray scale ceiling LUT (contrast preservation while dimmed)
# --------------------------------------------------------------------------- #


def test_full_ceiling_is_passthrough():
    device = ssd1333_device.ssd1333.__new__(ssd1333_device.ssd1333)
    device.gray_scale_ceiling(ssd1333_device.GRAY_SCALE_LEVELS)
    assert device._gray_scale_lut is None


def test_lut_preserves_relative_light():
    # Under any ceiling, a pixel's light relative to full white must stay
    # within half a gray level step of what the panel shows at full ceiling.
    # (This is the fix for the title bar dimming faster than bright text.)
    for ceiling in range(4, ssd1333_device.GRAY_SCALE_LEVELS):
        for value in range(0, 256, 8):
            native_light = max(0, value // 8 - 1) / STEPS
            mapped = lut_gray_level(value, ceiling)
            mapped_light = max(0, mapped - 1) / (ceiling - 1)
            half_step = 0.5 / (ceiling - 1)
            assert abs(mapped_light - native_light) <= half_step + 1e-9, (
                f"value {value} under ceiling {ceiling}: "
                f"{mapped_light:.3f} vs native {native_light:.3f}"
            )


def test_lut_keeps_black_black():
    for ceiling in range(2, ssd1333_device.GRAY_SCALE_LEVELS):
        assert lut_gray_level(0, ceiling) <= 1


def test_titlebar_survives_at_every_setting():
    # Regression for the title bar (pixel value 64) going black between UI
    # levels 16 and 15 while bright text stayed visible: with pre-charge
    # dimming holding the ceiling at MIN_TONAL_CEILING, it must render on an
    # emitting gray level (>= 2) at every lit brightness setting.
    for level in range(1, 256):
        device = registers_for(level)
        assert (
            lut_gray_level(TITLEBAR_VALUE, device.gray) >= 2
        ), f"title bar dark at UI brightness {level} (ceiling {device.gray})"
