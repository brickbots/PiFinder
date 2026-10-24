"""Tests for the catalog import's common names: the Messier names, their
placement as preferred names, title-casing NGC 2000.0's names, and the hand-
built Messier objects' akas.

Everything runs against a small objects DB built here, never the committed
one. See docs/ax/catalog.md 9.6 for the name order these tests pin down.
"""

import json

import pytest

import PiFinder.catalog_imports.catalog_import_utils as catalog_import_utils
import PiFinder.catalog_imports.post_processing as post_processing
from PiFinder.catalog_imports.post_processing import (
    add_messier_names,
    add_missing_messier_objects,
    parse_messier_names,
    title_case,
)
from PiFinder.db.objects_db import ObjectsDatabase

pytestmark = pytest.mark.unit


def _mag(*mags):
    return json.dumps({"mags": list(mags), "filter_mag": mags[0] if mags else 99})


def _size(*arcsec):
    return json.dumps({"e": list(arcsec), "p": 0.0})


@pytest.fixture
def db(tmp_path):
    """Sky objects with their listings and names, in insertion order, as the
    NGC loader and the NGC 2000.0 names leave them."""
    db = ObjectsDatabase(tmp_path / "objects.db")
    db.create_tables()
    for code in ("M", "NGC", "IC", "Lyn"):
        db.insert_catalog(code, 10000, code)
    objects = [
        (
            ("Gx", 10.6846, 41.2692, "And", _size(11400, 3600), _mag(3.4)),
            [("NGC", 224), ("M", 31)],
            [
                ("NGC 224", "NGC"),
                ("Great Nebula in Andromeda", "NGC"),
                ("M31", "NGC"),
            ],
        ),
        (
            ("OC", 130.1, 19.67, "Cnc", _size(5700), _mag(3.1)),
            [("NGC", 2632), ("M", 44)],
            [
                ("NGC 2632", "NGC"),
                ("Beehive Cluster", "NGC"),
                ("M44", "NGC"),
                ("Praesepe", "NGC"),
                ("Lyn 449", "Lyn"),
            ],
        ),
        (
            ("Nb", 274.7, -18.55, "Sgr", _size(), _mag()),
            [("IC", 4715)],
            [("IC 4715", "IC")],
        ),
    ]
    for values, listings, names in objects:
        object_id = db.insert_object(*values)
        for code, sequence in listings:
            db.insert_catalog_object(object_id, code, sequence, "")
        for name, origin in names:
            db.insert_name(object_id, name, origin)
    yield db
    db.conn.close()


def object_id_of(db, code, sequence):
    return db.get_catalog_object_by_sequence(code, sequence)["object_id"]


def names_of(db, code, sequence):
    """(name, origin) of a listing's sky object, in the order the device reads
    them (by row id)."""
    rows = db.cursor.execute(
        "SELECT common_name, origin FROM names WHERE object_id = ? ORDER BY id",
        (object_id_of(db, code, sequence),),
    )
    return [(row[0], row[1]) for row in rows]


# ---------------------------------------------------------------------------
# messier_names.dat parsing
# ---------------------------------------------------------------------------


def test_parse_messier_names_reads_each_line_in_order():
    lines = [
        "M1\tCrab Nebula\n",
        "\n",
        "M44\tBeehive Cluster;  Praesepe \n",
        "M45\tPleiades; Subaru; Seven Sisters\n",
    ]
    names = parse_messier_names(lines)
    assert names == {
        1: ["Crab Nebula"],
        44: ["Beehive Cluster", "Praesepe"],
        45: ["Pleiades", "Subaru", "Seven Sisters"],
    }
    assert list(names) == [1, 44, 45]


def test_parse_messier_names_keeps_commas_inside_a_name():
    # The separator is ";", so a comma is part of the name.
    assert parse_messier_names(["M8\tLagoon Nebula, core\n"]) == {
        8: ["Lagoon Nebula, core"]
    }


@pytest.mark.parametrize(
    "line, problem",
    [
        ("M1 NGC 1952 Crab Nebula", "expected M<n><TAB>Name; Name"),
        ("NGC 1952\tCrab Nebula", "is not an M number"),
        ("M\tCrab Nebula", "is not an M number"),
        ("M1\t ; ", "has no name"),
    ],
)
def test_parse_messier_names_rejects_a_malformed_line(line, problem):
    with pytest.raises(ValueError, match=problem) as excinfo:
        parse_messier_names(["M2\tGlobular\n", line])
    assert "line 2" in str(excinfo.value)


def test_parse_messier_names_rejects_a_number_listed_twice():
    with pytest.raises(ValueError, match="M 1 is listed twice"):
        parse_messier_names(["M1\tCrab Nebula", "M1\tTaurus A"])


