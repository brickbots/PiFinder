"""
Unit tests for ImuDeadReckoning in PiFinder.pointing_model.imu_dead_reckoning.

Tests pin the contract of the refactored class:
    - solve(pointing, q_x2imu): solves for q_eq2x; no-op on invalid input
    - predict(q_x2imu): returns RaDecRoll | None
    - is_initialized(): True after a valid solve, False otherwise
    - reset(): clears q_eq2x

Equivalence with the pre-refactor implementation is tested separately in
test_imu_dead_reckoning_equivalence.py.
"""

import numpy as np
import pytest
import quaternion

import PiFinder.pointing_model.quaternion_transforms as qt
from PiFinder.pointing_model.imu_dead_reckoning import ImuDeadReckoning
from PiFinder.types.coordinates import RaDecRoll


# ---------------------------------------------------------------- helpers ---

def assert_quat_close(q1, q2, abs_tol=1e-9):
    """Compare two quaternions modulo the double cover."""
    assert qt.get_quat_angular_diff(q1, q2) == pytest.approx(0.0, abs=abs_tol)


def make_imu(axis=(0.0, 0.0, 1.0), theta=0.3):
    return qt.axis_angle2quat(list(axis), theta).normalized()


@pytest.fixture
def dr():
    return ImuDeadReckoning("flat")


# ============================================== 1. solve ===================

@pytest.mark.unit
class TestSolve:
    """Behaviour of ImuDeadReckoning.solve()."""

    def test_solve_sets_q_eq2x_and_initializes(self, dr):
        ra, dec, roll = 1.234, -0.4, 0.1
        q_x2imu = make_imu(theta=0.3)

        dr.solve(RaDecRoll(ra, dec, roll), q_x2imu)

        expected_q_eq2pointing = qt.radec2q_eq(ra, dec, roll)
        expected_q_eq2x = (
            expected_q_eq2pointing * (q_x2imu * dr.q_imu2pointing).conj()
        ).normalized()
        assert_quat_close(dr.q_eq2x, expected_q_eq2x)
        assert dr.is_initialized() is True
        assert abs(dr.q_eq2x.norm() - 1.0) < 1e-12

    def test_solve_with_invalid_pointing_is_no_op(self, dr):
        invalid = RaDecRoll(np.nan, np.nan, np.nan)
        assert invalid.valid is False

        dr.solve(invalid, make_imu())
        assert dr.is_initialized() is False

    def test_solve_with_nan_imu_is_no_op(self, dr):
        dr.solve(RaDecRoll(1.0, 0.2, 0.0), quaternion.quaternion(np.nan))
        assert dr.is_initialized() is False

    def test_resolve_renews_q_eq2x(self, dr):
        dr.solve(RaDecRoll(1.0, 0.2, 0.0), make_imu(theta=0.0))
        first = quaternion.quaternion(dr.q_eq2x)

        dr.solve(RaDecRoll(1.1, 0.25, 0.0), make_imu(theta=0.4))
        assert qt.get_quat_angular_diff(first, dr.q_eq2x) > 1e-6


# ============================================== 2. predict =================

