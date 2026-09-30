"""Designation parsing for catalog imports.

A designation with a compound numeric part ("M 1-92", a Minkowski planetary
nebula) must not collapse into a different catalog entry (Messier 92). The
Perek-Kohoutek name column has 188 Minkowski names, so a parser that drops
the hyphen links 145 of them to the wrong object.
"""

import pytest

from PiFinder.catalog_imports.catalog_import_utils import parse_designation


@pytest.mark.unit
@pytest.mark.parametrize(
    "designation, expected",
    [
        ("NGC 40", ("NGC", 40)),
        ("NGC  7008", ("NGC", 7008)),
        ("NGC7008", ("NGC", 7008)),
        ("IC 418", ("IC", 418)),
        ("M 27", ("M", 27)),
        ("M  76", ("M", 76)),
        ("Messier 31", ("M", 31)),
        ("Abell 43", ("Abl", 43)),
        ("PN A66   80", ("Abl", 80)),
        ("Sh 2-176", ("Sh2", 176)),
        ("SH 2-216", ("Sh2", 216)),
        ("Sharpless 176", ("Sh2", 176)),
        ("Cr 24", ("Col", 24)),
        ("Collinder 24", ("Col", 24)),
        ("Caldwell 14", ("C", 14)),
        ("Barnard 33", ("B", 33)),
        ("Arp 244", ("Arp", 244)),
        ("Lyn 12", ("Lyn", 12)),
        ("Har 5", ("Har", 5)),
        ("Ta2 21", ("Ta2", 21)),
    ],
)
def test_recognized_designations(designation, expected):
    assert parse_designation(designation) == expected


@pytest.mark.unit
def test_one_letter_prefixes_need_a_source_alias():
    # "A 58" and "B 53" are the double stars of Aitken and van den Bos in
    # double-star sources, so only a source that means Abell adds "a".
    assert parse_designation("A 58") is None
    assert parse_designation("B 53") is None
    assert parse_designation("A 43", extra_aliases={"a": "Abl"}) == ("Abl", 43)


@pytest.mark.unit
@pytest.mark.parametrize(
    "designation",
    [
        # Minkowski planetary nebulae. Stripping the hyphen would read these
        # as Messier 11, 29, 32 and 92.
        "M 1-1",
        "M 2-9",
        "M 3-2",
        "M 1-92",
        # Haro planetary nebulae, not Herschel 400 entries.
        "H 1-1",
        "H 3-29",
        # Two halves of one object; expanding it is the loader's job, because
        # the trailing digits replace the tail of the first number.
        "NGC 650-1",
        # Designation families PiFinder has no catalog for.
        "K 2- 1",
        "He 2-47",
        "Vy 2-2",
        "Hu 1-2",
        "Wray 16-93",
        "IRAS 06518-1041",
        # Designations that end in digits that are not a sequence.
        "WDS 00001+7508",
        "PK 120+09.1",
        # Nothing to key on.
        "40",
        "",
        "Andromeda",
    ],
)
def test_rejected_designations(designation):
    assert parse_designation(designation) is None
