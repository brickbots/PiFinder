"""Tests for the catalog import's corrections: loading, checks, and the final pass.

Everything runs against a small objects DB built here, never the committed
one. See ADR 0046 and astro_data/corrections/README.md for the format.
"""

import json
import textwrap

import pytest

from PiFinder.catalog_imports.corrections import (
    CorrectionError,
    apply_corrections,
    hip_identifications,
    load_corrections,
    parse_dec,
    parse_designator,
    parse_ra,
)
from PiFinder.db.objects_db import ObjectsDatabase

pytestmark = pytest.mark.unit

CITED = 'why = "the source is wrong"\nsources = ["https://example.org/ref"]\n'


def _size(*arcsec, pa=0.0):
    return json.dumps({"e": list(arcsec), "p": pa})


def _mag(*mags):
    return json.dumps({"mags": list(mags), "filter_mag": mags[0] if mags else 99})


@pytest.fixture
def db(tmp_path):
    """Sky objects, each with its listings and names (in insertion order).

    As in the real import, an "M nn" name comes with Steinicke's NGC record,
    so its origin is NGC, not M.
    """
    db = ObjectsDatabase(tmp_path / "objects.db")
    db.create_tables()
    for code in ("M", "NGC", "IC", "C", "SaM"):
        db.insert_catalog(code, 10000, code)
    objects = [
        # M 42 / NGC 1976 at 05 35 17.1, -05 23 25.0
        (
            ("Nb", 83.82125, -5.390277777777778, "Ori", _size(5400, 3600), _mag(4.0)),
            [("M", 42, "Orion Nebula"), ("NGC", 1976, "Theta Orionis neb")],
            [("NGC 1976", "NGC"), ("Orion Nebula", "NGC"), ("M 42", "NGC")],
        ),
        (
            ("Nb", 83.405, -0.413, "Ori", _size(7200), _mag()),
            [("IC", 424, "F, eL")],
            [("IC 424", "IC")],
        ),
        (
            ("Gx", 148.975, 69.683, "UMa", _size(672, 258, pa=65.0), _mag(8.4)),
            [("NGC", 3034, "vB, vL"), ("M", 82, "Cigar")],
            [
                ("NGC 3034", "NGC"),
                ("Bode's nebulae", "NGC"),
                ("M82", "NGC"),
                ("M 82", "NGC"),
            ],
        ),
        (
            ("?", 120.0, -40.0, "Pup", _size(), _mag()),
            [("IC", 2477, "Not found")],
            [("IC 2477", "IC")],
        ),
        (
            ("Gx", 120.1, -40.1, "Pup", _size(60), _mag(13.0)),
            [("IC", 2480, "pF, S")],
            [("IC 2480", "IC")],
        ),
        (
            ("Gx", 345.514, 27.053, "Peg", _size(90, 30, pa=26.0), _mag(13.5)),
            [("NGC", 7466, "eF, eS"), ("IC", 5281, "= NGC 7466?")],
            [("NGC 7466", "NGC"), ("IC 5281", "IC")],
        ),
        (
            ("D*", 315.32, -33.78, "Mic", _size(), _mag(4.9)),
            [("SaM", 1297, "alpha Mic")],
            [("SaM 1297", "SaM")],
        ),
    ]
    for values, listings, names in objects:
        object_id = db.insert_object(*values)
        for code, sequence, description in listings:
            db.insert_catalog_object(object_id, code, sequence, description)
        for name, origin in names:
            db.insert_name(object_id, name, origin)
    yield db
    db.conn.close()


@pytest.fixture
def corrections_dir(tmp_path):
    path = tmp_path / "corrections"
    path.mkdir()
    return path


def write(directory, text, name="steinicke.toml"):
    (directory / name).write_text(textwrap.dedent(text))


def load(directory, text, name="steinicke.toml"):
    write(directory, text, name)
    return load_corrections(directory)


def problems_of(excinfo):
    return "\n".join(excinfo.value.problems)


