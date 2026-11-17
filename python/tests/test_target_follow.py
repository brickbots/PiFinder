"""Follow of a moving target: the plan and the mount control phase, with a
fake mount."""

import datetime
import math
import time
from functools import lru_cache
from pathlib import Path
from typing import Optional
from unittest.mock import Mock

import pytest
from skyfield.api import wgs84

import PiFinder.satellites as satellites
from PiFinder import target_follow
from PiFinder.calc_utils import FastAltAz
from PiFinder.mountcontrol_interface import (
    MountControlBase,
    MountControlPhases,
    meet_text,
    next_pass_text,
)
from PiFinder.target_follow import (
    BodyTarget,
    FollowStage,
    SampledTarget,
    SatelliteTarget,
    TargetFollow,
    angular_distance,
)
from mount_fake import LOCATION, FakeMount

pytestmark = pytest.mark.unit

DATA = Path(__file__).parent / "data" / "satellites"


@lru_cache(maxsize=None)
def iss_elements() -> satellites.SatElements:
    return satellites.parse_elements((DATA / "25544.3le").read_text())[0][0]


@lru_cache(maxsize=None)
def iss_pass() -> satellites.SatPass:
    """A high pass of the ISS over Brussels after the fixture epoch."""
    element = iss_elements()
    sat = satellites.TrackedSatellite.from_elements(element)
    topos = wgs84.latlon(LOCATION.lat, LOCATION.lon, LOCATION.altitude)
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


@pytest.fixture(autouse=True)
def corrected_directory(tmp_path, monkeypatch):
    """Corrected element sets go to a temporary directory."""
    monkeypatch.setattr(MountControlBase, "corrected_directory", tmp_path)


def start_follow(
    now: float, rates_ok: bool = True, command: Optional[dict] = None
) -> FakeMount:
    """A mount that starts a follow at ``now``, of the ISS by default."""
    mount = FakeMount(rates_ok=rates_ok)
    mount.now = now
    mount.command(follow_command() if command is None else command)
    return mount


def samples_command(name: str, samples: list) -> dict:
    return {
        "type": "follow_target",
        "kind": "samples",
        "name": name,
        "samples": samples,
    }


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
    mount = start_follow(iss_pass().culmination.timestamp() - 90.0)
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


def count_points(follow: TargetFollow) -> list:
    """Count the computed points of the target of ``follow``."""
    calls: list = []
    target = follow.target
    real = target.point

    def point(unix_time: float):
        calls.append(unix_time)
        return real(unix_time)

    target.point = point
    return calls


def test_follow_computes_one_point_a_second_in_wait_and_track(monkeypatch):
    mount = start_follow(iss_pass().culmination.timestamp() - 90.0)
    follow = mount._follow
    mount.now += 8.0
    mount.target_reached = True
    mount.phase()
    assert follow.stage == FollowStage.WAIT
    # WAIT: only the altitude check, once a second.
    calls = count_points(follow)
    for _step in range(20):
        mount.now += 0.1
        mount.phase()
    assert 1 <= len(calls) <= 2

    # TRACK: one point a second, at the time of the position report.
    mount.now = follow.aim_time + 0.1
    point = follow.point(mount.now)
    mount.current_ra, mount.current_dec = point.ra, point.dec
    mount.phase()
    assert follow.stage == FollowStage.TRACK
    reported = time.time()
    monkeypatch.setattr(time, "time", lambda: reported + 0.4)
    mount.current_time = reported
    calls.clear()
    for _step in range(10):
        mount.now += 0.11
        mount.phase()
    assert calls == [pytest.approx(mount.now - 0.4)]
    assert follow.stage == FollowStage.TRACK
    # The status target is that point, moved on to now.
    now_point = follow.point(mount.now)
    assert (
        angular_distance(mount.target_ra, mount.target_dec, now_point.ra, now_point.dec)
        < 0.01
    )


def test_follow_without_custom_rates_repeats_gotos_ahead():
    mount = start_follow(iss_pass().culmination.timestamp() - 120.0, rates_ok=False)
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
    mount = start_follow(pass_.culmination.timestamp())
    mount.now = pass_.set.timestamp() + 60.0
    mount.phase()
    assert mount._follow is None
    mount.stop_mount.assert_called()
    mount.restore_sidereal_tracking.assert_called()

    mount = start_follow(pass_.culmination.timestamp())
    mount.shared_state.datetime.return_value = None
    mount.command({"type": "set_step_size", "step_size": 0.5})
    assert mount._follow is not None
    mount.command({"type": "stop_movement"})
    assert mount._follow is None


