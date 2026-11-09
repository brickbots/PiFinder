"""
Tests for the Steinicke NGC/IC loader: object types, duplicates and
not-found objects.

These exercise ``preprocess_steinicke_type`` and ``steinicke_object_type``
(and their helpers) directly -- the functions where catalog object types are
derived during import -- along with the duplicate identification and the
listing descriptions. The data-validation tests in ``test_catalog_data.py``
only spot-check a handful of well-known objects in the *built* database,
which is why a whole class of globular clusters mis-typed as galaxies
(NGC 7006, M 75, ...) slipped through.

Two layers of coverage:

* Tier 1 -- pure unit tests, one case per decision branch and known
  ambiguity: the TYPE mapping, typing by Steinicke's status S first, the
  status-6 remarks, duplicate twins on small fixture rows, and the not-found
  description. The one insertion test writes to a fixture DB, never the
  committed one.
* Tier 2 -- an audit over the real Steinicke source: every object that the
  globular rescue is *eligible* to reclassify (a globular cross-ID plus a
  concentration-class TYPE) must end up typed ``Gb``; every duplicate
  attaches to its twin except the few whose rows contradict it; every
  Trumpler "n" cluster is a cluster with nebula. This catches each class
  generically rather than enumerating named objects.
"""

import json

import pytest

import PiFinder.utils as utils
from PiFinder.catalog_imports import catalog_import_utils
from PiFinder.catalog_imports.catalog_import_utils import NewCatalogObject
from PiFinder.catalog_imports.steinicke_loader import (
    NOT_FOUND_DESCRIPTION,
    insert_steinicke_objects,
    is_galaxy_type,
    is_trumpler_class,
    prepare_steinicke_object,
    preprocess_steinicke_type,
    resolve_duplicate_twins,
    select_listings,
    steinicke_description,
    steinicke_object_type,
    steinicke_status,
)
from PiFinder.db.objects_db import ObjectsDatabase


# ---------------------------------------------------------------------------
# Tier 1: pure-function mapping cases
# ---------------------------------------------------------------------------

# (steinicke_type, remarks, expected_pifinder_type, label)
MAPPING_CASES = [
    # The bug class: a bare Roman numeral is an Irregular galaxy, but the same
    # numeral with a GCL/globular cross-ID is a globular's concentration class.
    ("I", [], "Gx", "bare-I-is-irregular-galaxy"),
    ("I", ["GCL 119"], "Gb", "I+GCL-is-globular-ngc7006"),
    ("I", ["M 75", "GCL 116"], "Gb", "I+GCL-is-globular-m75"),
    ("IV", ["GCL 1"], "Gb", "IV+GCL-is-globular"),
    ("XII", ["globular"], "Gb", "XII+globular-keyword"),
    # Trumpler open-cluster classes (no globular signal) stay open clusters.
    ("II", [], "OC", "roman-numeral-trumpler-oc"),
    ("II1p", [], "OC", "trumpler-class-oc"),
    ("III2m", [], "OC", "trumpler-class-oc-2"),
    # A trailing "n" is Trumpler's nebulosity flag: a cluster with nebula.
    ("III3pn", [], "C+N", "trumpler-n-ic1805"),
    ("II3mn", ["M 16"], "C+N", "trumpler-n-m16"),
    ("IV2pn", ["IC 1985"], "C+N", "trumpler-n-ic348"),
    ("II3rn", [], "C+N", "trumpler-n-rich-ic1311"),
    # An object that merely *mentions* a globular but is not one (IC 4802 is a
    # star group inside Pal 9). Its exact-match type wins; it must stay Ast.
    ("*Grp", ["in GCL N 6717=Pal 9"], "Ast", "stargroup-in-globular-ic4802"),
    # Exact-match table entries.
    ("GCL", [], "Gb", "explicit-globular"),
    ("OCL", [], "OC", "explicit-open-cluster"),
    ("PN", [], "PN", "planetary-nebula"),
    ("SNR", [], "Nb", "supernova-remnant-as-nebula"),
    ("DN", [], "DN", "dark-nebula"),
    ("Nova", [], "*", "nova-as-star"),
    ("*2", [], "D*", "double-star"),
    ("**", [], "D*", "double-star-alt"),
    ("NF", [], "?", "not-found-unknown"),
    ("*Cloud", ["in Milky Way"], "Ast", "star-cloud-is-not-a-nebula"),
    # Combination types.
    ("OCL+EN", [], "C+N", "cluster-plus-nebula"),
    ("EN+RN", [], "Nb", "emission-plus-reflection-nebula"),
    ("RN+*", [], "C+N", "reflection-nebula-plus-star"),
    ("PN+OCL", ["OCl 743"], "PN", "planetary-in-cluster-ngc2818"),
    # Galaxy Hubble-type patterns.
    ("E", [], "Gx", "elliptical-galaxy"),
    ("Sb", [], "Gx", "spiral-galaxy"),
    ("SBc", [], "Gx", "barred-spiral-galaxy"),
    ("S0", [], "Gx", "lenticular-galaxy"),
    # Suffix stripping recurses back into the mapper.
    ("Sb?", [], "Gx", "galaxy-with-uncertainty-suffix"),
    ("Sa pec", [], "Gx", "peculiar-galaxy"),
    # Empty / missing type.
    ("", [], "?", "empty-type"),
]