def sky_object(db, code, sequence):
    return db.conn.execute(
        "SELECT o.* FROM objects o JOIN catalog_objects co ON co.object_id = o.id"
        " WHERE co.catalog_code = ? AND co.sequence = ?",
        (code, sequence),
    ).fetchone()


def object_id(db, code, sequence):
    return sky_object(db, code, sequence)["id"]


def names(db, code, sequence):
    return [
        row["common_name"]
        for row in db.conn.execute(
            "SELECT common_name FROM names WHERE object_id = ? ORDER BY id",
            (object_id(db, code, sequence),),
        )
    ]


def description(db, code, sequence):
    return db.conn.execute(
        "SELECT description FROM catalog_objects"
        " WHERE catalog_code = ? AND sequence = ?",
        (code, sequence),
    ).fetchone()["description"]


def snapshot(db):
    return [
        [tuple(row) for row in db.conn.execute(f"SELECT * FROM {table} ORDER BY id")]
        for table in ("objects", "catalog_objects", "names")
    ]


def apply(db, directory, text, name="steinicke.toml"):
    apply_corrections(db, load(directory, text, name))


def apply_fails(db, directory, text, name="steinicke.toml"):
    corrections = load(directory, text, name)
    before = snapshot(db)
    with pytest.raises(CorrectionError) as excinfo:
        apply_corrections(db, corrections)
    assert snapshot(db) == before, "a failed pass must change nothing"
    return problems_of(excinfo)


# ---- values ----


@pytest.mark.parametrize(
    "text", ["05 35 17.3", "05:35:17.3", "5h35m17.3s", "05 35.28833333"]
)
def test_parse_ra_reads_sexagesimal_hours(text):
    assert parse_ra(text) == pytest.approx(83.8220833, abs=1e-6)


@pytest.mark.parametrize(
    "text, degrees",
    [
        ("-05 23 28", -5.3911111),
        ("+41°16′09″", 41.2691667),
        ("41 16 09", 41.2691667),
        ("-00 30 00", -0.5),
        ("-00:30", -0.5),
    ],
)
def test_parse_dec_reads_sexagesimal_degrees_and_keeps_the_sign(text, degrees):
    assert parse_dec(text) == pytest.approx(degrees, abs=1e-6)


@pytest.mark.parametrize(
    "text", [83.82, "83.82", "24 00 00", "-05 35 17", "05 61 00", "05.5 30", "5 hrs"]
)
def test_parse_ra_rejects(text):
    with pytest.raises(ValueError):
        parse_ra(text)


@pytest.mark.parametrize("text", [-5.39, "91 00 00", "-05 23 28 1", "-05 23 60"])
def test_parse_dec_rejects(text):
    with pytest.raises(ValueError):
        parse_dec(text)


def test_parse_designator():
    assert parse_designator("NGC 604") == ("NGC", 604)
    assert parse_designator("Sh2 155") == ("Sh2", 155)
    for bad in ("NGC604", "NGC 0604", "NGC  604", "NGC 604A", "M 0", 604):
        with pytest.raises(ValueError):
            parse_designator(bad)


# ---- loading ----


def test_load_parses_values_into_reference_units(corrections_dir):
    (correction,) = load(
        corrections_dir,
        """
        ["IC 424"]
        why = "Steinicke's 120' is the whole complex"
        sources = ["https://example.org/a", "https://example.org/b"]
        size = "2.5'"
        was.size = "120'"
        mag = [4.86, 7.32]
        was.mag = ""
        dec = "-00 24 47"
        was.dec = "-00 24 50"
        """,
    )
    assert correction.designator == "IC 424"
    assert correction.listing == ("IC", 424)
    assert correction.label == "steinicke.toml [IC 424]"
    assert correction.sources == ["https://example.org/a", "https://example.org/b"]
    assert correction.fields["size"] == pytest.approx([150.0])
    assert correction.was["size"] == pytest.approx([7200.0])
    assert correction.fields["mag"] == [4.86, 7.32]
    assert correction.was["mag"] == []
    assert correction.fields["dec"] == pytest.approx(-(24 / 60 + 47 / 3600))


