"""Tests for the Named Stars catalog: every IAU-named Hipparcos star (#670).

The loader reads the WGSN's table and Hipparcos, and the star-identity stage
joins each listing to its star by its HIP number, never by position
(docs/ax/catalog.md §9.3). The sky objects are built in a small objects DB
here, never the committed one.
"""

import math
import re

import numpy as np
import pytest

import PiFinder.catalog_imports.catalog_import_utils as ciu
import PiFinder.catalog_imports.named_stars_loader as named_stars_loader
from PiFinder.catalog_imports.corrections import CorrectionError
from PiFinder.catalog_imports.named_stars_loader import (
    CATALOG_CODE,
    DESCRIPTION_PATH,
    load_named_stars,
    named_star_listings,
)
from PiFinder.catalog_imports.star_identity import (
    Hipparcos,
    identify_stars,
    load_hipparcos,
)
from PiFinder.catalog_imports.supplementary_sources import (
    WGSN_PATH,
    add_wgsn_names,
    read_wgsn,
)
from PiFinder.catalogs import Catalogs
from PiFinder.composite_object import MagnitudeObject, SizeObject
from PiFinder.db.objects_db import ObjectsDatabase

pytestmark = pytest.mark.unit

ARCMIN = 1 / 60

VEGA, MIZAR, IZAR, LONE, NO_V = 91262, 65378, 72105, 1, 2
HIPPARCOS = Hipparcos(
    hip=np.array([LONE, NO_V, MIZAR, IZAR, VEGA]),
    ra=np.array([10.0, 20.0, 200.98, 221.2467, 279.2347]),
    dec=np.array([-10.0, -20.0, 54.925, 27.0742, 38.7837]),
    vmag=np.array([5.0, np.nan, 2.27, 2.35, 0.03]),
    var_flag=np.zeros(5, dtype=int),
    # Mizar's and Izar's V are their pairs' combined light.
    own_vmag=np.array([True, True, False, False, True]),
)


def write_wgsn(tmp_path, *rows):
    """A WGSN table of (name, HIP or None) rows, as extract.py writes it."""
    path = tmp_path / "iau_csn.tsv"
    lines = ["name\twgsn_id\tdesignation\thip\tbayer_id\tconstellation\tadopted"]
    for name, hip in rows:
        lines.append(f"{name}\t1\tHR 1\t{hip or ''}\t\tLyr\t2016/06/30")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def db(tmp_path, monkeypatch):
    """An empty objects DB, set as the import's objects_db."""
    ciu.STAND_IN_POSITIONS.clear()
    ciu.SAC_SYSTEMS.clear()
    ciu.SOURCE_DM_NUMBERS.clear()
    ciu.STAR_HIPS.clear()
    db = ObjectsDatabase(tmp_path / "objects.db")
    db.create_tables()
    monkeypatch.setattr(ciu, "objects_db", db)
    monkeypatch.setattr(named_stars_loader, "objects_db", db)
    for code in ("SaM", "Str", "WDS"):
        db.insert_catalog(code, 100000, code)
    yield db
    db.conn.close()
    ciu.STAR_HIPS.clear()


def add(db, code, sequence, obj_type, ra, dec, mag=(), names=()):
    """A sky object of one listing, named as the loaders name it."""
    object_id = db.insert_object(
        obj_type,
        ra,
        dec,
        "UMa",
        SizeObject([]).to_json(),
        MagnitudeObject(list(mag)).to_json(),
    )
    db.insert_catalog_object(object_id, code, sequence, "")
    db.insert_name(object_id, f"{code} {sequence}", code)
    for name in names:
        db.insert_name(object_id, name, code)
    return object_id


def object_of(db, code, sequence):
    row = db.conn.execute(
        "SELECT object_id FROM catalog_objects WHERE catalog_code = ? AND sequence = ?",
        (code, sequence),
    ).fetchone()
    return row["object_id"]


