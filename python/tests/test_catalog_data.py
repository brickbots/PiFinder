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
        "M": 110,  # 106 from names.dat + 4 added by post-processing (M24, M40, M45, M102)
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
        "Arp": 337,  # should be 338, arp-1 is missing from the original sqlite source database !
        "TLK": 93,
    }

    # catalog count
    actual_catalogs = [row["catalog_code"] for row in db.get_catalogs()]
    expected_catalogs = list(catalog_counts.keys())
    missing_catalogs = set(expected_catalogs) - set(actual_catalogs)
    extra_catalogs = set(actual_catalogs) - set(expected_catalogs)
    assert (
        not missing_catalogs and not extra_catalogs
    ), f"Catalog mismatch. Missing catalogs: {sorted(missing_catalogs)}. Extra catalogs: {sorted(extra_catalogs)}"

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


def coords_are_close(coord1, coord2, tolerance=0.01):
    """
    Helper function to compare coordinates with floating point tolerance.

    Args:
        coord1: First coordinate value
        coord2: Second coordinate value
        tolerance: Acceptable difference (default 0.01 degrees)

    Returns:
        bool: True if coordinates are within tolerance
    """
    return abs(coord1 - coord2) <= tolerance


def check_messier_objects():
    """
    Validate specific Messier objects have correct coordinates and data.
    """
    db = objects_db.ObjectsDatabase()

    # Test M45 - Pleiades (should have been added by post-processing)
    m45_catalog_obj = db.get_catalog_object_by_sequence("M", 45)
    assert m45_catalog_obj is not None, "M45 should exist in catalog_objects table"

    m45_obj = db.get_object_by_id(m45_catalog_obj["object_id"])
    assert m45_obj is not None, "M45 object should exist in objects table"

    # Validate M45 coordinates (Pleiades)
    # Expected: RA=56.85°, Dec=+24.117°
    assert coords_are_close(
        m45_obj["ra"], 56.85
    ), f"M45 RA should be ~56.85°, got {m45_obj['ra']}"
    assert coords_are_close(
        m45_obj["dec"], 24.117
    ), f"M45 Dec should be ~24.117°, got {m45_obj['dec']}"

    # Validate M45 object type and constellation
    assert (
        m45_obj["obj_type"] == "OC"
    ), f"M45 should be type 'OC' (open cluster), got '{m45_obj['obj_type']}'"
    assert (
        m45_obj["const"] == "Tau"
    ), f"M45 should be in Taurus (Tau), got '{m45_obj['const']}'"

    # Test M40 - Winnecke 4 (should have been added by post-processing)
    m40_catalog_obj = db.get_catalog_object_by_sequence("M", 40)
    assert m40_catalog_obj is not None, "M40 should exist in catalog_objects table"

    m40_obj = db.get_object_by_id(m40_catalog_obj["object_id"])
    assert m40_obj is not None, "M40 object should exist in objects table"

    # Validate M40 coordinates (Winnecke 4)
    # Expected: RA=185.552°, Dec=+58.083°
    assert coords_are_close(
        m40_obj["ra"], 185.552
    ), f"M40 RA should be ~185.552°, got {m40_obj['ra']}"
    assert coords_are_close(
        m40_obj["dec"], 58.083
    ), f"M40 Dec should be ~58.083°, got {m40_obj['dec']}"

    # Validate M40 object type and constellation
    assert (
        m40_obj["obj_type"] == "D*"
    ), f"M40 should be type 'D*' (double star), got '{m40_obj['obj_type']}'"
    assert (
        m40_obj["const"] == "UMa"
    ), f"M40 should be in Ursa Major (UMa), got '{m40_obj['const']}'"


def check_ngc_objects():
    """
    Validate specific NGC objects have correct data.
    Placeholder for future NGC-specific validations.
    """
    # TODO: Add NGC-specific validations
    pass


def check_ic_objects():
    """
    Validate specific IC objects have correct data.
    Placeholder for future IC-specific validations.
    """
    # TODO: Add IC-specific validations
    pass


@pytest.mark.unit
def test_catalog_data_validation():
    """
    Test that critical catalog objects have correct coordinates and data.
    This validates the post-processing has correctly added missing objects
    and that coordinates match expected astronomical values.
    """
    check_messier_objects()
    # Future: check_ngc_objects(), check_ic_objects(), etc.
