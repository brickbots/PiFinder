"""The closed-loop sky simulator (sky_sim.py) with a fake INDI client."""

import datetime
import json

import numpy as np
import pytest

from PiFinder import calc_utils
from PiFinder.polar_alignment import axis_to_altaz_error
from PiFinder.indi_client import IndiProperty
from PiFinder.sky_sim import SkySimSettings, SkySimulator
from PiFinder.types.positioning import FailedSolve, SuccessfulSolve

pytestmark = pytest.mark.unit

NOW = datetime.datetime(2026, 11, 11, 22, 0, tzinfo=datetime.timezone.utc)
DEVICE = "Telescope Simulator"


class FakeClient:
    def __init__(self):
        self.listeners = []
        self.position = IndiProperty(
            DEVICE, "EQUATORIAL_EOD_COORD", "number", elements={"RA": 2.0, "DEC": 20.0}
        )

    def add_listener(self, callback):
        self.listeners.append(callback)

    def is_connected(self):
        return True

    def connect(self, timeout=5.0):
        return True

    def devices(self):
        return [DEVICE]

    def device_interface(self, device):
        return 5

    def get_property(self, device, name):
        return self.position if name == "EQUATORIAL_EOD_COORD" else None

    def move(self, ra_hours, dec, state="Ok"):
        """The driver reports a new position."""
        self.position = IndiProperty(
            DEVICE,
            "EQUATORIAL_EOD_COORD",
            "number",
            state=state,
            elements={"RA": ra_hours, "DEC": dec},
        )
        for callback in self.listeners:
            callback("set", DEVICE, "EQUATORIAL_EOD_COORD", self.position)


def _sim(**settings):
    values = dict(offset_ra_deg=1.5, offset_dec_deg=-0.8, noise_arcsec=0.0, seed=1)
    values.update(settings)
    clock = [1000.0]
    client = FakeClient()
    sim = SkySimulator(
        SkySimSettings(**values), lambda: NOW, client=client, clock=lambda: clock[0]
    )
    return sim, client, clock


def _jnow(solve):
    return calc_utils.j2000_to_jnow(solve.aligned.RA, solve.aligned.Dec, NOW)


def test_solve_is_mount_position_plus_pointing_error():
    sim, _client, clock = _sim()
    solve = sim.next_message()
    assert isinstance(solve, SuccessfulSolve)
    assert _jnow(solve) == pytest.approx((30.0 + 1.5, 20.0 - 0.8), abs=1e-6)
    assert solve.last_solve_success == 1000.0
    # The next solve comes one period later.
    clock[0] += 0.5
    assert sim.next_message() is None
    clock[0] += 0.5
    assert isinstance(sim.next_message(), SuccessfulSolve)


def test_no_solve_while_the_mount_slews():
    sim, client, _clock = _sim()
    client.move(3.0, 25.0, state="Busy")
    assert isinstance(sim.next_message(), FailedSolve)


def test_a_sync_is_tracked_and_a_slew_is_not():
    sim, client, _clock = _sim()
    client.move(2.0, 20.0)
    # A sync: the reported position jumps while the mount stands still.
    client.move(2.1, 19.2)
    assert (sim.sync_ra, sim.sync_dec) == pytest.approx((1.5, -0.8))
    # The telescope still points where it pointed before the sync.
    assert sim.true_pointing(31.5, 19.2) == pytest.approx((31.5, 19.2))
    # A slew: Busy, then the end position. No sync.
    client.move(2.5, 21.0, state="Busy")
    client.move(3.0, 22.0)
    client.move(3.0, 22.0)
    assert (sim.sync_ra, sim.sync_dec) == pytest.approx((1.5, -0.8))


def test_startup_positions_are_not_a_sync():
    """The driver first reports 0,0 and then the pole, with state Idle."""
    sim, client, _clock = _sim()
    client.move(0.0, 0.0, state="Idle")
    client.move(0.0, 90.0, state="Idle")
    client.move(0.0, 90.0)
    assert (sim.sync_ra, sim.sync_dec) == (0.0, 0.0)


def test_failures_and_scenario_events():
    sim, _client, clock = _sim(
        failure_rate=0.0,
        events=[{"t": 5, "failure_rate": 1.0}, {"t": 10, "offset_ra_deg": 0.0}],
    )
    assert isinstance(sim.next_message(), SuccessfulSolve)
    clock[0] += 5
    assert isinstance(sim.next_message(), FailedSolve)
    clock[0] += 5
    sim.settings.failure_rate = 0.0
    solve = sim.next_message()
    assert _jnow(solve)[0] == pytest.approx(30.0, abs=1e-6)


