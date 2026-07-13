"""
Unit tests for hardware_detect.

The I2C bus is faked: a stand-in ``get_i2c`` factory whose bus ``scan()``
returns a chosen address list, so the BQ25895 presence probe can be
exercised both ways without real hardware. The no-blinka path (get_i2c is
None) must degrade to all-False capabilities.
"""

import pytest

from PiFinder import hardware_detect
from PiFinder.hardware_detect import BQ25895_ADDRESS


class FakeI2C:
    """Minimal busio.I2C stand-in: lockable, with a fixed scan result."""

    def __init__(self, addresses):
        self._addresses = list(addresses)

    def try_lock(self):
        return True

    def unlock(self):
        pass

    def scan(self):
        return list(self._addresses)


def fake_get_i2c(addresses):
    """Stand-in for ``i2c_bus.get_i2c``: returns a FakeI2C factory."""

    def factory():
        return FakeI2C(addresses)

    return factory


@pytest.mark.unit
def test_i2c_present_true(monkeypatch):
    monkeypatch.setattr(
        hardware_detect, "get_i2c", fake_get_i2c([0x28, BQ25895_ADDRESS])
    )
    assert hardware_detect.i2c_present(BQ25895_ADDRESS) is True


@pytest.mark.unit
def test_i2c_present_false(monkeypatch):
    monkeypatch.setattr(hardware_detect, "get_i2c", fake_get_i2c([0x28, 0x77]))
    assert hardware_detect.i2c_present(BQ25895_ADDRESS) is False


@pytest.mark.unit
def test_detect_capabilities_present(monkeypatch):
    monkeypatch.setattr(hardware_detect, "get_i2c", fake_get_i2c([BQ25895_ADDRESS]))
    caps = hardware_detect.detect_capabilities()
    assert caps.has_bq25895 is True


@pytest.mark.unit
def test_detect_capabilities_absent(monkeypatch):
    monkeypatch.setattr(hardware_detect, "get_i2c", fake_get_i2c([0x28]))
    caps = hardware_detect.detect_capabilities()
    assert caps.has_bq25895 is False


@pytest.mark.unit
def test_detect_capabilities_no_blinka(monkeypatch):
    """No blinka / no bus (get_i2c is None) -> all-False, no exception."""
    monkeypatch.setattr(hardware_detect, "get_i2c", None)
    caps = hardware_detect.detect_capabilities()
    assert caps.has_bq25895 is False
    # The raw probe surfaces the failure; detect_capabilities swallows it.
    with pytest.raises(RuntimeError):
        hardware_detect.i2c_present(BQ25895_ADDRESS)


@pytest.mark.unit
def test_detect_capabilities_swallows_probe_error(monkeypatch):
    """A probe exception (e.g. bus error) degrades to all-False."""

    def boom(*args, **kwargs):
        raise OSError("bus error")

    monkeypatch.setattr(hardware_detect, "i2c_present", boom)
    caps = hardware_detect.detect_capabilities()
    assert caps.has_bq25895 is False
