"""Unit tests for the cloud/dew-guarded transmission estimator."""

import numpy as np

from PiFinder.sqm.clouds import CloudEstimator


def _clear(est, n=20, zp=14.81, sky=18.5, exp=0.5):
    """Feed n clear frames (nominal zero point, nominal sky)."""
    for _ in range(n):
        est.add_sample(zp + 2.5 * np.log10(exp), exp, sky_brightness=sky)


def test_clear_night_no_cloud():
    est = CloudEstimator(clear_zero_point=14.81, clear_sky_brightness=18.5)
    _clear(est)
    assert est.is_cloudy() is False
    assert est.deficit() < 0.1


def test_cloud_flagged_when_stars_dim_and_sky_brightens():
    est = CloudEstimator(clear_zero_point=14.81, clear_sky_brightness=18.5)
    _clear(est)
    # Cloud: zero point drops 0.6 mag, sky brightens 0.6 mag (SQM 18.5 -> 17.9).
    exp = 0.5
    for _ in range(5):
        est.add_sample((14.81 - 0.6) + 2.5 * np.log10(exp), exp, sky_brightness=17.9)
    assert est.is_cloudy() is True
    assert est.deficit() > 0.3


def test_dew_not_flagged_when_stars_and_sky_dim_together():
    # Dew/optics attenuate stars AND sky equally: zero point drops but the sky
    # does NOT brighten (SQM stays put). No sky excess -> not cloud.
    est = CloudEstimator(clear_zero_point=14.81, clear_sky_brightness=18.5)
    _clear(est)
    exp = 0.5
    for _ in range(5):
        est.add_sample((14.81 - 0.6) + 2.5 * np.log10(exp), exp, sky_brightness=18.5)
    assert est.is_cloudy() is False


def test_no_flag_without_sky_brightness():
    # Without the published SQM the guard cannot confirm cloud.
    est = CloudEstimator(clear_zero_point=14.81, clear_sky_brightness=18.5)
    for _ in range(20):
        est.add_sample(14.81 + 2.5 * np.log10(0.5), 0.5)
    exp = 0.5
    for _ in range(5):
        est.add_sample((14.81 - 0.6) + 2.5 * np.log10(exp), exp)
    assert est.is_cloudy() is False


def test_none_before_conditioning_without_seed():
    est = CloudEstimator()  # no factory seed
    est.add_sample(14.81 + 2.5 * np.log10(0.5), 0.5, sky_brightness=18.5)
    assert est.is_cloudy() is None
    assert est.deficit() is None


def test_factory_seed_detects_boot_under_cloud():
    # First frames are already cloudy; the factory seed supplies the baseline
    # so cloud is caught without any prior clear conditioning.
    est = CloudEstimator(
        clear_zero_point=14.81, clear_sky_brightness=18.5, min_samples=12
    )
    exp = 0.5
    est.add_sample((14.81 - 0.7) + 2.5 * np.log10(exp), exp, sky_brightness=17.8)
    assert est.is_cloudy() is True


def test_cloudy_frames_do_not_erode_baseline():
    est = CloudEstimator(clear_zero_point=14.81, clear_sky_brightness=18.5)
    _clear(est, n=30)
    base_before = est.baseline()
    exp = 0.5
    for _ in range(30):  # a long cloudy stretch
        est.add_sample((14.81 - 0.8) + 2.5 * np.log10(exp), exp, sky_brightness=17.7)
    # Asymmetric feeding: the clear baseline held despite sustained cloud.
    assert est.baseline() == base_before
    assert est.is_cloudy() is True


def test_recovers_to_clear_after_cloud_passes():
    est = CloudEstimator(clear_zero_point=14.81, clear_sky_brightness=18.5)
    _clear(est, n=20)
    exp = 0.5
    for _ in range(6):
        est.add_sample((14.81 - 0.7) + 2.5 * np.log10(exp), exp, sky_brightness=17.8)
    assert est.is_cloudy() is True
    _clear(est, n=6)
    assert est.is_cloudy() is False


def test_optics_deficit_does_not_erode_clear_baseline():
    est = CloudEstimator(clear_zero_point=14.81, clear_sky_brightness=18.5)
    _clear(est, n=20)
    base = est.baseline()
    exp = 0.5
    for _ in range(40):
        est.add_sample((14.81 - 0.7) + 2.5 * np.log10(exp), exp, 18.5)
    assert est.is_cloudy() is False
    assert est.baseline() == base
    assert est.conditioned()
