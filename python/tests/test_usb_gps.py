"""The generic USB GPS marker and the bridge check (usb_gps.py)."""

import pytest

from PiFinder import usb_gps

pytestmark = pytest.mark.unit


def test_marker_follows_gps_type(tmp_path):
    marker = tmp_path / "usb" / "generic-gps"
    marker.parent.mkdir()
    assert usb_gps.set_generic_usb_gps(True, marker)
    assert marker.exists()
    assert not usb_gps.set_generic_usb_gps(True, marker)  # no change
    assert usb_gps.set_generic_usb_gps(False, marker)
    assert not marker.exists()
    assert not usb_gps.set_generic_usb_gps(False, marker)


def test_marker_needs_the_directory(tmp_path):
    marker = tmp_path / "missing" / "generic-gps"
    assert not usb_gps.set_generic_usb_gps(True, marker)
    assert not marker.parent.exists()


def _sysfs(tmp_path, ttys):
    """A /sys/class/tty with ttys that link to USB devices: name -> vendor."""
    sys_tty = tmp_path / "class" / "tty"
    sys_tty.mkdir(parents=True)
    for name, vendor in ttys.items():
        usb = tmp_path / "devices" / name / "usb1" / "1-1"
        port = usb / "1-1:1.0" / name
        port.mkdir(parents=True)
        if vendor:
            (usb / "idVendor").write_text(vendor + "\n")
        (sys_tty / name).mkdir()
        (sys_tty / name / "device").symlink_to(port)
    return sys_tty


def test_bridge_plugged_in(tmp_path, monkeypatch):
    monkeypatch.setenv("PIFINDER_MOUNT_USB_BRIDGES", "10c4 0557 067b")
    with_bridge = _sysfs(tmp_path / "a", {"ttyUSB0": "10c4", "ttyAMA0": None})
    assert usb_gps.bridge_plugged_in(with_bridge)
    ftdi_only = _sysfs(tmp_path / "b", {"ttyUSB0": "0403"})
    assert not usb_gps.bridge_plugged_in(ftdi_only)


def test_bridge_check_off_without_list(tmp_path, monkeypatch):
    monkeypatch.delenv("PIFINDER_MOUNT_USB_BRIDGES", raising=False)
    assert not usb_gps.bridge_plugged_in(_sysfs(tmp_path, {"ttyUSB0": "10c4"}))
    assert not usb_gps.bridge_plugged_in(tmp_path / "none")
