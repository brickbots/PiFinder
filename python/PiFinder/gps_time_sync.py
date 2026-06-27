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
        status_file: Path = STATUS_FILE,
        time_fn: Callable[[], float] = time.time,
        monotonic_fn: Callable[[], float] = time.monotonic,
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
        self.status_file = status_file
        self.time_fn = time_fn
        self.monotonic_fn = monotonic_fn

        self.samples: Deque[dict[str, Any]] = deque()
        self.state = "disabled"
        self.message = "GPS time sync monitor disabled"
        self.last_status_write_monotonic: Optional[float] = None
        self.latest_sample: Optional[dict[str, Any]] = None

        self.pps_tick_count = 0
        self.last_pps_tick_monotonic: Optional[float] = None
        self.last_pps_tick_estimated_utc: Optional[datetime.datetime] = None
        self.next_pps_tick_monotonic: Optional[float] = None

    @classmethod
    def from_config(cls, cfg, status_file: Path = STATUS_FILE) -> "GpsTimeSyncMonitor":
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
            status_file=status_file,
        )

    def update_config(self, cfg) -> None:
        updated = self.from_config(cfg, status_file=self.status_file)
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
    ) -> tuple[Optional[datetime.datetime], Optional[int], str]:
        if isinstance(gps_content, datetime.datetime):
            return _utc_datetime(gps_content), None, "GPS"
        if not isinstance(gps_content, dict):
            return None, None, "unknown"

        gps_dt = gps_content.get("time")
        if not isinstance(gps_dt, datetime.datetime):
            return None, None, str(gps_content.get("source", "unknown"))

        tacc = gps_content.get("tAcc")
        if tacc is not None:
            tacc = _as_int(tacc, -1)
        return _utc_datetime(gps_dt), tacc, str(gps_content.get("source", "GPS"))

    def observe_time(self, gps_content: Any, reference_dt: Any = None) -> None:
        if not self._active():
            return

        now_monotonic = self.monotonic_fn()
        gps_dt, tacc_ns, source = self._extract_sample(gps_content)
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
            "tAcc_ns": tacc_ns,
            "reference_time": ref_dt.isoformat() if ref_dt else None,
            "offset_seconds": offset_seconds,
            "monotonic": now_monotonic,
            "received_unix": self.time_fn(),
        }
        self.latest_sample = sample
        self.samples.append(sample)
        self._prune_samples(now_monotonic)

        changed = self._evaluate_state()
        self.write_status(force=changed or len(self.samples) == 1)

    def _evaluate_state(self) -> bool:
        if not self.enabled:
            return self._set_state("software_pps_only", "Software PPS enabled")

        if self.latest_sample is None:
            return self._set_state("waiting_for_gps_time", "Waiting for GPS time")

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

        self.write_status(force=changed or ticked)

    def note_reset(self) -> None:
        if not self._active():
            return
        self.samples.clear()
        self.latest_sample = None
        changed = self._set_state("waiting_for_gps_time", "PiFinder datetime reset")
        self.write_status(force=changed)

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
            "system_clock_sync_state": "not_implemented_phase1",
            "rtc_sync_enabled": self.rtc_sync_enabled,
            "rtc_sync_state": "not_implemented_phase1",
            "samples": {
                "count": len(self.samples),
                "min_required": self.min_samples,
                "window_seconds": self.sample_window_seconds,
                "stale_seconds": self.stale_seconds,
            },
            "latest": {
                "gps_time": latest.get("gps_time"),
                "source": latest.get("source"),
                "tAcc_ns": latest.get("tAcc_ns"),
                "reference_time": latest.get("reference_time"),
                "offset_seconds": latest.get("offset_seconds"),
                "age_seconds": age,
            },
            "offset": stats,
            "thresholds": {
                "max_tAcc_ns": self.max_tacc_ns,
                "stable_jitter_seconds": self.stable_jitter_seconds,
                "stable_offset_seconds": self.stable_offset_seconds,
            },
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
