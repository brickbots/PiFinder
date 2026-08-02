"""
Unit tests for ImuDeadReckoning in PiFinder.pointing_model.imu_dead_reckoning.

Tests pin the contract of the dual-axis class:
    - solve(camera, aligned, q_x2imu): solves for q_eq2x and q_cam2aligned;
      no-op if either pointing is invalid or q_x2imu is NaN.
    - predict(q_x2imu): returns (camera, aligned) RaDecRoll tuple or None.
    - is_initialized(): True after a valid solve, False otherwise.
    - reset(): clears q_eq2x and q_cam2aligned.

Equivalence with the pre-refactor implementation is tested separately in
test_imu_dead_reckoning_equivalence.py.
"""

import numpy as np
import pytest
import quaternion

import PiFinder.pointing_model.quaternion_transforms as qt
from PiFinder.pointing_model.imu_dead_reckoning import ImuDeadReckoning, _quat_has_nan
from PiFinder.types.coordinates import RaDecRoll


# ---------------------------------------------------------------- helpers ---


def assert_quat_close(q1, q2, abs_tol=1e-9):
    """Compare two quaternions modulo the double cover."""
    assert qt.get_quat_angular_diff(q1, q2) == pytest.approx(0.0, abs=abs_tol)


def assert_radec_close(p1: RaDecRoll, p2: RaDecRoll, abs_tol=1e-9):
    """Compare two RaDecRoll values, handling RA wrap."""
    ra_diff = (p1.ra - p2.ra + np.pi) % (2 * np.pi) - np.pi
    assert ra_diff == pytest.approx(0.0, abs=abs_tol)
    assert p1.dec == pytest.approx(p2.dec, abs=abs_tol)
    assert p1.roll == pytest.approx(p2.roll, abs=abs_tol)


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
        camera = RaDecRoll(ra, dec, roll)
        q_x2imu = make_imu(theta=0.3)

        dr.solve(camera, camera, q_x2imu)

        expected_q_eq2cam = qt.radec2q_eq(ra, dec, roll)
        expected_q_eq2x = (
            expected_q_eq2cam * (q_x2imu * dr.q_imu2cam).conj()
        ).normalized()
        assert_quat_close(dr.q_eq2x, expected_q_eq2x)
        assert dr.is_initialized() is True
        assert abs(dr.q_eq2x.norm() - 1.0) < 1e-12

    def test_solve_with_identity_alignment_sets_identity_q_cam2aligned(self, dr):
        camera = RaDecRoll(1.0, 0.2, 0.0)
        dr.solve(camera, camera, make_imu(theta=0.3))

        # q_cam2aligned should be the identity rotation (modulo double cover).
        assert_quat_close(dr.q_cam2aligned, quaternion.quaternion(1, 0, 0, 0))

    def test_solve_with_offset_sets_nonidentity_q_cam2aligned(self, dr):
        camera = RaDecRoll(1.0, 0.2, 0.0)
        aligned = RaDecRoll(1.01, 0.21, 0.0)
        dr.solve(camera, aligned, make_imu(theta=0.3))

        # Distinct enough that q_cam2aligned is not the identity.
        assert (
            qt.get_quat_angular_diff(
                dr.q_cam2aligned, quaternion.quaternion(1, 0, 0, 0)
            )
            > 1e-6
        )

    def test_solve_with_invalid_camera_is_no_op(self, dr):
        invalid = RaDecRoll(np.nan, np.nan, np.nan)
        valid = RaDecRoll(1.0, 0.2, 0.0)
        dr.solve(invalid, valid, make_imu())
        assert dr.is_initialized() is False

    def test_solve_with_invalid_aligned_is_no_op(self, dr):
        invalid = RaDecRoll(np.nan, np.nan, np.nan)
        valid = RaDecRoll(1.0, 0.2, 0.0)
        dr.solve(valid, invalid, make_imu())
        assert dr.is_initialized() is False

    def test_solve_with_nan_imu_is_no_op(self, dr):
        camera = RaDecRoll(1.0, 0.2, 0.0)
        dr.solve(camera, camera, quaternion.quaternion(np.nan))
        assert dr.is_initialized() is False

    def test_resolve_renews_q_eq2x(self, dr):
        camera_a = RaDecRoll(1.0, 0.2, 0.0)
        dr.solve(camera_a, camera_a, make_imu(theta=0.0))
        first = quaternion.quaternion(dr.q_eq2x)

        camera_b = RaDecRoll(1.1, 0.25, 0.0)
        dr.solve(camera_b, camera_b, make_imu(theta=0.4))
        assert qt.get_quat_angular_diff(first, dr.q_eq2x) > 1e-6


