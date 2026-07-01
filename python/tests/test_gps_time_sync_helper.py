import datetime
import json

import pytz

from PiFinder.gps_time_sync_helper import GpsTimeSyncHelper


class FakeClock:
    def __init__(self, unix=1_700_000_000.0, monotonic=100.0):
        self.unix = unix
        self.monotonic = monotonic

    def time(self):
        return self.unix

    def monotonic_time(self):
        return self.monotonic


class FakeRunner:
    def __init__(self, system_ok=True, rtc_ok=True):
        self.system_ok = system_ok
        self.rtc_ok = rtc_ok
        self.system_calls = []
        self.rtc_calls = []

    def set_system_clock(self, gps_dt):
        self.system_calls.append(gps_dt)
        return {"ok": self.system_ok, "message": "system synced"}

    def set_rtc(self, gps_dt):
        self.rtc_calls.append(gps_dt)
        return {"ok": self.rtc_ok, "message": "rtc synced"}


def utc(second):
    return datetime.datetime(2026, 1, 1, 0, 0, second, tzinfo=pytz.UTC)


def write_request(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def valid_request(clock, gps_dt, actions):
    return {
        "version": 1,
        "request_id": "req-1",
        "boot_id": "boot-a",
        "created_monotonic": clock.monotonic,
        "created_unix": clock.unix,
        "gps_time": gps_dt.isoformat(),
        "monitor_state": "stable",
        "latest": {"valid": True, "source": "GPS", "tAcc_ns": 10_000},
        "actions": actions,
    }


def test_helper_processes_valid_system_clock_and_rtc_request(tmp_path):
    gps_dt = utc(5)
    clock = FakeClock(unix=gps_dt.timestamp() - 2.0)
    runner = FakeRunner()
    request_file = tmp_path / "request.json"
    status_file = tmp_path / "helper_status.json"
    write_request(
        request_file,
        valid_request(
            clock,
            gps_dt,
            {
                "system_clock": {
                    "enabled": True,
                    "step_threshold_seconds": 0.1,
                },
                "rtc": {"enabled": True},
            },
        ),
    )
    helper = GpsTimeSyncHelper(
        request_file=request_file,
        status_file=status_file,
        runner=runner,
        time_fn=clock.time,
        monotonic_fn=clock.monotonic_time,
        boot_id_fn=lambda: "boot-a",
    )

    status = helper.process_once()

    assert status["state"] == "completed"
    assert runner.system_calls == [gps_dt]
    assert runner.rtc_calls == [gps_dt]
    saved_status = json.loads(status_file.read_text())
    assert saved_status["last_request_id"] == "req-1"
    assert saved_status["results"]["system_clock"]["state"] == "synced"
    assert saved_status["results"]["rtc"]["state"] == "synced"


def test_helper_skips_system_clock_when_already_in_sync(tmp_path):
    gps_dt = utc(5)
    clock = FakeClock(unix=gps_dt.timestamp() - 0.05)
    runner = FakeRunner()
    request_file = tmp_path / "request.json"
    status_file = tmp_path / "helper_status.json"
    write_request(
        request_file,
        valid_request(
            clock,
            gps_dt,
            {
                "system_clock": {
                    "enabled": True,
                    "step_threshold_seconds": 0.5,
                }
            },
        ),
    )
    helper = GpsTimeSyncHelper(
        request_file=request_file,
        status_file=status_file,
        runner=runner,
        time_fn=clock.time,
        monotonic_fn=clock.monotonic_time,
        boot_id_fn=lambda: "boot-a",
    )

    status = helper.process_once()

    assert status["state"] == "completed"
    assert runner.system_calls == []
    saved_status = json.loads(status_file.read_text())
    assert saved_status["results"]["system_clock"]["state"] == "in_sync"


def test_helper_rejects_invalid_or_stale_request(tmp_path):
    gps_dt = utc(5)
    clock = FakeClock(unix=gps_dt.timestamp(), monotonic=500.0)
    runner = FakeRunner()
    request_file = tmp_path / "request.json"
    status_file = tmp_path / "helper_status.json"
    request = valid_request(clock, gps_dt, {"rtc": {"enabled": True}})
    request["created_monotonic"] = 100.0
    write_request(request_file, request)
    helper = GpsTimeSyncHelper(
        request_file=request_file,
        status_file=status_file,
        max_request_age_seconds=120.0,
        runner=runner,
        time_fn=clock.time,
        monotonic_fn=clock.monotonic_time,
        boot_id_fn=lambda: "boot-a",
    )

    status = helper.process_once()

    assert status["state"] == "invalid_request"
    assert "stale" in status["message"]
    assert runner.rtc_calls == []


def test_helper_does_not_reprocess_same_request_after_restart(tmp_path):
    gps_dt = utc(5)
    clock = FakeClock(unix=gps_dt.timestamp() - 2.0)
    runner = FakeRunner()
    request_file = tmp_path / "request.json"
    status_file = tmp_path / "helper_status.json"
    request = valid_request(clock, gps_dt, {"rtc": {"enabled": True}})
    write_request(request_file, request)
    status_file.write_text(
        json.dumps({"last_request_id": request["request_id"]}),
        encoding="utf-8",
    )
    helper = GpsTimeSyncHelper(
        request_file=request_file,
        status_file=status_file,
        runner=runner,
        time_fn=clock.time,
        monotonic_fn=clock.monotonic_time,
        boot_id_fn=lambda: "boot-a",
    )

    status = helper.process_once()

    assert status["state"] == "idle"
    assert runner.rtc_calls == []


def test_helper_accepts_selected_ntp_time_source(tmp_path):
    sync_dt = utc(8)
    clock = FakeClock(unix=sync_dt.timestamp() - 2.0)
    runner = FakeRunner()
    request_file = tmp_path / "request.json"
    status_file = tmp_path / "helper_status.json"
    request = valid_request(
        clock,
        sync_dt,
        {
            "system_clock": {
                "enabled": True,
                "step_threshold_seconds": 0.1,
            }
        },
    )
    request["sync_time"] = sync_dt.isoformat()
    request["selected"] = {
        "source": "NTP",
        "time": sync_dt.isoformat(),
        "valid": True,
        "quality_seconds": 0.02,
        "server": "pool.ntp.org",
    }
    request["latest"] = {"valid": False, "source": "GPS"}
    write_request(request_file, request)
    helper = GpsTimeSyncHelper(
        request_file=request_file,
        status_file=status_file,
        runner=runner,
        time_fn=clock.time,
        monotonic_fn=clock.monotonic_time,
        boot_id_fn=lambda: "boot-a",
    )

    status = helper.process_once()

    assert status["state"] == "completed"
    assert runner.system_calls == [sync_dt]
    saved_status = json.loads(status_file.read_text())
    assert saved_status["selected"]["source"] == "NTP"
    assert saved_status["last_sync_time"] == sync_dt.isoformat()
