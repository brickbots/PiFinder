"""Which service may open generic USB-serial bridges: gpsd or a mount.

A udev rule (nixos/indi.nix) keeps gpsd hotplug off the generic bridges
(CP210x and others) that mount controllers use too, unless GENERIC_GPS_FILE
exists. PiFinder creates that file when GPS Type is "GPSD (generic)", so a
USB GPS dongle on such a bridge still goes to gpsd. The file persists, so
the rule holds at boot too.
"""

import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger("USBGPS")

GENERIC_GPS_FILE = Path("/var/lib/pifinder/usb/generic-gps")


def bridges() -> list[str]:
    """USB vendor IDs of the generic bridges (from nixos/indi.nix)."""
    return os.environ.get("PIFINDER_MOUNT_USB_BRIDGES", "").split()


def set_generic_usb_gps(enabled: bool, marker: Path = GENERIC_GPS_FILE) -> bool:
    """Create or remove the marker. Return True if this changed it. Does
    nothing where the directory does not exist (not the NixOS image)."""
    if not marker.parent.is_dir():
        return False
    if enabled == marker.exists():
        return False
    try:
        if enabled:
            marker.touch()
        else:
            marker.unlink()
    except OSError as e:
        logger.warning("Cannot update %s: %s", marker, e)
        return False
    logger.info("Generic USB GPS on gpsd: %s", enabled)
    return True


def _usb_vendor(tty: Path) -> Optional[str]:
    """The idVendor of the USB device above a tty, or None."""
    try:
        node = (tty / "device").resolve()
    except OSError:
        return None
    for parent in [node, *node.parents]:
        vendor = parent / "idVendor"
        if vendor.is_file():
            try:
                return vendor.read_text().strip()
            except OSError:
                return None
    return None


def bridge_plugged_in(sys_tty: Path = Path("/sys/class/tty")) -> bool:
    """True if a tty on one of the generic bridges exists now. udev applies
    the rule at plug-in, so such a device needs a replug after a change."""
    wanted = set(bridges())
    if not wanted or not sys_tty.is_dir():
        return False
    return any(_usb_vendor(tty) in wanted for tty in sys_tty.iterdir())
