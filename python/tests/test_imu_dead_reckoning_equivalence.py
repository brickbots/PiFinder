"""
Equivalence tests: the dual-axis ImuDeadReckoning must produce the same
camera and aligned pointing results as the pre-refactor
ImuDeadReckoningLegacy when fed matched inputs.

The new class accepts a (camera, aligned) pair on every solve() and
replaces q_cam2aligned. The legacy class takes a one-shot
set_cam2scope_alignment() and then receives camera-only solves. To
match outputs we feed the new class an `aligned` value derived from the
same fixed offset that configures the legacy class.

This file is temporary. Delete it (and
PiFinder/pointing_model/imu_dead_reckoning_legacy.py) once the new
class is verified in production.
"""

import numpy as np
import pytest
import quaternion

import PiFinder.pointing_model.quaternion_transforms as qt
from PiFinder.pointing_model.imu_dead_reckoning import ImuDeadReckoning
from PiFinder.pointing_model.imu_dead_reckoning_legacy import (
    ImuDeadReckoningLegacy,
)
from PiFinder.types.coordinates import RaDecRoll


SCREEN_DIRECTIONS = [
    "flat",
    "flat3",
    "left",
    "right",
    "straight",
    "as_bloom",
    "as_heart",
    "v4_left",
    "v4_right",
    "v4_straight",
]

# Alignment offset for the "real_offset" parametrize value: derives a fixed
# q_cam2aligned from a (cam, aligned) pair that the legacy class uses for
# set_cam2scope_alignment(). The same offset is then applied to every
# subsequent `camera` to produce the matching `aligned` for the new class.
ALIGN_CAM_INIT = RaDecRoll(1.0, 0.3, 0.0)
ALIGN_ALIGNED_INIT_REAL = RaDecRoll(1.07, 0.32, 0.05)
ALIGN_ALIGNED_INIT_IDENTITY = ALIGN_CAM_INIT

ALIGNMENT_CASES = [
    pytest.param(ALIGN_ALIGNED_INIT_IDENTITY, id="identity"),
    pytest.param(ALIGN_ALIGNED_INIT_REAL, id="real_offset"),
]


def make_imu(axis=(0.0, 0.0, 1.0), theta=0.0):
    return qt.axis_angle2quat(list(axis), theta).normalized()


def assert_radec_close(new_pt, old_pt, abs_tol=1e-9):
    """Compare two RaDecRoll outputs; RA wrap handled via modulo 2pi."""
    assert new_pt is not None and old_pt is not None
    ra_diff = (new_pt.ra - old_pt.ra + np.pi) % (2 * np.pi) - np.pi
    assert ra_diff == pytest.approx(
        0.0, abs=abs_tol
    ), f"ra: new={new_pt.ra} old={old_pt.ra}"
    assert new_pt.dec == pytest.approx(
        old_pt.dec, abs=abs_tol
    ), f"dec: new={new_pt.dec} old={old_pt.dec}"
    assert new_pt.roll == pytest.approx(
        old_pt.roll, abs=abs_tol
    ), f"roll: new={new_pt.roll} old={old_pt.roll}"


def derive_aligned(
    camera: RaDecRoll, q_cam2aligned: quaternion.quaternion
) -> RaDecRoll:
    """Given a camera pointing and the fixed alignment offset, return
    the matching aligned pointing."""
    q_eq2cam = camera.as_quaternion()
    q_eq2aligned = (q_eq2cam * q_cam2aligned).normalized()
    return RaDecRoll.from_quaternion(q_eq2aligned)


def compute_q_cam2aligned(
    cam_init: RaDecRoll, aligned_init: RaDecRoll
) -> quaternion.quaternion:
    """Replicates the new IDR's solve()-time formula so the test can
    derive matching aligned values for arbitrary cameras."""
    q_eq2cam = cam_init.as_quaternion()
    q_eq2aligned = aligned_init.as_quaternion()
    return (q_eq2cam.conj() * q_eq2aligned).normalized()


