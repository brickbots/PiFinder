"""
Unit tests for telemetry recording, replay, and the TelemetryManager facade.
"""

import json
import queue
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import quaternion as quaternion_module

from PiFinder import telemetry as telemetry_module
from PiFinder.telemetry import (
    TelemetryManager,
    TelemetryPlayer,
    TelemetryRecorder,
    _serialize_quat,
)
from PiFinder.types.positioning import (
    FailedSolve,
    ImuSample,
    Pointing,
    SolveDiagnostics,
    SuccessfulSolve,
)


# ── Helpers ──────────────────────────────────────────────────────────


def _make_quat(w=1.0, x=0.0, y=0.0, z=0.0):
    return quaternion_module.quaternion(w, x, y, z)


def _make_imu_sample(
    quat=None, timestamp=1000.0, status=3, moving=False, gyro=None, accel=None
):
    return ImuSample(
        quat=quat or _make_quat(),
        timestamp=timestamp,
        status=status,
        moving=moving,
        gyro=gyro,
        accel=accel,
    )


def _make_successful_solve(
    ra=180.0,
    dec=45.0,
    roll=10.0,
    cam_ra=180.1,
    cam_dec=44.9,
    cam_roll=10.0,
    imu_anchor=None,
    last_solve_attempt=1000.4,
    last_solve_success=1000.5,
    matches=15,
    rmse=0.5,
):
    return SuccessfulSolve(
        camera=Pointing(RA=cam_ra, Dec=cam_dec, Roll=cam_roll),
        aligned=Pointing(RA=ra, Dec=dec, Roll=roll),
        imu_anchor=imu_anchor,
        last_solve_attempt=last_solve_attempt,
        last_solve_success=last_solve_success,
        diagnostics=SolveDiagnostics(Matches=matches, RMSE=rmse),
    )


def _make_failed_solve(last_solve_attempt=1000.4, last_solve_success=None):
    return FailedSolve(
        diagnostics=SolveDiagnostics(Matches=0),
        last_solve_attempt=last_solve_attempt,
        last_solve_success=last_solve_success,
    )


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


_ALL_SECTIONS = ["imu", "sqm", "solve", "target", "images"]


