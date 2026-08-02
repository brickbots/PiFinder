"""
Drift guard for the .pifinder format.

The hand-written reader/writer (PiFinder.obslist_formats) and the JSON Schema in
docs/ax/catalog/obslist-formats/ are two independent descriptions of the same
format. These tests fail if they disagree: the schema must accept what the writer
emits and the example file, and must reject the same malformed files the reader
rejects.

The schema is descriptive, not generative -- nothing in the app reads it -- so
this test is what keeps it honest.
"""

import json
from pathlib import Path

import pytest

from PiFinder.obslist_formats import (
    MagnitudeObject,
    ObsList,
    ObsListEntry,
    PiFinderFormatError,
    SizeObject,
    read_pifinder,
    write_pifinder,
)

jsonschema = pytest.importorskip("jsonschema")

_DOCS = Path(__file__).resolve().parents[2] / "docs/ax/catalog/obslist-formats"
_SCHEMA_PATH = _DOCS / "pifinder-list.schema.json"
_EXAMPLE_PATH = _DOCS / "example.pifinder"


def _schema() -> dict:
    return json.loads(_SCHEMA_PATH.read_text())


def _validator():
    schema = _schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


@pytest.mark.unit
def test_schema_is_valid_draft_2020_12():
    jsonschema.Draft202012Validator.check_schema(_schema())


@pytest.mark.unit
def test_example_file_matches_schema():
    _validator().validate(json.loads(_EXAMPLE_PATH.read_text()))


@pytest.mark.unit
def test_writer_output_matches_schema():
    # Exercise every branch the writer can emit: catalog-keyed, bare/structured
    # magnitude, flat and nested extents, and a per-entry epoch override.
    obs = ObsList(
        name="W",
        epoch="J2000",
        entries=[
            ObsListEntry(name="ngc", ra=0.0, dec=0.0, catalog_code="NGC", sequence=224),
            ObsListEntry(
                name="star", ra=10.0, dec=20.0, obj_type="*", mag=MagnitudeObject([7.0])
            ),
            ObsListEntry(
                name="ell",
                ra=30.0,
                dec=40.0,
                obj_type="Gx",
                size=SizeObject([180.0, 60.0], position_angle=30.0),
            ),
            ObsListEntry(
                name="line",
                ra=50.0,
                dec=60.0,
                obj_type="Neb",
                size=SizeObject([[50.0, 60.0], [50.5, 60.5]], geometry="polyline"),
            ),
            ObsListEntry(
                name="nova", ra=70.0, dec=-10.0, obj_type="Nova", epoch="J2016.0"
            ),
        ],
    )
    _validator().validate(json.loads(write_pifinder(obs)))


# Malformed files the hand-written reader rejects -- the schema must reject them too.
_INVALID = [
    ('{"name": "x", "objects": []}', "missing-version"),
    ('{"version": 2, "name": "x", "objects": []}', "bad-version"),
    ('{"version": 1, "name": "x"}', "missing-objects"),
    (
        '{"version": 1, "name": "x", "objects": [{"catalog_code": "NGC"}]}',
        "catalog-entry-missing-sequence",
    ),
    (
        '{"version": 1, "name": "x", "objects": '
        '[{"name": "a", "obj_type": "?", "ra": 1.0}]}',
        "coordinate-entry-missing-dec",
    ),
    (
        '{"version": 1, "name": "x", "objects": '
        '[{"name": "a", "obj_type": "?", "ra": 1.0, "dec": 2.0, '
        '"extents": {"shape": [[1.0, 2.0]]}}]}',
        "nested-extents-without-geometry",
    ),
]


@pytest.mark.unit
@pytest.mark.parametrize("text,reason", _INVALID, ids=[r for _, r in _INVALID])
def test_reader_and_schema_agree_on_rejection(text, reason):
    with pytest.raises(PiFinderFormatError):
        read_pifinder(text)
    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(json.loads(text))