@pytest.mark.unit
@pytest.mark.parametrize(
    "steinicke_type, remarks, expected",
    [(c[0], c[1], c[2]) for c in MAPPING_CASES],
    ids=[c[3] for c in MAPPING_CASES],
)
def test_preprocess_steinicke_type(steinicke_type, remarks, expected):
    assert preprocess_steinicke_type(steinicke_type, remarks) == expected


@pytest.mark.unit
def test_roman_numeral_galaxy_globular_overlap():
    """
    Document the ambiguity at the root of the bug: ``is_galaxy_type`` and
    ``is_trumpler_class`` both accept the bare numeral "I", so ordering in
    ``preprocess_steinicke_type`` (globular rescue before the galaxy check)
    is what disambiguates -- not the helpers themselves.
    """
    assert is_galaxy_type("I") is True
    assert is_trumpler_class("I") is True
    # The remarks are the tie-breaker.
    assert preprocess_steinicke_type("I", []) == "Gx"
    assert preprocess_steinicke_type("I", ["GCL 1"]) == "Gb"


@pytest.mark.unit
def test_remarks_accepts_string_and_list():
    """Remarks arrive as a list (ID1-ID11) but a bare string must also work."""
    assert preprocess_steinicke_type("I", "GCL 119") == "Gb"
    assert preprocess_steinicke_type("I", ["GCL 119"]) == "Gb"


# ---------------------------------------------------------------------------
# Tier 1: typing by Steinicke's status first
# ---------------------------------------------------------------------------

