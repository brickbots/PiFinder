"""Tests for the per-image sweep metadata record."""

import json

import numpy as np
import pytest

from PiFinder.camera_interface import sweep_frame_record


@pytest.mark.unit
def test_record_with_full_metadata_and_frame():
    metadata = {
        "ExposureTime": 99987,
        "AnalogueGain": np.float64(16.0),
        "DigitalGain": 1.0,
        "SensorTemperature": 27.0,
        "SensorBlackLevels": (4096, 4096, 4096, 4096),
        "ColourGains": (1.5, 1.5),
        "Lux": 0.002,
        "FrameDuration": 100000,
    }
    frame = np.full((8, 8), 240, dtype=np.uint16)
    frame[0, 0] = 4095

    record = sweep_frame_record(3, 100000, metadata, frame, bit_depth=12)

    assert record["index"] == 3
    assert record["exp_ms"] == 100.0
    assert record["sensor_temp_c"] == 27.0
    assert record["camera_metadata"]["ExposureTime"] == 99987
    assert record["camera_metadata"]["SensorBlackLevels"] == [4096, 4096, 4096, 4096]
    assert record["raw_stats"]["max_adu"] == 4095.0
    assert record["raw_stats"]["median_adu"] == 240.0
    assert record["raw_stats"]["saturated_fraction"] == pytest.approx(1 / 64)
    # Everything must survive json.dumps (numpy scalars, tuples coerced)
    json.dumps(record)


@pytest.mark.unit
def test_record_without_metadata_or_frame():
    record = sweep_frame_record(1, 25000, None, None, bit_depth=None)

    assert record["sensor_temp_c"] is None
    assert record["camera_metadata"]["SensorTemperature"] is None
    assert "raw_stats" not in record
    json.dumps(record)
