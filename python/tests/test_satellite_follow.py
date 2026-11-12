"""Satellite follow: the plan and the mount control phase, with a fake mount."""

from pathlib import Path
from queue import Queue
from unittest.mock import Mock

import pytest

import PiFinder.satellites as satellites
from PiFinder import satellite_follow
from PiFinder.mountcontrol_interface import MountControlBase, MountControlPhases
from PiFinder.satellite_follow import FollowStage, SatelliteFollow
from PiFinder.state import Location, SharedStateObj

pytestmark = pytest.mark.unit

DATA = Path(__file__).parent / "data" / "satellites"
LOCATION = Location(lat=50.85, lon=4.35, altitude=50.0, lock=True)


def iss_elements() -> satellites.SatElements:
    return satellites.parse_elements((DATA / "25544.3le").read_text())[0][0]


def iss_pass() -> satellites.SatPass:
    """A high pass of the ISS over Brussels after the fixture epoch."""
    element = iss_elements()
    sat = satellites.TrackedSatellite.from_elements(element)
    topos = satellites.observer_topos(LOCATION.lat, LOCATION.lon, LOCATION.altitude)
    passes = satellites.find_passes(sat, topos, element.epoch, hours=24)
    return max(passes, key=lambda item: item.max_alt)


def follow_command() -> dict:
    element = iss_elements()
    return {
        "type": "follow_satellite",
        "norad_id": element.norad_id,
        "name": element.name,
        "line1": element.line1,
        "line2": element.line2,
    }


class FakeMount(MountControlBase):
    def __init__(self, rates_ok: bool):
        shared_state = Mock(spec=SharedStateObj)
        shared_state.location.return_value = LOCATION
        super().__init__(Queue(), Queue(), shared_state)
        self.stop_mount = Mock(return_value=True)
        self.move_mount_to_target = Mock(return_value=True)
        self.is_mount_moving = Mock(return_value=True)
        self.set_track_rates = Mock(return_value=rates_ok)
        self.restore_sidereal_tracking = Mock()
        self.notify = Mock()
        self.state = MountControlPhases.MOUNT_TRACKING
        self.now = 0.0
        self.clock = lambda: self.now

    def command(self, command: dict) -> None:
        for _step in self._process_command(command):
            pass

    def phase(self) -> None:
        for _step in self._process_phase():
            pass


def test_follow_point_gives_jnow_position_and_rates():
    culmination = iss_pass().culmination.timestamp()
    follow = SatelliteFollow(iss_elements(), LOCATION.lat, LOCATION.lon, 50.0)
    now = follow.point(culmination)
    later = follow.point(culmination + 1.0)
    assert now.alt > 30
    assert now.ra_rate == pytest.approx((later.ra - now.ra + 540) % 360 - 180, abs=1e-3)
    assert now.dec_rate == pytest.approx(later.dec - now.dec, abs=1e-3)
    # The ISS high in the sky moves about a degree per second.
    assert abs(now.ra_rate) + abs(now.dec_rate) > 0.2


def test_lead_learns_the_slew_time():
    follow = SatelliteFollow(iss_elements(), LOCATION.lat, LOCATION.lon, 50.0)
    follow.aim(1000.0)
    assert follow.aim_time == 1000.0 + satellite_follow.DEFAULT_LEAD_S
    follow.slew_done(1010.0)
    assert follow.lead_s == pytest.approx(10.0 * satellite_follow.LEAD_MARGIN)
    assert follow.stage == FollowStage.WAIT
    follow.aim(2000.0)
    follow.slew_done(2001.0)
    assert follow.lead_s == satellite_follow.MIN_LEAD_S


def test_follow_with_custom_rates_aims_waits_and_tracks():
    mount = FakeMount(rates_ok=True)
    mount.now = iss_pass().culmination.timestamp() - 90.0
    mount.command(follow_command())
    assert mount.state == MountControlPhases.MOUNT_SATELLITE_FOLLOW
    follow = mount._follow
    assert follow is not None and follow.stage == FollowStage.AIM
    aim_ra, aim_dec = mount.move_mount_to_target.call_args.args
    expected = follow.point(mount.now + satellite_follow.DEFAULT_LEAD_S)
    assert (aim_ra, aim_dec) == pytest.approx((expected.ra, expected.dec))
    assert mount.status_text() == "Sat: slewing"

    # The slew ends after 8 s, before the satellite arrives.
    mount.now += 8.0
    mount.target_reached = True
    mount.phase()
    assert follow.stage == FollowStage.WAIT
    assert mount.status_text().startswith("Sat: in")

    # The satellite arrives: the mount tracks at its rates.
    mount.now = follow.aim_time + 0.1
    mount.current_ra, mount.current_dec = aim_ra, aim_dec
    mount.phase()
    assert follow.stage == FollowStage.TRACK
    ra_rate, dec_rate = mount.set_track_rates.call_args.args
    point = follow.point(mount.now)
    assert (ra_rate, dec_rate) == pytest.approx((point.ra_rate, point.dec_rate))

    # The rates update once a second.
    calls = mount.set_track_rates.call_count
    mount.now += 1.1
    mount.current_ra, mount.current_dec = (
        follow.point(mount.now).ra,
        follow.point(mount.now).dec,
    )
    mount.phase()
    assert mount.set_track_rates.call_count == calls + 1
    assert mount.mount_status().distance_deg == pytest.approx(0.0, abs=1e-6)

    # The mount falls behind: aim again.
    gotos = mount.move_mount_to_target.call_count
    mount.current_ra = (mount.current_ra + 2.0) % 360
    mount.phase()
    assert mount.move_mount_to_target.call_count == gotos + 1
    assert follow.stage == FollowStage.AIM


def test_follow_without_custom_rates_repeats_gotos_ahead():
    mount = FakeMount(rates_ok=False)
    mount.now = iss_pass().culmination.timestamp() - 120.0
    mount.command(follow_command())
    follow = mount._follow
    mount.now += 5.0
    mount.target_reached = True
    mount.phase()
    mount.now = follow.aim_time + 0.1
    mount.phase()
    assert follow.stage == FollowStage.PASS
    gotos = mount.move_mount_to_target.call_count
    # Still near the aim point: hold.
    mount.phase()
    assert mount.move_mount_to_target.call_count == gotos
    # Some seconds later the satellite is past: the next goto ahead.
    mount.now += 10.0
    mount.phase()
    assert mount.move_mount_to_target.call_count == gotos + 1
    assert follow.stage == FollowStage.AIM


def test_follow_ends_when_the_satellite_sets_or_on_another_command():
    pass_ = iss_pass()
    mount = FakeMount(rates_ok=True)
    mount.now = pass_.culmination.timestamp()
    mount.command(follow_command())
    mount.now = pass_.set.timestamp() + 60.0
    mount.phase()
    assert mount._follow is None
    mount.stop_mount.assert_called()
    mount.restore_sidereal_tracking.assert_called()

    mount = FakeMount(rates_ok=True)
    mount.now = pass_.culmination.timestamp()
    mount.command(follow_command())
    mount.shared_state.datetime.return_value = None
    mount.command({"type": "set_step_size", "step_size": 0.5})
    assert mount._follow is not None
    mount.command({"type": "stop_movement"})
    assert mount._follow is None


def test_follow_refuses_a_satellite_below_the_horizon():
    mount = FakeMount(rates_ok=True)
    mount.now = iss_pass().set.timestamp() + 300.0
    mount.command(follow_command())
    assert mount._follow is None
    mount.move_mount_to_target.assert_not_called()
    assert mount.console_queue.get_nowait() == ["WARNING", "Satellite too low"]
