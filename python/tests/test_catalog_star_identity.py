"""Tests for star identity: the Hipparcos cross-match, the merge, the D* rule.

docs/ax/catalog.md §9.3, ADR 0046 decision 4 (the `hip` hook), #670 item 2.
The sky objects are built in a small objects DB here, and Hipparcos is a
handful of stars given directly, never the committed DB or hip_main.dat.
"""

import numpy as np
import pytest

import PiFinder.catalog_imports.catalog_import_utils as ciu
from PiFinder.catalog_imports import wds_loader
from PiFinder.catalog_imports.corrections import CorrectionError
from PiFinder.catalog_imports.star_identity import (
    Hipparcos,
    cross_match,
    identify_stars,
    load_hipparcos,
    read_star_objects,
)
from PiFinder.composite_object import MagnitudeObject, SizeObject
from PiFinder.db.objects_db import ObjectsDatabase

pytestmark = pytest.mark.unit

ARCMIN = 1 / 60

CODES = ("SaM", "SaR", "Str", "RDS", "TLK", "WDS", "NGC")


def hipparcos(*stars, var_flags=None):
    """Hipparcos stars as (hip, ra, dec, V)."""
    hip, ra, dec, vmag = (np.array(column) for column in zip(*stars))
    flags = np.array(var_flags or [0] * len(stars), dtype=int)
    return Hipparcos(
        hip=hip.astype(int),
        ra=ra.astype(float),
        dec=dec.astype(float),
        vmag=vmag.astype(float),
        var_flag=flags,
    )


# Three stars near Mizar's place, and one far away.
MIZAR, ALCOR, FAINT, FAR = 65378, 65477, 65400, 1
HIPPARCOS = hipparcos(
    (MIZAR, 200.98, 54.925, 2.23),
    (ALCOR, 201.31, 54.988, 3.99),
    (FAINT, 200.98, 54.925 + 1.5 * ARCMIN, 9.5),
    (FAR, 10.0, -10.0, 5.0),
)


@pytest.fixture
def db(tmp_path):
    # No listing's position is rounded unless a test says so.
    ciu.ROUNDED_POSITIONS.clear()
    db = ObjectsDatabase(tmp_path / "objects.db")
    db.create_tables()
    for code in CODES:
        db.insert_catalog(code, 100000, code)
    yield db
    db.conn.close()


