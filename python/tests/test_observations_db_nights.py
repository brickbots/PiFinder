"""Tests for the night-scoped queries over a real observations database.

These cover what the pure grouping tests cannot: that the session context
each night needs survives the join, that the duplicate obs_sessions rows a
historical bug left behind do not multiply an observation, and that the
night-scoped export lines up with the session-scoped one.
"""

import datetime
import json

import pytest
import pytz

from PiFinder.db.observations_db import TSV_HEADERS, ObservationsDatabase

BRUSSELS = "Europe/Brussels"


def _epoch(year, month, day, hour, minute=0):
    zone = pytz.timezone(BRUSSELS)
    naive = datetime.datetime(  # noqa: DTZ001 - localized on the next line
        year, month, day, hour, minute
    )
    return zone.localize(naive).timestamp()


class _UnmappedObservationsDatabase(ObservationsDatabase):
    """The objects DB lives in a separate sqlite file that unit tests do
    not have; observed-status mapping is exercised elsewhere."""

    def _resolve_object_id(self, catalog, sequence):
        return None

    def _resolve_listings(self, object_id):
        return []


@pytest.fixture
def obs_db(tmp_path):
    db = _UnmappedObservationsDatabase(tmp_path / "observations.db")
    yield db
    db.close()


def _session(db, uid, start_epoch):
    db.create_obs_session(start_epoch, 51.05, 3.72, BRUSSELS, uid)


def _log(db, uid, epoch, catalog="M", sequence=31, notes=None):
    db.log_object(uid, epoch, catalog, sequence, None, notes or {})


@pytest.mark.unit
def test_two_runs_on_one_evening_are_one_night(obs_db):
    _session(obs_db, "run-1", _epoch(2026, 7, 18, 20, 30))
    _session(obs_db, "run-2", _epoch(2026, 7, 18, 23, 0))
    _log(obs_db, "run-1", _epoch(2026, 7, 18, 21, 0), sequence=31)
    _log(obs_db, "run-2", _epoch(2026, 7, 19, 0, 30), sequence=13)

    nights = obs_db.get_nights()

    assert len(nights) == 1
    night = nights[0]
    assert night["night_key"] == "2026-07-18"
    assert night["observations"] == 2
    assert night["sessions"] == 2
    assert night["timezone"] == BRUSSELS
    assert night["lat"] == pytest.approx(51.05)
    assert night["span_hours"] == pytest.approx(3.5)


@pytest.mark.unit
def test_duplicate_session_rows_do_not_multiply_observations(obs_db):
    # One run, written twice -- the shape the old double-session bug left
    # in existing databases.
    _session(obs_db, "run-1", _epoch(2026, 7, 18, 20, 30))
    _session(obs_db, "run-1", _epoch(2026, 7, 18, 20, 31))
    _log(obs_db, "run-1", _epoch(2026, 7, 18, 21, 0))

    nights = obs_db.get_nights()

    assert len(nights) == 1
    assert nights[0]["observations"] == 1
    assert len(obs_db.get_logs_by_night("2026-07-18")) == 1


@pytest.mark.unit
def test_logs_by_night_are_ordered_and_carry_local_time(obs_db):
    _session(obs_db, "run-1", _epoch(2026, 7, 18, 20, 30))
    _log(obs_db, "run-1", _epoch(2026, 7, 19, 0, 30), sequence=13)
    _log(obs_db, "run-1", _epoch(2026, 7, 18, 21, 0), sequence=31)
    # A different night must not leak in.
    _log(obs_db, "run-1", _epoch(2026, 7, 25, 22, 0), sequence=57)

    logs = obs_db.get_logs_by_night("2026-07-18")

    assert [log["sequence"] for log in logs] == [31, 13]
    assert [log["local_time"].hour for log in logs] == [21, 0]
    assert logs[0]["local_time"].tzinfo is not None


@pytest.mark.unit
def test_night_summarises_recorded_sky_brightness(obs_db):
    _session(obs_db, "run-1", _epoch(2026, 7, 18, 20, 30))
    for index, value in enumerate((21.4, 20.6)):
        _log(
            obs_db,
            "run-1",
            _epoch(2026, 7, 18, 21, index),
            sequence=index,
            notes={"sqm": {"value": value, "source": "Radiometer"}},
        )

    night = obs_db.get_nights()[0]

    assert night["sqm"]["median"] == pytest.approx(21.0)
    assert (night["sqm"]["min"], night["sqm"]["max"]) == (20.6, 21.4)


@pytest.mark.unit
def test_night_export_matches_the_session_export_shape(obs_db):
    _session(obs_db, "run-1", _epoch(2026, 7, 18, 20, 30))
    _log(obs_db, "run-1", _epoch(2026, 7, 18, 21, 0), notes={"seeing": "Good"})

    night_tsv = obs_db.observations_as_tsv(night_key="2026-07-18")
    session_tsv = obs_db.observations_as_tsv(session_uid="run-1")

    night_lines = night_tsv.split("\n")
    assert night_lines[0] == "\t".join(TSV_HEADERS)
    assert night_lines[0] == session_tsv.split("\n")[0]
    assert len(night_lines) == 2

    fields = night_lines[1].split("\t")
    assert len(fields) == len(TSV_HEADERS)
    assert fields[TSV_HEADERS.index("Catalog")] == "M"
    # Observation times in the export read in the observer's zone.
    assert fields[TSV_HEADERS.index("Observation_Time")] == "2026-07-18 21:00:00"
    assert json.loads(fields[TSV_HEADERS.index("Notes")]) == {"seeing": "Good"}


@pytest.mark.unit
def test_both_exports_agree_on_when_an_observation_happened(obs_db):
    # The same instant, downloaded two ways: a night export and the
    # session export an old link still reaches. Both must read as the
    # observer's clock, not UTC.
    _session(obs_db, "run-1", _epoch(2026, 7, 18, 20, 30))
    _log(obs_db, "run-1", _epoch(2026, 7, 18, 23, 30))

    time_column = TSV_HEADERS.index("Observation_Time")
    night_row = obs_db.observations_as_tsv(night_key="2026-07-18").split("\n")[1]
    session_row = obs_db.observations_as_tsv(session_uid="run-1").split("\n")[1]

    assert night_row.split("\t")[time_column] == "2026-07-18 23:30:00"
    assert session_row.split("\t")[time_column] == "2026-07-18 23:30:00"


@pytest.mark.unit
def test_session_export_survives_an_unreadable_timestamp(obs_db):
    _session(obs_db, "run-1", _epoch(2026, 7, 18, 20, 30))
    _log(obs_db, "run-1", _epoch(2026, 7, 18, 23, 30))
    obs_db.cursor.execute("update obs_objects set obs_time_local = 'sometime'")
    obs_db.conn.commit()

    row = obs_db.observations_as_tsv(session_uid="run-1").split("\n")[1]

    assert row.split("\t")[TSV_HEADERS.index("Observation_Time")] == "sometime"


@pytest.mark.unit
def test_night_key_for_session_points_at_its_first_observation(obs_db):
    _session(obs_db, "run-1", _epoch(2026, 7, 18, 20, 30))
    _log(obs_db, "run-1", _epoch(2026, 7, 19, 0, 30))

    assert obs_db.night_key_for_session("run-1") == "2026-07-18"
    # A run that logged nothing has no night to point at.
    assert obs_db.night_key_for_session("run-never-used") is None


@pytest.mark.unit
def test_empty_database_has_no_nights(obs_db):
    assert obs_db.get_nights() == []
    assert obs_db.get_logs_by_night("2026-07-18") == []
