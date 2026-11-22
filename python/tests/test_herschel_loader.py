"""
Tests for the Herschel 400 loader, against a small objects DB built here,
never the committed one.
"""

import json

import pytest

import PiFinder.utils as utils
from PiFinder.catalog_imports import catalog_import_utils, herschel_loader
from PiFinder.db.objects_db import ObjectsDatabase

pytestmark = pytest.mark.unit

SIZE = json.dumps({"e": [], "p": 0.0})
MAG = json.dumps({"mags": [], "filter_mag": 99})

HEADER = "NGC_#\tCon\tType\tRA_2000\tDeclination\tMag\tSize\tHershel_#\tNotes\n"


@pytest.fixture
def db(tmp_path, monkeypatch):
    """An objects DB the Herschel loader reads from and writes to."""
    db = ObjectsDatabase(tmp_path / "objects.db")
    db.create_tables()
    db.insert_catalog("NGC", 10000, "NGC")
    (tmp_path / "herschel400.desc").write_text("Herschel 400")
    monkeypatch.setattr(utils, "astro_data_dir", tmp_path)
    monkeypatch.setattr(herschel_loader, "objects_db", db)
    monkeypatch.setattr(catalog_import_utils, "objects_db", db)
    yield db
    db.conn.close()


def test_a_herschel_listing_joins_the_sky_object_of_its_ngc_listing(db, tmp_path):
    # NGC 6 is a Steinicke duplicate on NGC 20's sky object, so from there on
    # a listing's id runs ahead of its object's: NGC 404's listing is id 3,
    # its sky object id 2.
    ngc_20 = db.insert_object("Gx", 2.386, 33.309, "And", SIZE, MAG)
    ngc_404 = db.insert_object("Gx", 17.363, 35.718, "And", SIZE, MAG)
    db.insert_catalog_object(ngc_20, "NGC", 20, "")
    db.insert_catalog_object(ngc_20, "NGC", 6, "")
    db.insert_catalog_object(ngc_404, "NGC", 404, "")
    (tmp_path / "herschel400.tsv").write_text(
        HEADER
        + "404\tAND\tE0\t01 09.5\t\t10.1\t4'X4'\tH II 224\tBright\n"
        + "6\tAND\tE\t00 09.5\t\t13.1\t1'X1'\tH III 100\tFaint\n"
    )

    herschel_loader.load_herschel400()

    listings = {
        row["sequence"]: row["object_id"]
        for row in db.conn.execute(
            "SELECT sequence, object_id FROM catalog_objects WHERE catalog_code = 'H'"
        )
    }
    assert listings == {1: ngc_404, 2: ngc_20}
    names = {
        row["common_name"]: row["object_id"]
        for row in db.conn.execute("SELECT * FROM names WHERE origin = 'H'")
    }
    assert names == {"H II 224": ngc_404, "H III 100": ngc_20}
