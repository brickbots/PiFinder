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


def _rggb(height, width, red, green, blue):
    """Synthetic RGGB mosaic with a known, distinct value per CFA site."""
    a = np.zeros((height, width), dtype=np.uint16)
    a[0::2, 0::2] = red
    a[0::2, 1::2] = green
    a[1::2, 0::2] = green
    a[1::2, 1::2] = blue
    return a


@pytest.mark.unit
@pytest.mark.parametrize("height,width", [(1080, 1920), (1085, 1925), (215, 215)])
def test_sky_colour_is_sampled_on_the_right_mosaic_sites(height, width):
    """Red must come off the red sites, at any frame size.

    Blue is deliberately far from red here: a half-site phase slip reads blue
    as red and would otherwise pass silently, since the result stays a
    plausible number. The odd sizes exercise the border-evening -- a 215-px
    frame gives a 21-px border, and an odd border is exactly what shifts the
    crop onto the wrong CFA phase.
    """
    profile = get_camera_profile("imx462")
    sample = collect_radiometer_sample(
        _rggb(height, width, red=850, green=1000, blue=500),
        profile,
        1.0,
        sequence=1,
        captured_at=0.0,
    )
    assert sample["background_red"] == pytest.approx(850.0)
    assert sample["background_green"] == pytest.approx(1000.0)


@pytest.mark.unit
def test_rotated_or_odd_cropped_profiles_refuse_to_report_colour():
    """The invariants the sampler assumes are checked, not assumed.

    A 180-degree rotation leaves the green sites alone but swaps red and blue,
    so the pre-existing green extraction never had to care and this one does.
    Reporting no colour costs a fallback to the constant zero point; reporting
    blue as red would shift the published SQM by up to the clamp width.
    """
    from dataclasses import replace

    from PiFinder.sqm.radiometer import _mosaic_phase_is_rggb

    profile = get_camera_profile("imx462")
    assert _mosaic_phase_is_rggb(profile)

    for broken in (
        replace(profile, rotation_90=2),  # 180 deg: red <-> blue
        replace(profile, rotation_90=1),  # 90 deg: transposes the CFA
        replace(profile, crop_x=(471, 471)),  # odd origin: half-site slip
        replace(profile, crop_y=(51, 51)),
        replace(profile, format="SBGGR12"),  # Bayer, but not RGGB
    ):
        assert not _mosaic_phase_is_rggb(broken)
        sample = collect_radiometer_sample(
            _rggb(256, 256, red=850, green=1000, blue=500),
            broken,
            1.0,
            sequence=1,
            captured_at=0.0,
        )
        assert "background_red" not in sample


@pytest.mark.unit
def test_shipped_colour_profiles_hold_the_phase_invariants():
    """Guard the profiles themselves, not just the sampler.

    These three are RGGB, unrotated and even-cropped today, which is why the
    colour term is correct as shipped. If a future orientation change breaks
    that, this fails here rather than quietly biasing everyone's SQM.
    """
    from PiFinder.sqm.radiometer import _mosaic_phase_is_rggb

    for name in ("imx462", "imx290", "hq"):
        profile = get_camera_profile(name)
        assert _mosaic_phase_is_rggb(profile), name
        assert profile.rotation_90 == 0
        assert profile.crop_x[0] % 2 == 0 and profile.crop_y[0] % 2 == 0


@pytest.mark.unit
def test_mono_profile_reports_no_colour():
    profile = get_camera_profile("imx296")
    sample = collect_radiometer_sample(
        np.full((256, 256), 300, dtype=np.uint16),
        profile,
        1.0,
        sequence=1,
        captured_at=0.0,
    )
    assert "background_red" not in sample
    assert "background_green" not in sample


@pytest.mark.unit
def test_colour_sample_survives_the_round_trip_to_a_corrected_value():
    """End to end: mosaic in, colour-corrected zero point out.

    The other colour tests hand-build background_red/green; this one is the
    only path that proves the sampler and the estimator agree on units.
    """
    profile = get_camera_profile("imx462")
    pedestal = profile.bias_offset
    sample = collect_radiometer_sample(
        _rggb(512, 512, red=int(pedestal + 100), green=int(pedestal + 100), blue=200),
        profile,
        1.0,
        sequence=1,
        captured_at=0.0,
    )
    _, details = radiometric_sqm(sample, profile, pedestal=pedestal)
    assert details["sky_red_over_green"] == pytest.approx(1.0)
    assert details["radiometric_zero_point_effective"] == pytest.approx(
        profile.radiometric_zero_point
        + profile.radiometric_colour_slope * (1.0 - profile.radiometric_colour_pivot)
    )


@pytest.mark.unit
def test_a_phase_slip_really_would_read_blue_as_red():
    """Pin the failure the guard prevents, so its rationale stays checkable.

    ``crop_and_rotate`` runs before the sampler, so a rotated profile hands it
    an already-rotated frame. Feed the sampler that frame directly and red
    comes back as blue -- silently, still a plausible sky level. This is the
    whole reason _mosaic_phase_is_rggb refuses those profiles.
    """
    from PiFinder.sqm.radiometer import _sky_red_green

    profile = get_camera_profile("imx462")
    frame = _rggb(256, 256, red=850, green=1000, blue=500)

    red, green = _sky_red_green(frame, profile, 0.10, 4)
    assert (red, green) == (850.0, 1000.0)

    # What the sampler would have seen had the profile been rotated 180.
    slipped_red, slipped_green = _sky_red_green(np.rot90(frame, 2), profile, 0.10, 4)
    assert slipped_red == 500.0  # blue, not red
    assert slipped_green == 1000.0  # green sites are rotation-invariant
