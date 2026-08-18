"""Tests for object_id-derived observed status (ADR 0025, amended).

Log entries are recorded per catalog listing (catalog, sequence), but
observed status is a property of the underlying sky object: logging M 31
must mark NGC 224 observed — in-session, after a restart, and
retroactively for historical log entries. Virtual objects (negative,
session-minted object_ids) stay keyed per listing, as do log entries
whose listing no longer resolves.
"""

import sqlite3

import pytest

import PiFinder.utils as utils
from PiFinder.composite_object import CompositeObject
from PiFinder.db.observations_db import (
    ObservationsDatabase,
    _observed_identity_caches,
)

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

    def _identity_cache_key(self):
        # Unit tests don't build the separate objects database used on-device.
        return self.db_path.resolve(), self.db_path.resolve()

    def _query_observed_identities(self):
        listings = {
            (row["catalog"], row["sequence"]) for row in self.get_observed_objects()
        }
        object_ids = {
            LISTING_TO_OBJECT_ID[listing]
            for listing in listings
            if listing in LISTING_TO_OBJECT_ID
        }
        return listings, object_ids


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


@pytest.fixture(autouse=True)
def clear_identity_cache():
    _observed_identity_caches.clear()
    yield
    _observed_identity_caches.clear()


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
def test_identity_query_runs_once_then_process_cache_is_reused(tmp_path, monkeypatch):
    path = tmp_path / "observations.db"
    db = MappedObservationsDatabase(path)
    _log(db, "M", 31)
    db.close()
    _observed_identity_caches.clear()

    calls = 0
    original = MappedObservationsDatabase._query_observed_identities

    def counted_query(self):
        nonlocal calls
        calls += 1
        return original(self)

    monkeypatch.setattr(
        MappedObservationsDatabase, "_query_observed_identities", counted_query
    )

    first = MappedObservationsDatabase(path)
    second = MappedObservationsDatabase(path)

    assert calls == 1
    assert first.observed_objects_cache is second.observed_objects_cache
    assert first.observed_object_ids is second.observed_object_ids
    first.close()
    second.close()


@pytest.mark.unit
def test_real_identity_query_resolves_all_logged_listings_at_once(
    tmp_path, monkeypatch
):
    objects_path = tmp_path / "objects.db"
    conn = sqlite3.connect(objects_path)
    conn.execute(
        """
        CREATE TABLE catalog_objects (
            id INTEGER PRIMARY KEY,
            object_id INTEGER,
            catalog_code TEXT,
            sequence INTEGER,
            description TEXT
        )
        """
    )
    conn.executemany(
        "INSERT INTO catalog_objects"
        " (object_id, catalog_code, sequence, description) VALUES (?, ?, ?, ?)",
        [(42, "M", 31, "Andromeda"), (42, "NGC", 224, "")],
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(utils, "pifinder_db", objects_path)

    observations_path = tmp_path / "observations.db"
    db = ObservationsDatabase(observations_path)
    _log(db, "M", 31)
    db.close()
    _observed_identity_caches.clear()

    reopened = ObservationsDatabase(observations_path)

    assert reopened.observed_objects_cache == {("M", 31)}
    assert reopened.observed_object_ids == {42}
    assert reopened.check_logged(_obj("NGC", 224, 42)) is True
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
