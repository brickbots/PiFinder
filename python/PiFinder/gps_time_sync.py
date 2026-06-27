#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Integrated time-source monitor for PiFinder.

The monitor evaluates GPS and NTP candidates, selects the best available time
source, manages optional software PPS ticks, and writes constrained requests for
the privileged helper when system clock or RTC updates are enabled.
"""

from __future__ import annotations

import datetime
import json
import logging
import math
import os
import socket
import struct
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable, Deque, Optional

import pytz

from PiFinder import utils


logger = logging.getLogger("GPS.TimeSync")

DATA_DIR = Path(os.environ.get("PIFINDER_DATA_DIR", utils.data_dir))
STATUS_FILE = DATA_DIR / "gps_time_status.json"
REQUEST_FILE = DATA_DIR / "gps_time_sync_request.json"
HELPER_STATUS_FILE = DATA_DIR / "gps_time_sync_helper_status.json"
NTP_EPOCH_DELTA = 2_208_988_800
DEFAULT_NTP_SERVERS = (
    "pool.ntp.org",
    "time.google.com",
    "time.cloudflare.com",
    "time.nist.gov",
)


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
            logger.exception("Could not clear time sync request")


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


def _read_ntp_timestamp(packet: bytes, offset: int) -> float:
    seconds, fraction = struct.unpack("!II", packet[offset : offset + 8])
    return seconds - NTP_EPOCH_DELTA + fraction / 2**32


def _write_ntp_timestamp(packet: bytearray, offset: int, unix_time: float) -> None:
    ntp_time = unix_time + NTP_EPOCH_DELTA
    seconds = int(ntp_time)
    fraction = int((ntp_time - seconds) * 2**32)
    packet[offset : offset + 8] = struct.pack("!II", seconds, fraction)


def _read_ntp_short(packet: bytes, offset: int, signed: bool = False) -> float:
    fmt = "!i" if signed else "!I"
    raw_value = struct.unpack(fmt, packet[offset : offset + 4])[0]
    return raw_value / 2**16


class NtpClient:
    """Small SNTP client used for opportunistic time-source checks."""

    port = 123

    def __init__(self, time_fn: Callable[[], float] = time.time):
        self.time_fn = time_fn

    def query(self, server: str, timeout_seconds: float = 1.0) -> dict[str, Any]:
        server = server.strip()
        if not server:
            raise ValueError("NTP server is empty")

        packet = bytearray(48)
        packet[0] = 0x23  # LI=0, VN=4, mode=client
        t1 = self.time_fn()
        _write_ntp_timestamp(packet, 40, t1)

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(timeout_seconds)
            sock.sendto(packet, (server, self.port))
            data, address = sock.recvfrom(512)
            t4 = self.time_fn()

        if len(data) < 48:
            raise ValueError("NTP response was shorter than 48 bytes")

        leap = (data[0] >> 6) & 0x03
        version = (data[0] >> 3) & 0x07
        mode = data[0] & 0x07
        stratum = data[1]
        t2 = _read_ntp_timestamp(data, 32)
        t3 = _read_ntp_timestamp(data, 40)
        root_delay = _read_ntp_short(data, 4, signed=True)
        root_dispersion = _read_ntp_short(data, 8)
        delay = (t4 - t1) - (t3 - t2)
        offset = ((t2 - t1) + (t3 - t4)) / 2.0
        valid = mode in (4, 5) and 0 < stratum < 16 and t3 > 0 and leap != 3
        quality = max(0.0, delay) / 2.0 + max(0.0, root_dispersion)

        return {
            "time": datetime.datetime.fromtimestamp(t4 + offset, tz=pytz.UTC),
            "server": server,
            "address": address[0] if address else None,
            "valid": valid,
            "version": version,
            "mode": mode,
            "stratum": stratum,
            "leap": leap,
            "offset_seconds": offset,
            "delay_seconds": max(0.0, delay),
            "root_delay_seconds": root_delay,
            "root_dispersion_seconds": root_dispersion,
            "quality_seconds": quality,
            "received_unix": t4,
        }


class GpsTimeSyncMonitor:
    """Evaluate GPS time quality and optional software PPS ticks."""

    def __init__(
        self,
        time_sync_enabled: Optional[bool] = None,
        enabled: bool = False,
        ntp_enabled: bool = False,
        software_pps_enabled: bool = False,
        system_clock_sync_enabled: bool = False,
        rtc_sync_enabled: bool = False,
        source_mode: str = "best",
        ntp_server: str = DEFAULT_NTP_SERVERS[0],
        ntp_server_custom: str = "",
        ntp_poll_interval_seconds: float = 300.0,
        ntp_timeout_seconds: float = 1.0,
        ntp_max_delay_ms: float = 1500.0,
        ntp_stale_seconds: float = 900.0,
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
        ntp_client: Optional[NtpClient] = None,
        ntp_async: bool = True,
    ):
        if time_sync_enabled is None:
            time_sync_enabled = (
                enabled
                or ntp_enabled
                or software_pps_enabled
                or system_clock_sync_enabled
                or rtc_sync_enabled
            )
        self.time_sync_enabled = time_sync_enabled
        self.enabled = enabled
        self.ntp_enabled = ntp_enabled
        self.software_pps_enabled = software_pps_enabled
        self.system_clock_sync_enabled = system_clock_sync_enabled
        self.rtc_sync_enabled = rtc_sync_enabled
        self.source_mode = source_mode if source_mode in ("best", "gps", "ntp") else "best"
        self.ntp_server = ntp_server
        self.ntp_server_custom = ntp_server_custom
        self.ntp_poll_interval_seconds = max(5.0, ntp_poll_interval_seconds)
        self.ntp_timeout_seconds = max(0.1, ntp_timeout_seconds)
        self.ntp_max_delay_seconds = max(0.001, ntp_max_delay_ms / 1000.0)
        self.ntp_stale_seconds = max(5.0, ntp_stale_seconds)
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
        self.ntp_client = ntp_client or NtpClient(time_fn=time_fn)
        self.ntp_async = ntp_async

        self.samples: Deque[dict[str, Any]] = deque()
        self.state = "disabled"
        self.message = "Time sync disabled"
        self.gps_state = "disabled"
        self.gps_message = "GPS time source disabled"
        self.last_status_write_monotonic: Optional[float] = None
        self.latest_sample: Optional[dict[str, Any]] = None

        self.ntp_state = "disabled"
        self.ntp_message = "NTP time source disabled"
        self.latest_ntp_sample: Optional[dict[str, Any]] = None
        self.last_ntp_poll_monotonic: Optional[float] = None
        self.ntp_query_in_progress = False
        self.ntp_query_started_monotonic: Optional[float] = None
        self.ntp_pending_result: Optional[dict[str, Any]] = None
        self.ntp_lock = threading.Lock()

        self.selected_source: Optional[dict[str, Any]] = None

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
            time_sync_enabled=_as_bool(cfg.get_option("time_sync_enabled", False)),
            enabled=_as_bool(cfg.get_option("gps_time_sync", True)),
            ntp_enabled=_as_bool(cfg.get_option("ntp_time_sync", True)),
            software_pps_enabled=_as_bool(cfg.get_option("software_pps", False)),
            system_clock_sync_enabled=_as_bool(
                cfg.get_option(
                    "time_sync_system_clock",
                    cfg.get_option("gps_time_sync_system_clock", True),
                )
            ),
            rtc_sync_enabled=_as_bool(cfg.get_option("rtc_sync", False)),
            source_mode=str(cfg.get_option("time_sync_source_mode", "best")),
            ntp_server=str(cfg.get_option("ntp_server", DEFAULT_NTP_SERVERS[0])),
            ntp_server_custom=str(cfg.get_option("ntp_server_custom", "")),
            ntp_poll_interval_seconds=_as_float(
                cfg.get_option("ntp_poll_interval_seconds", 300.0), 300.0
            ),
            ntp_timeout_seconds=_as_float(
                cfg.get_option("ntp_timeout_seconds", 1.0), 1.0
            ),
            ntp_max_delay_ms=_as_float(
                cfg.get_option("ntp_max_delay_ms", 1500.0), 1500.0
            ),
            ntp_stale_seconds=_as_float(
                cfg.get_option("ntp_stale_seconds", 900.0), 900.0
            ),
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
                cfg.get_option(
                    "time_sync_system_clock_min_interval_seconds",
                    cfg.get_option(
                        "gps_time_sync_system_clock_min_interval_seconds", 300.0
                    ),
                ),
                300.0,
            ),
            system_clock_sync_step_threshold_ms=_as_float(
                cfg.get_option(
                    "time_sync_system_clock_step_threshold_ms",
                    cfg.get_option(
                        "gps_time_sync_system_clock_step_threshold_ms", 500.0
                    ),
                ),
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
        self.time_sync_enabled = updated.time_sync_enabled
        self.enabled = updated.enabled
        self.ntp_enabled = updated.ntp_enabled
        self.software_pps_enabled = updated.software_pps_enabled
        self.system_clock_sync_enabled = updated.system_clock_sync_enabled
        self.rtc_sync_enabled = updated.rtc_sync_enabled
        self.source_mode = updated.source_mode
        self.ntp_server = updated.ntp_server
        self.ntp_server_custom = updated.ntp_server_custom
        self.ntp_poll_interval_seconds = updated.ntp_poll_interval_seconds
        self.ntp_timeout_seconds = updated.ntp_timeout_seconds
        self.ntp_max_delay_seconds = updated.ntp_max_delay_seconds
        self.ntp_stale_seconds = updated.ntp_stale_seconds
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
        return self.time_sync_enabled and (
            self.enabled
            or self.ntp_enabled
            or self.software_pps_enabled
            or self.system_clock_sync_enabled
            or self.rtc_sync_enabled
        )

    def write_startup_status(self) -> None:
        if not self.time_sync_enabled:
            self._set_state("disabled", "Time sync disabled")
        elif self.enabled:
            self._set_state("waiting_for_time_source", "Waiting for time source")
        elif self.software_pps_enabled:
            self._set_state("software_pps_only", "Software PPS enabled")
        else:
            self._set_state("disabled", "Time sync has no enabled source")

        self._refresh_action_wait_states()
        if self._active() or self.status_file.exists():
            self.write_status(force=True)

    def _set_state(self, state: str, message: str) -> bool:
        changed = state != self.state or message != self.message
        self.state = state
        self.message = message
        return changed

    def _set_gps_state(self, state: str, message: str) -> bool:
        changed = state != self.gps_state or message != self.gps_message
        self.gps_state = state
        self.gps_message = message
        return changed

    def _set_ntp_state(self, state: str, message: str) -> bool:
        changed = state != self.ntp_state or message != self.ntp_message
        self.ntp_state = state
        self.ntp_message = message
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
        if not self.time_sync_enabled or not self.enabled:
            return

        now_monotonic = self.monotonic_fn()
        gps_dt, tacc_ns, source, valid = self._extract_sample(gps_content)
        if gps_dt is None:
            changed = self._set_gps_state(
                "invalid_sample", "GPS time sample missing time"
            )
            changed = self._evaluate_state() or changed
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

    def _evaluate_gps_state(self) -> bool:
        if not self.enabled:
            return self._set_gps_state("disabled", "GPS time source disabled")

        if self.latest_sample is None:
            return self._set_gps_state("waiting_for_gps_time", "Waiting for GPS time")

        if self.monotonic_fn() - self.latest_sample["monotonic"] > self.stale_seconds:
            return self._set_gps_state(
                "stale",
                f"No GPS time sample for more than {self.stale_seconds:.0f}s",
            )

        if not self.latest_sample.get("valid", True):
            return self._set_gps_state(
                "low_quality",
                "GPS time candidate is present but is not valid yet",
            )

        tacc_ns = self.latest_sample.get("tAcc_ns")
        if tacc_ns is not None and tacc_ns >= 0 and tacc_ns > self.max_tacc_ns:
            return self._set_gps_state(
                "low_quality",
                f"GPS time accuracy {tacc_ns} ns exceeds {self.max_tacc_ns} ns",
            )

        stats = self._offset_stats()
        if stats["latest_seconds"] is None:
            return self._set_gps_state(
                "no_reference",
                "GPS time received before PiFinder internal time was available",
            )

        if len(self.samples) < self.min_samples:
            return self._set_gps_state(
                "collecting",
                f"Collecting GPS time samples {len(self.samples)}/{self.min_samples}",
            )

        latest_offset = abs(stats["latest_seconds"] or 0.0)
        jitter = stats["jitter_seconds"] or 0.0
        if (
            latest_offset <= self.stable_offset_seconds
            and jitter <= self.stable_jitter_seconds
        ):
            return self._set_gps_state("stable", "GPS time is stable")

        return self._set_gps_state(
            "unstable",
            "GPS time offset or jitter is outside the configured threshold",
        )

    def _gps_quality_seconds(self) -> Optional[float]:
        if self.latest_sample is None:
            return None
        tacc_ns = self.latest_sample.get("tAcc_ns")
        if isinstance(tacc_ns, (int, float)) and tacc_ns >= 0:
            return tacc_ns / 1_000_000_000.0
        jitter = self._offset_stats().get("jitter_seconds")
        if isinstance(jitter, (int, float)):
            return max(jitter, self.stable_jitter_seconds)
        return self.stable_jitter_seconds

    def _gps_candidate(self) -> Optional[dict[str, Any]]:
        if self.gps_state != "stable" or self.latest_sample is None:
            return None
        age = self.monotonic_fn() - self.latest_sample["monotonic"]
        if age > self.stale_seconds:
            return None
        gps_dt = self._latest_gps_datetime()
        if gps_dt is None:
            return None
        quality_seconds = self._gps_quality_seconds()
        return {
            "source": "GPS",
            "time": gps_dt.isoformat(),
            "valid": True,
            "quality_seconds": quality_seconds,
            "age_seconds": age,
            "tAcc_ns": self.latest_sample.get("tAcc_ns"),
            "message_class": self.latest_sample.get("message_class"),
            "server": None,
        }

    def _ntp_candidate(self) -> Optional[dict[str, Any]]:
        if self.ntp_state != "stable" or self.latest_ntp_sample is None:
            return None
        age = self.monotonic_fn() - self.latest_ntp_sample["monotonic"]
        if age > self.ntp_stale_seconds:
            return None
        ntp_time = self.latest_ntp_sample.get("time")
        if not ntp_time:
            return None
        try:
            ntp_dt = _utc_datetime(datetime.datetime.fromisoformat(ntp_time))
        except ValueError:
            return None
        return {
            "source": "NTP",
            "time": ntp_dt.isoformat(),
            "valid": True,
            "quality_seconds": self.latest_ntp_sample.get("quality_seconds"),
            "age_seconds": age,
            "server": self.latest_ntp_sample.get("server"),
            "delay_seconds": self.latest_ntp_sample.get("delay_seconds"),
            "stratum": self.latest_ntp_sample.get("stratum"),
        }

    def _candidate_for_mode(self) -> list[dict[str, Any]]:
        gps_candidate = self._gps_candidate()
        ntp_candidate = self._ntp_candidate()
        if self.source_mode == "gps":
            return [gps_candidate] if gps_candidate else []
        if self.source_mode == "ntp":
            return [ntp_candidate] if ntp_candidate else []
        return [
            candidate
            for candidate in (gps_candidate, ntp_candidate)
            if candidate is not None
        ]

    def _evaluate_selected_source(self) -> bool:
        candidates = self._candidate_for_mode()
        if candidates:
            selected = min(
                candidates,
                key=lambda candidate: (
                    candidate.get("quality_seconds")
                    if isinstance(candidate.get("quality_seconds"), (int, float))
                    else float("inf")
                ),
            )
            changed = selected != self.selected_source
            self.selected_source = selected
            changed = (
                self._set_state(
                    "stable",
                    "Selected {source} time source".format(
                        source=selected.get("source", "time")
                    ),
                )
                or changed
            )
            return changed

        previous_selected = self.selected_source
        self.selected_source = None
        changed = previous_selected is not None

        if self.source_mode == "gps" and self.enabled:
            return self._set_state(self.gps_state, self.gps_message) or changed
        if self.source_mode == "ntp" and self.ntp_enabled:
            return self._set_state(self.ntp_state, self.ntp_message) or changed
        if self.enabled and self.gps_state not in ("disabled", "waiting_for_gps_time"):
            return self._set_state(self.gps_state, self.gps_message) or changed
        if self.ntp_enabled:
            return self._set_state(self.ntp_state, self.ntp_message) or changed
        if self.enabled:
            return self._set_state(self.gps_state, self.gps_message) or changed
        if self.software_pps_enabled:
            return (
                self._set_state("software_pps_only", "Software PPS enabled") or changed
            )
        return self._set_state("disabled", "Time sync has no enabled source") or changed

    def _evaluate_state(self) -> bool:
        if not self.time_sync_enabled:
            self.selected_source = None
            self._set_gps_state("disabled", "GPS time source disabled")
            self._set_ntp_state("disabled", "NTP time source disabled")
            return self._set_state("disabled", "Time sync disabled")

        changed = self._evaluate_gps_state()
        changed = self._evaluate_selected_source() or changed
        return changed

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

    def _selected_datetime(self) -> Optional[datetime.datetime]:
        if not self.selected_source:
            return None
        selected_time = self.selected_source.get("time")
        if not isinstance(selected_time, str) or not selected_time:
            return None
        try:
            return _utc_datetime(datetime.datetime.fromisoformat(selected_time))
        except ValueError:
            return None

    def _effective_ntp_server(self) -> str:
        if self.ntp_server == "custom":
            custom = self.ntp_server_custom.strip()
            if custom:
                return custom
        server = self.ntp_server.strip()
        return server if server and server != "custom" else DEFAULT_NTP_SERVERS[0]

    def _apply_ntp_result(self, result: dict[str, Any]) -> bool:
        now_monotonic = self.monotonic_fn()
        if not result.get("ok", True):
            self.latest_ntp_sample = {
                "server": result.get("server", self._effective_ntp_server()),
                "valid": False,
                "error": result.get("message", "NTP query failed"),
                "monotonic": now_monotonic,
                "received_unix": self.time_fn(),
            }
            return self._set_ntp_state(
                "unavailable", str(result.get("message") or "NTP query failed")
            )

        ntp_dt = result.get("time")
        if not isinstance(ntp_dt, datetime.datetime):
            self.latest_ntp_sample = {
                "server": result.get("server", self._effective_ntp_server()),
                "valid": False,
                "error": "NTP response did not include time",
                "monotonic": now_monotonic,
                "received_unix": self.time_fn(),
            }
            return self._set_ntp_state("invalid_sample", "NTP response missing time")

        ntp_dt = _utc_datetime(ntp_dt)
        delay_seconds = result.get("delay_seconds")
        valid = _as_bool(result.get("valid", True), True)
        sample = {
            "time": ntp_dt.isoformat(),
            "server": result.get("server", self._effective_ntp_server()),
            "address": result.get("address"),
            "valid": valid,
            "stratum": result.get("stratum"),
            "leap": result.get("leap"),
            "offset_seconds": result.get("offset_seconds"),
            "delay_seconds": delay_seconds,
            "root_delay_seconds": result.get("root_delay_seconds"),
            "root_dispersion_seconds": result.get("root_dispersion_seconds"),
            "quality_seconds": result.get("quality_seconds"),
            "system_offset_seconds": ntp_dt.timestamp() - self.time_fn(),
            "monotonic": now_monotonic,
            "received_unix": result.get("received_unix", self.time_fn()),
        }
        self.latest_ntp_sample = sample

        if not valid:
            return self._set_ntp_state(
                "low_quality", "NTP server response was not valid"
            )
        if (
            isinstance(delay_seconds, (int, float))
            and delay_seconds > self.ntp_max_delay_seconds
        ):
            return self._set_ntp_state(
                "low_quality",
                "NTP delay {delay:.3f}s exceeds {limit:.3f}s".format(
                    delay=delay_seconds, limit=self.ntp_max_delay_seconds
                ),
            )
        return self._set_ntp_state("stable", "NTP time is available")

    def _run_ntp_query(self, server: str) -> None:
        try:
            result = self.ntp_client.query(server, self.ntp_timeout_seconds)
            result = dict(result)
            result.setdefault("ok", True)
        except Exception as exc:
            result = {"ok": False, "server": server, "message": str(exc)}

        with self.ntp_lock:
            self.ntp_pending_result = result
            self.ntp_query_in_progress = False

    def _consume_ntp_result(self) -> bool:
        with self.ntp_lock:
            result = self.ntp_pending_result
            self.ntp_pending_result = None
        if result is None:
            return False
        return self._apply_ntp_result(result)

    def _poll_ntp(self, now_monotonic: float) -> bool:
        changed = self._consume_ntp_result()
        if not self.time_sync_enabled or not self.ntp_enabled:
            changed = (
                self._set_ntp_state("disabled", "NTP time source disabled") or changed
            )
            return changed

        if (
            self.latest_ntp_sample is not None
            and now_monotonic - self.latest_ntp_sample["monotonic"]
            > self.ntp_stale_seconds
        ):
            changed = self._set_ntp_state("stale", "NTP sample is stale") or changed

        if self.ntp_query_in_progress:
            return (
                self._set_ntp_state("querying", "Querying NTP server") or changed
            )

        due = (
            self.last_ntp_poll_monotonic is None
            or now_monotonic - self.last_ntp_poll_monotonic
            >= self.ntp_poll_interval_seconds
        )
        if not due:
            return changed

        server = self._effective_ntp_server()
        self.last_ntp_poll_monotonic = now_monotonic
        self.ntp_query_started_monotonic = now_monotonic
        self.ntp_query_in_progress = True

        if self.ntp_async:
            thread = threading.Thread(
                target=self._run_ntp_query,
                args=(server,),
                name="PiFinderNTP",
                daemon=True,
            )
            thread.start()
            return self._set_ntp_state("querying", "Querying NTP server") or changed

        self._run_ntp_query(server)
        return self._consume_ntp_result() or changed

    def _sync_block_reason(self) -> Optional[tuple[str, str]]:
        if not self.time_sync_enabled:
            return "disabled", "Time sync disabled"
        if self.selected_source is None:
            return "waiting_for_time_source", "Waiting for a stable time source"
        if self.state != "stable":
            return (
                "waiting_for_time_source",
                f"Waiting for stable time source; current state is {self.state}",
            )
        if self._selected_datetime() is None:
            return "waiting_for_time_source", "Selected time could not be parsed"
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
        sync_dt: datetime.datetime,
        actions: dict[str, Any],
    ) -> bool:
        latest = self.latest_sample or {}
        selected = self.selected_source or {}
        payload = {
            "version": 1,
            "request_id": self._request_id(actions),
            "created_monotonic": self.monotonic_fn(),
            "created_unix": self.time_fn(),
            "sync_time": sync_dt.isoformat(),
            "gps_time": sync_dt.isoformat(),
            "monitor_state": self.state,
            "status_file": str(self.status_file),
            "helper_status_file": str(self.helper_status_file),
            "actions": actions,
            "selected": {
                "source": selected.get("source"),
                "time": selected.get("time"),
                "valid": selected.get("valid"),
                "quality_seconds": selected.get("quality_seconds"),
                "server": selected.get("server"),
                "delay_seconds": selected.get("delay_seconds"),
                "tAcc_ns": selected.get("tAcc_ns"),
            },
            "latest": {
                "source": latest.get("source"),
                "valid": latest.get("valid"),
                "tAcc_ns": latest.get("tAcc_ns"),
                "message_class": latest.get("message_class"),
            },
            "sources": {
                "gps": self._gps_candidate(),
                "ntp": self._ntp_candidate(),
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
        sync_time = sync_dt.isoformat()
        message = str(result.get("message") or "Sync request written")
        changed = False
        if "system_clock" in actions:
            self.system_clock_request_count += 1
            self.last_system_clock_request_monotonic = now_monotonic
            self.last_system_clock_request_utc = sync_time
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
            self.last_rtc_request_utc = sync_time
            changed = (
                self._set_rtc_sync_state(
                    "requested", "RTC sync requested for privileged helper"
                )
                or changed
            )
        logger.info("Time sync helper request written: %s", message)
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

        sync_dt = self._selected_datetime()
        if sync_dt is None:
            return block_changed

        changed, system_clock_action = self._system_clock_request_action(sync_dt)
        changed = changed or block_changed
        rtc_changed, rtc_action = self._rtc_request_action(sync_dt)
        changed = rtc_changed or changed

        actions = {}
        if system_clock_action is not None:
            actions["system_clock"] = system_clock_action
        if rtc_action is not None:
            actions["rtc"] = rtc_action

        if actions:
            changed = self._write_sync_request(sync_dt, actions) or changed
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
        ntp_changed = self._poll_ntp(now_monotonic)
        ticked = self._poll_software_pps(now_monotonic)
        changed = False

        if self.enabled:
            if self.latest_sample is None:
                changed = (
                    self._set_gps_state("waiting_for_gps_time", "Waiting for GPS time")
                    or changed
                )
            elif now_monotonic - self.latest_sample["monotonic"] > self.stale_seconds:
                changed = self._set_gps_state(
                    "stale",
                    f"No GPS time sample for more than {self.stale_seconds:.0f}s",
                )
        elif self.software_pps_enabled:
            changed = (
                self._set_state("software_pps_only", "Software PPS enabled") or changed
            )

        changed = self._evaluate_state() or changed or ntp_changed
        changed = self._maybe_apply_sync_actions() or changed
        self.write_status(force=changed or ticked)

    def note_reset(self) -> None:
        if not self._active():
            return
        self.samples.clear()
        self.latest_sample = None
        changed = self._set_gps_state("waiting_for_gps_time", "PiFinder datetime reset")
        changed = self._evaluate_state() or changed
        changed = self._refresh_action_wait_states() or changed
        self.write_status(force=changed)

    def _read_helper_status(self) -> Optional[dict[str, Any]]:
        try:
            with open(self.helper_status_file, "r", encoding="utf-8") as helper_in:
                payload = json.load(helper_in)
        except FileNotFoundError:
            return None
        except Exception:
            logger.exception("Could not read time sync helper status")
            return {"state": "read_error"}
        return payload if isinstance(payload, dict) else {"state": "invalid_status"}

    def status_payload(self) -> dict[str, Any]:
        stats = self._offset_stats()
        latest = self.latest_sample or {}
        ntp_latest = self.latest_ntp_sample or {}
        age = None
        if latest.get("monotonic") is not None:
            age = self.monotonic_fn() - latest["monotonic"]
        ntp_age = None
        if ntp_latest.get("monotonic") is not None:
            ntp_age = self.monotonic_fn() - ntp_latest["monotonic"]

        return {
            "enabled": self.time_sync_enabled,
            "time_sync_enabled": self.time_sync_enabled,
            "state": self.state,
            "message": self.message,
            "updated_unix": self.time_fn(),
            "source_mode": self.source_mode,
            "selected": self.selected_source,
            "gps_time_sync_enabled": self.enabled,
            "gps_time_sync_state": self.gps_state,
            "gps_time_sync_message": self.gps_message,
            "ntp_time_sync_enabled": self.ntp_enabled,
            "ntp_time_sync_state": self.ntp_state,
            "ntp_time_sync_message": self.ntp_message,
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
            "ntp": {
                "enabled": self.ntp_enabled,
                "state": self.ntp_state,
                "message": self.ntp_message,
                "server": ntp_latest.get("server", self._effective_ntp_server()),
                "configured_server": self.ntp_server,
                "custom_server": self.ntp_server_custom,
                "time": ntp_latest.get("time"),
                "valid": ntp_latest.get("valid"),
                "stratum": ntp_latest.get("stratum"),
                "leap": ntp_latest.get("leap"),
                "offset_seconds": ntp_latest.get("offset_seconds"),
                "delay_seconds": ntp_latest.get("delay_seconds"),
                "root_delay_seconds": ntp_latest.get("root_delay_seconds"),
                "root_dispersion_seconds": ntp_latest.get("root_dispersion_seconds"),
                "quality_seconds": ntp_latest.get("quality_seconds"),
                "system_offset_seconds": ntp_latest.get("system_offset_seconds"),
                "age_seconds": ntp_age,
                "last_poll_monotonic": self.last_ntp_poll_monotonic,
                "poll_interval_seconds": self.ntp_poll_interval_seconds,
                "timeout_seconds": self.ntp_timeout_seconds,
                "max_delay_seconds": self.ntp_max_delay_seconds,
                "error": ntp_latest.get("error"),
            },
            "sources": {
                "gps": {
                    "enabled": self.enabled,
                    "state": self.gps_state,
                    "message": self.gps_message,
                    "candidate": self._gps_candidate(),
                },
                "ntp": {
                    "enabled": self.ntp_enabled,
                    "state": self.ntp_state,
                    "message": self.ntp_message,
                    "candidate": self._ntp_candidate(),
                },
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
            logger.exception("Could not write time sync status")
