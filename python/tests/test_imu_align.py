import pytest

import numpy as np
import quaternion  # Note: numpy-quaternion convention: quaternion(w, x, y, z)
from PiFinder.imu.imu_align.hand_eye_solver import solve_rotation, simulate_quaternion_measurements


def test_simulate_quaternion_measurements():
    N = 100  # Number of samples to simulate    

    # Set the true camera-from-body rotation
    true_rotvec = np.radians([10, -5, 20])
    q_12_true = quaternion.from_rotation_vector(true_rotvec)

    # Simulate measurements:
    q1, q2 = simulate_quaternion_measurements(
        q_12_true, N=N, q1_noise_amp=np.deg2rad(0.1), 
        q2_noise_amp=np.deg2rad(0.1), seed=0)
    assert len(q1) == N
    assert len(q2) == N


def test_solve_rotation():
    """ 
    The main block simulates pairs of q1 and q2 measurements and solves
    for the q_12 for the quaternion form of the hand-eye problem:

    q1 * q_12 = q_12 * q2
    """
    # Set the true camera-from-body rotation
    true_rotvec = np.radians([10, -5, 20])
    q_12_true = quaternion.from_rotation_vector(true_rotvec)

    # Simulate measurements:
    q1, q2 = simulate_quaternion_measurements(
        q_12_true, N=100, q1_noise_amp=np.deg2rad(0.1), 
        q2_noise_amp=np.deg2rad(0.1), seed=0)

    # Optional steps: 
    # Pair up and calculate relative rotations
    # Reject small rotations

    # solve
    q_12_est, diagnostics = solve_rotation(q1, q2)

    # Results
    print("\nTrue q_12:")
    print(quaternion.as_float_array(q_12_true))

    print("\nEstimated q_12_est:")
    print(quaternion.as_float_array(q_12_est))

    # Error
    q_error = q_12_est.conjugate() * q_12_true
    error_deg = np.rad2deg(
        np.linalg.norm(
            quaternion.as_rotation_vector(q_error)
        )
    )
    #print(f"\nCalibration error: {error_deg:.6f} deg")
