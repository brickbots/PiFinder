"""Tests for the catalog import's supplementary sources: Bica et al. (2008)
sizes and the RC3 extract's V magnitudes.

The rules run against a small objects DB and small VizieR responses built
here, never the committed DB. See docs/ax/catalog.md section 9.4.
"""

import json

import pytest

from PiFinder.catalog_imports.main import SUPPLEMENTARY_SOURCES
from PiFinder.catalog_imports.steinicke_loader import NOT_FOUND_DESCRIPTION
from PiFinder.catalog_imports.supplementary_sources import (
    BICA_PATH,
    RC3_PATH,
    fill_bica_sizes,
    ngc_ic_designation,
    read_bica,
    read_rc3_v_coded,
    read_vizier_tsv,
    replace_rc3_v_magnitudes,
)
from PiFinder.composite_object import MagnitudeObject, SizeObject
from PiFinder.db.objects_db import ObjectsDatabase

pytestmark = pytest.mark.unit

BICA_COLUMNS = ["Names", "RAJ2000", "DEJ2000", "Type", "amaj", "amin", "PA", "Com"]
BICA_UNITS = ["", '"h:m:s"', '"d:m:s"', "", "arcmin", "arcmin", "deg", ""]
RC3_COLUMNS = ["name", "altname", "PGC", "RA2000", "DE2000", "BT", "BT_code", "e_BT"]
RC3_UNITS = ["", "", "", '"h:m:s"', '"d:m:s"', "mag", "", "mag"]


def vizier_response(table, columns, units, rows):
    """One VizieR ASU-TSV response, laid out as VizieR sends it."""
    lines = [
        "#",
        "#   VizieR Astronomical Server vizier.cds.unistra.fr",
        "#INFO\trequest=https://vizier.cds.unistra.fr/viz-bin/asu-tsv?test",
        "",
        "#RESOURCE=yCat_test",
        f"#Table\t{table}:",
        *(f"#Column\t{column}\t(A9)\ttest" for column in columns),
        "\t".join(columns),
        "\t".join(f"{unit:1}" for unit in units),
        "\t".join("-" * 4 for _ in columns),
        *("\t".join(f"{value:6}" for value in row) for row in rows),
        "",
    ]
    return "\n".join(lines) + "\n"


def bica_row(names, ra, dec, bica_type, amaj, amin, pa="", comment=""):
    return [names, ra, dec, bica_type, amaj, amin, pa, comment]


def write_bica(tmp_path, *responses):
    """Bica's extract: one response per (table, rows) pair."""
    path = tmp_path / "bica2008_ngc_ic.tsv"
    path.write_text(
        "".join(
            vizier_response(f"J_MNRAS_389_678_{table}", BICA_COLUMNS, BICA_UNITS, rows)
            for table, rows in responses
        )
    )
    return path


def write_rc3(tmp_path, rows):
    path = tmp_path / "rc3_bt_code_v.tsv"
    path.write_text(vizier_response("VII_155_rc3", RC3_COLUMNS, RC3_UNITS, rows))
    return path


def rc3_row(name, bt, code="V"):
    return [name, "UGC 1", "PGC 1", "00 00 00.0", "+00 00 00", bt, code, "0.13"]


def _size(*arcsec, pa=0.0):
    return json.dumps({"e": list(arcsec), "p": pa})


def _mag(*mags):
    return MagnitudeObject(list(mags)).to_json()


# LMC positions, in degrees: Bica's rows below sit on these or near them.
NGC_1920 = (80.3858, -66.7533)  # 05 21 32.6, -66 45 12
NGC_1745 = (73.5, -69.1875)  # 04 54 00, -69 11 15


@pytest.fixture
def db(tmp_path):
    db = ObjectsDatabase(tmp_path / "objects.db")
    db.create_tables()
    for code in ("NGC", "IC", "Col"):
        db.insert_catalog(code, 10000, code)
    yield db
    db.conn.close()


def add_object(db, listings, obj_type="Nb", position=NGC_1745, size=None, mag=None):
    """A sky object with its listings: [("NGC", 1745, "description"), ...]."""
    object_id = db.insert_object(
        obj_type,
        position[0],
        position[1],
        "Dor",
        size or _size(),
        mag or _mag(),
    )
    for code, sequence, description in listings:
        db.insert_catalog_object(object_id, code, sequence, description)
        db.insert_name(object_id, f"{code} {sequence}", code)
    return object_id


