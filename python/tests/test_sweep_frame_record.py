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
def test_statistics_cover_the_crop_not_the_full_sensor():
    """Sweeps archive the whole sensor, but raw_stats must stay on the crop.

    The margins are vignetted, so measuring them would shift every mean and
    percentile and end comparability with the pre-full-sensor archive -- the
    black-level-versus-temperature series these records exist for.
    """
    from PiFinder.sqm import get_camera_profile

    profile = get_camera_profile("imx462")
    full = np.full(profile.raw_size[::-1], 1000, dtype=np.uint16)
    # Darken only what the crop discards, so a statistic computed over the
    # full sensor cannot possibly match one computed over the crop.
    kept = np.zeros_like(full, dtype=bool)
    top, bottom = profile.crop_y
    left, right = profile.crop_x
    kept[top : full.shape[0] - bottom, left : full.shape[1] - right] = True
    full[~kept] = 200

    record = sweep_frame_record(
        1, 100000, None, profile.crop_and_rotate(full), bit_depth=12
    )

    assert record["raw_stats"]["mean_adu"] == pytest.approx(1000.0)
    assert record["raw_stats"]["min_adu"] == 1000.0
    # The sibling TIFF is full-sensor, so the record must say what it covers.
    assert record["raw_stats"]["extent"] == "crop"


@pytest.mark.unit
def test_record_without_metadata_or_frame():
    record = sweep_frame_record(1, 25000, None, None, bit_depth=None)

    assert record["sensor_temp_c"] is None
    assert record["camera_metadata"]["SensorTemperature"] is None
    assert "raw_stats" not in record
    json.dumps(record)


@pytest.mark.unit
def test_tracker_window_dumps_are_json_serializable():
    from PiFinder.sqm.black_level import BlackLevelTracker
    from PiFinder.sqm.clouds import CloudEstimator
    from PiFinder.sqm.radiometer import RadiometerAccumulator
    from PiFinder.sqm.wings import WingEstimator

    black = BlackLevelTracker(bias_offset=256.0)
    for i in range(15):
        black.add_sample(0.1 + i * 0.06, 256.0 + (0.1 + i * 0.06) * 40.0)
    dump = black.dump()
    assert dump["n_samples"] == 15
    assert len(dump["samples_exposure_sec"]) == 15
    assert dump["pedestal"] == pytest.approx(256.0, abs=0.5)
    json.dumps(dump)

    clouds = CloudEstimator(clear_zero_point=14.5, clear_sky_brightness=18.5)
    for _ in range(4):
        clouds.add_sample(mzero=14.0, exposure_sec=0.5, sky_brightness=18.4)
    dump = clouds.dump()
    assert len(dump["recent_normalized_zp"]) == clouds.smooth_samples
    assert dump["baseline"] is not None
    json.dumps(dump)

    wings = WingEstimator()
    dump = wings.dump()
    assert dump["is_conditioned"] is False
    assert dump["samples_enclosed_fraction"] == []
    json.dumps(dump)

    radiometer = RadiometerAccumulator()
    radiometer.add(
        {
            "sequence": 7,
            "captured_at": 1000.0,
            "exposure_sec": 0.4,
            "background_per_pixel": 300.5,
        }
    )
    dump = radiometer.dump()
    assert dump["n_samples"] == 1
    assert dump["last_sequence"] == 7
    json.dumps(dump)


@pytest.mark.unit
class TestExposureSettling:
    """The sweep must not label a frame with an exposure the sensor wasn't at.

    The IMX290/462 serves exactly three frames at the old exposure after a
    change. Flushing a fixed two left the next capture stale, so the sweep's
    processed PNG was one step behind the raw TIFF beside it and the radiometer
    sample described the PNG rather than the labelled exposure.
    """

    class _FakeCamera:
        """Applies a new exposure only after `lag` frames, like the real sensor."""

        def __init__(self, lag=3):
            self.lag = lag
            self.requested = None
            self.applied = None
            self._since_change = 0
            self.captures = 0
            self.last_frame_metadata = {}

        def set_exposure(self, us):
            self.requested = us
            self._since_change = 0

        def capture(self):
            self.captures += 1
            self._since_change += 1
            if self._since_change > self.lag:
                self.applied = self.requested
            self.last_frame_metadata = {"ExposureTime": self.applied}
            return None

    def _settler(self, cam):
        from PiFinder.camera_interface import CameraInterface

        cam._settle_exposure = CameraInterface._settle_exposure.__get__(cam)
        return cam

    def test_settles_on_the_actual_exposure(self):
        cam = self._settler(self._FakeCamera(lag=3))
        cam.applied = 25_000
        cam.set_exposure(400_000)

        cam._settle_exposure(400_000)

        assert cam.last_frame_metadata["ExposureTime"] == 400_000

    def test_two_flushes_would_have_been_stale(self):
        """Pin the original bug: the old fixed count leaves the wrong exposure."""
        cam = self._FakeCamera(lag=3)
        cam.applied = 25_000
        cam.set_exposure(400_000)
        cam.capture()
        cam.capture()  # the old code stopped here

        assert cam.last_frame_metadata["ExposureTime"] == 25_000

    def test_gives_up_rather_than_spinning(self):
        cam = self._settler(self._FakeCamera(lag=99))
        cam.applied = 25_000
        cam.set_exposure(400_000)

        n = cam._settle_exposure(400_000, max_frames=4)

        assert n == 4

    def test_backend_without_exposure_metadata_does_not_burn_frames(self):
        cam = self._settler(self._FakeCamera(lag=0))
        cam.applied = None
        cam.set_exposure(400_000)

        n = cam._settle_exposure(400_000, max_frames=8)

        assert n == 1