def test_follow_without_a_meet_in_the_wait_tells_the_next_pass():
    mount = start_follow(iss_pass().set.timestamp() + 300.0)
    assert mount._follow is None
    mount.move_mount_to_target.assert_not_called()
    kind, text = mount.console_queue.get_nowait()
    item = target_follow.find_pass(iss_target(), mount.now, 24 * 60.0)
    assert item is not None
    wait = target_follow.meet_time(item) - mount.now
    assert wait > target_follow.MEET_SEARCH_MINUTES * 60.0
    assert kind == "WARNING"
    assert text == next_pass_text(item, mount.now, "UTC")
    lines = text.split("\n")
    assert len(lines) == 3 and all(len(line) <= 16 for line in lines)
    assert lines[0].startswith("Next pass ")
    assert lines[1].startswith("in ")
    assert lines[2].startswith("max ")


def test_follow_refuses_a_comet_below_the_horizon():
    now = 1_800_000_000.0
    samples = [(now, 0.0, -80.0), (now + 3600.0, 0.1, -80.0)]
    mount = start_follow(now, command=samples_command("Low", samples))
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
    assert follow.time_offset_s or follow.cross_deg

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


def start_tracking(now: float) -> FakeMount:
    """A mount that tracks the ISS from ``now``, on the target."""
    mount = start_follow(now)
    follow = mount._follow
    mount.now += 8.0
    mount.target_reached = True
    mount.phase()
    mount.now = follow.aim_time + 0.1
    point = follow.point(mount.now)
    mount.current_ra, mount.current_dec = point.ra, point.dec
    mount.phase()
    assert follow.stage == FollowStage.TRACK
    return mount


def count_shifts(monkeypatch) -> list:
    """Count the new targets of a time offset."""
    calls: list = []
    real = SatelliteTarget.shifted

    def shifted(self, seconds):
        calls.append(seconds)
        return real(self, seconds)

    monkeypatch.setattr(SatelliteTarget, "shifted", shifted)
    return calls


def test_a_press_changes_the_track_rates_in_the_same_loop_pass():
    mount = start_tracking(iss_pass().culmination.timestamp() - 90.0)
    follow = mount._follow
    mount.now += 0.2
    point = follow.point(mount.now)
    mount.current_ra, mount.current_dec = point.ra, point.dec
    calls = mount.set_track_rates.call_count
    # A press 0.05 degrees north, then the phase of the same loop pass.
    mount.command({"type": "manual_movement", "offset": (1.0, 0.0), "step_size": 0.05})
    mount.phase()
    assert mount.set_track_rates.call_count == calls + 1
    _ra_rate, dec_rate = mount.set_track_rates.call_args.args
    assert dec_rate - point.dec_rate == pytest.approx(
        0.05 / target_follow.CORRECTION_S, abs=2e-3
    )


def test_held_arrow_makes_new_elements_once_a_second(monkeypatch):
    mount = start_tracking(iss_pass().culmination.timestamp() - 90.0)
    follow = mount._follow
    shifts = count_shifts(monkeypatch)
    mount.step_size = 0.5
    point = follow.point(mount.now)
    cos_dec = math.cos(math.radians(point.dec))
    along = (point.dec_rate / point.speed, point.ra_rate * cos_dec / point.speed)
    mount.command({"type": "motion_start", "north": along[0], "east": along[1]})
    mount.now += 0.1
    mount.phase()
    # The status shows the correction at once.
    assert mount.status_text().startswith("Following +")
    first = mount.status_text()
    for _step in range(19):
        mount.now += 0.1
        mount.phase()
    assert mount.status_text() != first
    assert len(shifts) <= 2
    held = follow.time_offset_s
    mount.command({"type": "motion_stop"})
    # The release makes the elements of the full correction.
    assert shifts[-1] == pytest.approx(held)
    assert len(shifts) <= 3
    ahead = iss_target().point(mount.now + held)
    corrected = follow.point(mount.now)
    assert angular_distance(corrected.ra, corrected.dec, ahead.ra, ahead.dec) < 0.15


