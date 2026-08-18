"""
Unit tests for SSD1333 brightness: the measured-table register policy in
``DisplaySSD1333.set_brightness`` and the gray scale ceiling LUT in
``ssd1333_device`` (see ADR 0023, revised 2026-08).

The panel itself can't be asserted on, but the register maths can: emitted
light is modelled with the same measured response tables the policy inverts
(panel flux in ADU/s from the stage-3 calibration session), and the tests
check the invariants the dimming design promises -- regime structure, the
tonal-range canary, monotonicity per level, and no dead keypresses under the
UI's actual +20%/-10% stepping. No hardware: the display object is built
with ``__new__`` and handed a recording stub device.
"""

import math

import pytest

from PiFinder import ssd1333_device
from PiFinder.displays import DisplaySSD1333

pytestmark = pytest.mark.unit

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


def modelled_flux(device):
    """Panel flux (ADU/s) of a register state, from the measured tables.

    Every state the policy programs lies on one of the three measured
    response slices, so the model needs no separability assumption -- the
    very thing the measured surface ruled out.
    """
    product = device.contrast_level * (device.master + 1)
    if device.gray == ssd1333_device.GRAY_SCALE_LEVELS:
        assert device.precharge == DisplaySSD1333.PRECHARGE_FULL
        table = DisplaySSD1333._DRIVE_RESPONSE
        if product <= table[0][0]:
            return float(table[0][1])
        for (p_lo, f_lo), (p_hi, f_hi) in zip(table, table[1:]):
            if product <= p_hi:
                fraction = math.log(product / p_lo) / math.log(p_hi / p_lo)
                return f_lo * (f_hi / f_lo) ** fraction
        raise AssertionError(f"drive product {product} above measured range")
    if device.gray > DisplaySSD1333.MIN_TONAL_CEILING:
        assert product == DisplaySSD1333.MIN_DRIVE_PRODUCT
        assert device.precharge == DisplaySSD1333.PRECHARGE_FULL
        return DisplaySSD1333._CEILING_RESPONSE[
            device.gray - DisplaySSD1333.MIN_TONAL_CEILING - 1
        ]
    assert device.gray == DisplaySSD1333.MIN_TONAL_CEILING
    assert product == DisplaySSD1333.MIN_DRIVE_PRODUCT
    return DisplaySSD1333._PRECHARGE_RESPONSE[
        device.precharge - DisplaySSD1333.PRECHARGE_FLOOR
    ]


def flux_for(level):
    return modelled_flux(registers_for(level))


def press_up(level):
    """The UI's brightness-up keypress (main.py ALT_PLUS handling)."""
    return min(255, level + max(2, int(level * 0.2)))


def press_down(level):
    """The UI's brightness-down keypress (main.py ALT_MINUS handling)."""
    return max(0, level - max(1, int(level * 0.1)))


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


def test_precharge_regime_walks_the_measured_ladder():
    # Levels 1..KNEE_LEVEL are the panel's dimmest tonal-rule-compliant
    # states: ceiling at its tonal floor, drive at its cut-out, one
    # pre-charge code per level from the measured floor code up to the
    # calibrated init value. Every dim level is a distinct panel state.
    for level in range(1, DisplaySSD1333.KNEE_LEVEL + 1):
        device = registers_for(level)
        assert device.contrast_level == DisplaySSD1333.MIN_CONTRAST
        assert device.master == 0
        assert device.gray == DisplaySSD1333.MIN_TONAL_CEILING
        assert device.precharge == DisplaySSD1333.PRECHARGE_FLOOR + level - 1
    assert registers_for(DisplaySSD1333.KNEE_LEVEL).precharge == (
        DisplaySSD1333.PRECHARGE_FULL
    )


def test_ceiling_regime_walks_one_step_per_level():
    # Levels KNEE_LEVEL+1..CEILING_TOP_LEVEL hold the drive at its cut-out
    # and raise the ceiling one step per level to full, restoring tonal
    # range as the panel brightens.
    for level in range(
        DisplaySSD1333.KNEE_LEVEL + 1, DisplaySSD1333.CEILING_TOP_LEVEL + 1
    ):
        device = registers_for(level)
        assert device.contrast_level == DisplaySSD1333.MIN_CONTRAST
        assert device.master == 0
        assert device.precharge == DisplaySSD1333.PRECHARGE_FULL
        assert device.gray == (
            DisplaySSD1333.MIN_TONAL_CEILING + level - DisplaySSD1333.KNEE_LEVEL
        )
    assert registers_for(DisplaySSD1333.CEILING_TOP_LEVEL).gray == (
        ssd1333_device.GRAY_SCALE_LEVELS
    )


def test_drive_regime_keeps_full_tonal_range():
    # Above the ceiling regime every setting renders at the full ceiling
    # and calibrated pre-charge: brightness comes from drive current alone,
    # so no tonal range is ever sacrificed at normal brightness.
    for level in range(DisplaySSD1333.CEILING_TOP_LEVEL + 1, 256):
        device = registers_for(level)
        assert device.gray == ssd1333_device.GRAY_SCALE_LEVELS
        assert device.precharge == DisplaySSD1333.PRECHARGE_FULL
        assert DisplaySSD1333.MIN_CONTRAST <= device.contrast_level
        assert device.contrast_level <= DisplaySSD1333.MAX_CONTRAST
        assert 0 <= device.master <= 15


