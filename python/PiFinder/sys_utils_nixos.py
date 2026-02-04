"""
NixOS-native system utilities for PiFinder.

Replaces sys_utils.py's wpa_supplicant/hostapd/file-editing approach with:
- NetworkManager GLib bindings (gi.repository.NM) for WiFi management
- python-pam for password verification
- D-Bus for hostname/reboot/shutdown
- stdlib zipfile for backup/restore
- nixos-rebuild for camera switching and software updates
"""
import glob
import os
import subprocess
import socket
import time
import zipfile
import logging
from pathlib import Path

import requests

import dbus
import pam
import gi

gi.require_version("NM", "1.0")
from gi.repository import GLib, NM

from PiFinder import utils

BACKUP_PATH = str(utils.data_dir / "PiFinder_backup.zip")
AP_CONNECTION_NAME = "PiFinder-AP"

logger = logging.getLogger("SysUtils.NixOS")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a command, logging failures. Used only for nixos-rebuild and systemctl."""
    result = subprocess.run(cmd, capture_output=True, text=True, **kwargs)
    if result.returncode != 0:
        logger.error(
            "Command %s failed (rc=%d): %s",
            cmd, result.returncode, result.stderr.strip(),
        )
    return result


def _nm_client() -> NM.Client:
    """Create a NetworkManager client (synchronous)."""
    return NM.Client.new(None)


def _nm_run_async(async_fn, *args):
    """
    Run an async NM operation synchronously by spinning a local GLib MainLoop.

    Usage:
        result = _nm_run_async(client.add_connection_async, profile, True, None)
    """
    loop = GLib.MainLoop.new(None, False)
    state = {"result": None, "error": None}

    def callback(source, async_result, _user_data):
        try:
            # The finish method name matches the async method name:
            # add_connection_async -> add_connection_finish
            # delete_async -> delete_finish
            # activate_connection_async -> activate_connection_finish
            # deactivate_connection_async -> deactivate_connection_finish
            # commit_changes_async -> commit_changes_finish
            method_name = async_fn.__name__.replace("_async", "_finish")
            finish_fn = getattr(source, method_name)
            state["result"] = finish_fn(async_result)
        except Exception as e:
            state["error"] = e
        finally:
            loop.quit()

    async_fn(*args, callback, None)
    loop.run()

    if state["error"]:
        raise state["error"]
    return state["result"]


def _get_system_bus() -> dbus.SystemBus:
    return dbus.SystemBus()


# ---------------------------------------------------------------------------
# Network class — WiFi management via NM GLib bindings
# ---------------------------------------------------------------------------

class Network:
    """
    Provides wifi network info via NetworkManager GLib bindings (libnm).
    """

    def __init__(self):
        self._client = _nm_client()
        self._wifi_networks: list[dict] = []
        self._wifi_mode = self._detect_wifi_mode()
        self.populate_wifi_networks()

    def _detect_wifi_mode(self) -> str:
        """Detect whether we're in AP or Client mode."""
        for ac in self._client.get_active_connections():
            if ac.get_id() == AP_CONNECTION_NAME:
                return "AP"
        return "Client"

    def populate_wifi_networks(self) -> None:
        """Get saved WiFi connections from NetworkManager."""
        self._wifi_networks = []
        network_id = 0
        for conn in self._client.get_connections():
            s_wifi = conn.get_setting_wireless()
            if s_wifi is None:
                continue
            if conn.get_id() == AP_CONNECTION_NAME:
                continue
            ssid_bytes = s_wifi.get_ssid()
            ssid = ssid_bytes.get_data().decode("utf-8") if ssid_bytes else ""
            self._wifi_networks.append({
                "id": network_id,
                "ssid": ssid,
                "psk": None,
                "key_mgmt": "WPA-PSK",
            })
            network_id += 1

    def get_wifi_networks(self):
        return self._wifi_networks

    def delete_wifi_network(self, network_id):
        """Delete a saved WiFi connection."""
        if network_id < 0 or network_id >= len(self._wifi_networks):
            logger.error("Invalid network_id: %d", network_id)
            return
        ssid = self._wifi_networks[network_id]["ssid"]
        for conn in self._client.get_connections():
            if conn.get_id() == ssid:
                try:
                    _nm_run_async(conn.delete_async, None)
                except Exception as e:
                    logger.error("Failed to delete connection '%s': %s", ssid, e)
                break
        self.populate_wifi_networks()

    def add_wifi_network(self, ssid, key_mgmt, psk=None):
        """Add and connect to a WiFi network."""
        profile = NM.SimpleConnection.new()

        s_con = NM.SettingConnection.new()
        s_con.set_property(NM.SETTING_CONNECTION_ID, ssid)
        s_con.set_property(NM.SETTING_CONNECTION_TYPE, "802-11-wireless")
        s_con.set_property(NM.SETTING_CONNECTION_AUTOCONNECT, True)
        profile.add_setting(s_con)

        s_wifi = NM.SettingWireless.new()
        s_wifi.set_property(
            NM.SETTING_WIRELESS_SSID,
            GLib.Bytes.new(ssid.encode("utf-8")),
        )
        s_wifi.set_property(NM.SETTING_WIRELESS_MODE, "infrastructure")
        profile.add_setting(s_wifi)

        if key_mgmt == "WPA-PSK" and psk:
            s_wsec = NM.SettingWirelessSecurity.new()
            s_wsec.set_property(NM.SETTING_WIRELESS_SECURITY_KEY_MGMT, "wpa-psk")
            s_wsec.set_property(NM.SETTING_WIRELESS_SECURITY_PSK, psk)
            profile.add_setting(s_wsec)

        s_ip4 = NM.SettingIP4Config.new()
        s_ip4.set_property(NM.SETTING_IP_CONFIG_METHOD, "auto")
        profile.add_setting(s_ip4)

        try:
            _nm_run_async(
                self._client.add_and_activate_connection_async,
                profile,
                self._client.get_device_by_iface("wlan0"),
                None,
                None,
            )
        except Exception as e:
            logger.error("Failed to add WiFi network '%s': %s", ssid, e)

        self.populate_wifi_networks()

    def get_ap_name(self) -> str:
        """Get the current AP SSID from the PiFinder-AP profile."""
        for conn in self._client.get_connections():
            if conn.get_id() == AP_CONNECTION_NAME:
                s_wifi = conn.get_setting_wireless()
                if s_wifi:
                    ssid_bytes = s_wifi.get_ssid()
                    if ssid_bytes:
                        return ssid_bytes.get_data().decode("utf-8")
        return "PiFinderAP"

    def set_ap_name(self, ap_name: str) -> None:
        """Change the AP SSID."""
        if ap_name == self.get_ap_name():
            return
        for conn in self._client.get_connections():
            if conn.get_id() == AP_CONNECTION_NAME:
                s_wifi = conn.get_setting_wireless()
                if s_wifi:
                    s_wifi.set_property(
                        NM.SETTING_WIRELESS_SSID,
                        GLib.Bytes.new(ap_name.encode("utf-8")),
                    )
                    try:
                        _nm_run_async(conn.commit_changes_async, True, None)
                    except Exception as e:
                        logger.error("Failed to update AP SSID: %s", e)
                return

    def get_host_name(self) -> str:
        return socket.gethostname()

    def get_connected_ssid(self) -> str:
        """Returns the SSID of the connected wifi network."""
        if self.wifi_mode() == "AP":
            return ""
        device = self._client.get_device_by_iface("wlan0")
        if device is None:
            return ""
        ac = device.get_active_connection()
        if ac is None:
            return ""
        conn = ac.get_connection()
        if conn is None:
            return ""
        s_wifi = conn.get_setting_wireless()
        if s_wifi is None:
            return ""
        ssid_bytes = s_wifi.get_ssid()
        if ssid_bytes is None:
            return ""
        return ssid_bytes.get_data().decode("utf-8")

    def set_host_name(self, hostname: str) -> None:
        """Set hostname via D-Bus to org.freedesktop.hostname1."""
        if hostname == self.get_host_name():
            return
        try:
            bus = _get_system_bus()
            hostnamed = bus.get_object(
                "org.freedesktop.hostname1",
                "/org/freedesktop/hostname1",
            )
            iface = dbus.Interface(hostnamed, "org.freedesktop.hostname1")
            iface.SetStaticHostname(hostname, False)
        except dbus.DBusException as e:
            logger.error("Failed to set hostname via D-Bus: %s", e)

    def wifi_mode(self) -> str:
        return self._wifi_mode

    def set_wifi_mode(self, mode: str) -> None:
        if mode == self._wifi_mode:
            return
        if mode == "AP":
            self._activate_connection(AP_CONNECTION_NAME)
        elif mode == "Client":
            self._deactivate_connection(AP_CONNECTION_NAME)
        self._wifi_mode = mode

    def _activate_connection(self, name: str) -> None:
        """Activate a saved connection by name."""
        conn = None
        for c in self._client.get_connections():
            if c.get_id() == name:
                conn = c
                break
        if conn is None:
            logger.error("Connection '%s' not found", name)
            return
        device = self._client.get_device_by_iface("wlan0")
        try:
            _nm_run_async(
                self._client.activate_connection_async,
                conn, device, None, None,
            )
        except Exception as e:
            logger.error("Failed to activate '%s': %s", name, e)

    def _deactivate_connection(self, name: str) -> None:
        """Deactivate an active connection by name."""
        for ac in self._client.get_active_connections():
            if ac.get_id() == name:
                try:
                    _nm_run_async(
                        self._client.deactivate_connection_async, ac, None,
                    )
                except Exception as e:
                    logger.error("Failed to deactivate '%s': %s", name, e)
                return
        logger.warning("No active connection named '%s' to deactivate", name)

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