def test_a_corrected_follow_stores_its_elements(tmp_path):
    mount = start_follow(iss_pass().culmination.timestamp() - 60.0)
    follow = mount._follow
    follow.nudge(0.0, 0.0, mount.now)
    mount.command({"type": "stop_movement"})
    assert satellites.load_corrected_elements(tmp_path) == []

    mount.command(follow_command())
    mount._follow.nudge(0.5, 0.5, mount.now)
    assert mount._follow.corrected_elements() is not None
    mount.command({"type": "stop_movement"})
    stored = satellites.load_corrected_elements(tmp_path)
    assert len(stored) == 1
    assert stored[0].norad_id == iss_elements().norad_id
    assert stored[0].line2 != iss_elements().line2
    when = datetime.datetime.fromtimestamp(mount.now, datetime.timezone.utc)
    assert stored[0].name == satellites.corrected_name(iss_elements().name, when)
    notes = [call.args[0] for call in mount.notify.call_args_list]
    assert any(note.startswith("Saved") for note in notes), notes


def test_plate_solve_before_the_pass_gives_a_pointing_offset(monkeypatch):
    mount = start_follow(iss_pass().culmination.timestamp() - 90.0)
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


def start_comet_follow(rates_ok: bool) -> FakeMount:
    """The follow of a slow comet high over LOCATION."""
    now = high_time(80.0, 30.0)
    command = samples_command("C/2026 A1", comet_samples(now))
    return start_follow(now, rates_ok=rates_ok, command=command)


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


def test_body_target_gives_the_motion_of_the_moon():
    now = datetime.datetime(2026, 11, 12, 22, tzinfo=datetime.timezone.utc)
    point = BodyTarget("moon", 50.85, 4.35, 50.0).point(now.timestamp())
    assert 10 / 86400 < point.ra_rate < 18 / 86400
    with pytest.raises(ValueError):
        BodyTarget("vulcan", 50.85, 4.35, 50.0)


def test_follow_of_a_slow_target_has_no_lead_and_no_wait():
    # A time at which RA 80, Dec 30 is high over Brussels.
    mount = start_comet_follow(rates_ok=True)
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
    mount = start_comet_follow(rates_ok=False)
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


SIDEREAL_DEG_S = target_follow.SIDEREAL_DEG_PER_DAY / 86400.0


def geostationary_samples(start: float) -> list:
    """A target fixed in alt-az: the RA grows at the sidereal rate."""
    return [
        (start + 600.0 * i, 80.0 + SIDEREAL_DEG_S * 600.0 * i, 5.0) for i in range(4)
    ]


def test_ground_fixed_finds_a_geostationary_target():
    geo = target_follow.FollowPoint(80.0, 5.0, SIDEREAL_DEG_S, 0.0, 30.0)
    assert target_follow.ground_fixed(geo)
    drifting = target_follow.FollowPoint(80.0, 5.0, SIDEREAL_DEG_S, 0.001, 30.0)
    assert not target_follow.ground_fixed(drifting)
    star = target_follow.FollowPoint(80.0, 5.0, 0.0, 0.0, 30.0)
    assert not target_follow.ground_fixed(star)


def test_geostationary_follow_without_custom_rates_turns_tracking_off():
    now = high_time(80.0, 5.0)
    command = samples_command("ASTRA 1KR", geostationary_samples(now))
    mount = start_follow(now, rates_ok=False, command=command)
    mount.set_tracking = Mock(return_value=True)
    follow = mount._follow
    mount.target_reached = True
    mount.phase()
    mount.phase()
    assert follow.stage == FollowStage.PASS
    mount.set_tracking.assert_called_once_with(False)
    # With tracking off the mount stays on the target: no new goto.
    start = follow.point(mount.now)
    mount.current_ra, mount.current_dec = start.ra, start.dec
    gotos = mount.move_mount_to_target.call_count
    for _step in range(10):
        mount.now += 30.0
        mount.current_ra = (mount.current_ra + SIDEREAL_DEG_S * 30.0) % 360.0
        mount.phase()
    assert mount.move_mount_to_target.call_count == gotos
    mount.command({"type": "stop_movement"})
    assert mount.set_tracking.call_args_list[-1].args == (True,)


