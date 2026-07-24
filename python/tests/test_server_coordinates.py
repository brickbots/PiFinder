"""Unit tests for web location coordinate parsing.

The web location forms let users type coordinates, altitude and error. In a
comma-decimal browser locale a ``<input type="number">`` yields an empty value
for a period-formatted number (and vice-versa), which silently blocked the
save. ``parse_coordinate`` accepts either separator so the server never sees a
stray comma; these tests lock that in and guard the missing/garbage cases that
previously raised an uncaught 500.
"""

import pytest

from PiFinder.server import parse_coordinate


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("51.3", 51.3),
        ("51,3", 51.3),
        ("51", 51.0),
        ("  -3,2 ", -3.2),
        ("0", 0.0),
    ],
)
def test_parse_coordinate_accepts_both_separators(raw, expected):
    assert parse_coordinate(raw, "Latitude") == expected


@pytest.mark.unit
def test_parse_coordinate_missing_raises_value_error():
    with pytest.raises(ValueError):
        parse_coordinate(None, "Latitude")


@pytest.mark.unit
def test_parse_coordinate_garbage_raises_value_error():
    with pytest.raises(ValueError):
        parse_coordinate("not-a-number", "Longitude")
