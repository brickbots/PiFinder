from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

from PiFinder.sqm.camera_profiles import get_camera_profile
from PiFinder.sqm.radiometer import (
    RadiometerAccumulator,
    collect_radiometer_sample,
    extract_photometry_image,
    radiometric_sqm,
)


@pytest.mark.unit
def test_extracts_only_averaged_bayer_green():
    profile = get_camera_profile("imx462")
    raw = np.full((64, 64), 999, dtype=np.uint16)
    raw[0::2, 1::2] = 100
    raw[1::2, 0::2] = 120
    assert np.all(extract_photometry_image(raw, profile) == 110)


@pytest.mark.unit
def test_sparse_median_ignores_small_bright_sources():
    profile = get_camera_profile("imx296")
    raw = np.full((256, 256), 80, dtype=np.uint16)
    raw[100:110, 100:110] = 1000
    sample = collect_radiometer_sample(raw, profile, 0.5, sequence=3, captured_at=10.0)
    assert sample["background_per_pixel"] == 80.0
    assert sample["sequence"] == 3
    assert sample["pixels_per_side"] == 256


@pytest.mark.unit
def test_radiometric_result_is_exposure_invariant():
    profile = get_camera_profile("imx462")
    base = {
        "sequence": 1,
        "captured_at": 1.0,
        "pixels_per_side": 490,
        "method": "test",
    }
    short, _ = radiometric_sqm(
        {**base, "exposure_sec": 0.25, "background_per_pixel": 248.0}, profile
    )
    long, _ = radiometric_sqm(
        {**base, "exposure_sec": 0.50, "background_per_pixel": 258.0}, profile
    )
    assert short == pytest.approx(long)


@pytest.mark.unit
def test_rejects_unresolved_background():
    profile = get_camera_profile("imx462")
    value, details = radiometric_sqm(
        {
            "sequence": 1,
            "captured_at": 1.0,
            "exposure_sec": 0.5,
            "background_per_pixel": 239.0,
            "pixels_per_side": 490,
        },
        profile,
    )
    assert value is None
    assert details["failure_reason"] == "background_not_resolved_above_pedestal"


@pytest.mark.unit
def test_accumulator_deduplicates_and_expires_samples():
    profile = get_camera_profile("imx462")
    acc = RadiometerAccumulator(max_age_seconds=5.0)
    sample = {
        "sequence": 1,
        "captured_at": 10.0,
        "exposure_sec": 0.5,
        "background_per_pixel": 258.0,
        "pixels_per_side": 490,
    }
    assert acc.add(sample)
    assert not acc.add(sample)
    value, details = acc.estimate(profile, now=12.0)
    assert value is not None
    assert details["radiometer_samples"] == 1
    value, details = acc.estimate(profile, now=20.0)
    assert value is None
    assert details["failure_reason"] == "no_recent_resolved_radiometer_samples"


@pytest.mark.unit
def test_solver_publishes_radiometer_without_solution(monkeypatch):
    from PiFinder import solver

    shared = MagicMock()
    shared.sqm.return_value = SimpleNamespace(last_update=None)
    shared.sqm_details.return_value = {}
    calc = MagicMock()
    calc.profile = get_camera_profile("imx462")
    calc.noise_floor_estimator.dark_current_calibrated = False
    acc = RadiometerAccumulator()
    sample = {
        "sequence": 7,
        "captured_at": 100.0,
        "exposure_sec": 0.5,
        "background_per_pixel": 258.0,
        "pixels_per_side": 490,
    }
    monkeypatch.setattr(
        solver.timez,
        "local_now",
        lambda: SimpleNamespace(isoformat=lambda: "1970-01-01T00:01:40+00:00"),
    )
    assert solver.update_radiometric_sqm(shared, calc, acc, sample, now=100.0)
    published = shared.set_sqm.call_args.args[0]
    assert published.source == "Radiometer"
    assert published.value > 0


@pytest.mark.unit
def test_recent_conditioned_optics_deficit_corrects_radiometer(monkeypatch):
    from PiFinder import solver

    shared = MagicMock()
    shared.sqm.return_value = SimpleNamespace(last_update=None)
    shared.sqm_details.return_value = {
        "optics_attenuation_candidate": True,
        "transmission_deficit": 0.7,
        "transmission_diagnostic_at": 99.0,
    }
    calc = MagicMock()
    calc.profile = get_camera_profile("imx462")
    calc.noise_floor_estimator.dark_current_calibrated = False
    acc = RadiometerAccumulator()
    sample = {
        "sequence": 8,
        "captured_at": 100.0,
        "exposure_sec": 0.5,
        "background_per_pixel": 258.0,
        "pixels_per_side": 490,
    }
    uncorrected, _ = radiometric_sqm(sample, calc.profile)
    monkeypatch.setattr(
        solver.timez,
        "local_now",
        lambda: SimpleNamespace(isoformat=lambda: "1970-01-01T00:01:40+00:00"),
    )
    assert solver.update_radiometric_sqm(shared, calc, acc, sample, now=100.0)
    published = shared.set_sqm.call_args.args[0]
    assert published.value == pytest.approx(uncorrected - 0.7)
