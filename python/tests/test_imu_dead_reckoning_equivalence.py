"""
Equivalence tests: the refactored ImuDeadReckoning must produce the same
scope-pointing results as the pre-refactor ImuDeadReckoningLegacy when the
legacy class is configured with identity alignment (solved_cam == solved_scope).

This file is temporary. Delete it (and
PiFinder/pointing_model/imu_dead_reckoning_legacy.py) once the new class
is verified in production.
"""

import numpy as np
import pytest

import PiFinder.pointing_model.quaternion_transforms as qt
from PiFinder.pointing_model.imu_dead_reckoning import ImuDeadReckoning
from PiFinder.pointing_model.imu_dead_reckoning_legacy import (
    ImuDeadReckoningLegacy,
)
from PiFinder.types.coordinates import RaDecRoll


SCREEN_DIRECTIONS = ["flat", "flat3", "left", "right", "straight", "as_bloom"]


def make_imu(axis=(0.0, 0.0, 1.0), theta=0.0):
    return qt.axis_angle2quat(list(axis), theta).normalized()


def assert_radec_close(new_pt, old_pt, abs_tol=1e-9):
    """Compare two RaDecRoll outputs; RA wrap handled via modulo 2pi."""
    assert new_pt is not None and old_pt is not None
    ra_diff = (new_pt.ra - old_pt.ra + np.pi) % (2 * np.pi) - np.pi
    assert ra_diff == pytest.approx(0.0, abs=abs_tol), (
        f"ra: new={new_pt.ra} old={old_pt.ra}"
    )
    assert new_pt.dec == pytest.approx(old_pt.dec, abs=abs_tol), (
        f"dec: new={new_pt.dec} old={old_pt.dec}"
    )
    assert new_pt.roll == pytest.approx(old_pt.roll, abs=abs_tol), (
        f"roll: new={new_pt.roll} old={old_pt.roll}"
    )


@pytest.mark.unit
@pytest.mark.parametrize("screen_direction", SCREEN_DIRECTIONS)
def test_equivalence_mixed_sequence(screen_direction):
    """New `predict` matches legacy `get_scope_radec` through a mixed sequence.

    Legacy class is configured with identity alignment so that scope == cam,
    matching the new class's assumption that the plate-solve input *is* the
    pointing frame.
    """
    new = ImuDeadReckoning(screen_direction)
    old = ImuDeadReckoningLegacy(screen_direction)

    # Identity alignment so legacy's scope == legacy's cam == new's pointing.
    align_radec = RaDecRoll(1.0, 0.3, 0.0)
    old.set_cam2scope_alignment(align_radec, align_radec)

    scenarios = [
        ("solve", RaDecRoll(1.0, 0.3, 0.0), make_imu(theta=0.0)),
        ("predict", None, make_imu(theta=0.1)),
        ("predict", None, make_imu(axis=(1, 0, 0), theta=0.05)),
        ("solve", RaDecRoll(1.2, 0.25, 0.1), make_imu(axis=(0, 1, 0), theta=0.2)),
        ("predict", None, make_imu(axis=(0, 1, 0), theta=0.3)),
        ("predict", None, make_imu(axis=(1, 1, 0), theta=0.15)),
    ]

    for action, radec, q in scenarios:
        if action == "solve":
            new.solve(radec, q)
            old.update_plate_solve_and_imu(radec, q)
            old.update_imu(q)  # legacy needs explicit update_imu to fill q_eq2scope
        else:
            old.update_imu(q)

        new_pt = new.predict(q)
        old_pt = old.get_scope_radec()
        assert_radec_close(new_pt, old_pt)


@pytest.mark.unit
@pytest.mark.parametrize("screen_direction", SCREEN_DIRECTIONS)
def test_equivalence_after_reset(screen_direction):
    """Reset and re-solve produces identical results in both classes."""
    new = ImuDeadReckoning(screen_direction)
    old = ImuDeadReckoningLegacy(screen_direction)

    align = RaDecRoll(0.5, 0.1, 0.0)
    old.set_cam2scope_alignment(align, align)

    new.solve(RaDecRoll(0.5, 0.1, 0.0), make_imu(theta=0.0))
    old.update_plate_solve_and_imu(RaDecRoll(0.5, 0.1, 0.0), make_imu(theta=0.0))

    new.reset()
    # Legacy reset() is buggy (sets q_eq2x = None) -- emulate the intended
    # reset semantics by reinstantiating with a fresh alignment instead.
    old = ImuDeadReckoningLegacy(screen_direction)
    old.set_cam2scope_alignment(align, align)

    assert not new.is_initialized()
    assert new.predict(make_imu(theta=0.2)) is None

    radec = RaDecRoll(2.0, -0.2, 0.05)
    q = make_imu(axis=(0, 1, 0), theta=0.3)
    new.solve(radec, q)
    old.update_plate_solve_and_imu(radec, q)
    old.update_imu(q)

    assert_radec_close(new.predict(q), old.get_scope_radec())


@pytest.mark.unit
def test_equivalence_predict_before_solve_returns_none():
    """New class returns None before any solve; legacy never wrote outputs."""
    new = ImuDeadReckoning("flat")
    assert new.predict(make_imu(theta=0.1)) is None


@pytest.mark.unit
def test_equivalence_invalid_pointing_is_no_op_for_both():
    """Invalid plate-solve input leaves both classes unchanged."""
    new = ImuDeadReckoning("flat")
    old = ImuDeadReckoningLegacy("flat")
    align = RaDecRoll(1.0, 0.3, 0.0)
    old.set_cam2scope_alignment(align, align)

    invalid = RaDecRoll(np.nan, np.nan, np.nan)
    q = make_imu(theta=0.1)
    new.solve(invalid, q)
    old.update_plate_solve_and_imu(invalid, q)

    assert not new.is_initialized()
    assert old.tracking is False
