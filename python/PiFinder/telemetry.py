"""
Telemetry recording and replay for the integrator.

Records IMU readings and plate solves with accurate timing to JSONL files
in ~/PiFinder_data/telemetry/. Replay mode feeds recorded data back through
the integrator for bench testing.
"""

import copy
import json
import logging
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import quaternion as quaternion_module

from PiFinder import utils
from PiFinder import calc_utils
from PiFinder.pointing import (
    finalize_and_push_solution,
    update_imu,
    update_plate_solve_and_imu,
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
        self._session_dir = None
        self._last_flush = 0.0
        self._imu_skip_count = 0
        self._last_target_id = None

    def start(self, cfg, shared_state):
        """Start a new recording session."""
        if self.enabled:
            self.stop()

        TELEMETRY_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._session_dir = TELEMETRY_DIR / timestamp
        self._session_dir.mkdir(parents=True, exist_ok=True)
        session_file = self._session_dir / "session.jsonl"

        self._file = open(session_file, "a")
        self.enabled = True
        self._last_flush = time.time()

        # Write header (no location — written to separate .location file)
        dt = shared_state.datetime()
        header = {
            "t": time.time(),
            "e": "hdr",
            "dt": dt.isoformat() if dt else None,
            "cfg": {
                "integrator": cfg.get_option("imu_integrator"),
                "mount_type": cfg.get_option("mount_type"),
            },
        }
        self._buffer.append(json.dumps(header) + "\n")

        # Write location to a separate file to avoid leaking it in shared recordings
        location = shared_state.location()
        if location:
            loc_file = self._session_dir / "session.location"
            loc_data = {
                "lat": location.lat,
                "lon": location.lon,
                "altitude": location.altitude,
            }
            loc_file.write_text(json.dumps(loc_data))

        # Start flush thread
        self._stop_event.clear()
        self._flush_thread = threading.Thread(
            target=self._flush_loop, daemon=True, name="telemetry-flush"
        )
        self._flush_thread.start()
        logger.info("Telemetry recording started: %s", session_file)

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
        """Record an IMU reading. No-op if disabled.

        When stationary, only records every _STATIONARY_DECIMATION-th sample
        to reduce file size during long sessions.
        """
        if not self.enabled or imu is None:
            return
        moving = imu.get("moving", False)
        if not moving:
            self._imu_skip_count += 1
            if self._imu_skip_count < _STATIONARY_DECIMATION:
                return
            self._imu_skip_count = 0
        else:
            self._imu_skip_count = 0
        record = {
            "t": _rf(time.time()),
            "e": "imu",
            "q": _serialize_quat(imu.get("quat")),
            "pos": _serialize_vec(imu.get("pos")),
            "mv": moving,
            "st": imu.get("status", 0),
            "gyro": _serialize_vec(imu.get("gyro")),
            "accel": _serialize_vec(imu.get("accel")),
        }
        self._buffer.append(json.dumps(record) + "\n")

    def record_solve(self, solve_dict, predicted_ra=None, predicted_dec=None):
        """Record a plate solve result. No-op if disabled.

        predicted_ra/predicted_dec are the integrator's IMU-predicted position
        just before the solve arrived, enabling drift measurement.

        Returns the timestamp used for the record, or None if not recorded.
        """
        if not self.enabled or solve_dict is None:
            return None
        t = time.time()
        cam = solve_dict.get("camera_center", {})
        cam_is_dict = isinstance(cam, dict)
        record = {
            "t": _rf(t),
            "e": "solve",
            "ra": _rf(solve_dict["RA"]) if solve_dict.get("RA") is not None else None,
            "dec": _rf(solve_dict["Dec"])
            if solve_dict.get("Dec") is not None
            else None,
            "roll": _rf(solve_dict["Roll"])
            if solve_dict.get("Roll") is not None
            else None,
            "pred_ra": _rf(predicted_ra) if predicted_ra is not None else None,
            "pred_dec": _rf(predicted_dec) if predicted_dec is not None else None,
            "cam_ra": _rf(cam["RA"])
            if cam_is_dict and cam.get("RA") is not None
            else None,
            "cam_dec": _rf(cam["Dec"])
            if cam_is_dict and cam.get("Dec") is not None
            else None,
            "cam_roll": _rf(cam["Roll"])
            if cam_is_dict and cam.get("Roll") is not None
            else None,
            "iq": _serialize_quat(solve_dict.get("imu_quat")),
            "ip": _serialize_vec(solve_dict.get("imu_pos")),
            "matches": solve_dict.get("Matches"),
            "rmse": _rf(solve_dict["RMSE"])
            if solve_dict.get("RMSE") is not None
            else None,
            "lsa": solve_dict.get("last_solve_attempt"),
            "lss": solve_dict.get("last_solve_success"),
            "src": solve_dict.get("solve_source"),
        }
        self._buffer.append(json.dumps(record) + "\n")
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
        self._buffer.append(json.dumps(record) + "\n")

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
        """Flush the buffer to disk."""
        if not self._file or not self._buffer:
            return
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
        """Load all events from the JSONL file."""
        file_path = self.path
        if file_path.is_dir():
            file_path = file_path / "session.jsonl"

        with open(file_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                event = json.loads(line)
                if event.get("e") == "hdr":
                    self.header = event
                else:
                    self.events.append(event)

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
    def event_to_solve_dict(event):
        """Convert a recorded solve event to the fields needed by solved dict."""
        result = {
            "RA": event["ra"],
            "Dec": event["dec"],
            "Roll": event.get("roll"),
            "camera_center": {
                "RA": event.get("cam_ra"),
                "Dec": event.get("cam_dec"),
                "Roll": event.get("cam_roll"),
                "Alt": None,
                "Az": None,
            },
            "Matches": event.get("matches"),
            "RMSE": event.get("rmse"),
            "last_solve_attempt": event.get("lsa"),
            "last_solve_success": event.get("lss"),
            "solve_source": event.get("src", "CAM"),
            "solve_time": event["t"],
            "imu_pos": event.get("ip"),
        }
        iq = event.get("iq")
        if iq:
            result["imu_quat"] = quaternion_module.quaternion(
                iq[0], iq[1], iq[2], iq[3]
            )
        return result

    @staticmethod
    def event_to_imu_dict(event):
        """Convert a recorded IMU event to an imu dict, or None if no quat."""
        q = event.get("q")
        if not q:
            return None
        return {
            "quat": quaternion_module.quaternion(q[0], q[1], q[2], q[3]),
            "moving": event.get("mv", False),
            "status": event.get("st", 0),
        }


class TelemetryManager:
    """
    Facade over TelemetryRecorder and TelemetryPlayer.

    Owns all telemetry I/O: command dispatch, recording, replay state,
    image saving, and console/camera queue messaging.  The integrator
    only needs to call a handful of one-liners.
    """

    def __init__(self, cfg, shared_state, console_queue, camera_command_queue=None):
        self._cfg = cfg
        self._shared_state = shared_state
        self._console_queue = console_queue
        self._camera_command_queue = camera_command_queue
        self._recorder = TelemetryRecorder()
        self._recorder.images_enabled = bool(cfg.get_option("telemetry_images"))
        self._player = None
        if cfg.get_option("telemetry_record"):
            self._recorder.start(cfg, shared_state)

    @property
    def replaying(self):
        return self._player is not None

    def poll_commands(self, command_queue):
        """Check for and dispatch any pending telemetry commands."""
        if command_queue is None:
            return
        import queue

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
            self._player = TelemetryPlayer(cmd_arg)
            if self._player.header:
                self._apply_replay_header(self._player.header, self._shared_state)
            self._console_queue.put("Telemetry: Replay started")

        elif cmd_name == "replay_stop":
            logger.info("Exiting replay mode")
            self._player = None
            self._restart_camera()
            self._console_queue.put("Telemetry: Replay stopped")

    def next_replay_event(self):
        """Return the next replay event, or None.

        Automatically clears replay state and restarts camera when done.
        """
        if self._player is None:
            return None
        event, done = self._player.get_next_event()
        if done and event is None:
            self._player = None
            self._restart_camera()
            self._console_queue.put("Telemetry: Replay finished")
            logger.info("Replay finished")
            return None
        return event

    def handle_replay_event(
        self, event, solved, last_image_solve, imu_dead_reckoning, mount_type
    ):
        """Process a single replayed event. Returns updated last_image_solve."""
        if event["e"] == "imu":
            imu = TelemetryPlayer.event_to_imu_dict(event)
            if imu and last_image_solve and imu_dead_reckoning.tracking:
                update_imu(imu_dead_reckoning, solved, last_image_solve, imu)
                if solved["RA"] is not None:
                    finalize_and_push_solution(self._shared_state, solved, mount_type)

        elif event["e"] == "solve":
            replay_dict = TelemetryPlayer.event_to_solve_dict(event)

            # Always update metadata (needed for auto-exposure)
            for key in [
                "Matches",
                "RMSE",
                "last_solve_attempt",
                "last_solve_success",
            ]:
                if replay_dict.get(key) is not None:
                    solved[key] = replay_dict[key]

            if event.get("ra") is not None:
                # Successful solve — update position and push
                solved.update(replay_dict)
                self._shared_state.set_solve_state(True)
                update_plate_solve_and_imu(imu_dead_reckoning, solved)
                finalize_and_push_solution(self._shared_state, solved, mount_type)
                return copy.deepcopy(solved)
            else:
                # Failed solve — mirror normal-mode behavior
                solved["solve_source"] = "CAM_FAILED"
                solved["constellation"] = ""
                self._shared_state.set_solution(solved)
                self._shared_state.set_solve_state(False)

        return last_image_solve

    def record_solve(self, solve_dict, predicted_ra=None, predicted_dec=None):
        """Record a solve event and send save_image command if enabled."""
        t = self._recorder.record_solve(solve_dict, predicted_ra, predicted_dec)
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
        self._recorder.record_imu(imu)

    def flush(self):
        self._poll_target()
        self._recorder.flush()

    def _poll_target(self):
        """Check if the user's target changed and record it."""
        if not self._recorder.enabled:
            return
        try:
            target = self._shared_state.ui_state().target()
        except Exception:
            return
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

    def _apply_replay_header(self, hdr, shared_state):
        """Apply location/datetime from a replay session header."""
        loc_data = self._load_replay_location()
        if loc_data:
            loc = shared_state.location()
            loc.lat = loc_data["lat"]
            loc.lon = loc_data["lon"]
            loc.altitude = loc_data["altitude"]
            loc.lock = True
            loc.source = "replay"
            shared_state.set_location(loc)
        if hdr.get("dt"):
            shared_state.set_datetime(datetime.fromisoformat(hdr["dt"]))

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
