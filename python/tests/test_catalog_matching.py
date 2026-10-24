"""Tests for how a catalog listing joins a sky object (docs/ax/catalog.md §9).

The match guard (§9.3), precedence when a listing joins (§9.1), which akas
are stored as names, the Arp loader's lettered components, and the Caldwell,
Barnard and Arp loaders. Everything runs against a small objects DB built
here, never the committed one.
"""

import importlib
import logging
import sqlite3

import pytest

import PiFinder.catalog_imports.caldwell_loader as caldwell_loader
import PiFinder.catalog_imports.catalog_import_utils as ciu
import PiFinder.catalog_imports.specialized_loaders as specialized_loaders
import PiFinder.utils as utils
from PiFinder.catalog_imports.caldwell_loader import caldwell_akas
from PiFinder.catalog_imports.catalog_import_utils import (
    NewCatalogObject,
    ObjectFinder,
    is_star_type,
    match_guard,
    parse_component,
)
from PiFinder.composite_object import MagnitudeObject, SizeObject
from PiFinder.db.objects_db import ObjectsDatabase

pytestmark = pytest.mark.unit

# The package's __init__ exports main(), which shadows the module attribute.
catalog_import_main = importlib.import_module("PiFinder.catalog_imports.main")

ARCMIN = 1 / 60

# (catalog_code, sequence, obj_type, ra, dec, size in arcmin, mag)
SKY_OBJECTS = [
    ("NGC", 869, "OC", 34.75, 57.13, [18.0], [5.3]),
    ("NGC", 884, "OC", 35.6, 57.15, [18.0], [6.1]),
    ("NGC", 91, "*", 5.40, -22.40, [], [14.0]),
    ("NGC", 1097, "Gx", 41.579, -30.274, [9.4, 6.6], [9.5]),
    ("NGC", 4676, "Gx", 191.542, 30.733, [1.4], [13.5]),
    ("NGC", 5490, "Gx", 212.489, 17.546, [2.4], [12.1]),
    ("NGC", 5194, "Gx", 202.469, 47.195, [11.2], [8.4]),
    ("NGC", 6885, "Ast", 302.92, 26.55, [], []),
    ("NGC", 6401, "Gb", 264.65, -23.91, [4.8], [7.4]),
    ("NGC", 1835, "OC", 76.27, -69.41, [2.3], [9.8]),
    ("NGC", 7000, "Nb", 314.75, 44.33, [120.0, 100.0], [4.0]),
    ("IC", 1590, "C+N", 13.20, 56.63, [], []),
    ("Sh2", 155, "Nb", 344.25, 62.62, [50.0], []),
    ("B", 53, "DN", 270.0, -10.0, [10.0], []),
    ("H", 99, "Gx", 150.0, 20.0, [2.0], [11.0]),
    ("Str", 1, "*", 100.0, 10.0, [], [3.0]),
    ("NGC", 2000, "?", 120.0, 5.0, [], []),
    ("NGC", 4666, "Gx", 191.286, -0.462, [4.6, 1.3], [10.7]),
]
LISTING_CODES = ("M", "Arp", "C", "Col", "EGC", "Har", "Lyn", "SaM", "Ta2", "WDS")


@pytest.fixture
def db(tmp_path, monkeypatch):
    """A small objects DB, set as the import's objects_db."""
    db = ObjectsDatabase(tmp_path / "objects.db")
    db.create_tables()
    # Every catalog a fixture or a test lists, for the foreign key.
    codes = {row[0] for row in SKY_OBJECTS} | set(LISTING_CODES)
    for code in sorted(codes):
        db.insert_catalog(code, 10000, code)
    for code, sequence, obj_type, ra, dec, size, mag in SKY_OBJECTS:
        object_id = db.insert_object(
            obj_type,
            ra,
            dec,
            "And",
            SizeObject.from_arcmin(*size).to_json(),
            MagnitudeObject(mag).to_json(),
        )
        db.insert_catalog_object(object_id, code, sequence, "")
        db.insert_name(object_id, f"{code} {sequence}", code)
        if (code, sequence) == ("NGC", 5194):
            db.insert_catalog_object(object_id, "M", 51, "")
    monkeypatch.setattr(ciu, "objects_db", db)
    monkeypatch.setattr(ciu, "MATCH_REJECTIONS", [])
    # Loaders that build their own ObjectFinder() read this DB, not the
    # committed one.
    monkeypatch.setattr(ciu, "ObjectsDatabase", lambda: db)
    yield db
    db.conn.close()


