"""Tests for the star loaders' reading of their sources (#670 items 15-18, 26).

The SAC double-star, red-star and asterism loaders, the bright stars, RASC's
doubles, TLK's variables and WDS. The fixtures are the sources' own rows for
each case, loaded into a small objects DB built here, never the committed one.
"""

import math

import numpy as np
import pytest

import PiFinder.catalog_imports.bright_stars_loader as bright_stars_loader
import PiFinder.catalog_imports.catalog_import_utils as ciu
import PiFinder.catalog_imports.sac_loaders as sac_loaders
import PiFinder.catalog_imports.specialized_loaders as specialized_loaders
import PiFinder.catalog_imports.wds_loader as wds_loader
import PiFinder.utils as utils
from PiFinder.catalog_imports.sac_loaders import (
    is_rejected_pair,
    parse_sac_dec,
    parse_sac_magnitude,
    sac_pair_magnitudes,
)
from PiFinder.composite_object import MagnitudeObject, SizeObject
from PiFinder.db.objects_db import ObjectsDatabase

pytestmark = pytest.mark.unit

STAR_CODES = ("SaA", "SaM", "SaR", "Str", "RDS", "TLK", "WDS")


@pytest.fixture
def db(tmp_path, monkeypatch):
    """An empty objects DB, set as the import's objects_db."""
    db = ObjectsDatabase(tmp_path / "objects.db")
    db.create_tables()
    monkeypatch.setattr(ciu, "objects_db", db)
    monkeypatch.setattr(ciu, "MATCH_REJECTIONS", [])
    monkeypatch.setattr(ciu, "ObjectsDatabase", lambda: db)
    for module in (sac_loaders, bright_stars_loader, specialized_loaders, wds_loader):
        monkeypatch.setattr(module, "objects_db", db)
    yield db
    db.conn.close()
    ciu.STAND_IN_POSITIONS.clear()
    ciu.SAC_SYSTEMS.clear()
    ciu.SOURCE_DM_NUMBERS.clear()


@pytest.fixture
def astro_data(tmp_path, monkeypatch):
    path = tmp_path / "astro_data"
    path.mkdir()
    monkeypatch.setattr(utils, "astro_data_dir", path)
    return path


def listing(db, code, sequence):
    """The catalog listing's sky object, or None if the loader made none."""
    row = db.conn.execute(
        "SELECT o.*, c.description FROM catalog_objects c"
        " JOIN objects o ON o.id = c.object_id"
        " WHERE c.catalog_code = ? AND c.sequence = ?",
        (code, sequence),
    ).fetchone()
    return row


def mags(row):
    return MagnitudeObject.from_json(row["mag"]).mags


def sequences(db, code):
    rows = db.conn.execute(
        "SELECT sequence FROM catalog_objects WHERE catalog_code = ? ORDER BY sequence",
        (code,),
    ).fetchall()
    return [row["sequence"] for row in rows]


# --- SAC: declinations, magnitudes, rejected pairs ---------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("+42 06", 42.1),
        ("-19 28", -(19 + 28 / 60)),
        # int("-00") is 0: Mintaka and δ Ori once landed north of the equator.
        ("-00 18", -0.3),
        ("+00 18", 0.3),
    ],
)
def test_parse_sac_dec_keeps_the_sign_of_minus_00(raw, expected):
    assert parse_sac_dec(raw) == pytest.approx(expected)


@pytest.mark.parametrize(
    "raw, notes, expected",
    [
        ("4.3", "", 4.3),
        ("12  ", "", 12.0),
        ("-1.5", "", -1.5),
        # Mira: a variable at its maximum.
        (" 2 v", "", 2.0),
        # A "var." primary takes the brighter end of its note's range.
        ("var.", "CoCo; Primary is carbon star; mag var 8.0-8.5", 8.0),
        ("var.", "Primary is carbon star; mag var 7.6-13; Companion is", 7.6),
        # U Cam's row gives no range, and W Her's companion no number.
        ("var.", "", None),
        ("Var ", "", None),
        ("", "", None),
        ("none", "", None),
    ],
)
def test_parse_sac_magnitude(raw, notes, expected):
    assert parse_sac_magnitude(raw, notes) == expected