@pytest.mark.parametrize(
    "body, expected",
    [
        ('sources = ["https://x"]\nmag = 1\nwas.mag = 2', "needs `why`"),
        ('why = "x"\nmag = 1\nwas.mag = 2', "needs `sources`"),
        ('why = "x"\nsources = []\nmag = 1\nwas.mag = 2', "needs `sources`"),
        (CITED + 'size = "2.5\'"', "size needs was.size"),
        (CITED + 'mag = 1\nwas.mag = 2\nwas.size = "1\'"', "was.size without a size"),
        (CITED + "mag = 1\nwas.mag = 2\nwas.magnitude = 2", "was.magnitude is not"),
        (CITED + "magnitude = 5", "unknown key 'magnitude'"),
        (CITED + 'obj_type = "Galaxy"\nwas.obj_type = "Nb"', "not a type code"),
        (CITED + 'obj_type = "Gx"\nwas.obj_type = ""', "was.obj_type"),
        (CITED + 'const = "Orion"\nwas.const = "Ori"', "not an IAU constellation"),
        (CITED + 'size = "2.5\' x see"\nwas.size = ""', "non-numeric size token"),
        (CITED + 'size = 2.5\nwas.size = ""', "size must be a string"),
        (CITED + 'mag = "11.4"\nwas.mag = ""', "mag must be a number"),
        (CITED + 'mag = true\nwas.mag = ""', "mag must be a number"),
        (CITED + 'ra = 83.4\nwas.ra = "05 33 37"', "sexagesimal string"),
        (CITED + 'size = "2.5\'"\nwas.size = "150\\""', "corrects nothing"),
        (CITED + "mag = 4.0\nwas.mag = 4.04", "corrects nothing"),
        (CITED + 'same_as = "IC 2480"\nown_object = true', "contradict"),
        (CITED + "own_object = false", "can only be true"),
        (CITED + 'same_as = "IC 424"', "the designator itself"),
        (CITED + 'same_as = "IC424"', "same_as: 'IC424' is not a designator"),
        (CITED + "names.add = []", "names.add must be a non-empty list"),
        (CITED + 'names.add = ["A", "A"]', "lists a name twice"),
        (CITED + 'names.rename = ["A"]', "unknown key names.rename"),
        (CITED + 'names.add = ["A"]\nnames.remove = ["A"]', "both list ['A']"),
        (CITED + 'names.add = ["A"]\nnames.preferred = "A"', "drop it from names"),
        (CITED + 'names.remove = ["A"]\nnames.preferred = "A"', "also in names.r"),
        (CITED + "hip = 0", "Hipparcos number"),
        (CITED + 'hip = "102989"', "Hipparcos number"),
        (CITED + "hip = true", "Hipparcos number"),
        (CITED, "corrects nothing"),
    ],
)
def test_load_rejects(corrections_dir, body, expected):
    with pytest.raises(CorrectionError) as excinfo:
        load(corrections_dir, '["IC 424"]\n' + body)
    assert expected in problems_of(excinfo)
    assert "steinicke.toml [IC 424]" in problems_of(excinfo)


def test_load_rejects_a_header_that_is_not_a_designator(corrections_dir):
    with pytest.raises(CorrectionError) as excinfo:
        load(corrections_dir, '["IC424"]\n' + CITED + "hip = 5")
    assert "'IC424' is not a designator" in problems_of(excinfo)


def test_load_rejects_keys_outside_any_table(corrections_dir):
    with pytest.raises(CorrectionError) as excinfo:
        load(corrections_dir, CITED)
    assert "must be a table" in problems_of(excinfo)


