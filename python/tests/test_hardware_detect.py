"""
Unit tests for hardware_detect.

The I2C bus is faked: a stand-in ``board`` whose ``I2C().scan()`` returns
a chosen address list, so the BQ25895 presence probe can be exercised
both ways without real hardware. The no-blinka path (board is None) must
degrade to all-False capabilities.
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


class FakeBoard:
    """Stand-in for the ``board`` module: ``I2C()`` returns a FakeI2C."""

    def __init__(self, addresses):
        self._addresses = addresses

    def I2C(self):
        return FakeI2C(self._addresses)


@pytest.mark.unit
def test_i2c_present_true(monkeypatch):
    monkeypatch.setattr(hardware_detect, "board", FakeBoard([0x28, BQ25895_ADDRESS]))
    assert hardware_detect.i2c_present(BQ25895_ADDRESS) is True


@pytest.mark.unit
def test_i2c_present_false(monkeypatch):
    monkeypatch.setattr(hardware_detect, "board", FakeBoard([0x28, 0x77]))
    assert hardware_detect.i2c_present(BQ25895_ADDRESS) is False


@pytest.mark.unit
def test_detect_capabilities_present(monkeypatch):
    monkeypatch.setattr(hardware_detect, "board", FakeBoard([BQ25895_ADDRESS]))
    caps = hardware_detect.detect_capabilities()
    assert caps.has_bq25895 is True


@pytest.mark.unit
def test_detect_capabilities_absent(monkeypatch):
    monkeypatch.setattr(hardware_detect, "board", FakeBoard([0x28]))
    caps = hardware_detect.detect_capabilities()
    assert caps.has_bq25895 is False


@pytest.mark.unit
def test_detect_capabilities_no_blinka(monkeypatch):
    """No blinka / no bus (board is None) -> all-False, no exception."""
    monkeypatch.setattr(hardware_detect, "board", None)
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