def test_flux_is_monotonic_per_level():
    # Every UI level must be at least as bright as the one below it.
    # Adjacent levels may collide where the register grid is coarser than
    # the curve (the drive response is flat near its cut-out); dead
    # *keypresses* are ruled out separately below.
    outputs = [flux_for(level) for level in range(1, 256)]
    for i, (a, b) in enumerate(zip(outputs, outputs[1:]), start=1):
        assert b >= a, f"brightness decreases from level {i} to {i + 1}"


def test_no_dead_keypresses():
    # What the user actually steps through: the UI moves the level by +20%
    # (min 2) or -10% (min 1) per press. Every press must visibly change
    # the light. Sole exemption: an up-press landing exactly on 255, where
    # the drive register grid (~7 product units at the top) is coarser than
    # the last fraction of a level step.
    for level in range(1, 255):
        up = press_up(level)
        if up == 255:
            assert flux_for(up) >= flux_for(level)
        else:
            assert flux_for(up) > flux_for(level), f"dead up-press at {level}"
    for level in range(2, 256):
        down = press_down(level)
        assert flux_for(down) < flux_for(level), f"dead down-press at {level}"


def test_bottom_is_the_measured_emission_floor():
    # Level 1 is the panel's dimmest tonal-rule-compliant state -- the
    # measured 151 ADU/s emission floor -- not a modelled value 40x above
    # it, which is what the old separable model shipped.
    assert flux_for(1) == DisplaySSD1333._PRECHARGE_RESPONSE[0]
    assert flux_for(1) < 200


def test_top_is_the_soft_maximum():
    # Level 255 lands on MAX_TARGET_FLUX (75% of the measured clean
    # maximum) within the drive register quantisation, and stays under the
    # blooming cap.
    device = registers_for(255)
    assert modelled_flux(device) == pytest.approx(
        DisplaySSD1333.MAX_TARGET_FLUX, rel=0.02
    )
    product = device.contrast_level * (device.master + 1)
    assert product <= DisplaySSD1333.MAX_DRIVE_PRODUCT


def test_curve_spans_the_measured_decades():
    # The whole point of the refit: ~3.8 decades within the tonal rule,
    # against the 233:1 the old policy delivered.
    span = flux_for(255) / flux_for(1)
    assert span > 6000


def test_drive_regime_is_continuous_at_its_anchor():
    # The drive regime's power law anchors at the ceiling regime's top: the
    # first drive-regime level must sit within a few percent of it, not
    # jump.
    top = DisplaySSD1333.CEILING_TOP_LEVEL
    assert flux_for(top + 1) == pytest.approx(flux_for(top), rel=0.05)


def test_ceiling_holds_tonal_floor():
    # The ceiling never drops below MIN_TONAL_CEILING at any lit setting --
    # that ceiling is what keeps the title bar's shade emitting.
    for level in range(1, 256):
        assert registers_for(level).gray >= DisplaySSD1333.MIN_TONAL_CEILING


def test_drive_never_below_panel_cutout():
    # Lit iff drive product >= 4, at every lit setting.
    for level in range(1, 256):
        device = registers_for(level)
        assert device.contrast_level >= DisplaySSD1333.MIN_CONTRAST
        assert (
            device.contrast_level * (device.master + 1)
            >= DisplaySSD1333.MIN_DRIVE_PRODUCT
        )


def test_precharge_only_dims_the_bottom_settings():
    # Pre-charge stays at the calibrated init value everywhere above the
    # knee -- it is nearly inert at strong drive anyway (1.3x authority) --
    # and walks the measured code range only inside the pre-charge regime,
    # never below the measured cut-out edge.
    for level in range(1, 256):
        precharge = registers_for(level).precharge
        if level > DisplaySSD1333.KNEE_LEVEL:
            assert precharge == DisplaySSD1333.PRECHARGE_FULL
        else:
            assert (
                DisplaySSD1333.PRECHARGE_FLOOR
                <= precharge
                <= DisplaySSD1333.PRECHARGE_FULL
            )


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
    steps = ssd1333_device.GRAY_SCALE_LEVELS - 1
    for ceiling in range(4, ssd1333_device.GRAY_SCALE_LEVELS):
        for value in range(0, 256, 8):
            native_light = max(0, value // 8 - 1) / steps
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
    # levels 16 and 15 while bright text stayed visible: with the ceiling
    # held at MIN_TONAL_CEILING through the whole pre-charge regime, it must
    # render on an emitting gray level (>= 2) at every lit setting.
    for level in range(1, 256):
        device = registers_for(level)
        assert (
            lut_gray_level(TITLEBAR_VALUE, device.gray) >= 2
        ), f"title bar dark at UI brightness {level} (ceiling {device.gray})"