# ---------------------------------------------------------------------------
# Backup / restore (stdlib zipfile)
# ---------------------------------------------------------------------------

def remove_backup():
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
# System control (systemctl subprocess + D-Bus for reboot/shutdown)
# ---------------------------------------------------------------------------

def restart_pifinder() -> None:
    """Restart the PiFinder service."""
    logger.info("SYS: Restarting PiFinder")
    _run(["sudo", "systemctl", "restart", "pifinder"])


def restart_system() -> None:
    """Restart the system via D-Bus to login1."""
    logger.info("SYS: Initiating System Restart")
    try:
        bus = _get_system_bus()
        login1 = bus.get_object(
            "org.freedesktop.login1",
            "/org/freedesktop/login1",
        )
        manager = dbus.Interface(login1, "org.freedesktop.login1.Manager")
        manager.Reboot(False)
    except dbus.DBusException as e:
        logger.error("D-Bus reboot failed, falling back to subprocess: %s", e)
        _run(["sudo", "shutdown", "-r", "now"])


def shutdown() -> None:
    """Shut down the system via D-Bus to login1."""
    logger.info("SYS: Initiating Shutdown")
    try:
        bus = _get_system_bus()
        login1 = bus.get_object(
            "org.freedesktop.login1",
            "/org/freedesktop/login1",
        )
        manager = dbus.Interface(login1, "org.freedesktop.login1.Manager")
        manager.PowerOff(False)
    except dbus.DBusException as e:
        logger.error("D-Bus shutdown failed, falling back to subprocess: %s", e)
        _run(["sudo", "shutdown", "now"])