# (status, steinicke_type, remarks, expected_pifinder_type, label)
STATUS_CASES = [
    # Status 1 is a galaxy, whatever the TYPE string looks like.
    (1, "4S", ["UGC 4756", "VV 645"], "Gx", "galaxy-quartet-not-stars-ic2431"),
    (1, "3S", ["UGC 12055"], "Gx", "galaxy-not-stars-ic5223"),
    (1, "SBa/PRG", ["UGC 1201"], "Gx", "polar-ring-galaxy-ngc660"),
    (1, "C+*?", ["double system, contact"], "Gx", "galaxy-plus-star-ngc7431"),
    # Status 2 nebulae keep their TYPE's nebula or cluster-with-nebula.
    (2, "EN", [], "Nb", "emission-nebula"),
    (2, "EN+OCL", [], "C+N", "nebula-with-cluster"),
    # Status 3 is a planetary, even inside a cluster.
    (3, "PN+OCL", ["PK 261+8.1", "OCl 743"], "PN", "planetary-ngc2818"),
    # Status 4: a cluster; a star group Steinicke identifies as one is one.
    (4, "*Grp", ["NGC 6882", "OCL 132", "with 20 Vul"], "OC", "star-group-ngc6885"),
    (4, "OCL", [], "OC", "open-cluster"),
    (4, "OCL+EN", [], "C+N", "cluster-with-nebula"),
    (4, "IV3pn", ["OCL 409"], "C+N", "trumpler-n-cluster"),
    (4, "II3m", [], "OC", "trumpler-cluster"),
    # A star cloud stays an asterism under status 4: M 24 joins IC 4715 (PR 6).
    (
        4,
        "*Cloud",
        ["M 24", "ESO 591-**1", "Sagittarius Star Cloud"],
        "Ast",
        "star-cloud-ic4715",
    ),
    # Status 5 is a globular, with or without a GCL cross-ID.
    (5, "II", ["ESO 56-SC39", "in LMC"], "Gb", "globular-ngc1786"),
    (5, "V", ["OCL 51"], "Gb", "globular-ic1257"),
    # Status 9: stars, whose star groups stay asterisms (NGC 5120 included).
    (9, "*Grp", ["OCL 899", "ESO 96-SC11", "Ruprecht 166"], "Ast", "status9-grp"),
    (9, "*Cloud", ["ESO 96-SC13", "in Milky Way"], "Ast", "star-cloud-ngc5155"),
    (9, "*2", [], "D*", "double-star"),
    # Status 10: not found.
    (10, "NF", [], "?", "not-found"),
    # A duplicate is typed by its TYPE, for when its twin can't be found.
    (7, "S0", ["NGC 20"], "Gx", "duplicate-galaxy"),
    (8, "EN", ["NGC 281"], "Nb", "duplicate-nebula"),
    # No status: the TYPE alone.
    (None, "OCL", [], "OC", "no-status"),
]


@pytest.mark.unit
@pytest.mark.parametrize(
    "status, steinicke_type, remarks, expected",
    [c[:4] for c in STATUS_CASES],
    ids=[c[4] for c in STATUS_CASES],
)
def test_steinicke_object_type(status, steinicke_type, remarks, expected):
    assert steinicke_object_type(status, steinicke_type, remarks) == expected


# Status 6, part of another galaxy: typed by its remark.
# (steinicke_type, remarks, expected_pifinder_type, label)
PART_OF_GALAXY_CASES = [
    ("GxyP", ["HII in M 33"], "Nb", "hii-region-ngc604"),
    ("GxyP", ["HII+SCL in M 33"], "Nb", "hii-wins-over-star-cloud-ngc592"),
    ("GxyP", ["BCL 290C", "HII+SCL in M 33"], "Nb", "hii-ic131"),
    ("GxyP", ["HII/Association in N 2403"], "Nb", "hii-association-ngc2404"),
    ("GxyP", ["Henize 959, HII not PN in N5408"], "Nb", "hii-not-pn"),
    # A cluster ID among the identifications is not the remark (BCL is one).
    ("GxyP", ["BCL 710", "OCL in M 33"], "OC", "cluster-ic136"),
    ("GxyP", ["SCL in M 33"], "OC", "star-cloud-ic142"),
    ("GxyP", ["*Cloud in N 4559"], "OC", "star-cloud-ic3564"),
    ("GxyP", ["Association in M 31"], "OC", "association"),
    # Any other part of a galaxy is not a galaxy of its own.
    ("GxyP", ["part of M 101"], "?", "part-ngc5461"),
    ("GxyP", ["knot in NGC 932"], "?", "knot-ngc930"),
    ("GxyP", ["Spiral arm of N 3395"], "?", "spiral-arm-ic2605"),
    ("GxyP", ["part of M 31"], "?", "part-ngc206"),
    # A part that isn't typed GxyP keeps its TYPE (part of the Lagoon nebula).
    ("EN", ["SE part of Lagoon nebula (M 8)"], "Nb", "nebula-part-ngc6526"),
]


@pytest.mark.unit
@pytest.mark.parametrize(
    "steinicke_type, remarks, expected",
    [c[:3] for c in PART_OF_GALAXY_CASES],
    ids=[c[3] for c in PART_OF_GALAXY_CASES],
)
def test_part_of_galaxy_typed_by_remark(steinicke_type, remarks, expected):
    assert steinicke_object_type(6, steinicke_type, remarks) == expected