@pytest.fixture
def finder(db):
    finder = ObjectFinder(db)
    NewCatalogObject.set_shared_finder(finder)
    yield finder
    NewCatalogObject.clear_shared_finder()


def object_of(db, code, sequence):
    row = db.conn.execute(
        "SELECT object_id FROM catalog_objects WHERE catalog_code = ? AND sequence = ?",
        (code, sequence),
    ).fetchone()
    return row["object_id"]


def sky_object(db, code, sequence):
    return db.conn.execute(
        "SELECT * FROM objects WHERE id = ?", (object_of(db, code, sequence),)
    ).fetchone()


def names(db, code, sequence):
    rows = db.conn.execute(
        "SELECT common_name FROM names WHERE object_id = ? ORDER BY id",
        (object_of(db, code, sequence),),
    ).fetchall()
    return [row["common_name"] for row in rows]


def mags(db, code, sequence):
    return MagnitudeObject.from_json(sky_object(db, code, sequence)["mag"]).mags


def size_arcmin(db, code, sequence):
    size = SizeObject.from_json(sky_object(db, code, sequence)["size"])
    return [round(extent / 60, 3) for extent in size.extents]


def listing(code, sequence, obj_type, ra, dec, akas, mag=(), size=(), **kwargs):
    return NewCatalogObject(
        object_type=obj_type,
        catalog_code=code,
        sequence=sequence,
        ra=ra,
        dec=dec,
        mag=MagnitudeObject(list(mag)),
        size=SizeObject.from_arcmin(*size),
        aka_names=list(akas),
        **kwargs,
    )


def joins(db, new_listing, code, sequence):
    new_listing.insert()
    return object_of(db, new_listing.catalog_code, new_listing.sequence) == (
        object_of(db, code, sequence)
    )


def row(obj_type, ra, dec, size_arcmin=()):
    return {
        "obj_type": obj_type,
        "ra": ra,
        "dec": dec,
        "size": SizeObject.from_arcmin(*size_arcmin).to_json(),
    }


# --- The match guard ---------------------------------------------------------


@pytest.mark.parametrize(
    "obj_type, star",
    [
        ("*", True),
        ("* ", True),
        ("D*", True),
        ("**", True),
        ("***", None),
        ("D*?", True),
        ("Gx", False),
        ("OC", False),
        ("Ast", False),
        ("C+N", False),
        ("Open Cluster", False),
        ("?", None),
        ("", None),
        ("-", None),
        (None, None),
    ],
)
def test_star_types(obj_type, star):
    assert is_star_type(obj_type) is star


def test_guard_rejects_a_star_for_a_non_star_and_back():
    assert match_guard("D*", 10.0, 10.0, row("Gx", 10.0, 10.0)) == "types D* and Gx"
    assert match_guard("Gx", 10.0, 10.0, row("*", 10.0, 10.0)) == "types Gx and *"


def test_guard_accepts_compatible_types():
    assert match_guard("D*", 10.0, 10.0, row("*", 10.0, 10.0)) is None
    assert match_guard("Open Cluster", 10.0, 10.0, row("OC", 10.0, 10.0)) is None


def test_an_unknown_type_is_compatible_with_both():
    assert match_guard("D*", 10.0, 10.0, row("?", 10.0, 10.0)) is None
    assert match_guard("?", 10.0, 10.0, row("Gx", 10.0, 10.0)) is None


def test_a_star_group_is_compatible_with_both():
    # Lyngå lists M 73, Steinicke's "*4" group, as an open cluster.
    assert match_guard("OC", 10.0, 10.0, row("***", 10.0, 10.0)) is None
    assert match_guard("D*", 10.0, 10.0, row("***", 10.0, 10.0)) is None


def test_guard_limit_is_30_arcmin():
    assert match_guard("OC", 10.0, 10.0 + 29 * ARCMIN, row("OC", 10.0, 10.0)) is None
    assert (
        match_guard("OC", 10.0, 10.0 + 31 * ARCMIN, row("OC", 10.0, 10.0))
        == "31.0' apart, limit 30'"
    )


def test_guard_limit_widens_to_the_objects_own_size():
    big = row("Nb", 10.0, 10.0, (120.0, 100.0))
    assert match_guard("Nb", 10.0, 10.0 + 100 * ARCMIN, big) is None
    assert (
        match_guard("Nb", 10.0, 10.0 + 130 * ARCMIN, big) == "130.0' apart, limit 120'"
    )


