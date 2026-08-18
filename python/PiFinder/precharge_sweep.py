#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Interactive pre-charge voltage (0xBB) sweep harness for the SSD1333 panel.

Pre-charge voltage is the fourth brightness axis (see ADR 0023): the panel
dims as it drops and goes dark between 0x05 and 0x00. The 2026-07 sweep on
this harness found the response linear in the code and multiplicative with
the other axes, which is the model ``set_brightness`` now uses below
brightness setting 8. Like the other measured constants it is a panel
measurement and does not transfer: re-run this on any new panel revision or
supplier change, answering the same two questions:

1. Is it multiplicative? Step ``b`` down and watch the patch row: if every
   patch dims by the same ratio (the 64 patch stays ~25% of the 255 patch),
   pre-charge composes cleanly with the other axes. If dim patches die first,
   it has the same turn-on knee that makes low drive currents unusable.
2. Is it linear down the drive floor? Run ``floor`` (contrast 4, master 0,
   full ceiling -- the dimmest the current registers reach), then step ``b``
   down and note each level: still emitting? ramp still monotonic? artifacts,
   smearing or colour shift anywhere? Where does it go dark?

If either answer changes, the ``code / PRECHARGE_FULL`` dimming model in
``DisplaySSD1333.set_brightness`` no longer holds and the bottom seven
brightness settings will render wrong.

Usage (stop the PiFinder service first -- this owns the SPI display):

    cd python && source .venv/bin/activate
    python -m PiFinder.precharge_sweep

The test pattern is all red-channel, like the UI: a row of labelled patches
(255 down to 32), a mock title bar (value-64 bar, value-0 text), a 31-step
native gradient ramp, and a 1px checkerboard beside a solid block for
spotting smear. Commands:

    b <0-31>   set pre-charge voltage code (init value is 0x17 = 23)
    - / +      step pre-charge down / up by one
    c <0-255>  set contrast (all three channels)
    m <0-15>   set master brightness
    g <2-31>   set gray scale ceiling
    ui <0-255> apply the shipped set_brightness policy for that setting
    floor      preset: contrast 4, master 0, ceiling 31 (drive floor)
    q          quit (restores pre-charge 0x17 and clears the screen)