def test_load_rejects_invalid_toml(corrections_dir):
    with pytest.raises(CorrectionError) as excinfo:
        load(corrections_dir, "[IC 424]\n" + CITED)
    assert "steinicke.toml: not valid TOML" in problems_of(excinfo)


def test_load_reports_every_problem_in_every_file(corrections_dir):
    write(corrections_dir, '["IC 424"]\nmag = 1\nwas.mag = 2\n', "a.toml")
    write(corrections_dir, '["M 42"]\n' + CITED + "magnitude = 1\n", "b.toml")
    with pytest.raises(CorrectionError) as excinfo:
        load_corrections(corrections_dir)
    text = problems_of(excinfo)
    assert "a.toml [IC 424]: needs `why`" in text
    assert "a.toml [IC 424]: needs `sources`" in text
    assert "b.toml [M 42]: unknown key 'magnitude'" in text


def test_load_reads_files_in_name_order_and_ignores_other_files(corrections_dir):
    write(corrections_dir, '["M 42"]\n' + CITED + "hip = 2\n", "b.toml")
    write(corrections_dir, '["IC 424"]\n' + CITED + "hip = 1\n", "a.toml")
    (corrections_dir / "README.md").write_text("# not a correction")
    corrections = load_corrections(corrections_dir)
    assert [c.designator for c in corrections] == ["IC 424", "M 42"]


def test_load_with_no_corrections(tmp_path, corrections_dir):
    assert load_corrections(corrections_dir) == []
    assert load_corrections(tmp_path / "missing") == []


def test_shipped_corrections_load():
    load_corrections()


# ---- hip ----


def test_hip_is_exposed_for_the_star_cross_match_and_not_applied(db, corrections_dir):
    before = snapshot(db)
    corrections = load(
        corrections_dir,
        '["SaM 1297"]\n' + CITED + "hip = 102989\n",
        "sac_multistars.toml",
    )
    assert hip_identifications(corrections) == {"SaM 1297": 102989}
    apply_corrections(db, corrections)
    assert snapshot(db) == before


def test_hip_twice_for_one_designator_fails(db, corrections_dir):
    write(corrections_dir, '["SaM 1297"]\n' + CITED + "hip = 1\n", "a.toml")
    write(corrections_dir, '["SaM 1297"]\n' + CITED + "hip = 2\n", "b.toml")
    corrections = load_corrections(corrections_dir)
    with pytest.raises(CorrectionError) as excinfo:
        hip_identifications(corrections)
    assert "b.toml [SaM 1297]: conflicts with a.toml [SaM 1297]" in problems_of(excinfo)
    with pytest.raises(CorrectionError):
        apply_corrections(db, corrections)


def test_hip_designator_must_resolve(db, corrections_dir):
    problems = apply_fails(db, corrections_dir, '["SaM 9"]\n' + CITED + "hip = 5\n")
    assert "SaM 9 resolves to nothing" in problems


# ---- setting fields ----


def test_size_correction_keeps_the_position_angle(db, corrections_dir):
    apply(
        db,
        corrections_dir,
        '["M 82"]\n' + CITED + "size = \"12'x5'\"\nwas.size = \"11.2'x4.3'\"\n",
    )
    size = json.loads(sky_object(db, "M", 82)["size"])
    assert size["e"] == pytest.approx([720.0, 300.0])
    assert size["p"] == 65.0


def test_mag_takes_a_number_or_a_range(db, corrections_dir):
    apply(
        db,
        corrections_dir,
        '["IC 424"]\n' + CITED + 'mag = 11.4\nwas.mag = ""\n'
        '["IC 2480"]\n' + CITED + "mag = [4.86, 7.32]\nwas.mag = 13.0\n",
    )
    assert json.loads(sky_object(db, "IC", 424)["mag"]) == {
        "mags": [11.4],
        "filter_mag": 11.4,
    }
    mag = json.loads(sky_object(db, "IC", 2480)["mag"])
    assert mag["mags"] == [4.86, 7.32]
    assert mag["filter_mag"] == pytest.approx(6.09)


