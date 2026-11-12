"""MountControlIndi against a real indiserver and the INDI telescope
simulator. indiserver starts with no driver; the mount code starts the
simulator through the FIFO, as on the device."""

import datetime
import os
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path
from queue import Queue
from typing import Iterator
from unittest.mock import Mock

import numpy as np
import pytest

from PiFinder import indi_drivers, satellites, track_rates
from PiFinder.mount_settings import MountSettings
from PiFinder.mountcontrol_indi import POSITION, MountControlIndi
from PiFinder.mountcontrol_interface import MountControlPhases, angular_distance
from PiFinder.satellite_follow import FollowPoint, FollowStage, SatelliteFollow
from PiFinder.sky_sim import SkySimSettings, SkySimulator
from PiFinder.types.positioning import (
    PointingAxis,
    PointingEstimate,
    PointingMatrix,
    SuccessfulSolve,
)
from PiFinder.state import Location, SharedStateObj

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("indiserver") is None, reason="needs INDI"),
]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _indi_data_dir() -> Path:
    indiserver = Path(shutil.which("indiserver") or "").resolve()
    return indiserver.parent.parent / "share" / "indi"


@pytest.fixture
def indi(tmp_path: Path, monkeypatch) -> Iterator[int]:
    port = _free_port()
    fifo = tmp_path / "run" / "fifo"
    fifo.parent.mkdir()
    os.mkfifo(fifo)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("INDI_FIFO", str(fifo))
    monkeypatch.setenv("INDI_DATA_DIR", str(_indi_data_dir()))
    proc = subprocess.Popen(
        # A private local socket (-u): the default one allows one indiserver
        # per machine.
        [
            "indiserver",
            "-p",
            str(port),
            "-u",
            f"/tmp/indiserver-test-{port}",
            "-f",
            str(fifo),
        ],
        env={**os.environ, "HOME": str(home)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
            break
        except OSError:
            time.sleep(0.1)
    yield port
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def _shared_state() -> Mock:
    shared_state = Mock(spec=SharedStateObj)
    shared_state.location.return_value = Location(
        lat=50.85, lon=-4.35, altitude=60.0, lock=True
    )
    shared_state.datetime.return_value = datetime.datetime.now(datetime.timezone.utc)
    shared_state.solution.return_value = None
    return shared_state


def _wait(predicate, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return False


def test_init_goto_sync_stop_with_simulator(indi: int) -> None:
    assert indi_drivers.find_model(indi_drivers.SIMULATOR) is not None
    mount = MountControlIndi(
        Queue(),
        Queue(),
        _shared_state(),
        None,
        MountSettings(enabled=True, model=indi_drivers.SIMULATOR),
        indi_port=indi,
    )
    try:
        assert mount.init_mount()
        assert mount.device == "Telescope Simulator"

        # Location (longitude 0..360 East) and time reached the driver.
        assert _wait(
            lambda: mount.client.get_value(mount.device, "GEOGRAPHIC_COORD", "LONG")
            == pytest.approx(355.65, abs=1e-3),
            5,
        )
        assert mount.client.get_value(
            mount.device, "GEOGRAPHIC_COORD", "LAT"
        ) == pytest.approx(50.85, abs=1e-3)

        # Goto: Busy, then target reached.
        assert mount.move_mount_to_target(30.0, 20.0)
        assert _wait(lambda: mount.target_reached, 60)
        assert not mount.is_mount_moving()
        assert mount.current_ra == pytest.approx(30.0, abs=0.05)
        assert mount.current_dec == pytest.approx(20.0, abs=0.05)

        # Sync. The simulator confirms with a message but keeps reporting
        # its own position.
        assert mount.sync_mount(31.0, 21.0)
        assert _wait(
            lambda: any(
                "Sync is successful" in m for m in mount.client.messages(mount.device)
            ),
            5,
        )
        assert mount.client.get_value(mount.device, "ON_COORD_SET", "TRACK") is True

        # A manual step is a short goto.
        mount.target_reached = False
        dec_before = mount.current_dec
        assert mount._move_mount_manual("north", 1.0)
        assert _wait(
            lambda: mount.client.get_value(mount.device, POSITION, "DEC")
            == pytest.approx(dec_before + 1.0, abs=0.1),
            30,
        )

        # Stop during a long goto.
        assert mount.move_mount_to_target(200.0, -30.0)
        assert _wait(mount.is_mount_moving, 5)
        assert mount.stop_mount()
    finally:
        mount.disconnect_mount()
        indi_drivers.stop_driver()


def test_unknown_model_fails_without_driver(indi: int) -> None:
    console = Queue()
    mount = MountControlIndi(
        Queue(),
        console,
        _shared_state(),
        None,
        MountSettings(enabled=True, model="No Such Mount"),
        indi_port=indi,
    )
    assert not mount.init_mount()
    assert console.get_nowait()[0] == "WARNING"


def test_wifi_mount_driver_connects_to_the_address(indi: int) -> None:
    """The OnStep driver in TCP mode opens a connection to the address that
    PiFinder sets. A dummy server accepts it; it does not answer the LX200
    handshake, so the init itself fails."""
    model = indi_drivers.find_model("LX200 OnStep")
    assert model is not None
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    server.settimeout(30)
    address = f"127.0.0.1:{server.getsockname()[1]}"
    console: Queue = Queue()
    mount = MountControlIndi(
        Queue(),
        console,
        _shared_state(),
        None,
        MountSettings(
            enabled=True, model="LX200 OnStep", connection="wifi", address=address
        ),
        indi_port=indi,
    )
    accepted: list[bytes] = []

    def accept() -> None:
        try:
            conn, _addr = server.accept()
        except OSError:
            return
        conn.settimeout(5)
        try:
            accepted.append(conn.recv(64))
        except OSError:
            accepted.append(b"")
        conn.close()

    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    try:
        mount.init_mount()
        thread.join(timeout=30)
        assert accepted, "the driver did not connect to the WiFi address"
        assert mount.client.get_value(mount.device, "CONNECTION_MODE", "CONNECTION_TCP")
        assert (
            mount.client.get_value(mount.device, "DEVICE_ADDRESS", "PORT")
            == (address.split(":")[1])
        )
    finally:
        server.close()
        mount.disconnect_mount()
        indi_drivers.stop_driver()


def test_reload_switches_model_and_turns_off(indi: int) -> None:
    """reload_config applies new settings at once: off stops the driver,
    on with another model starts that driver."""
    settings = [MountSettings(enabled=True, model=indi_drivers.SIMULATOR)]
    console: Queue = Queue()
    mount = MountControlIndi(
        Queue(),
        console,
        _shared_state(),
        None,
        settings[0],
        load_settings=lambda: settings[0],
        indi_port=indi,
    )
    running = Path(os.environ["INDI_FIFO"]).parent / indi_drivers.RUNNING_DRIVER_FILE
    try:
        assert mount.init_mount()
        assert "indi_simulator_telescope" in running.read_text()

        settings[0] = MountSettings(enabled=False, model=indi_drivers.SIMULATOR)
        mount.reload_settings()
        assert mount.state == MountControlPhases.MOUNT_UNKNOWN
        assert mount.device is None
        assert not running.exists()
        assert not mount.init_mount()

        settings[0] = MountSettings(enabled=True, model=indi_drivers.SIMULATOR)
        mount.reload_settings()
        assert mount.state == MountControlPhases.MOUNT_INIT_TELESCOPE
        assert mount.init_mount()
        assert mount.device == "Telescope Simulator"
    finally:
        mount.disconnect_mount()
        indi_drivers.stop_driver()


def _simulator_mount(indi: int) -> MountControlIndi:
    return MountControlIndi(
        Queue(),
        Queue(),
        _shared_state(),
        None,
        MountSettings(enabled=True, model=indi_drivers.SIMULATOR),
        indi_port=indi,
    )


def test_drift_compensation_uses_custom_tracking(indi: int) -> None:
    """INDI applies a track rate only in TRACK_CUSTOM mode; a new goto goes
    back to sidereal."""
    mount = _simulator_mount(indi)
    try:
        assert mount.init_mount()
        device = mount.device
        rate = mount.client.get_value(device, "TELESCOPE_TRACK_RATE", "TRACK_RATE_RA")
        assert mount.adjust_mount_drift_rates(0.001, 0.0)
        assert _wait(
            lambda: mount.client.get_value(
                device, "TELESCOPE_TRACK_MODE", "TRACK_CUSTOM"
            )
            is True,
            5,
        )
        assert _wait(
            lambda: mount.client.get_value(
                device, "TELESCOPE_TRACK_RATE", "TRACK_RATE_RA"
            )
            == pytest.approx(rate + 3.6, abs=0.01),
            5,
        )
        assert not any(
            "must be set to Custom" in m for m in mount.client.messages(device)
        )
        assert mount.move_mount_to_target(40.0, 10.0)
        assert _wait(
            lambda: mount.client.get_value(
                device, "TELESCOPE_TRACK_MODE", "TRACK_SIDEREAL"
            )
            is True,
            5,
        )
    finally:
        mount.disconnect_mount()
        indi_drivers.stop_driver()


def test_sync_reply_does_not_end_the_next_goto(indi: int) -> None:
    """The driver confirms a sync with state Ok. When that reply comes after
    the next goto was sent, the goto must still run to its end."""
    mount = _simulator_mount(indi)
    try:
        assert mount.init_mount()
        assert mount.move_mount_to_target(30.0, 20.0)
        assert _wait(lambda: mount.target_reached, 60)
        mount.target_reached = False
        assert mount.sync_mount(30.5, 20.5)
        assert mount.move_mount_to_target(120.0, -10.0)
        time.sleep(1.0)
        assert not mount.target_reached
        assert mount.is_mount_moving()
        assert _wait(lambda: mount.target_reached, 90)
        assert mount.current_dec == pytest.approx(-10.0, abs=0.1)
    finally:
        mount.disconnect_mount()
        indi_drivers.stop_driver()


def test_stale_running_driver_record_is_restarted(indi: int) -> None:
    """A record that names the driver while indiserver does not run it must
    not stop the init."""
    running = Path(os.environ["INDI_FIFO"]).parent / indi_drivers.RUNNING_DRIVER_FILE
    model = indi_drivers.find_model(indi_drivers.SIMULATOR)
    assert model is not None
    running.write_text(f"{model.driver}\t{model.device_name}\n")
    mount = _simulator_mount(indi)
    try:
        assert mount.init_mount()
        assert mount.device == "Telescope Simulator"
    finally:
        mount.disconnect_mount()
        indi_drivers.stop_driver()


def test_status_follows_a_goto(indi: int) -> None:
    """The mount process status shows the slew with a shrinking distance."""
    shared_state = _shared_state()
    mount = MountControlIndi(
        Queue(),
        Queue(),
        shared_state,
        None,
        MountSettings(enabled=True, model=indi_drivers.SIMULATOR),
        indi_port=indi,
    )
    try:
        assert mount.init_mount()
        mount.state = MountControlPhases.MOUNT_TRACKING
        for _step in mount._process_command(
            {"type": "goto_target", "ra": 60.0, "dec": 10.0}
        ):
            pass
        distances = []
        deadline = time.time() + 60
        while time.time() < deadline and not mount.target_reached:
            status = mount.mount_status()
            assert status.model == indi_drivers.SIMULATOR
            if status.distance_deg is not None:
                distances.append(status.distance_deg)
            time.sleep(0.5)
        assert mount.target_reached
        assert len(distances) >= 2
        assert distances[-1] < distances[0]
        assert mount.mount_status().text == "Slewing"
        mount.publish_status()
        assert shared_state.set_mount_status.called
    finally:
        mount.disconnect_mount()
        indi_drivers.stop_driver()


def test_closed_loop_goto_refines_onto_the_target(indi: int) -> None:
    """The full loop: the mount process, the INDI simulator and the sky
    simulator with a 1.5° pointing error. A goto must end "On target" (within
    0.01°) after at most three refine rounds."""
    latest: list = []
    shared_state = _shared_state()

    def solution():
        if not latest:
            return None
        solve = latest[-1]
        axis = PointingAxis(solve=solve.aligned, estimate=solve.aligned)
        return PointingEstimate(
            pointing=PointingMatrix(camera=axis, aligned=axis),
            last_solve_success=solve.last_solve_success,
        )

    shared_state.solution.side_effect = solution
    mount = MountControlIndi(
        Queue(),
        Queue(),
        shared_state,
        None,
        MountSettings(enabled=True, model=indi_drivers.SIMULATOR),
        indi_port=indi,
    )
    sim = SkySimulator(
        SkySimSettings(
            rate_hz=2.0,
            offset_ra_deg=1.5,
            offset_dec_deg=-0.8,
            noise_arcsec=5,
            seed=3,
            indi_port=indi,
        ),
        shared_state.datetime,
    )
    # The simulator listens before the driver starts, as in the app, so it
    # sees the driver's startup positions too.
    sim.next_message()
    runner = threading.Thread(target=mount.run, daemon=True)
    runner.start()
    try:
        assert _wait(lambda: mount.state == MountControlPhases.MOUNT_TRACKING, 30)
        for _step in range(10):
            sim.next_message()
            time.sleep(0.1)
        target = (80.0, 25.0)
        mount.mount_queue.put(
            {"type": "goto_target", "ra": target[0], "dec": target[1]}
        )
        deadline = time.time() + 180
        while time.time() < deadline:
            message = sim.next_message()
            if isinstance(message, SuccessfulSolve):
                latest.append(message)
            if mount.state == MountControlPhases.MOUNT_DRIFT_COMPENSATION:
                break
            time.sleep(0.05)
        assert mount.state == MountControlPhases.MOUNT_DRIFT_COMPENSATION
        assert 1 <= mount._refine_count <= 3
        solve = mount.latest_solve()
        assert solve is not None
        assert abs((solve[0] - target[0] + 180) % 360 - 180) <= 0.01
        assert abs(solve[1] - target[1]) <= 0.01
        assert sim.sync_ra == pytest.approx(1.5, abs=0.01)
    finally:
        mount.mount_queue.put({"type": "exit"})
        runner.join(timeout=10)
        mount.disconnect_mount()
        indi_drivers.stop_driver()


def test_gps_lock_during_a_slew_does_not_stop_it(indi: int) -> None:
    """The location arrives while the mount slews. PiFinder sends it after
    the slew, so the goto ends at the target."""
    shared_state = _shared_state()
    shared_state.location.return_value = Location(lock=False)
    mount = _simulator_mount(indi)
    mount.shared_state = shared_state
    runner = threading.Thread(target=mount.run, daemon=True)
    runner.start()
    try:
        assert _wait(lambda: mount.state == MountControlPhases.MOUNT_TRACKING, 30)
        mount.mount_queue.put({"type": "goto_target", "ra": 250.0, "dec": -10.0})
        assert _wait(mount.is_mount_moving, 10)
        shared_state.location.return_value = Location(
            lat=50.85, lon=-4.35, altitude=60.0, lock=True
        )
        mount.last_periodic_update = 0.0
        # The state machine clears target_reached when it goes to REFINE, so
        # wait for the mount to stand at the target.
        assert _wait(
            lambda: not mount.is_mount_moving()
            and mount.current_ra is not None
            and abs(mount.current_ra - 250.0) < 0.1,
            120,
        )
        warnings = []
        while not mount.console_queue.empty():
            message = mount.console_queue.get_nowait()
            if message[0] == "WARNING":
                warnings.append(message[1])
        assert "Goto interrupted" not in warnings
        assert _wait(
            lambda: mount.client.get_value(mount.device, "GEOGRAPHIC_COORD", "LAT")
            == pytest.approx(50.85, abs=1e-3),
            40,
        )
    finally:
        mount.mount_queue.put({"type": "exit"})
        runner.join(timeout=10)
        mount.disconnect_mount()
        indi_drivers.stop_driver()


def test_continuous_move_north_until_stop(indi: int) -> None:
    """A held arrow: the simulator moves north until the stop."""
    mount = _simulator_mount(indi)
    try:
        assert mount.init_mount()
        assert mount.move_mount_to_target(60.0, 10.0)
        assert _wait(lambda: mount.target_reached, 60)
        dec_start = mount.client.get_value(mount.device, POSITION, "DEC")
        assert mount.start_motion(1.0, 0.0)
        time.sleep(2.0)
        assert mount.stop_motion()
        time.sleep(1.0)
        dec_stopped = mount.client.get_value(mount.device, POSITION, "DEC")
        assert dec_stopped > dec_start + 0.05
        time.sleep(1.5)
        dec_later = mount.client.get_value(mount.device, POSITION, "DEC")
        assert dec_later == pytest.approx(dec_stopped, abs=0.01)
    finally:
        mount.disconnect_mount()
        indi_drivers.stop_driver()


def _follow_rates(mount, ra_rate: float, dec_rate: float, seconds: float):
    """Set the rates once a second, as the satellite follow does, and return
    the rates measured in the last two seconds."""
    end = time.time() + seconds
    while time.time() < end - 2.0:
        assert mount.set_track_rates(ra_rate, dec_rate)
        time.sleep(1.0)
    start = (time.time(), mount.current_ra, mount.current_dec)
    assert mount.set_track_rates(ra_rate, dec_rate)
    time.sleep(2.0)
    elapsed = time.time() - start[0]
    return (
        ((mount.current_ra - start[1] + 540) % 360 - 180) / elapsed,
        (mount.current_dec - start[2]) / elapsed,
    )


def test_satellite_track_rates_move_the_mount_at_those_rates(indi: int) -> None:
    """set_track_rates gives absolute RA/Dec rates in both directions; it
    learns the sign convention of the driver from the motion."""
    mount = _simulator_mount(indi)
    try:
        assert mount.init_mount()
        assert mount.move_mount_to_target(40.0, 10.0)
        assert _wait(lambda: mount.target_reached, 60)
        ra_rate, dec_rate = _follow_rates(mount, 0.05, 0.02, 10.0)
        assert ra_rate == pytest.approx(0.05, abs=0.01)
        assert dec_rate == pytest.approx(0.02, abs=0.01)
        ra_rate, dec_rate = _follow_rates(mount, -0.05, -0.02, 8.0)
        assert ra_rate == pytest.approx(-0.05, abs=0.01)
        assert dec_rate == pytest.approx(-0.02, abs=0.01)
        mount.restore_sidereal_tracking()
        assert _wait(
            lambda: mount.client.get_value(
                mount.device, "TELESCOPE_TRACK_MODE", "TRACK_SIDEREAL"
            )
            is True,
            5,
        )
    finally:
        mount.disconnect_mount()
        indi_drivers.stop_driver()


def test_follow_a_moving_target_end_to_end(indi: int, monkeypatch) -> None:
    """The satellite follow with the simulator: aim ahead, wait, then track a
    target that moves 0.03°/s in RA and 0.01°/s in Dec."""
    t0 = time.time()

    def point(_self, unix_time: float) -> FollowPoint:
        seconds = unix_time - t0
        return FollowPoint(
            ra=(60.0 + 0.03 * seconds) % 360.0,
            dec=20.0 + 0.01 * seconds,
            ra_rate=0.03,
            dec_rate=0.01,
            alt=45.0,
        )

    monkeypatch.setattr(SatelliteFollow, "point", point)
    mount = _simulator_mount(indi)
    try:
        assert mount.init_mount()
        mount.state = MountControlPhases.MOUNT_TRACKING
        element = satellites.parse_elements(
            (Path(__file__).parent / "data" / "satellites" / "25544.3le").read_text()
        )[0][0]
        for _step in mount._process_command(
            {
                "type": "follow_satellite",
                "name": "TEST",
                "line1": element.line1,
                "line2": element.line2,
            }
        ):
            pass
        assert mount.state == MountControlPhases.MOUNT_SATELLITE_FOLLOW
        follow = mount._follow
        tracking_since = None
        deadline = time.time() + 120
        while time.time() < deadline:
            mount._follow_step(time.time())
            if follow.stage == FollowStage.TRACK and tracking_since is None:
                tracking_since = time.time()
            if tracking_since and time.time() - tracking_since > 10:
                break
            time.sleep(0.1)
        assert tracking_since is not None, follow.stage
        target = point(None, mount.current_time)
        error = angular_distance(
            mount.current_ra, mount.current_dec, target.ra, target.dec
        )
        assert error < 0.1
        assert mount._follow is follow and follow.aim_count <= 2
    finally:
        mount.disconnect_mount()
        indi_drivers.stop_driver()


def test_lunar_rate_uses_the_indi_track_mode(indi: int) -> None:
    mount = _simulator_mount(indi)
    try:
        assert mount.init_mount()
        assert mount.apply_track_rate(track_rates.LUNAR)
        assert _wait(
            lambda: mount.client.get_value(
                mount.device, "TELESCOPE_TRACK_MODE", "TRACK_LUNAR"
            )
            is True,
            5,
        )
        assert mount.apply_track_rate(track_rates.SIDEREAL)
        assert _wait(
            lambda: mount.client.get_value(
                mount.device, "TELESCOPE_TRACK_MODE", "TRACK_SIDEREAL"
            )
            is True,
            5,
        )
    finally:
        mount.disconnect_mount()
        indi_drivers.stop_driver()


def test_lunar_rate_as_custom_rates_without_the_track_mode(
    indi: int, monkeypatch
) -> None:
    """A driver without TRACK_LUNAR gets the motion of the Moon as custom
    rates: the RA of the mount grows by about half an arcsecond a second."""
    monkeypatch.setitem(track_rates.INDI_TRACK_MODES, track_rates.LUNAR, "NONE")
    mount = _simulator_mount(indi)
    try:
        assert mount.init_mount()
        assert mount.move_mount_to_target(40.0, 10.0)
        assert _wait(lambda: mount.target_reached, 60)
        assert mount.apply_track_rate(track_rates.LUNAR)
        location = mount.shared_state.location()
        moon_ra, _moon_dec = track_rates.body_rates(
            track_rates.LUNAR,
            location.lat,
            location.lon,
            location.altitude,
            mount.shared_state.datetime(),
        )
        assert _wait(
            lambda: mount.client.get_value(
                mount.device, "TELESCOPE_TRACK_RATE", "TRACK_RATE_RA"
            )
            == pytest.approx(15.041067 - moon_ra * 3600.0, abs=0.01),
            5,
        )
        time.sleep(1.5)
        start = (mount.current_time, mount.current_ra)
        time.sleep(8.0)
        ra_rate = (mount.current_ra - start[1]) / (mount.current_time - start[0])
        assert ra_rate * 3600 == pytest.approx(moon_ra * 3600, abs=0.2)
    finally:
        mount.disconnect_mount()
        indi_drivers.stop_driver()


def _solve_drift(solves: list, seconds: float) -> tuple[float, float]:
    """RA and Dec drift in arcseconds per second of the solves of the last
    ``seconds``, by a straight line fit."""
    end = solves[-1].last_solve_success
    recent = [s for s in solves if s.last_solve_success >= end - seconds]
    times = np.array([s.last_solve_success for s in recent])
    ra = np.unwrap(np.radians([s.aligned.RA for s in recent]))
    dec = np.array([s.aligned.Dec for s in recent])
    ra_slope = np.degrees(np.polyfit(times, ra, 1)[0]) * 3600.0
    dec_slope = np.polyfit(times, dec, 1)[0] * 3600.0
    return float(ra_slope), float(dec_slope)


@pytest.mark.parametrize("wrong_axis", [None, "ra", "dec"])
def test_drift_compensation_removes_a_drift(indi: int, wrong_axis) -> None:
    """The mount drifts 10"/s in RA and 20"/s in Dec on target. Drift
    compensation must stop the drift, also when it starts with the wrong
    sign of an axis for this driver."""
    latest: list = []
    shared_state = _shared_state()

    def solution():
        if not latest:
            return None
        solve = latest[-1]
        axis = PointingAxis(solve=solve.aligned, estimate=solve.aligned)
        return PointingEstimate(
            pointing=PointingMatrix(camera=axis, aligned=axis),
            last_solve_success=solve.last_solve_success,
        )

    shared_state.solution.side_effect = solution
    mount = MountControlIndi(
        Queue(),
        Queue(),
        shared_state,
        None,
        MountSettings(enabled=True, model=indi_drivers.SIMULATOR),
        indi_port=indi,
    )
    mount.drift_compensation_window = 4.0
    sim = SkySimulator(
        SkySimSettings(rate_hz=4.0, noise_arcsec=2, seed=5, indi_port=indi),
        shared_state.datetime,
    )
    sim.next_message()
    runner = threading.Thread(target=mount.run, daemon=True)
    runner.start()

    def feed(seconds: float) -> None:
        end = time.time() + seconds
        while time.time() < end:
            message = sim.next_message()
            if isinstance(message, SuccessfulSolve):
                latest.append(message)
            time.sleep(0.05)

    try:
        assert _wait(lambda: mount.state == MountControlPhases.MOUNT_TRACKING, 30)
        feed(1.0)
        mount.mount_queue.put({"type": "goto_target", "ra": 80.0, "dec": 25.0})
        deadline = time.time() + 120
        while (
            time.time() < deadline
            and mount.state != MountControlPhases.MOUNT_DRIFT_COMPENSATION
        ):
            feed(0.2)
        assert mount.state == MountControlPhases.MOUNT_DRIFT_COMPENSATION
        if wrong_axis == "ra":
            mount._ra_rate_sign = -mount._ra_rate_sign
        if wrong_axis == "dec":
            mount._dec_rate_sign = -mount._dec_rate_sign
        # No correction while the drift is measured.
        mount.drift_compensation_window = 1000.0
        # The drift: custom rates that the mount process does not know.
        assert mount._set_switch("TELESCOPE_TRACK_MODE", "TRACK_CUSTOM")
        assert mount._set_number(
            "TELESCOPE_TRACK_RATE",
            {"TRACK_RATE_RA": 15.041067 - 10.0, "TRACK_RATE_DE": 20.0},
        )
        feed(6.0)
        before = _solve_drift(latest, 4.0)
        assert abs(before[0]) > 5 and abs(before[1]) > 10, before
        mount.drift_compensation_window = 4.0
        feed(60.0)
        after = _solve_drift(latest, 6.0)
        assert mount.state == MountControlPhases.MOUNT_DRIFT_COMPENSATION
        assert abs(after[0]) < 2.0 and abs(after[1]) < 2.0, (before, after)
    finally:
        mount.mount_queue.put({"type": "exit"})
        runner.join(timeout=10)
        mount.disconnect_mount()
        indi_drivers.stop_driver()
