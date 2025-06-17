import pytest
from PiFinder.db import objects_db


@pytest.mark.unit
def test_object_counts():
    """
    This tests the count in each catalog along with total count
    and will need to be updated with each catalog update
    """
    db = objects_db.ObjectsDatabase()

    catalog_counts = {
        "NGC": 7840,
        "IC": 5386,
        "M": 110,
        "C": 109,
        "Col": 471,
        "Ta2": 200,
        "H": 400,
        "SaA": 114,
        "SaM": 2162,
        "SaR": 333,
        "Str": 78,
        "EGC": 91,
        "RDS": 110,
        "B": 343,
        "Sh2": 313,
        "Abl": 79,
        "Arp": 336,
        "TLK": 93,
    }

    # catalog count
    num_catalogs = len(list(db.get_catalogs()))
    actual_catalogs = [row['catalog_code'] for row in db.get_catalogs()]
    expected_catalogs = list(catalog_counts.keys())
    missing_catalogs = set(expected_catalogs) - set(actual_catalogs)
    extra_catalogs = set(actual_catalogs) - set(expected_catalogs)
    assert not missing_catalogs and not extra_catalogs, f"Catalog mismatch. Missing catalogs: {sorted(missing_catalogs)}. Extra catalogs: {sorted(extra_catalogs)}"

    # Catalog Counts
    for catalog_code, count in catalog_counts.items():
        assert len(list(db.get_catalog_objects_by_catalog_code(catalog_code))) == count


@pytest.mark.unit
def test_missing_catalog_data():
    db = objects_db.ObjectsDatabase()
    # missing data

    for obj in db.get_objects():
        assert obj["ra"] != 0
        assert obj["dec"] != 0
        assert obj["const"] != ""