def add(db, code, sequence, obj_type, ra, dec, mag=(), size_arcsec=(), names=()):
    """A sky object of one listing, named as the loaders name it."""
    object_id = db.insert_object(
        obj_type,
        ra,
        dec,
        "UMa",
        SizeObject.from_arcsec(*size_arcsec).to_json(),
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


def matches(db, stars=HIPPARCOS, **kwargs):
    found = cross_match(read_star_objects(db.conn.cursor(), set()), stars, **kwargs)
    return {object_id: match.hip for object_id, match in found.items()}


# --- The cross-match -----------------------------------------------------------


def test_the_nearest_star_within_3_arcmin_matches(db):
    # SAC rounds to 0.1m of RA and 1' of Dec: Mizar lies 1.2' off.
    sam = add(db, "SaM", 2054, "D*", 200.975, 54.9333, mag=[2.3, 4.0])
    assert matches(db) == {sam: MIZAR}


def test_nothing_within_the_radius_is_no_match(db):
    lone = add(db, "Str", 1, "*", 200.975, 54.925 + 3.5 * ARCMIN, mag=[2.3])
    assert matches(db) == {lone: None}


def test_sac_matches_within_6_arcmin(db):
    # SAC gives some RAs to the whole minute: α Her's "17 15" lies 5.8' off.
    near = add(db, "SaM", 958, "D*", 200.975, 54.925 + 5.5 * ARCMIN, mag=[2.3])
    sar = add(db, "SaR", 1, "*", 200.975, 54.925 + 5.5 * ARCMIN, mag=[2.3])
    far = add(db, "SaM", 1, "D*", 200.975, 54.925 + 6.5 * ARCMIN, mag=[2.3])
    rds = add(db, "RDS", 1, "D*", 200.975, 54.925 + 5.5 * ARCMIN, mag=[2.3])
    assert matches(db) == {near: MIZAR, sar: MIZAR, far: None, rds: None}


def test_the_v_gate_passes_over_a_star_of_another_magnitude(db):
    # A 9.6 mag double 0.1' from the 9.5 mag star, 1.4' from Mizar.
    near_faint = add(db, "SaM", 1, "D*", 200.98, 54.925 + 1.4 * ARCMIN, mag=[9.6])
    # A 2.2 mag listing 0.2' from the faint star still finds Mizar, 1.3' off.
    bright = add(db, "Str", 56, "*", 200.98, 54.925 + 1.3 * ARCMIN, mag=[2.2])
    found = cross_match(read_star_objects(db.conn.cursor(), set()), HIPPARCOS)
    assert found[near_faint].hip == FAINT
    assert found[bright].hip == MIZAR
    assert found[bright].rejected_by_v == (FAINT, pytest.approx(0.2), 9.5)


def test_v_outside_1_mag_of_every_star_is_no_match(db):
    off = add(db, "SaR", 1, "*", 200.98, 54.925, mag=[5.5])
    found = cross_match(read_star_objects(db.conn.cursor(), set()), HIPPARCOS)
    assert found[off].hip is None
    assert found[off].rejected_by_v == (MIZAR, pytest.approx(0.0), 2.23)


def test_a_listing_without_a_magnitude_matches_by_position(db):
    # ν Sco's AC row gives no magnitude for the star.
    ac = add(db, "SaM", 1772, "D*", 200.98, 54.925 + 0.2 * ARCMIN)
    assert matches(db) == {ac: MIZAR}


def test_of_several_candidates_the_nearest_wins(db):
    stars = hipparcos(
        (10, 50.0, 20.0 + 1.0 * ARCMIN, 6.0), (11, 50.0, 20.0 + 2.0 * ARCMIN, 6.2)
    )
    listing = add(db, "SaM", 1, "D*", 50.0, 20.0, mag=[6.1])
    found = cross_match(read_star_objects(db.conn.cursor(), set()), stars)
    assert found[listing].hip == 10
    assert found[listing].candidates == 2


def test_a_tie_goes_to_the_lower_hip_number(db):
    stars = hipparcos(
        (12, 50.0, 20.0 + 1.0 * ARCMIN, 6.0), (11, 50.0, 20.0 - 1.0 * ARCMIN, 6.0)
    )
    listing = add(db, "SaM", 1, "D*", 50.0, 20.0, mag=[6.0])
    assert matches(db, stars) == {listing: 11}


def test_an_arcsecond_source_matches_within_half_an_arcminute(db):
    # A WDS pair 1' from a Hipparcos star is another star; SAC's 1' is rounding.
    wds = add(db, "WDS", 1, "D*", 200.98, 54.925 + 1.0 * ARCMIN, mag=[2.5])
    sam = add(db, "SaM", 1, "D*", 200.98, 54.925 + 1.0 * ARCMIN, mag=[2.5])
    close = add(db, "WDS", 2, "D*", 200.98, 54.925 + 0.4 * ARCMIN, mag=[2.5])
    assert matches(db) == {wds: None, sam: MIZAR, close: MIZAR}


def test_a_wds_row_placed_by_its_identifier_matches_within_3_arcmin(db):
    wds = add(db, "WDS", 1, "D*", 200.98, 54.925 + 1.0 * ARCMIN, mag=[2.5])
    stars = read_star_objects(db.conn.cursor(), rounded={("WDS", 1)})
    assert cross_match(stars, HIPPARCOS)[wds].hip == MIZAR
    stars = read_star_objects(db.conn.cursor(), rounded=set())
    assert cross_match(stars, HIPPARCOS)[wds].hip is None


def test_a_wider_radius_shows_what_lies_just_outside(db):
    lone = add(db, "Str", 1, "*", 200.975, 54.925 + 3.5 * ARCMIN, mag=[2.3])
    assert matches(db, radius_scale=2) == {lone: MIZAR}


def test_variables_are_matched_by_position(db):
    stars = hipparcos((10826, 34.8366, -2.9773, 6.47), var_flags=[3])
    # Mira: SAC gives its maximum, TLK its range, Hipparcos its mean V.
    sar = add(db, "SaR", 82, "*", 34.825, -2.9833, mag=[2.0])
    tlk = add(db, "TLK", 32, "*", 34.8367, -2.9778, mag=[2.0, 10.1])
    assert matches(db, stars) == {sar: 10826, tlk: 10826}


def test_a_variable_never_takes_a_listing_from_the_star_its_v_describes(db):
    # STF 2816: the 5.7 mag star lies 0.3' away, a large-amplitude variable
    # of V 8.1 0.14' away.
    stars = hipparcos(
        (106886, 324.7401, 57.4891, 5.74),
        (106890, 324.7454, 57.4874, 8.10),
        var_flags=[1, 3],
    )
    rds = add(db, "RDS", 78, "D*", 324.7454, 57.4850, mag=[5.5, 5.7, 7.5])
    found = cross_match(read_star_objects(db.conn.cursor(), set()), stars)
    assert found[rds].hip == 106886
    assert found[rds].rejected_by_v == (106890, pytest.approx(0.14, abs=0.01), 8.1)


def test_a_tlk_range_passes_a_star_within_1_mag_of_it(db):
    # A star of V 9.0 is nearer, but only the 5.5 one lies near TLK's range.
    stars = hipparcos(
        (1, 189.0, 45.44 + 0.1 * ARCMIN, 9.0), (2, 189.0, 45.44 + 0.3 * ARCMIN, 5.5)
    )
    tlk = add(db, "TLK", 1, "*", 189.0, 45.44, mag=[3.5, 4.6])
    assert matches(db, stars) == {tlk: 2}


def test_a_tlk_range_is_not_compared(db):
    # La Superba: TLK's range is photographic, Hipparcos's V 5.42.
    stars = hipparcos((62223, 189.0, 45.44, 5.42), var_flags=[2])
    tlk = add(db, "TLK", 19, "*", 189.0, 45.44, mag=[7.4, 10.0])
    assert matches(db, stars) == {tlk: 62223}


def test_only_the_star_catalogs_are_cross_matched(db):
    add(db, "NGC", 5055, "*", 200.98, 54.925, mag=[2.3])
    assert matches(db) == {}


# --- The `hip` hook ------------------------------------------------------------


def run(db, identifications=None, stars=HIPPARCOS):
    return identify_stars(db, identifications or {}, hipparcos=stars)


def test_a_hip_correction_identifies_a_listing_its_position_cannot(db):
    # SAC's α Mic is whole degrees off; its `hip` correction names the star.
    str_far = add(db, "Str", 1, "*", 10.0, -10.0, mag=[5.0])
    sam_off = add(db, "SaM", 1297, "D*", 13.0, -14.0, mag=[5.0])
    result = run(db, {"SaM 1297": FAR})
    assert object_of(db, "SaM", 1297) == str_far
    assert result.merged_into == {sam_off: str_far}
    assert result.matches[sam_off].by_correction


def test_a_hip_correction_the_cross_match_makes_is_redundant(db):
    add(db, "SaM", 2054, "D*", 200.975, 54.9333, mag=[2.3])
    with pytest.raises(CorrectionError, match="redundant"):
        run(db, {"SaM 2054": MIZAR})


def test_a_hip_correction_that_resolves_to_nothing_fails(db):
    add(db, "SaM", 2054, "D*", 200.975, 54.9333, mag=[2.3])
    with pytest.raises(CorrectionError, match="SaM 9999 resolves to nothing"):
        run(db, {"SaM 9999": MIZAR})


def test_a_hip_correction_needs_a_star_listing_and_a_hipparcos_star(db):
    add(db, "NGC", 5055, "*", 13.0, -14.0)
    add(db, "SaM", 1, "D*", 13.0, -14.0, mag=[5.0])
    with pytest.raises(CorrectionError) as error:
        run(db, {"NGC 5055": FAR, "SaM 1": 999999})
    assert error.value.problems == [
        "hip correction for NGC 5055: NGC 5055 is no star catalog's listing",
        "hip correction for SaM 1: Hipparcos has no HIP 999999",
    ]


def test_two_hip_corrections_for_one_sky_object_conflict(db):
    sam = add(db, "SaM", 1297, "D*", 13.0, -14.0, mag=[5.0])
    db.insert_catalog_object(sam, "RDS", 1, "")
    with pytest.raises(CorrectionError, match="conflicts with the hip correction"):
        run(db, {"SaM 1297": FAR, "RDS 1": MIZAR})


def test_a_failing_hip_correction_writes_nothing(db):
    add(db, "SaM", 2054, "D*", 200.975, 54.9333, mag=[2.3])
    add(db, "Str", 56, "*", 200.975, 54.9167, mag=[2.2])
    with pytest.raises(CorrectionError):
        run(db, {"SaM 9999": MIZAR})
    assert object_of(db, "SaM", 2054) != object_of(db, "Str", 56)


# --- Merging -------------------------------------------------------------------


def test_listings_of_one_star_become_one_sky_object(db):
    sam = add(db, "SaM", 2054, "D*", 200.975, 54.9333, mag=[2.3, 4.0])
    add(db, "Str", 56, "*", 200.975, 54.9167, mag=[2.2])
    add(db, "WDS", 70779, "D*", 200.981, 54.9254, mag=[2.23, 3.88])
    result = run(db)
    for code, sequence in (("SaM", 2054), ("Str", 56), ("WDS", 70779)):
        assert object_of(db, code, sequence) == sam
    assert result.hips == {sam: MIZAR}
    count = db.conn.execute("SELECT count(*) FROM objects").fetchone()[0]
    assert count == 1


def test_the_first_loaders_sky_object_survives_with_its_values(db):
    add(db, "SaM", 2054, "D*", 200.975, 54.9333, mag=[2.3, 4.0])
    add(db, "Str", 56, "*", 200.975, 54.9167, mag=[2.2])
    run(db)
    survivor = sky_object(db, "Str", 56)
    assert (survivor["ra"], survivor["dec"]) == (200.975, 54.9333)
    assert MagnitudeObject.from_json(survivor["mag"]).mags == [2.3, 4.0]


def test_names_follow_the_survivors_in_id_order(db):
    add(db, "SaM", 2054, "D*", 200.975, 54.9333, names=["Zeta UMa", "Mizar"])
    add(db, "Str", 56, "*", 200.975, 54.9167, names=["Mizar", "Zeta Ursae Majoris"])
    add(db, "WDS", 70779, "D*", 200.981, 54.9254, names=["WDS J13239+5456"])
    run(db)
    assert names(db, "SaM", 2054) == [
        "SaM 2054",
        "Zeta UMa",
        "Mizar",
        "Str 56",
        "Zeta Ursae Majoris",
        "WDS 70779",
        "WDS J13239+5456",
    ]


def test_an_empty_magnitude_or_size_is_filled_and_never_replaced(db):
    # ν Sco's AC row has no magnitude and comes first here; AB fills it.
    add(db, "SaM", 1772, "D*", 200.98, 54.925, size_arcsec=[41.1])
    add(db, "SaM", 1771, "D*", 200.98, 54.925, mag=[2.3, 6.8], size_arcsec=[0.9])
    add(db, "Str", 56, "*", 200.98, 54.925, mag=[2.2])
    run(db)
    survivor = sky_object(db, "SaM", 1772)
    assert MagnitudeObject.from_json(survivor["mag"]).mags == [2.3, 6.8]
    assert SizeObject.from_json(survivor["size"]).extents == [pytest.approx(41.1)]


def test_a_star_without_a_match_stays_its_own(db):
    lone = add(db, "SaM", 1, "D*", 100.0, 10.0, mag=[9.0])
    add(db, "SaM", 2, "D*", 100.0, 10.0, mag=[9.0])
    result = run(db)
    assert object_of(db, "SaM", 1) == lone != object_of(db, "SaM", 2)
    assert result.hips == {}


def test_a_merge_is_reproducible(tmp_path):
    def build(path):
        db = ObjectsDatabase(path)
        db.create_tables()
        for code in CODES:
            db.insert_catalog(code, 100000, code)
        add(db, "SaM", 2054, "D*", 200.975, 54.9333, names=["Mizar"])
        add(db, "WDS", 1, "D*", 200.981, 54.9254, names=["STF1744"])
        add(db, "Str", 56, "*", 200.975, 54.9167, names=["Mizar", "Zeta"])
        run(db)
        rows = db.conn.execute(
            "SELECT object_id, common_name, origin FROM names ORDER BY id"
        ).fetchall()
        db.conn.close()
        return [tuple(row) for row in rows]

    assert build(tmp_path / "a.db") == build(tmp_path / "b.db")


# --- The D* rule ---------------------------------------------------------------


def test_a_star_sac_or_rasc_lists_as_a_double_is_d_star(db):
    # Mintaka: the bright stars' * joins SAC's and RASC's doubles.
    add(db, "Str", 52, "*", 200.975, 54.9167, mag=[2.2])
    add(db, "RDS", 8, "D*", 200.975, 54.93, mag=[2.4, 2.4, 6.8])
    run(db)
    assert sky_object(db, "Str", 52)["obj_type"] == "D*"


def test_a_wds_double_makes_a_merged_star_d_star(db):
    # π¹ Gru: SAC's red star, and WDS's I 135.
    add(db, "SaR", 161, "*", 200.975, 54.9167, mag=[2.6])
    add(db, "WDS", 123434, "D*", 200.98, 54.925, mag=[2.3, 10.7])
    run(db)
    assert sky_object(db, "SaR", 161)["obj_type"] == "D*"


def test_a_star_wds_lists_only_with_optical_companions_is_single(db):
    add(db, "Str", 77, "*", 200.975, 54.9167, mag=[2.2])
    add(db, "TLK", 1, "*", 200.98, 54.925, mag=[2.0, 2.5])
    add(db, "WDS", 94640, "*", 200.98, 54.925, mag=[2.2, 9.5])
    run(db)
    assert sky_object(db, "Str", 77)["obj_type"] == "*"


def test_an_unmatched_listing_keeps_its_catalogs_type(db):
    add(db, "SaR", 1, "*", 100.0, 10.0, mag=[8.5])
    add(db, "SaM", 1, "D*", 101.0, 10.0, mag=[9.0])
    run(db)
    assert sky_object(db, "SaR", 1)["obj_type"] == "*"
    assert sky_object(db, "SaM", 1)["obj_type"] == "D*"


def wds_pair(components="AB", notes="N", sep=1.9, mag1=3.5, mag2=6.2):
    return {
        "Components": components,
        "Notes": notes,
        "Sep": np.float64(sep),
        "Mag_First": np.float64(mag1),
        "Mag_Second": np.float64(mag2),
    }


@pytest.mark.parametrize(
    "pair, double",
    [
        # Propus's BU 1008, with an orbit.
        (wds_pair(notes="NC"), True),
        (wds_pair(components=""), True),
        (wds_pair(components="Aa,Ab", sep=0.5), True),
        # Too close to split: Capella's, Algol's and Dschubba's pairs.
        (wds_pair(components="Aa,Ab", sep=0.33), False),
        (wds_pair(notes="NO", sep=0.076), False),
        # Flagged optical or dubious: Vega's H 5 39 (U), Arcturus's HDS 2003 (X).
        (wds_pair(notes="NL U"), False),
        (wds_pair(notes="NS"), False),
        (wds_pair(notes="X"), False),
        (wds_pair(notes="Y"), False),
        # Not the primary's pair: Vega's STF 3136 BC.
        (wds_pair(components="BC"), False),
        # A companion no observer looks for: Alphard's 9.7 at 284",
        # σ CMa's 14.2 at 11".
        (wds_pair(sep=284.4, mag1=2.0, mag2=9.7), False),
        (wds_pair(sep=11.1, mag1=3.5, mag2=14.2), False),
        (wds_pair(sep=np.nan), False),
        (wds_pair(mag2=np.nan), False),
        (wds_pair(mag1=np.nan, mag2=9.0), True),
    ],
)
def test_is_double_star_pair(pair, double):
    assert wds_loader.is_double_star_pair(pair) is double


# --- Reading hip_main.dat ------------------------------------------------------

# The first 14 fields of four rows of astro_data/hip_main.dat.
HIP_ROWS = [
    "H|       10826| |02 19 20.79|-02 58 37.4| 6.47|3|H|034.83661103|-02.97706055"
    "| |   7.79|   10.33| -239.48",
    "H|       55203| |11 18 11.24|+31 31 50.8| 3.79| |G|            |            "
    "| |       |        |        ",
    "H|       69673|H|14 15 40.35|+19 11 14.2|-0.05|1|G|213.91811403|+19.18726997"
    "|*|  88.85|-1093.45|-1999.40",
    "H|       91262| |18 36 56.19|+38 46 58.8| 0.03|1|G|279.23410832|+38.78299311"
    "| |128.93|  201.02|  287.46",
]


def test_load_hipparcos(tmp_path):
    path = tmp_path / "hip_main.dat"
    path.write_text("\n".join(HIP_ROWS) + "\n")
    stars = load_hipparcos(path)
    assert stars.hip.tolist() == [10826, 55203, 69673, 91262]
    assert stars.vmag.tolist() == [6.47, 3.79, -0.05, 0.03]
    assert stars.var_flag.tolist() == [3, 0, 1, 1]
    # Arcturus moves 2.3"/yr: 20" from 1991.25 to 2000.
    years = 2000 - 1991.25
    assert stars.dec[2] == pytest.approx(19.18726997 - 1999.40 * years / 3.6e6)
    assert stars.ra[2] == pytest.approx(
        213.91811403 - 1093.45 * years / 3.6e6 / np.cos(np.radians(19.18726997))
    )
    # ξ UMa has no astrometric solution: its sexagesimal position stands.
    assert stars.ra[1] == pytest.approx(15 * (11 + 18 / 60 + 11.24 / 3600))
    assert stars.dec[1] == pytest.approx(31 + 31 / 60 + 50.8 / 3600)
    assert stars.index_of(91262) == 3
    assert stars.index_of(1) is None


def test_the_stage_runs_between_post_processing_and_corrections():
    # catalog.md §9.1: after every loader and post-processing, before the
    # supplementary sources and corrections.
    import importlib
    import inspect

    main = importlib.import_module("PiFinder.catalog_imports.main")
    source = inspect.getsource(main.main)
    assert (
        source.index("POST_PROCESSING_FUNCTIONS")
        < source.index("identify_stars(")
        < source.index("apply_corrections(")
    )