def test_comet_follow_without_custom_rates_keeps_tracking():
    mount = start_comet_follow(rates_ok=False)
    mount.set_tracking = Mock(return_value=True)
    mount.target_reached = True
    mount.phase()
    mount.phase()
    mount.set_tracking.assert_not_called()


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
        key=lambda t: FastAltAz(LOCATION.lat, LOCATION.lon, utc(t)).radec_to_altaz(
            ra, dec, alt_only=True
        )[0],
    )


# -- meet point -------------------------------------------------------------


def utc(unix_time: float) -> datetime.datetime:
    return datetime.datetime.fromtimestamp(unix_time, datetime.timezone.utc)


def fake_pass(rise: float, visible_start=None) -> satellites.SatPass:
    return satellites.SatPass(
        rise=utc(rise),
        culmination=utc(rise + 120.0),
        set=utc(rise + 240.0),
        rise_az=270.0,
        max_alt=60.0,
        max_alt_az=0.0,
        set_az=90.0,
        visible_start=None if visible_start is None else utc(visible_start),
        visible_end=None if visible_start is None else utc(rise + 200.0),
    )


def meet_start() -> float:
    """Ten minutes before the culmination of the high pass: the ISS is
    below the horizon."""
    return iss_pass().culmination.timestamp() - 600.0


def test_meet_is_the_first_visible_time_of_the_pass(monkeypatch):
    now = meet_start()
    calls = []

    def passes(sat, topos, start, hours, min_alt):
        calls.append((start, hours, min_alt))
        return [fake_pass(now + 300.0, visible_start=now + 360.0)]

    monkeypatch.setattr(satellites, "find_passes", passes)
    meet = find_meet(now)
    assert meet is not None and meet.time == pytest.approx(now + 360.0)
    assert calls == [
        (
            utc(now),
            target_follow.MEET_SEARCH_MINUTES / 60.0,
            target_follow.MEET_ALT_DEG,
        )
    ]
    alt, az = iss_target().alt_az(now + 360.0)
    assert (meet.alt, meet.az) == pytest.approx((alt, az))


def test_meet_without_a_visible_part_is_at_the_meet_altitude(monkeypatch):
    now = meet_start()
    monkeypatch.setattr(
        satellites, "find_passes", lambda *args, **kwargs: [fake_pass(now + 300.0)]
    )
    meet = find_meet(now)
    assert meet is not None and meet.time == pytest.approx(now + 300.0)


def test_no_meet_without_a_pass_or_with_a_pass_now(monkeypatch):
    now = meet_start()
    monkeypatch.setattr(satellites, "find_passes", lambda *args, **kwargs: [])
    assert find_meet(now) is None
    monkeypatch.setattr(
        satellites, "find_passes", lambda *args, **kwargs: [fake_pass(now)]
    )
    assert find_meet(now) is None


def test_meet_of_the_fixture_passes():
    # A pass in the Earth shadow: the meet is where the ISS reaches 20°.
    meet = find_meet(meet_start())
    assert meet is not None
    assert meet.alt == pytest.approx(target_follow.MEET_ALT_DEG, abs=0.2)
    assert meet.time == pytest.approx(
        iss_pass().culmination.timestamp() - 133.0, abs=5.0
    )
    # A visible pass in the evening twilight.
    element = iss_elements()
    sat = satellites.TrackedSatellite.from_elements(element)
    topos = wgs84.latlon(LOCATION.lat, LOCATION.lon, LOCATION.altitude)
    visible = [
        item
        for item in satellites.find_passes(
            sat, topos, element.epoch, hours=96, min_alt=target_follow.MEET_ALT_DEG
        )
        if item.visible
    ][0]
    start = visible.rise.timestamp() - 600.0
    meet = find_meet(start)
    assert meet is not None
    assert meet.time == pytest.approx(visible.visible_start.timestamp(), abs=1.0)
    assert meet.alt >= target_follow.MEET_ALT_DEG - 0.2


def find_meet(now: float) -> Optional[target_follow.MeetPoint]:
    """The meet point of the ISS in the default wait from ``now``."""
    target = iss_target()
    item = target_follow.find_pass(target, now, target_follow.MEET_SEARCH_MINUTES)
    return None if item is None else target_follow.meet_point(target, item)


