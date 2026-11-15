"""RA rotation of the mount for the polar alignment, with a fake mount."""

import datetime
from queue import Queue
from unittest.mock import Mock

import pytest

from PiFinder import mountcontrol_interface
from PiFinder.mountcontrol_interface import (
    MountControlBase,
    MountControlPhases,
    plan_ra_rotation,
    ra_rotation_room,
)
from PiFinder.state import Location, SharedStateObj
from PiFinder.types.mount import (
    ROTATION_DONE,
    ROTATION_FAILED,
    ROTATION_REFUSED,
    ROTATION_STALE,
    ROTATION_STOPPED,
    ROTATION_TIMEOUT,
    ROTATION_TURNING,
)

pytestmark = pytest.mark.unit

DT = datetime.datetime(2026, 11, 12, 22, 0, tzinfo=datetime.timezone.utc)
LAT = 50.85
LOCATION = Location(lat=LAT, lon=4.35, altitude=50.0, lock=True)
LST_DEG = mountcontrol_interface.local_sidereal_deg(DT, LOCATION.lon)


class RotatingMount(MountControlBase):
    """A mount at hour angle 30° west and declination +30°. It can turn
    more than 30° to the west and not 30° to the east."""

    def __init__(self, hour_angle=30.0, location=LOCATION):
        shared_state = Mock(spec=SharedStateObj)
        shared_state.datetime.return_value = DT
        shared_state.location.return_value = location
        super().__init__(Queue(), Queue(), shared_state)
        self.start_motion = Mock(return_value=True)
        self.stop_motion = Mock(return_value=True)
        self.stop_mount = Mock(return_value=True)
        self.notify = Mock()
        self.slewing = False
        self.altaz = False
        self.state = MountControlPhases.MOUNT_TRACKING
        self.current_ra = (LST_DEG - hour_angle) % 360.0
        self.current_dec = 30.0

    def is_slewing(self) -> bool:
        return self.slewing

    def is_altaz(self) -> bool:
        return self.altaz

    def command(self, command: dict) -> None:
        for _step in self._process_command(command):
            pass

    def turn(self, degrees_east: float, now: float) -> None:
        """The mount reports a new position, then the main loop checks."""
        self.mount_current_position(self.current_ra + degrees_east, self.current_dec)
        self._position_time = now
        self.check_motion_timeout(now)

    def warnings(self) -> list:
        texts = []
        while not self.console_queue.empty():
            texts.append(self.console_queue.get_nowait()[1])
        return texts


def rotate(mount: RotatingMount, angle_deg: float, rotation_id: int = 7) -> float:
    """Send the command. Return the start time of the rotation."""
    mount.command({"type": "rotate_ra", "angle_deg": angle_deg, "id": rotation_id})
    return mount._motion_started


# Item 1: the sender chooses the direction, the mount executes it.


@pytest.mark.parametrize(
    "hour_angle, angle_deg, east",
    [(30.0, -20.0, -1.0), (70.0, 20.0, 1.0), (-70.0, -20.0, -1.0), (-30.0, 20.0, 1.0)],
)
def test_rotation_turns_in_the_direction_of_the_sign(hour_angle, angle_deg, east):
    mount = RotatingMount(hour_angle)
    started = rotate(mount, angle_deg)
    assert mount.state == MountControlPhases.MOUNT_RA_ROTATION
    assert mount.start_motion.call_args.args == (0.0, east)
    assert mount.start_motion.call_args.kwargs == {"fastest": True}
    assert mount.status_text() == "Turning RA"
    assert mount.mount_status().rotation == ROTATION_TURNING
    assert mount.mount_status().rotation_id == 7

    mount.turn(10.0 * east, started + 1)
    assert mount.state == MountControlPhases.MOUNT_RA_ROTATION
    mount.stop_motion.assert_not_called()

    mount.turn(10.5 * east, started + 2)
    mount.stop_motion.assert_called_once()
    mount.start_motion.assert_called_once()


def test_second_rotation_keeps_the_direction_of_the_command():
    """After the first turn the mount is nearer to a limit. The mount does
    not choose a new direction: it turns as the command says, or refuses."""
    mount = RotatingMount(30.0)
    for _turn in range(2):
        started = rotate(mount, -20.0)
        assert mount.start_motion.call_args.args == (0.0, -1.0)
        mount.turn(-20.5, started + 1)
        mount.check_motion_timeout(started + 4)
        assert mount.mount_status().rotation == ROTATION_DONE
    # Hour angle 71°: a third turn to the west has no room.
    rotate(mount, -20.0)
    assert mount.mount_status().rotation == ROTATION_REFUSED
    assert mount.start_motion.call_count == 2


# Item 2: the limits of the sequence.


def test_room_stops_at_the_meridian_and_at_the_hour_angle_limit():
    east, west = ra_rotation_room(30.0, 30.0, LAT)
    assert east == pytest.approx(27.0)  # to 3° before the meridian
    assert west == pytest.approx(55.0)  # to hour angle 85°
    east, west = ra_rotation_room(-30.0, 30.0, LAT)
    assert (east, west) == (pytest.approx(55.0), pytest.approx(27.0))
    assert ra_rotation_room(100.0, 30.0, LAT) == (0.0, 0.0)


