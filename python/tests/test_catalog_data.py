import pytest
import threading
from PiFinder.db import objects_db
from PiFinder.db import observations_db
from PiFinder.catalogs import CatalogBackgroundLoader, Names


@pytest.mark.unit
def test_object_counts():
    """
    This tests the count in each catalog along with total count
    and will need to be updated with each catalog update
    """
    db = objects_db.ObjectsDatabase()

    catalog_counts = {
        "NGC": 7840,
        "WDS": 131303,
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
    num_catalogs = len(list(db.get_catalogs()))
    assert num_catalogs == 19
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
        assert obj["ra"] is not None
        assert obj["dec"] is not None


def coords_are_close(coord1, coord2, tolerance=0.02):
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
    Validate specific NGC objects have correct coordinates and object types.
    Tests 5 well-known NGC objects with known coordinates and classifications.
    """
    db = objects_db.ObjectsDatabase()

    # Test 5 well-known NGC objects with their expected data
    test_objects = [
        {
            "ngc": 104,
            "name": "47 Tucanae",
            "ra": 6.023,  # RA = 00h 24m 05.2s
            "dec": -72.081,  # Dec = -72° 04' 51"
            "obj_type": "Gb",  # Globular cluster
            "const": "Tuc",  # Tucana
        },
        {
            "ngc": 224,
            "name": "Andromeda Galaxy",
            "ra": 10.685,  # RA = 00h 42m 44.3s
            "dec": 41.269,  # Dec = +41° 16' 09"
            "obj_type": "Gx",  # Galaxy
            "const": "And",  # Andromeda
        },
        {
            "ngc": 1976,
            "name": "Orion Nebula",
            "ra": 83.822,  # RA = 05h 35m 17.3s
            "dec": -5.391,  # Dec = -05° 23' 27"
            "obj_type": "Nb",  # Nebula
            "const": "Ori",  # Orion
        },
        {
            "ngc": 2168,
            "name": "M35",
            "ra": 92.275,  # RA = 06h 09m 06s
            "dec": 24.350,  # Dec = +24° 21' 00"
            "obj_type": "OC",  # Open cluster
            "const": "Gem",  # Gemini
        },
        {
            "ngc": 7009,
            "name": "Saturn Nebula",
            "ra": 316.0417,  # RA = 21h 04m 10.8s
            "dec": -11.3631,  # Dec = -11° 22' 18"
            "obj_type": "PN",  # Planetary nebula
            "const": "Aqr",  # Aquarius
        },
    ]

    for test_obj in test_objects:
        ngc_num = test_obj["ngc"]
        name = test_obj["name"]

        # Get object from database
        catalog_obj = db.get_catalog_object_by_sequence("NGC", ngc_num)
        assert (
            catalog_obj is not None
        ), f"NGC {ngc_num} ({name}) should exist in catalog"

        obj = db.get_object_by_id(catalog_obj["object_id"])
        assert obj is not None, f"NGC {ngc_num} ({name}) object should exist"

        # Check coordinates (allow 0.1 degree tolerance for coordinate precision)
        assert coords_are_close(
            obj["ra"], test_obj["ra"], tolerance=0.1
        ), f"NGC {ngc_num} ({name}) RA should be ~{test_obj['ra']}°, got {obj['ra']}°"

        assert coords_are_close(
            obj["dec"], test_obj["dec"], tolerance=0.1
        ), f"NGC {ngc_num} ({name}) Dec should be ~{test_obj['dec']}°, got {obj['dec']}°"

        # Check object type
        assert (
            obj["obj_type"] == test_obj["obj_type"]
        ), f"NGC {ngc_num} ({name}) should be type '{test_obj['obj_type']}', got '{obj['obj_type']}'"

        # Check constellation (if provided)
        if test_obj["const"]:
            assert (
                obj["const"] == test_obj["const"]
            ), f"NGC {ngc_num} ({name}) should be in {test_obj['const']}, got '{obj['const']}'"

        print(
            f"✓ NGC {ngc_num} ({name}): RA={obj['ra']:.3f}°, Dec={obj['dec']:.3f}°, Type={obj['obj_type']}, Const={obj['const']}"
        )


def check_ic_objects():
    """
    Validate specific IC objects have correct coordinates and object types.
    Tests 5 well-known IC objects with known coordinates and classifications.
    """
    db = objects_db.ObjectsDatabase()

    # Test 5 well-known IC objects with their expected data
    test_objects = [
        {
            "ic": 434,
            "name": "Horsehead Nebula",
            "ra": 85.253,  # RA = 05h 41m 01s
            "dec": -2.457,  # Dec = -02° 27' 25"
            "obj_type": "Nb",  #  Emission Nebula
            "const": "Ori",  # Orion
        },
        {
            "ic": 1396,
            "name": "Elephant's Trunk Nebula",
            "ra": 324.725,  # RA = 21h 36m 33s
            "dec": 57.486,  # Dec = +57° 30' 00"
            "obj_type": "Nb",  # Emission nebula
            "const": "Cep",  # Cepheus
        },
        {
            "ic": 405,
            "name": "Flaming Star Nebula",
            "ra": 79.07,  # RA = 05h 16m 17s (hand corrected on simbad image)
            "dec": 34.383,  # Dec = +34° 34' 12.2"
            "obj_type": "Nb",  # Emission/reflection nebula
            "const": "Aur",  # Auriga
        },
        {
            "ic": 1805,
            "name": "Heart Nebula",
            "ra": 38.200,  # RA = 02h 32m 48s
            "dec": 61.450,  # Dec = +61° 27' 00"
            # "obj_type": "Nb", # Emission nebula
            "obj_type": "OC",  # Open cluster at the heart of the nebula
            "const": "Cas",  # Cassiopeia
        },
        {
            "ic": 10,
            "name": "Galaxy in Sculptor",
            "ra": 5.072,  # RA = 00h 20m 37s
            "dec": 59.303,  # Dec = -33° 45' 04"
            "obj_type": "Gx",  # Galaxy
            "const": "Cas",  # Cassiopeia
        },
    ]

    for test_obj in test_objects:
        ic_num = test_obj["ic"]
        name = test_obj["name"]

        # Get object from database
        catalog_obj = db.get_catalog_object_by_sequence("IC", ic_num)
        assert catalog_obj is not None, f"IC {ic_num} ({name}) should exist in catalog"

        obj = db.get_object_by_id(catalog_obj["object_id"])
        assert obj is not None, f"IC {ic_num} ({name}) object should exist"

        # Check coordinates (allow 0.1 degree tolerance for coordinate precision)
        assert coords_are_close(
            obj["ra"], test_obj["ra"], tolerance=0.1
        ), f"IC {ic_num} ({name}) RA should be ~{test_obj['ra']}°, got {obj['ra']}°"

        assert coords_are_close(
            obj["dec"], test_obj["dec"], tolerance=0.1
        ), f"IC {ic_num} ({name}) Dec should be ~{test_obj['dec']}°, got {obj['dec']}°"

        # Check object type
        assert (
            obj["obj_type"] == test_obj["obj_type"]
        ), f"IC {ic_num} ({name}) should be type '{test_obj['obj_type']}', got '{obj['obj_type']}'"

        # Check constellation (if provided)
        if test_obj["const"]:
            assert (
                obj["const"] == test_obj["const"]
            ), f"IC {ic_num} ({name}) should be in {test_obj['const']}, got '{obj['const']}'"

        print(
            f"✓ IC {ic_num} ({name}): RA={obj['ra']:.3f}°, Dec={obj['dec']:.3f}°, Type={obj['obj_type']}, Const={obj['const']}"
        )


@pytest.mark.unit
def test_catalog_data_validation():
    """
    Test that critical catalog objects have correct coordinates and data.
    This validates the post-processing has correctly added missing objects
    and that coordinates match expected astronomical values.
    """
    check_messier_objects()
    check_ngc_objects()
    check_ic_objects()


@pytest.mark.unit
def test_background_loader():
    """
    Test that CatalogBackgroundLoader correctly loads objects in background.
    """
    # Load minimal test data
    db = objects_db.ObjectsDatabase()

    # Create a mock observations database for testing
    class MockObservationsDB:
        def check_logged(self, obj):
            return False

    obs_db = MockObservationsDB()

    # Get small sample of WDS objects for testing
    catalog_objects = list(db.get_catalog_objects_by_catalog_code("WDS"))[:100]
    catalog_objects_list = [dict(row) for row in catalog_objects]

    # Get objects dict
    objects = {row["id"]: dict(row) for row in db.get_objects()}

    # Get names
    common_names = Names()

    # Track completion
    loaded_count = 0
    completed = threading.Event()
    loaded_objects = []

    def on_progress(loaded, total, catalog):
        nonlocal loaded_count
        loaded_count = loaded

    def on_complete(objects):
        nonlocal loaded_objects
        loaded_objects = objects
        completed.set()

    # Create and start loader
    loader = CatalogBackgroundLoader(
        deferred_catalog_objects=catalog_objects_list,
        objects=objects,
        common_names=common_names,
        obs_db=obs_db,
        on_progress=on_progress,
        on_complete=on_complete,
    )

    # Configure for faster testing
    loader.batch_size = 10
    loader.yield_time = 0.001

    loader.start()

    # Wait for completion (5 second timeout)
    assert completed.wait(timeout=5.0), "Background loading did not complete in time"

    # Verify results
    assert loaded_count == 100, f"Expected 100 objects, got {loaded_count}"
    assert len(loaded_objects) == 100, f"Expected 100 loaded objects, got {len(loaded_objects)}"

    # Verify objects have details loaded
    for obj in loaded_objects[:10]:  # Check first 10
        assert obj._details_loaded, "Object should have details loaded"
        assert obj.mag_str != "...", "Object should have magnitude loaded"
        assert hasattr(obj, "names"), "Object should have names"
        assert obj.catalog_code == "WDS", "Object should be WDS catalog"