def test_a_field_correction_reaches_the_sky_object_through_any_designator(
    db, corrections_dir
):
    apply(
        db,
        corrections_dir,
        '["NGC 1976"]\n' + CITED + 'obj_type = "C+N"\nwas.obj_type = "Nb"\n',
    )
    assert sky_object(db, "M", 42)["obj_type"] == "C+N"


def test_a_description_belongs_to_one_listing(db, corrections_dir):
    apply(
        db,
        corrections_dir,
        '["NGC 1976"]\n'
        + CITED
        + 'description = """\nThe Orion Nebula.\n"""\n'
        + 'was.description = "Theta Orionis neb"\n',
    )
    assert description(db, "NGC", 1976) == "The Orion Nebula."
    assert description(db, "M", 42) == "Orion Nebula"


def test_was_description_can_be_empty(db, corrections_dir):
    db.conn.execute("UPDATE catalog_objects SET description = '' WHERE sequence = 424")
    db.conn.commit()
    apply(
        db,
        corrections_dir,
        '["IC 424"]\n' + CITED + 'description = "Faint."\nwas.description = ""\n',
    )
    assert description(db, "IC", 424) == "Faint."


def test_a_position_correction_moves_the_constellation(db, corrections_dir, caplog):
    caplog.set_level("INFO")
    apply(
        db,
        corrections_dir,
        '["IC 424"]\n'
        + CITED
        + 'ra = "06 31 55"\nwas.ra = "05 33 37.2"\n'
        + 'dec = "+04 56 34"\nwas.dec = "-00 24 46.8"\n',
    )
    row = sky_object(db, "IC", 424)
    assert row["ra"] == pytest.approx(97.979167, abs=1e-6)
    assert row["dec"] == pytest.approx(4.942778, abs=1e-6)
    assert row["const"] == "Mon"
    assert "Constellation of IC 424 follows its corrected position: Ori -> Mon" in (
        caplog.text
    )


def test_a_const_correction_wins_over_the_position(db, corrections_dir):
    apply(
        db,
        corrections_dir,
        '["IC 424"]\n'
        + CITED
        + 'ra = "06 31 55"\nwas.ra = "05 33 37.2"\n'
        + 'const = "Eri"\nwas.const = "Ori"\n',
    )
    assert sky_object(db, "IC", 424)["const"] == "Eri"


def test_redundant_correction_fails(db, corrections_dir):
    problems = apply_fails(
        db, corrections_dir, '["M 42"]\n' + CITED + "mag = 4.0\nwas.mag = 5.0\n"
    )
    assert "steinicke.toml [M 42]: mag is already 4.0" in problems
    assert "redundant" in problems


def test_stale_correction_fails_and_says_what_the_database_holds(db, corrections_dir):
    problems = apply_fails(
        db,
        corrections_dir,
        '["IC 424"]\n' + CITED + 'size = "2.5\'"\nwas.size = "60\'"\n',
    )
    assert "size is stale: was.size says '1°'" in problems
    assert "the database holds '2°'" in problems


@pytest.mark.parametrize(
    "field, was, value, matches",
    [
        ("mag", "4.04", "9.0", True),
        ("mag", "4.06", "9.0", False),
        ("ra", '"05 35 17.15"', '"05 35 20"', True),  # 0.75 arcsec of RA
        ("ra", '"05 35 17.2"', '"05 35 20"', False),  # 1.5 arcsec
        ("dec", '"-05 23 25.9"', '"-05 23 40"', True),
        ("dec", '"-05 23 26.1"', '"-05 23 40"', False),
        ("size", "\"90'x60'\"", "\"80'x60'\"", True),
        ("size", '"1.5°x1°"', "\"80'x60'\"", True),
        ("size", "\"90'x61'\"", "\"80'x60'\"", False),
        ("size", '"90\'"', "\"80'x60'\"", False),
    ],
)
def test_was_tolerances(db, corrections_dir, field, was, value, matches):
    text = f'["M 42"]\n{CITED}{field} = {value}\nwas.{field} = {was}\n'
    if matches:
        apply(db, corrections_dir, text)
    else:
        assert f"{field} is stale" in apply_fails(db, corrections_dir, text)


