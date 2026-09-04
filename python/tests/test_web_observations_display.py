"""Tests for turning stored observation rows into what the pages draw.

Notes are a JSON blob whose shape has changed across releases and the
solution is a record that has never been displayed before, so the decoding
has to be forgiving: an entry written by an older PiFinder must still
render, just with less in it.
"""

import datetime
import json

import pytest
import pytz

from PiFinder.web_observations import (
    decode_notes,
    decode_solution,
    decorate_logs,
    hour_marks,
    night_summary,
    rating_stars,
    strip_ticks,
)

BRUSSELS = pytz.timezone("Europe/Brussels")


def _local(year, month, day, hour, minute=0):
    naive = datetime.datetime(  # noqa: DTZ001 - localized on the next line
        year, month, day, hour, minute
    )
    return BRUSSELS.localize(naive)


def _night(start, end):
    return {
        "start": start,
        "end": end,
        "start_epoch": start.timestamp(),
        "end_epoch": end.timestamp(),
        "span_hours": (end.timestamp() - start.timestamp()) / 3600,
        "observations": 2,
    }


@pytest.mark.unit
def test_ratings_become_stars_and_out_of_range_values_do_not():
    assert rating_stars(3) == {"filled": 3, "empty": 2}
    assert rating_stars(5) == {"filled": 5, "empty": 0}
    # 0 is the log screen's "not rated" state, not a zero-star rating.
    assert rating_stars(0) is None
    assert rating_stars(9) is None
    assert rating_stars(None) is None
    assert rating_stars("lots") is None


@pytest.mark.unit
def test_notes_split_into_ratings_chips_and_sky_brightness():
    decoded = decode_notes(
        json.dumps(
            {
                "schema_ver": 3,
                "transparency": "Good",
                "seeing": "NA",
                "eyepiece": "13mm Ethos",
                "observability": 4,
                "appeal": 0,
                "sqm": {"value": 21.2, "source": "Radiometer", "scatter": 0.04},
            }
        )
    )

    assert decoded["ratings"] == {"observability": {"filled": 4, "empty": 1}}
    labels = {chip["label"]: chip["value"] for chip in decoded["chips"]}
    # "NA" is the absence of an answer, so it earns no chip.
    assert labels == {"transparency": "Good", "eyepiece": "13mm Ethos"}
    assert decoded["sqm"]["value"] == 21.2


@pytest.mark.unit
def test_unmeasured_sky_brightness_is_not_shown_as_a_reading():
    decoded = decode_notes({"sqm": {"value": 20.15, "source": "None"}})

    assert decoded["sqm"] is None


@pytest.mark.unit
def test_older_notes_still_render():
    # Schema 2 has no sqm at all, and unknown keys must survive as chips
    # rather than vanishing from the page.
    decoded = decode_notes({"schema_ver": 2, "seeing": "Fair", "mood": "hopeful"})

    assert decoded["sqm"] is None
    labels = {chip["label"]: chip["value"] for chip in decoded["chips"]}
    assert labels == {"seeing": "Fair", "mood": "hopeful"}


@pytest.mark.unit
def test_notes_that_cannot_be_read_degrade_to_empty():
    for broken in (None, "", "not json", "[1, 2]", 7):
        decoded = decode_notes(broken)
        assert decoded == {"ratings": {}, "chips": [], "sqm": None}


@pytest.mark.unit
def test_solution_yields_where_the_pifinder_was_pointing():
    decoded = decode_solution(
        json.dumps({"constellation": "Her", "Alt": 61.4, "Az": 120.9, "RA": 250.4})
    )

    assert decoded == {"constellation": "Her", "altitude": 61, "azimuth": 121}


@pytest.mark.unit
def test_missing_or_broken_solution_yields_nothing_to_draw():
    assert decode_solution(None) == {}
    assert decode_solution("") == {}
    assert decode_solution("not json") == {}
    assert decode_solution(json.dumps({})) == {}


@pytest.mark.unit
def test_a_restart_is_flagged_on_the_entry_that_follows_it():
    logs = [
        {"session_uid": "run-1", "notes": {}, "solution": None},
        {"session_uid": "run-1", "notes": {}, "solution": None},
        {"session_uid": "run-2", "notes": {}, "solution": None},
    ]

    decorated = decorate_logs(logs)

    # Never on the first entry: the night starting is not an interruption.
    assert [entry["starts_new_run"] for entry in decorated] == [False, False, True]


@pytest.mark.unit
def test_ticks_place_observations_across_the_night():
    night = _night(_local(2026, 7, 18, 22), _local(2026, 7, 19, 2))
    logs = [
        {"epoch": _local(2026, 7, 18, 22).timestamp()},
        {"epoch": _local(2026, 7, 19, 0).timestamp()},
        {"epoch": _local(2026, 7, 19, 2).timestamp()},
    ]

    assert strip_ticks(night, logs) == [0.0, 0.5, 1.0]


@pytest.mark.unit
def test_ticks_on_a_night_with_no_span_sit_in_the_middle():
    moment = _local(2026, 7, 18, 22)
    night = _night(moment, moment)

    assert strip_ticks(night, [{"epoch": moment.timestamp()}]) == [0.5]


@pytest.mark.unit
def test_hour_marks_fall_on_whole_hours_inside_the_span():
    night = _night(_local(2026, 7, 18, 22, 30), _local(2026, 7, 19, 1, 30))

    assert [label for _fraction, label in hour_marks(night)] == ["23", "00", "01"]
    # Evenly spaced across a three-hour span, none of them at the edges.
    assert [round(fraction, 3) for fraction, _label in hour_marks(night)] == [
        0.167,
        0.5,
        0.833,
    ]


@pytest.mark.unit
def test_a_night_with_no_span_has_no_hour_marks():
    moment = _local(2026, 7, 18, 22)

    assert hour_marks(_night(moment, moment)) == []


@pytest.mark.unit
def test_hour_marks_follow_the_clock_through_a_dst_change():
    # Europe/Brussels falls back 03:00 -> 02:00 on 2026-10-25. Between
    # 23:00 and 04:00 the observer lives six real hours and sees 02 twice;
    # the marks must read the clock, not add an hour to a local time.
    night = _night(_local(2026, 10, 24, 23), _local(2026, 10, 25, 4))
    labels = [label for _fraction, label in hour_marks(night)]

    assert labels == ["00", "01", "02", "02", "03"]


@pytest.mark.unit
def test_summary_totals_every_night():
    nights = [
        {"observations": 6, "span_hours": 9.5},
        {"observations": 1, "span_hours": 0.0},
    ]

    assert night_summary(nights) == {
        "night_count": 2,
        "object_count": 7,
        "total_hours": 9.5,
    }