# ---------------------------------------------------------------------------
# Software updates — async upgrade via systemd service
# ---------------------------------------------------------------------------

UPGRADE_STATE_IDLE = "idle"
UPGRADE_STATE_RUNNING = "running"
UPGRADE_STATE_SUCCESS = "success"
UPGRADE_STATE_FAILED = "failed"

VERSIONS_URL = (
    "https://raw.githubusercontent.com/mrosseel/PiFinder/release/versions.json"
)

UPGRADE_REF_FILE = Path("/run/pifinder/upgrade-ref")


def fetch_version_manifest() -> dict | None:
    """Fetch the channel/version manifest from GitHub."""
    try:
        resp = requests.get(VERSIONS_URL, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error("Failed to fetch version manifest: %s", e)
        return None


def get_versions_for_channel(channel: str) -> list[dict]:
    """Get available versions for a channel.

    Returns list of {version, ref, date, notes}.
    """
    manifest = fetch_version_manifest()
    if manifest is None:
        return []
    return manifest.get("channels", {}).get(channel, {}).get("versions", [])


def get_available_channels() -> list[str]:
    """Get list of available channel names."""
    manifest = fetch_version_manifest()
    if manifest is None:
        return ["stable"]
    return list(manifest.get("channels", {}).keys())


def start_upgrade(ref: str = "release") -> bool:
    """Start pifinder-upgrade.service with a specific git ref.

    Writes the ref to /run/pifinder/upgrade-ref for the service to read.
    Returns True if the service was started successfully.
    """
    try:
        UPGRADE_REF_FILE.write_text(ref)
    except OSError as e:
        logger.error("Failed to write upgrade ref file: %s", e)
        return False

    _run(["sudo", "systemctl", "reset-failed", "pifinder-upgrade.service"])
    result = _run([
        "sudo", "systemctl", "start", "--no-block",
        "pifinder-upgrade.service",
    ])
    return result.returncode == 0


def get_upgrade_state() -> str:
    """Poll upgrade service state."""
    result = _run(["systemctl", "is-active", "pifinder-upgrade.service"])
    status = result.stdout.strip()
    if status == "activating":
        return UPGRADE_STATE_RUNNING
    elif status == "active":
        return UPGRADE_STATE_SUCCESS
    elif status == "failed":
        return UPGRADE_STATE_FAILED
    return UPGRADE_STATE_IDLE


def get_upgrade_log_tail(lines: int = 3) -> str:
    """Last N lines from upgrade journal for UI display."""
    result = _run([
        "journalctl", "-u", "pifinder-upgrade.service",
        "-n", str(lines), "--no-pager", "-o", "cat",
    ])
    return result.stdout.strip() if result.returncode == 0 else ""


def update_software() -> bool:
    """Blocking wrapper for backward compatibility (uses default ref)."""
    if not start_upgrade():
        return False
    while True:
        time.sleep(10)
        state = get_upgrade_state()
        if state == UPGRADE_STATE_SUCCESS:
            return True
        elif state == UPGRADE_STATE_FAILED:
            return False


# ---------------------------------------------------------------------------
# Password management (python-pam + chpasswd)
# ---------------------------------------------------------------------------

def verify_password(username: str, password: str) -> bool:
    """Verify a password against PAM."""
    p = pam.pam()
    return p.authenticate(username, password, service="login")


def change_password(username: str, current_password: str, new_password: str) -> bool:
    """Change the user password via chpasswd."""
    if not verify_password(username, current_password):
        return False
    result = subprocess.run(
        ["sudo", "chpasswd"],
        input=f"{username}:{new_password}\n",
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


# ---------------------------------------------------------------------------
# Camera switching (nixos-rebuild + reboot)
# ---------------------------------------------------------------------------

def switch_camera(cam_type: str) -> None:
    """
    Switch camera by rebuilding NixOS with the appropriate camera type.
    Requires reboot (dtoverlay change).
    """
    logger.info("SYS: Switching camera to %s via nixos-rebuild", cam_type)
    flake_path = str(utils.pifinder_home)
    result = _run([
        "sudo", "nixos-rebuild", "switch",
        "--flake", f"{flake_path}#pifinder-{cam_type}",
    ])
    if result.returncode == 0:
        restart_system()
    else:
        logger.error("SYS: Camera switch rebuild failed: %s", result.stderr)


def switch_cam_imx477() -> None:
    logger.info("SYS: Switching cam to imx477")
    switch_camera("imx477")


def switch_cam_imx296() -> None:
    logger.info("SYS: Switching cam to imx296")
    switch_camera("imx296")


def switch_cam_imx462() -> None:
    logger.info("SYS: Switching cam to imx462")
    switch_camera("imx462")


# ---------------------------------------------------------------------------
# GPSD config (declarative on NixOS — no-ops)
# ---------------------------------------------------------------------------

def check_and_sync_gpsd_config(baud_rate: int) -> bool:
    """
    On NixOS, GPSD config is managed declaratively via services.nix.
    This is a no-op.
    """
    logger.info(
        "SYS: GPSD baud rate %d — managed by NixOS configuration", baud_rate
    )
    return False


def update_gpsd_config(baud_rate: int) -> None:
    """On NixOS, GPSD configuration is declarative. This is a no-op."""
    logger.info(
        "SYS: GPSD config is managed declaratively on NixOS (baud=%d)", baud_rate
    )