def size_of(db, object_id):
    row = db.conn.execute("SELECT size FROM objects WHERE id = ?", (object_id,))
    return SizeObject.from_json(row.fetchone()["size"])


def mags_of(db, object_id):
    row = db.conn.execute("SELECT mag FROM objects WHERE id = ?", (object_id,))
    return MagnitudeObject.from_json(row.fetchone()["mag"]).mags


# ---- reading VizieR responses ----


def test_read_vizier_tsv_reads_concatenated_responses(tmp_path):
    path = write_bica(
        tmp_path,
        (
            "table3",
            [bica_row("NGC1866,SL319", "05 13 39", "-65 27 54", "C", "5.50", "5.50")],
        ),
        ("table4", []),
        (
            "table5",
            [
                bica_row(
                    "IC2105,LMC-N77A",
                    "04 49 26",
                    "-69 12 02",
                    "NC",
                    "0.65",
                    "0.60",
                    "170",
                )
            ],
        ),
    )
    rows = list(read_vizier_tsv(path))
    assert [table for table, _ in rows] == [
        "J_MNRAS_389_678_table3",
        "J_MNRAS_389_678_table5",
    ]
    assert rows[1][1] == {
        "Names": "IC2105,LMC-N77A",
        "RAJ2000": "04 49 26",
        "DEJ2000": "-69 12 02",
        "Type": "NC",
        "amaj": "0.65",
        "amin": "0.60",
        "PA": "170",
        "Com": "",
    }


def test_read_vizier_tsv_skips_a_blank_units_line(tmp_path):
    """A response whose columns have no units has a blank units line, which
    must not end the header."""
    path = tmp_path / "names.tsv"
    path.write_text(vizier_response("t", ["Names"], [""], [["NGC121"], ["NGC152"]]))
    assert [row["Names"] for _, row in read_vizier_tsv(path)] == ["NGC121", "NGC152"]


@pytest.mark.parametrize(
    "name, designation",
    [
        ("NGC1866", ("NGC", 1866, "")),
        ("IC2105", ("IC", 2105, "")),
        ("NGC    78A", ("NGC", 78, "A")),
        ("IC   5267B", ("IC", 5267, "B")),
        ("NGC1921e", ("NGC", 1921, "E")),
        ("NGC460nw", None),  # half of a pair
        ("ESO56EN24", None),
        ("SL319", None),
        ("B164", None),  # Bica's, not Barnard's
        ("M 42", None),  # a designation, but not NGC or IC
        ("30 Doradus", None),
        ("", None),
    ],
)
def test_ngc_ic_designation(name, designation):
    assert ngc_ic_designation(name) == designation


def test_read_bica_reads_each_row_once_major_axis_first(tmp_path):
    both = bica_row(
        "NGC1748,IC2114,LMC-N83B,", "04 54 23", "-69 11 05", "NC", "0.90", "0.80", "100"
    )
    path = write_bica(
        tmp_path,
        ("table5", [both]),  # the NGC query
        (
            "table5",
            [both, bica_row("IC2111", "04 51 51", "-69 23 35", "NC", "0.55", "0.65")],
        ),
    )
    rows = read_bica(path)
    assert len(rows) == 2
    assert rows[0].names == ["NGC1748", "IC2114", "LMC-N83B"]
    assert rows[0].listings() == [("NGC", 1748), ("IC", 2114)]
    assert rows[0].size.extents == pytest.approx([54.0, 48.0])
    assert rows[0].size.position_angle == 100.0
    assert rows[0].ra == pytest.approx(73.5958, abs=1e-4)
    assert rows[0].dec == pytest.approx(-69.1847, abs=1e-4)
    # axes given minor first are stored major first; no PA is 0
    assert rows[1].size.extents == pytest.approx([39.0, 33.0])
    assert rows[1].size.position_angle == 0.0