def test_the_curated_file_parses():
    names = post_processing._load_messier_names()
    assert set(names) <= set(range(1, 111))
    assert names[33] == ["Triangulum Galaxy"]  # "Pinwheel" is M 101
    assert names[101] == ["Pinwheel Galaxy"]
    assert names[44] == ["Beehive Cluster", "Praesepe"]
    assert names[45][0] == "Pleiades"
    # "Satellite of M31" describes M 32 and M 110; it isn't a name.
    assert 32 not in names
    assert 110 not in names
    for m_names in names.values():
        for name in m_names:
            assert not name.startswith(("NGC", "IC")), name


# ---------------------------------------------------------------------------
# Preferred names: the first Messier name goes first
# ---------------------------------------------------------------------------


def test_a_messier_name_becomes_the_preferred_name(db):
    add_messier_names(db, {31: ["Andromeda Galaxy"]})
    assert names_of(db, "M", 31) == [
        ("Andromeda Galaxy", "M"),
        ("NGC 224", "NGC"),
        ("Great Nebula in Andromeda", "NGC"),
        ("M31", "NGC"),
    ]


def test_a_name_the_object_has_moves_first_and_keeps_its_row(db):
    add_messier_names(db, {44: ["Beehive Cluster", "Praesepe"]})
    assert names_of(db, "M", 44) == [
        ("Beehive Cluster", "NGC"),
        ("Praesepe", "NGC"),
        ("NGC 2632", "NGC"),
        ("M44", "NGC"),
        ("Lyn 449", "Lyn"),
    ]


def test_other_objects_names_are_untouched(db):
    before = names_of(db, "IC", 4715)
    ic_ids = [
        row[0]
        for row in db.cursor.execute(
            "SELECT id FROM names WHERE object_id = ?",
            (object_id_of(db, "IC", 4715),),
        )
    ]
    add_messier_names(db, {31: ["Andromeda Galaxy"], 44: ["Praesepe"]})
    assert names_of(db, "IC", 4715) == before
    assert [
        row[0]
        for row in db.cursor.execute(
            "SELECT id FROM names WHERE object_id = ?",
            (object_id_of(db, "IC", 4715),),
        )
    ] == ic_ids


def test_placing_the_names_twice_gives_the_same_order(db):
    messier_names = {31: ["Andromeda Galaxy"], 44: ["Beehive Cluster", "Praesepe"]}
    add_messier_names(db, messier_names)
    once = (names_of(db, "M", 31), names_of(db, "M", 44))
    add_messier_names(db, messier_names)
    assert (names_of(db, "M", 31), names_of(db, "M", 44)) == once


def test_a_messier_number_no_loader_created_fails(db):
    with pytest.raises(ValueError, match="M 57"):
        add_messier_names(db, {57: ["Ring Nebula"]})


# ---------------------------------------------------------------------------
# NGC 2000.0 names: title case, by the atlas's rule
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Crab nebula", "Crab Nebula"),
        ("Bode's nebulae", "Bode's Nebulae"),
        # Small words after the first stay lower case.
        ("Ring nebula in Lyra", "Ring Nebula in Lyra"),
        ("Great Cluster in Hercules", "Great Cluster in Hercules"),
        ("Owl or E.T. Cluster", "Owl or E.T. Cluster"),
        # ... but not as the first word.
        ("the Eyes", "The Eyes"),
        # Each part of a hyphenated word.
        ("Pin-wheel nebula", "Pin-Wheel Nebula"),
        # A capital is never lowered.
        ("North America nebula", "North America Nebula"),
        ("Polarissima Borealis", "Polarissima Borealis"),
        ("eta Car nebula", "Eta Car Nebula"),
        ("47 Tuc", "47 Tuc"),
    ],
)
def test_title_case(name, expected):
    assert title_case(name) == expected


# ---------------------------------------------------------------------------
# The hand-built Messier objects
# ---------------------------------------------------------------------------


def test_m24_joins_ic_4715(db, monkeypatch):
    """M 24 takes "IC 4715" as an aka, so it lists on IC 4715's sky object."""
    monkeypatch.setattr(catalog_import_utils, "objects_db", db)
    monkeypatch.setattr(post_processing, "objects_db", db)
    monkeypatch.setattr(catalog_import_utils, "ObjectsDatabase", lambda: db)

    add_missing_messier_objects()

    assert object_id_of(db, "M", 24) == object_id_of(db, "IC", 4715)
    names = [name for name, _origin in names_of(db, "M", 24)]
    assert names[0] == "IC 4715"
    assert "M 24" in names
    assert "Sagittarius Star Cloud" in names