"""

import sys

from PIL import Image, ImageDraw, ImageFont

from PiFinder import ssd1333_device
from PiFinder.displays import DisplaySSD1333

#: Pre-charge voltage code the init sequence programs (0.40 x VCC). Every
#: other measured constant in the brightness policy assumes this value.
DEFAULT_PRECHARGE = 0x17

PATCH_VALUES = [255, 192, 128, 96, 64, 32]


def build_pattern(resolution):
    """Red-channel test pattern sized to the panel."""
    width, height = resolution
    image = Image.new("RGB", resolution)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()

    # Row of solid patches, brightest to dimmest, value printed below each
    # in full intensity so the labels outlive the patches as things dim.
    patch_w = width // len(PATCH_VALUES)
    for i, value in enumerate(PATCH_VALUES):
        left = i * patch_w
        draw.rectangle([left, 0, left + patch_w - 2, 40], fill=(value, 0, 0))
        draw.text((left + 2, 42), str(value), font=font, fill=(255, 0, 0))

    # Mock title bar: the UI surface this work is calibrated against.
    draw.rectangle([0, 58, width, 78], fill=(64, 0, 0))
    draw.text((6, 63), "TITLE BAR 64", font=font, fill=(0, 0, 0))

    # Native gradient ramp, one bar per gray level, for monotonicity checks.
    bar_w = width / 31
    for level in range(1, 32):
        left = round((level - 1) * bar_w)
        draw.rectangle(
            [left, 90, round(level * bar_w) - 1, 130], fill=(level * 8, 0, 0)
        )

    # 1px checkerboard beside a solid block: equal average load, so smear or
    # pre-charge crosstalk shows as the two halves diverging.
    half = width // 2
    for y in range(height - 30, height):
        for x in range(0, half, 2):
            image.putpixel((x + (y % 2), y), (255, 0, 0))
    draw.rectangle([half + 4, height - 30, width - 1, height - 1], fill=(255, 0, 0))
    return image


class _RegisterProbe:
    """Records what set_brightness would program, without hardware."""

    def __init__(self):
        self.master = None
        self.contrast_level = None
        self.gray = None
        self.precharge = None

    def master_brightness(self, level):
        self.master = level

    def contrast(self, level):
        self.contrast_level = level

    def gray_scale_ceiling(self, level):
        self.gray = level

    def precharge_voltage(self, level):
        self.precharge = level


def brightness_registers(setting):
    """The (contrast, master, ceiling, pre-charge) the shipped policy picks."""
    probe = DisplaySSD1333.__new__(DisplaySSD1333)
    probe.device = _RegisterProbe()
    probe.set_brightness(setting)
    device = probe.device
    return device.contrast_level, device.master, device.gray, device.precharge


class SweepState:
    def __init__(self, display):
        self.display = display
        self.pattern = build_pattern(display.resolution)
        self.precharge = DEFAULT_PRECHARGE
        self.contrast = None
        self.master = None
        self.ceiling = ssd1333_device.GRAY_SCALE_LEVELS
        self.apply_ui(125)

    def apply_ui(self, setting):
        """Set registers the way the shipped brightness policy would."""
        contrast, master, ceiling, precharge = brightness_registers(setting)
        self.set_master(master)
        self.set_contrast(contrast)
        # set_brightness(0) turns the panel off; ceiling/pre-charge untouched.
        if precharge is not None:
            self.set_precharge(precharge)
        if ceiling is not None:
            self.set_ceiling(ceiling)

    def set_precharge(self, level):
        self.display.device.precharge_voltage(level)
        self.precharge = level

    def set_contrast(self, level):
        self.display.device.contrast(level)
        self.contrast = level

    def set_master(self, level):
        self.display.device.master_brightness(level)
        self.master = level

    def set_ceiling(self, level):
        self.display.device.gray_scale_ceiling(level)
        self.ceiling = level
        self.redraw()

    def redraw(self):
        self.display.device.display(self.pattern.convert(self.display.device.mode))

    def status(self):
        return (
            f"pre-charge=0x{self.precharge:02X} ({self.precharge})  "
            f"contrast={self.contrast}  master={self.master}  "
            f"ceiling={self.ceiling}"
        )


def main():
    print("Initialising SSD1333 (stop the PiFinder service first)...")
    display = DisplaySSD1333()
    state = SweepState(display)
    print("Commands: b <n>, -, +, c <n>, m <n>, g <n>, ui <n>, floor, q")
    print(state.status())

    while True:
        try:
            line = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            line = "q"

        try:
            if line == "q":
                break
            elif line == "-":
                state.set_precharge(max(0, state.precharge - 1))
            elif line == "+":
                state.set_precharge(min(31, state.precharge + 1))
            elif line == "floor":
                state.set_contrast(DisplaySSD1333.MIN_CONTRAST)
                state.set_master(0)
                state.set_ceiling(ssd1333_device.GRAY_SCALE_LEVELS)
            elif line.startswith("b "):
                state.set_precharge(int(line[2:], 0))
            elif line.startswith("c "):
                state.set_contrast(int(line[2:], 0))
            elif line.startswith("m "):
                state.set_master(int(line[2:], 0))
            elif line.startswith("g "):
                state.set_ceiling(int(line[2:], 0))
            elif line.startswith("ui "):
                state.apply_ui(int(line[3:], 0))
            elif line:
                print("unknown command")
                continue
        except (ValueError, AssertionError) as error:
            print(f"rejected: {error or 'value out of range'}")
            continue

        print(state.status())

    # Leave the panel the way the app expects to find it.
    state.set_precharge(DEFAULT_PRECHARGE)
    display.set_brightness(125)
    display.device.display(Image.new("RGB", display.resolution))
    print("restored pre-charge 0x17, screen cleared")
    return 0


if __name__ == "__main__":
    sys.exit(main())