def test_follow_below_the_horizon_slews_to_the_meet_point():
    mount = start_follow(meet_start())
    follow = mount._follow
    assert follow is not None and follow.meet is not None
    meet_time = follow.meet.time
    assert meet_time - mount.now == pytest.approx(467.0, abs=5.0)
    aim_ra, aim_dec = mount.move_mount_to_target.call_args.args
    expected = follow.point(meet_time)
    assert (aim_ra, aim_dec) == pytest.approx((expected.ra, expected.dec))
    assert follow.aim_time == meet_time
    assert mount.status_text() == "Follow: slewing"

    # The slew ends. The mount waits with the sidereal tracking.
    mount.now += 30.0
    mount.target_reached = True
    mount.current_ra, mount.current_dec = aim_ra, aim_dec
    mount.phase()
    assert follow.stage == FollowStage.WAIT
    seconds = math.ceil(meet_time - mount.now)
    minutes, rest = divmod(seconds, 60)
    compass = satellites.compass(follow.meet.az)
    assert mount.status_text() == f"Meet in {minutes}:{rest:02d} 20° {compass}"
    mount.set_track_rates.assert_not_called()

    # The ISS is below the horizon during the wait: the follow stays.
    for _step in range(15):
        mount.now += 20.0
        mount.phase()
        assert mount._follow is follow
    assert mount.move_mount_to_target.call_count == 1
    assert mount.status_text().startswith("Meet in 2:")


def test_meet_text_format():
    meet = target_follow.MeetPoint(0.0, 20.4, 135.0)
    assert meet_text(133.0, meet) == "Meet in 2:13 20° SE"
    assert meet_text(0.4, meet) == "Meet in 0:01 20° SE"


def wait_at_meet(mount: FakeMount) -> TargetFollow:
    follow = mount._follow
    mount.now += 30.0
    mount.target_reached = True
    mount.current_ra, mount.current_dec = mount.move_mount_to_target.call_args.args
    mount.phase()
    assert follow.stage == FollowStage.WAIT
    return follow


def test_without_input_the_follow_tracks_at_the_meet_time():
    mount = start_follow(meet_start())
    follow = wait_at_meet(mount)
    mount.now = follow.meet.time + 0.1
    mount.phase()
    assert follow.stage == FollowStage.TRACK
    point = follow.point(mount.now)
    assert mount.set_track_rates.call_args.args == pytest.approx(
        (point.ra_rate, point.dec_rate)
    )
    assert point.alt == pytest.approx(target_follow.MEET_ALT_DEG, abs=0.5)
    assert mount.status_text() == "Following"


def test_without_custom_rates_the_follow_passes_at_the_meet_time():
    mount = start_follow(meet_start(), rates_ok=False)
    follow = wait_at_meet(mount)
    mount.now = follow.meet.time + 0.1
    mount.phase()
    assert follow.stage == FollowStage.PASS
    mount.now += 10.0
    mount.phase()
    assert follow.stage == FollowStage.AIM
    assert follow.aim_time == pytest.approx(mount.now + follow.lead_s)


def test_click_before_the_meet_time_says_i_see_it():
    mount = start_follow(meet_start())
    follow = wait_at_meet(mount)
    meet_time = follow.meet.time
    aim_ra, aim_dec = follow.aim_ra, follow.aim_dec
    mount.now = meet_time - 40.0
    mount.command({"type": "manual_movement", "offset": (0.0, 1.0), "step_size": 0.5})
    # The offset is the 40 s, and a small part for the Earth rotation.
    assert follow.time_offset_s == pytest.approx(40.0, abs=3.0)
    assert follow.meet is None and not follow.meet_pending(mount.now)
    # The satellite is at the meet point now, and the mount tracks at once.
    point = follow.point(mount.now)
    assert angular_distance(point.ra, point.dec, aim_ra, aim_dec) < 0.005
    assert follow.stage == FollowStage.TRACK
    assert mount.set_track_rates.call_args.args == pytest.approx(
        (point.ra_rate, point.dec_rate)
    )
    notes = [call.args[0] for call in mount.notify.call_args_list]
    assert "Seen" in notes
    assert mount.status_text() == f"Following {follow.time_offset_s:+.1f}s"

    # The next arrow corrects the path as before.
    offset = follow.time_offset_s
    mount.now += 1.0
    mount.command({"type": "manual_movement", "offset": (1.0, 0.0), "step_size": 0.2})
    assert follow.time_offset_s != pytest.approx(offset)
    assert follow.stage == FollowStage.TRACK