def test_read_bica_lettered_names_name_no_listing(tmp_path):
    path = write_bica(
        tmp_path,
        (
            "table3",
            [
                bica_row(
                    "NGC1921e,BSDL1214", "05 19 18", "-69 47 23", "CN", "1.00", "0.90"
                )
            ],
        ),
    )
    assert read_bica(path)[0].listings() == []


def test_vendored_bica_extract():
    rows = read_bica(BICA_PATH)
    assert len(rows) == 388
    by_listing = {listing: row for row in rows for listing in row.listings()}
    assert by_listing[("NGC", 1966)].size.extents == pytest.approx([66.0, 60.0])
    assert by_listing[("NGC", 2070)].names[0] == "30 Doradus"


def test_vendored_rc3_extract():
    magnitudes = read_rc3_v_coded(RC3_PATH)
    assert len(magnitudes) == 101
    assert magnitudes[("NGC", 484, "")] == 12.05
    assert magnitudes[("NGC", 78, "A")] == 13.68


# ---- Bica: fill a missing size, never replace one ----


def test_bica_fills_a_missing_size(db, tmp_path):
    object_id = add_object(db, [("NGC", 1745, "")])
    path = write_bica(
        tmp_path,
        (
            "table5",
            [
                bica_row(
                    "NGC1745,LMC-N83A",
                    "04 54 00",
                    "-69 11 15",
                    "NA",
                    "1.20",
                    "1.10",
                    "90",
                )
            ],
        ),
    )
    result = fill_bica_sizes(db, path)
    assert result.filled == ["NGC 1745"]
    size = size_of(db, object_id)
    assert size.extents == pytest.approx([72.0, 66.0])
    assert size.position_angle == 90.0


def test_bica_never_replaces_a_size(db, tmp_path):
    """NGC 1966 keeps NGC 2000.0's 15' complex, not Bica's 1.1' cluster."""
    object_id = add_object(db, [("NGC", 1966, "")], size=_size(900.0))
    path = write_bica(
        tmp_path,
        (
            "table3",
            [
                bica_row(
                    "NGC1966,ESO56SC125",
                    "04 54 00",
                    "-69 11 15",
                    "DCN",
                    "1.10",
                    "1.00",
                    "30",
                )
            ],
        ),
    )
    result = fill_bica_sizes(db, path)
    assert result.filled == []
    assert size_of(db, object_id).extents == [900.0]


def test_bica_fill_passes_the_match_guard(db, tmp_path):
    """Steinicke's NGC 2029 is Bica's NGC 2030, 91' away, and the reverse;
    neither gets the other's size."""
    far = add_object(db, [("NGC", 2029, "")], position=(83.8475, -66.0333))
    path = write_bica(
        tmp_path,
        (
            "table5",
            [
                bica_row(
                    "NGC2029,ESO56EN156",
                    "05 34 59",
                    "-67 33 23",
                    "NC",
                    "1.10",
                    "0.85",
                    "60",
                )
            ],
        ),
    )
    result = fill_bica_sizes(db, path)
    assert result.filled == []
    assert [(r.aka, r.object_id) for r in result.rejected] == [("NGC 2029", far)]
    assert "apart, limit 30'" in result.rejected[0].reason
    assert size_of(db, far).extents == []


def test_bica_never_sizes_a_star(db, tmp_path):
    star = add_object(db, [("IC", 2116, "PN , stellar")], obj_type="*")
    path = write_bica(
        tmp_path,
        (
            "table5",
            [
                bica_row(
                    "IC2116,LMC-N11A", "04 54 00", "-69 11 15", "NC", "0.60", "0.60"
                )
            ],
        ),
    )
    result = fill_bica_sizes(db, path)
    assert result.filled == []
    assert result.rejected[0].reason == "types NC and *"
    assert size_of(db, star).extents == []


def test_bica_skips_a_not_found_object(db, tmp_path):
    not_found = add_object(
        db, [("NGC", 1915, f"{NOT_FOUND_DESCRIPTION}\neF, pL")], obj_type="?"
    )
    path = write_bica(
        tmp_path,
        (
            "table3",
            [
                bica_row(
                    "NGC1915,ESO85SC71", "04 54 10", "-69 11 15", "C", "0.60", "0.55"
                )
            ],
        ),
    )
    result = fill_bica_sizes(db, path)
    assert result.filled == []
    assert result.not_found == ["NGC 1915"]
    assert size_of(db, not_found).extents == []


