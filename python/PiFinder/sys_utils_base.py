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

    def local_ip(self) -> str:
        if self._wifi_mode == "AP":
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
    subprocess.run(["sudo", "systemctl", "restart", "pifinder"])