def test_guard_measures_great_circle_distance():
    # At Dec 60, 1 degree of RA is 30' of sky.
    assert match_guard("OC", 11.0, 60.0, row("OC", 10.0, 60.0)) is None


def test_a_rejected_listing_becomes_its_own_sky_object(db, finder, caplog):
    arp_65 = listing("Arp", 65, "Gx", 5.40, -22.40, ["NGC 0091"])
    with caplog.at_level(logging.WARNING):
        assert not joins(db, arp_65, "NGC", 91)
    assert ciu.MATCH_REJECTIONS == [
        ciu.MatchRejection(
            "Arp 65", "NGC 0091", object_of(db, "NGC", 91), "types Gx and *"
        )
    ]
    assert "Match guard: Arp 65 does not join 'NGC 0091'" in caplog.text
    # The rejected designation is another sky object's: not a name of this one.
    assert names(db, "Arp", 65) == ["Arp 65"]


def test_a_listing_too_far_away_becomes_its_own_sky_object(db, finder):
    far = listing("Col", 314, "OC", 34.75, 59.13, ["NGC 869"])
    assert not joins(db, far, "NGC", 869)
    assert ciu.MATCH_REJECTIONS[0].reason == "120.0' apart, limit 30'"


def test_after_a_rejection_the_next_aka_is_tried(db, finder):
    near_1097 = listing("Arp", 77, "Gx", 41.58, -30.27, ["NGC 91", "NGC 1097"])
    assert joins(db, near_1097, "NGC", 1097)
    assert [rejection.aka for rejection in ciu.MATCH_REJECTIONS] == ["NGC 91"]


def test_a_star_joins_a_star(db, finder):
    assert joins(db, listing("SaM", 7, "D*", 100.0, 10.0, ["Str 1"]), "Str", 1)


def test_a_star_joins_an_object_of_unknown_type(db, finder):
    assert joins(db, listing("SaM", 8, "D*", 120.0, 5.0, ["NGC 2000"]), "NGC", 2000)


# --- The lookup ----------------------------------------------------------------


def test_lookup_goes_through_the_allowlist_only(db):
    finder = ObjectFinder(db)
    # Unspaced, these were once the exact keys of Barnard 53 and H 400 #99.
    assert finder.get_object_id("B53") is None
    assert finder.get_object_id("b53") is None
    assert finder.get_object_id("h99") is None
    assert finder.get_object_id("H 99") is None
    assert finder.get_object_id("Barnard 53") == object_of(db, "B", 53)
    assert finder.get_object_id("NGC0869") == object_of(db, "NGC", 869)
    assert finder.get_object_id("Sh2-155") == object_of(db, "Sh2", 155)


def test_resolve_tells_designations_from_other_names(db):
    finder = ObjectFinder(db)
    assert finder.resolve("NGC 884") == (True, object_of(db, "NGC", 884))
    assert finder.resolve("NGC 9999") == (True, None)
    assert finder.resolve("The Double Cluster") == (False, None)
    assert finder.resolve("UGC 10814") == (False, None)
    assert finder.resolve("NGC 4676A") == (False, None)


# --- Precedence ----------------------------------------------------------------


def test_a_later_loader_fills_an_empty_magnitude(db, finder):
    listing("C", 37, "Open Cluster", 302.92, 26.55, ["NGC 6885"], mag=[5.9]).insert()
    assert mags(db, "NGC", 6885) == [5.9]


def test_a_later_loader_never_replaces_a_magnitude(db, finder):
    listing("Col", 24, "OC", 34.75, 57.13, ["NGC 869"], mag=[4.3]).insert()
    assert mags(db, "NGC", 869) == [5.3]


def test_the_first_fill_stands(db, finder):
    listing("Col", 417, "OC", 302.92, 26.55, ["NGC 6885"], mag=[8.1]).insert()
    listing("Lyn", 884, "OC", 302.92, 26.55, ["NGC 6885"], mag=[7.0]).insert()
    assert mags(db, "NGC", 6885) == [8.1]


def test_a_listing_without_a_magnitude_leaves_it(db, finder):
    listing("C", 37, "Open Cluster", 302.92, 26.55, ["NGC 6885"]).insert()
    assert mags(db, "NGC", 6885) == []


