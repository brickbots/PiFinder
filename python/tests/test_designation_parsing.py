"""Designation parsing for catalog imports.

The regression these guard against: `ObjectFinder` used to resolve aliases by
stripping spaces *and hyphens*, so any designation with a compound numeric
part collapsed into a plausible but wrong sequence number. Feeding it the
Perek-Kohoutek name column produced 147 matches, 145 of them false — 188 of
those names are Minkowski planetary nebulae ("M 1-92"), not Messier objects.
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
        ("A 43", ("Abl", 43)),
        ("Abell 43", ("Abl", 43)),
        ("PN A66   80", ("Abl", 80)),
        ("Sh 2-176", ("Sh2", 176)),
        ("SH 2-216", ("Sh2", 216)),
        ("Sharpless 176", ("Sh2", 176)),
        ("Cr 24", ("Col", 24)),
        ("Collinder 24", ("Col", 24)),
        ("Caldwell 14", ("C", 14)),
        ("Barnard 33", ("B", 33)),
    ],
)
def test_recognized_designations(designation, expected):
    assert parse_designation(designation) == expected


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
        # Nothing to key on.
        "40",
        "",
        "Andromeda",
    ],
)
def test_rejected_designations(designation):
    assert parse_designation(designation) is None