def test_room_stops_at_the_altitude_limit():
    # At declination -10° the altitude is 15° at hour angle 50.7°.
    _east, west = ra_rotation_room(30.0, -10.0, LAT)
    assert west == pytest.approx(20.7, abs=0.1)
    # Declination -30° never reaches 15° at this latitude.
    assert ra_rotation_room(0.0, -30.0, LAT) == (0.0, 0.0)
    # The same sky from a southern site.
    _east, west = ra_rotation_room(30.0, 10.0, -LAT)
    assert west == pytest.approx(20.7, abs=0.1)


@pytest.mark.parametrize(
    "hour_angle, lat, dec, expected",
    [
        (30.0, LAT, 30.0, -21.5),  # no room toward the meridian: turn away
        (-30.0, LAT, 30.0, 21.5),
        (70.0, LAT, 30.0, 27.5),  # toward the meridian
        (-70.0, LAT, 30.0, -27.5),
        (40.0, LAT, 30.0, 12.5),  # both fit: toward the meridian, higher
        (70.0, -33.0, -30.0, 27.5),  # southern site
        (100.0, LAT, 30.0, None),
        (-100.0, LAT, 30.0, None),
        (150.0, LAT, 30.0, None),
        (30.0, LAT, -10.0, None),  # too low at the end of the turn
    ],
)
def test_plan_for_two_rotations(hour_angle, lat, dec, expected):
    step = plan_ra_rotation(hour_angle, dec, lat, 30.0, 2, 10.0)
    if expected is None:
        assert step is None
        return
    assert step == pytest.approx(expected)
    # The two rotations and the overshoot stay inside the limits.
    end = hour_angle - 2 * step
    assert abs(end) <= mountcontrol_interface.RA_ROTATION_MAX_HA_DEG
    assert end * hour_angle > 0


@pytest.mark.parametrize("hour_angle, angle_deg", [(30.0, 30.0), (45.0, -45.0)])
def test_unsafe_rotation_is_refused(hour_angle, angle_deg):
    # East 30° from 30° crosses the meridian. West 45° from 45° passes
    # hour angle 85°.
    mount = RotatingMount(hour_angle)
    rotate(mount, angle_deg)
    mount.start_motion.assert_not_called()
    assert mount.state == MountControlPhases.MOUNT_TRACKING
    assert mount.warnings() == ["RA turn not safe"]
    status = mount.mount_status()
    assert (status.rotation_id, status.rotation) == (7, ROTATION_REFUSED)


def test_rotation_needs_position_and_site():
    mount = RotatingMount()
    mount.current_ra = None
    rotate(mount, -20.0)
    assert mount.warnings() == ["No mount position"]

    no_lock = Location(lat=LAT, lon=4.35, altitude=50.0, lock=False)
    mount = RotatingMount(location=no_lock)
    rotate(mount, -20.0)
    assert mount.warnings() == ["Need GPS lock"]
    mount.start_motion.assert_not_called()


# Item 3: no rotation during a goto, and every exit stops the motion.


def test_rotation_is_refused_during_a_goto():
    mount = RotatingMount()
    mount.state = MountControlPhases.MOUNT_TARGET_ACQUISITION_MOVE
    rotate(mount, -20.0)
    assert mount.state == MountControlPhases.MOUNT_TARGET_ACQUISITION_MOVE

    mount = RotatingMount()
    mount.slewing = True
    rotate(mount, -20.0)
    assert mount.warnings() == ["Mount is slewing"]
    mount.start_motion.assert_not_called()
    assert mount.mount_status().rotation == ROTATION_REFUSED


def test_phase_change_stops_the_rotation():
    mount = RotatingMount()
    started = rotate(mount, -20.0)
    # A mount event changes the phase during the rotation.
    mount.state = MountControlPhases.MOUNT_STOPPED
    mount.check_motion_timeout(started + 0.1)
    mount.stop_motion.assert_called_once()
    assert mount._rotation is None and mount._motion_started is None
    assert mount.state == MountControlPhases.MOUNT_STOPPED
    assert mount.mount_status().rotation == ROTATION_STOPPED


@pytest.mark.parametrize(
    "command",
    [
        {"type": "stop_movement"},
        {"type": "motion_stop"},
        {"type": "motion_start", "north": 1.0, "east": 0.0},
        {"type": "goto_target", "ra": 10.0, "dec": 20.0},
    ],
)
def test_any_command_stops_the_rotation(command):
    mount = RotatingMount()
    mount.move_mount_to_target = Mock(return_value=True)
    rotate(mount, -20.0)
    mount.command(command)
    assert mount.stop_motion.call_count >= 1
    assert mount._rotation is None
    assert mount.mount_status().rotation == ROTATION_STOPPED


