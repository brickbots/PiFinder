"""Unit tests for the equipment field rules (#569).

The equipment forms built their records with bare ``float()``/``int()``
inside a ``try/except`` that logged the failure and rendered the success
banner anyway, so a comma decimal, a blank name or an out-of-range value
reported "Eyepiece added" and saved nothing.  These tests pin the rules
the API enforces now; ``test_server_equipment_forms.py`` drives the same
rules through the routes.
"""

import pytest

from PiFinder.equipment import (
    EYEPIECE_LIMITS,
    TELESCOPE_LIMITS,
    format_measurement,
)
from PiFinder.server import (
    eyepiece_from_form,
    parse_measurement,
    parse_name,
    telescope_from_form,
)


def eyepiece_form(**overrides):
    form = {
        "make": "TeleVue",
        "name": "Ethos",
        "focal_length_mm": "13",
        "afov": "100",
        "field_stop": "0",
    }
    form.update(overrides)
    return form


def instrument_form(**overrides):
    form = {
        "make": "Celestron",
        "name": "C11",
        "aperture": "279.4",
        "focal_length_mm": "2800",
        "obstruction_perc": "34",
        "mount_type": "alt/az",
    }
    form.update(overrides)
    return form


# ── parse_measurement ──────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize("raw, expected", [("7.5", 7.5), ("7,5", 7.5), (" 7 ", 7.0)])
def test_parse_measurement_accepts_both_separators(raw, expected):
    assert parse_measurement(raw, "Focal length", (0.1, 100)) == expected


@pytest.mark.unit
@pytest.mark.parametrize("raw", ["0.05", "101"])
def test_parse_measurement_rejects_out_of_range(raw):
    with pytest.raises(ValueError, match="between"):
        parse_measurement(raw, "Focal length", (0.1, 100))


@pytest.mark.unit
def test_parse_measurement_accepts_the_bounds_themselves():
    assert parse_measurement("0.1", "Focal length", (0.1, 100)) == 0.1
    assert parse_measurement("100", "Focal length", (0.1, 100)) == 100


@pytest.mark.unit
def test_parse_measurement_blank_uses_default_when_given():
    assert parse_measurement("", "Field stop", (0, 100), default=0.0) == 0.0


@pytest.mark.unit
def test_parse_measurement_blank_without_default_is_an_error():
    """A field the user left empty must not silently become zero."""
    with pytest.raises(ValueError):
        parse_measurement("", "Focal length", (0.1, 100))


# ── parse_name ─────────────────────────────────────────────────────


@pytest.mark.unit
def test_parse_name_strips_surrounding_space():
    assert parse_name("  Ethos  ", "Name") == "Ethos"


@pytest.mark.unit
def test_parse_name_required_rejects_blank():
    with pytest.raises(ValueError, match="required"):
        parse_name("   ", "Name")


@pytest.mark.unit
def test_parse_name_optional_allows_blank():
    assert parse_name("", "Make", required=False) == ""


@pytest.mark.unit
def test_parse_name_rejects_overlong_value():
    with pytest.raises(ValueError, match="characters"):
        parse_name("E" * 65, "Name")


# ── eyepiece_from_form ─────────────────────────────────────────────


@pytest.mark.unit
def test_eyepiece_accepts_comma_decimal():
    eyepiece = eyepiece_from_form(
        eyepiece_form(focal_length_mm="7,5", field_stop="8,0")
    )
    assert eyepiece.focal_length_mm == 7.5
    assert eyepiece.field_stop == 8.0


@pytest.mark.unit
def test_eyepiece_blank_field_stop_means_unknown():
    assert eyepiece_from_form(eyepiece_form(field_stop="")).field_stop == 0.0


@pytest.mark.unit
def test_eyepiece_requires_a_name():
    with pytest.raises(ValueError, match="required"):
        eyepiece_from_form(eyepiece_form(name=" "))


@pytest.mark.unit
def test_eyepiece_make_is_optional():
    assert eyepiece_from_form(eyepiece_form(make="")).make == ""


@pytest.mark.unit
def test_eyepiece_rejects_zero_focal_length():
    """calc_magnification divides by it — zero used to be storable."""
    with pytest.raises(ValueError):
        eyepiece_from_form(eyepiece_form(focal_length_mm="0"))


@pytest.mark.unit
@pytest.mark.parametrize("afov", ["0", "360", "wide"])
def test_eyepiece_rejects_impossible_afov(afov):
    with pytest.raises(ValueError):
        eyepiece_from_form(eyepiece_form(afov=afov))


@pytest.mark.unit
def test_eyepiece_keeps_a_fractional_afov():
    assert eyepiece_from_form(eyepiece_form(afov="68.5")).afov == 68.5


# ── telescope_from_form ────────────────────────────────────────────


@pytest.mark.unit
def test_instrument_accepts_fractional_aperture():
    """An 11" SCT is 279.4mm; int(aperture) made that unenterable (#291)."""
    assert telescope_from_form(instrument_form()).aperture_mm == 279.4


@pytest.mark.unit
def test_instrument_accepts_comma_decimal():
    instrument = telescope_from_form(
        instrument_form(aperture="279,4", focal_length_mm="1280,2")
    )
    assert instrument.aperture_mm == 279.4
    assert instrument.focal_length_mm == 1280.2


@pytest.mark.unit
def test_instrument_requires_a_name():
    with pytest.raises(ValueError, match="required"):
        telescope_from_form(instrument_form(name=""))


@pytest.mark.unit
@pytest.mark.parametrize("obstruction", ["-1", "101"])
def test_instrument_rejects_impossible_obstruction(obstruction):
    with pytest.raises(ValueError):
        telescope_from_form(instrument_form(obstruction_perc=obstruction))


@pytest.mark.unit
def test_instrument_blank_obstruction_means_none():
    assert (
        telescope_from_form(instrument_form(obstruction_perc="")).obstruction_perc == 0
    )


@pytest.mark.unit
def test_instrument_rejects_unknown_mount_type():
    with pytest.raises(ValueError, match="mount type"):
        telescope_from_form(instrument_form(mount_type="dobsonian"))


@pytest.mark.unit
def test_instrument_flags_come_from_the_checkboxes():
    instrument = telescope_from_form(instrument_form(flip="on", reverse_arrow_b="on"))
    assert (instrument.flip_image, instrument.flop_image) == (True, False)
    assert (instrument.reverse_arrow_a, instrument.reverse_arrow_b) == (False, True)


# ── limits and display ─────────────────────────────────────────────


@pytest.mark.unit
def test_limits_are_ordered():
    for limits in (TELESCOPE_LIMITS, EYEPIECE_LIMITS):
        for field, limit in limits.items():
            assert limit.minimum < limit.maximum, field


@pytest.mark.unit
@pytest.mark.parametrize(
    "value, expected",
    [(1000.0, "1000"), (7.5, "7.5"), (0, "0"), ("", ""), ("51,3", "51,3")],
)
def test_format_measurement(value, expected):
    assert format_measurement(value) == expected
