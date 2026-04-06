"""
INDI Alignment Subsystem Manager
---------------------------------
Detects and optionally disables the INDI alignment subsystem on connected
telescope mounts that would otherwise interfere with PiFinder's own
plate-solve–based pointing corrections.

This module is called from ``mountcontrol_indi`` at the end of ``init_mount()``,
using the already-established PyIndi connection.  It runs once at startup —
if users subsequently re-enable alignment via an INDI client, that is their
choice.

Startup flow
~~~~~~~~~~~~
1. Load in-repo ``indi_disable_alignment.yml`` and user-override
   ``~/PiFinder_data/indi_disable_alignment.yml``, merge them.
2. Receive the connected ``PiFinderIndiClient`` and the telescope device.
3. For each configured driver, check whether the device name matches and
   whether its alignment property indicates the subsystem is active.
4. If active, send a warning to the console queue (shown on PiFinder screen).
5. If disable commands are configured, send them via the existing PyIndi
   client and log each result.
6. Write a JSON status file that the web server can read.
"""

import difflib
import json
import logging
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Optional

import yaml

from PiFinder import utils

logger = logging.getLogger("INDI.Alignment")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
# When the app runs from python/, ".." resolves to the PiFinder repo root.
_PIFINDER_DIR = Path("..").resolve()
REPO_CONFIG_PATH: Path = _PIFINDER_DIR / "indi_disable_alignment.yml"
USER_CONFIG_PATH: Path = utils.data_dir / "indi_disable_alignment.yml"
STATUS_FILE_PATH: Path = utils.data_dir / "mountcontrol_alignment_status.json"


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
    - Key in user file + empty ``disable_commands: []`` → detect only, no disable
    - Key absent from user file                      → repo defaults unchanged
    """
    repo_cfg = _load_yaml_safe(REPO_CONFIG_PATH)
    if not repo_cfg:
        logger.warning(
            "In-repo config %s not found or empty; alignment detection disabled",
            REPO_CONFIG_PATH,
        )
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
            merged["drivers"][key] = deepcopy(user_driver)
            logger.info("User config adds new driver: %s", key)
            continue

        repo_driver = merged["drivers"][key]

        if "disable_commands" in user_driver:
            cmds = user_driver["disable_commands"]
            if cmds == [] or cmds is None:
                repo_driver["disable_commands"] = []
                logger.info(
                    "User config clears disable_commands for driver '%s'; "
                    "alignment will be detected but NOT disabled",
                    key,
                )
            else:
                repo_driver["disable_commands"] = deepcopy(cmds)
                logger.info(
                    "User config overrides disable_commands for driver '%s'", key
                )

        for field in (
            "device_name",
            "description",
            "detect_property",
            "detect_element",
            "detect_active_value",
        ):
            if field in user_driver:
                repo_driver[field] = user_driver[field]

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
        logger.error(
            "Failed to write INDI alignment status to %s: %s", STATUS_FILE_PATH, exc
        )


def read_status() -> dict:
    """Read the last-saved alignment status (used by the web server)."""
    try:
        with open(STATUS_FILE_PATH, "r") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {"state": "not_started"}
    except Exception as exc:
        logger.error("Failed to read INDI alignment status: %s", exc)
        return {"state": "error", "error": str(exc)}


# ---------------------------------------------------------------------------
# PyIndi helpers
# ---------------------------------------------------------------------------

def _get_switch_value(device, prop_name: str, elem_name: str) -> Optional[str]:
    """
    Read a single switch element from a PyIndi device.
    Returns ``"On"``, ``"Off"``, or ``None`` if the property/element is absent.
    """
    try:
        import PyIndi

        switch_prop = device.getSwitch(prop_name)
        if not switch_prop:
            return None
        for i in range(len(switch_prop)):
            if switch_prop[i].name == elem_name:
                return "On" if switch_prop[i].s == PyIndi.ISS_ON else "Off"
    except Exception as exc:
        logger.debug("Error reading switch %s.%s: %s", prop_name, elem_name, exc)
    return None


def _apply_switch_command(
    client, device, prop_name: str, elem_name: str, value: str
) -> bool:
    """
    Send a switch command via the existing PiFinderIndiClient.

    - ``value="On"``  → ``client.set_switch(device, prop_name, elem_name)``
      (sets *elem_name* ON, all others OFF)
    - ``value="Off"`` → ``client.set_switch_off(device, prop_name)``
      (sets all elements OFF)
    """
    if value.lower() == "on":
        return client.set_switch(device, prop_name, elem_name)
    else:
        return client.set_switch_off(device, prop_name)


# ---------------------------------------------------------------------------
# Main entry point (called from mountcontrol_indi.init_mount)
# ---------------------------------------------------------------------------

def check_and_disable_alignment(client, device, console_queue=None) -> None:
    """
    Detect active INDI alignment subsystems on *device* and optionally disable
    them according to the merged YAML configuration.

    Args:
        client:        The connected ``PiFinderIndiClient`` instance.
        device:        The INDI telescope device (``PyIndi.BaseDevice``).
        console_queue: Optional queue for pushing warning strings to the UI.
    """
    config = load_merged_config()
    drivers_cfg = config.get("drivers", {})
    device_name = device.getDeviceName()

    status: dict[str, Any] = {
        "state": "checked",
        "indi_connected": True,
        "indi_host": client.getHost(),
        "indi_port": client.getPort(),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "devices": [device_name],
        "drivers": {},
        "errors": [],
    }

    logger.info("Running alignment check for INDI device '%s'", device_name)

    for key, drv in drivers_cfg.items():
        expected_name = drv.get("device_name", "")
        detect_prop = drv.get("detect_property", "")
        detect_elem = drv.get("detect_element", "")
        detect_active_val = drv.get("detect_active_value", "On")
        disable_commands = drv.get("disable_commands") or []

        result: dict[str, Any] = {
            "description": drv.get("description", key),
            "device_name": expected_name,
            "device_found": device_name == expected_name,
            "alignment_detected": False,
            "alignment_active": False,
            "will_disable": bool(disable_commands),
            "disabled": False,
            "commands_sent": [],
            "errors": [],
        }

        if not result["device_found"]:
            status["drivers"][key] = result
            continue

        # Device matches — wait briefly for the property then check it
        client._wait_for_property(device, detect_prop, timeout=3.0)
        current_val = _get_switch_value(device, detect_prop, detect_elem)

        if current_val is None:
            logger.debug(
                "Driver '%s': property '%s' / element '%s' not found on '%s'",
                key, detect_prop, detect_elem, device_name,
            )
            status["drivers"][key] = result
            continue

        result["alignment_detected"] = True
        is_active = current_val.lower() == detect_active_val.lower()
        result["alignment_active"] = is_active

        if not is_active:
            logger.info(
                "Driver '%s' (%s): alignment subsystem is already inactive",
                key, device_name,
            )
            status["drivers"][key] = result
            continue

        # --- Alignment is ACTIVE ---
        if disable_commands:
            msg = f"INDI: disabling alignment on {device_name}"
        else:
            msg = f"INDI: alignment active on {device_name} — not disabled (per config)"

        logger.warning(
            "INDI alignment subsystem ACTIVE on '%s' (%s)%s",
            device_name,
            drv.get("description", key),
            " — will disable" if disable_commands else " — no disable commands configured",
        )
        _push_console(console_queue, msg)

        if not disable_commands:
            status["drivers"][key] = result
            continue

        # Send each disable command
        all_ok = True
        for cmd in disable_commands:
            if cmd.get("type") != "switch":
                err = f"Unknown command type '{cmd.get('type')}' for driver '{key}'"
                logger.error(err)
                result["errors"].append(err)
                all_ok = False
                continue

            prop = cmd.get("property", "")
            elem = cmd.get("element", "")
            val = cmd.get("value", "Off")

            logger.info(
                "Sending: device=%s prop=%s element=%s value=%s",
                device_name, prop, elem, val,
            )
            ok = _apply_switch_command(client, device, prop, elem, val)
            result["commands_sent"].append(
                {"property": prop, "element": elem, "value": val, "success": ok}
            )
            if ok:
                logger.info("  → success")
            else:
                err = f"Failed to set {device_name}.{prop}.{elem}={val}"
                logger.error("  → FAILED: %s", err)
                result["errors"].append(err)
                status["errors"].append(err)
                all_ok = False

        result["disabled"] = all_ok
        if result["disabled"]:
            logger.info("Alignment disabled successfully on '%s'", device_name)
            _push_console(console_queue, f"INDI: alignment disabled on {device_name}")
        else:
            logger.error("Alignment disable INCOMPLETE on '%s'", device_name)
            _push_console(console_queue, f"INDI: alignment disable FAILED on {device_name}")

        status["drivers"][key] = result

    _save_status(status)
    logger.info("INDI alignment check complete; status written to %s", STATUS_FILE_PATH)


def _push_console(console_queue, message: str) -> None:
    if console_queue is not None:
        try:
            console_queue.put_nowait(message)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Utility functions for the web server
# ---------------------------------------------------------------------------

def get_repo_config_path() -> Path:
    return REPO_CONFIG_PATH


def get_user_config_path() -> Path:
    return USER_CONFIG_PATH


def get_repo_config_text() -> str:
    try:
        return REPO_CONFIG_PATH.read_text()
    except OSError:
        return ""


def get_user_config_text() -> str:
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
    return list(
        difflib.unified_diff(
            repo_text.splitlines(keepends=True),
            user_text.splitlines(keepends=True),
            fromfile="repo/indi_disable_alignment.yml",
            tofile="~/PiFinder_data/indi_disable_alignment.yml",
        )
    )


def copy_repo_config_to_user() -> tuple[bool, str]:
    """
    Copy the in-repo YAML to ``~/PiFinder_data/indi_disable_alignment.yml``.
    Returns ``(success, message)``.
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