def test_a_later_loader_fills_an_empty_size_and_never_replaces_one(db, finder):
    listing("Col", 8, "OC", 13.2, 56.63, ["IC 1590"], size=(25.0, 30.0)).insert()
    listing("Col", 24, "OC", 34.75, 57.13, ["NGC 869"], size=(30.0,)).insert()
    assert size_arcmin(db, "IC", 1590) == [25.0, 30.0]
    assert size_arcmin(db, "NGC", 869) == [18.0]


def test_a_listing_of_a_group_fills_nothing(db, finder):
    # TAAS's "2237;2244" carries the cluster's 4.8, no value of the nebula.
    group = listing(
        "Ta2", 52, "Gas. Neb.+OC", 302.92, 26.55, ["NGC 6885", "NGC 869"], mag=[4.8]
    )
    group.size = SizeObject.from_arcmin(90.0)
    assert joins(db, group, "NGC", 6885)
    assert mags(db, "NGC", 6885) == []
    assert size_arcmin(db, "NGC", 6885) == []


def test_harris_replaces_a_globulars_magnitude(db, finder):
    listing("Har", 112, "Gb", 264.65, -23.91, ["NGC 6401"], mag=[9.45]).insert()
    assert mags(db, "NGC", 6401) == [9.45]


def test_harris_without_a_magnitude_leaves_it(db, finder):
    listing("Har", 112, "Gb", 264.65, -23.91, ["NGC 6401"]).insert()
    assert mags(db, "NGC", 6401) == [7.4]


def test_egc_sets_globular_on_an_object_it_joins(db, finder):
    listing("EGC", 2, "Gb", 76.27, -69.41, ["NGC 1835"], mag=[9.0]).insert()
    obj = sky_object(db, "NGC", 1835)
    assert obj["obj_type"] == "Gb"
    assert mags(db, "NGC", 1835) == [9.8]


def test_type_and_position_are_the_first_loaders(db, finder):
    listing("Col", 417, "Gb", 302.95, 26.5, ["NGC 6885"]).insert()
    obj = sky_object(db, "NGC", 6885)
    assert (obj["obj_type"], obj["ra"], obj["dec"]) == ("Ast", 302.92, 26.55)


def test_a_minted_object_keeps_its_own_values(db, finder):
    listing("C", 41, "Open Cluster", 66.75, 16.0, [], mag=[0.5], size=(330,)).insert()
    obj = sky_object(db, "C", 41)
    assert (obj["obj_type"], obj["ra"], obj["dec"]) == ("Open Cluster", 66.75, 16.0)
    assert mags(db, "C", 41) == [0.5]
    assert size_arcmin(db, "C", 41) == [330.0]


# --- Names: only the akas that resolve to the listing's sky object --------------


def test_a_members_number_is_not_a_name_of_its_sibling(db, finder):
    double_cluster = listing(
        "Ta2",
        21,
        "OC + OC",
        34.75,
        57.13,
        ["NGC 869", "NGC 884", "The Double Cluster"],
    )
    assert joins(db, double_cluster, "NGC", 869)
    assert names(db, "NGC", 869) == [
        "NGC 869",
        "Ta2 21",
        "NGC 869",
        "The Double Cluster",
    ]
    assert names(db, "NGC", 884) == ["NGC 884"]


def test_common_names_and_other_catalogs_numbers_are_kept(db, finder):
    listing(
        "Sh2", 125, "Nb", 314.75, 44.33, ["NGC 7000", "UGC 1", "SIMEIS 147"]
    ).insert()
    assert names(db, "NGC", 7000)[1:] == ["Sh2 125", "NGC 7000", "UGC 1", "SIMEIS 147"]


def test_on_a_joined_object_a_designation_resolving_to_nothing_is_dropped(db, finder):
    listing("Ta2", 99, "Galaxy", 41.58, -30.27, ["NGC 1097", "NGC 9999"]).insert()
    assert names(db, "NGC", 1097) == ["NGC 1097", "Ta2 99", "NGC 1097"]


def test_a_minted_object_keeps_a_designation_resolving_to_nothing(db, finder):
    listing("Ta2", 98, "Galaxy", 60.0, 10.0, ["NGC 9999"]).insert()
    assert names(db, "Ta2", 98) == ["Ta2 98", "NGC 9999"]