def test_redundancy_is_within_tolerance_too(db, corrections_dir):
    problems = apply_fails(
        db, corrections_dir, '["M 42"]\n' + CITED + "mag = 4.03\nwas.mag = 6\n"
    )
    assert "mag is already 4.03" in problems


@pytest.mark.parametrize(
    "designator, expected",
    [("NGC 9999", "NGC 9999 resolves to nothing"), ("Xyz 1", "no catalog has")],
)
def test_a_designator_that_resolves_to_nothing_fails(
    db, corrections_dir, designator, expected
):
    problems = apply_fails(
        db, corrections_dir, f'["{designator}"]\n{CITED}mag = 1\nwas.mag = 2\n'
    )
    assert expected in problems


def test_two_corrections_reaching_one_field_of_a_sky_object_fail(db, corrections_dir):
    write(corrections_dir, '["M 42"]\n' + CITED + "mag = 4.1\nwas.mag = 4.0\n")
    problems = apply_fails(
        db,
        corrections_dir,
        '["NGC 1976"]\n' + CITED + "mag = 4.2\nwas.mag = 4.0\n",
        "other.toml",
    )
    assert (
        "steinicke.toml [M 42]: conflicts with other.toml [NGC 1976]: both"
        " correct mag" in problems
    )


def test_two_corrections_on_different_fields_of_a_sky_object_are_fine(
    db, corrections_dir
):
    write(corrections_dir, '["M 42"]\n' + CITED + "mag = 4.1\nwas.mag = 4.0\n")
    apply(
        db,
        corrections_dir,
        '["NGC 1976"]\n' + CITED + "size = \"85'x60'\"\nwas.size = \"90'x60'\"\n",
        "other.toml",
    )
    row = sky_object(db, "M", 42)
    assert json.loads(row["mag"])["mags"] == [4.1]
    assert json.loads(row["size"])["e"] == pytest.approx([5100.0, 3600.0])


# ---- names ----


def test_names_remove_and_preferred(db, corrections_dir):
    apply(
        db,
        corrections_dir,
        '["M 82"]\n'
        + CITED
        + 'names.remove = ["Bode\'s nebulae"]\n'
        + 'names.preferred = "Cigar Galaxy"\n',
        "ngc2000_names.toml",
    )
    assert names(db, "M", 82) == ["Cigar Galaxy", "NGC 3034", "M82", "M 82"]


def test_names_preferred_moves_an_existing_name_first(db, corrections_dir):
    apply(db, corrections_dir, '["M 42"]\n' + CITED + 'names.preferred = "M 42"\n')
    assert names(db, "M", 42) == ["M 42", "NGC 1976", "Orion Nebula"]


def test_names_add_appends(db, corrections_dir):
    apply(db, corrections_dir, '["M 42"]\n' + CITED + 'names.add = ["Great Nebula"]\n')
    assert names(db, "NGC", 1976)[-1] == "Great Nebula"


def test_names_remove_takes_every_copy(db, corrections_dir):
    db.insert_name(object_id(db, "M", 82), "M82", "Arp")
    apply(db, corrections_dir, '["NGC 3034"]\n' + CITED + 'names.remove = ["M82"]\n')
    assert "M82" not in names(db, "M", 82)


@pytest.mark.parametrize(
    "operation, expected",
    [
        ('names.remove = ["Crab Nebula"]', "which the sky object doesn't have"),
        ('names.add = ["Orion Nebula"]', "which it already has"),
        ('names.preferred = "NGC 1976"', "is already the first name"),
    ],
)
def test_name_checks(db, corrections_dir, operation, expected):
    problems = apply_fails(db, corrections_dir, f'["M 42"]\n{CITED}{operation}\n')
    assert expected in problems


