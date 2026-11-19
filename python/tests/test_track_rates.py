"""Sidereal, lunar and solar track rates."""

import datetime

import pytest

from PiFinder import track_rates
from PiFinder.calc_utils import FastAltAz
from PiFinder.composite_object import CompositeObject
from PiFinder.mountcontrol_interface import MountControlPhases
from mount_fake import LOCATION, FakeMount

pytestmark = pytest.mark.unit

DT = datetime.datetime(2026, 11, 12, 22, 0, tzinfo=datetime.timezone.utc)


def planet(name: str) -> CompositeObject:
    return CompositeObject(catalog_code="PL", names=[name], obj_type="Pla")


def test_auto_rate_picks_lunar_for_the_moon_only():
    assert track_rates.rate_for_object("auto", planet("Moon")) == "lunar"
    assert track_rates.rate_for_object("auto", planet("Sun")) == "solar"
    assert track_rates.rate_for_object("auto", planet("Jupiter")) == "sidereal"
    ngc = CompositeObject(catalog_code="NGC", names=["Moon"])
    assert track_rates.rate_for_object("auto", ngc) == "sidereal"
    assert track_rates.rate_for_object("solar", planet("Moon")) == "solar"


def test_body_rates_match_the_motion_of_moon_and_sun():
    moon_ra, moon_dec = track_rates.body_rates("lunar", 50.85, 4.35, 50.0, DT)
    # The Moon moves east 12 to 15 degrees a day relative to the stars.
    assert 10 / 86400 < moon_ra < 18 / 86400
    assert abs(moon_dec) < 6 / 86400
    sun_ra, sun_dec = track_rates.body_rates("solar", 50.85, 4.35, 50.0, DT)
    # The Sun moves about one degree a day.
    assert 0.8 / 86400 < sun_ra < 1.2 / 86400
    assert abs(sun_dec) < 0.5 / 86400
    assert track_rates.body_rates("sidereal", 50.85, 4.35, 50.0, DT) is None


def test_goto_applies_the_track_rate_of_the_command():
    mount = FakeMount(dt=DT)
    mount.command(
        {"type": "goto_target", "ra": 10.0, "dec": 5.0, "track_rate": "lunar"}
    )
    mount.apply_track_rate.assert_called_with("lunar")
    assert mount.track_rate == "lunar"
    mount.state = MountControlPhases.MOUNT_TRACKING
    assert mount.status_text() == "Tracking Lunar"
    mount.command({"type": "goto_target", "ra": 20.0, "dec": 5.0})
    assert mount.track_rate == "sidereal"
    mount.state = MountControlPhases.MOUNT_TRACKING
    assert mount.status_text() == "Tracking"


def test_set_track_rate_falls_back_to_sidereal():
    mount = FakeMount(supported={"sidereal"}, dt=DT)
    mount.command({"type": "set_track_rate", "rate": "solar"})
    assert mount.track_rate == "sidereal"
    assert mount.console_queue.get_nowait() == ["WARNING", "No such track rate"]
    mount = FakeMount(supported={"sidereal", "solar"}, dt=DT)
    mount.command({"type": "set_track_rate", "rate": "solar"})
    assert mount.track_rate == "solar"


def test_follow_sets_the_sidereal_rate_on_the_mount():
    """A mount in the lunar track mode without custom rates follows with
    gotos. The follow puts the mount back to the sidereal rate."""
    mount = FakeMount(rates_ok=False, dt=DT)
    mount.command({"type": "set_track_rate", "rate": "lunar"})
    assert mount.track_rate == "lunar"
    # A slow comet on the meridian, 50 degrees north.
    mount.now = DT.timestamp()
    ra = FastAltAz(LOCATION.lat, LOCATION.lon, DT).local_siderial_time
    samples = [(mount.now, ra, 50.0), (mount.now + 3600.0, ra + 1.0, 50.0)]
    mount.command(
        {"type": "follow_target", "kind": "samples", "name": "C", "samples": samples}
    )
    assert mount._follow is not None
    mount.apply_track_rate.assert_called_with("sidereal")
    assert mount.track_rate == "sidereal"
