"""The follow_target command of a catalog object that moves."""

import datetime
from types import SimpleNamespace

import pytest

from PiFinder import follow_command
from PiFinder.composite_object import CompositeObject

pytestmark = pytest.mark.unit

DT = datetime.datetime(2026, 11, 12, 22, 0, tzinfo=datetime.timezone.utc)


def comet() -> CompositeObject:
    return CompositeObject(
        catalog_code="CM", sequence=3, names=["C/2026 A1"], ra=80.0, dec=30.0
    )


def test_satellite_command_has_the_elements(monkeypatch):
    elements = SimpleNamespace(norad_id=25544, name="ISS", line1="1 ...", line2="2 ...")
    catalog = SimpleNamespace(
        tracked=lambda sequence: SimpleNamespace(elements=elements)
    )
    monkeypatch.setattr(
        follow_command.satellite_catalog, "is_satellite", lambda obj: True
    )
    monkeypatch.setattr(
        follow_command.satellite_catalog, "active_catalog", lambda: catalog
    )
    command = follow_command.follow_command(comet(), None)
    assert command == {
        "type": "follow_target",
        "kind": "satellite",
        "norad_id": 25544,
        "name": "ISS",
        "line1": "1 ...",
        "line2": "2 ...",
    }


def test_fast_comet_gets_samples_in_jnow(monkeypatch):
    def track(name, datetimes):
        assert name == "C/2026 A1"
        return [(80.0 + 0.05 * i, 30.0) for i in range(len(datetimes))]

    monkeypatch.setattr(follow_command.comets, "comet_track", track)
    command = follow_command.follow_command(comet(), DT)
    assert command["kind"] == "samples" and command["name"] == "C/2026 A1"
    samples = command["samples"]
    assert len(samples) == follow_command.SAMPLE_COUNT
    assert samples[0][0] == DT.timestamp()
    assert samples[1][0] - samples[0][0] == 1800.0
    # JNow is some tenths of a degree from J2000 in 2026.
    assert 0.1 < abs(samples[0][1] - 80.0) < 1.0
    assert samples[1][1] - samples[0][1] == pytest.approx(0.05, abs=1e-3)


def test_slow_asteroid_gets_a_normal_goto(monkeypatch):
    def track(number, datetimes):
        assert number == 4
        return [(80.0 + 0.001 * i, 30.0) for i in range(len(datetimes))]

    monkeypatch.setattr(follow_command.asteroids, "asteroid_track", track)
    vesta = CompositeObject(catalog_code="MP", sequence=4, names=["Vesta"])
    assert follow_command.follow_command(vesta, DT) is None


def test_object_without_motion_or_data_gets_a_normal_goto(monkeypatch):
    ngc = CompositeObject(catalog_code="NGC", sequence=7000, names=["NGC 7000"])
    assert follow_command.follow_command(ngc, DT) is None
    monkeypatch.setattr(follow_command.comets, "comet_track", lambda name, dts: [])
    assert follow_command.follow_command(comet(), DT) is None
    assert follow_command.follow_command(comet(), None) is None
