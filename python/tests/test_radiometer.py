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


@pytest.mark.unit
def test_colour_term_moves_the_zero_point_with_sky_colour():
    """A bare sensor's zero point must track sky colour.

    LP sky is green-weighted (low R/G), airglow is grey and NIR-rich (R/G ~1).
    The sensor sees that difference and a V-band meter does not, so a single
    constant is wrong at one end. Same sky signal, different colour, must give
    a different answer.
    """
    from PiFinder.sqm import get_camera_profile
    from PiFinder.sqm.radiometer import radiometric_sqm

    prof = get_camera_profile("imx462")
    base = dict(
        sequence=1,
        captured_at=0.0,
        exposure_sec=1.0,
        background_per_pixel=400.0,
        pixels_per_side=980,
    )
    ped = prof.bias_offset

    lp = dict(base, background_red=ped + 0.85 * 100, background_green=ped + 100)
    dark = dict(base, background_red=ped + 1.00 * 100, background_green=ped + 100)

    v_lp, d_lp = radiometric_sqm(lp, prof, pedestal=ped)
    v_dark, _ = radiometric_sqm(dark, prof, pedestal=ped)

    assert v_lp is not None and v_dark is not None
    # 0.15 of R/G at the fitted slope
    assert (v_dark - v_lp) == pytest.approx(
        0.15 * prof.radiometric_colour_slope, abs=1e-6
    )
    assert d_lp["sky_red_over_green"] == pytest.approx(0.85, abs=1e-6)
    # The reported constant must stay the profile value, not the applied one,
    # so archives remain comparable across this change.
    assert d_lp["radiometric_zero_point"] == pytest.approx(prof.radiometric_zero_point)
    # At the pivot the correction is exactly zero -- that is what makes the
    # no-colour fallback land on a sensible value rather than the fit intercept.
    assert d_lp["radiometric_zero_point_effective"] == pytest.approx(
        prof.radiometric_zero_point, abs=1e-9
    )


@pytest.mark.unit
def test_missing_colour_falls_back_to_the_constant():
    """No colour (mono sensor, or a malformed sample) must not break or drift."""
    from PiFinder.sqm import get_camera_profile
    from PiFinder.sqm.radiometer import radiometric_sqm

    prof = get_camera_profile("imx462")
    sample = dict(
        sequence=1,
        captured_at=0.0,
        exposure_sec=1.0,
        background_per_pixel=400.0,
        pixels_per_side=980,
    )
    v, d = radiometric_sqm(sample, prof, pedestal=prof.bias_offset)
    assert v is not None
    assert d["radiometric_zero_point"] == pytest.approx(prof.radiometric_zero_point)
    assert d["radiometric_zero_point_effective"] == pytest.approx(
        prof.radiometric_zero_point
    )
    assert "sky_red_over_green" not in d


@pytest.mark.unit
def test_colour_ratio_is_clamped_to_the_calibrated_range():
    """Never extrapolate off the end of the fit."""
    from PiFinder.sqm import get_camera_profile
    from PiFinder.sqm.radiometer import radiometric_sqm

    prof = get_camera_profile("imx462")
    ped = prof.bias_offset
    wild = dict(
        sequence=1,
        captured_at=0.0,
        exposure_sec=1.0,
        background_per_pixel=400.0,
        pixels_per_side=980,
        background_red=ped + 500.0,
        background_green=ped + 100.0,  # R/G = 5
    )
    _, d = radiometric_sqm(wild, prof, pedestal=ped)
    assert d["sky_red_over_green"] == pytest.approx(5.0)
    assert d["sky_red_over_green_clamped"] == pytest.approx(
        prof.radiometric_colour_range[1]
    )


@pytest.mark.unit
def test_ir_cut_sensor_keeps_a_plain_constant():
    """HQ has a factory IR-cut, so there is no NIR leak to correct."""
    from PiFinder.sqm import get_camera_profile

    assert get_camera_profile("hq").radiometric_colour_slope == 0.0
    assert get_camera_profile("imx296").radiometric_colour_slope == 0.0
