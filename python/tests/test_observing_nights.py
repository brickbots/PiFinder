"""Tests for grouping observations into observing nights.

A session is one software run, so a restart mid-evening starts a new one;
a night is what the observer experienced, noon to noon in the timezone the
observations were logged in. These tests pin the boundary behaviour that
makes an evening and its after-midnight hours one night, and the fallbacks
that keep imperfect rows (no timezone, legacy timestamps) displayable.
"""

import datetime

import pytest
import pytz

from PiFinder.observing_nights import (
    coerce_epoch,
    group_into_nights,
    night_key,
    observation_sqm,
)

BRUSSELS = "Europe/Brussels"


def _epoch(year, month, day, hour, minute=0, tzname=BRUSSELS):
    """A local wall-clock time in `tzname`, as an absolute epoch."""
    zone = pytz.timezone(tzname)
    naive = datetime.datetime(  # noqa: DTZ001 - localized on the next line
        year, month, day, hour, minute
    )
    return zone.localize(naive).timestamp()


def _row(epoch, session_uid="run-1", tzname=BRUSSELS, notes=None):
    return {
        "obs_time_local": epoch,
        "session_uid": session_uid,
        "timezone": tzname,
        "lat": 51.05,
        "lon": 3.72,
        "notes": notes,
    }


@pytest.mark.unit
def test_restart_mid_evening_stays_one_night():
    # 21:00 and 23:30 on the same evening, logged under two software runs.
    rows = [
        _row(_epoch(2026, 7, 18, 21, 0), session_uid="run-1"),
        _row(_epoch(2026, 7, 18, 23, 30), session_uid="run-2"),
    ]

    nights = group_into_nights(rows)

    assert len(nights) == 1
    assert nights[0]["night_key"] == "2026-07-18"
    assert nights[0]["observations"] == 2
    assert nights[0]["sessions"] == 2
    assert nights[0]["span_hours"] == pytest.approx(2.5)


@pytest.mark.unit
def test_after_midnight_belongs_to_the_evening_that_led_to_it():
    rows = [
        _row(_epoch(2026, 7, 18, 22, 0)),
        _row(_epoch(2026, 7, 19, 1, 30)),
    ]

    nights = group_into_nights(rows)

    assert [n["night_key"] for n in nights] == ["2026-07-18"]
    assert nights[0]["start"].hour == 22
    assert nights[0]["end"].hour == 1
    assert nights[0]["span_hours"] == pytest.approx(3.5)


@pytest.mark.unit
def test_noon_is_the_boundary_between_two_nights():
    # 11:59 closes the night named for the previous evening; 12:00 opens
    # the next one.
    before = _epoch(2026, 7, 19, 11, 59)
    after = _epoch(2026, 7, 19, 12, 0)

    assert night_key(before, BRUSSELS) == "2026-07-18"
    assert night_key(after, BRUSSELS) == "2026-07-19"


@pytest.mark.unit
def test_single_observation_night_reports_a_real_time_and_zero_span():
    rows = [_row(_epoch(2026, 7, 18, 22, 15))]

    night = group_into_nights(rows)[0]

    assert night["observations"] == 1
    assert night["span_hours"] == 0
    assert night["start"] == night["end"]
    assert (night["start"].hour, night["start"].minute) == (22, 15)


@pytest.mark.unit
def test_session_running_past_noon_splits_into_two_nights():
    rows = [
        _row(_epoch(2026, 7, 18, 23, 0), session_uid="marathon"),
        _row(_epoch(2026, 7, 19, 14, 0), session_uid="marathon"),
    ]

    nights = group_into_nights(rows)

    assert [n["night_key"] for n in nights] == ["2026-07-19", "2026-07-18"]
    assert all(n["observations"] == 1 for n in nights)