def test_a_blank_primary_keeps_the_companions_magnitude_off_the_star():
    # ν Sco's AC row: the 6.4 is C's, not ν Sco's.
    assert sac_pair_magnitudes("    ", "6.4 ") == ([], 6.4)
    assert sac_pair_magnitudes("4.3 ", "6.8 ") == ([4.3, 6.8], None)
    # W Her's companion is "Var": the primary's magnitude stands alone.
    assert sac_pair_magnitudes("7.3 ", "Var ") == ([7.3], None)


@pytest.mark.parametrize(
    "name, notes, rejected",
    [
        ("Sigma Per      ", "STT 56 rej.", True),
        ("STT 207    rej.", "Bino pair", True),
        ("STF 1918       ", "STF 1918 rej. A is a sp-bin.", True),
        ("Delta Ori      ", "CoCo; W/B", False),
    ],
)
def test_is_rejected_pair(name, notes, rejected):
    assert is_rejected_pair(name, notes) is rejected


SAM_HEADER = (
    "|CON|NAME           |R.A.   |DEC.  |COMP|OTHER NAMES               |Mag |Mag2"
    "|SEP  |PA |NOTES                                                        "
    "|U2K|TIR|BSA|SAO   |\n"
)


def sam_row(con, name, ra, dec, comp, other, mag1, mag2, sep, pa, notes):
    fields = [con, name, ra, dec, comp, other, mag1, mag2, sep, pa, notes]
    return "|" + "|".join(fields) + "|59 |4  |3  |      |\n"


SAM_ROWS = [
    sam_row("CET", "Omicron Cet", "02 19.3", "-02 59", "AB", "Mira", " 2 v", "12",
            "73.1", "85", "M"),
    sam_row("ORI", "Delta Ori", "05 32.0", "-00 18", "", "Mintaka", "2.2", "6.3",
            "52.6", "359", "CoCo; W/B"),
    sam_row("PER", "Sigma Per", "03 31.5", "+47 51", "", "STT  56", "6.8", "10.3",
            "28.7", "352", "STT 56 rej."),
    sam_row("SCO", "Nu Sco", "16 12.0", "-19 28", "AB", "Lesath; H   6", "4.3",
            "6.8", "0.9", "2", "CoCo; Y/O"),
    sam_row("SCO", "Nu Sco", "16 12.0", "-19 28", "AC", "Laseth", "    ", "6.4",
            "41.1", "336", "Bino pair"),
    sam_row("SCO", "Nu Sco", "16 12.0", "-19 28", "CD", "Laseth", "    ", "7.8",
            "2.3", "51", ""),
]  # fmt: skip


@pytest.fixture
def sac_multistars(db, astro_data):
    path = astro_data / "SAC_Multistars_Ver40"
    path.mkdir()
    (path / "sacm.desc").write_text("SAC Multistars")
    (path / "SAC_DBL40_Fence.txt").write_text(SAM_HEADER + "".join(SAM_ROWS))
    sac_loaders.load_sac_multistars()
    return db


def test_load_sac_multistars_keeps_the_sign_of_minus_00(sac_multistars):
    assert listing(sac_multistars, "SaM", 2)["dec"] == pytest.approx(-0.3)


def test_load_sac_multistars_skips_a_rejected_pair_and_keeps_the_numbering(
    sac_multistars,
):
    # σ Per's row is no double; ν Sco keeps the numbers it always had.
    assert listing(sac_multistars, "SaM", 3) is None
    assert sequences(sac_multistars, "SaM") == [1, 2, 4, 5, 6]


def test_load_sac_multistars_keeps_a_companions_magnitude_off_its_primary(
    sac_multistars,
):
    assert mags(listing(sac_multistars, "SaM", 4)) == [4.3, 6.8]
    ac = listing(sac_multistars, "SaM", 5)
    assert mags(ac) == []
    assert MagnitudeObject.from_json(ac["mag"]).filter_mag == 99
    assert ac["description"] == (
        "Bino pair\nComponents: AC\nPA: 336°\nCompanion mag 6.4"
    )


