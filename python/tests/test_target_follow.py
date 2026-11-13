"""Follow of a moving target: the plan and the mount control phase, with a
fake mount."""

import datetime
import math
import time
from pathlib import Path
from queue import Queue
from unittest.mock import Mock

import pytest

import PiFinder.satellites as satellites
from PiFinder import target_follow
from PiFinder.mountcontrol_interface import MountControlBase, MountControlPhases
from PiFinder.target_follow import (
    BodyTarget,
    FollowStage,
    SampledTarget,
    SatelliteTarget,
    TargetFollow,
    angular_distance,
)
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


def iss_target() -> SatelliteTarget:
    return SatelliteTarget(iss_elements(), LOCATION.lat, LOCATION.lon, 50.0)


def follow_command() -> dict:
    element = iss_elements()
    return {
        "type": "follow_target",
        "kind": "satellite",
        "norad_id": element.norad_id,
        "name": element.name,
        "line1": element.line1,
        "line2": element.line2,
    }


class FakeMount(MountControlBase):
    def __init__(self, rates_ok: bool):
        shared_state = Mock(spec=SharedStateObj)
        shared_state.location.return_value = LOCATION
        shared_state.solution.return_value = None
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
    follow = iss_target()
    now = follow.point(culmination)
    later = follow.point(culmination + 1.0)
    assert now.alt > 30
    assert now.ra_rate == pytest.approx((later.ra - now.ra + 540) % 360 - 180, abs=1e-3)
    assert now.dec_rate == pytest.approx(later.dec - now.dec, abs=1e-3)
    # The ISS high in the sky moves about a degree per second.
    assert abs(now.ra_rate) + abs(now.dec_rate) > 0.2


def test_lead_learns_the_slew_time():
    start = iss_pass().culmination.timestamp()
    follow = TargetFollow(iss_target(), start)
    assert follow.fast
    follow.aim(1000.0)
    assert follow.aim_time == 1000.0 + target_follow.DEFAULT_LEAD_S
    follow.slew_done(1010.0)
    assert follow.lead_s == pytest.approx(10.0 * target_follow.LEAD_MARGIN)
    assert follow.stage == FollowStage.WAIT
    follow.aim(2000.0)
    follow.slew_done(2001.0)
    assert follow.lead_s == target_follow.MIN_LEAD_S


def test_follow_with_custom_rates_aims_waits_and_tracks():
    mount = FakeMount(rates_ok=True)
    mount.now = iss_pass().culmination.timestamp() - 90.0
    mount.command(follow_command())
    assert mount.state == MountControlPhases.MOUNT_TARGET_FOLLOW
    follow = mount._follow
    assert follow is not None and follow.stage == FollowStage.AIM
    aim_ra, aim_dec = mount.move_mount_to_target.call_args.args
    expected = follow.point(mount.now + target_follow.DEFAULT_LEAD_S)
    assert (aim_ra, aim_dec) == pytest.approx((expected.ra, expected.dec))
    assert mount.status_text() == "Follow: slewing"

    # The slew ends after 8 s, before the satellite arrives.
    mount.now += 8.0
    mount.target_reached = True
    mount.phase()
    assert follow.stage == FollowStage.WAIT
    assert mount.status_text().startswith("Follow: in")

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
    mount.now += 1.1
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
    assert mount.console_queue.get_nowait() == ["WARNING", "Target too low"]


def test_follow_needs_the_time():
    mount = FakeMount(rates_ok=True)
    mount.clock = lambda: None
    mount.command(follow_command())
    assert mount._follow is None
    assert mount.console_queue.get_nowait() == ["WARNING", "No time"]


def test_trusted_time_is_the_pifinder_time_not_the_system_clock():
    mount = FakeMount(rates_ok=True)
    mount.shared_state.datetime.return_value = None
    assert mount._trusted_time() is None
    gps = datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc)
    mount.shared_state.datetime.return_value = gps
    assert mount._trusted_time() == pytest.approx(gps.timestamp(), abs=1.0)


def test_shift_elements_moves_the_satellite_along_its_track():
    elements = iss_elements()
    culmination = iss_pass().culmination.timestamp()
    shifted = target_follow.shift_elements(elements, 3.0)
    assert shifted.line1 == elements.line1
    assert shifted.line2 != elements.line2
    # The new lines are valid elements with a good checksum.
    satellites.parse_elements(shifted.to_tle())
    early = SatelliteTarget(shifted, LOCATION.lat, LOCATION.lon, 50.0).point(
        culmination
    )
    # The shifted satellite is now about where the original is 3 s later.
    # The rest is the motion of the observer with the Earth in 3 s.
    later = iss_target().point(culmination + 3.0)
    original = iss_target().point(culmination)
    moved = angular_distance(original.ra, original.dec, later.ra, later.dec)
    assert moved > 1.0
    assert angular_distance(early.ra, early.dec, later.ra, later.dec) < 0.2


