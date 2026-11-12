"""RA rotation of the mount for the polar alignment, with a fake mount."""

import datetime
from queue import Queue
from unittest.mock import Mock

import pytest

from PiFinder import mountcontrol_interface
from PiFinder.mountcontrol_interface import MountControlBase, MountControlPhases
from PiFinder.state import Location, SharedStateObj

pytestmark = pytest.mark.unit

DT = datetime.datetime(2026, 11, 12, 22, 0, tzinfo=datetime.timezone.utc)
LOCATION = Location(lat=50.85, lon=4.35, altitude=50.0, lock=True)


class RotatingMount(MountControlBase):
    def __init__(self):
        shared_state = Mock(spec=SharedStateObj)
        shared_state.datetime.return_value = DT
        shared_state.location.return_value = LOCATION
        super().__init__(Queue(), Queue(), shared_state)
        self.start_motion = Mock(return_value=True)
        self.stop_motion = Mock(return_value=True)
        self.stop_mount = Mock(return_value=True)
        self.notify = Mock()
        self.state = MountControlPhases.MOUNT_TRACKING
        self.current_ra = 100.0
        self.current_dec = 30.0

    def command(self, command: dict) -> None:
        for _step in self._process_command(command):
            pass

    def phase(self) -> None:
        for _step in self._process_phase():
            pass


def lst_deg() -> float:
    t = mountcontrol_interface.calc_utils.sf_utils.ts.from_datetime(DT)
    return (t.gast * 15.0 + LOCATION.lon) % 360.0


def test_rotation_turns_the_ra_axis_by_the_angle():
    mount = RotatingMount()
    mount.command({"type": "rotate_ra", "degrees": 30.0})
    assert mount.state == MountControlPhases.MOUNT_RA_ROTATION
    north, east = mount.start_motion.call_args.args
    assert north == 0.0 and abs(east) == 1.0
    assert mount.start_motion.call_args.kwargs == {"fastest": True}
    assert mount.status_text() == "Turning RA"

    mount.current_ra += 15.0 * east
    mount.phase()
    assert mount.state == MountControlPhases.MOUNT_RA_ROTATION
    mount.stop_motion.assert_not_called()

    mount.current_ra += 16.0 * east
    mount.phase()
    assert mount.state == MountControlPhases.MOUNT_TRACKING
    mount.stop_motion.assert_called_once()


def test_rotation_ends_on_stop_and_on_timeout():
    mount = RotatingMount()
    mount.command({"type": "rotate_ra", "degrees": 30.0})
    mount.command({"type": "stop_movement"})
    mount.stop_motion.assert_called()
    assert mount._rotation is None

    mount = RotatingMount()
    mount.command({"type": "rotate_ra", "degrees": 30.0})
    started = mount._rotation[2]
    mount._rotation_step(started + mountcontrol_interface.RA_ROTATION_TIMEOUT_S + 1)
    assert mount.state == MountControlPhases.MOUNT_TRACKING
    assert mount.console_queue.get_nowait() == ["WARNING", "Rotation too slow"]


@pytest.mark.parametrize(
    "hour_angle, expected_east",
    [
        (120.0, True),  # far west: toward the meridian is east
        (-120.0, False),  # far east: toward the meridian is west
        (30.0, False),  # near the meridian: away from it, not across
        (-30.0, True),
    ],
)
def test_rotation_direction(hour_angle, expected_east):
    mount = RotatingMount()
    mount.current_ra = (lst_deg() - hour_angle) % 360.0
    assert mount.rotation_direction_east() is expected_east


def test_rotation_needs_a_mount_position():
    mount = RotatingMount()
    mount.current_ra = None
    mount.command({"type": "rotate_ra", "degrees": 30.0})
    assert mount.state == MountControlPhases.MOUNT_TRACKING
    mount.start_motion.assert_not_called()
