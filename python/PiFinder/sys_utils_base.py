"""
Abstract base for PiFinder system utilities.

Defines the public API contract and shared implementations used by all
platform backends (Debian, NixOS, fake/testing).
"""

import logging
import socket
import zipfile
from abc import ABC, abstractmethod
from pathlib import Path

from PiFinder import utils

BACKUP_PATH = str(utils.data_dir / "PiFinder_backup.zip")

logger = logging.getLogger("SysUtils")


# ---------------------------------------------------------------------------
# Network ABC — shared + abstract methods
# ---------------------------------------------------------------------------


class NetworkBase(ABC):
    """Base class for platform-specific Network implementations."""

    _wifi_mode: str = "Client"
    _wifi_networks: list = []

    def get_host_name(self) -> str:
        return socket.gethostname()

    def is_wired_connected(self) -> bool:
        """True when a wired (ethernet) link is the active uplink. Overridden
        on hardware; the base default assumes no wired link."""
        return False

    def local_ip(self) -> str:
        # In AP mode the only address is the AP's own — unless an ethernet
        # cable is plugged in, in which case the device is really reachable on
        # the wired IP, so fall through to it.
        if self._wifi_mode == "AP" and not self.is_wired_connected():
            return "10.10.10.1"
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("192.255.255.255", 1))
            ip = s.getsockname()[0]
        except Exception:
            ip = "NONE"
        finally:
            s.close()
        return ip

    def get_active_label(self) -> str:
        """Label for the active uplink, for the status display: a wired link
        wins (shown as 'Ethernet'), then the connected client SSID, then the
        AP name; empty if nothing is up."""
        if self.is_wired_connected():
            return "Ethernet"
        ssid = self.get_connected_ssid()
        if ssid:
            return ssid
        if self.wifi_mode() == "AP":
            return self.get_ap_name()
        return ""

    def wifi_mode(self) -> str:
        return self._wifi_mode

    def get_wifi_networks(self):
        return self._wifi_networks

    def set_wifi_mode(self, mode: str) -> None:
        if mode == self._wifi_mode:
            return
        if mode == "AP":
            self._go_ap()
        elif mode == "Client":
            self._go_client()
        self._wifi_mode = mode

    @abstractmethod
    def _go_ap(self) -> None: ...

    @abstractmethod
    def _go_client(self) -> None: ...

    @abstractmethod
    def populate_wifi_networks(self) -> None: ...

    @abstractmethod
    def delete_wifi_network(self, network_id) -> None: ...

    @abstractmethod
    def add_wifi_network(self, ssid, key_mgmt, psk=None) -> None: ...

    @abstractmethod
    def get_ap_name(self) -> str: ...

    @abstractmethod
    def set_ap_name(self, ap_name: str) -> None: ...

    @abstractmethod
    def get_connected_ssid(self) -> str: ...

    @abstractmethod
    def set_host_name(self, hostname: str) -> None: ...


# ---------------------------------------------------------------------------
# Backup / restore (stdlib zipfile — portable across all platforms)
# ---------------------------------------------------------------------------


def remove_backup() -> None:
    """Removes backup file."""
    path = Path(BACKUP_PATH)
    if path.exists():
        path.unlink()


def backup_userdata() -> str:
    """
    Back up userdata to a single zip file.

    Backs up:
        config.json
        observations.db
        obslists/*
    """
    remove_backup()

    files = [
        utils.data_dir / "config.json",
        utils.data_dir / "observations.db",
    ]
    for p in utils.data_dir.glob("obslists/*"):
        files.append(p)

    with zipfile.ZipFile(BACKUP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for filepath in files:
            filepath = Path(filepath)
            if filepath.exists():
                zf.write(filepath, filepath.relative_to("/"))

    return BACKUP_PATH


def restore_userdata(zip_path: str) -> None:
    """
    Restore userdata from a zip backup.
    OVERWRITES existing data!
    """
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall("/")


# ---------------------------------------------------------------------------
# Service control (shared across Debian + NixOS)
# ---------------------------------------------------------------------------


def restart_pifinder() -> None:
    """Restart the PiFinder service via systemctl."""
    import subprocess

    logger.info("SYS: Restarting PiFinder")
    # Must be the full unit name: the NixOS sudoers rule allows exactly
    # "systemctl restart pifinder.service", and sudo matches arguments
    # verbatim — "restart pifinder" is refused and the restart silently
    # never happens (the UI shows "Restarting..." but the stale process
    # keeps running, e.g. with the old screen_direction IMU geometry).
    result = subprocess.run(
        ["sudo", "-n", "systemctl", "restart", "pifinder.service"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.error("SYS: PiFinder restart failed: %s", result.stderr.strip())
