#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Privileged helper for time-source disciplined system clock and RTC updates.

PiFinder itself runs as the normal PiFinder user and writes a constrained JSON
request. This helper is intended to run as root under systemd and performs only
the requested clock operations after validating the request.
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Optional

from PiFinder.gps_time_sync import (
    HELPER_STATUS_FILE,
    REQUEST_FILE,
    _read_boot_id,
    _utc_datetime,
)
from PiFinder import utils


logger = logging.getLogger("GPS.TimeSync.Helper")


class ClockCommandRunner:
    command_timeout_seconds = 10

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run

    def _run(self, command: list[str]) -> dict[str, Any]:
        if self.dry_run:
            return {"ok": True, "message": "dry run: " + " ".join(command)}

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                check=False,
                text=True,
                timeout=self.command_timeout_seconds,
            )
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

        output = (result.stdout + result.stderr).strip()
        if result.returncode == 0:
            return {"ok": True, "message": output or "command completed"}
        return {
            "ok": False,
            "message": output or f"command exited with {result.returncode}",
        }

    def set_system_clock(self, gps_dt: datetime.datetime) -> dict[str, Any]:
        gps_dt = _utc_datetime(gps_dt)
        return self._run(["/usr/bin/date", "-u", "--set", f"@{gps_dt.timestamp():.6f}"])

    def set_rtc(self, gps_dt: datetime.datetime) -> dict[str, Any]:
        gps_dt = _utc_datetime(gps_dt)
        rtc_date = gps_dt.strftime("%Y-%m-%d %H:%M:%S UTC")
        return self._run(["/usr/sbin/hwclock", "--utc", "--set", "--date", rtc_date])


