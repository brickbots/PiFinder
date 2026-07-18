"""Regression tests for the civil-datetime contract on SharedStateObj.

These lock in the behaviour decided in ADR-0018: the civil datetime is stored
timezone-aware in UTC, normalised at the set_datetime() boundary, and read back
through utc_datetime() (UTC) / local_datetime() (the location's zone). The
status-screen bug they guard against ("UTC TM" equal to "LCL TM" at a non-UTC
location) is exactly the kind that only shows up on a non-UTC box.
"""

import datetime

import pytest
import pytz

import PiFinder.state as state_mod
from PiFinder.state import Location, SharedStateObj

UTC = datetime.timezone.utc

# A real place whose zone is unambiguous and offset from UTC in June (CEST,
# +02:00). set_location() derives the zone from lat/lon, so we pick coordinates
# rather than naming the zone directly.
BRUSSELS_LAT, BRUSSELS_LON = 50.85, 4.35


@pytest.fixture
def frozen_clock(monkeypatch):
    """Freeze the wall clock state.datetime() uses for drift.

    datetime() returns __datetime + (time.time() - __datetime_time); pinning
    time.time() makes that drift exactly zero so stored == read-back and the
    assertions below are deterministic instead of off by the test's runtime.
    """
    monkeypatch.setattr(state_mod.time, "time", lambda: 1_700_000_000.0)


def _state_at(lat=0.0, lon=0.0):
    """A SharedStateObj whose location resolves to the zone at (lat, lon)."""
    shared_state = SharedStateObj()
    location = Location()
    location.lat = lat
    location.lon = lon
    shared_state.set_location(location)
    return shared_state, location


@pytest.mark.unit
def test_naive_input_is_interpreted_as_utc(frozen_clock):
    shared_state = SharedStateObj()
    # Note: linter will refuse naive datetimes, we have to trick it
    # to get past it, make an 'acceptable' datetime then nuke the tzinfo
    shared_state.set_datetime(
        datetime.datetime(2024, 6, 28, 11, 0, 0, tzinfo=UTC).replace(tzinfo=None),
        force=True,
    )

    stored = shared_state.utc_datetime()
    assert stored.utcoffset() == datetime.timedelta(0)
    assert stored == datetime.datetime(2024, 6, 28, 11, 0, 0, tzinfo=UTC)


@pytest.mark.unit
def test_aware_local_input_is_converted_to_utc(frozen_clock):
    shared_state = SharedStateObj()
    # 13:00 in Brussels in June (CEST, +02:00) is the same instant as 11:00 UTC
    # Note: linter will refuse naive datetimes, we have to trick it
    # to get past it, make an 'acceptable' datetime then nuke the tzinfo

    local = pytz.timezone("Europe/Brussels").localize(
        datetime.datetime(2024, 6, 28, 13, 0, 0, tzinfo=UTC).replace(tzinfo=None)
    )

    shared_state.set_datetime(local, force=True)

    assert shared_state.utc_datetime().utcoffset() == datetime.timedelta(0)
    assert shared_state.utc_datetime() == datetime.datetime(
        2024, 6, 28, 11, 0, 0, tzinfo=UTC
    )
    # The fix lives in storage: bare datetime() must already be UTC, so the
    # status screen's datetime().time() cannot print a local clock as "UTC".
    # (utc_datetime() would re-convert and mask a set_datetime() regression.)
    assert shared_state.datetime().utcoffset() == datetime.timedelta(0)
    assert shared_state.datetime().time() == datetime.time(11, 0, 0)


@pytest.mark.unit
def test_utc_and_local_are_one_instant_in_two_zones(frozen_clock):
    # The status-screen regression: at a non-UTC location, UTC TM and LCL TM
    # are the same instant but must NOT print the same wall-clock time-of-day.
    shared_state, _ = _state_at(BRUSSELS_LAT, BRUSSELS_LON)

    shared_state.set_datetime(
        datetime.datetime(2024, 6, 28, 11, 0, 0, tzinfo=UTC), force=True
    )

    utc_dt = shared_state.utc_datetime()
    local_dt = shared_state.local_datetime()

    assert utc_dt == local_dt  # one absolute instant
    assert utc_dt.time().isoformat()[:8] == "11:00:00"
    assert local_dt.time().isoformat()[:8] == "13:00:00"
    assert utc_dt.time() != local_dt.time()


@pytest.mark.unit
def test_local_datetime_falls_back_to_utc_for_unresolvable_timezone(frozen_clock):
    # set_location() always resolves a valid zone from lat/lon, so to exercise
    # the defensive fallback we force an invalid zone on the stored location.
    shared_state, location = _state_at(BRUSSELS_LAT, BRUSSELS_LON)
    location.timezone = "Not/AZone"

    shared_state.set_datetime(
        datetime.datetime(2024, 6, 28, 11, 0, 0, tzinfo=UTC), force=True
    )

    assert shared_state.local_datetime().utcoffset() == datetime.timedelta(0)
    assert shared_state.local_datetime() == shared_state.utc_datetime()


@pytest.mark.unit
def test_accessors_return_none_when_datetime_unset():
    shared_state = SharedStateObj()

    assert shared_state.utc_datetime() is None
    assert shared_state.local_datetime() is None
