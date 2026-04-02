"""
INDI Alignment Subsystem Manager
---------------------------------
Detects and optionally disables the INDI alignment subsystem on connected
telescope mounts that would otherwise interfere with PiFinder's own
plate-solve–based pointing corrections.

Startup flow
~~~~~~~~~~~~
1. Load in-repo ``indi_disable_alignment.yml`` and user-override
   ``~/PiFinder_data/indi_disable_alignment.yml``, merge them.
2. Attempt to connect to the INDI server.
3. For each configured driver, check whether the target device is present
   and whether its alignment property indicates the subsystem is active.
4. If active, show a warning on the PiFinder screen.
5. If disable commands are configured for that driver, send them and log the
   result.
6. Write a JSON status file that the web server can read.
"""

import difflib
import json
import logging
import re
import socket
import threading
import time
import xml.etree.ElementTree as ET
from copy import deepcopy
from pathlib import Path
from typing import Any, Optional

import yaml

from PiFinder import utils

logger = logging.getLogger("INDI.Alignment")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
# pifinder_dir = python/../  (repo root when running from python/)
_PIFINDER_DIR = Path("..").resolve()
REPO_CONFIG_PATH: Path = _PIFINDER_DIR / "indi_disable_alignment.yml"
USER_CONFIG_PATH: Path = utils.data_dir / "indi_disable_alignment.yml"
STATUS_FILE_PATH: Path = utils.data_dir / "indi_alignment_status.json"


# ---------------------------------------------------------------------------
# Minimal INDI XML client
# ---------------------------------------------------------------------------

