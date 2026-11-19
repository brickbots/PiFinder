"""
Unit tests for the shared-memory state snapshot (PiFinder/state_snapshot.py):
slot writes and reads, the version check, the size limit, the derived values,
the heartbeat, no half-written read between processes, and the wiring with a
real manager as main.py does it.
"""

import datetime
import logging
import multiprocessing
import time
import uuid
from multiprocessing.managers import BaseManager
import pytest

# Installs the ``_()`` gettext builtin that PiFinder.ui modules rely on.
import PiFinder.i18n  # noqa: F401
from PiFinder import state_snapshot
from PiFinder.state import Location, SharedStateObj
from PiFinder.state_snapshot import (
    SLOT_SIZES,
    SnapshotBlock,
    SnapshotWriter,
    StateReader,
    StateSnapshot,
)
from PiFinder.state_utils import SharedStateLost
from PiFinder.types.positioning import PointingEstimate
from PiFinder.ui.base import CurrentSnapshot, UIModule

pytestmark = pytest.mark.unit


@pytest.fixture
def block():
    block = SnapshotBlock(name=f"pifinder_test_{uuid.uuid4().hex[:12]}")
    yield block
    block.close()


@pytest.fixture
def writer(block):
    writer = SnapshotWriter(block.spec)
    yield writer
    writer._buf.release()
    writer._shm.close()


@pytest.fixture
def reader(block):
    reader = StateReader(block.spec)
    yield reader
    reader.close()


def test_a_published_value_reads_back(writer, reader):
    writer.publish("sats", (7, 12))
    writer.publish("camera_type", "imx462")
    snapshot = reader.read()
    assert snapshot.sats() == (7, 12)
    assert snapshot.camera_type() == "imx462"


def test_an_unwritten_slot_reads_its_default_and_a_written_none_stays_none(
    writer, reader
):
    assert reader.read().sqm_details() == {}
    assert reader.read().optical_train_known() is True
    writer.publish("sqm_details", None)
    assert reader.read().sqm_details() is None


def test_an_unchanged_slot_is_not_decoded_again(writer, reader):
    writer.publish("location", Location(lat=51.0, lon=4.4))
    first = reader.read().location()
    assert reader.read().location() is first
    writer.publish("location", Location(lat=52.0, lon=4.4))
    assert reader.read().location().lat == 52.0


def test_a_value_too_large_for_its_slot_leaves_the_slot_unchanged(
    writer, reader, caplog
):
    writer.publish("sats", (1, 2))
    with caplog.at_level(logging.ERROR, logger="SharedState.Snapshot"):
        writer.publish("sats", list(range(SLOT_SIZES["sats"])))
    assert "do not fit" in caplog.text
    assert reader.read().sats() == (1, 2)


def test_solve_state_comes_with_its_solution(writer, reader):
    solution = PointingEstimate()
    writer.publish("solution", (solution, False))
    snapshot = reader.read()
    assert snapshot.solve_state() is False
    assert snapshot.solution() is not None


def test_datetime_advances_from_the_stored_time():
    stored = datetime.datetime(2026, 9, 30, 20, 0, tzinfo=datetime.timezone.utc)
    snapshot = StateSnapshot({"datetime": (stored, time.time() - 10.0)})
    assert 9.0 < (snapshot.datetime() - stored).total_seconds() < 12.0
    assert snapshot.utc_datetime().tzinfo is not None


def test_local_datetime_uses_the_location_timezone():
    stored = datetime.datetime(2026, 9, 30, 20, 0, tzinfo=datetime.timezone.utc)
    snapshot = StateSnapshot(
        {
            "datetime": (stored, time.time()),
            "location": Location(timezone="Europe/Brussels"),
        }
    )
    assert snapshot.local_datetime().utcoffset() == datetime.timedelta(hours=2)
    no_zone = StateSnapshot(
        {"datetime": (stored, time.time()), "location": Location(timezone=None)}
    )
    assert no_zone.local_datetime().utcoffset() == datetime.timedelta(0)


def test_altaz_ready_needs_a_lock_and_a_time():
    now = (datetime.datetime.now(datetime.timezone.utc), time.time())
    assert not StateSnapshot({"location": Location(lock=True)}).altaz_ready()
    assert not StateSnapshot(
        {"location": Location(lock=False), "datetime": now}
    ).altaz_ready()
    assert StateSnapshot(
        {"location": Location(lock=True), "datetime": now}
    ).altaz_ready()


def test_a_snapshot_rejects_unknown_values():
    with pytest.raises(KeyError):
        StateSnapshot({"solutoin": None})


def test_an_old_heartbeat_means_the_manager_is_gone(writer, reader):
    writer.publish("heartbeat", time.monotonic())
    reader.read()
    writer.publish("heartbeat", time.monotonic() - state_snapshot.HEARTBEAT_TIMEOUT - 1)
    with pytest.raises(SharedStateLost):
        reader.read()


def _write_pairs(spec, stop_at):
    """Publishes (n, [n] * k) with a size that changes on every write."""
    writer = SnapshotWriter(spec)
    n = 0
    while time.monotonic() < stop_at:
        n += 1
        writer.publish("solution", ((n, [n] * (n % 200)), None))


def test_a_reader_never_sees_a_half_written_slot(block, reader):
    stop_at = time.monotonic() + 1.5
    process = multiprocessing.Process(target=_write_pairs, args=(block.spec, stop_at))
    process.start()
    seen = set()
    try:
        while time.monotonic() < stop_at:
            value = reader.read().solution()
            if value is None:
                continue
            n, repeated = value
            assert repeated == [n] * (n % 200)
            seen.add(n)
    finally:
        process.join()
    assert process.exitcode == 0
    assert len(seen) > 10


class _Manager(BaseManager):
    pass


_Manager.register("SharedState", SharedStateObj)


def test_setters_through_the_manager_reach_the_snapshot(block, reader):
    manager = _Manager()
    manager.start(initializer=state_snapshot.attach_writer, initargs=(block.spec,))
    try:
        shared_state = manager.SharedState()
        # The manager publishes every value when it builds the object.
        assert reader.read().solution() is not None

        shared_state.set_power_state(0)
        shared_state.set_sats((5, 9))
        shared_state.set_location(Location(lat=51.0, lon=4.4, lock=True))
        shared_state.set_datetime(datetime.datetime.now(datetime.timezone.utc))
        snapshot = reader.read()
        assert snapshot.power_state() == 0
        assert snapshot.sats() == (5, 9)
        assert snapshot.location().lat == 51.0
        assert snapshot.altaz_ready()

        # A value the setter rejects does not reach the snapshot either.
        shared_state.set_power_state(7)
        assert reader.read().power_state() == 0
    finally:
        manager.shutdown()


def test_the_snapshot_reads_like_the_shared_state_proxy():
    """Every getter of StateSnapshot has a SharedStateObj getter of the same
    name, so read-only code accepts either."""
    getters = {
        name
        for name in dir(StateSnapshot)
        if not name.startswith("_")
        and callable(getattr(StateSnapshot, name))
        and name != "from_state"
    }
    missing = {name for name in getters if not hasattr(SharedStateObj, name)}
    assert missing == set()


def test_current_snapshot_answers_from_the_frame_snapshot(monkeypatch):
    view = CurrentSnapshot()
    monkeypatch.setattr(UIModule, "snapshot", StateSnapshot({"sats": (1, 1)}))
    assert view.sats() == (1, 1)
    monkeypatch.setattr(UIModule, "snapshot", StateSnapshot({"sats": (2, 3)}))
    assert view.sats() == (2, 3)
