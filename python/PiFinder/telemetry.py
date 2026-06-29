"""
Telemetry recording and replay for the integrator.

Records IMU samples and plate solves with accurate timing to JSONL files
in ~/PiFinder_data/telemetry/. Replay mode converts recorded events back
into :class:`SolveResult` / :class:`ImuSample` messages that the
integrator feeds through its normal apply/advance paths for bench
testing.
"""

import copy
import json
import logging
import queue
import threading
import time
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path

import quaternion as quaternion_module

from PiFinder import calc_utils
from PiFinder import utils
from PiFinder import timez
from PiFinder.types.positioning import (
    FailedSolve,
    ImuSample,
    Pointing,
    SolveDiagnostics,
    SuccessfulSolve,
)

logger = logging.getLogger("Telemetry")

TELEMETRY_DIR = Path(utils.data_dir) / "telemetry"


_R = 5  # decimal places for float rounding (BNO055 is ~14-bit)

# Stationary IMU downsampling: record every Nth sample when not moving
_STATIONARY_DECIMATION = 10


def _rf(v):
    """Round a float for compact serialization."""
    return round(v, _R)


def _serialize_quat(q):
    """Serialize a quaternion to a list [w, x, y, z]."""
    if q is None:
        return None
    try:
        return [_rf(q.w), _rf(q.x), _rf(q.y), _rf(q.z)]
    except (AttributeError, TypeError):
        return None


def _serialize_vec(v):
    """Serialize a 3-tuple/list to rounded list, or None."""
    if v is None:
        return None
    try:
        return [_rf(v[0]), _rf(v[1]), _rf(v[2])]
    except (TypeError, IndexError):
        return None