# ============================================== 2. predict =================


@pytest.mark.unit
class TestPredict:
    """Behaviour of ImuDeadReckoning.predict()."""

    def test_predict_before_solve_returns_none(self, dr):
        assert dr.predict(make_imu()) is None

    def test_predict_returns_tuple_of_two_radecroll(self, dr):
        camera = RaDecRoll(1.0, 0.2, 0.0)
        dr.solve(camera, camera, make_imu(theta=0.0))
        out = dr.predict(make_imu(theta=0.4))
        assert out is not None
        assert len(out) == 2
        cam_pred, aligned_pred = out
        assert isinstance(cam_pred, RaDecRoll)
        assert isinstance(aligned_pred, RaDecRoll)
        assert cam_pred.valid is True
        assert aligned_pred.valid is True

    def test_predict_with_identity_alignment_returns_identical_pointings(self, dr):
        camera = RaDecRoll(1.0, 0.2, 0.0)
        dr.solve(camera, camera, make_imu(theta=0.0))
        cam_pred, aligned_pred = dr.predict(make_imu(theta=0.4))
        assert_radec_close(cam_pred, aligned_pred)

    def test_predict_with_offset_returns_distinct_pointings(self, dr):
        camera = RaDecRoll(1.0, 0.2, 0.0)
        aligned = RaDecRoll(1.05, 0.22, 0.0)
        q = make_imu(theta=0.0)
        dr.solve(camera, aligned, q)

        cam_pred, aligned_pred = dr.predict(q)
        # At the solve sample, predictions reproduce the inputs.
        assert_radec_close(cam_pred, camera)
        assert_radec_close(aligned_pred, aligned)

    def test_predict_with_same_quat_returns_input_radec(self, dr):
        camera = RaDecRoll(1.0, 0.2, 0.0)
        q = make_imu(theta=0.3)
        dr.solve(camera, camera, q)

        cam_pred, aligned_pred = dr.predict(q)
        assert_radec_close(cam_pred, camera)
        assert_radec_close(aligned_pred, camera)

    def test_predict_rotates_camera_by_imu_delta(self, dr):
        q0 = make_imu(theta=0.0)
        camera = RaDecRoll(1.0, 0.2, 0.0)
        dr.solve(camera, camera, q0)
        q_eq2cam_at_solve = (dr.q_eq2x * q0 * dr.q_imu2cam).normalized()

        delta = 0.05
        q1 = (q0 * qt.axis_angle2quat([0, 0, 1], delta)).normalized()
        cam_pred, _ = dr.predict(q1)
        q_eq2cam_pred = (dr.q_eq2x * q1 * dr.q_imu2cam).normalized()
        moved = qt.get_quat_angular_diff(q_eq2cam_at_solve, q_eq2cam_pred)
        assert moved == pytest.approx(delta, abs=1e-9)
        # Sanity: predicted RaDecRoll matches the predicted quaternion.
        assert_quat_close(cam_pred.as_quaternion(), q_eq2cam_pred)

    def test_predict_aligned_offset_preserved_under_imu_motion(self, dr):
        """The angular separation between camera and aligned is fixed by
        q_cam2aligned and should be invariant under IMU motion."""
        camera = RaDecRoll(1.0, 0.2, 0.0)
        aligned = RaDecRoll(1.05, 0.22, 0.0)
        q0 = make_imu(theta=0.0)
        dr.solve(camera, aligned, q0)
        original_offset = qt.get_quat_angular_diff(
            camera.as_quaternion(), aligned.as_quaternion()
        )

        q1 = make_imu(axis=(0, 1, 0), theta=0.3)
        cam_pred, aligned_pred = dr.predict(q1)
        predicted_offset = qt.get_quat_angular_diff(
            cam_pred.as_quaternion(), aligned_pred.as_quaternion()
        )
        assert predicted_offset == pytest.approx(original_offset, abs=1e-9)

    @pytest.mark.parametrize(
        "ra,dec,roll",
        [
            (0.5, 0.3, 0.0),
            (3.0, -0.7, 0.2),
            (1.7, 0.0, -0.4),
            (5.9, 0.45, 0.1),
        ],
    )
    def test_solve_then_predict_round_trip_identity_alignment(self, dr, ra, dec, roll):
        """solve(radec, radec, q) then predict(q) returns radec on both axes."""
        camera = RaDecRoll(ra, dec, roll)
        q = make_imu(theta=0.2)
        dr.solve(camera, camera, q)
        cam_pred, aligned_pred = dr.predict(q)
        assert_radec_close(cam_pred, camera)
        assert_radec_close(aligned_pred, camera)