@pytest.mark.unit
def test_status_reads_the_extractors_string():
    """The extractor stores S as a string ("10"); the loader compares ints."""
    assert steinicke_status({"status": "10"}) == 10
    assert steinicke_status({"status": None}) is None
    assert steinicke_status({}) is None


# ---------------------------------------------------------------------------
# Tier 1: not-found descriptions
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_not_found_description_leads_with_the_not_found_line():
    obj = {"status": "10"}
    assert steinicke_description(obj, "eF, S, R") == (
        "Not found: nothing at Dreyer's position (Steinicke).\neF, S, R"
    )
    assert steinicke_description(obj, "") == NOT_FOUND_DESCRIPTION
    assert NOT_FOUND_DESCRIPTION == (
        "Not found: nothing at Dreyer's position (Steinicke)."
    )


@pytest.mark.unit
def test_found_description_is_dreyers_text_and_steinickes_values():
    obj = {"status": "1", "redshift_distance": 64.1065, "surface_brightness": 13.5}
    assert steinicke_description(obj, "F, S") == (
        "F, S\nD(z)=64.1 Mpc,SB=13.5 mag/arcmin²"
    )
    assert steinicke_description({"status": "1"}, "F, S") == "F, S"


# ---------------------------------------------------------------------------
# Tier 1: duplicates, on small fixtures
# ---------------------------------------------------------------------------


def _row(
    designation,
    status,
    remarks=(),
    ra=(0, 7, 15.9),
    dec=(1, 27, 42, 32.0),
    object_type="Sb",
    letter=None,
    component=None,
    **values,
):
    """One Steinicke row as the extractor writes it."""
    catalog, number = designation.split()
    hours, minutes, seconds = ra
    sign, degrees, arcmin, arcsec = dec
    return {
        "catalogue_prefix": "N" if catalog == "NGC" else "I",
        "catalogue_number": int(number),
        "extension_letter": letter,
        "component": component,
        "status": str(status),
        "object_type": object_type,
        "right_ascension": {"hours": hours, "minutes": minutes, "seconds": seconds},
        "declination": {
            "sign": sign,
            "degrees": degrees,
            "minutes": arcmin,
            "seconds": arcsec,
        },
        "remarks": list(remarks) or None,
        **values,
    }


def _key(designation):
    catalog, number = designation.split()
    return ("N" if catalog == "NGC" else "I", int(number))


def _twins(*rows):
    selected = select_listings(list(rows))
    return {
        " ".join(("NGC" if k[0] == "N" else "IC", str(k[1]))): " ".join(
            ("NGC" if t[0] == "N" else "IC", str(t[1]))
        )
        for k, t in resolve_duplicate_twins(selected).items()
    }


@pytest.mark.unit
def test_a_duplicate_attaches_to_the_twin_it_names():
    assert _twins(
        _row("NGC 6", 7, ["NGC 20", "UGC 84"]),
        _row("NGC 20", 1, ["UGC 84"]),
        _row("IC 11", 8, ["NGC 281", "LBN 616"], ra=(0, 52, 59), object_type="EN"),
        _row("NGC 281", 2, ["IC 11"], ra=(0, 52, 59), object_type="EN"),
    ) == {"NGC 6": "NGC 20", "IC 11": "NGC 281"}


@pytest.mark.unit
def test_a_chain_of_duplicates_ends_at_the_non_duplicate():
    assert _twins(
        _row("IC 249", 8, ["NGC 961"]),
        _row("NGC 961", 7, ["NGC 1051"]),
        _row("NGC 1051", 1, ["IC 249"]),
    ) == {"IC 249": "NGC 1051", "NGC 961": "NGC 1051"}


@pytest.mark.unit
def test_duplicates_naming_each_other_take_the_non_duplicate_they_name():
    assert _twins(
        _row("IC 5179", 7, ["IC 5183", "IC 5184", "ESO 405-5"]),
        _row("IC 5183", 7, ["IC 5179", "IC 5184", "ESO 405-5"]),
        _row("IC 5184", 1, ["IC 5179", "IC 5184", "ESO 405-5"]),
    ) == {"IC 5179": "IC 5184", "IC 5183": "IC 5184"}