def test_load_sac_multistars_reads_a_variables_magnitude(sac_multistars):
    # Mira's "2 v" was a string, which left the companion's 12 as its magnitude.
    assert mags(listing(sac_multistars, "SaM", 1)) == [2.0, 12.0]


def test_load_sac_redstars_keeps_the_sign_of_minus_00(db, astro_data):
    path = astro_data / "SAC_RedStars_Ver20"
    path.mkdir()
    (path / "sacr.desc").write_text("SAC Red Stars")
    (path / "SAC_RedStars_ver20_FENCE.TXT").write_text(
        "|NAME         |OTHER NAMES                        |CON|RA J2K |DecJ2K|V   "
        "|B-V |SPEC. |NOTES   |\n"
        "|CI Ori       |HD 36167; SAO 132176               |ORI|05 29.7|-00 06| 4.7"
        "|1.85|M1    |Lb      |\n"
    )
    sac_loaders.load_sac_redstars()
    assert listing(db, "SaR", 1)["dec"] == pytest.approx(-0.1)
    # A red star is single; the star cross-match makes a double one D*.
    assert listing(db, "SaR", 1)["obj_type"] == "*"


def test_load_sac_asterisms_keeps_the_sign_of_minus_00(db, astro_data):
    (astro_data / "sac.desc").write_text("SAC Asterisms")
    (astro_data / "SAC_Asterisms_Ver32_Fence.txt").write_text(
        "|Name                  |CON|RA     |Dec   |Mag |SIZE       |TIR|BSA|COMMENTS|\n"
        "|African Buffalo Horns |ORI|05 48.9|-00 40| 9  |24' X 8'   |11 | 4 |Arcs|\n"
    )
    sac_loaders.load_sac_asterisms()
    assert listing(db, "SaA", 1)["dec"] == pytest.approx(-40 / 60)


# --- The bright stars, RASC and TLK: declinations ----------------------------


def test_load_bright_stars_keeps_the_sign_of_minus_0(db, astro_data):
    (astro_data / "Str.desc").write_text("Bright stars")
    (astro_data / "bright_stars.csv").write_text(
        "N,NamedStar,LatinDesignation,RA Hr,RA Min,Dec Deg,Dec Min,Magnitude,Const\r\n"
        "52,Mintaka,Delta Orionis,5,32,-0,17,2.2,Ori\r\n"
        "77,Vega,Alpha Lyrce,18,36.9,38,47,0,Lyr\r\n"
    )
    bright_stars_loader.load_bright_stars()
    assert listing(db, "Str", 52)["dec"] == pytest.approx(-17 / 60)
    assert listing(db, "Str", 77)["dec"] == pytest.approx(38 + 47 / 60)


def test_load_rasc_double_stars_keeps_the_sign_of_minus_00(db, astro_data):
    path = astro_data / "RASC_DoubleStars"
    path.mkdir()
    (path / "rasc_ds.desc").write_text("RASC doubles")
    (path / "rasc_double_stars.csv").write_text(
        "sequence\tTarget\tAlternateID\tWDS\tCon\tRA2000\tDec2000\tMag\tMaxSepSec"
        "\tNotes\n"
        "8\tMintaka\tDelta Ori, 34 Ori\tSTFA 14\tOri\t05 32.0\t-00 18"
        "\t[2.4, 2.4, 6.8]\t56.2\tWidely separated, very attractive.\n"
    )
    specialized_loaders.load_rasc_double_Stars()
    assert listing(db, "RDS", 8)["dec"] == pytest.approx(-0.3)