def names_of(db, object_id):
    return [
        row["common_name"]
        for row in db.conn.execute(
            "SELECT common_name FROM names WHERE object_id = ? ORDER BY id",
            (object_id,),
        )
    ]


def sky_object(db, object_id):
    return db.conn.execute(
        "SELECT * FROM objects WHERE id = ?", (object_id,)
    ).fetchone()


# --- The loader ------------------------------------------------------------------


def test_one_listing_per_hip_number_numbered_by_it(tmp_path):
    path = write_wgsn(
        tmp_path,
        ("Vega", VEGA),
        ("Izar", IZAR),
        ("Pulcherrima", IZAR),
        ("WASP-1", None),
        ("Mizar", MIZAR),
    )
    listings = named_star_listings(HIPPARCOS, path)
    assert [listing.sequence for listing in listings] == [MIZAR, IZAR, VEGA]
    assert {listing.catalog_code for listing in listings} == {CATALOG_CODE}
    assert {listing.object_type for listing in listings} == {"*"}
    # The listing carries no names: the WGSN source gives them.
    assert all(listing.aka_names == [] for listing in listings)


def test_a_listing_lies_at_its_hipparcos_position_at_j2000(tmp_path):
    (vega,) = named_star_listings(HIPPARCOS, write_wgsn(tmp_path, ("Vega", VEGA)))
    assert (vega.ra, vega.dec) == (279.2347, 38.7837)


def test_the_real_listings_lie_at_hipparcos_j2000():
    hipparcos = load_hipparcos()
    listings = {listing.sequence: listing for listing in named_star_listings(hipparcos)}
    # Arcturus in hip_main.dat: 213.91811403 +19.18726997 at J1991.25, moving
    # -1093.45 and -1999.40 mas/yr; 8.75 years carry it about 20".
    years, mas = 8.75, 3.6e6
    dec = 19.18726997 - 1999.40 * years / mas
    ra = 213.91811403 - 1093.45 * years / mas / math.cos(math.radians(19.18726997))
    assert (listings[69673].ra, listings[69673].dec) == pytest.approx((ra, dec))
    index = hipparcos.index_of(VEGA)
    assert (listings[VEGA].ra, listings[VEGA].dec) == (
        hipparcos.ra[index],
        hipparcos.dec[index],
    )


def test_v_is_the_stars_own_or_its_systems_combined_light(tmp_path):
    path = write_wgsn(tmp_path, ("Vega", VEGA), ("Mizar", MIZAR), ("None", NO_V))
    mags = {
        listing.sequence: listing.mag.mags
        for listing in named_star_listings(HIPPARCOS, path)
    }
    # Mizar's 2.27 is the pair's light: what a finder shows of a star listed
    # alone. A star Hipparcos gives no V for has none.
    assert mags == {VEGA: [0.03], MIZAR: [2.27], NO_V: []}


def test_a_hip_number_hipparcos_lacks_fails(tmp_path):
    with pytest.raises(ValueError, match="HIP 999999"):
        named_star_listings(HIPPARCOS, write_wgsn(tmp_path, ("Nobody", 999999)))


def test_the_catalog_description_counts_the_wgsn_table():
    names = read_wgsn()
    hips = {name.hip for name in names if name.hip is not None}
    text = DESCRIPTION_PATH.read_text()
    with_hip = sum(name.hip is not None for name in names)
    without = len(names) - with_hip
    assert re.search(rf"\b{len(hips)} stars carry {with_hip} names\b", text)
    assert re.search(rf"\b{without} names of objects without", text)


# --- Identity: a listing is its HIP number ---------------------------------------


def load(db, tmp_path, *rows):
    db.insert_catalog(CATALOG_CODE, 0, "")
    load_named_stars(HIPPARCOS, write_wgsn(tmp_path, *rows))


