#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
GPS-disciplined time monitor for PiFinder.

Phase 1 is intentionally observational: it evaluates incoming GPS time samples,
tracks offset/jitter against PiFinder's internal time, and writes a compact
status file. It does not change the system clock, RTC, or chrony state.
"""

from __future__ import annotations

import datetime
import json
import logging
import math
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable, Deque, Optional

import pytz

from PiFinder import utils


logger = logging.getLogger("GPS.TimeSync")

STATUS_FILE = utils.data_dir / "gps_time_status.json"
REQUEST_FILE = utils.data_dir / "gps_time_sync_request.json"
HELPER_STATUS_FILE = utils.data_dir / "gps_time_sync_helper_status.json"


def _read_boot_id() -> str:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return "unknown"


class ClockSyncRequestWriter:
    """Write requests for the privileged GPS time-sync helper."""

    def __init__(
        self,
        request_file: Path = REQUEST_FILE,
        boot_id_fn: Callable[[], str] = _read_boot_id,
    ):
        self.request_file = request_file
        self.boot_id_fn = boot_id_fn

    def write_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            utils.create_path(self.request_file.parent)
            payload = dict(payload)
            payload["boot_id"] = self.boot_id_fn()
            tmp_file = self.request_file.with_name(self.request_file.name + ".tmp")
            with open(tmp_file, "w", encoding="utf-8") as request_out:
                json.dump(payload, request_out, indent=2, sort_keys=True)
            tmp_file.replace(self.request_file)
        except Exception as exc:
            return {"ok": False, "message": str(exc)}
        return {"ok": True, "message": f"request written to {self.request_file}"}

    def clear_request(self) -> None:
        try:
            self.request_file.unlink()
        except FileNotFoundError:
            return
        except Exception:
            logger.exception("Could not clear GPS time sync request")


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _utc_datetime(dt: datetime.datetime) -> datetime.datetime:
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        return pytz.timezone("UTC").localize(dt)
    return dt.astimezone(pytz.timezone("UTC"))


class GpsTimeSyncMonitor:
    """Evaluate GPS time quality and optional software PPS ticks."""

    def __init__(
        self,
        enabled: bool = False,
        software_pps_enabled: bool = False,
        system_clock_sync_enabled: bool = False,
        rtc_sync_enabled: bool = False,
        min_samples: int = 5,
        sample_window_seconds: float = 120.0,
        stale_seconds: float = 30.0,
        max_tacc_ns: int = 1_000_000_000,
        stable_jitter_ms: float = 250.0,
        stable_offset_ms: float = 1000.0,
        status_write_interval_seconds: float = 5.0,
        software_pps_interval_seconds: float = 1.0,
        system_clock_sync_min_interval_seconds: float = 300.0,
        system_clock_sync_step_threshold_ms: float = 500.0,
        rtc_sync_min_interval_seconds: float = 3600.0,
        status_file: Path = STATUS_FILE,
        helper_status_file: Path = HELPER_STATUS_FILE,
        time_fn: Callable[[], float] = time.time,
        monotonic_fn: Callable[[], float] = time.monotonic,
        request_writer: Optional[ClockSyncRequestWriter] = None,
    ):
        self.enabled = enabled
        self.software_pps_enabled = software_pps_enabled
        self.system_clock_sync_enabled = system_clock_sync_enabled
        self.rtc_sync_enabled = rtc_sync_enabled
        self.min_samples = max(1, min_samples)
        self.sample_window_seconds = max(1.0, sample_window_seconds)
        self.stale_seconds = max(1.0, stale_seconds)
        self.max_tacc_ns = max_tacc_ns
        self.stable_jitter_seconds = max(0.001, stable_jitter_ms / 1000.0)
        self.stable_offset_seconds = max(0.001, stable_offset_ms / 1000.0)
        self.status_write_interval_seconds = max(0.5, status_write_interval_seconds)
        self.software_pps_interval_seconds = max(0.1, software_pps_interval_seconds)
        self.system_clock_sync_min_interval_seconds = max(
            1.0, system_clock_sync_min_interval_seconds
        )
        self.system_clock_sync_step_threshold_seconds = max(
            0.0, system_clock_sync_step_threshold_ms / 1000.0
        )
        self.rtc_sync_min_interval_seconds = max(1.0, rtc_sync_min_interval_seconds)
        self.status_file = status_file
        self.helper_status_file = helper_status_file
        self.time_fn = time_fn
        self.monotonic_fn = monotonic_fn
        self.request_writer = request_writer or ClockSyncRequestWriter()

        self.samples: Deque[dict[str, Any]] = deque()
        self.state = "disabled"
        self.message = "GPS time sync monitor disabled"
        self.last_status_write_monotonic: Optional[float] = None
        self.latest_sample: Optional[dict[str, Any]] = None

        self.pps_tick_count = 0
        self.last_pps_tick_monotonic: Optional[float] = None
        self.last_pps_tick_estimated_utc: Optional[datetime.datetime] = None
        self.next_pps_tick_monotonic: Optional[float] = None

        self.system_clock_sync_state = "disabled"
        self.system_clock_sync_message = "System clock sync disabled"
        self.system_clock_request_count = 0
        self.last_system_clock_request_monotonic: Optional[float] = None
        self.last_system_clock_request_utc: Optional[str] = None
        self.last_system_clock_offset_seconds: Optional[float] = None

        self.rtc_sync_state = "disabled"
        self.rtc_sync_message = "RTC sync disabled"
        self.rtc_request_count = 0
        self.last_rtc_request_monotonic: Optional[float] = None
        self.last_rtc_request_utc: Optional[str] = None

    @classmethod
    def from_config(
        cls,
        cfg,
        status_file: Path = STATUS_FILE,
        helper_status_file: Path = HELPER_STATUS_FILE,
    ) -> "GpsTimeSyncMonitor":
        return cls(
            enabled=_as_bool(cfg.get_option("gps_time_sync", False)),
            software_pps_enabled=_as_bool(cfg.get_option("software_pps", False)),
            system_clock_sync_enabled=_as_bool(
                cfg.get_option("gps_time_sync_system_clock", False)
            ),
            rtc_sync_enabled=_as_bool(cfg.get_option("rtc_sync", False)),
            min_samples=_as_int(cfg.get_option("gps_time_sync_min_samples", 5), 5),
            sample_window_seconds=_as_float(
                cfg.get_option("gps_time_sync_window_seconds", 120.0), 120.0
            ),
            stale_seconds=_as_float(
                cfg.get_option("gps_time_sync_stale_seconds", 30.0), 30.0
            ),
            max_tacc_ns=_as_int(
                cfg.get_option("gps_time_sync_max_tacc_ns", 1_000_000_000),
                1_000_000_000,
            ),
            stable_jitter_ms=_as_float(
                cfg.get_option("gps_time_sync_stable_jitter_ms", 250.0), 250.0
            ),
            stable_offset_ms=_as_float(
                cfg.get_option("gps_time_sync_stable_offset_ms", 1000.0), 1000.0
            ),
            software_pps_interval_seconds=_as_float(
                cfg.get_option("software_pps_interval_seconds", 1.0), 1.0
            ),
            system_clock_sync_min_interval_seconds=_as_float(
                cfg.get_option("gps_time_sync_system_clock_min_interval_seconds", 300.0),
                300.0,
            ),
            system_clock_sync_step_threshold_ms=_as_float(
                cfg.get_option("gps_time_sync_system_clock_step_threshold_ms", 500.0),
                500.0,
            ),
            rtc_sync_min_interval_seconds=_as_float(
                cfg.get_option("rtc_sync_min_interval_seconds", 3600.0), 3600.0
            ),
            status_file=status_file,
            helper_status_file=helper_status_file,
        )

    def update_config(self, cfg) -> None:
        updated = self.from_config(
            cfg,
            status_file=self.status_file,
            helper_status_file=self.helper_status_file,
        )
        self.enabled = updated.enabled
        self.software_pps_enabled = updated.software_pps_enabled
        self.system_clock_sync_enabled = updated.system_clock_sync_enabled
        self.rtc_sync_enabled = updated.rtc_sync_enabled
        self.min_samples = updated.min_samples
        self.sample_window_seconds = updated.sample_window_seconds
        self.stale_seconds = updated.stale_seconds
        self.max_tacc_ns = updated.max_tacc_ns
        self.stable_jitter_seconds = updated.stable_jitter_seconds
        self.stable_offset_seconds = updated.stable_offset_seconds
        self.status_write_interval_seconds = updated.status_write_interval_seconds
        self.software_pps_interval_seconds = updated.software_pps_interval_seconds
        self.system_clock_sync_min_interval_seconds = (
            updated.system_clock_sync_min_interval_seconds
        )
        self.system_clock_sync_step_threshold_seconds = (
            updated.system_clock_sync_step_threshold_seconds
        )
        self.rtc_sync_min_interval_seconds = updated.rtc_sync_min_interval_seconds
        self._refresh_action_wait_states()
        self.write_status(force=True)

    def _active(self) -> bool:
        return self.enabled or self.software_pps_enabled

    def write_startup_status(self) -> None:
        if self.enabled:
            self._set_state("waiting_for_gps_time", "Waiting for GPS time")
        elif self.software_pps_enabled:
            self._set_state("software_pps_only", "Software PPS enabled")
        else:
            self._set_state("disabled", "GPS time sync monitor disabled")

        self._refresh_action_wait_states()
        if self._active() or self.status_file.exists():
            self.write_status(force=True)

    def _set_state(self, state: str, message: str) -> bool:
        changed = state != self.state or message != self.message
        self.state = state
        self.message = message
        return changed

    def _prune_samples(self, now_monotonic: float) -> None:
        while (
            self.samples
            and now_monotonic - self.samples[0]["monotonic"] > self.sample_window_seconds
        ):
            self.samples.popleft()

    def _offset_stats(self) -> dict[str, Optional[float]]:
        offsets = [
            sample["offset_seconds"]
            for sample in self.samples
            if sample.get("offset_seconds") is not None
        ]
        if not offsets:
            return {
                "latest_seconds": None,
                "mean_seconds": None,
                "jitter_seconds": None,
                "min_seconds": None,
                "max_seconds": None,
            }
        latest = offsets[-1]
        min_offset = min(offsets)
        max_offset = max(offsets)
        return {
            "latest_seconds": latest,
            "mean_seconds": sum(offsets) / len(offsets),
            "jitter_seconds": max_offset - min_offset,
            "min_seconds": min_offset,
            "max_seconds": max_offset,
        }

    def _extract_sample(
        self, gps_content: Any
    ) -> tuple[Optional[datetime.datetime], Optional[int], str, bool]:
        if isinstance(gps_content, datetime.datetime):
            return _utc_datetime(gps_content), None, "GPS", True
        if not isinstance(gps_content, dict):
            return None, None, "unknown", False

        gps_dt = gps_content.get("time")
        if not isinstance(gps_dt, datetime.datetime):
            return None, None, str(gps_content.get("source", "unknown")), False

        tacc = gps_content.get("tAcc")
        if tacc is not None:
            tacc = _as_int(tacc, -1)
        return (
            _utc_datetime(gps_dt),
            tacc,
            str(gps_content.get("source", "GPS")),
            _as_bool(gps_content.get("valid", True), True),
        )

    def observe_time(self, gps_content: Any, reference_dt: Any = None) -> None:
        if not self._active():
            return

        now_monotonic = self.monotonic_fn()
        gps_dt, tacc_ns, source, valid = self._extract_sample(gps_content)
        if gps_dt is None:
            changed = self._set_state("invalid_sample", "GPS time sample missing time")
            self.write_status(force=changed)
            return

        ref_dt = None
        offset_seconds = None
        if isinstance(reference_dt, datetime.datetime):
            ref_dt = _utc_datetime(reference_dt)
            offset_seconds = (gps_dt - ref_dt).total_seconds()

        sample = {
            "gps_time": gps_dt.isoformat(),
            "source": source,
            "valid": valid,
            "tAcc_ns": tacc_ns,
            "reference_time": ref_dt.isoformat() if ref_dt else None,
            "offset_seconds": offset_seconds,
            "system_offset_seconds": gps_dt.timestamp() - self.time_fn(),
            "monotonic": now_monotonic,
            "received_unix": self.time_fn(),
        }
        for key in (
            "message_class",
            "lock_type",
            "mode",
            "satellites_seen",
            "satellites_used",
            "hdop",
            "pdop",
        ):
            if isinstance(gps_content, dict) and key in gps_content:
                sample[key] = gps_content[key]
        self.latest_sample = sample
        self.samples.append(sample)
        self._prune_samples(now_monotonic)

        changed = self._evaluate_state()
        changed = self._maybe_apply_sync_actions() or changed
        self.write_status(force=changed or len(self.samples) == 1)

    def _evaluate_state(self) -> bool:
        if not self.enabled:
            return self._set_state("software_pps_only", "Software PPS enabled")

        if self.latest_sample is None:
            return self._set_state("waiting_for_gps_time", "Waiting for GPS time")

        if not self.latest_sample.get("valid", True):
            return self._set_state(
                "low_quality",
                "GPS time candidate is present but is not valid yet",
            )

        tacc_ns = self.latest_sample.get("tAcc_ns")
        if tacc_ns is not None and tacc_ns >= 0 and tacc_ns > self.max_tacc_ns:
            return self._set_state(
                "low_quality",
                f"GPS time accuracy {tacc_ns} ns exceeds {self.max_tacc_ns} ns",
            )

        stats = self._offset_stats()
        if stats["latest_seconds"] is None:
            return self._set_state(
                "no_reference",
                "GPS time received before PiFinder internal time was available",
            )

        if len(self.samples) < self.min_samples:
            return self._set_state(
                "collecting",
                f"Collecting GPS time samples {len(self.samples)}/{self.min_samples}",
            )

        latest_offset = abs(stats["latest_seconds"] or 0.0)
        jitter = stats["jitter_seconds"] or 0.0
        if (
            latest_offset <= self.stable_offset_seconds
            and jitter <= self.stable_jitter_seconds
        ):
            return self._set_state("stable", "GPS time is stable")

        return self._set_state(
            "unstable",
            "GPS time offset or jitter is outside the configured threshold",
        )

    def _set_system_clock_sync_state(
        self, state: str, message: str, offset_seconds: Optional[float] = None
    ) -> bool:
        changed = (
            state != self.system_clock_sync_state
            or message != self.system_clock_sync_message
            or offset_seconds != self.last_system_clock_offset_seconds
        )
        self.system_clock_sync_state = state
        self.system_clock_sync_message = message
        self.last_system_clock_offset_seconds = offset_seconds
        return changed

    def _set_rtc_sync_state(self, state: str, message: str) -> bool:
        changed = state != self.rtc_sync_state or message != self.rtc_sync_message
        self.rtc_sync_state = state
        self.rtc_sync_message = message
        return changed

    def _latest_gps_datetime(self) -> Optional[datetime.datetime]:
        if self.latest_sample is None:
            return None
        gps_time = self.latest_sample.get("gps_time")
        if not gps_time:
            return None
        try:
            return _utc_datetime(datetime.datetime.fromisoformat(gps_time))
        except ValueError:
            return None

    def _sync_block_reason(self) -> Optional[tuple[str, str]]:
        if not self.enabled:
            return "disabled", "GPS time sync disabled"
        if self.latest_sample is None:
            return "waiting_for_stable_gps", "Waiting for GPS time"
        if not self.latest_sample.get("valid", True):
            return "waiting_for_stable_gps", "Latest GPS time is not valid yet"
        if self.state != "stable":
            return (
                "waiting_for_stable_gps",
                f"Waiting for stable GPS time; current state is {self.state}",
            )
        if self._latest_gps_datetime() is None:
            return "waiting_for_stable_gps", "Latest GPS time could not be parsed"
        return None

    def _cooldown_active(
        self, last_monotonic: Optional[float], min_interval_seconds: float
    ) -> bool:
        if last_monotonic is None:
            return False
        return self.monotonic_fn() - last_monotonic < min_interval_seconds

    def _system_clock_request_action(
        self, gps_dt: datetime.datetime
    ) -> tuple[bool, Optional[dict[str, Any]]]:
        if not self.system_clock_sync_enabled:
            changed = self._set_system_clock_sync_state(
                "disabled", "System clock sync disabled"
            )
            return changed, None

        offset_seconds = gps_dt.timestamp() - self.time_fn()
        if abs(offset_seconds) <= self.system_clock_sync_step_threshold_seconds:
            changed = self._set_system_clock_sync_state(
                "in_sync",
                "System clock offset is within the configured threshold",
                offset_seconds,
            )
            return changed, None

        if self._cooldown_active(
            self.last_system_clock_request_monotonic,
            self.system_clock_sync_min_interval_seconds,
        ):
            changed = self._set_system_clock_sync_state(
                "cooldown",
                "Waiting before the next system clock sync request",
                offset_seconds,
            )
            return changed, None

        return False, {
            "enabled": True,
            "offset_seconds": offset_seconds,
            "step_threshold_seconds": self.system_clock_sync_step_threshold_seconds,
            "min_interval_seconds": self.system_clock_sync_min_interval_seconds,
        }

    def _rtc_request_action(
        self, gps_dt: datetime.datetime
    ) -> tuple[bool, Optional[dict[str, Any]]]:
        del gps_dt
        if not self.rtc_sync_enabled:
            changed = self._set_rtc_sync_state("disabled", "RTC sync disabled")
            return changed, None

        if self._cooldown_active(
            self.last_rtc_request_monotonic, self.rtc_sync_min_interval_seconds
        ):
            changed = self._set_rtc_sync_state(
                "cooldown", "Waiting before the next RTC sync request"
            )
            return changed, None

        return False, {
            "enabled": True,
            "min_interval_seconds": self.rtc_sync_min_interval_seconds,
        }

    def _request_id(self, actions: dict[str, Any]) -> str:
        action_names = "-".join(sorted(actions))
        return f"{int(self.monotonic_fn() * 1000)}-{action_names}"

    def _write_sync_request(
        self,
        gps_dt: datetime.datetime,
        actions: dict[str, Any],
    ) -> bool:
        latest = self.latest_sample or {}
        payload = {
            "version": 1,
            "request_id": self._request_id(actions),
            "created_monotonic": self.monotonic_fn(),
            "created_unix": self.time_fn(),
            "gps_time": gps_dt.isoformat(),
            "monitor_state": self.state,
            "status_file": str(self.status_file),
            "helper_status_file": str(self.helper_status_file),
            "actions": actions,
            "latest": {
                "source": latest.get("source"),
                "valid": latest.get("valid"),
                "tAcc_ns": latest.get("tAcc_ns"),
                "message_class": latest.get("message_class"),
            },
            "samples": {
                "count": len(self.samples),
                "min_required": self.min_samples,
            },
        }
        result = self.request_writer.write_request(payload)
        if not result.get("ok"):
            message = str(result.get("message") or "Could not write sync request")
            changed = False
            if "system_clock" in actions:
                changed = (
                    self._set_system_clock_sync_state("request_error", message)
                    or changed
                )
            if "rtc" in actions:
                changed = self._set_rtc_sync_state("request_error", message) or changed
            return changed

        now_monotonic = self.monotonic_fn()
        gps_time = gps_dt.isoformat()
        message = str(result.get("message") or "Sync request written")
        changed = False
        if "system_clock" in actions:
            self.system_clock_request_count += 1
            self.last_system_clock_request_monotonic = now_monotonic
            self.last_system_clock_request_utc = gps_time
            changed = (
                self._set_system_clock_sync_state(
                    "requested",
                    "System clock sync requested for privileged helper",
                    actions["system_clock"].get("offset_seconds"),
                )
                or changed
            )
        if "rtc" in actions:
            self.rtc_request_count += 1
            self.last_rtc_request_monotonic = now_monotonic
            self.last_rtc_request_utc = gps_time
            changed = (
                self._set_rtc_sync_state(
                    "requested", "RTC sync requested for privileged helper"
                )
                or changed
            )
        logger.info("GPS time sync helper request written: %s", message)
        return changed

    def _clear_sync_request(self) -> None:
        self.request_writer.clear_request()

    def _refresh_action_wait_states(self) -> bool:
        changed = False
        block_reason = self._sync_block_reason()
        if block_reason is not None:
            block_state, block_message = block_reason
            if self.system_clock_sync_enabled:
                changed = (
                    self._set_system_clock_sync_state(block_state, block_message)
                    or changed
                )
            else:
                changed = (
                    self._set_system_clock_sync_state(
                        "disabled", "System clock sync disabled"
                    )
                    or changed
                )
            if self.rtc_sync_enabled:
                changed = self._set_rtc_sync_state(block_state, block_message) or changed
            else:
                changed = (
                    self._set_rtc_sync_state("disabled", "RTC sync disabled") or changed
                )
        return changed

    def _maybe_apply_sync_actions(self) -> bool:
        block_changed = self._refresh_action_wait_states()
        if self._sync_block_reason() is not None:
            self._clear_sync_request()
            return block_changed

        gps_dt = self._latest_gps_datetime()
        if gps_dt is None:
            return block_changed

        changed, system_clock_action = self._system_clock_request_action(gps_dt)
        changed = changed or block_changed
        rtc_changed, rtc_action = self._rtc_request_action(gps_dt)
        changed = rtc_changed or changed

        actions = {}
        if system_clock_action is not None:
            actions["system_clock"] = system_clock_action
        if rtc_action is not None:
            actions["rtc"] = rtc_action

        if actions:
            changed = self._write_sync_request(gps_dt, actions) or changed
        return changed

    def _estimated_utc_for_monotonic(
        self, tick_monotonic: float
    ) -> Optional[datetime.datetime]:
        if self.latest_sample is None:
            return None
        gps_time = self.latest_sample.get("gps_time")
        sample_monotonic = self.latest_sample.get("monotonic")
        if not gps_time or sample_monotonic is None:
            return None
        try:
            gps_dt = datetime.datetime.fromisoformat(gps_time)
        except ValueError:
            return None
        return _utc_datetime(gps_dt) + datetime.timedelta(
            seconds=tick_monotonic - sample_monotonic
        )

    def _poll_software_pps(self, now_monotonic: float) -> bool:
        if not self.software_pps_enabled:
            self.next_pps_tick_monotonic = None
            return False

        if self.next_pps_tick_monotonic is None:
            interval = self.software_pps_interval_seconds
            self.next_pps_tick_monotonic = (
                math.floor(now_monotonic / interval) + 1
            ) * interval
            return False

        ticked = False
        while now_monotonic >= self.next_pps_tick_monotonic:
            tick_monotonic = self.next_pps_tick_monotonic
            self.pps_tick_count += 1
            self.last_pps_tick_monotonic = tick_monotonic
            self.last_pps_tick_estimated_utc = self._estimated_utc_for_monotonic(
                tick_monotonic
            )
            self.next_pps_tick_monotonic += self.software_pps_interval_seconds
            ticked = True
        return ticked

    def poll(self) -> None:
        if not self._active():
            return

        now_monotonic = self.monotonic_fn()
        ticked = self._poll_software_pps(now_monotonic)
        changed = False

        if self.enabled:
            if self.latest_sample is None:
                changed = self._set_state("waiting_for_gps_time", "Waiting for GPS time")
            elif now_monotonic - self.latest_sample["monotonic"] > self.stale_seconds:
                changed = self._set_state(
                    "stale",
                    f"No GPS time sample for more than {self.stale_seconds:.0f}s",
                )
        elif self.software_pps_enabled:
            changed = self._set_state("software_pps_only", "Software PPS enabled")

        changed = self._refresh_action_wait_states() or changed
        self.write_status(force=changed or ticked)

    def note_reset(self) -> None:
        if not self._active():
            return
        self.samples.clear()
        self.latest_sample = None
        changed = self._set_state("waiting_for_gps_time", "PiFinder datetime reset")
        changed = self._refresh_action_wait_states() or changed
        self.write_status(force=changed)

    def _read_helper_status(self) -> Optional[dict[str, Any]]:
        try:
            with open(self.helper_status_file, "r", encoding="utf-8") as helper_in:
                payload = json.load(helper_in)
        except FileNotFoundError:
            return None
        except Exception:
            logger.exception("Could not read GPS time sync helper status")
            return {"state": "read_error"}
        return payload if isinstance(payload, dict) else {"state": "invalid_status"}

    def status_payload(self) -> dict[str, Any]:
        stats = self._offset_stats()
        latest = self.latest_sample or {}
        age = None
        if latest.get("monotonic") is not None:
            age = self.monotonic_fn() - latest["monotonic"]

        return {
            "enabled": self.enabled,
            "state": self.state,
            "message": self.message,
            "updated_unix": self.time_fn(),
            "system_clock_sync_enabled": self.system_clock_sync_enabled,
            "system_clock_sync_state": self.system_clock_sync_state,
            "rtc_sync_enabled": self.rtc_sync_enabled,
            "rtc_sync_state": self.rtc_sync_state,
            "samples": {
                "count": len(self.samples),
                "min_required": self.min_samples,
                "window_seconds": self.sample_window_seconds,
                "stale_seconds": self.stale_seconds,
            },
            "latest": {
                "gps_time": latest.get("gps_time"),
                "source": latest.get("source"),
                "valid": latest.get("valid"),
                "tAcc_ns": latest.get("tAcc_ns"),
                "message_class": latest.get("message_class"),
                "lock_type": latest.get("lock_type"),
                "mode": latest.get("mode"),
                "satellites_seen": latest.get("satellites_seen"),
                "satellites_used": latest.get("satellites_used"),
                "hdop": latest.get("hdop"),
                "pdop": latest.get("pdop"),
                "reference_time": latest.get("reference_time"),
                "offset_seconds": latest.get("offset_seconds"),
                "system_offset_seconds": latest.get("system_offset_seconds"),
                "age_seconds": age,
            },
            "offset": stats,
            "thresholds": {
                "max_tAcc_ns": self.max_tacc_ns,
                "stable_jitter_seconds": self.stable_jitter_seconds,
                "stable_offset_seconds": self.stable_offset_seconds,
                "system_clock_sync_step_threshold_seconds": (
                    self.system_clock_sync_step_threshold_seconds
                ),
            },
            "system_clock_sync": {
                "enabled": self.system_clock_sync_enabled,
                "state": self.system_clock_sync_state,
                "message": self.system_clock_sync_message,
                "request_count": self.system_clock_request_count,
                "min_interval_seconds": self.system_clock_sync_min_interval_seconds,
                "last_request_monotonic": self.last_system_clock_request_monotonic,
                "last_request_utc": self.last_system_clock_request_utc,
                "last_offset_seconds": self.last_system_clock_offset_seconds,
            },
            "rtc_sync": {
                "enabled": self.rtc_sync_enabled,
                "state": self.rtc_sync_state,
                "message": self.rtc_sync_message,
                "request_count": self.rtc_request_count,
                "min_interval_seconds": self.rtc_sync_min_interval_seconds,
                "last_request_monotonic": self.last_rtc_request_monotonic,
                "last_request_utc": self.last_rtc_request_utc,
            },
            "helper": self._read_helper_status(),
            "software_pps": {
                "enabled": self.software_pps_enabled,
                "interval_seconds": self.software_pps_interval_seconds,
                "tick_count": self.pps_tick_count,
                "last_tick_monotonic": self.last_pps_tick_monotonic,
                "last_tick_estimated_utc": (
                    self.last_pps_tick_estimated_utc.isoformat()
                    if self.last_pps_tick_estimated_utc
                    else None
                ),
            },
        }

    def write_status(self, force: bool = False) -> None:
        if not self._active() and not force:
            return

        now_monotonic = self.monotonic_fn()
        if (
            not force
            and self.last_status_write_monotonic is not None
            and now_monotonic - self.last_status_write_monotonic
            < self.status_write_interval_seconds
        ):
            return

        try:
            utils.create_path(self.status_file.parent)
            with open(self.status_file, "w", encoding="utf-8") as status_out:
                json.dump(self.status_payload(), status_out, indent=2, sort_keys=True)
            self.last_status_write_monotonic = now_monotonic
        except Exception:
            logger.exception("Could not write GPS time sync status")