def test_load_tlk_keeps_the_sign_of_a_declination_just_south_of_the_equator(
    db, astro_data
):
    path = astro_data / "variables" / "TLK_90_vars"
    path.mkdir(parents=True)
    (path / "v90.desc").write_text("TLK 90")
    # SS Vir's row, moved to -0 46: TLK's sign is a column of its own.
    (path / "v90.csv").write_text(
        "CONST;STAR;SAO#;RA2K_H;RA2K_M;RA2K_S;DEC2K_SIGN;DEC2K_D;DEC2K_M;DEC2K_S;"
        "VARTYPE;MagMax;MagMin;PERIOD_Days;DESCRIPTION\n"
        "Virgo;SS Vir;;12;25;13,7;-;0;46;12;SRA;6;9,6;364,14;Red Carbon Star\n"
    )
    specialized_loaders.load_tlk_90_vars()
    assert listing(db, "TLK", 1)["dec"] == pytest.approx(-(46 / 60 + 12 / 3600))


# --- WDS: the columns of wds_precise.txt --------------------------------------

WDS_LINES = [
    # Vega's first three pairs.
    "18369+3846H 5  39AB    1781 2023   87 184.80   84.870      0.09  9.5  A0Va"
    "      +201+286 +004-006 +38 3238 NL U 183656.33+384701.2",
    "18369+3846STFB  9AC    1864 2023    8 252.10   79.400      0.09 11.0  A0Va"
    "      +201+286 +004+000          NS   183656.33+384701.2",
    "18369+3846STFB  9AE    1831 2023   27  39.00   83.360      0.09  9.5  A0Va"
    "      +201+288 +007-004          NL S 183656.33+384701.2",
    # No position angle measured, and south of the equator by 44'.
    "00016-0045SHN  45      1997 1997    0  -1.00    0.160     13.3  15.0      "
    "      +002+006                        000137.21-004421.0",
    # No magnitude for the companion.
    "00023+3257HO  209Aa,Ab 2015 2015    2  30.90    0.354      9.07   .   G0  "
    "      +026-039          +32 4755      000219.30+325724.7",
    # A separation over 1000", which the old columns cut to its last digits.
    "00023+3257ABC   1AB    2015 2015    2  30.90 1234.567      9.07  9.5  G0  "
    "      +026-039          +32 4755      000219.30+325724.7",
    # No arcsecond coordinates: placed by its identifier.
    "00123-2729LDS2101      1954 2017    2  57.20    1.900     16.0  19.8      "
    "      +085+027                    X         .         . ",
    # Propus's BU 1008, 6.15 at 1.9" with an orbit.
    "06149+2230BU 1008      1881 2021  113 256.20    1.900      3.52  6.15 M2III "
    "    -060-008          +22 1241 NC   061452.69+223024.6",
]


@pytest.fixture
def wds_file(tmp_path):
    path = tmp_path / "wds_precise.txt"
    path.write_text("\n".join(WDS_LINES) + "\n")
    return path


def test_read_wds_catalog_reads_the_precise_files_columns(wds_file):
    data = wds_loader.read_wds_catalog(wds_file)
    # Vega AB once read "PA=80.0, Sep=0.0".
    assert data["PA"][0] == pytest.approx(184.8)
    assert data["Sep"][0] == pytest.approx(84.87)
    assert data["Mag_First"][0] == pytest.approx(0.09)
    assert data["Mag_Second"][0] == pytest.approx(9.5)
    assert data["Notes"][0] == "NL U"
    assert data["Sep"][5] == pytest.approx(1234.567)


def test_read_wds_catalog_reads_what_wds_lacks_as_missing(wds_file):
    data = wds_loader.read_wds_catalog(wds_file)
    # "-1" is no measure, and "." no magnitude: neither is a 0.
    assert np.isnan(data["PA"][3])
    assert data["Sep"][3] == pytest.approx(0.16)
    assert np.isnan(data["Mag_Second"][4])


def test_wds_magnitudes_leave_out_what_wds_lacks():
    assert wds_loader.wds_magnitudes(9.07, math.nan).mags == [9.07]
    assert wds_loader.wds_magnitudes(math.nan, 9.5).mags == []
    assert wds_loader.wds_magnitudes(0.09, 9.5).mags == [0.09, 9.5]


