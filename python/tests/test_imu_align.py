import numpy as np
import quaternion  # Note: numpy-quaternion convention: quaternion(w, x, y, z)
from PiFinder.imu.imu_align.hand_eye_solver import (
    solve_rotation,
    simulate_quaternion_measurements,
    HandEyeSolverDiagnostics,
)


def test_simulate_quaternion_measurements():
    N = 100  # Number of samples to simulate

    # Set the true camera-from-body rotation
    true_rotvec = np.radians([10, -5, 20])
    q_12_true = quaternion.from_rotation_vector(true_rotvec)

    # Simulate measurements:
    q1, q2 = simulate_quaternion_measurements(
        q_12_true,
        N=N,
        q1_noise_amp=np.deg2rad(0.1),
        q2_noise_amp=np.deg2rad(0.1),
        seed=0,
    )
    assert len(q1) == N
    assert len(q2) == N


def test_solve_rotation():
    """
    The main block simulates pairs of q1 and q2 measurements and solves
    for the q_12 for the quaternion form of the hand-eye problem:

    q1 * q_12 = q_12 * q2
    """
    # Set the true camera-from-body rotation
    true_rotvec = np.array([1, 1, 1]) / np.sqrt(3) * np.deg2rad(30)
    q_12_true = quaternion.from_rotation_vector(true_rotvec)

    # Simulate measurements:
    sigma = np.deg2rad(0.1)
    q1, q2 = simulate_quaternion_measurements(
        q_12_true,
        N=100,
        q1_noise_amp=sigma,
        q2_noise_amp=sigma,
        seed=0,
    )

    # solve
    q_12_est, diagnostics = solve_rotation(q1, q2)
    assert isinstance(q_12_est, quaternion.quaternion)
    assert isinstance(diagnostics, HandEyeSolverDiagnostics)

    # Check error
    # q_error = q_12_est.conjugate() * q_12_true
    # error_rad = np.linalg.norm(quaternion.as_rotation_vector(q_error))
    # print(f"Uncertainty: {np.rad2deg(diagnostics.sol_angle_error):.3f} degrees.")
    # assert error_rad < np.deg2rad(1.0), f"error_rad too large. Got {error_rad:.3f} rad"
