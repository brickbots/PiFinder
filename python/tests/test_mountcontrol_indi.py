"""MountControlIndi against a real indiserver and the INDI telescope
simulator. indiserver starts with no driver; the mount code starts the
simulator through the FIFO, as on the device."""

import datetime
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path
from queue import Queue
from typing import Iterator
from unittest.mock import Mock

import pytest

from PiFinder import indi_drivers
from PiFinder.mountcontrol_indi import POSITION, MountControlIndi
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
        ["indiserver", "-p", str(port), "-f", str(fifo)],
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
        indi_drivers.SIMULATOR,
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
    mount = MountControlIndi(Queue(), console, _shared_state(), None, "No Such Mount")
    assert not mount.init_mount()
    assert console.get_nowait()[0] == "WARNING"