def test_without_matching_every_aka_is_a_name(db, finder):
    # find_object_id=False is the WDS path: no lookup, so no name is judged.
    listing("WDS", 1, "D*", 34.75, 57.13, ["NGC 884", "STF 1"]).insert(
        find_object_id=False
    )
    assert names(db, "WDS", 1) == ["WDS 1", "NGC 884", "STF 1"]


# --- Lettered components (the Arp loader only) ---------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("NGC 4676A", ("NGC", 4676, "A")),
        ("NGC4676B", ("NGC", 4676, "B")),
        ("IC 1623 a", ("IC", 1623, "A")),
        ("M51A", ("M", 51, "A")),
        ("NGC 0341A", ("NGC", 341, "A")),
        ("NGC 4676", None),
        ("UGC 10814A", None),
        ("h 2827A", None),
        ("MCG-02-13-040A", None),
        ("The Mice", None),
    ],
)
def test_parse_component(raw, expected):
    assert parse_component(raw) == expected


def arp(sequence, ra, dec, akas):
    return listing("Arp", sequence, "Gx", ra, dec, akas, lettered_components=True)


def test_an_a_component_resolves_to_its_number(db, finder):
    assert joins(db, arp(242, 191.54, 30.72, ["NGC 4676A", "NGC 4676B"]), "NGC", 4676)
    # NGC 4676B is the other galaxy of the pair: not a name of NGC 4676.
    assert names(db, "NGC", 4676) == ["NGC 4676", "Arp 242", "NGC 4676A"]


def test_m51a_is_m_51_and_m51b_is_not(db, finder):
    assert joins(db, arp(85, 202.47, 47.18, ["M51A", "M51B"]), "M", 51)
    assert "M51B" not in names(db, "M", 51)


def test_beside_its_number_an_a_component_is_a_companion(db, finder):
    arp_77 = arp(77, 41.54, -30.27, ["NGC 1097A", "NGC 1097"])
    assert joins(db, arp_77, "NGC", 1097)
    assert names(db, "NGC", 1097) == ["NGC 1097", "Arp 77", "NGC 1097"]


def test_any_other_letter_is_a_galaxy_of_its_own(db, finder):
    arp_79 = arp(79, 212.53, 17.6, ["NGC 5490C"])
    assert not joins(db, arp_79, "NGC", 5490)
    assert names(db, "Arp", 79) == ["Arp 79", "NGC 5490C"]


def test_other_loaders_read_lettered_akas_as_plain_names(db, finder):
    pair = listing("Ta2", 97, "Galaxy", 191.54, 30.72, ["NGC 4676A"])
    assert not joins(db, pair, "NGC", 4676)
    assert names(db, "Ta2", 97) == ["Ta2 97", "NGC 4676A"]


# --- Loaders --------------------------------------------------------------------


def test_collinder_and_sharpless_load_before_caldwell():
    order = [function for _, function in catalog_import_main.CATALOG_LOADERS]
    assert order[0] == "load_ngc_catalog"
    assert order.index("load_collinder") < order.index("load_caldwell")
    assert order.index("load_sharpless") < order.index("load_caldwell")


@pytest.mark.parametrize(
    "other_name, akas",
    [
        ("NGC 188", ["NGC 188"]),
        ("IC 342", ["IC 342"]),
        ("NGC 869/884", ["NGC 869", "NGC 884"]),
        ("NGC 6992/5", ["NGC 6992", "NGC 6995"]),
        ("NGC 2237-9", ["NGC 2237", "NGC 2239"]),
        ("Sh2-155", ["Sh2-155"]),
        ("none", []),
        ("  none\n", []),
        ("", []),
    ],
)
def test_caldwell_other_names(other_name, akas):
    assert caldwell_akas(other_name) == akas


def caldwell_line(sequence, other_name, obj_type, mag, size, ra_h, ra_m, sign, d, m):
    fields = [f"{sequence:>7}", other_name, obj_type, "Xxx", mag, f"Size: {size}"]
    return "\t".join(fields + [str(ra_h), str(ra_m), sign, str(d), str(m)]) + "\n"


@pytest.fixture
def astro_data(tmp_path, monkeypatch):
    path = tmp_path / "astro_data"
    path.mkdir()
    monkeypatch.setattr(utils, "astro_data_dir", path)
    return path