class TelemetryRecorder:
    """
    Records IMU and solve events to a JSONL file.

    Uses a deque buffer flushed every 5 seconds by a background thread.
    When disabled, all methods are no-ops.
    """

    def __init__(self):
        self.enabled = False
        self.images_enabled = False
        self._buffer = deque(maxlen=300)
        self._file = None
        self._flush_thread = None
        self._stop_event = threading.Event()
        self._flush_lock = threading.Lock()
        self._session_dir = None
        self._last_flush = 0.0
        self._imu_skip_count = 0
        self._last_imu_timestamp = None
        self._last_target_id = None
        self._dropped_events = 0
        self._header_cfg = None
        self._dt_recorded = False
        self._loc_recorded = False

    def _append(self, record):
        """Serialize a record into the buffer, counting overflow drops."""
        if len(self._buffer) == self._buffer.maxlen:
            # deque(maxlen) silently evicts the oldest entry on append.
            self._dropped_events += 1
        self._buffer.append(json.dumps(record) + "\n")

    def start(self, cfg, shared_state):
        """Start a new recording session."""
        if self.enabled:
            self.stop()

        TELEMETRY_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = timez.local_now().strftime("%Y%m%d_%H%M%S")
        self._session_dir = TELEMETRY_DIR / timestamp
        self._session_dir.mkdir(parents=True, exist_ok=True)
        session_file = self._session_dir / "session.jsonl"

        self._file = open(session_file, "a")
        self.enabled = True
        self._last_flush = time.time()

        # Reset per-session state
        self._imu_skip_count = 0
        self._last_imu_timestamp = None
        self._last_target_id = None
        self._dropped_events = 0

        # Write header (no location — written to separate .location file)
        dt = shared_state.datetime()
        self._header_cfg = {
            "screen_direction": cfg.get_option("screen_direction"),
            "mount_type": cfg.get_option("mount_type"),
        }
        header = {
            "t": time.time(),
            "e": "hdr",
            "dt": dt.isoformat() if dt else None,
            "cfg": self._header_cfg,
        }
        self._append(header)
        self._dt_recorded = dt is not None

        # Write location to a separate file to avoid leaking it in shared recordings
        location = shared_state.location()
        self._loc_recorded = self._write_location_sidecar(location)

        # Start flush thread
        self._stop_event.clear()
        self._flush_thread = threading.Thread(
            target=self._flush_loop, daemon=True, name="telemetry-flush"
        )
        self._flush_thread.start()
        logger.info("Telemetry recording started: %s", session_file)

    def _write_location_sidecar(self, location):
        """Write the .location sidecar. Returns True if written."""
        if not location or self._session_dir is None:
            return False
        loc_file = self._session_dir / "session.location"
        loc_data = {
            "lat": location.lat,
            "lon": location.lon,
            "altitude": location.altitude,
        }
        loc_file.write_text(json.dumps(loc_data))
        return True

    def update_session_context(self, dt, location):
        """Late-bind datetime/location that weren't available at start().

        A recording often starts before GPS lock; once time/place arrive,
        write an updated header record (the player keeps the last header
        seen) and the location sidecar, so the session replays with the
        correct clock and Alt/Az.
        """
        if not self.enabled:
            return
        if dt is not None and not self._dt_recorded:
            self._append(
                {
                    "t": time.time(),
                    "e": "hdr",
                    "dt": dt.isoformat(),
                    "cfg": self._header_cfg,
                }
            )
            self._dt_recorded = True
        if location is not None and not self._loc_recorded:
            self._loc_recorded = self._write_location_sidecar(location)

    def stop(self):
        """Stop the current recording session."""
        if not self.enabled:
            return
        self.enabled = False
        self._stop_event.set()
        if self._flush_thread:
            self._flush_thread.join(timeout=2)
            self._flush_thread = None
        self._do_flush()
        if self._file:
            self._file.close()
            self._file = None
        self._session_dir = None
        logger.info("Telemetry recording stopped")

    def record_imu(self, imu):
        """Record an :class:`ImuSample`. No-op if disabled.

        Stamps the record with the sample's own epoch (``imu.timestamp``)
        and dedupes on it: the integrator loop polls faster than the IMU
        updates, so the same sample is seen multiple times.

        When stationary, only records every _STATIONARY_DECIMATION-th sample
        to reduce file size during long sessions.
        """
        if not self.enabled or imu is None:
            return
        if imu.timestamp == self._last_imu_timestamp:
            return  # same sample re-polled by a faster loop
        self._last_imu_timestamp = imu.timestamp
        moving = imu.moving
        if not moving:
            self._imu_skip_count += 1
            if self._imu_skip_count < _STATIONARY_DECIMATION:
                return
            self._imu_skip_count = 0
        else:
            self._imu_skip_count = 0
        record = {
            "t": _rf(imu.timestamp),
            "e": "imu",
            "q": _serialize_quat(imu.quat),
            "mv": moving,
            "st": imu.status,
            "gyro": _serialize_vec(imu.gyro),
            "accel": _serialize_vec(imu.accel),
        }
        self._append(record)

    def record_solve(self, solve_result, predicted=None):
        """Record a :class:`SolveResult`. No-op if disabled.

        ``predicted`` is the integrator's current aligned-axis estimate
        (the IMU-progressed :class:`Pointing`) just before the solve was
        applied, enabling drift measurement.

        Returns the timestamp used for the record, or None if not recorded.
        """
        if not self.enabled or solve_result is None:
            return None
        t = time.time()
        success = isinstance(solve_result, SuccessfulSolve)
        record = {
            "t": _rf(t),
            "e": "solve",
            "ra": _rf(solve_result.aligned.RA) if success else None,
            "dec": _rf(solve_result.aligned.Dec) if success else None,
            "roll": _rf(solve_result.aligned.Roll) if success else None,
            "pred_ra": _rf(predicted.RA) if predicted is not None else None,
            "pred_dec": _rf(predicted.Dec) if predicted is not None else None,
            "cam_ra": _rf(solve_result.camera.RA) if success else None,
            "cam_dec": _rf(solve_result.camera.Dec) if success else None,
            "cam_roll": _rf(solve_result.camera.Roll) if success else None,
            "iq": _serialize_quat(solve_result.imu_anchor) if success else None,
            "matches": solve_result.diagnostics.Matches,
            "rmse": _rf(solve_result.diagnostics.RMSE)
            if solve_result.diagnostics.RMSE is not None
            else None,
            "lsa": solve_result.last_solve_attempt,
            "lss": solve_result.last_solve_success,
            "src": "CAM" if success else "CAM_FAILED",
        }
        self._append(record)
        return t

    def record_target(self, target, alt=None, az=None):
        """Record a target change event. Pass None when target is cleared."""
        if not self.enabled:
            return
        if target is None:
            target_id = None
        else:
            target_id = getattr(target, "object_id", None)

        if target_id == self._last_target_id:
            return
        self._last_target_id = target_id

        if target is None:
            record = {
                "t": _rf(time.time()),
                "e": "tgt",
                "name": None,
                "ra": None,
                "dec": None,
                "alt": None,
                "az": None,
            }
        else:
            record = {
                "t": _rf(time.time()),
                "e": "tgt",
                "name": getattr(target, "display_name", None),
                "ra": _rf(target.ra) if target.ra is not None else None,
                "dec": _rf(target.dec) if target.dec is not None else None,
                "alt": _rf(alt) if alt is not None else None,
                "az": _rf(az) if az is not None else None,
            }
        self._append(record)

    def get_session_dir(self):
        """Return current session directory path, or None."""
        return self._session_dir

    def flush(self):
        """Time-gated flush - only actually flushes every 5 seconds."""
        if not self.enabled:
            return
        now = time.time()
        if now - self._last_flush >= 5.0:
            self._do_flush()
            self._last_flush = now

    def _do_flush(self):
        """Flush the buffer to disk.

        Locked: the background flush thread and the integrator loop's
        time-gated flush may run concurrently, and interleaved writes
        would scramble event order.
        """
        with self._flush_lock:
            if not self._file or not self._buffer:
                return
            if self._dropped_events:
                logger.warning(
                    "Telemetry buffer overflow: %d events dropped since last flush",
                    self._dropped_events,
                )
                self._dropped_events = 0
            lines = []
            while self._buffer:
                try:
                    lines.append(self._buffer.popleft())
                except IndexError:
                    break
            if lines:
                self._file.writelines(lines)
                self._file.flush()

    def _flush_loop(self):
        """Background thread that flushes every 5 seconds."""
        while not self._stop_event.is_set():
            self._stop_event.wait(5.0)
            self._do_flush()