def test_nudge_along_the_track_becomes_a_time_offset():
    now = iss_pass().culmination.timestamp()
    follow = TargetFollow(iss_target(), now)
    follow.aim(now)
    aim_time = follow.aim_time
    point = follow.point(now)
    # 2 s of motion along the track.
    north, east = (
        2.0 * point.dec_rate,
        2.0 * point.ra_rate * math.cos(math.radians(point.dec)),
    )
    follow.nudge(north, east, now)
    assert follow.time_offset_s == pytest.approx(2.0, abs=0.01)
    assert follow.cross_deg == pytest.approx(0.0, abs=1e-6)
    assert follow.aim_time == pytest.approx(aim_time - 2.0, abs=0.01)
    ahead = iss_target().point(now + 2.0)
    corrected = follow.point(now)
    assert angular_distance(corrected.ra, corrected.dec, ahead.ra, ahead.dec) < 0.15
    # The offset stays later in the pass: this is the path adjustment.
    ahead = iss_target().point(now + 32.0)
    corrected = follow.point(now + 30.0)
    assert angular_distance(corrected.ra, corrected.dec, ahead.ra, ahead.dec) < 0.15
    assert follow.corrected_elements().line2 != iss_elements().line2


def test_nudge_across_the_track_keeps_the_time():
    now = iss_pass().culmination.timestamp()
    follow = TargetFollow(iss_target(), now)
    point = follow.point(now)
    cos_dec = math.cos(math.radians(point.dec))
    # 0.2 degrees at a right angle to the motion.
    north = 0.2 * point.ra_rate * cos_dec / point.speed
    east = -0.2 * point.dec_rate / point.speed
    follow.nudge(north, east, now)
    assert follow.time_offset_s == pytest.approx(0.0, abs=1e-6)
    assert follow.cross_deg == pytest.approx(0.2)
    for seconds in (0.0, 30.0):
        base = iss_target().point(now + seconds)
        corrected = follow.point(now + seconds)
        distance = angular_distance(corrected.ra, corrected.dec, base.ra, base.dec)
        assert distance == pytest.approx(0.2, abs=0.01)
    assert follow.corrected_elements() is None


def test_arrow_during_a_follow_corrects_the_path_and_keeps_the_follow():
    mount = FakeMount(rates_ok=True)
    mount.move_mount_offset = Mock(return_value=True)
    mount.start_motion = Mock(return_value=True)
    mount.now = iss_pass().culmination.timestamp() - 60.0
    mount.command(follow_command())
    follow = mount._follow
    before = follow.point(mount.now)
    mount.command({"type": "manual_movement", "offset": (1.0, 0.0), "step_size": 0.5})
    assert mount._follow is follow
    mount.move_mount_offset.assert_not_called()
    after = follow.point(mount.now)
    assert angular_distance(before.ra, before.dec, after.ra, after.dec) == (
        pytest.approx(0.5, abs=0.05)
    )
    assert follow.corrected

    # A held arrow moves the path one step size per second.
    mount.step_size = 0.1
    mount.command({"type": "motion_start", "north": 0.0, "east": 1.0})
    mount.start_motion.assert_not_called()
    mount.now += 2.0
    at = mount.now
    held = follow.point(at)
    mount.phase()
    mount.command({"type": "motion_stop"})
    moved = follow.point(at)
    assert angular_distance(held.ra, held.dec, moved.ra, moved.dec) == (
        pytest.approx(0.2, abs=0.03)
    )
    mount.now += 2.0
    mount.phase()
    still = follow.point(at)
    assert angular_distance(still.ra, still.dec, moved.ra, moved.dec) < 1e-6


def test_plate_solve_before_the_pass_gives_a_pointing_offset(monkeypatch):
    mount = FakeMount(rates_ok=True)
    mount.now = iss_pass().culmination.timestamp() - 90.0
    mount.command(follow_command())
    follow = mount._follow
    aim_ra, aim_dec = mount.move_mount_to_target.call_args.args
    mount.now += 8.0
    mount.target_reached = True
    mount.current_ra, mount.current_dec = aim_ra, aim_dec
    mount.phase()
    assert follow.stage == FollowStage.WAIT
    # The camera solves 0.2 degrees north of the mount position, after the
    # mount came to rest.
    solved = time.time() + 2.0
    mount.latest_solve = Mock(return_value=(aim_ra, aim_dec + 0.2, solved))
    monkeypatch.setattr(time, "time", lambda: solved + 0.5)
    mount.phase()
    assert mount._follow_offset == pytest.approx((0.0, 0.2))
    assert mount._follow_pointing() == pytest.approx((aim_ra, aim_dec + 0.2))

    # In TRACK the rates pull the telescope 0.2 degrees south.
    mount.now = follow.aim_time + 0.1
    mount.phase()
    assert follow.stage == FollowStage.TRACK
    mount.now += 1.1
    point = follow.point(mount.now)
    mount.current_ra, mount.current_dec = point.ra, point.dec
    mount.phase()
    _ra_rate, dec_rate = mount.set_track_rates.call_args.args
    assert dec_rate == pytest.approx(
        point.dec_rate - 0.2 / target_follow.CORRECTION_S, abs=1e-3
    )
    # The next goto takes the offset into account.
    mount.now += 1.1
    mount.current_ra = (mount.current_ra + 2.0) % 360
    mount.phase()
    _goto_ra, goto_dec = mount.move_mount_to_target.call_args.args
    expected = follow.point(follow.aim_time)
    assert goto_dec == pytest.approx(expected.dec - 0.2)