class GpsTimeSyncHelper:
    def __init__(
        self,
        request_file: Path = REQUEST_FILE,
        status_file: Path = HELPER_STATUS_FILE,
        max_request_age_seconds: float = 120.0,
        poll_interval_seconds: float = 1.0,
        runner: Optional[ClockCommandRunner] = None,
        time_fn: Callable[[], float] = time.time,
        monotonic_fn: Callable[[], float] = time.monotonic,
        boot_id_fn: Callable[[], str] = _read_boot_id,
    ):
        self.request_file = request_file
        self.status_file = status_file
        self.max_request_age_seconds = max(1.0, max_request_age_seconds)
        self.poll_interval_seconds = max(0.1, poll_interval_seconds)
        self.runner = runner or ClockCommandRunner()
        self.time_fn = time_fn
        self.monotonic_fn = monotonic_fn
        self.boot_id_fn = boot_id_fn
        self.last_processed_request_id = self._last_processed_request_id()

    def _read_json_file(self, path: Path) -> Optional[dict[str, Any]]:
        try:
            with open(path, "r", encoding="utf-8") as file_in:
                payload = json.load(file_in)
        except FileNotFoundError:
            return None
        if not isinstance(payload, dict):
            raise ValueError(f"{path} does not contain a JSON object")
        return payload

    def _last_processed_request_id(self) -> Optional[str]:
        try:
            status = self._read_json_file(self.status_file)
        except Exception:
            return None
        if not status:
            return None
        request_id = status.get("last_request_id")
        return str(request_id) if request_id else None

    def _write_status(self, payload: dict[str, Any]) -> None:
        status = {
            "state": payload.get("state", "unknown"),
            "message": payload.get("message", ""),
            "updated_unix": self.time_fn(),
            "updated_monotonic": self.monotonic_fn(),
            "effective_uid": os.geteuid(),
            "request_file": str(self.request_file),
        }
        status.update(payload)

        utils.create_path(self.status_file.parent)
        tmp_file = self.status_file.with_name(self.status_file.name + ".tmp")
        with open(tmp_file, "w", encoding="utf-8") as status_out:
            json.dump(status, status_out, indent=2, sort_keys=True)
        tmp_file.replace(self.status_file)

    def _validate_request(self, request: dict[str, Any]) -> tuple[dict[str, Any], str]:
        if request.get("version") != 1:
            raise ValueError("unsupported request version")

        request_id = str(request.get("request_id") or "")
        if not request_id:
            raise ValueError("request_id is missing")

        if request_id == self.last_processed_request_id:
            return {}, "already_processed"

        boot_id = str(request.get("boot_id") or "")
        if boot_id != self.boot_id_fn():
            raise ValueError("request was created during a different boot")

        created_monotonic = float(request.get("created_monotonic"))
        age = self.monotonic_fn() - created_monotonic
        if age < 0:
            raise ValueError("request monotonic timestamp is in the future")
        if age > self.max_request_age_seconds:
            raise ValueError(
                f"request is stale: {age:.1f}s > {self.max_request_age_seconds:.1f}s"
            )

        if request.get("monitor_state") != "stable":
            raise ValueError("request monitor_state is not stable")

        selected = request.get("selected")
        if not isinstance(selected, dict):
            selected = request.get("latest")
        if not isinstance(selected, dict) or selected.get("valid") is not True:
            raise ValueError("request selected time source is not valid")

        actions = request.get("actions")
        if not isinstance(actions, dict) or not actions:
            raise ValueError("request contains no actions")

        sync_time = request.get("sync_time", request.get("gps_time"))
        if not isinstance(sync_time, str):
            raise ValueError("sync_time is missing")
        try:
            sync_dt = _utc_datetime(datetime.datetime.fromisoformat(sync_time))
        except ValueError as exc:
            raise ValueError("sync_time is invalid") from exc

        return {
            "request_id": request_id,
            "sync_dt": sync_dt,
            "selected": selected,
            "actions": actions,
            "age_seconds": age,
        }, "ready"

    def _process_system_clock(
        self, gps_dt: datetime.datetime, action: dict[str, Any]
    ) -> dict[str, Any]:
        threshold = float(action.get("step_threshold_seconds", 0.5))
        offset_seconds = gps_dt.timestamp() - self.time_fn()
        if abs(offset_seconds) <= threshold:
            return {
                "state": "in_sync",
                "message": "System clock offset is within threshold",
                "offset_seconds": offset_seconds,
            }

        result = self.runner.set_system_clock(gps_dt)
        return {
            "state": "synced" if result.get("ok") else "error",
            "message": str(result.get("message") or ""),
            "offset_seconds": offset_seconds,
        }

    def _process_rtc(
        self, gps_dt: datetime.datetime, action: dict[str, Any]
    ) -> dict[str, Any]:
        del action
        result = self.runner.set_rtc(gps_dt)
        return {
            "state": "synced" if result.get("ok") else "error",
            "message": str(result.get("message") or ""),
        }

    def process_once(self) -> dict[str, Any]:
        try:
            request = self._read_json_file(self.request_file)
            if request is None:
                status = {"state": "idle", "message": "No sync request"}
                self._write_status(status)
                return status

            parsed, request_state = self._validate_request(request)
            if request_state == "already_processed":
                status = {
                    "state": "idle",
                    "message": "Request already processed",
                    "last_request_id": self.last_processed_request_id,
                }
                return status
        except Exception as exc:
            status = {"state": "invalid_request", "message": str(exc)}
            self._write_status(status)
            return status

        sync_dt = parsed["sync_dt"]
        actions = parsed["actions"]
        results = {}

        if actions.get("system_clock", {}).get("enabled"):
            results["system_clock"] = self._process_system_clock(
                sync_dt, actions["system_clock"]
            )
        if actions.get("rtc", {}).get("enabled"):
            results["rtc"] = self._process_rtc(sync_dt, actions["rtc"])

        result_states = [result.get("state") for result in results.values()]
        if any(state == "error" for state in result_states):
            state = "partial_error" if any(state != "error" for state in result_states) else "error"
        elif results:
            state = "completed"
        else:
            state = "skipped"

        self.last_processed_request_id = parsed["request_id"]
        status = {
            "state": state,
            "message": "Time sync request processed",
            "last_request_id": parsed["request_id"],
            "last_sync_time": sync_dt.isoformat(),
            "last_gps_time": sync_dt.isoformat(),
            "selected": parsed["selected"],
            "request_age_seconds": parsed["age_seconds"],
            "results": results,
        }
        self._write_status(status)
        return status

    def run_forever(self) -> None:
        self._write_status({"state": "idle", "message": "Helper started"})
        while True:
            try:
                self.process_once()
            except Exception:
                logger.exception("Unexpected time sync helper error")
            time.sleep(self.poll_interval_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Process one request and exit")
    parser.add_argument("--dry-run", action="store_true", help="Log commands without running them")
    parser.add_argument("--interval", type=float, default=1.0, help="Polling interval in seconds")
    parser.add_argument("--max-age", type=float, default=120.0, help="Maximum request age in seconds")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    helper = GpsTimeSyncHelper(
        max_request_age_seconds=args.max_age,
        poll_interval_seconds=args.interval,
        runner=ClockCommandRunner(dry_run=args.dry_run),
    )
    if args.once:
        status = helper.process_once()
        print(json.dumps(status, indent=2, sort_keys=True))
        return
    helper.run_forever()


if __name__ == "__main__":
    main()