class TelemetryPlayer:
    """
    Reads a recorded JSONL session and replays events with original timing.
    """

    def __init__(self, path):
        self.path = Path(path)
        self.events = []
        self.header = None
        self._index = 0
        self._base_time = None
        self._replay_start = None
        self._load()

    def _load(self):
        """Load all events from the JSONL file.

        Tolerates corrupt lines (e.g. a truncated tail from a power cut
        mid-recording): unparseable or timestamp-less lines are skipped
        with a warning instead of aborting the load.
        """
        file_path = self.path
        if file_path.is_dir():
            file_path = file_path / "session.jsonl"

        skipped = 0
        with open(file_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    skipped += 1
                    continue
                if not isinstance(event, dict) or "t" not in event:
                    skipped += 1
                    continue
                if event.get("e") == "hdr":
                    self.header = event
                else:
                    self.events.append(event)

        if skipped:
            logger.warning(
                "Skipped %d corrupt telemetry lines in %s", skipped, file_path
            )
        if self.events:
            self._base_time = self.events[0]["t"]
        logger.info("Loaded telemetry: %d events from %s", len(self.events), file_path)

    def reset(self):
        """Reset replay to the beginning."""
        self._index = 0
        self._replay_start = None

    def get_next_event(self):
        """
        Return the next event if its relative timestamp has elapsed,
        otherwise return None. Call this in a loop.

        Returns (event_dict, done_bool).
        """
        if self._index >= len(self.events):
            return None, True

        if self._replay_start is None:
            self._replay_start = time.time()

        event = self.events[self._index]
        event_offset = event["t"] - self._base_time
        elapsed = time.time() - self._replay_start

        if elapsed >= event_offset:
            self._index += 1
            return event, self._index >= len(self.events)

        return None, False

    @property
    def progress(self):
        """Return replay progress as a fraction 0.0-1.0."""
        if not self.events:
            return 1.0
        return self._index / len(self.events)

    @property
    def total_events(self):
        return len(self.events)

    @property
    def current_index(self):
        return self._index

    @staticmethod
    def event_to_solve_result(event):
        """Convert a recorded solve event back into a SolveResult message.

        A recorded ``ra`` of None means the original attempt failed —
        rebuild it as a :class:`FailedSolve`; otherwise as a
        :class:`SuccessfulSolve`.
        """
        t = event["t"]
        diagnostics = SolveDiagnostics(
            Matches=event.get("matches") or 0,
            RMSE=event.get("rmse"),
        )

        if event.get("ra") is None:
            return FailedSolve(
                diagnostics=diagnostics,
                last_solve_attempt=event.get("lsa") or t,
                last_solve_success=event.get("lss"),
            )

        aligned = Pointing(
            RA=event["ra"],
            Dec=event["dec"],
            Roll=event.get("roll") or 0.0,
        )
        if event.get("cam_ra") is not None:
            camera = Pointing(
                RA=event["cam_ra"],
                Dec=event["cam_dec"],
                Roll=event.get("cam_roll") or 0.0,
            )
        else:
            # Recordings without camera-axis data: fall back to aligned.
            camera = aligned

        imu_anchor = None
        iq = event.get("iq")
        if iq:
            imu_anchor = quaternion_module.quaternion(iq[0], iq[1], iq[2], iq[3])

        return SuccessfulSolve(
            camera=camera,
            aligned=aligned,
            imu_anchor=imu_anchor,
            last_solve_attempt=event.get("lsa") or t,
            last_solve_success=event.get("lss") or t,
            diagnostics=diagnostics,
        )

    @staticmethod
    def event_to_imu_sample(event):
        """Convert a recorded IMU event into an ImuSample, or None if no quat."""
        q = event.get("q")
        if not q:
            return None
        gyro = event.get("gyro")
        accel = event.get("accel")
        return ImuSample(
            quat=quaternion_module.quaternion(q[0], q[1], q[2], q[3]),
            timestamp=event["t"],
            status=event.get("st", 0),
            moving=event.get("mv", False),
            gyro=tuple(gyro) if gyro else None,
            accel=tuple(accel) if accel else None,
        )


class TelemetryManager:
    """
    Facade over TelemetryRecorder and TelemetryPlayer.

    Owns all telemetry I/O: command dispatch, recording, replay state,
    image saving, and console/camera queue messaging.  The integrator
    only needs to call a handful of one-liners and feed replayed
    messages through its normal apply/advance paths.
    """

    def __init__(self, cfg, shared_state, console_queue, camera_command_queue=None):
        self._cfg = cfg
        self._shared_state = shared_state
        self._console_queue = console_queue
        self._camera_command_queue = camera_command_queue
        self._recorder = TelemetryRecorder()
        self._recorder.images_enabled = bool(cfg.get_option("telemetry_images"))
        self._player = None
        # Pre-replay state to restore when replay ends.
        self._saved_location = None
        self._datetime_overridden = False
        if cfg.get_option("telemetry_record"):
            self._recorder.start(cfg, shared_state)

    @property
    def replaying(self):
        return self._player is not None

    def poll_commands(self, command_queue):
        """Check for and dispatch any pending telemetry commands."""
        if command_queue is None:
            return
        try:
            cmd = command_queue.get(block=False)
            if isinstance(cmd, tuple):
                self._handle_command(cmd[0], cmd[1])
        except queue.Empty:
            pass

    def _handle_command(self, cmd_name, cmd_arg):
        """Dispatch a telemetry command."""
        if cmd_name == "telemetry_record_on":
            self._recorder.images_enabled = bool(
                self._cfg.get_option("telemetry_images")
            )
            self._recorder.start(self._cfg, self._shared_state)
            self._console_queue.put("Telemetry: Recording")

        elif cmd_name == "telemetry_record_off":
            self._recorder.stop()
            self._console_queue.put("Telemetry: Stopped")

        elif cmd_name == "replay":
            logger.info("Entering replay mode: %s", cmd_arg)
            try:
                self._player = TelemetryPlayer(cmd_arg)
            except OSError as e:
                # Missing/unreadable session must not kill the integrator.
                # The UI already stopped the camera, so restart it.
                logger.error("Failed to load telemetry session %s: %s", cmd_arg, e)
                self._restart_camera()
                self._console_queue.put("Telemetry: Replay load failed")
                return
            if self._player.header:
                self._apply_replay_header(self._player.header, self._shared_state)
            self._console_queue.put("Telemetry: Replay started")

        elif cmd_name == "replay_stop":
            logger.info("Exiting replay mode")
            self._end_replay("Telemetry: Replay stopped")

    def next_replay_message(self):
        """Return the next replayed message, or None.

        Converts the next due recorded event into a
        :class:`SuccessfulSolve` / :class:`FailedSolve` / :class:`ImuSample`
        for the integrator to feed through its normal paths. Returns None
        when no event is due yet. Automatically clears replay state and
        restarts the camera when the session is exhausted.
        """
        if self._player is None:
            return None
        event, done = self._player.get_next_event()
        if done and event is None:
            logger.info("Replay finished")
            self._end_replay("Telemetry: Replay finished")
            return None
        if event is None:
            return None

        event_type = event.get("e")
        try:
            if event_type == "imu":
                return TelemetryPlayer.event_to_imu_sample(event)
            elif event_type == "solve":
                return TelemetryPlayer.event_to_solve_result(event)
        except (KeyError, IndexError, TypeError) as e:
            # A malformed event must not kill the integrator mid-replay.
            logger.warning("Skipping malformed replay event: %s", e)
        return None

    def record_solve(self, solve_result, predicted=None):
        """Record a solve event and send save_image command if enabled."""
        if self.replaying:
            return
        t = self._recorder.record_solve(solve_result, predicted)
        if (
            t is not None
            and self._recorder.images_enabled
            and self._camera_command_queue is not None
        ):
            session_dir = self._recorder.get_session_dir()
            if session_dir:
                self._camera_command_queue.put(
                    f"save_image:{session_dir / f'img_{t:.3f}.png'}"
                )

    def record_imu(self, imu):
        if self.replaying:
            return
        self._recorder.record_imu(imu)

    def flush(self):
        self._poll_target()
        self._update_session_context()
        self._recorder.flush()

    def _update_session_context(self):
        """Late-bind session datetime/location once they become available."""
        rec = self._recorder
        if not rec.enabled or (rec._dt_recorded and rec._loc_recorded):
            return
        rec.update_session_context(
            self._shared_state.datetime(), self._shared_state.location()
        )

    def _poll_target(self):
        """Check if the user's target changed and record it."""
        if not self._recorder.enabled:
            return
        try:
            target = self._shared_state.ui_state().target()
        except Exception:
            return
        target_id = None if target is None else getattr(target, "object_id", None)
        if target_id == self._recorder._last_target_id:
            return  # unchanged — skip the per-loop Alt/Az computation
        alt, az = None, None
        if target is not None and target.ra is not None:
            try:
                location = self._shared_state.location()
                dt = self._shared_state.datetime()
                if location and dt:
                    calc_utils.sf_utils.set_location(
                        location.lat, location.lon, location.altitude
                    )
                    alt, az = calc_utils.sf_utils.radec_to_altaz(
                        target.ra, target.dec, dt
                    )
            except Exception:
                pass
        self._recorder.record_target(target, alt=alt, az=az)

    def stop(self):
        self._recorder.stop()

    def _restart_camera(self):
        if self._camera_command_queue is not None:
            self._camera_command_queue.put("start")

    def _end_replay(self, console_msg):
        """Leave replay mode: restore hijacked state and restart the camera."""
        self._player = None
        if self._saved_location is not None:
            self._shared_state.set_location(self._saved_location)
            self._saved_location = None
        if self._datetime_overridden:
            # Clear the forced replay clock so GPS time updates resume.
            self._shared_state.reset_datetime()
            self._datetime_overridden = False
        self._restart_camera()
        self._console_queue.put(console_msg)

    def _apply_replay_header(self, hdr, shared_state):
        """Apply location/datetime from a replay session header.

        The pre-replay location is saved for restoration by _end_replay.
        """
        loc_data = self._load_replay_location()
        if loc_data:
            self._saved_location = copy.deepcopy(shared_state.location())
            loc = shared_state.location()
            loc.lat = loc_data["lat"]
            loc.lon = loc_data["lon"]
            loc.altitude = loc_data["altitude"]
            loc.lock = True
            loc.source = "replay"
            shared_state.set_location(loc)
        if hdr.get("dt"):
            replay_dt = datetime.fromisoformat(hdr["dt"])
            # The header may have been written later than the first event
            # (e.g. a late-bound header once GPS time arrived); shift dt
            # back so the clock matches the start of the event stream.
            base_time = self._player._base_time if self._player else None
            if base_time is not None and hdr.get("t") is not None:
                replay_dt -= timedelta(seconds=max(0.0, hdr["t"] - base_time))
            # force=True so a recording from the past actually overwrites
            # the current clock — set_datetime otherwise rejects "older"
            # times, and it also blocks later GPS updates mid-replay.
            shared_state.set_datetime(replay_dt, force=True)
            self._datetime_overridden = True

        cfg = hdr.get("cfg", {})
        recorded_mount = cfg.get("mount_type")
        current_mount = self._cfg.get_option("mount_type")
        if recorded_mount and current_mount and recorded_mount != current_mount:
            logger.warning(
                "Replay mount_type '%s' differs from current config '%s'",
                recorded_mount,
                current_mount,
            )

    def _load_replay_location(self):
        """Load location from the .location sidecar file, or None."""
        if self._player is None:
            return None
        loc_file = self._player.path
        if loc_file.is_file():
            loc_file = loc_file.parent / "session.location"
        else:
            loc_file = loc_file / "session.location"
        if loc_file.exists():
            try:
                return json.loads(loc_file.read_text())
            except (json.JSONDecodeError, OSError):
                return None
        return None
