"""Tests for the catalog import's supplementary sources: Hipparcos's star
positions and V, the IAU WGSN's star names, Bica et al. (2008) sizes and the
RC3 extract's V magnitudes.

The rules run against a small objects DB and small VizieR responses built
here, never the committed DB. See docs/ax/catalog.md section 9.4.
"""

import csv
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

import PiFinder.catalog_imports.catalog_import_utils as ciu
import PiFinder.utils as utils
from PiFinder.catalog_imports.main import SUPPLEMENTARY_SOURCES
from PiFinder.catalog_imports.star_identity import Hipparcos
from PiFinder.catalog_imports.steinicke_loader import NOT_FOUND_DESCRIPTION
from PiFinder.catalog_imports.supplementary_sources import (
    BICA_PATH,
    RC3_PATH,
    WGSN_PATH,
    add_wgsn_names,
    ascii_folded,
    fill_bica_sizes,
    ngc_ic_designation,
    read_bica,
    read_rc3_v_coded,
    read_vizier_tsv,
    read_wgsn,
    replace_hipparcos_values,
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
    for code in ("NGC", "IC", "Col", "SaM", "Str", "TLK", "WDS"):
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


# ---- Hipparcos: star positions and V ----

VEGA, CASTOR, MIRA, EPS_AUR, NO_V = 91262, 36850, 10826, 23416, 1
# (hip, ra, dec, V, V is the star's own, variability flag H6)
HIPPARCOS_STARS = (
    (VEGA, 279.23473, 38.78369, 0.03, True, 1),
    (CASTOR, 113.64947, 31.88828, 1.58, False, 0),
    (MIRA, 34.83663, -2.97764, 6.47, True, 3),
    (EPS_AUR, 75.49222, 43.82331, 3.03, True, 2),
    (NO_V, 0.00091, 1.08901, float("nan"), True, 0),
)


def hipparcos_stars(stars=HIPPARCOS_STARS):
    hip, ra, dec, vmag, own, var = (np.array(column) for column in zip(*stars))
    return Hipparcos(
        hip=hip.astype(int),
        ra=ra.astype(float),
        dec=dec.astype(float),
        vmag=vmag.astype(float),
        var_flag=var.astype(int),
        own_vmag=own.astype(bool),
    )


def position_of(db, object_id):
    row = db.conn.execute(
        "SELECT ra, dec, const FROM objects WHERE id = ?", (object_id,)
    ).fetchone()
    return row["ra"], row["dec"], row["const"]


def test_hipparcos_replaces_position_and_the_primarys_v(db):
    # SAC's Vega: 0.6, a minute off; the companion's 9.5 stays.
    vega = add_object(
        db, [("SaM", 1241, "")], "D*", position=(279.25, 38.8), mag=_mag(0.6, 9.5)
    )
    result = replace_hipparcos_values(db, {vega: VEGA}, hipparcos_stars())
    assert position_of(db, vega)[:2] == (279.23473, 38.78369)
    assert mags_of(db, vega) == [0.03, 9.5]
    assert result.replaced == 1
    assert result.magnitudes == [(vega, VEGA, 0.6, 0.03)]
    [(object_id, hip, arcsec)] = result.moved
    assert (object_id, hip) == (vega, VEGA)
    assert arcsec == pytest.approx(72.7, abs=0.1)


def test_hipparcos_recomputes_the_constellation(db):
    # The fixture's sky objects say Dor; Vega's position is in Lyra.
    vega = add_object(db, [("Str", 77, "")], "*", position=(279.2, 38.8), mag=_mag(0))
    result = replace_hipparcos_values(db, {vega: VEGA}, hipparcos_stars())
    assert position_of(db, vega)[2] == "Lyr"
    assert result.constellations == [(vega, "Dor", "Lyr")]


def test_hipparcos_fills_the_primarys_v_of_a_star_without_one(db):
    vega = add_object(db, [("SaM", 1241, "")], "D*", position=(279.2, 38.8))
    replace_hipparcos_values(db, {vega: VEGA}, hipparcos_stars())
    assert mags_of(db, vega) == [0.03]


def test_hipparcos_keeps_a_v_that_is_not_the_stars_own(db):
    # Castor's 1.58 is A and B together: in A's place beside B it would
    # count B twice. The position is replaced all the same.
    castor = add_object(
        db, [("SaM", 1, "")], "D*", position=(113.65, 31.9), mag=_mag(1.9, 2.9)
    )
    result = replace_hipparcos_values(db, {castor: CASTOR}, hipparcos_stars())
    assert mags_of(db, castor) == [1.9, 2.9]
    assert position_of(db, castor)[:2] == (113.64947, 31.88828)
    assert result.not_own_v == [(castor, CASTOR)]
    assert result.magnitudes == []


def test_hipparcos_keeps_a_large_amplitude_variables_v(db):
    # SAC gives Mira at its maximum, 2.0; Hipparcos's 6.47 is one value of
    # a 2-10 mag swing.
    mira = add_object(db, [("SaM", 465, "")], "*", position=(34.84, -2.98), mag=_mag(2))
    result = replace_hipparcos_values(db, {mira: MIRA}, hipparcos_stars())
    assert mags_of(db, mira) == [2.0]
    assert result.large_amplitude == [(mira, MIRA)]


def test_hipparcos_keeps_a_variables_range(db):
    # TLK's [max, min] is a range, not a primary and a companion.
    eps_aur = add_object(
        db, [("TLK", 11, "")], "*", position=(75.49, 43.82), mag=_mag(2.9, 3.8)
    )
    result = replace_hipparcos_values(db, {eps_aur: EPS_AUR}, hipparcos_stars())
    assert mags_of(db, eps_aur) == [2.9, 3.8]
    assert result.kept_range == [eps_aur]


def test_hipparcos_without_a_v_keeps_the_sources(db):
    star = add_object(db, [("WDS", 1, "")], "*", position=(0.0, 1.09), mag=_mag(9.1))
    result = replace_hipparcos_values(db, {star: NO_V}, hipparcos_stars())
    assert mags_of(db, star) == [9.1]
    assert result.no_v == [star]


def test_hipparcos_touches_only_identified_stars(db):
    # No new matching: a star sky object without a HIP keeps its values,
    # even on a Hipparcos star's position.
    vega = add_object(db, [("SaM", 1241, "")], "D*", position=(279.25, 38.8))
    other = add_object(
        db, [("SaM", 1242, "")], "D*", position=(279.23473, 38.78369), mag=_mag(0.6)
    )
    replace_hipparcos_values(db, {vega: VEGA}, hipparcos_stars())
    assert position_of(db, other) == (279.23473, 38.78369, "Dor")
    assert mags_of(db, other) == [0.6]


def test_hipparcos_joins_the_hips_star_identity_recorded(db):
    vega = add_object(db, [("SaM", 1241, "")], "D*", position=(279.25, 38.8))
    ciu.STAR_HIPS.clear()
    ciu.STAR_HIPS[vega] = VEGA
    try:
        replace_hipparcos_values(db, hipparcos=hipparcos_stars())
    finally:
        ciu.STAR_HIPS.clear()
    assert mags_of(db, vega) == [0.03]


# ---- IAU WGSN: star names ----

WGSN_COLUMNS = [
    "name",
    "wgsn_id",
    "designation",
    "hip",
    "bayer_id",
    "constellation",
    "adopted",
]


def write_wgsn(tmp_path, *rows):
    """iau_csn.tsv with (name, HIP) rows; a HIP of None is blank."""
    path = tmp_path / "iau_csn.tsv"
    with open(path, "w", encoding="utf-8", newline="") as tsv:
        writer = csv.writer(tsv, delimiter="\t", lineterminator="\n")
        writer.writerow(WGSN_COLUMNS)
        for name, hip in rows:
            writer.writerow([name, "1", "HR 1", hip or "", "", "Sco", "2016/08/21"])
    return path


def star_with_names(db, *names, sequence=1):
    object_id = add_object(db, [], "D*")
    db.insert_catalog_object(object_id, "SaM", sequence, "")
    for name in names:
        db.insert_name(object_id, name, "SaM")
    return object_id


def names_of(db, object_id):
    return [
        (row["common_name"], row["origin"])
        for row in db.conn.execute(
            "SELECT common_name, origin FROM names WHERE object_id = ? ORDER BY id",
            (object_id,),
        )
    ]


def test_wgsn_name_becomes_the_preferred_name_and_old_names_stay(db, tmp_path):
    acrab = star_with_names(db, "SaM 1768", "Beta Sco", "Graffias")
    path = write_wgsn(tmp_path, ("Acrab", 78820))
    result = add_wgsn_names(db, {acrab: 78820}, path)
    assert names_of(db, acrab) == [
        ("Acrab", "WGSN"),
        ("SaM 1768", "SaM"),
        ("Beta Sco", "SaM"),
        ("Graffias", "SaM"),
    ]
    assert result.preferred == [("Acrab", acrab)]
    assert result.added == ["Acrab"]


def test_wgsn_name_the_star_has_moves_first(db, tmp_path):
    vega = star_with_names(db, "SaM 1241", "Alpha Lyr", "Vega")
    result = add_wgsn_names(db, {vega: VEGA}, write_wgsn(tmp_path, ("Vega", VEGA)))
    assert names_of(db, vega) == [
        ("Vega", "SaM"),
        ("SaM 1241", "SaM"),
        ("Alpha Lyr", "SaM"),
    ]
    assert result.preferred == [("Vega", vega)]
    assert result.added == []


def test_wgsn_spelling_with_diacritics_gets_an_ascii_alias(db, tmp_path):
    star = star_with_names(db, "WDS 1")
    result = add_wgsn_names(db, {star: 2}, write_wgsn(tmp_path, ("Mönch", 2)))
    assert names_of(db, star) == [
        ("Mönch", "WGSN"),
        ("WDS 1", "SaM"),
        ("Monch", "WGSN"),
    ]
    assert result.folded == [("Mönch", "Monch")]


def test_wgsn_skips_and_counts_names_it_cannot_place(db, tmp_path):
    star = star_with_names(db, "SaM 1", "Izar")
    unidentified = star_with_names(db, "SaM 2", "Polaris", sequence=2)
    path = write_wgsn(
        tmp_path,
        ("Mesarthim", None),  # no HIP
        ("Polaris", 11767),  # a star PiFinder holds, but not identified
        ("Pulcherrima", 72105),  # two names for one HIP, no component
        ("Izar", 72105),
    )
    result = add_wgsn_names(db, {star: 72105}, path)
    assert result.no_hip == ["Mesarthim"]
    assert result.not_held == ["Polaris"]
    assert result.shared_hip == ["Pulcherrima", "Izar"]
    assert result.preferred == []
    assert names_of(db, star) == [("SaM 1", "SaM"), ("Izar", "SaM")]
    assert names_of(db, unidentified) == [("SaM 2", "SaM"), ("Polaris", "SaM")]


def test_wgsn_notes_a_name_spelled_otherwise(db, tmp_path):
    star = star_with_names(db, "SaM 1", "Zuben Elgenubi")
    path = write_wgsn(tmp_path, ("Zubenelgenubi", 72622))
    result = add_wgsn_names(db, {star: 72622}, path)
    assert result.spellings == [("Zubenelgenubi", "Zuben Elgenubi")]
    assert [name for name, _ in names_of(db, star)] == [
        "Zubenelgenubi",
        "SaM 1",
        "Zuben Elgenubi",
    ]


def test_wgsn_notes_a_name_another_sky_object_has(db, tmp_path):
    star = star_with_names(db, "Str 31")
    other = star_with_names(db, "SaR 228", "Betelgeuse", sequence=2)
    path = write_wgsn(tmp_path, ("Betelgeuse", 27989))
    result = add_wgsn_names(db, {star: 27989}, path)
    assert result.elsewhere == [("Betelgeuse", [other])]
    assert names_of(db, other) == [("SaR 228", "SaM"), ("Betelgeuse", "SaM")]


@pytest.mark.parametrize(
    "name, folded",
    [
        ("Mönch", "Monch"),
        ("Dhanuśarāgra", "Dhanusaragra"),
        ("Batsũ̀", "Batsu"),
        ("Uñallamacha", "Unallamacha"),
        ("Vega", "Vega"),
    ],
)
def test_ascii_folded(name, folded):
    assert ascii_folded(name) == folded


def test_read_wgsn(tmp_path):
    names = read_wgsn(write_wgsn(tmp_path, ("Acrab", 78820), ("Mesarthim", None)))
    assert [(name.name, name.hip) for name in names] == [
        ("Acrab", 78820),
        ("Mesarthim", None),
    ]


def _extract_module():
    path = Path(utils.astro_data_dir) / "iau_wgsn" / "extract.py"
    spec = importlib.util.spec_from_file_location("wgsn_extract", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_wgsn_extract_reads_the_catalog_table(tmp_path):
    header = "".join(
        f"<th class='sort'> {column}</th>"
        for column in (
            "proper names",
            "NEC+",
            "Designation",
            "HIP",
            "Bayer ID",
            "Constellation",
            "Origin",
            "Date of Adoption",
        )
    )
    page = tmp_path / "page.html"
    page.write_text(
        "<table id='other'><tbody><tr><td>not this</td></tr></tbody></table>"
        f"<table id='table_1'><thead><tr>{header}</tr></thead><tbody>"
        "<tr><td>M&ouml;nch</td><td>1</td><td>HD 1</td><td>30905</td>"
        "<td>&alpha; X</td><td>Ari</td><td>long <b>text</b></td><td>2015/12/15</td></tr>"
        "<tr><td>Krios</td><td>2</td><td>HD 240429</td><td></td>"
        "<td></td><td>Cas</td><td></td><td>2026/01/01</td></tr>"
        f"</tbody><tfoot><tr>{header}</tr></tfoot></table>",
        encoding="utf-8",
    )
    tsv = tmp_path / "out.tsv"
    assert _extract_module().extract(page, tsv) == 2
    assert tsv.read_text(encoding="utf-8").splitlines() == [
        "\t".join(WGSN_COLUMNS),
        "Mönch\t1\tHD 1\t30905\tα X\tAri\t2015/12/15",
        "Krios\t2\tHD 240429\t\t\tCas\t2026/01/01",
    ]


def test_vendored_wgsn_extract(tmp_path):
    """iau_csn.tsv is extract.py's output for the vendored page, as committed."""
    names = read_wgsn(WGSN_PATH)
    assert len(names) == 652
    assert sum(1 for name in names if name.hip is not None) == 579
    tsv = tmp_path / "iau_csn.tsv"
    _extract_module().extract(WGSN_PATH.with_name("modern-iau-star-names.html"), tsv)
    assert tsv.read_bytes() == WGSN_PATH.read_bytes()


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
    """Hipparcos values, WGSN names, Bica sizes, RC3 magnitudes (§9.1), each a
    function of the objects database."""
    assert SUPPLEMENTARY_SOURCES == [
        ("supplementary_sources", "replace_hipparcos_values"),
        ("supplementary_sources", "add_wgsn_names"),
        ("supplementary_sources", "fill_bica_sizes"),
        ("supplementary_sources", "replace_rc3_v_magnitudes"),
    ]
