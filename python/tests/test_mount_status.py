"""The live mount status: the text lines, the publish rules and the
snapshot slot."""

from queue import Queue
from unittest.mock import Mock

import pytest

from PiFinder.mountcontrol_interface import (
    STATUS_HEARTBEAT_S,
    MountControlBase,
    MountControlPhases,
    angular_distance,
)
from PiFinder.state import SharedStateObj
from PiFinder.state_snapshot import StateSnapshot
from PiFinder.types.mount import STATUS_MAX_AGE_S, MountStatus, status_lines

pytestmark = pytest.mark.unit


def _status(**values):
    fields = dict(
        phase="MOUNT_TARGET_ACQUISITION_MOVE",
        text="Slewing",
        distance_deg=12.4,
        step_deg=14.6 / 60,
        model="SAL-33",
        updated=1000.0,
    )
    fields.update(values)
    return MountStatus(**fields)


def test_status_lines():
    assert status_lines(_status(), now=1001.0) == ["Slewing 12.4°", "Step 14.6'"]
    tracking = _status(phase="MOUNT_TRACKING", text="Tracking")
    assert status_lines(tracking, now=1001.0) == ["Tracking", "Step 14.6'"]
    assert status_lines(_status(distance_deg=None), now=1001.0)[0] == "Slewing"


def test_status_lines_without_status():
    assert status_lines(None) == ["No mount status"]
    stale = 1000.0 + STATUS_MAX_AGE_S + 0.1
    assert status_lines(_status(), now=stale) == ["No mount status"]


def test_angular_distance():
    assert angular_distance(10, 20, 10, 20) == pytest.approx(0.0, abs=1e-9)
    assert angular_distance(0, 0, 90, 0) == pytest.approx(90.0)
    assert angular_distance(359.5, 0, 0.5, 0) == pytest.approx(1.0)
    assert angular_distance(0, 89, 180, 89) == pytest.approx(2.0)


def _mount():
    mount = MountControlBase(Queue(), Queue(), Mock(spec=SharedStateObj))
    mount.notify = Mock()
    return mount


def test_status_from_state():
    mount = _mount()
    mount.state = MountControlPhases.MOUNT_TARGET_ACQUISITION_REFINE
    mount._refine_count = 1
    mount.target_ra, mount.target_dec = 10.0, 20.0
    mount.current_ra, mount.current_dec = 10.0, 21.0
    status = mount.mount_status(now=5.0)
    assert status.text == "Refining 2/3"
    assert status.distance_deg == pytest.approx(1.0)
    assert status.updated == 5.0


def test_publish_rules(monkeypatch):
    mount = _mount()
    clock = [100.0]
    monkeypatch.setattr("PiFinder.mountcontrol_interface.time.time", lambda: clock[0])
    publish = mount.shared_state.set_mount_status

    mount.publish_status()
    assert publish.call_count == 1
    # Nothing changed: no write.
    clock[0] += 0.1
    mount.publish_status()
    assert publish.call_count == 1
    # A phase change: written at once.
    mount.state = MountControlPhases.MOUNT_STOPPED
    mount.publish_status()
    assert publish.call_count == 2
    # Only the distance changes: at most once per second.
    mount.target_ra, mount.target_dec = 10.0, 20.0
    mount.current_ra, mount.current_dec = 10.0, 25.0
    clock[0] += 0.2
    mount.publish_status()
    assert publish.call_count == 2
    clock[0] += 1.0
    mount.publish_status()
    assert publish.call_count == 3
    # The heartbeat writes an unchanged status too.
    clock[0] += STATUS_HEARTBEAT_S
    mount.publish_status()
    assert publish.call_count == 4


def test_snapshot_slot():
    assert StateSnapshot().mount_status() is None
    status = _status()
    assert StateSnapshot({"mount_status": status}).mount_status() is status