def _make_cfg(
    telemetry_record=False,
    screen_direction="flat",
    mount_type="Alt/Az",
    telemetry_sections=None,
    telemetry_max_session_mb=0,
):
    cfg = MagicMock()
    sections = list(_ALL_SECTIONS if telemetry_sections is None else telemetry_sections)

    def get_option(key):
        return {
            "telemetry_record": telemetry_record,
            "screen_direction": screen_direction,
            "mount_type": mount_type,
            "telemetry_sections": sections,
            "telemetry_max_session_mb": telemetry_max_session_mb,
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
        rec.record_imu(_make_imu_sample())
        assert len(rec._buffer) == 0

    def test_record_solve_noop_when_disabled(self):
        rec = TelemetryRecorder()
        result = rec.record_solve(_make_successful_solve())
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
            cfg = _make_cfg(screen_direction="flat")
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
            session_dir = rec._session_dir
            session_file = session_dir / "session.jsonl"
            rec.stop()
            assert not rec.enabled
            assert rec._file is None
            assert rec._session_dir is None
            content = session_file.read_text()
            assert '"e": "hdr"' in content
            # Location should be in separate file, not in header
            assert '"loc"' not in content
            loc_file = session_dir / "session.location"
            assert loc_file.exists()
            loc_data = json.loads(loc_file.read_text())
            assert loc_data["lat"] == 40.0

    def test_record_radio_noop_when_disabled(self):
        rec = TelemetryRecorder()
        rec.record_radio({"sequence": 1, "captured_at": 100.0})
        assert len(rec._buffer) == 0

    def test_record_radio_dedupes_and_rate_limits(self, tmp_path):
        with patch("PiFinder.telemetry.TELEMETRY_DIR", tmp_path / "telemetry"):
            rec = TelemetryRecorder()
            rec.start(_make_cfg(), _make_shared_state())
            try:
                base = len(rec._buffer)

                def sample(seq, t):
                    return {
                        "sequence": seq,
                        "captured_at": t,
                        "exposure_sec": 1.0,
                        "background_per_pixel": 515.0,
                        "background_mad": 28.0,
                        "background_gradient": 12.0,
                    }

                rec.record_radio(sample(1, 100.0))
                rec.record_radio(sample(1, 100.0))  # duplicate sequence: dropped
                rec.record_radio(sample(2, 100.5))  # <1 s later: dropped
                rec.record_radio(sample(3, 101.5))  # recorded
                rec.record_radio(None)  # no sample: dropped
                assert len(rec._buffer) - base == 2
                event = json.loads(rec._buffer[-1])
                assert event["e"] == "radio"
                assert event["seq"] == 3
                assert event["exp"] == 1.0
                assert event["bg"] == 515.0
                assert event["grad"] == 12.0
            finally:
                rec.stop()

    def test_record_radio_logs_ingredients_and_derived(self, tmp_path):
        with patch("PiFinder.telemetry.TELEMETRY_DIR", tmp_path / "telemetry"):
            rec = TelemetryRecorder()
            rec.start(_make_cfg(), _make_shared_state())
            try:
                rec.record_radio(
                    {
                        "sequence": 7,
                        "captured_at": 200.0,
                        "exposure_sec": 1.0,
                        "background_per_pixel": 515.0,
                        "background_mad": 28.0,
                        "background_gradient": 12.0,
                        "background_red": 540.0,
                        "background_blue": 470.0,
                        "optical_black_pedestal": 238.0,
                        "pixels_per_side": 512,
                    },
                    sqm=20.9,
                    floor=51.5,
                )
                event = json.loads(rec._buffer[-1])
                # raw ingredients — recompute-able under a future calculation
                assert event["bg"] == 515.0
                assert event["red"] == 540.0
                assert event["blue"] == 470.0
                assert event["ped"] == 238.0
                assert event["px"] == 512
                # derived audit values — what the device published
                assert event["sqm"] == 20.9
                assert event["floor"] == 51.5
            finally:
                rec.stop()

    def test_record_radio_optional_fields_default_none(self, tmp_path):
        """Mono sensor / no published SQM: optional fields serialize as None."""
        with patch("PiFinder.telemetry.TELEMETRY_DIR", tmp_path / "telemetry"):
            rec = TelemetryRecorder()
            rec.start(_make_cfg(), _make_shared_state())
            try:
                rec.record_radio(
                    {
                        "sequence": 1,
                        "captured_at": 100.0,
                        "exposure_sec": 1.0,
                        "background_per_pixel": 515.0,
                        "background_mad": 28.0,
                        "background_gradient": 12.0,
                    }
                )
                event = json.loads(rec._buffer[-1])
                for key in ("red", "blue", "ped", "px", "sqm", "floor"):
                    assert event[key] is None
            finally:
                rec.stop()

    def test_no_cap_by_default(self, tmp_path):
        with patch("PiFinder.telemetry.TELEMETRY_DIR", tmp_path / "telemetry"):
            rec = TelemetryRecorder()
            rec.start(_make_cfg(), _make_shared_state())
            try:
                assert rec.max_session_bytes == 0
                assert rec.images_capped is False
            finally:
                rec.stop()

    def test_session_cap_suspends_images(self, tmp_path):
        """Once the session dir exceeds the cap, frame capture is suspended."""
        with patch("PiFinder.telemetry.TELEMETRY_DIR", tmp_path / "telemetry"):
            rec = TelemetryRecorder()
            rec.start(_make_cfg(telemetry_max_session_mb=1), _make_shared_state())
            try:
                assert rec.max_session_bytes == 1024 * 1024
                rec._refresh_session_bytes()
                assert rec.images_capped is False  # header only, well under 1 MB

                # Simulate saved frames pushing the session past the cap.
                (rec.get_session_dir() / "img_1.png").write_bytes(b"x" * 1_200_000)
                rec._refresh_session_bytes()
                assert rec.session_bytes >= 1024 * 1024
                assert rec.images_capped is True
            finally:
                rec.stop()

    def test_header_snapshots_sqm_calibration(self, tmp_path):
        with patch("PiFinder.telemetry.TELEMETRY_DIR", tmp_path / "telemetry"):
            rec = TelemetryRecorder()
            ss = _make_shared_state()
            ss.camera_type.return_value = "imx462"
            rec.start(_make_cfg(), ss)
            try:
                cfg_hdr = json.loads(rec._buffer[0])["cfg"]
                assert cfg_hdr["camera_type"] == "imx462"
                cal = cfg_hdr["sqm_calibration"]
                # full profile is captured, not a hand-picked subset
                assert "radiometric_zero_point" in cal["profile"]
                assert "radiometric_fov_degrees" in cal["profile"]
                assert "bias_offset" in cal["profile"]
                # Airglow constants only exist on branches carrying the model.
                if telemetry_module.airglow is not None:
                    assert cal["airglow"]["red_response"] == 4.07
            finally:
                rec.stop()

    def test_header_calibration_mono_has_no_airglow(self, tmp_path):
        with patch("PiFinder.telemetry.TELEMETRY_DIR", tmp_path / "telemetry"):
            rec = TelemetryRecorder()
            ss = _make_shared_state()
            ss.camera_type.return_value = "imx296"  # mono: no airglow entry
            rec.start(_make_cfg(), ss)
            try:
                cal = json.loads(rec._buffer[0])["cfg"]["sqm_calibration"]
                assert "profile" in cal
                assert "airglow" not in cal
            finally:
                rec.stop()

    def test_header_calibration_none_for_unknown_camera(self, tmp_path):
        with patch("PiFinder.telemetry.TELEMETRY_DIR", tmp_path / "telemetry"):
            rec = TelemetryRecorder()
            ss = _make_shared_state()
            ss.camera_type.return_value = "no_such_cam"
            rec.start(_make_cfg(), ss)
            try:
                cfg_hdr = json.loads(rec._buffer[0])["cfg"]
                assert cfg_hdr["camera_type"] == "no_such_cam"
                assert cfg_hdr["sqm_calibration"] is None
            finally:
                rec.stop()

    def test_sections_default_all_on(self, tmp_path):
        with patch("PiFinder.telemetry.TELEMETRY_DIR", tmp_path / "telemetry"):
            rec = TelemetryRecorder()
            rec.start(_make_cfg(), _make_shared_state())
            try:
                assert rec.sections == {
                    "imu": True,
                    "sqm": True,
                    "solve": True,
                    "target": True,
                    "images": True,
                }
            finally:
                rec.stop()

    def test_imu_section_off_skips_imu_only(self, tmp_path):
        with patch("PiFinder.telemetry.TELEMETRY_DIR", tmp_path / "telemetry"):
            rec = TelemetryRecorder()
            rec.start(
                _make_cfg(telemetry_sections=["sqm", "solve", "target"]),
                _make_shared_state(),
            )
            try:
                base = len(rec._buffer)
                rec.record_imu(_make_imu_sample(moving=True))
                assert len(rec._buffer) == base  # IMU gated off
                rec.record_radio(
                    {
                        "sequence": 1,
                        "captured_at": 100.0,
                        "exposure_sec": 1.0,
                        "background_per_pixel": 515.0,
                        "background_mad": 28.0,
                        "background_gradient": 12.0,
                    }
                )
                assert len(rec._buffer) == base + 1  # SQM still records
            finally:
                rec.stop()

    def test_sqm_section_off_skips_radio(self, tmp_path):
        with patch("PiFinder.telemetry.TELEMETRY_DIR", tmp_path / "telemetry"):
            rec = TelemetryRecorder()
            rec.start(
                _make_cfg(telemetry_sections=["imu", "solve", "target"]),
                _make_shared_state(),
            )
            try:
                base = len(rec._buffer)
                rec.record_radio(
                    {
                        "sequence": 1,
                        "captured_at": 100.0,
                        "exposure_sec": 1.0,
                        "background_per_pixel": 515.0,
                    }
                )
                assert len(rec._buffer) == base
            finally:
                rec.stop()

    def test_solve_section_off_skips_solve(self, tmp_path):
        with patch("PiFinder.telemetry.TELEMETRY_DIR", tmp_path / "telemetry"):
            rec = TelemetryRecorder()
            rec.start(
                _make_cfg(telemetry_sections=["imu", "sqm", "target"]),
                _make_shared_state(),
            )
            try:
                base = len(rec._buffer)
                result = rec.record_solve(_make_successful_solve())
                assert result is None
                assert len(rec._buffer) == base
            finally:
                rec.stop()

    def test_target_section_off_skips_target(self, tmp_path):
        with patch("PiFinder.telemetry.TELEMETRY_DIR", tmp_path / "telemetry"):
            rec = TelemetryRecorder()
            rec.start(
                _make_cfg(telemetry_sections=["imu", "sqm", "solve"]),
                _make_shared_state(),
            )
            try:
                base = len(rec._buffer)
                target = MagicMock()
                target.object_id = 42
                target.display_name = "M31"
                target.ra = 10.68
                target.dec = 41.27
                rec.record_target(target, alt=45.0, az=90.0)
                assert len(rec._buffer) == base
            finally:
                rec.stop()

    def test_apply_sections_updates_live_recording(self, tmp_path):
        with patch("PiFinder.telemetry.TELEMETRY_DIR", tmp_path / "telemetry"):
            rec = TelemetryRecorder()
            rec.start(_make_cfg(), _make_shared_state())
            try:
                base = len(rec._buffer)
                rec.record_imu(_make_imu_sample(moving=True, timestamp=1000.0))
                assert len(rec._buffer) == base + 1  # recorded while on

                rec.apply_sections(
                    _make_cfg(telemetry_sections=["sqm", "solve", "target"])
                )
                assert rec.sections["imu"] is False
                # Distinct timestamp so IMU dedup can't mask the section gate.
                rec.record_imu(_make_imu_sample(moving=True, timestamp=1001.0))
                assert len(rec._buffer) == base + 1  # now gated off
            finally:
                rec.stop()

    def test_record_imu_when_enabled(self, tmp_path):
        with patch("PiFinder.telemetry.TELEMETRY_DIR", tmp_path / "telemetry"):
            rec = TelemetryRecorder()
            rec.start(_make_cfg(), _make_shared_state())
            try:
                rec.record_imu(
                    _make_imu_sample(
                        quat=_make_quat(1, 0, 0, 0),
                        moving=True,
                        status=3,
                        gyro=(0.01, -0.02, 0.03),
                        accel=(0.1, 0.2, -0.3),
                    )
                )
                assert len(rec._buffer) == 2  # header + imu
                line = json.loads(rec._buffer[-1])
                assert line["e"] == "imu"
                assert line["q"] == [1.0, 0.0, 0.0, 0.0]
                assert line["mv"] is True
                assert line["gyro"] == [0.01, -0.02, 0.03]
                assert line["accel"] == [0.1, 0.2, -0.3]
            finally:
                rec.stop()

    def test_record_imu_stationary_decimation(self, tmp_path):
        """Stationary samples are decimated; moving samples are not."""
        with patch("PiFinder.telemetry.TELEMETRY_DIR", tmp_path / "telemetry"):
            rec = TelemetryRecorder()
            rec.start(_make_cfg(), _make_shared_state())
            try:
                for i in range(10):
                    rec.record_imu(_make_imu_sample(moving=False, timestamp=1000.0 + i))
                # Only every 10th stationary sample is recorded
                assert len(rec._buffer) == 2  # header + 1 imu
                for i in range(3):
                    rec.record_imu(_make_imu_sample(moving=True, timestamp=2000.0 + i))
                assert len(rec._buffer) == 5  # + 3 moving samples
            finally:
                rec.stop()

    def test_record_imu_dedups_repolled_sample(self, tmp_path):
        """The same sample polled twice by a faster loop records once."""
        with patch("PiFinder.telemetry.TELEMETRY_DIR", tmp_path / "telemetry"):
            rec = TelemetryRecorder()
            rec.start(_make_cfg(), _make_shared_state())
            try:
                sample = _make_imu_sample(moving=True, timestamp=1000.0)
                rec.record_imu(sample)
                rec.record_imu(sample)
                rec.record_imu(sample)
                assert len(rec._buffer) == 2  # header + 1 imu
                rec.record_imu(_make_imu_sample(moving=True, timestamp=1000.1))
                assert len(rec._buffer) == 3
            finally:
                rec.stop()

    def test_record_imu_stamped_with_sample_time(self, tmp_path):
        """Records carry the IMU sample epoch, not the poll time."""
        with patch("PiFinder.telemetry.TELEMETRY_DIR", tmp_path / "telemetry"):
            rec = TelemetryRecorder()
            rec.start(_make_cfg(), _make_shared_state())
            try:
                rec.record_imu(_make_imu_sample(moving=True, timestamp=1234.5))
                line = json.loads(rec._buffer[-1])
                assert line["t"] == 1234.5
            finally:
                rec.stop()

    def test_update_session_context_late_binds_dt_and_location(self, tmp_path):
        """A session started before GPS lock gains dt/location later."""
        with patch("PiFinder.telemetry.TELEMETRY_DIR", tmp_path / "telemetry"):
            rec = TelemetryRecorder()
            ss = MagicMock()
            ss.location.return_value = None
            ss.datetime.return_value = None
            rec.start(_make_cfg(), ss)
            try:
                assert rec._dt_recorded is False
                assert rec._loc_recorded is False

                rec.update_session_context(
                    datetime.fromisoformat("2024-01-15T22:30:00"),
                    _make_location(lat=35.0),
                )
                assert rec._dt_recorded and rec._loc_recorded
                lines = [json.loads(line) for line in rec._buffer]
                hdrs = [ln for ln in lines if ln["e"] == "hdr"]
                assert len(hdrs) == 2  # initial (dt=null) + late-bound
                assert hdrs[-1]["dt"] == "2024-01-15T22:30:00"
                assert (rec._session_dir / "session.location").exists()

                # Idempotent once bound
                rec.update_session_context(
                    datetime.fromisoformat("2024-01-15T22:31:00"),
                    _make_location(lat=36.0),
                )
                lines = [json.loads(line) for line in rec._buffer]
                assert len([ln for ln in lines if ln["e"] == "hdr"]) == 2
            finally:
                rec.stop()

    def test_buffer_overflow_counted(self, tmp_path):
        """Events evicted by the bounded buffer are counted for warning."""
        with patch("PiFinder.telemetry.TELEMETRY_DIR", tmp_path / "telemetry"):
            rec = TelemetryRecorder()
            rec.start(_make_cfg(), _make_shared_state())
            try:
                overshoot = rec._buffer.maxlen + 100
                for i in range(overshoot):
                    rec.record_imu(_make_imu_sample(moving=True, timestamp=1000.0 + i))
                # header + overshoot appends into a maxlen buffer
                assert rec._dropped_events == overshoot + 1 - rec._buffer.maxlen
            finally:
                rec.stop()

    def test_record_solve_when_enabled(self, tmp_path):
        with patch("PiFinder.telemetry.TELEMETRY_DIR", tmp_path / "telemetry"):
            rec = TelemetryRecorder()
            rec.start(_make_cfg(), _make_shared_state())
            try:
                t = rec.record_solve(
                    _make_successful_solve(
                        ra=180.0,
                        dec=45.0,
                        roll=10.0,
                        cam_ra=180.1,
                        cam_dec=44.9,
                        cam_roll=10.0,
                        imu_anchor=_make_quat(1, 0, 0, 0),
                        last_solve_attempt=1000.4,
                        last_solve_success=1000.5,
                    ),
                    predicted=Pointing(RA=179.5, Dec=44.8, Roll=0.0),
                )
                assert t is not None
                assert len(rec._buffer) == 2  # header + solve
                line = json.loads(rec._buffer[-1])
                assert line["e"] == "solve"
                assert line["ra"] == 180.0
                assert line["pred_ra"] == 179.5
                assert line["cam_ra"] == 180.1
                assert line["iq"] == [1.0, 0.0, 0.0, 0.0]
                assert line["lsa"] == 1000.4
                assert line["lss"] == 1000.5
                assert line["src"] == "CAM"
            finally:
                rec.stop()

    def test_record_failed_solve(self, tmp_path):
        with patch("PiFinder.telemetry.TELEMETRY_DIR", tmp_path / "telemetry"):
            rec = TelemetryRecorder()
            rec.start(_make_cfg(), _make_shared_state())
            try:
                t = rec.record_solve(_make_failed_solve(last_solve_attempt=1000.4))
                assert t is not None
                line = json.loads(rec._buffer[-1])
                assert line["e"] == "solve"
                assert line["ra"] is None
                assert line["cam_ra"] is None
                assert line["iq"] is None
                assert line["matches"] == 0
                assert line["lsa"] == 1000.4
                assert line["src"] == "CAM_FAILED"
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
                rec.record_imu(_make_imu_sample(moving=True))
                rec._do_flush()
                assert len(rec._buffer) == 0
                content = (rec._session_dir / "session.jsonl").read_text()
                lines = [line for line in content.strip().split("\n") if line]
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

    def test_record_target(self, tmp_path):
        with patch("PiFinder.telemetry.TELEMETRY_DIR", tmp_path / "telemetry"):
            rec = TelemetryRecorder()
            rec.start(_make_cfg(), _make_shared_state())
            try:
                target = MagicMock()
                target.object_id = 42
                target.display_name = "NGC 7331"
                target.ra = 339.267
                target.dec = 34.416
                rec.record_target(target)
                assert len(rec._buffer) == 2  # header + target
                line = json.loads(rec._buffer[-1])
                assert line["e"] == "tgt"
                assert line["name"] == "NGC 7331"
                assert line["ra"] == 339.267
                assert line["dec"] == 34.416
                assert "alt" in line
                assert "az" in line
            finally:
                rec.stop()

    def test_record_target_dedup(self, tmp_path):
        with patch("PiFinder.telemetry.TELEMETRY_DIR", tmp_path / "telemetry"):
            rec = TelemetryRecorder()
            rec.start(_make_cfg(), _make_shared_state())
            try:
                target = MagicMock()
                target.object_id = 42
                target.display_name = "NGC 7331"
                target.ra = 339.267
                target.dec = 34.416
                rec.record_target(target)
                rec.record_target(target)  # same target, should be deduped
                assert len(rec._buffer) == 2  # header + one target
            finally:
                rec.stop()

    def test_record_target_change(self, tmp_path):
        with patch("PiFinder.telemetry.TELEMETRY_DIR", tmp_path / "telemetry"):
            rec = TelemetryRecorder()
            rec.start(_make_cfg(), _make_shared_state())
            try:
                t1 = MagicMock()
                t1.object_id = 42
                t1.display_name = "NGC 7331"
                t1.ra = 339.267
                t1.dec = 34.416
                t2 = MagicMock()
                t2.object_id = 99
                t2.display_name = "M 31"
                t2.ra = 10.684
                t2.dec = 41.269
                rec.record_target(t1)
                rec.record_target(t2)
                assert len(rec._buffer) == 3  # header + 2 targets
            finally:
                rec.stop()

    def test_record_target_cleared(self, tmp_path):
        with patch("PiFinder.telemetry.TELEMETRY_DIR", tmp_path / "telemetry"):
            rec = TelemetryRecorder()
            rec.start(_make_cfg(), _make_shared_state())
            try:
                target = MagicMock()
                target.object_id = 42
                target.display_name = "NGC 7331"
                target.ra = 339.267
                target.dec = 34.416
                rec.record_target(target)
                rec.record_target(None)
                assert len(rec._buffer) == 3  # header + target + clear
                line = json.loads(rec._buffer[-1])
                assert line["e"] == "tgt"
                assert line["name"] is None
                assert line["ra"] is None
                assert line["alt"] is None
                assert line["az"] is None
            finally:
                rec.stop()


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

    def test_load_skips_corrupt_lines(self, tmp_path):
        """Truncated/corrupt lines (e.g. from a power cut) are skipped."""
        session_file = tmp_path / "session.jsonl"
        session_file.write_text(
            json.dumps({"t": 999.0, "e": "hdr"})
            + "\n"
            + json.dumps({"t": 1000.0, "e": "imu", "q": [1, 0, 0, 0]})
            + "\n"
            + '{"e": "imu", "q": [1, 0, 0, 0]}\n'  # valid JSON, missing "t"
            + '["not", "a", "dict"]\n'  # valid JSON, wrong shape
            + '{"t": 1001.0, "e": "imu", "q": [1, 0'  # truncated tail
        )
        player = TelemetryPlayer(session_file)
        assert player.header is not None
        assert len(player.events) == 1
        assert player.events[0]["t"] == 1000.0

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

    def test_event_to_solve_result_success(self):
        event = {
            "t": 1000.5,
            "ra": 180.0,
            "dec": 45.0,
            "roll": 10.0,
            "cam_ra": 180.1,
            "cam_dec": 44.9,
            "cam_roll": 10.0,
            "matches": 15,
            "rmse": 0.5,
            "iq": [1.0, 0.0, 0.0, 0.0],
            "lsa": 1000.4,
            "lss": 1000.5,
            "src": "CAM",
        }
        result = TelemetryPlayer.event_to_solve_result(event)
        assert isinstance(result, SuccessfulSolve)
        assert result.aligned.RA == 180.0
        assert result.aligned.Dec == 45.0
        assert result.aligned.Roll == 10.0
        assert result.camera.RA == 180.1
        assert result.diagnostics.Matches == 15
        assert result.diagnostics.RMSE == 0.5
        assert result.last_solve_attempt == 1000.4
        assert result.last_solve_success == 1000.5
        assert isinstance(result.imu_anchor, quaternion_module.quaternion)
        assert result.imu_anchor.w == 1.0

    def test_event_to_solve_result_no_imu_quat(self):
        event = {"t": 1000.0, "ra": 180.0, "dec": 45.0}
        result = TelemetryPlayer.event_to_solve_result(event)
        assert isinstance(result, SuccessfulSolve)
        assert result.aligned.RA == 180.0
        assert result.imu_anchor is None
        # Missing lsa/lss fall back to the event timestamp
        assert result.last_solve_attempt == 1000.0
        assert result.last_solve_success == 1000.0

    def test_event_to_solve_result_no_camera_falls_back_to_aligned(self):
        event = {"t": 1000.0, "ra": 180.0, "dec": 45.0, "roll": 10.0}
        result = TelemetryPlayer.event_to_solve_result(event)
        assert isinstance(result, SuccessfulSolve)
        assert result.camera.RA == 180.0
        assert result.camera.Dec == 45.0

    def test_event_to_solve_result_failed(self):
        event = {
            "t": 1000.0,
            "ra": None,
            "dec": None,
            "matches": 0,
            "lsa": 1000.0,
        }
        result = TelemetryPlayer.event_to_solve_result(event)
        assert isinstance(result, FailedSolve)
        assert result.diagnostics.Matches == 0
        assert result.last_solve_attempt == 1000.0
        assert result.last_solve_success is None

    def test_event_to_imu_sample(self):
        event = {"t": 1000.0, "q": [1.0, 0.0, 0.0, 0.0], "mv": True, "st": 3}
        result = TelemetryPlayer.event_to_imu_sample(event)
        assert result is not None
        assert isinstance(result, ImuSample)
        assert isinstance(result.quat, quaternion_module.quaternion)
        assert result.timestamp == 1000.0
        assert result.moving is True
        assert result.status == 3

    def test_event_to_imu_sample_no_quat(self):
        event = {"t": 1000.0, "mv": False}
        assert TelemetryPlayer.event_to_imu_sample(event) is None

    def test_event_to_imu_sample_defaults(self):
        event = {"t": 1000.0, "q": [1.0, 0.0, 0.0, 0.0]}
        result = TelemetryPlayer.event_to_imu_sample(event)
        assert result.moving is False
        assert result.status == 0
        assert result.gyro is None
        assert result.accel is None

    def test_event_to_imu_sample_with_raw_sensors(self):
        event = {
            "t": 1000.0,
            "q": [1.0, 0.0, 0.0, 0.0],
            "gyro": [0.01, -0.02, 0.03],
            "accel": [0.1, 0.2, -0.3],
        }
        result = TelemetryPlayer.event_to_imu_sample(event)
        assert result.gyro == (0.01, -0.02, 0.03)
        assert result.accel == (0.1, 0.2, -0.3)


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

    def test_record_radio_stamps_published_sqm_and_floor(self, tmp_path):
        """The manager pulls the last published SQM/floor from shared state."""
        with patch("PiFinder.telemetry.TELEMETRY_DIR", tmp_path / "telemetry"):
            ss = _make_shared_state()
            ss.sqm.return_value = MagicMock(value=20.9)
            ss.sqm_details.return_value = {"skyglow_floor": 51.5}
            cq = queue.Queue()
            mgr = TelemetryManager(_make_cfg(telemetry_record=True), ss, cq)
            try:
                mgr.record_radio(
                    {
                        "sequence": 1,
                        "captured_at": 100.0,
                        "exposure_sec": 1.0,
                        "background_per_pixel": 515.0,
                        "background_mad": 28.0,
                        "background_gradient": 12.0,
                        "background_red": 540.0,
                    }
                )
                event = json.loads(mgr._recorder._buffer[-1])
                assert event["e"] == "radio"
                assert event["red"] == 540.0
                assert event["sqm"] == 20.9
                assert event["floor"] == 51.5
            finally:
                mgr.stop()

    def test_record_radio_survives_missing_sqm_state(self, tmp_path):
        """No SQM published yet: sqm/floor log as None, recording continues."""
        with patch("PiFinder.telemetry.TELEMETRY_DIR", tmp_path / "telemetry"):
            ss = _make_shared_state()
            ss.sqm.return_value = None
            ss.sqm_details.return_value = None
            cq = queue.Queue()
            mgr = TelemetryManager(_make_cfg(telemetry_record=True), ss, cq)
            try:
                mgr.record_radio(
                    {
                        "sequence": 1,
                        "captured_at": 100.0,
                        "exposure_sec": 1.0,
                        "background_per_pixel": 515.0,
                        "background_mad": 28.0,
                        "background_gradient": 12.0,
                    }
                )
                event = json.loads(mgr._recorder._buffer[-1])
                assert event["sqm"] is None
                assert event["floor"] is None
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
        hdr = {"t": 999.0, "e": "hdr", "dt": "2024-01-15T22:30:00"}
        events = [{"t": 1000.0, "e": "imu", "q": [1, 0, 0, 0]}]
        _write_session_jsonl(tmp_path / "session.jsonl", events, header=hdr)
        loc_file = tmp_path / "session.location"
        loc_file.write_text(json.dumps({"lat": 35.0, "lon": -120.0, "altitude": 200.0}))

        ss = _make_shared_state()
        cq = queue.Queue()
        mgr = TelemetryManager(_make_cfg(), ss, cq)
        mgr._handle_command("replay", str(tmp_path))

        ss.set_location.assert_called_once()
        loc_arg = ss.set_location.call_args[0][0]
        assert loc_arg.lat == 35.0
        assert loc_arg.source == "replay"
        ss.set_datetime.assert_called_once()
        # Recordings are from the past; set_datetime rejects "older" times
        # unless forced, so replay must force-apply.
        assert ss.set_datetime.call_args.kwargs.get("force") is True

    def test_replay_restores_location_and_datetime(self, tmp_path):
        """Replay saves the pre-replay location and restores it on stop,
        and clears the forced replay clock so GPS time resumes."""
        hdr = {"t": 999.0, "e": "hdr", "dt": "2024-01-15T22:30:00"}
        events = [{"t": 1000.0, "e": "imu", "q": [1, 0, 0, 0]}]
        _write_session_jsonl(tmp_path / "session.jsonl", events, header=hdr)
        (tmp_path / "session.location").write_text(
            json.dumps({"lat": 35.0, "lon": -120.0, "altitude": 200.0})
        )

        original_loc = _make_location(lat=51.0, lon=4.0, alt=10.0)
        ss = _make_shared_state(location=original_loc)
        cq = queue.Queue()
        mgr = TelemetryManager(_make_cfg(), ss, cq)
        mgr._handle_command("replay", str(tmp_path))
        assert mgr.replaying

        mgr._handle_command("replay_stop", None)
        assert not mgr.replaying
        restored = ss.set_location.call_args[0][0]
        assert restored.lat == 51.0
        assert restored.lon == 4.0
        ss.reset_datetime.assert_called_once()

    def test_replay_late_header_dt_shifted_to_stream_start(self, tmp_path):
        """A late-bound header's dt is shifted back to the first event."""
        event = {"t": 1000.0, "e": "imu", "q": [1, 0, 0, 0]}
        hdr = {"t": 1060.0, "e": "hdr", "dt": "2024-01-15T22:31:00"}
        session = tmp_path / "session.jsonl"
        session.write_text(json.dumps(event) + "\n" + json.dumps(hdr) + "\n")

        ss = _make_shared_state()
        mgr = TelemetryManager(_make_cfg(), ss, queue.Queue())
        mgr._handle_command("replay", str(tmp_path))

        dt_arg = ss.set_datetime.call_args[0][0]
        assert dt_arg == datetime.fromisoformat("2024-01-15T22:30:00")

    def test_handle_command_replay_missing_path_survives(self, tmp_path):
        """A nonexistent session must not raise out of the command handler."""
        cq = queue.Queue()
        cam_q = queue.Queue()
        mgr = TelemetryManager(_make_cfg(), _make_shared_state(), cq, cam_q)
        mgr._handle_command("replay", str(tmp_path / "does_not_exist"))
        assert not mgr.replaying
        assert cq.get_nowait() == "Telemetry: Replay load failed"
        # The UI stops the camera before sending the command; on a failed
        # load the manager must restart it.
        assert cam_q.get_nowait() == "start"

    def test_next_replay_message_malformed_event_skipped(self, tmp_path):
        """A structurally-broken event is skipped, not raised."""
        events = [
            {"t": 1000.0, "e": "imu", "q": [1, 0]},  # truncated quat
            {"t": 1000.0, "e": "imu", "q": [1, 0, 0, 0]},  # same t → due at once
        ]
        _write_session_jsonl(tmp_path / "session.jsonl", events)
        mgr = TelemetryManager(_make_cfg(), _make_shared_state(), queue.Queue())
        mgr._handle_command("replay", str(tmp_path))
        first = mgr.next_replay_message()  # malformed → skipped → None
        assert first is None
        second = mgr.next_replay_message()
        assert isinstance(second, ImuSample)

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

    def test_next_replay_message_not_replaying(self):
        mgr = TelemetryManager(_make_cfg(), _make_shared_state(), queue.Queue())
        assert mgr.next_replay_message() is None

    def test_next_replay_message_imu_event(self, tmp_path):
        now = time.time()
        events = [{"t": now, "e": "imu", "q": [1, 0, 0, 0], "mv": True, "st": 3}]
        _write_session_jsonl(tmp_path / "session.jsonl", events)

        cq = queue.Queue()
        mgr = TelemetryManager(_make_cfg(), _make_shared_state(), cq)
        mgr._handle_command("replay", str(tmp_path))
        cq.get_nowait()  # drain "Replay started"

        message = mgr.next_replay_message()
        assert isinstance(message, ImuSample)
        assert message.moving is True

    def test_next_replay_message_solve_event(self, tmp_path):
        now = time.time()
        events = [
            {
                "t": now,
                "e": "solve",
                "ra": 180.0,
                "dec": 45.0,
                "roll": 10.0,
                "cam_ra": 180.1,
                "cam_dec": 44.9,
                "cam_roll": 10.0,
            }
        ]
        _write_session_jsonl(tmp_path / "session.jsonl", events)

        cq = queue.Queue()
        mgr = TelemetryManager(_make_cfg(), _make_shared_state(), cq)
        mgr._handle_command("replay", str(tmp_path))
        cq.get_nowait()  # drain "Replay started"

        message = mgr.next_replay_message()
        assert isinstance(message, SuccessfulSolve)
        assert message.aligned.RA == 180.0

    def test_next_replay_message_failed_solve_event(self, tmp_path):
        now = time.time()
        events = [{"t": now, "e": "solve", "ra": None, "dec": None, "matches": 0}]
        _write_session_jsonl(tmp_path / "session.jsonl", events)

        cq = queue.Queue()
        mgr = TelemetryManager(_make_cfg(), _make_shared_state(), cq)
        mgr._handle_command("replay", str(tmp_path))
        cq.get_nowait()  # drain "Replay started"

        message = mgr.next_replay_message()
        assert isinstance(message, FailedSolve)

    def test_next_replay_message_auto_finish(self, tmp_path):
        now = time.time()
        events = [{"t": now, "e": "imu", "q": [1, 0, 0, 0]}]
        _write_session_jsonl(tmp_path / "session.jsonl", events)

        cq = queue.Queue()
        cam_q = queue.Queue()
        mgr = TelemetryManager(_make_cfg(), _make_shared_state(), cq, cam_q)
        mgr._handle_command("replay", str(tmp_path))
        cq.get_nowait()  # drain "Replay started"

        # First call returns the event
        message = mgr.next_replay_message()
        assert message is not None

        # Next call: done → auto-cleanup
        message2 = mgr.next_replay_message()
        assert message2 is None
        assert not mgr.replaying
        assert cq.get_nowait() == "Telemetry: Replay finished"
        assert cam_q.get_nowait() == "start"

    def test_record_solve_delegates(self):
        mgr = TelemetryManager(_make_cfg(), _make_shared_state(), queue.Queue())
        mgr._recorder = MagicMock()
        mgr._recorder.record_solve.return_value = None
        mgr.record_solve(_make_successful_solve())
        mgr._recorder.record_solve.assert_called_once()

    def test_record_solve_sends_image_command(self, tmp_path):
        with patch("PiFinder.telemetry.TELEMETRY_DIR", tmp_path / "telemetry"):
            cam_q = queue.Queue()
            mgr = TelemetryManager(
                _make_cfg(), _make_shared_state(), queue.Queue(), cam_q
            )
            mgr._recorder.start(_make_cfg(), _make_shared_state())  # images section on
            try:
                mgr.record_solve(_make_successful_solve())
                msg = cam_q.get_nowait()
                assert msg.startswith("save_image:")
            finally:
                mgr.stop()

    def test_record_solve_no_image_once_cap_reached(self, tmp_path):
        with patch("PiFinder.telemetry.TELEMETRY_DIR", tmp_path / "telemetry"):
            cam_q = queue.Queue()
            console_q = queue.Queue()
            mgr = TelemetryManager(_make_cfg(), _make_shared_state(), console_q, cam_q)
            mgr._recorder.start(
                _make_cfg(telemetry_max_session_mb=1), _make_shared_state()
            )
            try:
                # Push the session past the cap, then re-measure.
                (mgr._recorder.get_session_dir() / "img_1.png").write_bytes(
                    b"x" * 1_200_000
                )
                mgr._recorder._refresh_session_bytes()
                assert mgr._recorder.images_capped

                mgr.record_solve(_make_successful_solve())
                assert cam_q.empty()  # no further frames requested
                assert console_q.get_nowait() == "Telemetry: Size cap, frames off"
            finally:
                mgr.stop()

    def test_record_solve_no_image_when_images_section_off(self, tmp_path):
        with patch("PiFinder.telemetry.TELEMETRY_DIR", tmp_path / "telemetry"):
            cam_q = queue.Queue()
            mgr = TelemetryManager(
                _make_cfg(), _make_shared_state(), queue.Queue(), cam_q
            )
            # Solves on, Images off: solve recorded but no frame saved.
            mgr._recorder.start(
                _make_cfg(telemetry_sections=["imu", "sqm", "solve", "target"]),
                _make_shared_state(),
            )
            try:
                mgr.record_solve(_make_successful_solve())
                assert cam_q.empty()
            finally:
                mgr.stop()

    def test_record_imu_delegates(self):
        mgr = TelemetryManager(_make_cfg(), _make_shared_state(), queue.Queue())
        mgr._recorder = MagicMock()
        mgr.record_imu(_make_imu_sample())
        mgr._recorder.record_imu.assert_called_once()

    def test_record_noop_while_replaying(self, tmp_path):
        """Recording is suppressed while replaying to avoid re-recording
        the replayed session."""
        events = [{"t": 1000.0, "e": "imu", "q": [1, 0, 0, 0]}]
        _write_session_jsonl(tmp_path / "session.jsonl", events)

        cq = queue.Queue()
        mgr = TelemetryManager(_make_cfg(), _make_shared_state(), cq)
        mgr._recorder = MagicMock()
        mgr._handle_command("replay", str(tmp_path))

        mgr.record_solve(_make_successful_solve())
        mgr.record_imu(_make_imu_sample())
        mgr._recorder.record_solve.assert_not_called()
        mgr._recorder.record_imu.assert_not_called()

    def test_flush_delegates(self):
        mgr = TelemetryManager(_make_cfg(), _make_shared_state(), queue.Queue())
        mgr._recorder = MagicMock()
        mgr._recorder.enabled = False
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
        mgr = TelemetryManager(_make_cfg(), _make_shared_state(), queue.Queue(), None)
        mgr._restart_camera()  # no-op, no crash

    def test_replay_header_mount_type_mismatch_warns(self, tmp_path):
        """Replay should warn when header mount_type differs from config."""
        hdr = {
            "t": 999.0,
            "e": "hdr",
            "dt": "2024-01-15T22:30:00",
            "cfg": {"screen_direction": "flat", "mount_type": "EQ"},
        }
        events = [{"t": 1000.0, "e": "imu", "q": [1, 0, 0, 0]}]
        _write_session_jsonl(tmp_path / "session.jsonl", events, header=hdr)

        ss = _make_shared_state()
        cq = queue.Queue()
        cfg = _make_cfg(mount_type="Alt/Az")
        mgr = TelemetryManager(cfg, ss, cq)

        with patch("PiFinder.telemetry.logger") as mock_logger:
            mgr._handle_command("replay", str(tmp_path))
            mock_logger.warning.assert_called_once()
            assert "EQ" in mock_logger.warning.call_args[0][1]
            assert "Alt/Az" in mock_logger.warning.call_args[0][2]

    def test_replay_header_mount_type_match_no_warn(self, tmp_path):
        """No warning when header mount_type matches config."""
        hdr = {
            "t": 999.0,
            "e": "hdr",
            "cfg": {"screen_direction": "flat", "mount_type": "Alt/Az"},
        }
        events = [{"t": 1000.0, "e": "imu", "q": [1, 0, 0, 0]}]
        _write_session_jsonl(tmp_path / "session.jsonl", events, header=hdr)

        cfg = _make_cfg(mount_type="Alt/Az")
        mgr = TelemetryManager(cfg, _make_shared_state(), queue.Queue())

        with patch("PiFinder.telemetry.logger") as mock_logger:
            mgr._handle_command("replay", str(tmp_path))
            mock_logger.warning.assert_not_called()

    def test_flush_polls_target(self, tmp_path):
        with patch("PiFinder.telemetry.TELEMETRY_DIR", tmp_path / "telemetry"):
            ss = _make_shared_state()
            target = MagicMock()
            target.object_id = 42
            target.display_name = "M 31"
            target.ra = 10.684
            target.dec = 41.269
            ui_state = MagicMock()
            ui_state.target.return_value = target
            ss.ui_state.return_value = ui_state

            mgr = TelemetryManager(_make_cfg(telemetry_record=True), ss, queue.Queue())
            try:
                mgr.flush()
                assert mgr._recorder._last_target_id == 42
                # Check a target event was buffered (header + target)
                assert len(mgr._recorder._buffer) >= 2
                lines = [json.loads(line) for line in mgr._recorder._buffer]
                tgt_lines = [line for line in lines if line.get("e") == "tgt"]
                assert len(tgt_lines) == 1
                assert tgt_lines[0]["name"] == "M 31"
            finally:
                mgr.stop()

    def test_poll_target_no_ui_state(self):
        """_poll_target should not crash if ui_state() raises."""
        ss = _make_shared_state()
        ss.ui_state.side_effect = Exception("no ui state")
        mgr = TelemetryManager(_make_cfg(), ss, queue.Queue())
        mgr._recorder.enabled = True
        mgr._poll_target()  # should not raise

    def test_header_includes_mount_type(self, tmp_path):
        """Recording header should include mount_type from config."""
        with patch("PiFinder.telemetry.TELEMETRY_DIR", tmp_path / "telemetry"):
            rec = TelemetryRecorder()
            cfg = _make_cfg(mount_type="EQ")
            ss = _make_shared_state()
            rec.start(cfg, ss)
            try:
                line = json.loads(rec._buffer[0])
                assert line["cfg"]["mount_type"] == "EQ"
            finally:
                rec.stop()


# ── Recording → replay round trip ───────────────────────────────────


@pytest.mark.unit
class TestRecordReplayRoundTrip:
    def test_recorded_solve_replays_as_equivalent_message(self, tmp_path):
        """A recorded SuccessfulSolve comes back as an equivalent message."""
        with patch("PiFinder.telemetry.TELEMETRY_DIR", tmp_path / "telemetry"):
            rec = TelemetryRecorder()
            rec.start(_make_cfg(), _make_shared_state())
            original = _make_successful_solve(imu_anchor=_make_quat(1, 0, 0, 0))
            rec.record_solve(original)
            rec._do_flush()
            session_dir = rec._session_dir
            rec.stop()

            player = TelemetryPlayer(session_dir)
            assert player.total_events == 1
            replayed = TelemetryPlayer.event_to_solve_result(player.events[0])
            assert isinstance(replayed, SuccessfulSolve)
            assert replayed.aligned.RA == original.aligned.RA
            assert replayed.aligned.Dec == original.aligned.Dec
            assert replayed.camera.RA == original.camera.RA
            assert replayed.imu_anchor == original.imu_anchor
            assert replayed.last_solve_attempt == original.last_solve_attempt
            assert replayed.last_solve_success == original.last_solve_success
            assert replayed.diagnostics.Matches == original.diagnostics.Matches

    def test_recorded_imu_replays_as_equivalent_sample(self, tmp_path):
        """A recorded ImuSample comes back as an equivalent sample."""
        with patch("PiFinder.telemetry.TELEMETRY_DIR", tmp_path / "telemetry"):
            rec = TelemetryRecorder()
            rec.start(_make_cfg(), _make_shared_state())
            original = _make_imu_sample(
                quat=_make_quat(0.5, 0.5, 0.5, 0.5),
                moving=True,
                status=3,
                gyro=(0.01, -0.02, 0.03),
                accel=(0.1, 0.2, -0.3),
            )
            rec.record_imu(original)
            rec._do_flush()
            session_dir = rec._session_dir
            rec.stop()

            player = TelemetryPlayer(session_dir)
            assert player.total_events == 1
            replayed = TelemetryPlayer.event_to_imu_sample(player.events[0])
            assert isinstance(replayed, ImuSample)
            assert replayed.quat == original.quat
            assert replayed.moving is True
            assert replayed.status == 3
            assert replayed.gyro == original.gyro
            assert replayed.accel == original.accel
