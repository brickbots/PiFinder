"""Tests for the sky-brightness field carried by an observation's notes.

An observation records the SQM reading behind it so a log entry can later
be read in the light it was made under. The reading is only trustworthy
when the radiometer produced one: SQM.value holds a plausible dark-sky
default from the moment shared state exists, so source is what separates a
measurement from that default. The radiometer's own sample count and
frame scatter travel with the value, which is what makes its stability
judgeable after the fact; the full rolling window stays in telemetry.
"""

import json

import pytest

from PiFinder.obslog import sqm_note
from PiFinder.state import SQM


def _details(**overrides):
    details = {
        "radiometer_samples": 9,
        "radiometer_frame_scatter": 0.0412345,
        "pedestal_source": "optical_black",
        # The published details also carry whole window dumps; these must
        # not end up in an observation's notes.
        "window_radiometer": {"n_samples": 9, "samples": [{"sequence": 1}]},
    }
    details.update(overrides)
    return details


@pytest.mark.unit
def test_measured_reading_carries_value_and_stability():
    note = sqm_note(SQM(value=21.237, source="Radiometer"), _details())

    assert note["value"] == 21.24
    assert note["source"] == "Radiometer"
    assert note["samples"] == 9
    assert note["scatter"] == 0.041
    assert note["pedestal_source"] == "optical_black"


@pytest.mark.unit
def test_window_dumps_stay_out_of_the_note():
    note = sqm_note(SQM(value=21.0, source="Radiometer"), _details())

    assert "window_radiometer" not in note
    # Small enough to sit in every log entry without bloating it.
    assert len(json.dumps(note)) < 200


@pytest.mark.unit
def test_unmeasured_default_is_not_recorded_as_a_reading():
    # A fresh SQM reads 20.15/"None" before anything has been measured;
    # logging that would invent a sky brightness for the observation.
    assert sqm_note(SQM(), None) is None
    assert sqm_note(SQM(value=20.15, source="None"), _details()) is None
    assert sqm_note(None, _details()) is None


@pytest.mark.unit
def test_manual_reading_is_recorded_without_radiometer_stats():
    note = sqm_note(SQM(value=20.8, source="Manual"), {})

    assert note == {"value": 20.8, "source": "Manual"}


@pytest.mark.unit
def test_missing_stability_fields_are_omitted_not_nulled():
    note = sqm_note(
        SQM(value=21.0, source="Radiometer"),
        _details(radiometer_frame_scatter=None, pedestal_source=None),
    )

    assert "scatter" not in note
    assert "pedestal_source" not in note
    assert note["samples"] == 9


@pytest.mark.unit
def test_note_is_json_serializable_with_numpy_scalars():
    numpy = pytest.importorskip("numpy")
    note = sqm_note(
        SQM(value=21.0, source="Radiometer"),
        _details(radiometer_frame_scatter=numpy.float64(0.25)),
    )

    assert json.loads(json.dumps(note))["scatter"] == 0.25