def test_held_arrow_at_the_meet_point_also_says_i_see_it():
    mount = start_follow(meet_start())
    follow = wait_at_meet(mount)
    mount.now = follow.meet.time - 10.0
    mount.command({"type": "motion_start", "north": 1.0, "east": 0.0})
    offset = follow.time_offset_s
    assert offset == pytest.approx(10.0, abs=1.0)
    assert mount._follow_motion is None
    assert follow.stage == FollowStage.TRACK
    mount.now += 1.0
    mount.phase()
    mount.command({"type": "motion_stop"})
    assert follow.time_offset_s == offset


def test_click_long_before_the_meet_time_is_refused():
    mount = start_follow(meet_start())
    follow = wait_at_meet(mount)
    mount.now = follow.meet.time - target_follow.MAX_TIME_OFFSET_S - 10.0
    mount.command({"type": "manual_movement", "offset": (0.0, 1.0), "step_size": 0.5})
    assert mount.console_queue.get_nowait() == ["WARNING", "Too early"]
    assert follow.time_offset_s == 0.0
    assert follow.stage == FollowStage.WAIT and follow.meet is not None
    # A click inside the limit works.
    mount.now = follow.meet.time - target_follow.MAX_TIME_OFFSET_S + 1.0
    mount.command({"type": "manual_movement", "offset": (0.0, 1.0), "step_size": 0.5})
    assert 100.0 < follow.time_offset_s <= target_follow.MAX_TIME_OFFSET_S
    assert follow.stage == FollowStage.TRACK


def test_click_after_the_meet_time_corrects_the_path():
    mount = start_follow(meet_start())
    follow = wait_at_meet(mount)
    mount.now = follow.meet.time + 0.1
    mount.phase()
    assert follow.stage == FollowStage.TRACK
    mount.now += 1.0
    point = follow.point(mount.now)
    cos_dec = math.cos(math.radians(point.dec))
    # 3 s of motion along the track.
    north, east = 3.0 * point.dec_rate, 3.0 * point.ra_rate * cos_dec
    mount.command({"type": "manual_movement", "offset": (north, east), "step_size": 1})
    assert follow.time_offset_s == pytest.approx(3.0, abs=0.05)
    notes = [call.args[0] for call in mount.notify.call_args_list]
    assert "Seen" not in notes


def test_click_at_the_meet_point_stores_corrected_elements(tmp_path):
    mount = start_follow(meet_start())
    follow = wait_at_meet(mount)
    meet_time = follow.meet.time
    aim_ra, aim_dec = follow.aim_ra, follow.aim_dec
    mount.now = meet_time - 25.0
    mount.command({"type": "manual_movement", "offset": (0.0, 1.0), "step_size": 0.5})
    mount.command({"type": "stop_movement"})
    stored = satellites.load_corrected_elements(tmp_path)
    assert len(stored) == 1
    # The stored elements have the time offset of the click.
    offset = follow.time_offset_s
    assert offset == pytest.approx(25.0, abs=2.0)
    shifted = target_follow.shift_elements(iss_elements(), offset)
    assert stored[0].line2 == shifted.line2
    # They put the ISS near the meet point at the click. The rest is the
    # correction across the track, which is not in the elements.
    corrected = SatelliteTarget(stored[0], LOCATION.lat, LOCATION.lon, 50.0)
    point = corrected.point(meet_time - 25.0)
    assert angular_distance(point.ra, point.dec, aim_ra, aim_dec) < 0.3