def test_noise_is_seeded_and_small():
    first, _c, _k = _sim(noise_arcsec=10.0, seed=7)
    second, _c, _k = _sim(noise_arcsec=10.0, seed=7)
    a, b = first.next_message(), second.next_message()
    assert (a.aligned.RA, a.aligned.Dec) == (b.aligned.RA, b.aligned.Dec)
    ra, dec = _jnow(a)
    assert abs(dec - 19.2) < 60 / 3600
    assert abs(ra - 31.5) < 60 / 3600


def test_settings_from_file(tmp_path):
    path = tmp_path / "sim.json"
    path.write_text(json.dumps({"rate_hz": 2.0, "offset_ra_deg": 0.5}))
    settings = SkySimSettings.load(path)
    assert (settings.rate_hz, settings.offset_ra_deg) == (2.0, 0.5)
    assert SkySimSettings.load("default") == SkySimSettings()
    path.write_text(json.dumps({"bogus": 1}))
    with pytest.raises(ValueError):
        SkySimSettings.load(path)


def test_polar_error_turns_the_mount_pole_onto_the_axis():
    """The mount pole (Dec 90) lands on the axis of the mount: an alt/az
    error that axis_to_altaz_error reads back."""
    sim, _client, _clock = _sim(
        offset_ra_deg=0.0,
        offset_dec_deg=0.0,
        polar_error_alt_deg=0.5,
        polar_error_az_deg=-0.3,
        latitude_deg=50.85,
        longitude_deg=4.35,
    )
    ra, dec = sim.true_pointing(10.0, 90.0, NOW)
    axis = np.array(
        [
            np.cos(np.radians(dec)) * np.cos(np.radians(ra)),
            np.cos(np.radians(dec)) * np.sin(np.radians(ra)),
            np.sin(np.radians(dec)),
        ]
    )
    t = calc_utils.sf_utils.ts.from_datetime(NOW)
    lst = (float(t.gast) * 15.0 + 4.35) % 360.0
    d_alt, d_az = axis_to_altaz_error(axis, 50.85, lst)
    assert d_alt == pytest.approx(0.5, abs=1e-3)
    assert d_az == pytest.approx(-0.3, abs=1e-3)


def test_no_polar_error_keeps_the_position():
    sim, _client, _clock = _sim(offset_ra_deg=0.0, offset_dec_deg=0.0)
    assert sim.true_pointing(123.0, 45.0, NOW) == pytest.approx((123.0, 45.0))
    sim, _client, _clock = _sim(polar_error_alt_deg=1.0)
    with pytest.raises(ValueError):
        sim.true_pointing(123.0, 45.0, NOW)


def test_a_continuous_move_is_not_a_sync():
    sim, client, clock = _sim()
    client.move(2.0, 20.0)
    on = IndiProperty(
        DEVICE, "TELESCOPE_MOTION_WE", "switch", elements={"MOTION_EAST": True}
    )
    off = IndiProperty(
        DEVICE, "TELESCOPE_MOTION_WE", "switch", elements={"MOTION_EAST": False}
    )
    for callback in client.listeners:
        callback("set", DEVICE, "TELESCOPE_MOTION_WE", on)
    client.move(2.1, 20.0)
    client.move(2.2, 20.0)
    assert isinstance(sim.next_message(), FailedSolve)
    for callback in client.listeners:
        callback("set", DEVICE, "TELESCOPE_MOTION_WE", off)
    clock[0] += 3.0
    assert sim.sync_ra == 0.0
    solve = sim.next_message()
    assert isinstance(solve, SuccessfulSolve)
    ra, _dec = _jnow(solve)
    assert ra == pytest.approx(2.2 * 15.0 + 1.5, abs=0.01)


def test_attitude_without_polar_error_keeps_the_roll():
    sim, _client, _clock = _sim(offset_ra_deg=0.0, offset_dec_deg=0.0, roll_deg=12.0)
    assert sim.true_attitude(40.0, 20.0, NOW) == pytest.approx((40.0, 20.0, 12.0))


def test_attitude_with_polar_error_matches_the_position():
    sim, _client, _clock = _sim(
        offset_ra_deg=0.0,
        offset_dec_deg=0.0,
        roll_deg=12.0,
        polar_error_alt_deg=1.0,
        polar_error_az_deg=2.0,
        latitude_deg=50.85,
        longitude_deg=4.35,
    )
    ra, dec, roll = sim.true_attitude(40.0, 20.0, NOW)
    assert (ra, dec) == pytest.approx(sim.true_pointing(40.0, 20.0, NOW), abs=1e-6)
    # A tilt of a few degrees turns the roll by a few degrees at most.
    assert roll != pytest.approx(12.0, abs=1e-6)
    assert abs(roll - 12.0) < 5.0
