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
