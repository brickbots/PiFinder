"""Tests for object_id-derived observed status (ADR 0020, amended).

Log entries are recorded per catalog listing (catalog, sequence), but
observed status is a property of the underlying sky object: logging M 31
must mark NGC 224 observed — in-session, after a restart, and
retroactively for historical log entries. Virtual objects (negative,
session-minted object_ids) stay keyed per listing, as do log entries
whose listing no longer resolves.
"""

import pytest

from PiFinder.composite_object import CompositeObject
from PiFinder.db.observations_db import ObservationsDatabase

# M 31 and NGC 224 are the same sky object; NGC 7000 is unrelated.
LISTING_TO_OBJECT_ID = {("M", 31): 42, ("NGC", 224): 42, ("NGC", 7000): 77}


class MappedObservationsDatabase(ObservationsDatabase):
    """ObservationsDatabase with the objects-DB lookups replaced by a
    fixed listing<->object_id table (the real mapping lives in a separate
    sqlite file not present in unit tests)."""

    def _resolve_object_id(self, catalog, sequence):
        return LISTING_TO_OBJECT_ID.get((catalog, sequence))

    def _resolve_listings(self, object_id):
        return [
            listing for listing, oid in LISTING_TO_OBJECT_ID.items() if oid == object_id
        ]


def _obj(catalog_code: str, sequence: int, object_id: int) -> CompositeObject:
    return CompositeObject(
        object_id=object_id, catalog_code=catalog_code, sequence=sequence
    )


def _log(db: ObservationsDatabase, catalog: str, sequence: int) -> None:
    db.log_object("session-1", 1234567890, catalog, sequence, None, {})


@pytest.fixture
def obs_db(tmp_path):
    db = MappedObservationsDatabase(tmp_path / "observations.db")
    yield db
    db.close()


@pytest.mark.unit
def test_logging_marks_sibling_listing_in_session(obs_db):
    _log(obs_db, "M", 31)
    assert obs_db.check_logged(_obj("M", 31, 42)) is True
    assert obs_db.check_logged(_obj("NGC", 224, 42)) is True
    assert obs_db.check_logged(_obj("NGC", 7000, 77)) is False


@pytest.mark.unit
def test_observed_status_derives_by_object_id_after_restart(tmp_path):
    db = MappedObservationsDatabase(tmp_path / "observations.db")
    _log(db, "M", 31)
    db.close()

    reopened = MappedObservationsDatabase(tmp_path / "observations.db")
    assert reopened.check_logged(_obj("NGC", 224, 42)) is True
    assert reopened.check_logged(_obj("NGC", 7000, 77)) is False
    reopened.close()


@pytest.mark.unit
def test_virtual_objects_key_per_listing(obs_db):
    # Virtual objects share the -1 default (and session-minted negative
    # ids aren't stable across restarts): logging Mars must not mark
    # Jupiter, only the exact listing counts.
    _log(obs_db, "PL", 1)
    assert obs_db.check_logged(_obj("PL", 1, -1)) is True
    assert obs_db.check_logged(_obj("PL", 2, -1)) is False


@pytest.mark.unit
def test_unresolved_listing_stays_listing_keyed(obs_db):
    # A log entry from a catalog that no longer resolves to an object id
    # keeps marking its own listing observed.
    _log(obs_db, "GONE", 5)
    assert obs_db.check_logged(_obj("GONE", 5, -1)) is True


@pytest.mark.unit
def test_details_logs_combine_sibling_listings(obs_db):
    _log(obs_db, "M", 31)
    _log(obs_db, "NGC", 224)
    assert len(obs_db.get_logs_for_object(_obj("NGC", 224, 42))) == 2
    assert len(obs_db.get_logs_for_object(_obj("M", 31, 42))) == 2
    assert len(obs_db.get_logs_for_object(_obj("NGC", 7000, 77))) == 0


@pytest.mark.unit
def test_details_logs_stay_per_listing_for_virtual_objects(obs_db):
    _log(obs_db, "PL", 1)
    assert len(obs_db.get_logs_for_object(_obj("PL", 1, -1))) == 1
    assert len(obs_db.get_logs_for_object(_obj("PL", 2, -1))) == 0