@pytest.mark.unit
def test_dst_transition_inside_a_night_keeps_wall_clock_honest():
    # Europe/Brussels falls back 03:00 -> 02:00 on 2026-10-25, so this
    # night is one hour longer than its clock readings suggest.
    rows = [
        _row(_epoch(2026, 10, 24, 23, 0)),
        _row(_epoch(2026, 10, 25, 3, 0)),
    ]

    night = group_into_nights(rows)[0]

    assert night["night_key"] == "2026-10-24"
    assert night["span_hours"] == pytest.approx(5.0)
    assert (night["start"].hour, night["end"].hour) == (23, 3)


@pytest.mark.unit
def test_missing_or_invalid_timezone_falls_back_to_utc():
    epoch = _epoch(2026, 7, 18, 22, 0, tzname="UTC")

    for tzname in (None, "", "Mars/Olympus_Mons"):
        night = group_into_nights([_row(epoch, tzname=tzname)])[0]
        assert night["night_key"] == "2026-07-18"
        assert night["start"].hour == 22


@pytest.mark.unit
def test_legacy_string_timestamps_still_land_in_a_night():
    # Early rows stored a rendered UTC datetime rather than an epoch.
    rows = [_row("2026-07-18 20:00:00", tzname="UTC")]

    night = group_into_nights(rows)[0]

    assert night["night_key"] == "2026-07-18"
    assert night["start"].hour == 20


@pytest.mark.unit
def test_unreadable_timestamps_are_dropped():
    rows = [
        _row(_epoch(2026, 7, 18, 22, 0)),
        _row(None),
        _row("not a time"),
    ]

    nights = group_into_nights(rows)

    assert len(nights) == 1
    assert nights[0]["observations"] == 1


@pytest.mark.unit
def test_nights_are_summarised_by_their_sky_brightness():
    readings = [21.4, 21.0, 20.6]
    rows = [
        _row(
            _epoch(2026, 7, 18, 22, index),
            notes={"sqm": {"value": value, "source": "Radiometer"}},
        )
        for index, value in enumerate(readings)
    ]
    # An observation logged before any reading existed contributes nothing.
    rows.append(_row(_epoch(2026, 7, 18, 23, 0), notes={"schema_ver": 2}))

    night = group_into_nights(rows)[0]

    assert night["sqm"] == {"median": 21.0, "min": 20.6, "max": 21.4, "count": 3}


@pytest.mark.unit
def test_night_without_readings_has_no_sky_brightness():
    night = group_into_nights([_row(_epoch(2026, 7, 18, 22, 0))])[0]

    assert night["sqm"] is None


@pytest.mark.unit
def test_nights_are_listed_most_recent_first():
    rows = [
        _row(_epoch(2026, 7, 10, 22, 0)),
        _row(_epoch(2026, 7, 18, 22, 0)),
        _row(_epoch(2026, 7, 14, 22, 0)),
    ]

    nights = group_into_nights(rows)

    assert [n["night_key"] for n in nights] == [
        "2026-07-18",
        "2026-07-14",
        "2026-07-10",
    ]


@pytest.mark.unit
def test_coerce_epoch_accepts_the_shapes_the_db_holds():
    assert coerce_epoch(1_752_000_000) == 1_752_000_000.0
    assert coerce_epoch("1752000000") == 1_752_000_000.0
    assert coerce_epoch("2026-07-18 20:00:00") == _epoch(2026, 7, 18, 20, tzname="UTC")
    assert coerce_epoch(None) is None
    assert coerce_epoch("") is None
    assert coerce_epoch("yesterday") is None


@pytest.mark.unit
def test_observation_sqm_ignores_unmeasured_and_malformed_notes():
    assert observation_sqm({"sqm": {"value": 21.2, "source": "Radiometer"}}) == 21.2
    # The notes column holds JSON text, which must read the same way.
    assert observation_sqm('{"sqm": {"value": 21.2, "source": "Radiometer"}}') == 21.2
    assert observation_sqm({"sqm": {"value": 20.15, "source": "None"}}) is None
    assert observation_sqm({"sqm": {"value": None, "source": "Manual"}}) is None
    assert observation_sqm({"schema_ver": 2}) is None
    assert observation_sqm("not a dict") is None
    assert observation_sqm(None) is None