@pytest.mark.unit
class TestPredict:
    """Behaviour of ImuDeadReckoning.predict()."""

    def test_predict_before_solve_returns_none(self, dr):
        assert dr.predict(make_imu()) is None

    def test_predict_with_same_quat_returns_input_radec(self, dr):
        ra, dec, roll = 1.0, 0.2, 0.0
        q = make_imu(theta=0.3)
        dr.solve(RaDecRoll(ra, dec, roll), q)

        out = dr.predict(q)
        assert out is not None
        out_ra, out_dec, out_roll = out.get()
        ra_diff = (out_ra - ra + np.pi) % (2 * np.pi) - np.pi
        assert ra_diff == pytest.approx(0.0, abs=1e-9)
        assert out_dec == pytest.approx(dec, abs=1e-9)
        assert out_roll == pytest.approx(roll, abs=1e-9)

    def test_predict_rotates_by_imu_delta(self, dr):
        q0 = make_imu(theta=0.0)
        dr.solve(RaDecRoll(1.0, 0.2, 0.0), q0)
        q_eq2pointing_at_solve = (
            dr.q_eq2x * q0 * dr.q_imu2pointing
        ).normalized()

        delta = 0.05
        q1 = (q0 * qt.axis_angle2quat([0, 0, 1], delta)).normalized()
        out = dr.predict(q1)
        q_eq2pointing_pred = (
            dr.q_eq2x * q1 * dr.q_imu2pointing
        ).normalized()
        moved = qt.get_quat_angular_diff(
            q_eq2pointing_at_solve, q_eq2pointing_pred
        )
        assert moved == pytest.approx(delta, abs=1e-9)
        # Sanity: predicted RaDecRoll matches the predicted quaternion.
        assert_quat_close(out.as_quaternion(), q_eq2pointing_pred)

    def test_predict_returns_unit_quaternion_radec(self, dr):
        dr.solve(RaDecRoll(1.0, 0.2, 0.0), make_imu(theta=0.0))
        out = dr.predict(make_imu(theta=0.4))
        assert isinstance(out, RaDecRoll)
        assert out.valid is True

    @pytest.mark.parametrize(
        "ra,dec,roll",
        [
            (0.5, 0.3, 0.0),
            (3.0, -0.7, 0.2),
            (1.7, 0.0, -0.4),
            (5.9, 0.45, 0.1),
        ],
    )
    def test_solve_then_predict_round_trip(self, dr, ra, dec, roll):
        """solve(radec, q) then predict(q) returns radec (mod 2pi on RA)."""
        q = make_imu(theta=0.2)
        dr.solve(RaDecRoll(ra, dec, roll), q)
        out_ra, out_dec, out_roll = dr.predict(q).get()
        ra_diff = (out_ra - ra + np.pi) % (2 * np.pi) - np.pi
        assert ra_diff == pytest.approx(0.0, abs=1e-9)
        assert out_dec == pytest.approx(dec, abs=1e-9)
        assert out_roll == pytest.approx(roll, abs=1e-9)


# ============================================== 3. reset ===================

@pytest.mark.unit
class TestReset:
    """Behaviour of ImuDeadReckoning.reset()."""

    def test_reset_clears_initialization(self, dr):
        dr.solve(RaDecRoll(1.0, 0.2, 0.0), make_imu())
        assert dr.is_initialized() is True

        dr.reset()
        assert dr.is_initialized() is False
        assert isinstance(dr.q_eq2x, quaternion.quaternion)
        assert np.isnan(dr.q_eq2x)

    def test_predict_after_reset_returns_none(self, dr):
        dr.solve(RaDecRoll(1.0, 0.2, 0.0), make_imu())
        dr.reset()
        assert dr.predict(make_imu(theta=0.5)) is None

    def test_can_re_solve_after_reset(self, dr):
        dr.solve(RaDecRoll(1.0, 0.2, 0.0), make_imu())
        dr.reset()

        dr.solve(RaDecRoll(2.0, -0.1, 0.0), make_imu(theta=0.4))
        assert dr.is_initialized() is True
        assert not np.isnan(dr.q_eq2x)


# =============================== 4. State sequence =========================

@pytest.mark.unit
def test_full_sequence_solve_predict_solve():
    """solve(A) -> predict -> solve(B) renews q_eq2x and preserves predict()."""
    dr = ImuDeadReckoning("flat")
    assert dr.is_initialized() is False

    radec_A = RaDecRoll(1.0, 0.2, 0.0)
    q_imu_A = make_imu(theta=0.0)
    dr.solve(radec_A, q_imu_A)
    q_eq2x_after_A = quaternion.quaternion(dr.q_eq2x)
    assert dr.is_initialized() is True

    # Predict mid-flight.
    q_mid = (q_imu_A * qt.axis_angle2quat([0, 0, 1], 0.05)).normalized()
    mid = dr.predict(q_mid)
    assert mid is not None

    # Second solve at a different pointing renews q_eq2x.
    radec_B = RaDecRoll(1.05, 0.21, 0.0)
    q_imu_B = (q_imu_A * qt.axis_angle2quat([0, 0, 1], 0.10)).normalized()
    dr.solve(radec_B, q_imu_B)
    assert qt.get_quat_angular_diff(q_eq2x_after_A, dr.q_eq2x) > 1e-6


# =============================== 5. Constructor ============================

@pytest.mark.unit
def test_invalid_screen_direction_raises():
    with pytest.raises(ValueError):
        ImuDeadReckoning("sideways")