def test_load_caldwell(db, astro_data, monkeypatch):
    (astro_data / "caldwell.desc").write_text("Caldwell")
    (astro_data / "caldwell.dat").write_text(
        caldwell_line(
            9, "Sh2-155", "Bright Nebula", "--", "50 x 10", 22, 57.0, "+", 62, 37
        )
        + caldwell_line(
            14, "NGC 869/884", "Open Cluster", "4.3", "30 and 30", 2, 20, "+", 57, 8
        )
        + caldwell_line(
            37, "NGC 6885", "Open Cluster", "5.9", "7", 20, 11.7, "+", 26, 33
        )
        + caldwell_line(41, "none", "Open Cluster", "0.5", "330", 4, 27, "+", 16, 0)
    )
    monkeypatch.setattr(caldwell_loader, "objects_db", db)
    caldwell_loader.load_caldwell()

    assert object_of(db, "C", 9) == object_of(db, "Sh2", 155)
    assert names(db, "Sh2", 155) == ["Sh2 155", "C 9", "Sh2-155"]
    assert object_of(db, "C", 14) == object_of(db, "NGC", 869)
    assert "NGC 884" not in names(db, "NGC", 869)
    assert mags(db, "NGC", 6885) == [5.9]
    assert names(db, "C", 41) == ["C 41"]
    assert ciu.MATCH_REJECTIONS == []


def test_load_barnard_types_dark_nebulae(db, astro_data, monkeypatch):
    barnard = astro_data / "barnard"
    barnard.mkdir()
    (barnard / "barnard.desc").write_text("Barnard")
    (barnard / "barnard.dat").write_text(
        "  33  5 38 18 - 2 30   5 40 59  - 2 28   4.\n"
        "  33a 5 38 18 - 2 30   5 40 59  - 2 28   4.\n"
    )
    (barnard / "notes.dat").write_text("  33  Horsehead\n")
    monkeypatch.setattr(specialized_loaders, "objects_db", db)
    specialized_loaders.load_barnard()

    obj = sky_object(db, "B", 33)
    assert obj["obj_type"] == "DN"
    assert size_arcmin(db, "B", 33) == [4.0]