class _INDIClient:
    """
    Bare-minimum INDI XML-over-TCP client sufficient for reading properties
    and sending switch commands.

    The INDI protocol sends a *stream* of sibling XML elements (not a valid
    XML document).  We wrap received data in a synthetic root element before
    parsing; incomplete trailing elements are silently discarded.
    """

    def __init__(self, host: str, port: int, connect_timeout: float, read_timeout: float):
        self.host = host
        self.port = port
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self._sock: Optional[socket.socket] = None

    # ------------------------------------------------------------------
    def connect(self) -> bool:
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.settimeout(self.connect_timeout)
            self._sock.connect((self.host, self.port))
            logger.info("Connected to INDI server at %s:%d", self.host, self.port)
            return True
        except (ConnectionRefusedError, OSError, socket.timeout) as exc:
            logger.debug("INDI connection failed: %s", exc)
            self._sock = None
            return False

    def disconnect(self) -> None:
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    @property
    def is_connected(self) -> bool:
        return self._sock is not None

    # ------------------------------------------------------------------
    def _send(self, data: str) -> bool:
        if not self._sock:
            return False
        try:
            self._sock.sendall(data.encode("utf-8"))
            return True
        except OSError as exc:
            logger.error("INDI send error: %s", exc)
            self.disconnect()
            return False

    def _read(self, timeout: float) -> str:
        """Read bytes until *timeout* seconds of silence."""
        if not self._sock:
            return ""
        self._sock.settimeout(0.3)
        buf = b""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                chunk = self._sock.recv(16384)
                if not chunk:
                    break
                buf += chunk
            except socket.timeout:
                if buf:
                    break  # data arrived, silence now — stop
        return buf.decode("utf-8", errors="replace")

    # ------------------------------------------------------------------
    def get_all_properties(self) -> dict[str, dict[str, Any]]:
        """
        Request all INDI properties and return a nested dict:
        ``{ device_name: { property_name: { element_name: value, ... } } }``
        """
        if not self._send('<getProperties version="1.7"/>\n'):
            return {}
        raw = self._read(self.read_timeout)
        return self._parse_xml_stream(raw)

    def get_devices(self) -> list[str]:
        """Return list of INDI device names currently visible."""
        props = self.get_all_properties()
        return list(props.keys())

    def set_switch(self, device: str, prop: str, element: str, value: str) -> bool:
        """
        Send a newSwitchVector command.
        *value* should be ``"On"`` or ``"Off"``.
        """
        cmd = (
            f'<newSwitchVector device="{device}" name="{prop}">'
            f'<oneSwitch name="{element}">{value}</oneSwitch>'
            f'</newSwitchVector>\n'
        )
        logger.debug("INDI set_switch: device=%s prop=%s element=%s value=%s",
                     device, prop, element, value)
        if not self._send(cmd):
            return False
        # Give driver time to apply the change and drain any response
        time.sleep(0.4)
        self._read(0.8)
        return True

    # ------------------------------------------------------------------
    @staticmethod
    def _parse_xml_stream(data: str) -> dict[str, dict[str, Any]]:
        """
        Parse a stream of INDI XML sibling elements into a device property dict.
        Wraps the data in a root element to make it parseable by ElementTree.
        Silently ignores malformed trailing fragments.
        """
        devices: dict[str, dict[str, Any]] = {}

        # Strip any XML declaration or processing instructions that break parsing
        data = re.sub(r'<\?[^?]*\?>', '', data)

        # The stream may end mid-element; truncate to last complete closing tag.
        last_close = data.rfind('>')
        if last_close >= 0:
            data = data[: last_close + 1]

        wrapped = f"<root>{data}</root>"
        try:
            root = ET.fromstring(wrapped)
        except ET.ParseError as exc:
            logger.debug("INDI XML parse error (partial data expected): %s", exc)
            # Fall back: extract switch states with a regex
            return _INDIClient._parse_xml_regex(data)

        for elem in root:
            device = elem.get("device")
            name = elem.get("name")
            if not device or not name:
                continue
            if device not in devices:
                devices[device] = {}

            # We care primarily about switch vectors
            if "SwitchVector" in elem.tag:
                elements: dict[str, str] = {}
                for child in elem:
                    child_name = child.get("name")
                    if child_name:
                        raw = (child.text or "").strip()
                        elements[child_name] = raw if raw else "Off"
                devices[device][name] = elements

        return devices

    @staticmethod
    def _parse_xml_regex(data: str) -> dict[str, dict[str, Any]]:
        """Fallback regex-based extraction of switch vector states."""
        devices: dict[str, dict[str, Any]] = {}
        vec_pat = re.compile(
            r'<(?:def|set)SwitchVector\s[^>]*device="([^"]+)"[^>]*name="([^"]+)"[^>]*>'
            r'(.*?)</(?:def|set)SwitchVector>',
            re.DOTALL,
        )
        sw_pat = re.compile(r'<(?:def|one)Switch\s[^>]*name="([^"]+)"[^>]*>(.*?)</(?:def|one)Switch>', re.DOTALL)
        for m in vec_pat.finditer(data):
            device, prop, body = m.group(1), m.group(2), m.group(3)
            if device not in devices:
                devices[device] = {}
            elements: dict[str, str] = {}
            for sm in sw_pat.finditer(body):
                elem_name = sm.group(1)
                val = sm.group(2).strip() or "Off"
                elements[elem_name] = val
            devices[device][prop] = elements
        return devices


# ---------------------------------------------------------------------------
# Config loading and merging
# ---------------------------------------------------------------------------

def _load_yaml_safe(path: Path) -> Optional[dict]:
    """Load a YAML file, returning None on any error."""
    try:
        with open(path, "r") as fh:
            return yaml.safe_load(fh) or {}
    except FileNotFoundError:
        return None
    except Exception as exc:
        logger.error("Failed to read YAML %s: %s", path, exc)
        return None


