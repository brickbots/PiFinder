"""Unit tests for the sky-vs-exposure black-level tracker."""

import numpy as np
import pytest

from PiFinder.sqm.black_level import BlackLevelTracker


def _feed(tracker, pedestal, rate, exposures, noise=0.0, seed=0):
    rng = np.random.default_rng(seed)
    for exp in exposures:
        bg = pedestal + rate * exp + (rng.normal(0, noise) if noise else 0.0)
        tracker.add_sample(exp, bg)


def test_recovers_pedestal_from_clean_ramp():
    t = BlackLevelTracker(bias_offset=238.0)
    _feed(t, pedestal=236.0, rate=40.0, exposures=np.linspace(0.05, 1.0, 20))
    assert t.pedestal() == pytest.approx(236.0, abs=0.2)


def test_none_until_min_samples():
    t = BlackLevelTracker(bias_offset=238.0, min_samples=12)
    _feed(t, 238.0, 30.0, np.linspace(0.1, 1.0, 8))
    assert t.pedestal() is None


def test_none_without_exposure_lever_arm():
    # All samples at ~one exposure: intercept is an unreliable extrapolation.
    t = BlackLevelTracker(bias_offset=238.0)
    _feed(t, 238.0, 30.0, np.full(20, 0.5))
    assert t.pedestal() is None


def test_rejects_drifting_sky():
    # Background rises with time independently of exposure (moonrise/twilight):
    # the single-line fit's intercept stderr blows past the gate.
    t = BlackLevelTracker(bias_offset=238.0, max_intercept_stderr=1.0)
    rng = np.random.default_rng(1)
    for i, exp in enumerate(np.tile(np.linspace(0.1, 1.0, 5), 4)):
        drift = 3.0 * i  # ADU of sky brightening unrelated to exposure
        t.add_sample(exp, 238.0 + 30.0 * exp + drift + rng.normal(0, 0.5))
    assert t.pedestal() is None


def test_rejects_fit_far_from_profile():
    # A pathological intercept far from the profile constant is refused.
    t = BlackLevelTracker(bias_offset=238.0, max_offset_deviation=12.0)
    _feed(t, pedestal=200.0, rate=40.0, exposures=np.linspace(0.05, 1.0, 20))
    assert t.pedestal() is None


def test_rejects_negative_slope():
    # Background falling with exposure is unphysical for a sky ramp.
    t = BlackLevelTracker(bias_offset=238.0)
    for exp in np.linspace(0.05, 1.0, 20):
        t.add_sample(exp, 238.0 - 20.0 * exp)
    assert t.pedestal() is None


def test_stable_gate_drops_sample():
    t = BlackLevelTracker(bias_offset=238.0, min_samples=6)
    for exp in np.linspace(0.05, 1.0, 20):
        t.add_sample(exp, 238.0 + 40.0 * exp, stable=False)
    assert t.pedestal() is None
    assert t.state()[2] == 0  # nothing recorded


def test_tracks_a_shift_within_the_window():
    t = BlackLevelTracker(bias_offset=238.0, max_samples=20, min_samples=10)
    _feed(t, pedestal=238.0, rate=40.0, exposures=np.linspace(0.05, 1.0, 20))
    assert t.pedestal() == pytest.approx(238.0, abs=0.2)
    # Pedestal shifts +3 ADU; refill the whole window at the new level.
    _feed(t, pedestal=241.0, rate=40.0, exposures=np.linspace(0.05, 1.0, 20))
    assert t.pedestal() == pytest.approx(241.0, abs=0.3)


def test_ignores_invalid_inputs():
    t = BlackLevelTracker(bias_offset=238.0, min_samples=4)
    t.add_sample(0.0, 238.0)  # zero exposure
    t.add_sample(-0.1, 238.0)  # negative exposure
    t.add_sample(0.5, float("nan"))  # nan background
    t.add_sample(0.5, None)  # missing background
    assert t.state()[2] == 0


# ---------------------------------------------------------------------------
# Digital gain. It multiplies the sky signal but not the pedestal, so a window
# whose reported gain moves is a set of lines with a shared intercept and
# different slopes. Fitting against gain-scaled exposure recovers it exactly.
# ---------------------------------------------------------------------------


def _feed_with_gain(tracker, pedestal, rate, exposures, gains, pass_ratio):
    for exp, gain in zip(exposures, gains):
        bg = pedestal + rate * gain * exp
        tracker.add_sample(exp, bg, gain_ratio=gain if pass_ratio else 1.0)


def test_gain_jitter_corrupts_the_intercept_when_ignored():
    # Measured spread on rich-imx462/sweep_20260719_041913: a driver that folds
    # white balance into the sensor gain reports 1.017-1.197 inside one sweep.
    rng = np.random.default_rng(3)
    exposures = np.linspace(0.05, 1.0, 24)
    gains = rng.uniform(1.017, 1.197, size=exposures.size)

    ignored = BlackLevelTracker(bias_offset=238.0)
    _feed_with_gain(ignored, 236.0, 120.0, exposures, gains, pass_ratio=False)

    corrected = BlackLevelTracker(bias_offset=238.0)
    _feed_with_gain(corrected, 236.0, 120.0, exposures, gains, pass_ratio=True)

    assert corrected.pedestal() == pytest.approx(236.0, abs=0.05)
    # The uncorrected fit is either rejected outright or lands off the truth by
    # far more than the corrected one. Either way it must not quietly agree.
    assert ignored.pedestal() is None or abs(ignored.pedestal() - 236.0) > 0.5


def test_constant_gain_changes_nothing():
    exposures = np.linspace(0.05, 1.0, 20)
    plain = BlackLevelTracker(bias_offset=238.0)
    _feed(plain, pedestal=236.5, rate=40.0, exposures=exposures)

    scaled = BlackLevelTracker(bias_offset=238.0)
    _feed_with_gain(
        scaled, 236.5, 40.0, exposures, np.full(exposures.size, 1.0), pass_ratio=True
    )
    assert scaled.pedestal() == pytest.approx(plain.pedestal())


@pytest.mark.parametrize("ratio", [None, 0.0, -1.0, float("nan")])
def test_unusable_gain_ratio_falls_back_to_one(ratio):
    t = BlackLevelTracker(bias_offset=238.0)
    for exp in np.linspace(0.05, 1.0, 20):
        t.add_sample(exp, 236.0 + 40.0 * exp, gain_ratio=ratio)
    assert t.pedestal() == pytest.approx(236.0, abs=0.2)