# ============================================== 3. reset ===================


@pytest.mark.unit
class TestReset:
    """Behaviour of ImuDeadReckoning.reset()."""

    def test_reset_clears_q_eq2x_and_q_cam2aligned(self, dr):
        camera = RaDecRoll(1.0, 0.2, 0.0)
        aligned = RaDecRoll(1.05, 0.22, 0.0)
        dr.solve(camera, aligned, make_imu())
        assert dr.is_initialized() is True
        assert not _quat_has_nan(dr.q_cam2aligned)

        dr.reset()
        assert dr.is_initialized() is False
        assert isinstance(dr.q_eq2x, quaternion.quaternion)
        assert isinstance(dr.q_cam2aligned, quaternion.quaternion)
        assert _quat_has_nan(dr.q_eq2x)
        assert _quat_has_nan(dr.q_cam2aligned)

    def test_predict_after_reset_returns_none(self, dr):
        camera = RaDecRoll(1.0, 0.2, 0.0)
        dr.solve(camera, camera, make_imu())
        dr.reset()
        assert dr.predict(make_imu(theta=0.5)) is None

    def test_can_re_solve_after_reset(self, dr):
        camera = RaDecRoll(1.0, 0.2, 0.0)
        dr.solve(camera, camera, make_imu())
        dr.reset()

        camera_b = RaDecRoll(2.0, -0.1, 0.0)
        dr.solve(camera_b, camera_b, make_imu(theta=0.4))
        assert dr.is_initialized() is True
        assert not _quat_has_nan(dr.q_eq2x)
        assert not _quat_has_nan(dr.q_cam2aligned)


# =============================== 4. State sequence =========================


@pytest.mark.unit
def test_full_sequence_solve_predict_solve():
    """solve(A) -> predict -> solve(B) renews q_eq2x and preserves predict()."""
    dr = ImuDeadReckoning("flat")
    assert dr.is_initialized() is False

    radec_A = RaDecRoll(1.0, 0.2, 0.0)
    q_imu_A = make_imu(theta=0.0)
    dr.solve(radec_A, radec_A, q_imu_A)
    q_eq2x_after_A = quaternion.quaternion(dr.q_eq2x)
    assert dr.is_initialized() is True

    # Predict mid-flight.
    q_mid = (q_imu_A * qt.axis_angle2quat([0, 0, 1], 0.05)).normalized()
    mid = dr.predict(q_mid)
    assert mid is not None
    assert len(mid) == 2

    # Second solve at a different pointing renews q_eq2x.
    radec_B = RaDecRoll(1.05, 0.21, 0.0)
    q_imu_B = (q_imu_A * qt.axis_angle2quat([0, 0, 1], 0.10)).normalized()
    dr.solve(radec_B, radec_B, q_imu_B)
    assert qt.get_quat_angular_diff(q_eq2x_after_A, dr.q_eq2x) > 1e-6


# =============================== 5. Constructor ============================


@pytest.mark.unit
def test_invalid_screen_direction_raises():
    with pytest.raises(ValueError):
        ImuDeadReckoning("sideways")


