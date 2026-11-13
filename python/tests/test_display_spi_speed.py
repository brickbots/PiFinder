"""Tests for the display SPI speed setting (display_spi_speed_mhz / --spi-speed).

The setting is in MHz; None keeps each panel's default clock. A bad value
must fall back to the default rather than stop the display from starting.
"""

import pytest

from PiFinder import displays
from PiFinder.displays import get_display, spi_speed_hz_from_mhz


@pytest.mark.unit
@pytest.mark.parametrize(
    "value, expected",
    [
        (None, None),
        (10, 10_000_000),
        (8.5, 8_500_000),
        ("16", 16_000_000),
        (0, None),
        (-5, None),
        ("fast", None),
        ([10], None),
    ],
)
def test_spi_speed_hz_from_mhz(value, expected):
    assert spi_speed_hz_from_mhz(value) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "spi_speed_hz, expected",
    [(None, 40_000_000), (10_000_000, 10_000_000)],
)
def test_get_display_passes_spi_speed(monkeypatch, spi_speed_hz, expected):
    seen = {}

    def fake_spi(**kwargs):
        seen.update(kwargs)
        return object()

    class FakeDevice:
        def __init__(self, serial, **kwargs):
            pass

        def capabilities(self, **kwargs):
            pass

    monkeypatch.setattr(displays, "spi", fake_spi)
    monkeypatch.setattr(displays, "ssd1351", FakeDevice)
    get_display("ssd1351", spi_speed_hz)
    assert seen["bus_speed_hz"] == expected