def test_new_pointing_offset_gives_a_goto_before_the_meet_time():
    mount = start_follow(meet_start())
    follow = wait_at_meet(mount)
    meet_time = follow.meet.time
    # No new offset: no goto before the meet time.
    mount.now = meet_time - target_follow.MEET_REFRESH_S + 1.0
    mount.phase()
    assert mount.move_mount_to_target.call_count == 1

    mount = start_follow(meet_start())
    follow = wait_at_meet(mount)
    aim_ra, aim_dec = mount.move_mount_to_target.call_args.args
    # A plate solve during the wait found an offset of 0.3° in Dec.
    mount._follow_offset = (0.0, 0.3)
    mount.now = meet_time - 60.0
    mount.phase()
    assert mount.move_mount_to_target.call_count == 1
    mount.now = meet_time - target_follow.MEET_REFRESH_S + 1.0
    mount.phase()
    assert mount.move_mount_to_target.call_count == 2
    goto_ra, goto_dec = mount.move_mount_to_target.call_args.args
    assert (goto_ra, goto_dec) == pytest.approx((aim_ra, aim_dec - 0.3))
    assert follow.aim_time == meet_time
    # The short slew ends: the wait goes on, with no other goto.
    mount.now += 3.0
    mount.target_reached = True
    mount.phase()
    assert follow.stage == FollowStage.WAIT
    mount.now += 1.0
    mount.phase()
    assert mount.move_mount_to_target.call_count == 2
    assert mount.status_text().startswith("Meet in 0:")


def test_satellite_past_its_meet_point_follows_at_once():
    # High in the sky: as before, a goto ahead by the lead.
    mount = start_follow(iss_pass().culmination.timestamp() - 120.0)
    follow = mount._follow
    assert follow.meet is None
    assert follow.aim_time == mount.now + target_follow.DEFAULT_LEAD_S
    # Low and going down after the pass: no meet point, a follow at once.
    mount = FakeMount(rates_ok=True)
    mount.now = iss_pass().culmination.timestamp() + 160.0
    alt = iss_target().point(mount.now).alt
    assert target_follow.MIN_ALT_DEG < alt < target_follow.MEET_ALT_DEG
    mount.command(follow_command())
    follow = mount._follow
    assert follow is not None and follow.meet is None
    assert follow.aim_time == mount.now + target_follow.DEFAULT_LEAD_S


def test_next_pass_text_in_the_local_time():
    rise = datetime.datetime(2026, 11, 14, 20, 43, tzinfo=datetime.timezone.utc)
    now = rise.timestamp() - (2 * 3600 + 5 * 60)
    item = fake_pass(rise.timestamp())
    item.max_alt, item.max_alt_az = 38.4, 135.0
    text = next_pass_text(item, now, "Europe/Brussels")
    assert text == "Next pass 21:43\nin 2h05\nmax 38° SE"
    # The meet time of a pass with a visible part is its visible start.
    item = fake_pass(rise.timestamp(), visible_start=rise.timestamp() + 120.0)
    text = next_pass_text(item, now, "UTC")
    assert text.split("\n")[:2] == ["Next pass 20:45", "in 2h07"]
    # Less than an hour.
    text = next_pass_text(item, rise.timestamp() - 45 * 60.0, "No/Zone")
    assert text.split("\n")[:2] == ["Next pass 20:45", "in 47 min"]
    assert next_pass_text(None, now, "UTC") == "No pass in 24 h"


def test_no_pass_in_24_hours(monkeypatch):
    start = meet_start()
    calls = []

    def passes(sat, topos, start, hours, min_alt):
        calls.append(hours)
        return []

    monkeypatch.setattr(satellites, "find_passes", passes)
    mount = start_follow(start)
    assert mount._follow is None
    mount.move_mount_to_target.assert_not_called()
    assert mount.console_queue.get_nowait() == ["WARNING", "No pass in 24 h"]
    assert calls == [target_follow.NEXT_PASS_HOURS]


def test_max_wait_setting_decides_on_the_meet(monkeypatch):
    start = meet_start()
    monkeypatch.setattr(
        satellites,
        "find_passes",
        lambda *args, **kwargs: [fake_pass(start + 20 * 60.0)],
    )
    # 15 min: the pass in 20 min is too late. The PiFinder tells it.
    mount = FakeMount(rates_ok=True)
    mount.max_wait_min = 15.0
    mount.now = start
    mount.command(follow_command())
    assert mount._follow is None
    mount.move_mount_to_target.assert_not_called()
    kind, text = mount.console_queue.get_nowait()
    assert kind == "WARNING"
    assert text.split("\n")[1] == "in 20 min"
    # 30 min, the default: the mount waits at the meet point.
    mount = FakeMount(rates_ok=True)
    assert mount.max_wait_min == target_follow.MEET_SEARCH_MINUTES
    mount.now = start
    mount.command(follow_command())
    assert mount._follow is not None
    assert mount._follow.meet.time == pytest.approx(start + 20 * 60.0)
    mount.move_mount_to_target.assert_called_once()