@pytest.mark.unit
@pytest.mark.parametrize("screen_direction", SCREEN_DIRECTIONS)
@pytest.mark.parametrize("aligned_init", ALIGNMENT_CASES)
def test_equivalence_mixed_sequence(screen_direction, aligned_init):
    """New `predict` matches legacy `get_cam_radec` / `get_scope_radec`
    through a mixed sequence, for both identity and real-offset alignment.
    """
    new = ImuDeadReckoning(screen_direction)
    old = ImuDeadReckoningLegacy(screen_direction)

    # Configure legacy with the alignment pair; derive the fixed offset
    # the new class needs so its solve()-time q_cam2aligned matches.
    old.set_cam2scope_alignment(ALIGN_CAM_INIT, aligned_init)
    q_offset = compute_q_cam2aligned(ALIGN_CAM_INIT, aligned_init)

    cameras_and_qs = [
        ("solve", RaDecRoll(1.0, 0.3, 0.0), make_imu(theta=0.0)),
        ("predict", None, make_imu(theta=0.1)),
        ("predict", None, make_imu(axis=(1, 0, 0), theta=0.05)),
        ("solve", RaDecRoll(1.2, 0.25, 0.1), make_imu(axis=(0, 1, 0), theta=0.2)),
        ("predict", None, make_imu(axis=(0, 1, 0), theta=0.3)),
        ("predict", None, make_imu(axis=(1, 1, 0), theta=0.15)),
    ]

    for action, camera, q in cameras_and_qs:
        if action == "solve":
            aligned = derive_aligned(camera, q_offset)
            new.solve(camera, aligned, q)
            old.update_plate_solve_and_imu(camera, q)
            old.update_imu(q)  # legacy needs explicit update_imu to fill q_eq2scope
        else:
            old.update_imu(q)

        predicted = new.predict(q)
        assert predicted is not None
        cam_pred, aligned_pred = predicted
        assert_radec_close(cam_pred, old.get_cam_radec())
        assert_radec_close(aligned_pred, old.get_scope_radec())


@pytest.mark.unit
@pytest.mark.parametrize("screen_direction", SCREEN_DIRECTIONS)
@pytest.mark.parametrize("aligned_init", ALIGNMENT_CASES)
def test_equivalence_after_reset(screen_direction, aligned_init):
    """Reset and re-solve produces identical results in both classes."""
    new = ImuDeadReckoning(screen_direction)
    old = ImuDeadReckoningLegacy(screen_direction)

    old.set_cam2scope_alignment(ALIGN_CAM_INIT, aligned_init)
    q_offset = compute_q_cam2aligned(ALIGN_CAM_INIT, aligned_init)

    cam_warmup = RaDecRoll(0.5, 0.1, 0.0)
    aligned_warmup = derive_aligned(cam_warmup, q_offset)
    new.solve(cam_warmup, aligned_warmup, make_imu(theta=0.0))
    old.update_plate_solve_and_imu(cam_warmup, make_imu(theta=0.0))

    new.reset()
    # Legacy reset() is buggy (sets q_eq2x = None) -- emulate the intended
    # reset semantics by reinstantiating with a fresh alignment instead.
    old = ImuDeadReckoningLegacy(screen_direction)
    old.set_cam2scope_alignment(ALIGN_CAM_INIT, aligned_init)

    assert not new.is_initialized()
    assert new.predict(make_imu(theta=0.2)) is None

    camera = RaDecRoll(2.0, -0.2, 0.05)
    aligned = derive_aligned(camera, q_offset)
    q = make_imu(axis=(0, 1, 0), theta=0.3)
    new.solve(camera, aligned, q)
    old.update_plate_solve_and_imu(camera, q)
    old.update_imu(q)

    predicted = new.predict(q)
    assert predicted is not None
    cam_pred, aligned_pred = predicted
    assert_radec_close(cam_pred, old.get_cam_radec())
    assert_radec_close(aligned_pred, old.get_scope_radec())


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
    new.solve(invalid, invalid, q)
    old.update_plate_solve_and_imu(invalid, q)

    assert not new.is_initialized()
    assert old.tracking is False
