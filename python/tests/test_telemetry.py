"""
Unit tests for telemetry recording, replay, and the TelemetryManager facade.
"""

import json
import queue
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import quaternion as quaternion_module

from PiFinder.telemetry import (
    TelemetryManager,
    TelemetryPlayer,
    TelemetryRecorder,
    _serialize_quat,
)


# ── Helpers ──────────────────────────────────────────────────────────


def _make_quat(w=1.0, x=0.0, y=0.0, z=0.0):
    return quaternion_module.quaternion(w, x, y, z)


def _make_location(lat=40.0, lon=-74.0, alt=100.0):
    loc = MagicMock()
    loc.lat = lat
    loc.lon = lon
    loc.altitude = alt
    loc.lock = False
    loc.source = "gps"
    return loc


def _make_shared_state(location=None, dt=None):
    ss = MagicMock()
    ss.location.return_value = location or _make_location()
    ss.datetime.return_value = dt
    return ss


def _make_cfg(telemetry_record=False, telemetry_images=False, imu_integrator="flat"):
    cfg = MagicMock()

    def get_option(key):
        return {
            "telemetry_record": telemetry_record,
            "telemetry_images": telemetry_images,
            "imu_integrator": imu_integrator,
        }.get(key)

    cfg.get_option = get_option
    return cfg


