import datetime
import json

import pytz

from PiFinder.gps_time_sync import GpsTimeSyncMonitor


class FakeClock:
    def __init__(self, unix=1_700_000_000.0, monotonic=100.0):
        self.unix = unix
        self.monotonic = monotonic

    def time(self):
        return self.unix

    def monotonic_time(self):
        return self.monotonic

    def advance(self, seconds):
        self.unix += seconds
        self.monotonic += seconds


def utc(second):
    return datetime.datetime(2026, 1, 1, 0, 0, second, tzinfo=pytz.UTC)


def read_status(path):
    return json.loads(path.read_text())


def test_gps_time_monitor_marks_stable_after_enough_samples(tmp_path):
    clock = FakeClock()
    status_file = tmp_path / "gps_time_status.json"
    monitor = GpsTimeSyncMonitor(
        enabled=True,
        min_samples=3,
        stable_jitter_ms=100,
        stable_offset_ms=500,
        status_file=status_file,
        time_fn=clock.time,
        monotonic_fn=clock.monotonic_time,
    )

    for second, offset in [(1, 0.05), (2, 0.04), (3, 0.06)]:
        gps_dt = utc(second)
        reference_dt = gps_dt - datetime.timedelta(seconds=offset)
        monitor.observe_time(
            {"time": gps_dt, "tAcc": 10_000, "source": "GPS"}, reference_dt
        )
        clock.advance(1)

    status = read_status(status_file)
    assert status["state"] == "stable"
    assert status["samples"]["count"] == 3
    assert status["offset"]["latest_seconds"] == 0.06
    assert status["offset"]["jitter_seconds"] < 0.03


def test_gps_time_monitor_flags_low_quality_time_accuracy(tmp_path):
    clock = FakeClock()
    status_file = tmp_path / "gps_time_status.json"
    monitor = GpsTimeSyncMonitor(
        enabled=True,
        max_tacc_ns=500_000,
        status_file=status_file,
        time_fn=clock.time,
        monotonic_fn=clock.monotonic_time,
    )

    gps_dt = utc(10)
    monitor.observe_time(
        {"time": gps_dt, "tAcc": 5_000_000, "source": "GPS"},
        gps_dt,
    )

    status = read_status(status_file)
    assert status["state"] == "low_quality"
    assert status["latest"]["tAcc_ns"] == 5_000_000


def test_gps_time_monitor_marks_samples_stale(tmp_path):
    clock = FakeClock()
    status_file = tmp_path / "gps_time_status.json"
    monitor = GpsTimeSyncMonitor(
        enabled=True,
        stale_seconds=5,
        status_file=status_file,
        time_fn=clock.time,
        monotonic_fn=clock.monotonic_time,
    )

    gps_dt = utc(20)
    monitor.observe_time({"time": gps_dt, "source": "GPS"}, gps_dt)
    clock.advance(6)
    monitor.poll()

    status = read_status(status_file)
    assert status["state"] == "stale"


def test_software_pps_records_ticks(tmp_path):
    clock = FakeClock(monotonic=100.2)
    status_file = tmp_path / "gps_time_status.json"
    monitor = GpsTimeSyncMonitor(
        software_pps_enabled=True,
        software_pps_interval_seconds=1.0,
        status_file=status_file,
        time_fn=clock.time,
        monotonic_fn=clock.monotonic_time,
    )

    monitor.poll()
    clock.advance(0.9)
    monitor.poll()
    clock.advance(1.0)
    monitor.poll()

    status = read_status(status_file)
    assert status["software_pps"]["enabled"] is True
    assert status["software_pps"]["tick_count"] == 2
    assert status["software_pps"]["last_tick_monotonic"] == 102.0


def test_startup_status_clears_stale_file_when_disabled(tmp_path):
    clock = FakeClock()
    status_file = tmp_path / "gps_time_status.json"
    status_file.write_text('{"state": "stable"}')
    monitor = GpsTimeSyncMonitor(
        enabled=False,
        software_pps_enabled=False,
        status_file=status_file,
        time_fn=clock.time,
        monotonic_fn=clock.monotonic_time,
    )

    monitor.write_startup_status()

    status = read_status(status_file)
    assert status["enabled"] is False
    assert status["state"] == "disabled"