def test_bica_nearer_row_fills_a_shared_sky_object(db, tmp_path):
    """Steinicke's duplicate NGC 1911 joins NGC 1920's sky object; Bica lists
    a 0.6' cluster 8.8' away as NGC 1911, and NGC 1920 itself."""
    object_id = add_object(
        db, [("NGC", 1920, ""), ("NGC", 1911, "")], obj_type="C+N", position=NGC_1920
    )
    path = write_bica(
        tmp_path,
        (
            "table3",
            [
                bica_row(
                    "NGC1911,ESO85SC70", "05 19 25", "-66 40 59", "C", "0.60", "0.60"
                )
            ],
        ),
        (
            "table5",
            [
                bica_row(
                    "NGC1920,LMC-N38",
                    "05 21 33",
                    "-66 45 12",
                    "DNC",
                    "1.20",
                    "1.10",
                    "100",
                )
            ],
        ),
    )
    result = fill_bica_sizes(db, path)
    assert result.filled == ["NGC 1920"]
    assert size_of(db, object_id).extents == pytest.approx([72.0, 66.0])


def test_bica_row_naming_one_sky_object_twice_fills_it_once(db, tmp_path):
    object_id = add_object(db, [("NGC", 1748, ""), ("IC", 2114, "")])
    path = write_bica(
        tmp_path,
        (
            "table5",
            [
                bica_row(
                    "NGC1748,IC2114,LMC-N83B",
                    "04 54 00",
                    "-69 11 15",
                    "NC",
                    "0.90",
                    "0.80",
                    "100",
                )
            ],
        ),
    )
    result = fill_bica_sizes(db, path)
    assert result.filled == ["NGC 1748"]
    assert size_of(db, object_id).extents == pytest.approx([54.0, 48.0])


def test_bica_lettered_name_fills_nothing(db, tmp_path):
    object_id = add_object(db, [("NGC", 1921, "")])
    path = write_bica(
        tmp_path,
        (
            "table3",
            [
                bica_row(
                    "NGC1921e,BSDL1214", "04 54 00", "-69 11 15", "CN", "1.00", "0.90"
                )
            ],
        ),
    )
    assert fill_bica_sizes(db, path).filled == []
    assert size_of(db, object_id).extents == []


def test_bica_number_pifinder_lacks_is_ignored(db, tmp_path):
    path = write_bica(
        tmp_path,
        ("table3", [bica_row("NGC9999", "04 54 00", "-69 11 15", "C", "1.00", "1.00")]),
    )
    assert fill_bica_sizes(db, path).filled == []


# ---- RC3: Steinicke's Bmag where it is RC3's V-coded BT ----


def steinicke_row(prefix, number, bmag, vmag, letter=None):
    return {
        "catalogue_prefix": prefix,
        "catalogue_number": number,
        "extension_letter": letter,
        "status": "1",
        "blue_magnitude": bmag,
        "visual_magnitude": vmag,
    }


def steinicke(*rows):
    return {(row["catalogue_prefix"], row["catalogue_number"]): row for row in rows}


def test_rc3_replaces_v_with_steinickes_bmag(db, tmp_path):
    object_id = add_object(db, [("NGC", 484, "")], obj_type="Gx", mag=_mag(11.1))
    path = write_rc3(tmp_path, [rc3_row("NGC   484", "12.05")])
    result = replace_rc3_v_magnitudes(
        db, path, steinicke(steinicke_row("N", 484, 12.1, 11.1))
    )
    assert result.replaced == [("NGC 484", 11.1, 12.1)]
    assert mags_of(db, object_id) == [12.1]


