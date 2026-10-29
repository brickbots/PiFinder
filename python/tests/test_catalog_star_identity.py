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
    apply_identifier_rules,
    apply_vetoes,
    cross_match,
    double_star_designation,
    identify_stars,
    load_hipparcos,
    read_star_objects,
)
from PiFinder.composite_object import MagnitudeObject, SizeObject
from PiFinder.db.objects_db import ObjectsDatabase

pytestmark = pytest.mark.unit

ARCMIN = 1 / 60

CODES = ("SaM", "SaR", "Str", "RDS", "TLK", "WDS", "NGC")


def hipparcos(*stars, var_flags=None, numbers=None):
    """Hipparcos stars as (hip, ra, dec, V); `numbers` maps a HIP to its
    catalog numbers, such as {("HD", 12345)}."""
    hip, ra, dec, vmag = (np.array(column) for column in zip(*stars))
    flags = np.array(var_flags or [0] * len(stars), dtype=int)
    numbers = numbers or {}
    return Hipparcos(
        hip=hip.astype(int),
        ra=ra.astype(float),
        dec=dec.astype(float),
        vmag=vmag.astype(float),
        var_flag=flags,
        numbers_of={number: set(keys) for number, keys in numbers.items()},
        star_with={key: number for number, keys in numbers.items() for key in keys},
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
    # No loader records unless a test says so.
    ciu.STAND_IN_POSITIONS.clear()
    ciu.SAC_SYSTEMS.clear()
    ciu.SOURCE_DM_NUMBERS.clear()
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


def matches(db, stars=HIPPARCOS, stand_in=(), **kwargs):
    """Each sky object's match, after the vetoes, as its HIP or None."""
    found = cross_match(
        read_star_objects(db.conn.cursor(), set(stand_in)), stars, **kwargs
    )
    apply_vetoes(read_star_objects(db.conn.cursor(), set(stand_in)), found, stars)
    return {object_id: match.hip for object_id, match in found.items()}


def reasons(db, stars=HIPPARCOS):
    """Each sky object's reason for having no match."""
    star_objects = read_star_objects(db.conn.cursor(), set())
    found = cross_match(star_objects, stars)
    apply_vetoes(star_objects, found, stars)
    return {object_id: match.reason for object_id, match in found.items()}


# --- The cross-match -----------------------------------------------------------
#
# A match is made only where it is reliably right; a star the rules miss is
# matched by a `hip` correction (catalog.md §9.3).

ARCSEC = ARCMIN / 60


def test_the_one_star_within_3_arcmin_that_passes_the_v_gate_matches(db):
    # SAC rounds to 0.1m of RA and 1' of Dec: Mizar lies 1.2' off. The 9.5 mag
    # star 1.5' away fails the V gate.
    sam = add(db, "SaM", 2054, "D*", 200.975, 54.9333, mag=[2.3, 4.0])
    assert matches(db) == {sam: MIZAR}


def test_nothing_within_3_arcmin_is_no_match(db):
    # SAC's 3-6' rows are mostly stars Hipparcos lacks; those it has get a
    # hip correction.
    lone = add(db, "Str", 1, "*", 200.975, 54.925 + 3.5 * ARCMIN, mag=[2.3])
    sam = add(db, "SaM", 958, "D*", 200.975, 54.925 + 5.5 * ARCMIN, mag=[2.3])
    assert matches(db) == {lone: None, sam: None}


def test_the_v_gate_picks_the_star_of_the_listings_magnitude(db):
    near_faint = add(db, "SaM", 1, "D*", 200.98, 54.925 + 1.4 * ARCMIN, mag=[9.6])
    bright = add(db, "Str", 56, "*", 200.98, 54.925 + 1.3 * ARCMIN, mag=[2.2])
    assert matches(db) == {near_faint: FAINT, bright: MIZAR}


def test_v_outside_1_mag_of_every_star_is_no_match(db):
    off = add(db, "SaR", 1, "*", 200.98, 54.925, mag=[5.5])
    assert reasons(db) == {off: "V gate"}


def test_a_listing_without_a_magnitude_is_not_matched(db):
    # ν Sco's AC row gives no magnitude for the star; by position alone, 14 Aur
    # AC found its companion C.
    ac = add(db, "SaM", 1772, "D*", 200.98, 54.925 + 0.2 * ARCMIN)
    assert reasons(db) == {ac: "no V"}


def test_two_stars_that_pass_the_v_gate_are_no_match(db):
    # 61 Oph: both components have a Hipparcos entry, and SAC's rounded
    # position cannot tell them apart.
    stars = hipparcos(
        (86831, 50.0, 20.0 + 0.9 * ARCMIN, 6.16),
        (86835, 50.0, 20.0 + 0.76 * ARCMIN, 6.67),
    )
    sam = add(db, "SaM", 1380, "D*", 50.0, 20.0, mag=[6.2])
    assert reasons(db, stars) == {sam: "ambiguous"}


def test_an_arcsecond_source_matches_within_3_arcsec(db):
    # WDS and TLK place a star to the arcsecond: a pair 10" from a Hipparcos
    # star may be another star.
    wds = add(db, "WDS", 1, "D*", 200.98, 54.925 + 2 * ARCSEC, mag=[2.3])
    far = add(db, "WDS", 2, "D*", 200.98, 54.925 + 10 * ARCSEC, mag=[2.3])
    sam = add(db, "SaM", 1, "D*", 200.98, 54.925 + 1.0 * ARCMIN, mag=[2.3])
    assert matches(db) == {wds: MIZAR, far: None, sam: MIZAR}


def test_a_stand_in_position_is_not_matched(db):
    # A WDS row its identifier places, a SAC companion pair at its system's
    # position (ε Lyr's CD row lies at ε¹).
    wds = add(db, "WDS", 1, "D*", 200.98, 54.925, mag=[2.3])
    cd = add(db, "SaM", 1251, "D*", 200.98, 54.925, mag=[2.3])
    found = matches(db, stand_in={("WDS", 1), ("SaM", 1251)})
    assert found == {wds: None, cd: None}


def test_a_wider_radius_shows_what_lies_just_outside(db):
    lone = add(db, "Str", 1, "*", 200.975, 54.925 + 3.5 * ARCMIN, mag=[2.3])
    assert matches(db, radius_scale=2) == {lone: MIZAR}


def test_a_tlk_range_passes_a_star_within_1_mag_of_it(db):
    # A star of V 9.0 is nearer, but only the 5.5 one lies near TLK's range.
    stars = hipparcos(
        (1, 189.0, 45.44 + 1 * ARCSEC, 9.0), (2, 189.0, 45.44 + 2 * ARCSEC, 5.5)
    )
    tlk = add(db, "TLK", 1, "*", 189.0, 45.44, mag=[3.5, 4.6])
    assert matches(db, stars) == {tlk: 2}


def test_a_variable_whose_v_disagrees_is_not_matched(db):
    # Mira: SAC gives its maximum, Hipparcos its mean; La Superba: TLK's
    # range is photographic. Both are hip corrections.
    stars = hipparcos((10826, 34.8366, -2.9773, 6.47), (62223, 189.0, 45.44, 5.42))
    sar = add(db, "SaR", 82, "*", 34.825, -2.9833, mag=[2.0])
    tlk = add(db, "TLK", 19, "*", 189.0, 45.44, mag=[7.4, 10.0])
    assert reasons(db, stars) == {sar: "V gate", tlk: "V gate"}


def test_only_the_star_catalogs_are_cross_matched(db):
    add(db, "NGC", 5055, "*", 200.98, 54.925, mag=[2.3])
    assert matches(db) == {}


# --- The vetoes: a match must not contradict the listing's own designations ---

NUMBERED = hipparcos(
    (99649, 300.0, 30.0, 6.5),
    (99653, 300.0, 30.0 + 6 * ARCMIN, 6.6),
    numbers={99649: {("HD", 192422)}, 99653: {("HD", 192443)}},
)


def test_a_catalog_number_of_another_star_vetoes(db):
    # SaR 123 names HD 192443, which is HIP 99653, not the star 2' away.
    sar = add(
        db, "SaR", 123, "*", 300.0, 30.0 + 2 * ARCMIN, mag=[6.5], names=["HD 192443"]
    )
    assert reasons(db, NUMBERED) == {sar: "HD 192443 is HIP 99653"}


def test_a_catalog_number_the_star_has_confirms(db):
    sar = add(db, "SaR", 1, "*", 300.0, 30.0, mag=[6.5], names=["HD 192422"])
    assert matches(db, NUMBERED) == {sar: 99649}


def test_one_confirming_number_outweighs_a_wrong_one(db):
    # SaR 329: its HD is SAC's slip; its BD names the star.
    stars = hipparcos(
        (1, 300.0, 30.0, 6.5),
        (2, 300.0, 31.0, 6.5),
        numbers={1: {("BD", "+", 19, 4017)}, 2: {("HD", 183556)}},
    )
    sar = add(
        db, "SaR", 329, "*", 300.0, 30.0, mag=[6.5], names=["HD 183556", "BD +19 4017"]
    )
    assert matches(db, stars) == {sar: 1}


def test_a_catalog_number_hipparcos_lacks_vetoes(db):
    # SaR 306's HD 26748 is in no Hipparcos row: its star is not this one.
    sar = add(db, "SaR", 306, "*", 300.0, 30.0, mag=[6.5], names=["HD 26748"])
    assert reasons(db, NUMBERED) == {sar: "HD 26748 is no Hipparcos star's"}


def test_a_wds_designation_elsewhere_vetoes(db):
    # STF 1162's WDS listing lies 3.9' from the star a SAC row 1' off found.
    sam = add(
        db, "SaM", 554, "D*", 200.98, 54.925 + 1 * ARCMIN, mag=[2.3], names=["STF 1162"]
    )
    wds = add(
        db, "WDS", 1, "D*", 200.98, 54.925 + 3.9 * ARCMIN, mag=[9.0], names=["STF1162"]
    )
    found = reasons(db)
    assert found[sam] == "WDS STF 1162 is 3.9' from HIP 65378"
    assert found[wds] is not None


def test_a_wds_designation_on_another_star_vetoes(db):
    # SAC's h 4166 row found the 9.5 mag star; WDS's HJ 4166 is Mizar.
    sam = add(
        db, "SaM", 1, "D*", 200.98, 54.925 + 1.4 * ARCMIN, mag=[9.6], names=["h 4166"]
    )
    add(db, "WDS", 1, "D*", 200.98, 54.925, mag=[2.3], names=["HJ 4166"])
    assert reasons(db)[sam] == "WDS h 4166 is HIP 65378"


def test_a_wds_designation_on_the_star_confirms(db):
    # The WDS listing sits on the star, matched or not (here: no V).
    sam = add(
        db, "SaM", 1, "D*", 200.98, 54.925 + 1 * ARCMIN, mag=[2.3], names=["Howe 87"]
    )
    add(db, "WDS", 1, "D*", 200.98, 54.925 + 5 * ARCSEC, names=["HWE 87"])
    assert matches(db)[sam] == MIZAR


@pytest.mark.parametrize(
    "name, designation",
    [
        ("STF 362", "STF362"),
        ("STF1744", "STF1744"),
        ("h 4166", "HJ4166"),
        ("Howe 87", "HWE87"),
        ("Burnham 584", "BU584"),
        ("Stone 15", "STN15"),
        ("Sh 73", "SHJ73"),
        ("HD 60585", None),
        ("SAO 129835", None),
        ("SaM 1234", None),
        ("H 38", None),
        ("Alpha Her", None),
        ("41 Ari", None),
    ],
)
def test_double_star_designation(name, designation):
    assert double_star_designation(name) == designation


# --- Exact identifiers: for a star the position match leaves unmatched --------


def identified(db, stars=HIPPARCOS, dm_numbers=None, systems=None):
    """Each sky object's match after the identifier rules, and why not."""
    star_objects = read_star_objects(
        db.conn.cursor(), set(), dm_numbers or {}, systems or {}
    )
    found = cross_match(star_objects, stars)
    apply_vetoes(star_objects, found, stars)
    apply_identifier_rules(star_objects, found, stars)
    return found


# Mira, with its HD; a pair 15" apart, both in Hipparcos, for WDS and SAC.
IDENTIFIED = hipparcos(
    (10826, 34.8366, -2.9773, 6.47),
    (59272, 182.0, 20.0, 6.81),
    (59273, 182.0, 20.0 + 15 * ARCSEC, 6.65),
    (1, 182.0, 20.0 + 1.0 * ARCMIN, 6.8),
    numbers={
        10826: {("HD", 14386)},
        59272: {("HD", 105590), ("BD", "+", 20, 2700)},
        59273: {("HD", 105591), ("BD", "+", 20, 2701)},
        1: {("BD", "+", 20, 2702)},
    },
)


def test_a_catalog_number_identifies_a_star_the_v_gate_turned_away(db):
    # Mira's SAC red-star row gives its maximum, 2.0; its HD is Hipparcos's.
    sar = add(db, "SaR", 82, "*", 34.825, -2.9833, mag=[2.0], names=["HD 14386"])
    match = identified(db, IDENTIFIED)[sar]
    assert (match.hip, match.rule) == (10826, "catalog number")


def test_a_catalog_number_resolves_a_pair_the_position_cannot(db):
    # RASC's STF 1604 row lies between the two components.
    rds = add(
        db, "RDS", 32, "D*", 182.0, 20.0 + 0.1 * ARCMIN, mag=[6.8], names=["HD 105590"]
    )
    assert identified(db, IDENTIFIED)[rds].hip == 59272


def test_a_catalog_number_naming_a_far_star_is_a_slip(db):
    # TU Gem's HD 42247 names a star 65° away: no match.
    sar = add(db, "SaR", 147, "*", 100.0, 22.0, mag=[7.4], names=["HD 14386"])
    assert identified(db, IDENTIFIED)[sar].hip is None


def test_two_catalog_numbers_naming_two_stars_are_no_match(db):
    sam = add(
        db, "SaR", 1, "*", 182.0, 20.0, mag=[2.0], names=["HD 105590", "HD 105591"]
    )
    match = identified(db, IDENTIFIED)[sam]
    assert match.hip is None and match.reason.startswith("rules disagree")


def test_a_wds_dm_number_identifies_the_star_within_30_arcsec(db):
    # WDS's DM column, which may be BD, CD or CPD; its V is another band's.
    wds = add(db, "WDS", 1, "D*", 182.0, 20.0 + 10 * ARCSEC, mag=[9.5])
    far = add(db, "WDS", 2, "D*", 182.0, 20.0 + 1.6 * ARCMIN, mag=[9.5])
    found = identified(
        db,
        IDENTIFIED,
        dm_numbers={("WDS", 1): ("+", 20, 2701), ("WDS", 2): ("+", 20, 2702)},
    )
    assert found[wds].hip == 59273
    assert found[far].hip is None


def test_a_wds_dm_number_never_overrides_an_arcsecond_position(db):
    # θ¹ Ori's PTR 1 sits on one component while its DM names the other.
    wds = add(db, "WDS", 1, "D*", 182.0, 20.0 + 1 * ARCSEC, mag=[9.5])
    found = identified(db, IDENTIFIED, dm_numbers={("WDS", 1): ("+", 20, 2701)})
    assert found[wds].hip is None


def test_a_wds_designation_identifies_a_pairs_primary(db):
    # SAC's STF 1604 row is ambiguous by position; WDS's listing sits on 59272.
    sam = add(
        db, "SaM", 661, "D*", 182.0, 20.0 + 0.1 * ARCMIN, mag=[6.8], names=["STF 1604"]
    )
    add(db, "WDS", 1, "D*", 182.0, 20.0 + 1 * ARCSEC, mag=[6.86], names=["STF1604"])
    match = identified(db, IDENTIFIED)[sam]
    assert (match.hip, match.rule) == (59272, "WDS designation")


def test_a_wds_designation_still_needs_the_rows_v(db):
    # θ¹ Ori's CF row (5.1) is not the WDS primary of STF 748 (6.71).
    sam = add(
        db, "SaM", 1, "D*", 182.0, 20.0 + 0.1 * ARCMIN, mag=[5.1], names=["STF 1604"]
    )
    add(db, "WDS", 1, "D*", 182.0, 20.0 + 1 * ARCSEC, mag=[6.86], names=["STF1604"])
    assert identified(db, IDENTIFIED)[sam].hip is None


def test_a_wds_listing_whose_dm_names_its_other_star_vouches_for_nothing(db):
    # STF 1122: the position says one component, WDS's DM the other.
    sam = add(
        db, "SaM", 259, "D*", 182.0, 20.0 + 0.1 * ARCMIN, mag=[6.8], names=["STF 1604"]
    )
    add(db, "WDS", 1, "D*", 182.0, 20.0 + 1 * ARCSEC, mag=[6.86], names=["STF1604"])
    found = identified(db, IDENTIFIED, dm_numbers={("WDS", 1): ("+", 20, 2701)})
    assert found[sam].hip is None


def test_rules_that_name_different_stars_are_no_match(db):
    # Its HD names 59273, its WDS designation 59272.
    sam = add(
        db,
        "SaM",
        1,
        "D*",
        182.0,
        20.0 + 0.1 * ARCMIN,
        mag=[6.8],
        names=["STF 1604", "HD 105591"],
    )
    add(db, "WDS", 1, "D*", 182.0, 20.0 + 1 * ARCSEC, mag=[6.86], names=["STF1604"])
    match = identified(db, IDENTIFIED)[sam]
    assert match.hip is None and match.reason.startswith("rules disagree")


def test_a_sac_continuation_row_joins_its_systems_first_row(db):
    # ν Sco's AC row gives no V; its AB row is the system's.
    ab = add(db, "SaM", 1771, "D*", 200.98, 54.925, mag=[2.3, 6.8])
    ac = add(db, "SaM", 1772, "D*", 200.98, 54.925)
    found = identified(db, systems={("SaM", 1772): ("SaM", 1771)})
    assert (found[ac].hip, found[ac].rule, found[ac].joined_to) == (
        MIZAR,
        "SAC system",
        ab,
    )
    ciu.SAC_SYSTEMS[("SaM", 1772)] = ("SaM", 1771)
    run(db)
    assert object_of(db, "SaM", 1772) == object_of(db, "SaM", 1771) == ab


def test_a_sac_system_is_one_sky_object_though_unmatched(db):
    ab = add(db, "SaM", 1, "D*", 100.0, 10.0, mag=[9.0])
    ac = add(db, "SaM", 2, "D*", 100.0, 10.0)
    found = identified(db, systems={("SaM", 2): ("SaM", 1)})
    assert found[ab].hip is None and found[ac].joined_to == ab
    ciu.SAC_SYSTEMS[("SaM", 2)] = ("SaM", 1)
    result = run(db)
    assert object_of(db, "SaM", 2) == ab
    assert result.hips == {} and result.merged_into == {ac: ab}


def test_a_continuation_row_naming_another_star_stays_apart(db):
    # STF 1830's rows: its own designation's WDS listing matched another star.
    add(
        db,
        "SaM",
        2058,
        "D*",
        182.0,
        20.0 + 0.1 * ARCMIN,
        mag=[6.8],
        names=["HD 105590"],
    )
    cont = add(db, "SaM", 2059, "D*", 182.0, 20.0 + 0.1 * ARCMIN, names=["HD 105591"])
    found = identified(db, IDENTIFIED, systems={("SaM", 2059): ("SaM", 2058)})
    assert found[cont].hip is None and found[cont].joined_to is None
    assert found[cont].reason.startswith("rules disagree")


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
    add(db, "SaM", 2054, "D*", 200.975, 54.9333, mag=[2.3], names=["Zeta UMa", "Mizar"])
    add(
        db,
        "Str",
        56,
        "*",
        200.975,
        54.9167,
        mag=[2.2],
        names=["Mizar", "Zeta Ursae Majoris"],
    )
    add(db, "WDS", 70779, "D*", 200.981, 54.9254, mag=[2.2], names=["WDS J13239+5456"])
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


def test_an_empty_size_is_filled_and_nothing_replaced(db):
    # The bright stars give no size; SAC's comes first, WDS's would replace it.
    add(db, "Str", 56, "*", 200.98, 54.925, mag=[2.2])
    add(db, "SaM", 2054, "D*", 200.98, 54.925, mag=[2.3, 4.0], size_arcsec=[14.4])
    add(db, "WDS", 1, "D*", 200.98, 54.925, mag=[2.23, 3.88], size_arcsec=[14.0])
    run(db)
    survivor = sky_object(db, "Str", 56)
    assert MagnitudeObject.from_json(survivor["mag"]).mags == [2.2]
    assert SizeObject.from_json(survivor["size"]).extents == [pytest.approx(14.4)]


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
        add(db, "SaM", 2054, "D*", 200.975, 54.9333, mag=[2.3], names=["Mizar"])
        add(db, "WDS", 1, "D*", 200.981, 54.9254, mag=[2.2], names=["STF1744"])
        add(db, "Str", 56, "*", 200.975, 54.9167, mag=[2.2], names=["Mizar", "Zeta"])
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

# The first 14 fields of four rows of astro_data/hip_main.dat, and their HD,
# BD, CD and CPD numbers (H71-H74).
HIP_ROWS = [
    (
        "H|       10826| |02 19 20.79|-02 58 37.4| 6.47|3|H|034.83661103|-02.97706055"
        "| |   7.79|   10.33| -239.48",
        " 14386|B-03  353 |          |          ",
    ),
    (
        "H|       55203| |11 18 11.24|+31 31 50.8| 3.79| |G|            |            "
        "| |       |        |        ",
        " 98230|B+32 2132 |          |          ",
    ),
    (
        "H|       69673|H|14 15 40.35|+19 11 14.2|-0.05|1|G|213.91811403|+19.18726997"
        "|*|  88.85|-1093.45|-1999.40",
        "124897|B+19 2777 |          |          ",
    ),
    (
        "H|       91262| |18 36 56.19|+38 46 58.8| 0.03|1|G|279.23410832|+38.78299311"
        "| |128.93|  201.02|  287.46",
        "172167|B+38 3238 |          |          ",
    ),
]


def test_load_hipparcos(tmp_path):
    path = tmp_path / "hip_main.dat"
    # Fields 14-70 are blank here; 71-74 are the catalog numbers.
    path.write_text("".join(f"{head}{'|' * 58}{tail}\n" for head, tail in HIP_ROWS))
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
    assert stars.numbers_of[69673] == {("HD", 124897), ("BD", "+", 19, 2777)}
    assert stars.star_with[("BD", "-", 3, 353)] == 10826


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
