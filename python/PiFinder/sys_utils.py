"""
NixOS system utilities for PiFinder.

Uses:
- NetworkManager GLib bindings (gi.repository.NM) for WiFi management
- python-pam for password verification
- D-Bus for hostname/reboot/shutdown
- stdlib zipfile for backup/restore
- NixOS specialisations for camera switching
- systemd service for software updates
"""

import os
import re
import json
import subprocess
import logging

from PiFinder import timez
from pathlib import Path
from typing import Optional

import dbus
import pam
import gi

gi.require_version("NM", "1.0")
from gi.repository import GLib, NM  # noqa: E402

from PiFinder.sys_utils_base import (  # noqa: E402
    NetworkBase,
    BACKUP_PATH,  # noqa: F401
    remove_backup,  # noqa: F401
    backup_userdata,  # noqa: F401
    restore_userdata,  # noqa: F401
    restart_pifinder,  # noqa: F401
)

AP_CONNECTION_NAME = "PiFinder-AP"

logger = logging.getLogger("SysUtils.NixOS")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a command, logging failures."""
    result = subprocess.run(cmd, capture_output=True, text=True, **kwargs)
    if result.returncode != 0:
        logger.error(
            "Command %s failed (rc=%d): %s",
            cmd,
            result.returncode,
            result.stderr.strip(),
        )
    return result


def _nm_client() -> NM.Client:
    """Create a NetworkManager client (synchronous)."""
    return NM.Client.new(None)


def _nm_run_async(async_fn, *args):
    """
    Run an async NM operation synchronously by spinning a local GLib MainLoop.
    """
    loop = GLib.MainLoop.new(None, False)
    state = {"result": None, "error": None}

    def callback(source, async_result, _user_data):
        try:
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


class Network(NetworkBase):
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
            ssid = (
                ssid_bytes.get_data().decode("utf-8", "replace") if ssid_bytes else ""
            )
            self._wifi_networks.append(
                {
                    "id": network_id,
                    "uuid": conn.get_uuid(),
                    "ssid": ssid,
                    "psk": None,
                    "key_mgmt": "WPA-PSK",
                }
            )
            network_id += 1

    def get_wifi_networks(self):
        """Return the saved networks, re-queried live from NetworkManager.

        The list is not cached: changes made outside this process (the AP/CLI
        switch, another tool, a repair) are reflected on the next read.
        """
        self.populate_wifi_networks()
        return self._wifi_networks

    def wifi_mode(self) -> str:
        """Report the actual current mode from NetworkManager.

        AP fallback (or any out-of-band change) can flip the radio after init,
        so detect live rather than trusting the value cached at construction —
        otherwise the UI shows "Client" while the device is really broadcasting
        the AP. Refreshing the cached field keeps local_ip()/set_wifi_mode()
        consistent too.
        """
        self._wifi_mode = self._detect_wifi_mode()
        return self._wifi_mode

    def is_wired_connected(self) -> bool:
        """True if an ethernet device has an active connection."""
        try:
            for dev in self._client.get_devices():
                if (
                    dev.get_device_type() == NM.DeviceType.ETHERNET
                    and dev.get_active_connection() is not None
                ):
                    return True
        except Exception:
            return False
        return False

    def delete_wifi_network(self, network_id):
        """Delete a saved WiFi connection by its NetworkManager UUID.

        Matching on the UUID (not the connection id or SSID) is what makes this
        robust: a connection's id need not equal its SSID, and corrupt entries
        store unrelated text in the SSID field, so an id/SSID match silently
        fails to delete them.
        """
        if network_id < 0 or network_id >= len(self._wifi_networks):
            logger.error("Invalid network_id: %d", network_id)
            return
        entry = self._wifi_networks[network_id]
        conn = self._client.get_connection_by_uuid(entry["uuid"])
        if conn is None:
            logger.error("Connection uuid %s not found", entry["uuid"])
        else:
            try:
                _nm_run_async(conn.delete_async, None)
            except Exception as e:
                logger.error("Failed to delete connection '%s': %s", entry["ssid"], e)
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

        # Persist the connection first. Saving must not depend on being able to
        # activate it right now: wlan0 is often unavailable at add time (in AP
        # mode, or out of range of the new network), and add_and_activate would
        # then fail and save nothing.
        try:
            conn = _nm_run_async(self._client.add_connection_async, profile, True, None)
        except Exception as e:
            logger.error("Failed to add WiFi network '%s': %s", ssid, e)
            self.populate_wifi_networks()
            return

        # Best effort: bring it up now if the radio is available.
        device = self._client.get_device_by_iface("wlan0")
        if device is not None:
            try:
                _nm_run_async(
                    self._client.activate_connection_async, conn, device, None, None
                )
            except Exception as e:
                logger.warning("Saved '%s' but could not activate it now: %s", ssid, e)

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
        """Change the AP SSID.

        Commit the new SSID to the PiFinder-AP profile and, when AP is the live
        WiFi mode, re-activate the connection so the running access point
        rebroadcasts under the new name without a reboot. (Clients must rejoin
        anyway once the SSID changes.)
        """
        if ap_name == self.get_ap_name():
            return
        conn = None
        for c in self._client.get_connections():
            if c.get_id() == AP_CONNECTION_NAME:
                conn = c
                break
        if conn is None:
            logger.error("Connection '%s' not found", AP_CONNECTION_NAME)
            return
        s_wifi = conn.get_setting_wireless()
        if s_wifi is None:
            return
        s_wifi.set_property(
            NM.SETTING_WIRELESS_SSID,
            GLib.Bytes.new(ap_name.encode("utf-8")),
        )
        try:
            _nm_run_async(conn.commit_changes_async, True, None)
        except Exception as e:
            logger.error("Failed to update AP SSID: %s", e)
            return
        if self.wifi_mode() == "AP":
            self._activate_connection(AP_CONNECTION_NAME)

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

    _HOSTNAME_RE = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$")

    def set_host_name(self, hostname: str) -> None:
        """Set kernel hostname and update avahi mDNS announcement.

        NixOS makes /etc/hostname read-only (nix store symlink), so we set
        the kernel hostname directly and persist to a file that a boot
        service reads on startup.
        """
        hostname = hostname.strip()
        if not self._HOSTNAME_RE.match(hostname):
            logger.warning("Invalid hostname rejected: %r", hostname)
            return
        if hostname == self.get_host_name():
            return
        subprocess.run(["sudo", "hostname", hostname], check=False)
        result = subprocess.run(["sudo", "avahi-set-host-name", hostname], check=False)
        if result.returncode != 0:
            logger.warning(
                "avahi-set-host-name failed (rc=%d), restarting avahi-daemon",
                result.returncode,
            )
            subprocess.run(
                ["sudo", "systemctl", "restart", "avahi-daemon.service"],
                check=False,
            )
        data_dir = Path(os.environ.get("PIFINDER_DATA", "/home/pifinder/PiFinder_data"))
        (data_dir / "hostname").write_text(hostname)

    def _go_ap(self) -> None:
        """Activate the AP connection and remember the choice across reboots."""
        self._persist_wifi_mode("AP")
        self._activate_connection(AP_CONNECTION_NAME)

    def _go_client(self) -> None:
        """Deactivate the AP connection (fall back to client)."""
        self._persist_wifi_mode("Client")
        self._deactivate_connection(AP_CONNECTION_NAME)

    @staticmethod
    def _persist_wifi_mode(mode: str) -> None:
        """Persist the desired WiFi mode for the boot-time fallback service.

        The PiFinder-AP NetworkManager profile has a low autoconnect priority,
        so a forced AP would otherwise be lost on reboot; the fallback service
        reads this file to restore it.
        """
        data_dir = Path(os.environ.get("PIFINDER_DATA", "/home/pifinder/PiFinder_data"))
        try:
            (data_dir / "wifi_mode").write_text(mode)
        except OSError as e:
            logger.warning("Could not persist WiFi mode %r: %s", mode, e)

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
                conn,
                device,
                None,
                None,
            )
        except Exception as e:
            logger.error("Failed to activate '%s': %s", name, e)

    def _deactivate_connection(self, name: str) -> None:
        """Deactivate an active connection by name."""
        for ac in self._client.get_active_connections():
            if ac.get_id() == name:
                try:
                    _nm_run_async(
                        self._client.deactivate_connection_async,
                        ac,
                        None,
                    )
                except Exception as e:
                    logger.error("Failed to deactivate '%s': %s", name, e)
                return
        logger.warning("No active connection named '%s' to deactivate", name)


# ---------------------------------------------------------------------------
# Module-level WiFi switching (called by callbacks.py and status.py)
# ---------------------------------------------------------------------------

_network_instance: Optional[Network] = None


def _get_network() -> Network:
    global _network_instance
    if _network_instance is None:
        _network_instance = Network()
    return _network_instance


def go_wifi_ap():
    logger.info("SYS: Switching to AP")
    net = _get_network()
    net.set_wifi_mode("AP")
    return True


def go_wifi_cli():
    logger.info("SYS: Switching to Client")
    net = _get_network()
    net.set_wifi_mode("Client")
    return True


def get_wifi_mode() -> str:
    """The live WiFi mode ("AP" or "Client") from NetworkManager."""
    return _get_network().wifi_mode()


# ---------------------------------------------------------------------------
# System control (systemctl subprocess + D-Bus for reboot/shutdown)
# ---------------------------------------------------------------------------


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

UPGRADE_REF_FILE = Path("/run/pifinder/upgrade-ref")
UPGRADE_SELECTION_FILE = Path("/run/pifinder/upgrade-selection.json")
UPGRADE_STATUS_FILE = Path("/run/pifinder/upgrade-status")


def _upgrade_service_state() -> str:
    result = subprocess.run(
        ["systemctl", "is-active", "pifinder-upgrade.service"],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def start_upgrade(ref: str = "release", selection: Optional[dict] = None) -> bool:
    """Start pifinder-upgrade.service with a specific git ref."""
    try:
        UPGRADE_REF_FILE.write_text(ref)
        if selection:
            UPGRADE_SELECTION_FILE.write_text(json.dumps(selection, sort_keys=True))
        else:
            UPGRADE_SELECTION_FILE.unlink(missing_ok=True)
    except OSError as e:
        logger.error("Failed to write upgrade ref file: %s", e)
        return False

    # Clean stale status from previous run
    UPGRADE_STATUS_FILE.unlink(missing_ok=True)

    # reset-failed errors on a unit that isn't loaded, so only clear an
    # actual failed state
    if _upgrade_service_state() == "failed":
        _run(["sudo", "systemctl", "reset-failed", "pifinder-upgrade.service"])
    result = _run(
        [
            "sudo",
            "systemctl",
            "start",
            "--no-block",
            "pifinder-upgrade.service",
        ]
    )
    if result.returncode != 0:
        UPGRADE_STATUS_FILE.write_text("failed")
        return False
    return True


def list_rollback_targets(profile_dir: Path = Path("/nix/var/nix/profiles")) -> list:
    """On-disk system generations available for rollback (all but the current).

    Reads only immutable generation data — the profile symlinks and the
    store-path names — so there is NO sidecar state file to evolve or corrupt,
    and it works even when the updater is offline. Each entry mirrors a
    Software-screen version entry so the same list UI can render it.
    """
    try:
        current = (profile_dir / "system").resolve()
    except OSError:
        return []

    targets = []
    for link in profile_dir.glob("system-*-link"):
        try:
            generation = int(link.name.split("-")[1])
            store_path = link.resolve()
            mtime = link.lstat().st_mtime
        except (OSError, ValueError, IndexError):
            continue
        if store_path == current:
            continue
        marker = "nixos-system-pifinder-"
        name = store_path.name
        label = name.split(marker, 1)[-1] if marker in name else name
        # Local time for display, via the tz-aware timez helper (DTZ)
        date = timez.utc_from_timestamp(mtime).astimezone().strftime("%d %b %H:%M")
        targets.append(
            (
                generation,
                {
                    "ref": str(store_path),
                    "label": label,
                    "version": label,
                    "notes": None,
                    "subtitle": f"gen {generation} · {date}",
                    "channel": "rollback",
                },
            )
        )
    targets.sort(key=lambda t: t[0], reverse=True)
    return [entry for _generation, entry in targets]


def get_upgrade_state() -> str:
    """Poll upgrade status file written by the upgrade service."""
    try:
        status = UPGRADE_STATUS_FILE.read_text().strip()
    except FileNotFoundError:
        # Service hasn't written status yet — check if it's still starting
        svc = _upgrade_service_state()
        if svc in ("activating", "active"):
            return UPGRADE_STATE_RUNNING
        if svc == "failed":
            return UPGRADE_STATE_FAILED
        return UPGRADE_STATE_IDLE

    if status == "success":
        return UPGRADE_STATE_SUCCESS
    elif status in ("failed", "unavailable", "connfail"):
        return UPGRADE_STATE_FAILED
    elif status.startswith("downloading") or status in (
        "starting",
        "activating",
        "rebooting",
    ):
        return UPGRADE_STATE_RUNNING
    return UPGRADE_STATE_IDLE


def get_upgrade_progress() -> dict:
    """Return structured upgrade progress for UI display.

    Returns dict with keys:
      phase: "starting" | "downloading" | "activating" | "rebooting"
             | "success" | "failed" | "unavailable" | "connfail" | ""
      done: int (downloaded so far, in `unit`)
      total: int (total to download, in `unit`)
      unit: "bytes" | "paths"
      percent: int (0-100)

    The download status line is "downloading <done>/<total>" in bytes;
    a trailing " paths" marks the fallback where byte sizes were not
    available and the figures are path counts instead.
    """
    empty = {
        "phase": "",
        "done": 0,
        "total": 0,
        "unit": "bytes",
        "percent": 0,
        "item": "",
    }
    try:
        raw = UPGRADE_STATUS_FILE.read_text().strip()
    except FileNotFoundError:
        svc = _upgrade_service_state()
        if svc in ("activating", "active"):
            return {**empty, "phase": "starting"}
        if svc == "failed":
            return {**empty, "phase": "failed"}
        return empty

    svc = _upgrade_service_state()
    if raw in ("starting", "activating") or raw.startswith("downloading "):
        if svc in ("failed", "inactive"):
            return {**empty, "phase": "failed"}

    if raw.startswith("downloading "):
        body = raw[len("downloading ") :].strip()
        unit = "bytes"
        if body.endswith(" paths"):
            unit = "paths"
            body = body[: -len(" paths")].strip()
        # body is "<done>/<total>" optionally followed by " <package label>"
        nums, _sep, item = body.partition(" ")
        parts = nums.split("/")
        try:
            done, total = int(parts[0]), int(parts[1])
            pct = int(done * 100 / total) if total > 0 else 0
            pct = max(0, min(100, pct))
            return {
                "phase": "downloading",
                "done": done,
                "total": total,
                "unit": unit,
                "percent": pct,
                "item": item.strip(),
            }
        except (ValueError, IndexError):
            return {**empty, "phase": "downloading"}
    if raw == "starting":
        return {**empty, "phase": "starting"}
    if raw == "activating":
        return {**empty, "phase": "activating", "percent": 100}
    if raw == "rebooting":
        return {**empty, "phase": "rebooting", "percent": 100}
    if raw == "success":
        return {**empty, "phase": "success", "percent": 100}
    if raw == "unavailable":
        return {**empty, "phase": "unavailable"}
    if raw == "connfail":
        return {**empty, "phase": "connfail"}
    if raw == "failed":
        return {**empty, "phase": "failed"}
    return empty


def get_upgrade_log_tail(lines: int = 3) -> str:
    """Last N lines from upgrade journal for UI display."""
    result = _run(
        [
            "journalctl",
            "-u",
            "pifinder-upgrade.service",
            "-n",
            str(lines),
            "--no-pager",
            "-o",
            "cat",
        ]
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def update_software(ref: str = "release", selection: Optional[dict] = None) -> bool:
    """Start the upgrade service (non-blocking).

    The service downloads, sets the boot profile, and reboots.
    UI should poll get_upgrade_progress() for status.
    """
    return start_upgrade(ref=ref, selection=selection)


# ---------------------------------------------------------------------------
# Password management (python-pam + chpasswd)
# ---------------------------------------------------------------------------


def verify_password(username: str, password: str) -> bool:
    """Verify a password against PAM."""
    p = pam.pam()
    return p.authenticate(username, password, service="pifinder")


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
# Camera switching (specialisations + reboot)
# ---------------------------------------------------------------------------

CAMERA_TYPE_FILE = "/var/lib/pifinder/camera-type"


def switch_camera(cam_type: str) -> None:
    """
    Switch camera via NixOS specialisation.
    Requires reboot (dtoverlay change).
    """
    logger.info("SYS: Switching camera to %s via specialisation", cam_type)
    result = _run(["sudo", "pifinder-switch-camera", cam_type])
    if result.returncode != 0:
        logger.error("SYS: Camera switch failed: %s", result.stderr)


def get_camera_type() -> list[str]:
    try:
        with open(CAMERA_TYPE_FILE) as f:
            return [f.read().strip()]
    except FileNotFoundError:
        return ["imx462"]


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
    logger.info("SYS: GPSD baud rate %d — managed by NixOS configuration", baud_rate)
    return False


def update_gpsd_config(baud_rate: int) -> None:
    """On NixOS, GPSD configuration is declarative. This is a no-op."""
    logger.info(
        "SYS: GPSD config is managed declaratively on NixOS (baud=%d)", baud_rate
    )


# Raspberry Pi red power LED — a plain gpio-led (on/off only, not dimmable).
PWR_LED_PATH = Path("/sys/class/leds/PWR")


def set_power_led(on: bool) -> None:
    """Turn the Raspberry Pi's red PWR LED on or off.

    The kernel trigger is set to "none" first, otherwise the firmware's
    "default-on" trigger keeps re-asserting the LED. Direct sysfs writes —
    pwm-permissions (services.nix) makes these files user-writable at boot,
    so no sudo is needed. A missing LED (dev box, other SBC) raises OSError,
    which the caller treats as non-fatal.
    """
    (PWR_LED_PATH / "trigger").write_text("none")
    (PWR_LED_PATH / "brightness").write_text("1" if on else "0")