def test_a_listing_joins_the_star_other_catalogs_list(db, tmp_path):
    # Mizar's listings in Str, SAC and WDS are one star, and the Named Stars
    # listing joins it: the first loader's sky object survives.
    str_mizar = add(db, "Str", 56, "*", 200.975, 54.925, mag=[2.2], names=["Mizar"])
    sam = add(db, "SaM", 2054, "D*", 200.975, 54.9333, mag=[2.3, 4.0])
    wds = add(db, "WDS", 70779, "D*", 200.98, 54.925, mag=[2.2, 3.9])
    load(db, tmp_path, ("Mizar", MIZAR))
    named = object_of(db, CATALOG_CODE, MIZAR)
    result = identify_stars(db, {}, hipparcos=HIPPARCOS)
    assert result.matches[named].rule == "HIP number"
    assert result.merged_into == {sam: str_mizar, wds: str_mizar, named: str_mizar}
    assert result.hips == {str_mizar: MIZAR}
    assert object_of(db, CATALOG_CODE, MIZAR) == str_mizar
    # Typed by the D* rule; the survivor's V stands.
    assert sky_object(db, str_mizar)["obj_type"] == "D*"
    assert MagnitudeObject.from_json(sky_object(db, str_mizar)["mag"]).mags == [2.2]


def test_a_star_no_catalog_lists_is_a_sky_object_of_its_own(db, tmp_path):
    load(db, tmp_path, ("Lone", LONE))
    named = object_of(db, CATALOG_CODE, LONE)
    result = identify_stars(db, {}, hipparcos=HIPPARCOS)
    assert result.merged_into == {}
    assert result.hips == {named: LONE}


def test_a_listing_never_joins_by_position(db, tmp_path):
    # A Str listing on the star whose V fails the gate is not identified, so
    # the Named Stars listing does not join it: a miss is a `hip` correction.
    off = add(db, "Str", 1, "*", 10.0, -10.0, mag=[8.0])
    load(db, tmp_path, ("Lone", LONE))
    named = object_of(db, CATALOG_CODE, LONE)
    result = identify_stars(db, {}, hipparcos=HIPPARCOS)
    assert result.matches[off].hip is None
    assert result.merged_into == {}
    assert result.hips == {named: LONE}


def test_a_hip_correction_joins_a_missed_listing_to_it(db, tmp_path):
    off = add(db, "Str", 1, "*", 10.0, -10.0, mag=[8.0])
    load(db, tmp_path, ("Lone", LONE))
    named = object_of(db, CATALOG_CODE, LONE)
    result = identify_stars(db, {"Str 1": LONE}, hipparcos=HIPPARCOS)
    assert result.merged_into == {named: off}


def test_a_listing_takes_no_hip_correction(db, tmp_path):
    load(db, tmp_path, ("Lone", LONE))
    with pytest.raises(CorrectionError, match="numbered by its HIP"):
        identify_stars(db, {f"{CATALOG_CODE} {LONE}": VEGA}, hipparcos=HIPPARCOS)


def test_the_listings_change_no_other_match(db, tmp_path):
    def stars(database):
        add(database, "Str", 56, "*", 200.975, 54.925, mag=[2.2])
        add(database, "SaM", 1, "D*", 200.975, 54.925 + 2 * ARCMIN, mag=[2.3])
        add(database, "Str", 1, "*", 10.0, -10.0, mag=[8.0])

    def other_matches(database):
        result = identify_stars(database, {}, hipparcos=HIPPARCOS)
        return {
            oid: (match.hip, match.rule, match.reason)
            for oid, match in result.matches.items()
            if not result.stars[oid].listings[0].startswith(CATALOG_CODE)
        }

    without = ObjectsDatabase(tmp_path / "without.db")
    without.create_tables()
    for code in ("SaM", "Str", "WDS"):
        without.insert_catalog(code, 100000, code)
    stars(without)
    stars(db)
    load(db, tmp_path, ("Mizar", MIZAR), ("Lone", LONE))
    assert other_matches(db) == other_matches(without)
    without.conn.close()


