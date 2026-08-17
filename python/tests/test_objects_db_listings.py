"""Tests for bulk listing -> object_id resolution in the catalog objects DB.

The observed-objects cache resolves every logged listing to its sky object.
Done one lookup at a time that is N queries per cache build; this maps the
whole set in one query per chunk.
"""

import pytest

from PiFinder.db.objects_db import ObjectsDatabase


@pytest.fixture
def objects_db(tmp_path):
    db = ObjectsDatabase(tmp_path / "pifinder_objects.db")
    db.create_tables()
    for catalog_code in ("M", "NGC"):
        db.insert_catalog(catalog_code, 10000, catalog_code)
    andromeda = db.insert_object("Gx", 10.68, 41.27, "And", "3x1", "3.4")
    north_america = db.insert_object("Nb", 314.75, 44.31, "Cyg", "120x100", "4.0")
    db.insert_catalog_object(andromeda, "M", 31, "Andromeda Galaxy")
    db.insert_catalog_object(andromeda, "NGC", 224, "Andromeda Galaxy")
    db.insert_catalog_object(north_america, "NGC", 7000, "North America Nebula")
    db.object_ids = {"andromeda": andromeda, "north_america": north_america}
    yield db
    db.conn.close()


@pytest.mark.unit
def test_bulk_lookup_matches_single_lookups(objects_db):
    andromeda = objects_db.object_ids["andromeda"]
    north_america = objects_db.object_ids["north_america"]
    listings = [("M", 31), ("NGC", 224), ("NGC", 7000)]
    assert objects_db.get_object_ids_by_listings(listings) == {
        ("M", 31): andromeda,
        ("NGC", 224): andromeda,
        ("NGC", 7000): north_america,
    }


@pytest.mark.unit
def test_bulk_lookup_omits_unresolved_listings(objects_db):
    assert objects_db.get_object_ids_by_listings([("GONE", 5)]) == {}
    assert objects_db.get_object_ids_by_listings([]) == {}


@pytest.mark.unit
def test_bulk_lookup_spans_chunks(objects_db):
    # More listings than one chunk holds, so the chunking loop runs more
    # than once and the known listing still resolves.
    listings = [("MISS", sequence) for sequence in range(1000)]
    listings.append(("NGC", 7000))
    assert objects_db.get_object_ids_by_listings(listings) == {
        ("NGC", 7000): objects_db.object_ids["north_america"]
    }
