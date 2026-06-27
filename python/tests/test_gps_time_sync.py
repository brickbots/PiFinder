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


class FakeRequestWriter:
    def __init__(self, ok=True):
        self.ok = ok
        self.requests = []
        self.clear_count = 0

    def write_request(self, payload):
        self.requests.append(payload)
        if not self.ok:
            return {"ok": False, "message": "request write failed"}
        return {"ok": True, "message": "request write ok"}

    def clear_request(self):
        self.clear_count += 1


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


def test_gps_time_monitor_flags_invalid_candidate(tmp_path):
    clock = FakeClock()
    status_file = tmp_path / "gps_time_status.json"
    monitor = GpsTimeSyncMonitor(
        enabled=True,
        status_file=status_file,
        time_fn=clock.time,
        monotonic_fn=clock.monotonic_time,
    )

    gps_dt = utc(11)
    monitor.observe_time(
        {
            "time": gps_dt,
            "valid": False,
            "source": "GPSD-SKY",
            "satellites_seen": 1,
            "satellites_used": 0,
        },
        gps_dt,
    )

    status = read_status(status_file)
    assert status["state"] == "low_quality"
    assert status["latest"]["valid"] is False
    assert status["latest"]["source"] == "GPSD-SKY"
    assert status["latest"]["satellites_seen"] == 1
    assert status["latest"]["satellites_used"] == 0


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


def test_system_clock_sync_writes_request_after_stable_gps(tmp_path):
    first_gps = utc(1)
    clock = FakeClock(unix=first_gps.timestamp() - 2.0)
    request_writer = FakeRequestWriter()
    status_file = tmp_path / "gps_time_status.json"
    monitor = GpsTimeSyncMonitor(
        enabled=True,
        system_clock_sync_enabled=True,
        min_samples=3,
        stable_jitter_ms=100,
        stable_offset_ms=500,
        system_clock_sync_step_threshold_ms=100,
        status_file=status_file,
        time_fn=clock.time,
        monotonic_fn=clock.monotonic_time,
        request_writer=request_writer,
    )

    for second, offset in [(1, 0.05), (2, 0.04), (3, 0.06)]:
        gps_dt = utc(second)
        monitor.observe_time(
            {"time": gps_dt, "tAcc": 10_000, "source": "GPS"},
            gps_dt - datetime.timedelta(seconds=offset),
        )
        clock.advance(1)

    status = read_status(status_file)
    assert status["state"] == "stable"
    assert status["system_clock_sync"]["state"] == "requested"
    assert status["system_clock_sync"]["request_count"] == 1
    assert status["system_clock_sync"]["last_offset_seconds"] == 2.0
    assert len(request_writer.requests) == 1
    request = request_writer.requests[0]
    assert request["gps_time"] == utc(3).isoformat()
    assert request["monitor_state"] == "stable"
    assert request["actions"]["system_clock"]["offset_seconds"] == 2.0


def test_system_clock_sync_waits_for_valid_stable_gps(tmp_path):
    clock = FakeClock()
    request_writer = FakeRequestWriter()
    status_file = tmp_path / "gps_time_status.json"
    monitor = GpsTimeSyncMonitor(
        enabled=True,
        system_clock_sync_enabled=True,
        status_file=status_file,
        time_fn=clock.time,
        monotonic_fn=clock.monotonic_time,
        request_writer=request_writer,
    )

    gps_dt = utc(10)
    monitor.observe_time(
        {"time": gps_dt, "valid": False, "source": "GPSD-SKY"},
        gps_dt,
    )

    status = read_status(status_file)
    assert status["state"] == "low_quality"
    assert status["system_clock_sync"]["state"] == "waiting_for_stable_gps"
    assert request_writer.requests == []
    assert request_writer.clear_count == 1


def test_system_clock_sync_skips_small_offset(tmp_path):
    first_gps = utc(1)
    clock = FakeClock(unix=first_gps.timestamp() - 0.05)
    request_writer = FakeRequestWriter()
    status_file = tmp_path / "gps_time_status.json"
    monitor = GpsTimeSyncMonitor(
        enabled=True,
        system_clock_sync_enabled=True,
        min_samples=2,
        stable_jitter_ms=100,
        stable_offset_ms=500,
        system_clock_sync_step_threshold_ms=500,
        status_file=status_file,
        time_fn=clock.time,
        monotonic_fn=clock.monotonic_time,
        request_writer=request_writer,
    )

    for second in [1, 2]:
        gps_dt = utc(second)
        monitor.observe_time(
            {"time": gps_dt, "source": "GPS"},
            gps_dt - datetime.timedelta(seconds=0.05),
        )
        clock.advance(1)

    status = read_status(status_file)
    assert status["state"] == "stable"
    assert status["system_clock_sync"]["state"] == "in_sync"
    assert request_writer.requests == []


def test_rtc_sync_writes_request_after_stable_gps(tmp_path):
    clock = FakeClock()
    request_writer = FakeRequestWriter()
    status_file = tmp_path / "gps_time_status.json"
    monitor = GpsTimeSyncMonitor(
        enabled=True,
        rtc_sync_enabled=True,
        min_samples=2,
        stable_jitter_ms=100,
        stable_offset_ms=500,
        status_file=status_file,
        time_fn=clock.time,
        monotonic_fn=clock.monotonic_time,
        request_writer=request_writer,
    )

    for second in [1, 2]:
        gps_dt = utc(second)
        monitor.observe_time(
            {"time": gps_dt, "source": "GPS"},
            gps_dt - datetime.timedelta(seconds=0.05),
        )
        clock.advance(1)

    status = read_status(status_file)
    assert status["state"] == "stable"
    assert status["rtc_sync"]["state"] == "requested"
    assert status["rtc_sync"]["request_count"] == 1
    assert len(request_writer.requests) == 1
    request = request_writer.requests[0]
    assert request["gps_time"] == utc(2).isoformat()
    assert request["actions"]["rtc"]["enabled"] is True