def test_a_listing_that_shares_its_sky_object_fails(db, tmp_path):
    load(db, tmp_path, ("Lone", LONE))
    db.insert_catalog_object(object_of(db, CATALOG_CODE, LONE), "Str", 9, "")
    with pytest.raises(ValueError, match="shares its sky object"):
        identify_stars(db, {}, hipparcos=HIPPARCOS)


# --- Names -----------------------------------------------------------------------


def test_a_star_gets_its_iau_name_once(db, tmp_path):
    vega = add(db, "Str", 77, "*", 279.2347, 38.7837, mag=[0.0], names=["Vega"])
    path = write_wgsn(tmp_path, ("Vega", VEGA), ("Lone", LONE))
    db.insert_catalog(CATALOG_CODE, 0, "")
    load_named_stars(HIPPARCOS, path)
    lone = object_of(db, CATALOG_CODE, LONE)
    identify_stars(db, {}, hipparcos=HIPPARCOS)
    add_wgsn_names(db, path=path)
    assert names_of(db, vega) == ["Vega", "Str 77", f"{CATALOG_CODE} {VEGA}"]
    assert names_of(db, lone) == ["Lone", f"{CATALOG_CODE} {LONE}"]


def test_izar_keeps_its_names_and_gets_neither_iau_name(db, tmp_path):
    # HIP 72105 carries two IAU names, with no component to choose between
    # them: its listing is the pair's, and the older Izar stays.
    izar = add(db, "Str", 45, "*", 221.2467, 27.0742, mag=[2.4], names=["Izar"])
    path = write_wgsn(tmp_path, ("Izar", IZAR), ("Pulcherrima", IZAR))
    db.insert_catalog(CATALOG_CODE, 0, "")
    load_named_stars(HIPPARCOS, path)
    identify_stars(db, {}, hipparcos=HIPPARCOS)
    result = add_wgsn_names(db, path=path)
    assert names_of(db, izar) == ["Str 45", "Izar", f"{CATALOG_CODE} {IZAR}"]
    assert result.shared_hip == ["Izar", "Pulcherrima"]


# --- The real catalog ------------------------------------------------------------


class _Catalog:
    def __init__(self, objects):
        self.catalog_code = CATALOG_CODE
        self._objects = objects

    def is_selected(self):
        return True

    def get_objects(self):
        return self._objects


class _Object:
    def __init__(self, sequence, names):
        self.catalog_code = CATALOG_CODE
        self.sequence = sequence
        self.names = names


def test_search_finds_the_stars_no_other_catalog_lists(db):
    # The real table and Hipparcos, with no other catalog loaded: Miaplacidus,
    # Naos and Pherkad were in none.
    db.insert_catalog(CATALOG_CODE, 0, "")
    hipparcos = load_hipparcos()
    load_named_stars(hipparcos)
    identify_stars(db, {}, hipparcos=hipparcos)
    add_wgsn_names(db, path=WGSN_PATH)
    objects = [
        _Object(row["sequence"], names_of(db, row["object_id"]))
        for row in db.conn.execute(
            "SELECT sequence, object_id FROM catalog_objects WHERE catalog_code = ?",
            (CATALOG_CODE,),
        )
    ]
    catalogs = Catalogs([_Catalog(objects)])
    by_hip = {obj.sequence: obj for obj in objects}
    for name, hip in (("Miaplacidus", 45238), ("Naos", 39429), ("Pherkad", 75097)):
        assert hip in [obj.sequence for obj in catalogs.search_by_text(name)]
        assert by_hip[hip].names[0] == name
    # "Pherkad" also finds Pherkad Minor.
    assert {obj.sequence for obj in catalogs.search_by_text("Pherkad")} == {
        75097,
        74793,
    }
    # The keypad's text search finds an accented name by its ASCII form.
    assert [obj.sequence for obj in catalogs.search_by_text("Monch")] == [72339]
    assert len(objects) == len({n.hip for n in read_wgsn() if n.hip is not None})