def load_merged_config() -> dict:
    """
    Load repo config and user override, merge them, return merged dict.

    Merge rules for each driver key:
    - Key in user file + non-empty disable_commands  → user list replaces repo
    - Key in user file + empty disable_commands: []  → detect only, no disable
    - Key absent from user file                      → repo defaults unchanged
    """
    repo_cfg = _load_yaml_safe(REPO_CONFIG_PATH)
    if not repo_cfg:
        logger.warning("In-repo config %s not found or empty; alignment detection disabled", REPO_CONFIG_PATH)
        repo_cfg = {"indi": {}, "drivers": {}}

    user_cfg = _load_yaml_safe(USER_CONFIG_PATH)
    if user_cfg is None:
        logger.info("No user override at %s; using repo defaults", USER_CONFIG_PATH)
        return deepcopy(repo_cfg)

    merged = deepcopy(repo_cfg)
    user_drivers = user_cfg.get("drivers", {}) or {}

    for key, user_driver in user_drivers.items():
        if user_driver is None:
            user_driver = {}
        if key not in merged.setdefault("drivers", {}):
            # New driver only in user file — add it
            merged["drivers"][key] = deepcopy(user_driver)
            logger.info("User config adds new driver: %s", key)
            continue

        repo_driver = merged["drivers"][key]

        if "disable_commands" in user_driver:
            if user_driver["disable_commands"] == [] or user_driver["disable_commands"] is None:
                # Explicit empty list → detect only, remove disable commands
                repo_driver["disable_commands"] = []
                logger.info(
                    "User config clears disable_commands for driver '%s'; "
                    "alignment will be detected but NOT disabled",
                    key,
                )
            else:
                repo_driver["disable_commands"] = deepcopy(user_driver["disable_commands"])
                logger.info("User config overrides disable_commands for driver '%s'", key)

        # Override any other scalar/list fields the user specified
        for field in ("device_name", "description", "detect_property",
                      "detect_element", "detect_active_value"):
            if field in user_driver:
                repo_driver[field] = user_driver[field]

    # Merge indi connection settings if user specified them
    if "indi" in user_cfg:
        merged.setdefault("indi", {}).update(user_cfg["indi"])

    return merged


# ---------------------------------------------------------------------------
# Status persistence
# ---------------------------------------------------------------------------

def _save_status(status: dict) -> None:
    try:
        STATUS_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(STATUS_FILE_PATH, "w") as fh:
            json.dump(status, fh, indent=2, default=str)
    except OSError as exc:
        logger.error("Failed to write INDI alignment status to %s: %s", STATUS_FILE_PATH, exc)


def read_status() -> dict:
    """Read the last-saved alignment status (used by web server)."""
    try:
        with open(STATUS_FILE_PATH, "r") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {"state": "not_started"}
    except Exception as exc:
        logger.error("Failed to read INDI alignment status: %s", exc)
        return {"state": "error", "error": str(exc)}


# ---------------------------------------------------------------------------
# Core alignment check
# ---------------------------------------------------------------------------