def test_two_corrections_touching_one_name_fail(db, corrections_dir):
    write(corrections_dir, '["M 42"]\n' + CITED + 'names.add = ["Great Nebula"]\n')
    problems = apply_fails(
        db,
        corrections_dir,
        '["NGC 1976"]\n' + CITED + 'names.preferred = "Great Nebula"\n',
        "other.toml",
    )
    assert "both correct names.preferred" not in problems
    assert "both correct the name 'Great Nebula'" in problems


# ---- identifications ----


def test_same_as_merges_a_lone_listing_into_the_other_sky_object(db, corrections_dir):
    orphan = object_id(db, "IC", 2477)
    apply(db, corrections_dir, '["IC 2477"]\n' + CITED + 'same_as = "IC 2480"\n')
    assert object_id(db, "IC", 2477) == object_id(db, "IC", 2480)
    assert names(db, "IC", 2480) == ["IC 2480", "IC 2477"]
    assert description(db, "IC", 2477) == "Not found"
    assert (
        db.conn.execute("SELECT 1 FROM objects WHERE id = ?", (orphan,)).fetchone()
        is None
    )


def test_same_as_moves_one_listing_off_a_shared_sky_object(db, corrections_dir):
    apply(db, corrections_dir, '["IC 5281"]\n' + CITED + 'same_as = "IC 2480"\n')
    assert object_id(db, "IC", 5281) == object_id(db, "IC", 2480)
    assert names(db, "IC", 5281) == ["IC 2480", "IC 5281"]
    assert names(db, "NGC", 7466) == ["NGC 7466"]


def test_a_field_correction_follows_its_listing_after_same_as(db, corrections_dir):
    apply(
        db,
        corrections_dir,
        '["IC 2477"]\n'
        + CITED
        + 'same_as = "IC 2480"\n'
        + 'description = "= IC 2480 (Corwin)"\nwas.description = "Not found"\n',
    )
    assert description(db, "IC", 2477) == "= IC 2480 (Corwin)"
    assert description(db, "IC", 2480) == "pF, S"


def test_same_as_that_is_already_true_fails(db, corrections_dir):
    problems = apply_fails(
        db, corrections_dir, '["NGC 1976"]\n' + CITED + 'same_as = "M 42"\n'
    )
    assert "already the same sky object" in problems


def test_same_as_an_unresolved_target_fails(db, corrections_dir):
    problems = apply_fails(
        db, corrections_dir, '["IC 2477"]\n' + CITED + 'same_as = "IC 9999"\n'
    )
    assert "same_as: IC 9999 resolves to nothing" in problems


def test_same_as_chains_fail(db, corrections_dir):
    problems = apply_fails(
        db,
        corrections_dir,
        '["IC 2477"]\n'
        + CITED
        + 'same_as = "IC 424"\n'
        + '["IC 424"]\n'
        + CITED
        + 'same_as = "IC 2480"\n',
    )
    assert "[IC 2477]: same_as IC 424, which is itself corrected" in problems


def test_two_identifications_of_one_listing_conflict(db, corrections_dir):
    write(corrections_dir, '["IC 5281"]\n' + CITED + "own_object = true\n")
    problems = apply_fails(
        db,
        corrections_dir,
        '["IC 5281"]\n' + CITED + 'same_as = "IC 2480"\n',
        "other.toml",
    )
    assert "both correct the identification of IC 5281" in problems