def test_slow_rotation_stops_on_the_timeout():
    mount = RotatingMount()
    started = rotate(mount, -20.0)
    end = started + mountcontrol_interface.RA_ROTATION_TIMEOUT_S + 1
    mount.turn(-1.0, end)
    mount.stop_motion.assert_called_once()
    assert mount.warnings() == ["Rotation too slow"]
    assert mount.mount_status().rotation == ROTATION_TIMEOUT


def test_rotation_stops_without_new_positions():
    mount = RotatingMount()
    started = rotate(mount, -20.0)
    mount.turn(-1.0, started + 1)
    mount.check_motion_timeout(started + 3)
    mount.stop_motion.assert_not_called()
    mount.check_motion_timeout(started + 1 + 3.1)
    mount.stop_motion.assert_called_once()
    assert mount.warnings() == ["No mount position"]
    assert mount.mount_status().rotation == ROTATION_STALE


def test_rotation_stops_when_the_mount_turns_the_wrong_way():
    mount = RotatingMount()
    started = rotate(mount, -20.0)
    mount.turn(2.5, started + 1)
    mount.stop_motion.assert_called_once()
    assert mount.warnings() == ["Wrong RA direction"]
    assert mount.mount_status().rotation == ROTATION_FAILED


def test_failed_stop_aborts_the_mount():
    mount = RotatingMount()
    mount.stop_motion.return_value = False
    started = rotate(mount, -20.0)
    mount.turn(-20.5, started + 1)
    mount.stop_mount.assert_called_once()
    assert mount.warnings() == ["Move not stopped!"]
    assert mount.mount_status().rotation == ROTATION_FAILED


# Item 5: the result, the phase after the rotation and the wait until still.


def test_done_only_when_the_mount_is_still():
    mount = RotatingMount()
    started = rotate(mount, -20.0)
    mount.turn(-20.5, started + 1)
    assert mount.mount_status().rotation == ROTATION_TURNING
    # The mount still moves after the stop: the wait starts again.
    mount.turn(-0.5, started + 2.5)
    mount.check_motion_timeout(started + 4)
    assert mount.mount_status().rotation == ROTATION_TURNING
    mount.check_motion_timeout(started + 4.6)
    assert mount.mount_status().rotation == ROTATION_DONE
    assert mount.state == MountControlPhases.MOUNT_TRACKING
    mount.stop_motion.assert_called_once()
    mount.stop_mount.assert_not_called()


def test_mount_that_never_stands_still_is_aborted():
    mount = RotatingMount()
    started = rotate(mount, -20.0)
    mount.turn(-20.5, started + 1)
    now = started + 1
    while mount._rotation is not None and now < started + 60:
        now += 1.0
        mount.turn(-0.1, now)
    assert now == pytest.approx(
        started + 2 + mountcontrol_interface.RA_ROTATION_STILL_TIMEOUT_S
    )
    mount.stop_mount.assert_called_once()
    assert mount.warnings() == ["Mount not still"]
    assert mount.mount_status().rotation == ROTATION_TIMEOUT


@pytest.mark.parametrize(
    "previous, expected",
    [
        (MountControlPhases.MOUNT_STOPPED, MountControlPhases.MOUNT_STOPPED),
        (MountControlPhases.MOUNT_TRACKING, MountControlPhases.MOUNT_TRACKING),
        (
            MountControlPhases.MOUNT_DRIFT_COMPENSATION,
            MountControlPhases.MOUNT_TRACKING,
        ),
    ],
)
def test_phase_after_the_rotation(previous, expected):
    mount = RotatingMount()
    mount.state = previous
    started = rotate(mount, -20.0)
    mount.turn(-20.5, started + 1)
    mount.check_motion_timeout(started + 4)
    assert mount.state == expected


def test_failed_start_is_reported():
    mount = RotatingMount()
    mount.start_motion.return_value = False
    rotate(mount, -20.0)
    assert mount.state == MountControlPhases.MOUNT_TRACKING
    assert mount.warnings() == ["Mount did not move!"]
    assert mount.mount_status().rotation == ROTATION_FAILED


def test_status_carries_the_position_and_the_rotation():
    mount = RotatingMount()
    mount.shared_state.set_mount_status = Mock()
    mount.publish_status()
    rotate(mount, -20.0, rotation_id=42)
    mount.publish_status()
    status = mount.shared_state.set_mount_status.call_args.args[0]
    assert (status.rotation_id, status.rotation) == (42, ROTATION_TURNING)
    assert status.ra_deg == mount.current_ra and status.dec_deg == 30.0
    mount.command({"type": "stop_movement"})
    mount.publish_status()
    status = mount.shared_state.set_mount_status.call_args.args[0]
    assert (status.rotation_id, status.rotation) == (42, ROTATION_STOPPED)


# Item 6: the mount type.


def test_altaz_mount_is_refused():
    mount = RotatingMount()
    mount.altaz = True
    rotate(mount, -20.0)
    mount.start_motion.assert_not_called()
    assert mount.warnings() == ["Not equatorial"]
    assert mount.mount_status().altaz is True
    assert mount.mount_status().rotation == ROTATION_REFUSED