@pytest.mark.unit
def test_a_cycle_with_no_way_out_stays_unattached():
    assert (
        _twins(
            _row("IC 5179", 7, ["IC 5183"]),
            _row("IC 5183", 7, ["IC 5179"]),
        )
        == {}
    )


@pytest.mark.unit
def test_a_messier_twin_is_the_one_non_duplicate_listing_it():
    # NGC 651 is M 76's NE lobe, 0.75' from NGC 650, inside the guard
    rows = [
        _row(
            "NGC 651",
            7,
            ["M 76", "PK 130-10.1"],
            ra=(1, 42, 22.0),
            dec=(1, 51, 34, 50.0),
            object_type="PN",
        ),
        _row(
            "NGC 650",
            3,
            ["M 76", "PK 130-10.1"],
            ra=(1, 42, 18.1),
            dec=(1, 51, 34, 17.0),
            object_type="PN",
        ),
    ]
    assert _twins(*rows) == {"NGC 651": "NGC 650"}
    # Two non-duplicates listing one M number: no twin
    assert _twins(*rows, _row("NGC 652", 1, ["M 76"])) == {}


@pytest.mark.unit
def test_a_lettered_twin_is_the_kept_row_or_nothing():
    # NGC 3280 has rows A, B and C and no main row, so "NGC 3280A" is the row
    # the loader keeps as NGC 3280. NGC 4676 keeps its A row, so "NGC 4676B"
    # has no sky object and IC 820 stays its own.
    assert _twins(
        _row("NGC 3295", 7, ["IC 617"], letter="A"),
        _row("IC 617", 8, ["NGC 3280A", "NGC 3295A"]),
        _row("NGC 3280", 1, ["IC 617"], letter="A"),
        _row("NGC 3280", 1, [], letter="B"),
        _row("IC 820", 8, ["NGC 4676B", "UGC 7939"]),
        _row("NGC 4676", 1, ["IC 819"], letter="A"),
        _row("NGC 4676", 1, ["IC 820"], letter="B"),
    ) == {"NGC 3295": "NGC 3280", "IC 617": "NGC 3280"}


@pytest.mark.unit
def test_a_component_twin_must_be_the_kept_component():
    assert _twins(
        _row("NGC 1042", 7, ["NGC 1040-1"]),
        _row("NGC 1040", 1, [], component=1),
        _row("NGC 1043", 7, ["NGC 1040-2"]),
    ) == {"NGC 1042": "NGC 1040"}


@pytest.mark.unit
def test_a_duplicate_away_from_its_twin_stays_its_own():
    # NGC 6363 names NGC 6138, whose row is 11 degrees away; IC 2458 has a
    # position (and values) of its own 2.1' from NGC 2820.
    assert (
        _twins(
            _row("NGC 6363", 7, ["NGC 6138"], ra=(17, 22, 39.9), dec=(1, 41, 6, 8.0)),
            _row("NGC 6138", 1, ["NGC 6341"], ra=(16, 23, 6.3), dec=(1, 40, 51, 30.0)),
            _row("IC 2458", 8, ["NGC 2820"], ra=(9, 21, 30.2), dec=(1, 64, 14, 18.0)),
            _row("NGC 2820", 1, ["IC 2458"], ra=(9, 21, 46.0), dec=(1, 64, 15, 31.0)),
        )
        == {}
    )


@pytest.mark.unit
def test_a_twin_the_loader_does_not_keep_leaves_the_duplicate_alone():
    assert _twins(_row("NGC 6", 7, ["NGC 20"])) == {}
    assert _twins(_row("NGC 6", 7, ["ESO 233-25"]), _row("NGC 20", 1)) == {}


@pytest.fixture
def objects_db(tmp_path, monkeypatch):
    """An empty objects DB that NewCatalogObject.insert() writes to."""

    class NoMatches:
        def get_object_id(self, object_name):
            return None

    db = ObjectsDatabase(tmp_path / "objects.db")
    db.create_tables()
    for code in ("NGC", "IC"):
        db.insert_catalog(code, 10000, code)
    monkeypatch.setattr(catalog_import_utils, "objects_db", db)
    NewCatalogObject.set_shared_finder(NoMatches())
    yield db
    NewCatalogObject.clear_shared_finder()
    db.conn.close()