def test_own_object_splits_a_listing_into_a_sky_object_of_its_own(db, corrections_dir):
    apply(
        db,
        corrections_dir,
        '["IC 5281"]\n'
        + CITED
        + "own_object = true\n"
        + 'obj_type = "D*"\nwas.obj_type = "Gx"\n'
        + "mag = 12.1\nwas.mag = 13.5\n",
    )
    assert object_id(db, "IC", 5281) != object_id(db, "NGC", 7466)
    split = sky_object(db, "IC", 5281)
    assert split["obj_type"] == "D*"
    assert json.loads(split["mag"])["mags"] == [12.1]
    assert split["ra"] == pytest.approx(345.514)  # copied, since not corrected
    assert names(db, "IC", 5281) == ["IC 5281"]
    assert names(db, "NGC", 7466) == ["NGC 7466"]
    assert sky_object(db, "NGC", 7466)["obj_type"] == "Gx"


def test_same_as_a_split_designator_joins_its_new_sky_object(db, corrections_dir):
    apply(
        db,
        corrections_dir,
        '["IC 2477"]\n'
        + CITED
        + 'same_as = "IC 5281"\n'
        + '["IC 5281"]\n'
        + CITED
        + "own_object = true\n",
    )
    assert object_id(db, "IC", 2477) == object_id(db, "IC", 5281)
    assert object_id(db, "IC", 5281) != object_id(db, "NGC", 7466)


def test_own_object_that_is_already_true_fails(db, corrections_dir):
    problems = apply_fails(
        db, corrections_dir, '["IC 424"]\n' + CITED + "own_object = true\n"
    )
    assert "already a sky object of its own" in problems


def test_a_split_that_leaves_a_listing_behind_fails(db, corrections_dir):
    # A Caldwell listing that joined through "IC5281" stays on NGC 7466.
    ngc_7466 = object_id(db, "NGC", 7466)
    db.insert_catalog_object(ngc_7466, "C", 99, "")
    db.insert_name(ngc_7466, "C 99", "C")
    db.insert_name(ngc_7466, "IC5281", "C")
    problems = apply_fails(
        db, corrections_dir, '["IC 5281"]\n' + CITED + "own_object = true\n"
    )
    assert (
        "[IC 5281]: own_object leaves NGC 7466, C 99 still named 'IC5281' (from C)"
        in problems
    )


def test_a_stray_name_left_behind_can_be_removed_by_a_correction(db, corrections_dir):
    db.insert_name(object_id(db, "NGC", 7466), "IC 5281", "NGC")
    apply(
        db,
        corrections_dir,
        '["IC 5281"]\n'
        + CITED
        + "own_object = true\n"
        + '["NGC 7466"]\n'
        + CITED
        + 'names.remove = ["IC 5281"]\n',
    )
    assert names(db, "NGC", 7466) == ["NGC 7466"]
    assert names(db, "IC", 5281) == ["IC 5281"]


@pytest.mark.parametrize("identification", ["own_object = true", 'same_as = "IC 2480"'])
def test_moving_an_m_listing_needs_the_ngc_records_m_name_removed(
    db, corrections_dir, identification
):
    # Steinicke's NGC record carries "M 42", so moving the M listing alone
    # leaves NGC 1976 asserting a cross-identification the correction denies.
    move = f'["M 42"]\n{CITED}{identification}\n'
    problems = apply_fails(db, corrections_dir, move)
    assert "leaves NGC 1976 still named 'M 42' (from NGC)" in problems

    apply(
        db,
        corrections_dir,
        move + '["NGC 1976"]\n' + CITED + 'names.remove = ["M 42"]\n',
    )
    assert object_id(db, "M", 42) != object_id(db, "NGC", 1976)
    assert names(db, "NGC", 1976) == ["NGC 1976", "Orion Nebula"]
    assert names(db, "M", 42)[-1] == "M 42"


def test_a_failed_check_rolls_back_the_identifications_too(db, corrections_dir):
    apply_fails(
        db,
        corrections_dir,
        '["IC 2477"]\n'
        + CITED
        + 'same_as = "IC 2480"\n'
        + '["M 42"]\n'
        + CITED
        + "mag = 4.1\nwas.mag = 9.0\n",
    )
    assert object_id(db, "IC", 2477) != object_id(db, "IC", 2480)
