#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
BRANCH-ONLY (battery-runtime-test): battery runtime-test telemetry.

Appends one CSV row per battery poll to a per-boot run directory under
``~/PiFinder_data/battery_runtime/``, alongside a ``run_metadata.json``
describing the device and the pinned typical-load profile. Used by the
bench discharge campaign that calibrates the state-of-charge curve —
see docs/adr/0020-soc-as-runtime-fraction.md.

The run ends with a hard power cut (the SYS boost drops out), and the
last rows are the most valuable — they record the cutoff voltage that
anchors 0% — so every row is flushed AND fsync'd. At the 5 s poll
cadence the write load is trivial.

Analysis notes (consumed by tools/battery_runtime_analysis.py):
* the discharge clock starts where ``on_external_power`` flips
  True→False (cable pull), or at the first row if never external;
* ``solve_attempt_age_s`` staying small proves the capture+solve load
  ran for the whole discharge — a growing age means a poisoned run.
"""

import json
import logging
import os
import platform
import socket
import time

from PiFinder import utils
from PiFinder.types.hardware import BatteryState

logger = logging.getLogger("Battery.telemetry")

# Pinned typical-load profile, recorded in run_metadata.json. These must
# match the branch's hardcoded overrides (camera_interface / main.py).
PINNED_PROFILE = {
    "camera_exposure_us": 400000,
    "camera_gain": 20,
    "display_brightness": 255,
    "display_sleep": "forced off",
    "camera_mode": "real capture discarded; solver fed test_images/pifinder_debug_02.png",
}

CSV_COLUMNS = [
    "time_iso",
    "epoch_s",
    "monotonic_s",
    "battery_voltage_v",
    "charge_status",
    "on_external_power",
    "soc_pct",  # published estimate (blank while charging)
    "soc_raw_pct",  # estimate_soc(voltage) regardless of charge state
    "charge_current_ma",
    "vbus_voltage_v",
    "sys_voltage_v",
    "cpu_temp_c",
    "load_1min",
    "throttled_hex",
    "solve_attempt_age_s",
    "solve_matches",
    "solve_source",
    # Appended after the first campaign (older CSVs lack it): per-frame IMU
    # pointing delta from the camera metadata, to quantify the bench
    # pseudo-motion that blanked the substituted image in the first runs.
    "imu_delta_deg",
]


def _pi_serial() -> str:
    """Pi serial from /proc/cpuinfo — hostnames are all 'pifinder', the
    serial is what actually distinguishes test devices."""
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("Serial"):
                    return line.split(":")[1].strip()
    except OSError:
        pass
    return "unknown"


def _cpu_temp_c():
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return round(int(f.read().strip()) / 1000.0, 1)
    except (OSError, ValueError):
        return ""


def _load_1min():
    try:
        return round(os.getloadavg()[0], 2)
    except OSError:
        return ""


def _throttled_hex():
    """RPi firmware throttle flags (under-voltage / freq-capped bits)."""
    try:
        with open("/sys/devices/platform/soc/soc:firmware/get_throttled") as f:
            return f.read().strip()
    except OSError:
        return ""


def _sw_version() -> str:
    try:
        return (utils.pifinder_dir / "version.txt").read_text().strip()
    except OSError:
        return "unknown"


class TelemetryLogger:
    """One instance per battery-monitor process; one run dir per boot."""

    def __init__(self, shared_state, source: str):
        self._shared_state = shared_state
        self._start_monotonic = time.monotonic()

        stamp = time.strftime("%Y%m%d_%H%M%S")
        serial = _pi_serial()
        self.run_dir = utils.data_dir / "battery_runtime" / f"run_{serial}_{stamp}"
        self.run_dir.mkdir(parents=True, exist_ok=True)

        metadata = {
            "serial": serial,
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "sw_version": _sw_version(),
            "battery_source": source,  # "bq25895" or "fake"
            "start_time_iso": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "pinned_profile": PINNED_PROFILE,
            "notes": "battery-runtime-test branch; see docs/adr/0020-soc-as-runtime-fraction.md",
        }
        with open(self.run_dir / "run_metadata.json", "w") as f:
            json.dump(metadata, f, indent=2)
            f.flush()
            os.fsync(f.fileno())

        self._csv = open(self.run_dir / "telemetry.csv", "a")
        self._csv.write(",".join(CSV_COLUMNS) + "\n")
        self._durable_flush()
        logger.warning("Battery runtime telemetry -> %s", self.run_dir)

    def _durable_flush(self):
        self._csv.flush()
        os.fsync(self._csv.fileno())

    def _solver_fields(self):
        """(solve_attempt_age_s, matches, source) from shared state; blanks
        if no solution has been published yet."""
        try:
            solution = self._shared_state.solution()
        except Exception:
            return "", "", ""
        if solution is None:
            return "", "", ""
        attempt = getattr(solution, "last_solve_attempt", None)
        age = round(time.time() - attempt, 1) if attempt else ""
        diagnostics = getattr(solution, "diagnostics", None)
        matches = getattr(diagnostics, "Matches", "") if diagnostics else ""
        source = getattr(solution, "solve_source", "")
        return age, matches, str(source)

    def _imu_delta_deg(self):
        try:
            metadata = self._shared_state.last_image_metadata()
            return round(float(metadata["imu_delta"]), 3)
        except Exception:
            return ""

    def log(self, state: BatteryState, soc_raw_pct: int):
        solve_age, matches, solve_source = self._solver_fields()
        row = [
            time.strftime("%Y-%m-%dT%H:%M:%S"),
            round(time.time(), 1),
            round(time.monotonic() - self._start_monotonic, 1),
            round(state.battery_voltage, 3),
            state.charge_status.name,
            int(state.on_external_power),
            "" if state.state_of_charge_pct is None else state.state_of_charge_pct,
            soc_raw_pct,
            round(state.charge_current_ma, 1),
            round(state.vbus_voltage, 2),
            round(state.sys_voltage, 3),
            _cpu_temp_c(),
            _load_1min(),
            _throttled_hex(),
            solve_age,
            matches,
            solve_source,
            self._imu_delta_deg(),
        ]
        try:
            self._csv.write(",".join(str(v) for v in row) + "\n")
            self._durable_flush()
        except OSError as e:
            # Never let telemetry kill the battery monitor.
            logger.error("Telemetry write failed: %s", e)