@pytest.mark.parametrize(
    "bmag, bt, replaced",
    [
        (12.1, "12.10", True),
        (12.1, "12.06", True),
        (12.1, "12.05", True),  # 0.05 below
        (12.1, "12.15", True),  # 0.05 above, 0.0500000000000007 in floats
        (12.1, "12.04", False),
        (12.1, "12.16", False),
        (13.2, "12.20", False),  # Steinicke's B is a B: nothing to fix
    ],
)
def test_rc3_match_within_005(db, tmp_path, bmag, bt, replaced):
    object_id = add_object(db, [("NGC", 3224, "")], obj_type="Gx", mag=_mag(11.0))
    path = write_rc3(tmp_path, [rc3_row("NGC  3224", bt)])
    replace_rc3_v_magnitudes(db, path, steinicke(steinicke_row("N", 3224, bmag, 11.0)))
    assert mags_of(db, object_id) == ([bmag] if replaced else [11.0])


def test_rc3_joins_the_kept_row_letter_included(db, tmp_path):
    """Steinicke's NGC 78 is his row NGC 78A, which RC3 lists as NGC 78A; his
    NGC 986 is the main row, not RC3's companion NGC 986A."""
    ngc_78 = add_object(db, [("NGC", 78, "")], obj_type="Gx", mag=_mag(12.8))
    ngc_986 = add_object(db, [("NGC", 986, "")], obj_type="Gx", mag=_mag(10.9))
    ic_5267 = add_object(db, [("IC", 5267, "")], obj_type="Gx", mag=_mag(10.5))
    path = write_rc3(
        tmp_path,
        [
            rc3_row("NGC    78A", "13.68"),
            rc3_row("NGC   986A", "11.60"),
            rc3_row("IC   5267", "11.40"),
        ],
    )
    result = replace_rc3_v_magnitudes(
        db,
        path,
        steinicke(
            steinicke_row("N", 78, 13.7, 12.8, letter="A"),
            steinicke_row("N", 986, 11.6, 10.9),
            steinicke_row("I", 5267, 11.4, 10.5, letter="A"),
        ),
    )
    assert result.replaced == [("NGC 78", 12.8, 13.7)]
    assert mags_of(db, ngc_78) == [13.7]
    assert mags_of(db, ngc_986) == [10.9]
    assert mags_of(db, ic_5267) == [10.5]


def test_rc3_bmag_is_never_a_fallback_v(db, tmp_path):
    """A Steinicke row with a Bmag and no V leaves the sky object without one,
    even where RC3 agrees; and with no RC3 row, a Bmag changes nothing."""
    no_v = add_object(db, [("NGC", 5121, "")], obj_type="Gx")
    no_rc3 = add_object(db, [("NGC", 6164, "")], obj_type="Nb", mag=_mag(6.7))
    path = write_rc3(tmp_path, [rc3_row("NGC  5121", "11.51")])
    result = replace_rc3_v_magnitudes(
        db,
        path,
        steinicke(
            steinicke_row("N", 5121, 11.5, None),
            steinicke_row("N", 6164, 12.0, 6.7),
        ),
    )
    assert result.replaced == []
    assert result.skipped == ["NGC 5121"]
    assert mags_of(db, no_v) == []
    assert mags_of(db, no_rc3) == [6.7]


def test_rc3_leaves_a_v_steinicke_did_not_set(db, tmp_path):
    """The sky object's V is another source's, so it isn't Steinicke's error."""
    object_id = add_object(db, [("NGC", 5062, "")], obj_type="Gx", mag=_mag(11.9))
    path = write_rc3(tmp_path, [rc3_row("NGC  5062", "12.20")])
    result = replace_rc3_v_magnitudes(
        db, path, steinicke(steinicke_row("N", 5062, 12.2, 11.2))
    )
    assert result.replaced == []
    assert result.skipped == ["NGC 5062"]
    assert mags_of(db, object_id) == [11.9]


def test_rc3_reads_only_v_coded_rows(tmp_path):
    """ "v" codes a variable nucleus: its BT is a B magnitude."""
    path = write_rc3(
        tmp_path,
        [rc3_row("NGC  1566", "10.33", code="v"), rc3_row("NGC  7731", "13.51")],
    )
    assert read_rc3_v_coded(path) == {("NGC", 7731, ""): 13.51}


# ---- the pipeline ----


def test_supplementary_sources_are_registered_in_order():
    """Sizes then magnitudes, each a function of the objects database."""
    assert SUPPLEMENTARY_SOURCES == [
        ("supplementary_sources", "fill_bica_sizes"),
        ("supplementary_sources", "replace_rc3_v_magnitudes"),
    ]