@pytest.mark.unit
def test_a_duplicate_listing_joins_its_twins_sky_object(objects_db):
    rows = [
        _row("NGC 6", 7, ["NGC 20"], object_type="E-S0", visual_magnitude=13.1),
        _row("NGC 20", 1, ["NGC 6"], object_type="E-S0", visual_magnitude=13.1),
        _row("NGC 21", 1, ["NGC 29"], ra=(0, 10, 47), visual_magnitude=12.7),
        _row("NGC 6363", 7, ["NGC 6138"], ra=(17, 22, 39.9), dec=(1, 41, 6, 8.0)),
        _row("NGC 6138", 1, ["NGC 6341"], ra=(16, 23, 6.3), dec=(1, 40, 51, 30.0)),
    ]
    selected = select_listings(rows)
    prepared = {
        key: prepare_steinicke_object(obj, f"Dreyer {key[1]}")
        for key, obj in selected.items()
    }
    insert_steinicke_objects(prepared, resolve_duplicate_twins(selected))

    listings = {
        row["sequence"]: row
        for row in objects_db.conn.execute("SELECT * FROM catalog_objects")
    }
    assert set(listings) == {6, 20, 21, 6138, 6363}
    assert listings[6]["object_id"] == listings[20]["object_id"]
    # every other listing has a sky object of its own
    assert len({listings[n]["object_id"] for n in (20, 21, 6138, 6363)}) == 4
    assert objects_db.conn.execute("SELECT count(*) FROM objects").fetchone()[0] == 4
    # the duplicate keeps its own listing description and adds its designation
    assert listings[6]["description"] == "Dreyer 6"
    names = [
        row["common_name"]
        for row in objects_db.conn.execute(
            "SELECT common_name FROM names WHERE object_id = ? ORDER BY rowid",
            (listings[20]["object_id"],),
        )
    ]
    assert names == ["NGC 20", "NGC 6"]


@pytest.mark.unit
def test_prepare_types_by_status_and_describes_not_found(objects_db):
    not_found = prepare_steinicke_object(
        _row("NGC 7088", 10, object_type="NF"), "Baxendell's neb"
    )
    assert not_found.object_type == "?"
    assert not_found.description == f"{NOT_FOUND_DESCRIPTION}\nBaxendell's neb"
    assert not_found.ra == pytest.approx(1.81625)
    assert not_found.dec == pytest.approx(27.708889, abs=1e-6)
    hii = prepare_steinicke_object(
        _row("NGC 604", 6, ["HII in M 33"], object_type="GxyP"), ""
    )
    assert hii.object_type == "Nb"


# ---------------------------------------------------------------------------
# Tier 2: invariant audit over the real Steinicke source
# ---------------------------------------------------------------------------

# Globulars whose Steinicke TYPE is a concentration class ("I") and which were
# historically mis-typed as galaxies. Used to prove the audit actually inspects
# real data rather than silently examining an empty set.
KNOWN_CONCENTRATION_CLASS_GLOBULARS = {
    ("N", 2808),
    ("N", 5824),
    ("N", 5834),
    ("N", 6864),
    ("N", 7006),
}