def test_load_arp_reads_lettered_components(db, astro_data, monkeypatch):
    arp_path = astro_data / "arp"
    arp_path.mkdir()
    (arp_path / "arp.desc").write_text("Arp")
    (arp_path / "arp_comments.csv").write_text("arp_number,names,comment\n")
    conn = sqlite3.connect(arp_path / "arp.sqlite")
    conn.execute(
        "CREATE TABLE cat (ra REAL, dec REAL, magnitude REAL, name TEXT,"
        " catalog_identifier TEXT)"
    )
    conn.executemany(
        "INSERT INTO cat VALUES (?, ?, ?, ?, ?)",
        [
            (191.54, 30.72, 13.0, "NGC 4676A", "242"),
            (191.54, 30.72, 13.0, "NGC 4676B", "242"),
            (41.54, -30.27, 9.2, "NGC 1097A", "77"),
            (41.54, -30.27, 9.2, "NGC 1097", "77"),
            (212.53, 17.6, 13.9, "NGC 5490C", "79"),
            (5.40, -22.40, 13.0, "NGC 0091", "65"),
        ],
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(specialized_loaders, "objects_db", db)
    specialized_loaders.load_arp()

    assert object_of(db, "Arp", 242) == object_of(db, "NGC", 4676)
    assert object_of(db, "Arp", 77) == object_of(db, "NGC", 1097)
    assert names(db, "NGC", 1097) == ["NGC 1097", "Arp 77", "NGC 1097"]
    assert names(db, "Arp", 79) == ["Arp 79", "NGC 5490C"]
    assert [rejection.listing for rejection in ciu.MATCH_REJECTIONS] == ["Arp 65"]


# --- Declinations between -1° and 0° ----------------------------------------
#
# Each loader below once negated the degrees and lost the sign of "-00". The
# fixtures are the sources' own rows for the case.


def test_harris_keeps_the_sign_of_a_declination_just_south_of_the_equator(tmp_path):
    from PiFinder.catalog_imports.harris_loader import (
        create_cluster_object,
        read_harris_catalog,
    )

    # The position columns of three rows of astro_data/harris/catalog.
    catalog = tmp_path / "catalog"
    catalog.write_text(
        " NGC 104   47 Tuc      00 24 05.2  -72 04 51  305.90 -44.89\n"
        " NGC 6535              18 03 50.7  -00 17 49   27.18  10.44\n"
        " NGC 7089  M 2         21 33 29.3  -00 49 23   53.38 -35.78\n"
    )
    decs = [
        create_cluster_object(entry, seq)["dec"]
        for seq, entry in enumerate(read_harris_catalog(catalog), 1)
    ]
    assert decs == pytest.approx(
        [-(72 + 4 / 60 + 51 / 3600), -(17 / 60 + 49 / 3600), -(49 / 60 + 23 / 3600)]
    )


def test_lynga_keeps_the_sign_of_a_declination_just_south_of_the_equator(tmp_path):
    from PiFinder.catalog_imports.lynga_loader import (
        create_cluster_object,
        read_lynga_catalog,
    )

    # Lyn 229, astro_data/lynga/catalog line 229.
    catalog = tmp_path / "catalog"
    catalog.write_text(
        " 3  24  637.8-0054  635.2-0052 .51 -.5212.18 -3.46 241 539  10.  419"
        "                                     0 0 0 0 0 0 0 0\n"
    )
    (entry,) = read_lynga_catalog(catalog)
    assert create_cluster_object(entry, 229)["dec"] == pytest.approx(-54 / 60)


def test_load_taas200_keeps_the_sign_of_s00(db, astro_data, monkeypatch):
    (astro_data / "taas200.desc").write_text("TAAS 200")
    (astro_data / "TAAS_200.csv").write_text(
        "Nr,NGC/IC,Name,Type,Const,RA Hr,RA Min,Dec Deg,Dec Min,Magnitude,Size,"
        "GC Conc or Class,# Stars,Min Aperture,Herschel 400,Description\n"
        '129,4666,,eg,VIR,12,45.1,s00,28,10.8,4.5\'x1.5,Sc,,"4 in, 25X",Y,"Edge-on"\n'
        '130,,,eg,VIR,12,45.1,s00,28,10.8,,,,,,""\n'
    )
    monkeypatch.setattr(specialized_loaders, "objects_db", db)
    specialized_loaders.load_taas200()

    # At +00 28 it lay 56' from NGC 4666, and the match guard refused it.
    assert object_of(db, "Ta2", 129) == object_of(db, "NGC", 4666)
    assert ciu.MATCH_REJECTIONS == []
    assert sky_object(db, "Ta2", 130)["dec"] == pytest.approx(-28 / 60)


def test_load_barnard_keeps_the_sign_of_minus_0(db, astro_data, monkeypatch):
    barnard = astro_data / "barnard"
    barnard.mkdir()
    (barnard / "barnard.desc").write_text("Barnard")
    (barnard / "barnard.dat").write_text(
        " 326 18 57    -00 34  19  3     - 0 23  20.\n"
    )
    (barnard / "notes.dat").write_text(" 326  Narrow; 25' long E and W; 3' wide\n")
    monkeypatch.setattr(specialized_loaders, "objects_db", db)
    specialized_loaders.load_barnard()

    assert sky_object(db, "B", 326)["dec"] == pytest.approx(-23 / 60)


def test_load_collinder_keeps_the_sign_of_minus_00(db, astro_data, monkeypatch):
    (astro_data / "collinder.desc").write_text("Collinder")
    (astro_data / "collinder.txt").write_text(
        "Col #\tNGC/Other Cat.\tCon\tRA\tDEC\tm (v/p)\t# Stars\tSize\tClass\tn\n"
        "401\t \tAql\t19h 38m 24.0s\t-00\u00ba 20' 00\"\t7p\t8\u00b1\t1\t\u03bcNorm\t \n"
    )
    (astro_data / "collinder2.txt").write_text(
        "Collinder number\tNGC/IC number\tOther names\tImage\tObject type"
        "\tConstellation\tApparent magnitude\n"
        "Cr 401\t-\t\t\tOpen cluster\tAquila\t7.0\n"
    )
    monkeypatch.setattr(specialized_loaders, "objects_db", db)
    specialized_loaders.load_collinder()

    assert sky_object(db, "Col", 401)["dec"] == pytest.approx(-20 / 60)


def test_load_caldwell_keeps_the_sign_of_minus_0(db, astro_data, monkeypatch):
    (astro_data / "caldwell.desc").write_text("Caldwell")
    (astro_data / "caldwell.dat").write_text(
        caldwell_line(200, "none", "Open Cluster", "5.0", "5", 12, 30.0, "-", 0, 30)
    )
    monkeypatch.setattr(caldwell_loader, "objects_db", db)
    caldwell_loader.load_caldwell()

    assert sky_object(db, "C", 200)["dec"] == pytest.approx(-0.5)