@pytest.mark.unit
def test_q_imu2cam_as_bloom():
    """Physical axis correspondences for the AS Bloom build (rev4 board:
    IMU on the back side of the UI board; derived with
    pointing_model/docs/imu2cam_tool.html under the rev4 depiction --
    supersedes the value read off a rev3 depiction of the same
    arrangement)."""
    R = quaternion.as_rotation_matrix(ImuDeadReckoning._q_imu2cam("as_bloom"))
    # columns = camera axes expressed in IMU coordinates
    assert np.allclose(R[:, 0], [1, 0, 0], atol=1e-9)  # image left  = +x_imu
    assert np.allclose(R[:, 1], [0, -1, 0], atol=1e-9)  # image up    = -y_imu
    assert np.allclose(R[:, 2], [0, 0, -1], atol=1e-9)  # boresight   = -z_imu


@pytest.mark.unit
def test_q_imu2cam_as_heart():
    """Physical axis correspondences for the AS Heart build (rev4 board:
    IMU on the back side of the UI board; derived with
    pointing_model/docs/imu2cam_tool.html under the rev4 depiction --
    supersedes the value read off a rev3 depiction of the same
    arrangement)."""
    R = quaternion.as_rotation_matrix(ImuDeadReckoning._q_imu2cam("as_heart"))
    # columns = camera axes expressed in IMU coordinates
    assert np.allclose(R[:, 0], [-1, 0, 0], atol=1e-9)  # image left  = -x_imu
    assert np.allclose(R[:, 1], [0, 0, -1], atol=1e-9)  # image up    = -z_imu
    assert np.allclose(R[:, 2], [0, -1, 0], atol=1e-9)  # boresight   = -y_imu


@pytest.mark.unit
def test_q_imu2cam_rev4_left():
    """Physical axis correspondences for the Rev4 Left build (rev4 board:
    IMU on the back side of the UI board; derived with
    pointing_model/docs/imu2cam_tool.html under the rev4 depiction)."""
    R = quaternion.as_rotation_matrix(ImuDeadReckoning._q_imu2cam("rev4_left"))
    # columns = camera axes expressed in IMU coordinates
    assert np.allclose(R[:, 0], [0, 0, -1], atol=1e-9)  # image left  = -z_imu
    assert np.allclose(R[:, 1], [1, 0, 0], atol=1e-9)  # image up    = +x_imu
    assert np.allclose(R[:, 2], [0, -1, 0], atol=1e-9)  # boresight   = -y_imu


@pytest.mark.unit
def test_q_imu2cam_rev4_right():
    """Physical axis correspondences for the Rev4 Right build (rev4 board:
    IMU on the back side of the UI board; derived with
    pointing_model/docs/imu2cam_tool.html under the rev4 depiction)."""
    R = quaternion.as_rotation_matrix(ImuDeadReckoning._q_imu2cam("rev4_right"))
    # columns = camera axes expressed in IMU coordinates
    assert np.allclose(R[:, 0], [0, 0, 1], atol=1e-9)  # image left  = +z_imu
    assert np.allclose(R[:, 1], [1, 0, 0], atol=1e-9)  # image up    = +x_imu
    assert np.allclose(R[:, 2], [0, 1, 0], atol=1e-9)  # boresight   = +y_imu


@pytest.mark.unit
def test_q_imu2cam_rev4_straight():
    """Physical axis correspondences for the Rev4 Straight build (rev4 board:
    IMU on the back side of the UI board; derived with
    pointing_model/docs/imu2cam_tool.html under the rev4 depiction).
    45-degree mount: no camera axis coincides with an IMU axis; the
    boresight sits halfway between +x_imu and +z_imu."""
    R = quaternion.as_rotation_matrix(ImuDeadReckoning._q_imu2cam("rev4_straight"))
    s = np.sqrt(2) / 2
    # columns = camera axes expressed in IMU coordinates (tilted)
    assert np.allclose(R[:, 0], [-0.5, -s, 0.5], atol=1e-9)  # image left
    assert np.allclose(R[:, 1], [0.5, -s, -0.5], atol=1e-9)  # image up
    assert np.allclose(R[:, 2], [s, 0.0, s], atol=1e-9)  # boresight
