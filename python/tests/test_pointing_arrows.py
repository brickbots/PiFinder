"""
Unit tests for ui_utils.pointing_arrows: the shared push-to direction
resolver used by the object locate screen, object lists, and the polar
alignment screen.

The focus here is the contract the polar alignment screen relies on:
passing mount_type="Alt/Az" forces directional arrows regardless of the
user's configured mount, because a polar correction is always made with
the mount's ground-frame alt/az adjusters -- never the RA/Dec drive axes.
A regression in this branch would make EQ-mount users see +/- axis signs
instead of arrows during polar alignment.
"""

from types import SimpleNamespace

import pytest

from PiFinder.ui.ui_utils import pointing_arrows

pytestmark = pytest.mark.unit

# Sentinel arrow glyphs. pointing_arrows compares with `is`, so identity is
# preserved because each value is read straight off the same stub attribute.
LEFT, RIGHT, UP, DOWN = "<LEFT>", "<RIGHT>", "<UP>", "<DOWN>"


def make_ui(mount_type="Alt/Az", pushto_az_arrows="Default"):
    """Minimal stand-in carrying only what pointing_arrows touches: the four
    arrow glyphs and a config_object exposing get_option."""
    options = {"mount_type": mount_type, "pushto_az_arrows": pushto_az_arrows}

    def get_option(key, default=None):
        return options.get(key, default)

    return SimpleNamespace(
        _LEFT_ARROW=LEFT,
        _RIGHT_ARROW=RIGHT,
        _UP_ARROW=UP,
        _DOWN_ARROW=DOWN,
        config_object=SimpleNamespace(get_option=get_option),
    )


# ── The polar-alignment contract: forced Alt/Az ignores configured mount ──


def test_forced_altaz_gives_arrows_even_for_eq_config():
    """The exact polar regression: an EQ-mount user must still get directional
    arrows (not +/-) when the caller forces mount_type="Alt/Az"."""
    ui = make_ui(mount_type="EQ")
    az_arrow, az, alt_arrow, alt = pointing_arrows(ui, 1.5, 2.0, mount_type="Alt/Az")
    assert (az_arrow, alt_arrow) == (RIGHT, UP)
    # Values are made positive and otherwise unchanged.
    assert (az, alt) == (1.5, 2.0)


def test_forced_altaz_negative_values_point_left_and_down():
    ui = make_ui(mount_type="EQ")
    az_arrow, az, alt_arrow, alt = pointing_arrows(ui, -1.5, -2.0, mount_type="Alt/Az")
    assert (az_arrow, alt_arrow) == (LEFT, DOWN)
    assert (az, alt) == (1.5, 2.0)  # magnitudes, sign stripped


# ── The pushto_az_arrows "Reverse" preference rides the Alt/Az branch ──


def test_reverse_flips_az_arrow_only():
    """Reverse swaps the azimuth arrow but must leave altitude alone."""
    ui = make_ui(mount_type="EQ", pushto_az_arrows="Reverse")
    # +az would be RIGHT by default -> flips to LEFT; +alt stays UP.
    az_arrow, _, alt_arrow, _ = pointing_arrows(ui, 1.0, 1.0, mount_type="Alt/Az")
    assert (az_arrow, alt_arrow) == (LEFT, UP)

    # -az would be LEFT by default -> flips to RIGHT; -alt stays DOWN.
    az_arrow, _, alt_arrow, _ = pointing_arrows(ui, -1.0, -1.0, mount_type="Alt/Az")
    assert (az_arrow, alt_arrow) == (RIGHT, DOWN)


def test_reverse_default_does_not_flip():
    ui = make_ui(mount_type="Alt/Az", pushto_az_arrows="Default")
    az_arrow, _, _, _ = pointing_arrows(ui, 1.0, 1.0, mount_type="Alt/Az")
    assert az_arrow == RIGHT


# ── Contrast: the two branches stay distinct ──


def test_eq_mount_uses_plus_minus_signs():
    """Locks the EQ branch apart from Alt/Az so the forced-Alt/Az test above
    is meaningful: with an EQ frame the indicators are +/-, never arrows."""
    ui = make_ui(mount_type="Alt/Az")  # config is irrelevant; arg wins
    pos_az, _, pos_alt, _ = pointing_arrows(ui, 1.0, 1.0, mount_type="EQ")
    assert (pos_az, pos_alt) == ("+", "+")
    neg_az, _, neg_alt, _ = pointing_arrows(ui, -1.0, -1.0, mount_type="EQ")
    assert (neg_az, neg_alt) == ("-", "-")


def test_eq_mount_ignores_reverse_preference():
    """Reverse only applies to the Alt/Az branch; EQ signs are untouched."""
    ui = make_ui(mount_type="EQ", pushto_az_arrows="Reverse")
    az_arrow, _, _, _ = pointing_arrows(ui, 1.0, 1.0, mount_type="EQ")
    assert az_arrow == "+"


# ── mount_type=None falls back to configured mount (existing behavior) ──


def test_none_mount_type_reads_config():
    ui = make_ui(mount_type="Alt/Az")
    az_arrow, _, alt_arrow, _ = pointing_arrows(ui, 1.0, 1.0)
    assert (az_arrow, alt_arrow) == (RIGHT, UP)

    ui = make_ui(mount_type="EQ")
    az_arrow, _, alt_arrow, _ = pointing_arrows(ui, 1.0, 1.0)
    assert (az_arrow, alt_arrow) == ("+", "+")