def _write_session_jsonl(path, events, header=None):
    """Write a list of event dicts to a JSONL file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        if header:
            f.write(json.dumps(header) + "\n")
        for ev in events:
            f.write(json.dumps(ev) + "\n")


# ── _serialize_quat ──────────────────────────────────────────────────


@pytest.mark.unit
class TestSerializeQuat:
    def test_none(self):
        assert _serialize_quat(None) is None

    def test_valid(self):
        q = _make_quat(1.0, 2.0, 3.0, 4.0)
        result = _serialize_quat(q)
        assert result == [1.0, 2.0, 3.0, 4.0]

    def test_non_quaternion(self):
        assert _serialize_quat("not a quat") is None

    def test_identity(self):
        q = _make_quat(1.0, 0.0, 0.0, 0.0)
        assert _serialize_quat(q) == [1.0, 0.0, 0.0, 0.0]


# ── TelemetryRecorder ───────────────────────────────────────────────


@pytest.mark.unit
class TestTelemetryRecorder:
    def test_disabled_by_default(self):
        rec = TelemetryRecorder()
        assert not rec.enabled

    def test_record_imu_noop_when_disabled(self):
        rec = TelemetryRecorder()
        rec.record_imu({"quat": _make_quat(), "pos": [0, 0, 0]})
        assert len(rec._buffer) == 0

    def test_record_solve_noop_when_disabled(self):
        rec = TelemetryRecorder()
        result = rec.record_solve({"RA": 180.0, "Dec": 45.0})
        assert result is None
        assert len(rec._buffer) == 0

    def test_record_solve_noop_for_none(self):
        rec = TelemetryRecorder()
        rec.enabled = True
        result = rec.record_solve(None)
        assert result is None

    def test_start_creates_session(self, tmp_path):
        with patch("PiFinder.telemetry.TELEMETRY_DIR", tmp_path / "telemetry"):
            rec = TelemetryRecorder()
            cfg = _make_cfg(imu_integrator="flat")
            ss = _make_shared_state()
            rec.start(cfg, ss)
            try:
                assert rec.enabled
                assert rec._session_dir is not None
                assert rec._session_dir.exists()
                assert len(rec._buffer) == 1  # header
            finally:
                rec.stop()

    def test_stop_flushes_and_closes(self, tmp_path):
        with patch("PiFinder.telemetry.TELEMETRY_DIR", tmp_path / "telemetry"):
            rec = TelemetryRecorder()
            rec.start(_make_cfg(), _make_shared_state())
            session_file = rec._session_dir / "session.jsonl"
            rec.stop()
            assert not rec.enabled
            assert rec._file is None
            assert rec._session_dir is None
            content = session_file.read_text()
            assert '"e": "hdr"' in content

    def test_record_imu_when_enabled(self, tmp_path):
        with patch("PiFinder.telemetry.TELEMETRY_DIR", tmp_path / "telemetry"):
            rec = TelemetryRecorder()
            rec.start(_make_cfg(), _make_shared_state())
            try:
                rec.record_imu(
                    {
                        "quat": _make_quat(1, 0, 0, 0),
                        "pos": [1.0, 2.0, 3.0],
                        "moving": True,
                        "status": 3,
                    }
                )
                assert len(rec._buffer) == 2  # header + imu
                line = json.loads(rec._buffer[-1])
                assert line["e"] == "imu"
                assert line["q"] == [1.0, 0.0, 0.0, 0.0]
                assert line["mv"] is True
            finally:
                rec.stop()

    def test_record_solve_when_enabled(self, tmp_path):
        with patch("PiFinder.telemetry.TELEMETRY_DIR", tmp_path / "telemetry"):
            rec = TelemetryRecorder()
            rec.start(_make_cfg(), _make_shared_state())
            try:
                t = rec.record_solve(
                    {
                        "RA": 180.0,
                        "Dec": 45.0,
                        "Roll": 10.0,
                        "camera_center": {"RA": 180.1, "Dec": 44.9, "Roll": 10.0},
                        "imu_quat": _make_quat(1, 0, 0, 0),
                    },
                    predicted_ra=179.5,
                    predicted_dec=44.8,
                )
                assert t is not None
                assert len(rec._buffer) == 2  # header + solve
                line = json.loads(rec._buffer[-1])
                assert line["e"] == "solve"
                assert line["ra"] == 180.0
                assert line["pred_ra"] == 179.5
                assert line["cam_ra"] == 180.1
            finally:
                rec.stop()

    def test_flush_time_gated(self, tmp_path):
        with patch("PiFinder.telemetry.TELEMETRY_DIR", tmp_path / "telemetry"):
            rec = TelemetryRecorder()
            rec.start(_make_cfg(), _make_shared_state())
            try:
                rec._last_flush = time.time()
                rec.flush()
                # Buffer should NOT be flushed (< 5s elapsed)
                assert len(rec._buffer) == 1  # header still in buffer
            finally:
                rec.stop()

    def test_do_flush_writes_to_file(self, tmp_path):
        with patch("PiFinder.telemetry.TELEMETRY_DIR", tmp_path / "telemetry"):
            rec = TelemetryRecorder()
            rec.start(_make_cfg(), _make_shared_state())
            try:
                rec.record_imu({"quat": _make_quat(), "pos": None})
                rec._do_flush()
                assert len(rec._buffer) == 0
                content = (rec._session_dir / "session.jsonl").read_text()
                lines = [l for l in content.strip().split("\n") if l]
                assert len(lines) == 2  # header + imu
            finally:
                rec.stop()

    def test_get_session_dir(self, tmp_path):
        with patch("PiFinder.telemetry.TELEMETRY_DIR", tmp_path / "telemetry"):
            rec = TelemetryRecorder()
            assert rec.get_session_dir() is None
            rec.start(_make_cfg(), _make_shared_state())
            try:
                assert rec.get_session_dir() is not None
            finally:
                rec.stop()
            assert rec.get_session_dir() is None

    def test_stop_idempotent(self):
        rec = TelemetryRecorder()
        rec.stop()  # no-op
        rec.stop()  # still no-op


# ── TelemetryPlayer ─────────────────────────────────────────────────


@pytest.mark.unit
class TestTelemetryPlayer:
    def test_load_from_file(self, tmp_path):
        events = [
            {"t": 1000.0, "e": "imu", "q": [1, 0, 0, 0], "mv": False},
            {"t": 1001.0, "e": "solve", "ra": 180.0, "dec": 45.0},
        ]
        hdr = {"t": 999.0, "e": "hdr", "loc": [40.0, -74.0, 100.0]}
        session_file = tmp_path / "session.jsonl"
        _write_session_jsonl(session_file, events, header=hdr)

        player = TelemetryPlayer(session_file)
        assert player.header is not None
        assert player.header["e"] == "hdr"
        assert len(player.events) == 2
        assert player.total_events == 2

    def test_load_from_directory(self, tmp_path):
        events = [{"t": 1000.0, "e": "imu", "q": [1, 0, 0, 0]}]
        _write_session_jsonl(tmp_path / "session.jsonl", events)
        player = TelemetryPlayer(tmp_path)
        assert len(player.events) == 1

    def test_progress(self, tmp_path):
        events = [
            {"t": 1000.0, "e": "imu", "q": [1, 0, 0, 0]},
            {"t": 1001.0, "e": "imu", "q": [1, 0, 0, 0]},
        ]
        _write_session_jsonl(tmp_path / "session.jsonl", events)
        player = TelemetryPlayer(tmp_path)
        assert player.progress == 0.0
        assert player.current_index == 0

    def test_progress_empty(self, tmp_path):
        _write_session_jsonl(tmp_path / "session.jsonl", [])
        player = TelemetryPlayer(tmp_path)
        assert player.progress == 1.0

    def test_get_next_event_timing(self, tmp_path):
        now = time.time()
        events = [
            {"t": now, "e": "imu", "q": [1, 0, 0, 0]},
            {"t": now + 100.0, "e": "imu", "q": [1, 0, 0, 0]},
        ]
        _write_session_jsonl(tmp_path / "session.jsonl", events)
        player = TelemetryPlayer(tmp_path)

        event, done = player.get_next_event()
        assert event is not None
        assert event["e"] == "imu"
        assert not done

        # Second event is 100s in the future, should not be ready
        event2, done2 = player.get_next_event()
        assert event2 is None
        assert not done2

    def test_get_next_event_done(self, tmp_path):
        now = time.time()
        events = [{"t": now, "e": "imu", "q": [1, 0, 0, 0]}]
        _write_session_jsonl(tmp_path / "session.jsonl", events)
        player = TelemetryPlayer(tmp_path)

        event, done = player.get_next_event()
        assert event is not None
        assert done  # last event

        event2, done2 = player.get_next_event()
        assert event2 is None
        assert done2

    def test_reset(self, tmp_path):
        now = time.time()
        events = [{"t": now, "e": "imu", "q": [1, 0, 0, 0]}]
        _write_session_jsonl(tmp_path / "session.jsonl", events)
        player = TelemetryPlayer(tmp_path)

        player.get_next_event()
        assert player.current_index == 1
        player.reset()
        assert player.current_index == 0
        assert player._replay_start is None

    def test_event_to_solve_dict(self):
        event = {
            "ra": 180.0,
            "dec": 45.0,
            "roll": 10.0,
            "cam_ra": 180.1,
            "cam_dec": 44.9,
            "cam_roll": 10.0,
            "matches": 15,
            "rmse": 0.5,
            "iq": [1.0, 0.0, 0.0, 0.0],
        }
        result = TelemetryPlayer.event_to_solve_dict(event)
        assert result["RA"] == 180.0
        assert result["Dec"] == 45.0
        assert result["Roll"] == 10.0
        assert result["camera_center"]["RA"] == 180.1
        assert result["Matches"] == 15
        assert result["solve_source"] == "CAM"
        assert isinstance(result["imu_quat"], quaternion_module.quaternion)
        assert result["imu_quat"].w == 1.0

    def test_event_to_solve_dict_no_imu_quat(self):
        event = {"ra": 180.0, "dec": 45.0}
        result = TelemetryPlayer.event_to_solve_dict(event)
        assert result["RA"] == 180.0
        assert "imu_quat" not in result

    def test_event_to_imu_dict(self):
        event = {"q": [1.0, 0.0, 0.0, 0.0], "mv": True, "st": 3}
        result = TelemetryPlayer.event_to_imu_dict(event)
        assert result is not None
        assert isinstance(result["quat"], quaternion_module.quaternion)
        assert result["moving"] is True
        assert result["status"] == 3

    def test_event_to_imu_dict_no_quat(self):
        event = {"mv": False}
        assert TelemetryPlayer.event_to_imu_dict(event) is None

    def test_event_to_imu_dict_defaults(self):
        event = {"q": [1.0, 0.0, 0.0, 0.0]}
        result = TelemetryPlayer.event_to_imu_dict(event)
        assert result["moving"] is False
        assert result["status"] == 0


# ── TelemetryManager ────────────────────────────────────────────────


@pytest.mark.unit
class TestTelemetryManager:
    def test_init_no_auto_record(self):
        cfg = _make_cfg(telemetry_record=False)
        ss = _make_shared_state()
        cq = queue.Queue()
        mgr = TelemetryManager(cfg, ss, cq)
        assert not mgr.replaying
        assert not mgr._recorder.enabled

    def test_init_auto_record(self, tmp_path):
        with patch("PiFinder.telemetry.TELEMETRY_DIR", tmp_path / "telemetry"):
            cfg = _make_cfg(telemetry_record=True)
            ss = _make_shared_state()
            cq = queue.Queue()
            mgr = TelemetryManager(cfg, ss, cq)
            try:
                assert mgr._recorder.enabled
            finally:
                mgr.stop()

    def test_poll_commands_none_queue(self):
        mgr = TelemetryManager(_make_cfg(), _make_shared_state(), queue.Queue())
        mgr.poll_commands(None)  # no-op

    def test_poll_commands_empty_queue(self):
        mgr = TelemetryManager(_make_cfg(), _make_shared_state(), queue.Queue())
        cmd_q = queue.Queue()
        mgr.poll_commands(cmd_q)  # no-op

    def test_handle_command_record_on(self, tmp_path):
        with patch("PiFinder.telemetry.TELEMETRY_DIR", tmp_path / "telemetry"):
            cq = queue.Queue()
            mgr = TelemetryManager(_make_cfg(), _make_shared_state(), cq)
            mgr._handle_command("telemetry_record_on", None)
            try:
                assert mgr._recorder.enabled
                assert cq.get_nowait() == "Telemetry: Recording"
            finally:
                mgr.stop()

    def test_handle_command_record_off(self, tmp_path):
        with patch("PiFinder.telemetry.TELEMETRY_DIR", tmp_path / "telemetry"):
            cq = queue.Queue()
            mgr = TelemetryManager(_make_cfg(), _make_shared_state(), cq)
            mgr._handle_command("telemetry_record_on", None)
            cq.get_nowait()  # drain "Recording" msg
            mgr._handle_command("telemetry_record_off", None)
            assert not mgr._recorder.enabled
            assert cq.get_nowait() == "Telemetry: Stopped"

    def test_handle_command_replay(self, tmp_path):
        events = [{"t": 1000.0, "e": "imu", "q": [1, 0, 0, 0]}]
        _write_session_jsonl(tmp_path / "session.jsonl", events)

        cq = queue.Queue()
        mgr = TelemetryManager(_make_cfg(), _make_shared_state(), cq)
        mgr._handle_command("replay", str(tmp_path))
        assert mgr.replaying
        assert cq.get_nowait() == "Telemetry: Replay started"

    def test_handle_command_replay_with_header(self, tmp_path):
        hdr = {
            "t": 999.0,
            "e": "hdr",
            "loc": [35.0, -120.0, 200.0],
            "dt": "2024-01-15T22:30:00",
        }
        events = [{"t": 1000.0, "e": "imu", "q": [1, 0, 0, 0]}]
        _write_session_jsonl(tmp_path / "session.jsonl", events, header=hdr)

        ss = _make_shared_state()
        cq = queue.Queue()
        mgr = TelemetryManager(_make_cfg(), ss, cq)
        mgr._handle_command("replay", str(tmp_path))

        ss.set_location.assert_called_once()
        ss.set_datetime.assert_called_once()

    def test_handle_command_replay_stop(self, tmp_path):
        events = [{"t": 1000.0, "e": "imu", "q": [1, 0, 0, 0]}]
        _write_session_jsonl(tmp_path / "session.jsonl", events)

        cq = queue.Queue()
        cam_q = queue.Queue()
        mgr = TelemetryManager(_make_cfg(), _make_shared_state(), cq, cam_q)
        mgr._handle_command("replay", str(tmp_path))
        cq.get_nowait()  # drain "Replay started"

        mgr._handle_command("replay_stop", None)
        assert not mgr.replaying
        assert cq.get_nowait() == "Telemetry: Replay stopped"
        assert cam_q.get_nowait() == "start"

    def test_next_replay_event_not_replaying(self):
        mgr = TelemetryManager(_make_cfg(), _make_shared_state(), queue.Queue())
        assert mgr.next_replay_event() is None

    def test_next_replay_event_auto_finish(self, tmp_path):
        now = time.time()
        events = [{"t": now, "e": "imu", "q": [1, 0, 0, 0]}]
        _write_session_jsonl(tmp_path / "session.jsonl", events)

        cq = queue.Queue()
        cam_q = queue.Queue()
        mgr = TelemetryManager(_make_cfg(), _make_shared_state(), cq, cam_q)
        mgr._handle_command("replay", str(tmp_path))
        cq.get_nowait()  # drain "Replay started"

        # First call returns the event
        event = mgr.next_replay_event()
        assert event is not None

        # Next call: done → auto-cleanup
        event2 = mgr.next_replay_event()
        assert event2 is None
        assert not mgr.replaying
        assert cq.get_nowait() == "Telemetry: Replay finished"
        assert cam_q.get_nowait() == "start"

    def test_record_solve_delegates(self):
        mgr = TelemetryManager(_make_cfg(), _make_shared_state(), queue.Queue())
        mgr._recorder = MagicMock()
        mgr._recorder.record_solve.return_value = None
        mgr.record_solve({"RA": 180.0})
        mgr._recorder.record_solve.assert_called_once()

    def test_record_solve_sends_image_command(self, tmp_path):
        with patch("PiFinder.telemetry.TELEMETRY_DIR", tmp_path / "telemetry"):
            cam_q = queue.Queue()
            cfg = _make_cfg(telemetry_images=True)
            mgr = TelemetryManager(cfg, _make_shared_state(), queue.Queue(), cam_q)
            mgr._recorder.start(_make_cfg(), _make_shared_state())
            mgr._recorder.images_enabled = True
            try:
                mgr.record_solve({"RA": 180.0, "Dec": 45.0})
                msg = cam_q.get_nowait()
                assert msg.startswith("save_image:")
            finally:
                mgr.stop()

    def test_record_imu_delegates(self):
        mgr = TelemetryManager(_make_cfg(), _make_shared_state(), queue.Queue())
        mgr._recorder = MagicMock()
        mgr.record_imu({"quat": _make_quat()})
        mgr._recorder.record_imu.assert_called_once()

    def test_flush_delegates(self):
        mgr = TelemetryManager(_make_cfg(), _make_shared_state(), queue.Queue())
        mgr._recorder = MagicMock()
        mgr.flush()
        mgr._recorder.flush.assert_called_once()

    def test_stop_delegates(self):
        mgr = TelemetryManager(_make_cfg(), _make_shared_state(), queue.Queue())
        mgr._recorder = MagicMock()
        mgr.stop()
        mgr._recorder.stop.assert_called_once()

    def test_poll_commands_dispatches_tuple(self, tmp_path):
        with patch("PiFinder.telemetry.TELEMETRY_DIR", tmp_path / "telemetry"):
            cq = queue.Queue()
            mgr = TelemetryManager(_make_cfg(), _make_shared_state(), cq)
            cmd_q = queue.Queue()
            cmd_q.put(("telemetry_record_on", None))
            mgr.poll_commands(cmd_q)
            try:
                assert mgr._recorder.enabled
            finally:
                mgr.stop()

    def test_poll_commands_ignores_non_tuple(self):
        cq = queue.Queue()
        mgr = TelemetryManager(_make_cfg(), _make_shared_state(), cq)
        cmd_q = queue.Queue()
        cmd_q.put("not a tuple")
        mgr.poll_commands(cmd_q)  # should not crash

    def test_restart_camera_no_queue(self):
        mgr = TelemetryManager(
            _make_cfg(), _make_shared_state(), queue.Queue(), None
        )
        mgr._restart_camera()  # no-op, no crash


# ── pointing.py ──────────────────────────────────────────────────────


@pytest.mark.unit
class TestGetRollByMountType:
    def test_eq_mount_returns_zero(self):
        from PiFinder.pointing import get_roll_by_mount_type

        roll = get_roll_by_mount_type(180.0, 45.0, None, None, "EQ")
        assert roll == 0.0

    def test_eq_mount_southern_hemisphere(self):
        from PiFinder.pointing import get_roll_by_mount_type

        loc = _make_location(lat=-35.0)
        roll = get_roll_by_mount_type(180.0, 45.0, loc, None, "EQ")
        assert roll == 180.0

    def test_altaz_no_location_returns_zero(self):
        from PiFinder.pointing import get_roll_by_mount_type

        roll = get_roll_by_mount_type(180.0, 45.0, None, None, "Alt/Az")
        assert roll == 0.0

    def test_unknown_mount_returns_zero(self):
        from PiFinder.pointing import get_roll_by_mount_type

        roll = get_roll_by_mount_type(180.0, 45.0, None, None, "Dobsonian")
        assert roll == 0.0


@pytest.mark.unit
class TestUpdatePlateSolveAndImu:
    def test_returns_early_on_none_ra(self):
        from PiFinder.pointing import update_plate_solve_and_imu

        imu_dr = MagicMock()
        solved = {"RA": None, "Dec": 45.0}
        update_plate_solve_and_imu(imu_dr, solved)
        imu_dr.update_plate_solve_and_imu.assert_not_called()

    def test_returns_early_on_none_dec(self):
        from PiFinder.pointing import update_plate_solve_and_imu

        imu_dr = MagicMock()
        solved = {"RA": 180.0, "Dec": None}
        update_plate_solve_and_imu(imu_dr, solved)
        imu_dr.update_plate_solve_and_imu.assert_not_called()


@pytest.mark.unit
class TestUpdateImu:
    def test_returns_early_no_last_image_solve(self):
        from PiFinder.pointing import update_imu

        imu_dr = MagicMock()
        imu_dr.tracking = True
        solved = {"RA": 180.0}
        imu = {"quat": _make_quat()}
        update_imu(imu_dr, solved, None, imu)
        imu_dr.update_imu.assert_not_called()

    def test_returns_early_not_tracking(self):
        from PiFinder.pointing import update_imu

        imu_dr = MagicMock()
        imu_dr.tracking = False
        solved = {"RA": 180.0}
        last = {"imu_quat": _make_quat()}
        imu = {"quat": _make_quat()}
        update_imu(imu_dr, solved, last, imu)
        imu_dr.update_imu.assert_not_called()
