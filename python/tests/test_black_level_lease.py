"""Plan B regression tests: the accepted pedestal is a lease, not a latch."""

import numpy as np
import pytest

from PiFinder.sqm.black_level import BlackLevelTracker


def _feed_clean_ramp(tracker, pedestal=236.0, rate=300.0, n=20):
    """Randomized sweep-like ramp: exposures 25 ms - 1 s, exact line."""
    rng = np.random.default_rng(42)
    exps = np.geomspace(0.025, 1.0, n)
    rng.shuffle(exps)
    for e in exps:
        tracker.add_sample(float(e), pedestal + rate * float(e))


@pytest.mark.unit
def test_clean_ramp_is_accepted():
    tracker = BlackLevelTracker(bias_offset=238.0)
    _feed_clean_ramp(tracker)
    assert tracker.pedestal() == pytest.approx(236.0, abs=0.2)
    assert tracker.stderr() < 0.6


@pytest.mark.unit
def test_accepted_pedestal_expires_without_fresh_fit(monkeypatch):
    """2026-07-17 regression: one accepted fit must not rule the session.

    After acceptance, every later refit fails a gate (pinned exposure -> no
    lever arm). The old latch kept the value forever; the lease returns None
    once max_age_seconds passes, so callers fall back to the profile.
    """
    fake_now = [1000.0]
    monkeypatch.setattr("PiFinder.sqm.black_level.time.monotonic", lambda: fake_now[0])
    tracker = BlackLevelTracker(bias_offset=238.0, max_age_seconds=900.0)
    _feed_clean_ramp(tracker)
    assert tracker.pedestal() is not None

    # Pinned-exposure night: 1 s frames only. 60 samples turn the window
    # over completely; refits keep re-accepting while ramp points remain in
    # the window (still a valid lever arm), then stop qualifying once the
    # ratio collapses to 1.0. The lease keeps serving meanwhile...
    fake_now[0] += 600.0
    for _ in range(60):
        tracker.add_sample(1.0, 536.0)
    assert tracker.pedestal() is not None

    # ...but with the window fully pinned no fresh fit can renew it, and
    # once max_age_seconds pass since the last acceptance it expires —
    # even though more (unusable) samples keep arriving.
    fake_now[0] += 901.0
    for _ in range(5):
        tracker.add_sample(1.0, 536.0)
    assert tracker.pedestal() is None


@pytest.mark.unit
def test_cloud_grade_fit_rejected_by_tighter_gate():
    """The 2026-07-17 poison fit passed at stderr 0.97 < 1.0. Honest fits on
    the 27-sweep archive run 0.10-0.69; the 0.6 default must reject a
    0.97-grade window while accepting a clean ramp."""
    tracker = BlackLevelTracker(bias_offset=238.0)
    # Drifting-sky window: line plus a smooth trend produces an inflated
    # intercept error in the ~1 ADU range, like the cloud window.
    rng = np.random.default_rng(7)
    exps = np.linspace(0.5, 1.0, 20)
    for i, e in enumerate(exps):
        drift = 3.0 * i / len(exps)
        noise = float(rng.normal(0.0, 1.2))
        tracker.add_sample(float(e), 236.0 + 300.0 * float(e) + drift + noise)
    assert tracker.pedestal() is None


@pytest.mark.unit
def test_reset_clears_lease():
    tracker = BlackLevelTracker(bias_offset=238.0)
    _feed_clean_ramp(tracker)
    tracker.reset()
    assert tracker.pedestal() is None
    assert tracker.dump()["age_seconds"] is None