def comet_samples(start: float) -> list:
    """A comet that moves 0.01 degrees a minute east and half of it north."""
    return [(start + 600.0 * i, 80.0 + 0.1 * i, 30.0 + 0.05 * i) for i in range(4)]


def test_sampled_target_interpolates_and_continues_after_the_last_sample():
    target = SampledTarget("C/2026 A1", comet_samples(1000.0), 50.85, 4.35)
    point = target.point(1300.0)
    assert (point.ra, point.dec) == pytest.approx((80.05, 30.025))
    assert point.ra_rate == pytest.approx(0.1 / 600.0)
    assert point.dec_rate == pytest.approx(0.05 / 600.0)
    after = target.point(1000.0 + 2400.0)
    assert (after.ra, after.dec) == pytest.approx((80.4, 30.2))
    with pytest.raises(ValueError):
        SampledTarget("one", comet_samples(0.0)[:1], 50.85, 4.35)


def test_altitude_agrees_with_skyfield():
    now = iss_pass().culmination.timestamp()
    point = iss_target().point(now)
    alt = target_follow.altitude(point.ra, point.dec, now, LOCATION.lat, LOCATION.lon)
    assert alt == pytest.approx(point.alt, abs=0.1)


def test_body_target_gives_the_motion_of_the_moon():
    now = datetime.datetime(2026, 11, 12, 22, tzinfo=datetime.timezone.utc)
    point = BodyTarget("moon", 50.85, 4.35, 50.0).point(now.timestamp())
    assert 10 / 86400 < point.ra_rate < 18 / 86400
    with pytest.raises(ValueError):
        BodyTarget("vulcan", 50.85, 4.35, 50.0)


def test_follow_of_a_slow_target_has_no_lead_and_no_wait():
    mount = FakeMount(rates_ok=True)
    # A time at which RA 80, Dec 30 is high over Brussels.
    mount.now = high_time(80.0, 30.0)
    command = {
        "type": "follow_target",
        "kind": "samples",
        "name": "C/2026 A1",
        "samples": comet_samples(mount.now),
    }
    mount.command(command)
    follow = mount._follow
    assert follow is not None and not follow.fast and follow.lead_s == 0.0
    assert mount.move_mount_to_target.call_args.args == pytest.approx((80.0, 30.0))
    mount.now += 12.0
    mount.target_reached = True
    mount.phase()
    mount.phase()
    assert follow.stage == FollowStage.TRACK
    ra_rate, dec_rate = mount.set_track_rates.call_args.args
    assert (ra_rate, dec_rate) == pytest.approx((0.1 / 600.0, 0.05 / 600.0))
    assert mount.status_text() == "Following"

    # An arrow moves a slow target by a fixed angle.
    mount.command({"type": "manual_movement", "offset": (0.0, 1.0), "step_size": 0.1})
    point = follow.point(mount.now)
    base = follow.target.point(mount.now)
    assert point.dec == pytest.approx(base.dec)
    assert (point.ra - base.ra) * math.cos(math.radians(base.dec)) == (
        pytest.approx(0.1, abs=1e-3)
    )


def test_slow_target_without_custom_rates_gets_a_goto_after_a_small_motion():
    mount = FakeMount(rates_ok=False)
    mount.now = high_time(80.0, 30.0)
    mount.command(
        {
            "type": "follow_target",
            "kind": "samples",
            "name": "C/2026 A1",
            "samples": comet_samples(mount.now),
        }
    )
    follow = mount._follow
    mount.target_reached = True
    mount.phase()
    mount.phase()
    assert follow.stage == FollowStage.PASS
    gotos = mount.move_mount_to_target.call_count
    mount.now += 30.0
    mount.phase()
    assert mount.move_mount_to_target.call_count == gotos
    # After two minutes the comet is 0.02 degrees away: a new goto.
    mount.now += 120.0
    mount.phase()
    assert mount.move_mount_to_target.call_count == gotos + 1


def test_bad_follow_command_is_refused():
    mount = FakeMount(rates_ok=True)
    mount.command({"type": "follow_target", "kind": "ufo"})
    assert mount._follow is None
    assert mount.console_queue.get_nowait() == ["WARNING", "Bad target data"]


def high_time(ra: float, dec: float) -> float:
    """A unix time at which this position is on the meridian of LOCATION."""
    start = 1_800_000_000.0
    return max(
        (start + 600.0 * step for step in range(144)),
        key=lambda t: target_follow.altitude(ra, dec, t, LOCATION.lat, LOCATION.lon),
    )
