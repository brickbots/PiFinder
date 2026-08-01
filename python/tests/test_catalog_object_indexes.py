"""Tests for the catalog_objects lookup indexes.

Both directions of the sky-object <-> catalog-listing mapping are hot paths:
an object's sibling listings (get_catalog_objects_by_object_id) and a listing
resolved back to its sky object (get_catalog_object_by_sequence, which the
observed-objects cache runs for every logged listing). Unindexed, each is a
full scan of ~151k rows, paid per call.

create_tables() only runs during catalog import, so a shipped objects.db has
whatever indexes existed when it was built. _ensure_catalog_object_indexes()
backfills them on open, and must stay quiet and non-fatal when it can't.
"""

import sqlite3

import pytest

from PiFinder.db.objects_db import ObjectsDatabase

INDEX_NAMES = {
    "idx_catalog_objects_object_id",
    "idx_catalog_objects_code_sequence",
}


def _make_db(tmp_path, with_indexes: bool):
    """An objects.db with the catalog_objects table, indexed or not —
    standing in for a freshly built DB vs. one shipped before the indexes
    existed."""
    path = tmp_path / "objects.db"
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE catalog_objects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            object_id INTEGER,
            catalog_code TEXT,
            sequence INTEGER,
            description TEXT
        )
        """
    )
    conn.executemany(
        "INSERT INTO catalog_objects (object_id, catalog_code, sequence, description)"
        " VALUES (?, ?, ?, ?)",
        [(42, "M", 31, "Andromeda"), (42, "NGC", 224, ""), (77, "NGC", 7000, "")],
    )
    if with_indexes:
        conn.execute(
            "CREATE INDEX idx_catalog_objects_object_id ON catalog_objects(object_id)"
        )
        conn.execute(
            "CREATE INDEX idx_catalog_objects_code_sequence"
            " ON catalog_objects(catalog_code, sequence)"
        )
    conn.commit()
    conn.close()
    return path


def _indexes(path) -> set:
    conn = sqlite3.connect(path)
    try:
        return {
            row[0]
            for row in conn.execute(
                "select name from sqlite_master"
                " where type = 'index' and tbl_name = 'catalog_objects'"
            )
        }
    finally:
        conn.close()


@pytest.mark.unit
def test_indexes_backfilled_on_open(tmp_path):
    """A DB built before the indexes existed gets them on first open."""
    path = _make_db(tmp_path, with_indexes=False)
    assert _indexes(path) == set()

    ObjectsDatabase(db_path=path)

    assert INDEX_NAMES <= _indexes(path)


@pytest.mark.unit
def test_open_is_idempotent(tmp_path):
    """Opening an already-indexed DB leaves it alone and doesn't raise."""
    path = _make_db(tmp_path, with_indexes=True)

    ObjectsDatabase(db_path=path)
    ObjectsDatabase(db_path=path)

    assert INDEX_NAMES <= _indexes(path)


@pytest.mark.unit
@pytest.mark.parametrize(
    "query, expected_index",
    [
        (
            "select * from catalog_objects where object_id = 42",
            "idx_catalog_objects_object_id",
        ),
        (
            "select * from catalog_objects"
            " where catalog_code = 'NGC' and sequence = 224",
            "idx_catalog_objects_code_sequence",
        ),
    ],
)
def test_lookups_use_an_index(tmp_path, query, expected_index):
    """Both hot-path lookups plan as an index search, not a table scan."""
    path = _make_db(tmp_path, with_indexes=False)
    db = ObjectsDatabase(db_path=path)

    plan = " ".join(
        row["detail"] for row in db.cursor.execute(f"explain query plan {query}")
    )

    assert expected_index in plan
    assert "SCAN" not in plan


@pytest.mark.unit
def test_unbuildable_indexes_are_not_fatal(tmp_path, caplog):
    """A DB we can't index still opens — lookups are slow, not broken."""
    path = tmp_path / "objects.db"
    sqlite3.connect(path).close()  # no catalog_objects table to index

    db = ObjectsDatabase(db_path=path)

    assert db.conn is not None
    assert _indexes(path) == set()
    assert "catalog lookups will be slower" in caplog.text