@pytest.fixture
def wds(db, astro_data):
    path = astro_data / "WDS"
    path.mkdir()
    (path / "wds.desc").write_text("WDS")
    (path / "wds_precise.txt").write_text("\n".join(WDS_LINES) + "\n")
    wds_loader.load_wds()
    return db


def test_load_wds_describes_each_pair(wds):
    vega = listing(wds, "WDS", 1)
    assert vega["description"].split("\n") == [
        "AB: Mag=0.09/9.5, PA=184.8 (2023), Sep=84.87 Notes: NL U",
        "AC: Mag=0.09/11.0, PA=252.1 (2023), Sep=79.4 Notes: NS",
        "AE: Mag=0.09/9.5, PA=39.0 (2023), Sep=83.36 Notes: NL S",
    ]
    assert SizeObject.from_json(vega["size"]).extents == [pytest.approx(84.9)]
    assert mags(vega) == [0.09, 9.5]
    assert listing(wds, "WDS", 2)["description"] == "Mag=13.3/15.0, Sep=0.16"


def test_load_wds_keeps_the_sign_of_minus_00(wds):
    assert listing(wds, "WDS", 2)["dec"] == pytest.approx(-(44 / 60 + 21.0 / 3600))


def test_load_wds_keeps_a_missing_companion_magnitude_out(wds):
    pair = listing(wds, "WDS", 3)
    assert mags(pair) == [9.07]
    assert pair["description"].split("\n")[0] == (
        "Aa,Ab: Mag=9.07/?, PA=30.9 (2015), Sep=0.354"
    )


def test_load_wds_types_a_listing_by_its_pairs(wds):
    # Vega's pairs are all flagged optical; Propus's BU 1008 is a double.
    assert listing(wds, "WDS", 1)["obj_type"] == "*"
    assert listing(wds, "WDS", 5)["obj_type"] == "D*"
    # SHN 45 is 0.16" wide, too close to split.
    assert listing(wds, "WDS", 2)["obj_type"] == "*"
    # No companion magnitude, or a companion 1234" away: no double star.
    assert listing(wds, "WDS", 3)["obj_type"] == "*"


def test_load_wds_records_a_row_placed_by_its_identifier(wds):
    # 00123-2729 is 00h12.3m -27°29': the star cross-match gives it 3'.
    row = listing(wds, "WDS", 4)
    assert row["ra"] == pytest.approx((12.3 / 60) * 15)
    assert row["dec"] == pytest.approx(-(27 + 29 / 60))
    assert ("WDS", 4) in ciu.STAND_IN_POSITIONS
    assert ("WDS", 1) not in ciu.STAND_IN_POSITIONS


def test_load_sac_multistars_records_a_companion_pair_as_a_stand_in(sac_multistars):
    # ν Sco's CD row sits at A's position, which is not C's.
    assert ("SaM", 6) in ciu.STAND_IN_POSITIONS
    assert ("SaM", 5) not in ciu.STAND_IN_POSITIONS
    assert ("SaM", 4) not in ciu.STAND_IN_POSITIONS


def test_load_sac_multistars_records_a_systems_continuation_rows(sac_multistars):
    # ν Sco: AB (SaM 4) is the system's first row; AC gives no V, CD is a
    # companion pair. Mira's and δ Ori's rows are systems of one row.
    assert ciu.SAC_SYSTEMS == {("SaM", 5): ("SaM", 4), ("SaM", 6): ("SaM", 4)}


def test_load_wds_records_each_listings_dm_number(wds):
    # Vega's rows give BD +38 3238; SHN 45's none.
    assert ciu.SOURCE_DM_NUMBERS[("WDS", 1)] == ("+", 38, 3238)
    assert ("WDS", 2) not in ciu.SOURCE_DM_NUMBERS


@pytest.mark.parametrize(
    "raw, dm",
    [
        ("+38 3238", ("+", 38, 3238)),
        ("-00 6337", ("-", 0, 6337)),
        ("", None),
        (".", None),
    ],
)
def test_wds_dm_number(raw, dm):
    assert wds_loader.wds_dm_number(raw) == dm
