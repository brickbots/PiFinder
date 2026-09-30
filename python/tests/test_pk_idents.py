"""The Perek-Kohoutek import splits V/84 cross-identifications correctly."""

import pytest

from PiFinder.catalog_imports.pk_loader import _split_idents
from PiFinder.db import objects_db

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "field, expected",
    [
        # One row writes "NGC,6742" for NGC 6742.
        ("A55 39,NGC,6742,VV' 472", ["A55 39", "NGC 6742", "VV' 472"]),
        # Blanco designations have no digit and stand alone.
        ("Bl G,ESO 455-48", ["Bl G", "ESO 455-48"]),
        ("Bl  J=K", ["Bl  J=K"]),
        # A lone number after a designation with digits stays its own token.
        ("VV 1,2", ["VV 1", "2"]),
        ("", []),
    ],
)
def test_split_idents(field, expected):
    assert _split_idents(field) == expected


def test_no_pk_name_is_only_a_number_or_a_bare_prefix():
    db = objects_db.ObjectsDatabase()
    db.cursor.execute(
        "SELECT common_name FROM names WHERE origin = 'PK'"
        " AND (trim(common_name) GLOB '[0-9]*' AND trim(common_name) NOT GLOB"
        " '*[^0-9]*' OR trim(common_name) IN ('NGC', 'IC', 'M'))"
    )
    assert db.cursor.fetchall() == []
