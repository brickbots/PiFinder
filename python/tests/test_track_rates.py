"""Sidereal, lunar and solar track rates."""

import datetime
from queue import Queue
from unittest.mock import Mock

import pytest

from PiFinder import track_rates
from PiFinder.composite_object import CompositeObject
from PiFinder.mountcontrol_interface import MountControlBase, MountControlPhases
from PiFinder.state import Location, SharedStateObj

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


class RateMount(MountControlBase):
    def __init__(self, supported):
        shared_state = Mock(spec=SharedStateObj)
        shared_state.location.return_value = Location(lat=50.85, lon=4.35, lock=True)
        shared_state.datetime.return_value = DT
        super().__init__(Queue(), Queue(), shared_state)
        self.move_mount_to_target = Mock(return_value=True)
        self.apply_track_rate = Mock(side_effect=lambda rate: rate in supported)
        self.notify = Mock()
        self.state = MountControlPhases.MOUNT_TRACKING

    def command(self, command: dict) -> None:
        for _step in self._process_command(command):
            pass


def test_goto_applies_the_track_rate_of_the_command():
    mount = RateMount({"sidereal", "lunar", "solar"})
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
    mount = RateMount({"sidereal"})
    mount.command({"type": "set_track_rate", "rate": "solar"})
    assert mount.track_rate == "sidereal"
    assert mount.console_queue.get_nowait() == ["WARNING", "No such track rate"]
    mount = RateMount({"sidereal", "solar"})
    mount.command({"type": "set_track_rate", "rate": "solar"})
    assert mount.track_rate == "solar"