class INDIAlignmentManager:
    """
    Checks for active INDI alignment subsystems and optionally disables them.
    Intended to run once (with retries) as a background daemon thread.
    """

    def __init__(self):
        self.config: dict = {}
        self.status: dict = {
            "state": "initialising",
            "indi_connected": False,
            "indi_host": "localhost",
            "indi_port": 7624,
            "timestamp": None,
            "devices": [],
            "drivers": {},
            "errors": [],
        }

    # ------------------------------------------------------------------
    def load_config(self) -> None:
        self.config = load_merged_config()
        indi_cfg = self.config.get("indi", {})
        self.status["indi_host"] = indi_cfg.get("host", "localhost")
        self.status["indi_port"] = indi_cfg.get("port", 7624)

    # ------------------------------------------------------------------
    def run(self, console_queue=None, menu_manager=None) -> None:
        """
        Entry point for the background daemon thread.
        Retries until INDI is available or max_retries is exceeded.
        """
        self.load_config()
        indi_cfg = self.config.get("indi", {})
        host = indi_cfg.get("host", "localhost")
        port = int(indi_cfg.get("port", 7624))
        connect_timeout = float(indi_cfg.get("connect_timeout", 5.0))
        read_timeout = float(indi_cfg.get("read_timeout", 3.0))
        retry_interval = float(indi_cfg.get("retry_interval", 30.0))
        max_retries = int(indi_cfg.get("max_retries", 10))

        attempt = 0
        while attempt < max_retries:
            attempt += 1
            logger.info("INDI alignment check attempt %d/%d", attempt, max_retries)

            client = _INDIClient(host, port, connect_timeout, read_timeout)
            if not client.connect():
                logger.info("INDI server not available (attempt %d); retrying in %.0fs",
                            attempt, retry_interval)
                self.status["state"] = "waiting_for_indi"
                self.status["indi_connected"] = False
                _save_status(self.status)
                time.sleep(retry_interval)
                continue

            try:
                self._do_check(client, console_queue, menu_manager)
            except Exception as exc:
                msg = f"Unexpected error during INDI alignment check: {exc}"
                logger.exception(msg)
                self.status["errors"].append(msg)
                self.status["state"] = "error"
            finally:
                client.disconnect()

            # Check is complete (success or persistent error) — stop retrying
            _save_status(self.status)
            return

        # Exhausted retries
        logger.warning("INDI server not reachable after %d attempts; giving up", max_retries)
        self.status["state"] = "indi_unavailable"
        _save_status(self.status)

    # ------------------------------------------------------------------
    def _do_check(self, client: _INDIClient, console_queue, menu_manager) -> None:
        logger.info("Fetching INDI properties …")
        all_props = client.get_all_properties()

        self.status["indi_connected"] = True
        self.status["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        self.status["devices"] = list(all_props.keys())
        self.status["state"] = "checked"

        if not all_props:
            logger.info("No INDI devices visible")
            self.status["state"] = "no_devices"
            return

        logger.info("INDI devices: %s", self.status["devices"])

        drivers_cfg = self.config.get("drivers", {})
        driver_results: dict[str, dict] = {}

        for key, drv in drivers_cfg.items():
            device_name = drv.get("device_name", "")
            detect_prop = drv.get("detect_property", "")
            detect_elem = drv.get("detect_element", "")
            detect_active = drv.get("detect_active_value", "On")
            disable_commands = drv.get("disable_commands") or []

            result: dict[str, Any] = {
                "description": drv.get("description", key),
                "device_name": device_name,
                "device_found": device_name in all_props,
                "alignment_detected": False,
                "alignment_active": False,
                "will_disable": bool(disable_commands),
                "disabled": False,
                "commands_sent": [],
                "errors": [],
            }

            if not result["device_found"]:
                logger.debug("Driver '%s': device '%s' not present", key, device_name)
                driver_results[key] = result
                continue

            result["alignment_detected"] = True
            dev_props = all_props.get(device_name, {})
            prop_data = dev_props.get(detect_prop)

            if prop_data is None:
                logger.debug(
                    "Driver '%s': property '%s' not found on device '%s'",
                    key, detect_prop, device_name,
                )
                result["alignment_detected"] = False
                driver_results[key] = result
                continue

            current_val = prop_data.get(detect_elem, "")
            is_active = (current_val.strip().lower() == detect_active.strip().lower())
            result["alignment_active"] = is_active

            if not is_active:
                logger.info("Driver '%s' (%s): alignment is already inactive", key, device_name)
                driver_results[key] = result
                continue

            # --- Alignment is ACTIVE ---
            logger.warning(
                "INDI alignment subsystem ACTIVE on '%s' (%s)!",
                device_name, drv.get("description", key),
            )

            if disable_commands:
                _msg = f"INDI: Disabling alignment on {device_name}"
            else:
                _msg = f"INDI: Alignment active on {device_name} — NOT disabled (per config)"

            self._send_screen_warning(console_queue, menu_manager, _msg, is_active, bool(disable_commands))

            if not disable_commands:
                logger.warning(
                    "No disable_commands for driver '%s'; alignment remains active", key
                )
                driver_results[key] = result
                continue

            # Send each disable command
            all_ok = True
            for cmd in disable_commands:
                if cmd.get("type") != "switch":
                    logger.error("Unknown command type '%s' for driver '%s'", cmd.get("type"), key)
                    result["errors"].append(f"Unknown command type: {cmd.get('type')}")
                    all_ok = False
                    continue

                prop = cmd.get("property", "")
                elem = cmd.get("element", "")
                val = cmd.get("value", "Off")

                logger.info(
                    "Sending: device=%s prop=%s element=%s value=%s",
                    device_name, prop, elem, val,
                )
                ok = client.set_switch(device_name, prop, elem, val)
                cmd_record = {
                    "property": prop,
                    "element": elem,
                    "value": val,
                    "success": ok,
                }
                result["commands_sent"].append(cmd_record)

                if ok:
                    logger.info("  → success")
                else:
                    msg = f"Failed to set {device_name}.{prop}.{elem}={val}"
                    logger.error("  → FAILED: %s", msg)
                    result["errors"].append(msg)
                    all_ok = False

            result["disabled"] = all_ok and bool(disable_commands)
            if result["disabled"]:
                logger.info("Alignment disabled successfully on '%s'", device_name)
            else:
                logger.error("Alignment disable INCOMPLETE on '%s'", device_name)

            driver_results[key] = result

        self.status["drivers"] = driver_results

        # Summary log
        active_count = sum(1 for r in driver_results.values() if r.get("alignment_active"))
        disabled_count = sum(1 for r in driver_results.values() if r.get("disabled"))
        if active_count == 0:
            logger.info("INDI alignment check complete: no active alignment subsystems found")
        else:
            logger.warning(
                "INDI alignment check complete: %d active, %d disabled",
                active_count, disabled_count,
            )

    # ------------------------------------------------------------------
    @staticmethod
    def _send_screen_warning(console_queue, menu_manager, message: str,
                              is_active: bool, will_disable: bool) -> None:
        """Push a warning to the PiFinder console/screen."""
        if console_queue:
            try:
                console_queue.put_nowait(message)
            except Exception:
                pass
        if menu_manager:
            timeout = 5 if will_disable else 8
            try:
                menu_manager.message(message, timeout)
            except Exception:
                pass
        logger.warning("SCREEN WARNING: %s", message)


# ---------------------------------------------------------------------------
# Thread helper
# ---------------------------------------------------------------------------

def start_alignment_monitor(console_queue=None, menu_manager=None) -> threading.Thread:
    """
    Start the alignment check as a background daemon thread and return it.
    Call from ``main.py`` after the UI is ready.
    """
    manager = INDIAlignmentManager()
    t = threading.Thread(
        target=manager.run,
        args=(console_queue, menu_manager),
        name="INDIAlignmentMonitor",
        daemon=True,
    )
    t.start()
    logger.info("INDI alignment monitor thread started")
    return t


# ---------------------------------------------------------------------------
# Utility functions for web server
# ---------------------------------------------------------------------------

def get_repo_config_path() -> Path:
    return REPO_CONFIG_PATH


def get_user_config_path() -> Path:
    return USER_CONFIG_PATH


def get_repo_config_text() -> str:
    """Return raw text of the in-repo YAML (for diff display)."""
    try:
        return REPO_CONFIG_PATH.read_text()
    except OSError:
        return ""


def get_user_config_text() -> str:
    """Return raw text of the user YAML, or empty string if absent."""
    try:
        return USER_CONFIG_PATH.read_text()
    except FileNotFoundError:
        return ""
    except OSError as exc:
        logger.error("Cannot read user config %s: %s", USER_CONFIG_PATH, exc)
        return ""


def diff_configs() -> list[str]:
    """
    Return unified diff lines between repo config and user config.
    Empty list means files are identical or user file does not exist.
    """
    repo_text = get_repo_config_text()
    user_text = get_user_config_text()
    if not user_text:
        return []
    diff = list(difflib.unified_diff(
        repo_text.splitlines(keepends=True),
        user_text.splitlines(keepends=True),
        fromfile="repo/indi_disable_alignment.yml",
        tofile="~/PiFinder_data/indi_disable_alignment.yml",
    ))
    return diff


def copy_repo_config_to_user() -> tuple[bool, str]:
    """
    Copy the in-repo YAML to ~/PiFinder_data/indi_disable_alignment.yml.
    Returns (success, message).
    """
    repo_text = get_repo_config_text()
    if not repo_text:
        return False, f"Repository config not found at {REPO_CONFIG_PATH}"
    try:
        USER_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        USER_CONFIG_PATH.write_text(repo_text)
        logger.info("Copied repo YAML to %s", USER_CONFIG_PATH)
        return True, f"Copied to {USER_CONFIG_PATH}"
    except OSError as exc:
        msg = f"Failed to copy config: {exc}"
        logger.error(msg)
        return False, msg