def _load_steinicke_source():
    """
    Load the parsed Steinicke catalog, generating it from the committed source
    ZIP if the JSON has not been produced yet (it is gitignored).
    """
    json_path = utils.astro_data_dir / "ngc_ic_m/steinicke/steinicke_catalog.json"
    if not json_path.exists():
        from PiFinder.catalog_imports.steinicke_loader import _extract_and_process_data

        _extract_and_process_data()
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.mark.unit
def test_globular_crossid_never_typed_as_galaxy():
    """
    Class-level invariant: any Steinicke object carrying a globular cross-ID
    (GCL.../globular in its remarks) together with a concentration-class TYPE
    must map to ``Gb``, never to a galaxy. This would have caught NGC 7006 and
    the four other globulars without anyone naming them.
    """
    data = _load_steinicke_source()

    examined = set()
    offenders = []
    for obj in data:
        prefix = obj.get("catalogue_prefix")
        number = obj.get("catalogue_number")
        if prefix not in ("N", "I") or not number:
            continue
        remarks = obj.get("remarks") or []
        remarks_str = " ".join(str(r) for r in remarks if r)
        has_globular_crossid = "GCL" in remarks_str or "globular" in remarks_str.lower()
        steinicke_type = (obj.get("object_type") or "").strip()
        # Only objects the globular rescue is eligible to reclassify: a
        # globular cross-ID plus a Roman-numeral concentration class.
        if has_globular_crossid and is_trumpler_class(steinicke_type):
            examined.add((prefix, int(number)))
            mapped = preprocess_steinicke_type(steinicke_type, remarks)
            if mapped != "Gb":
                offenders.append((prefix, int(number), steinicke_type, mapped))

    assert not offenders, (
        "Steinicke objects with a globular cross-ID and concentration-class "
        f"TYPE that were not mapped to 'Gb': {offenders}"
    )
    # Guard against the audit silently inspecting nothing (e.g. a schema change
    # that drops remarks): the known mis-typed globulars must be in scope.
    missing = KNOWN_CONCENTRATION_CLASS_GLOBULARS - examined
    assert not missing, f"Audit did not examine expected globulars: {sorted(missing)}"


# The duplicates (status 7 and 8) the loader keeps as sky objects of their
# own, and why: Steinicke's row contradicts the twin it names.
DUPLICATES_KEPT_APART = {
    ("N", 6363),  # its twin NGC 6138's row is 11 degrees away
    ("I", 1028),  # 62' from NGC 5731, with a UGC number of its own
    ("I", 2458),  # 2.1' from NGC 2820, with its own type and magnitude
    ("I", 820),  # NGC 4676B, a B row the loader does not keep
}

# The clusters with nebulosity #670 lists (M 16 is NGC 6611)
TRUMPLER_N_CLUSTERS = {
    ("I", 1805),
    ("I", 1848),
    ("I", 348),
    ("N", 1624),
    ("N", 2264),
    ("N", 3603),
    ("N", 6530),
    ("N", 6823),
    ("N", 7380),
    ("N", 6611),
}


@pytest.mark.unit
def test_every_duplicate_attaches_but_the_contradictory_ones():
    selected = select_listings(_load_steinicke_source())
    duplicates = {
        key for key, obj in selected.items() if steinicke_status(obj) in (7, 8)
    }
    twins = resolve_duplicate_twins(selected)

    assert duplicates - set(twins) == DUPLICATES_KEPT_APART
    assert len(twins) == 600
    # every twin is a non-duplicate listing
    assert not set(twins.values()) & duplicates
    assert twins[("I", 1985)] == ("I", 348)
    assert twins[("N", 2239)] == ("N", 2244)
    assert twins[("N", 651)] == ("N", 650)  # by way of "M 76"
    assert twins[("I", 5179)] == twins[("I", 5183)] == ("I", 5184)


@pytest.mark.unit
def test_every_trumpler_n_cluster_is_a_cluster_with_nebula():
    selected = select_listings(_load_steinicke_source())
    flagged = {
        key
        for key, obj in selected.items()
        if is_trumpler_class((obj.get("object_type") or "").strip())
        and (obj.get("object_type") or "").strip().endswith("n")
        and steinicke_status(obj) == 4
    }
    assert TRUMPLER_N_CLUSTERS <= flagged
    for key in flagged:
        obj = selected[key]
        assert (
            steinicke_object_type(
                steinicke_status(obj), obj["object_type"], obj.get("remarks") or ""
            )
            == "C+N"
        ), key


@pytest.mark.unit
def test_no_part_of_a_galaxy_is_typed_a_galaxy():
    selected = select_listings(_load_steinicke_source())
    parts = [obj for obj in selected.values() if steinicke_status(obj) == 6]
    assert len(parts) == 53
    galaxies = [
        (obj["catalogue_prefix"], obj["catalogue_number"])
        for obj in parts
        if steinicke_object_type(6, obj["object_type"], obj.get("remarks") or "")
        == "Gx"
    ]
    assert not galaxies
