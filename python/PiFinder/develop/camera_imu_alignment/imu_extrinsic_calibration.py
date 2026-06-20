"""
Alignment of the IMU-camera axes (extrinsic calibration)

For dead-reckoning with the IMU, we need the rotation between the IMU and
camera axes. This is done by the quaternion q_cam2imu and its inverse
q_imu2cam.

The goal of this module is to estimate q_cam2imu. We can do this using pairs of
camera and IMU orientation quaternions measured simultaneously.

Required measurements
---------------------

The measurements we have are:

* q_eq2cam: Quaternion rotation of the camera center relative to the equatorial
  frame. 
* q_x2imu: The rotation of the IMU relative to some arbibtrary reference frame
  X.

The camera and IMU measurements are paired and assumed to be simultaneous.
  
Algorithm:
----------

We can express the rotation between successive timesteps for the camera and
IMU:

dq_cam = q_eq2cam[k-1].conjugate() * q_eq2cam[k] dq_imu =
q_x2imu[k-1].conjugate() * q_x2imu[k]

where * is the quaternion multiplication and .conjugate() is the quaternion
conjugate, which is equivalent to the inverse for a unit quaternion. We can
relate the changes in orientation of the camera and IMU by

dq_cam * q_cam2imu = q_cam2imu * dq_imu

This is the quaternion version of the hand-eye calibration problem (better
known  in the matrix form: AX = XB).

We will solve for q_cam2imu by defining the error quaternion:

q_err = (dq_cam * q_cam2imu) * (q_cam2imu * dq_imu).conjugate()

In the ideal case, q_err will converge to the identity quaternion (1, 0, 0, 0)
at the solution. Quaternions are defined by 4 parameters with one constraint.
We will map the quaternion to a 3-parameter rotation vector, which can be
solved more efficiently and simply. The rotation vector is the product of the
unit vector around the axis of rotation (u) and the rotation (theta):

e = theta * u = log(q_err)

The optimization algorith will minimize the two-norm of the error rotation
vector for k = 1..N measurements:

sum(||e[k]||^2)


Assumptions & limitations
-------------------------

1. Small rotation angles for dq_cam and dq_imu could cause numerical problems
   so successive samples should be selected so that the angles are sufficiently
   large.
2. The IMU will drift over time so the time between the samples used to
   calculate dq_imu should be short enough for drift to be negligible.
3. The camera and IMU samples should be taken simultaneously. If the camera
   moves during exposure, this will introduce an error. Error could be reduced
   by used samples when the camera movement is reasonably stationary.
4. In practice, the plate solver will have worse error in roll than RA and Dec.
   This is not accounted for.
5. Ideally, the camera/IMU should be rotated around all three axes but on a
   mount, the rotation will likely be around two axes. This may result in a 
   larger uncertainty for the rotation/alignment about some axes.
"""

import numpy as np
import quaternion  # Note: numpy-quaternion convention: quaternion(w, x, y, z)
from scipy.optimize import least_squares
import time
from typing import Union

import PiFinder.pointing_model.quaternion_transforms as qt

list_of_quats = list[quaternion.quaternion]


def ensure_quat_continuity(q_list: list_of_quats) -> list_of_quats:
    """
    Ensures that consecutive quaternions in the list have consistent signs (due
    to the double coverage property of quaternions where q and -q represent
    same rotation).

    TODO: Possibly move this to quaternion_transforms?
    """
    q_list_out = [q_list[0]]
    for q in q_list[1:]:
        q_prev = quaternion.as_float_array(q_list_out[-1])
        q_curr = quaternion.as_float_array(q)

        if np.dot(q_prev, q_curr) < 0:
            q = -q
        q_list_out.append(q)

    return q_list_out


def build_relative_rotations(q_list: list_of_quats, step=1) -> list_of_quats:
    """
    Calculate the relative rotation between successive quaternions:
    dq[k] = q[k].conjugate() * q[k+step]
    """
    dq = []
    for k in range(len(q_list) - step):
        q_rel = q_list[k].conjugate() * q_list[k + step]
        dq.append(q_rel)

    return dq


def reject_small_rotations(dq_cam: list_of_quats, 
                           dq_imu: list_of_quats,
                           min_rotation=np.deg2rad(1.0),  # Reject rotations below this [radians]
                           ) -> tuple[list_of_quats, list_of_quats]:
    """
    Reject small rotations
    """
    keep_dq_cam = []
    keep_dq_imu = []
    for qc, qi in zip(dq_cam, dq_imu):
        angle_cam = np.linalg.norm(quaternion.as_rotation_vector(qc))
        angle_imu = np.linalg.norm(quaternion.as_rotation_vector(qi))

        if angle_cam >= min_rotation or angle_imu >= min_rotation:
            keep_dq_cam.append(qc)
            keep_dq_imu.append(qi)

    return keep_dq_cam, keep_dq_imu


def residual_rotation_vector(x,  # (3,) Trial solution (q as rotation vector) 
                             dq_cam: list_of_quats,  # List of relative camera rotation quaternions
                             dq_imu: list_of_quats  # List of relative IMU rotation quaternions
                             ) -> np.ndarray:
    """
    Calculate the esiduals at the trial solution x for least squares
    optimization.

    For solving q_cam2imu in the quaternion form of the hand-eye problem: 
    dq_cam * q_cam2imu = q_cam2imu * dq_imu
    """
    # Convert trial solution (rotation vector) to quaternion
    q_cam2imu = quaternion.from_rotation_vector(x)

    n_meas = len(dq_cam)
    residuals = np.zeros(3 * n_meas)
    for ii, (qc, qi) in enumerate(zip(dq_cam, dq_imu)):
        q_left = qc * q_cam2imu
        q_right = q_cam2imu * qi

        # Error quaternion
        q_err = q_left * q_right.conjugate()

        # Convert to rotation vector (Lie algebra logarithm map)
        residuals[(3 * ii):(3 * ii + 3)] = quaternion.as_rotation_vector(q_err)

    return np.array(residuals)


N_UNKNOWN_PARAMS = 3  # Number of unknown parameters in the problem to solve

def calibrate_camera_imu(
        q_cam: list_of_quats,  # Camera orientations
        q_imu: list_of_quats,  # IMU orientations at same moments
        step: int = 1,  # Skip successive measurements
        min_rotation=np.deg2rad(1.0),  # Reject rotations below this [radians]
        x0: Union[np.ndarray, list] = np.zeros(N_UNKNOWN_PARAMS),  # Initial guess
        residual_threshold = 0.01,  # Reject samples with residual > resid_threshold in first pass
        verbose=True
        ):
    """
    Estimate q_cam2imu from pairs of simultaneous camera and IMU measurements
    q_cam and q_imu (as quaternions).

    RETURNS:
    q_cam2imu: [quaternion.quaternion] Camera-to-IMU rotation estimate
    sigma_total: [rad] Total rotaion uncertainty
    condition_number: < 10 excellent, < 100 acceptable, <1E4 weak observability

    TODO: 
    - Add checks to fail gracefully if there aren't enough data points.
    - Remove outliers
    """
    t_start = time.time()

    # Enforce quaternion continuity
    q_cam = ensure_quat_continuity(q_cam)
    q_imu = ensure_quat_continuity(q_imu)

    # Calculate relative rotations between successive quaternions
    dq_cam = build_relative_rotations(q_cam, step)
    dq_imu = build_relative_rotations(q_imu, step)

    # Reject rotation angle < min_rotation
    reject_small_rotations(dq_cam, dq_imu, min_rotation=min_rotation)
    # TODO: Convert print() to logging
    print(f"{len(q_cam)} measurements. Using {len(dq_cam)} pairs for camera-IMU calibration.")
    # Calculate angular differences for logging
    d_thetas = []
    for ii, dq in enumerate(dq_cam):
        if ii > 0:
            d_thetas.append(qt.get_quat_angular_diff(prev_dq, dq))
        prev_dq = dq
    print(f"Angular rotations: {np.rad2deg(np.min(np.abs(d_thetas))):.2f} to " 
          f"{np.rad2deg(np.max(np.abs(d_thetas))):.2f} deg. "
          f"Median: {np.rad2deg(np.median(np.abs(d_thetas))):.2f} deg.")

    # Solve for x by non-linear least squares (Levenberg-Marquardt)
    # TODO: Tune LM params
    # TODO: Calculate the Jacobians analytically? Current numerical Jacobians is probably fast enough?
    result = least_squares(residual_rotation_vector, x0, method='lm', 
                           args=(dq_cam, dq_imu))
    # TODO: Investigate using robust loss functions?
    #result = least_squares(residual_rotation_vector, x0, loss='cauchy', 
    #                       args=(dq_cam, dq_imu))

    # Re-run least-squares with outliers removed
    if residual_threshold is not None:
        # NOTE: Each quaternion measurement is converted to rotation vectors with 3 values
        resid_reshaped = result.fun.reshape(-1, 3)  # Each row is a sample
        msk_accept = np.all(np.abs(resid_reshaped) < residual_threshold, axis=1)
        dq_cam_accept = np.array(dq_cam)[msk_accept]
        dq_imu_accept = np.array(dq_imu)[msk_accept]
        if verbose:
            print(f"Accepted {np.sum(msk_accept)}/{resid_reshaped.shape[0]} samples.")
        # Run least-squares again (using previous solution as the initial guess)
        result = least_squares(residual_rotation_vector, result.x, 
                               args=(dq_cam_accept, dq_imu_accept))

    # Convert estimate from rotatino vector to quaternion
    q_cam2imu = quaternion.from_rotation_vector(result.x)
    t_compute = time.time() - t_start
    
    if verbose:
        print(f"Estimated q_cam2imu: q_cam2imu={q_cam2imu}, compute time = {t_compute:.3f}s ",
            f"Func evaluations: {result.nfev}, Cost = {result.cost:.4g}, ", 
            f"Success: {result.success}, {result.message}")

    # Diagnostics
    sigma_total, condition_number = _solution_diagnostics(result)
    residuals = result.fun

    return q_cam2imu, sigma_total, residuals, condition_number


def _solution_diagnostics(result):
    """ 
    Calculate the diagnostics of the least-squares solution. The input, 
    `result` is the output from scipy.optimize.least_squares.
    
    Condition number: < 10 excellent, < 100 acceptable, <1E4 weak observability
    """
    t_start = time.time()

    # Estimate the uncertainty of the solution
    residuals = result.fun
    dof = len(residuals) - len(result.x)  # Degrees-of-freedom = Number of meas - Number of params
    residuals_var = np.sum(residuals**2) / dof  # Estimate of residual variance

    # Using 'backslash' rather than inv(): Faster but could be unstable?
    #JTJ = result.jac.T @ result.jac  # Hessian approx from the Jacobians
    #cov_x = residuals_var * np.linalg.solve(JTJ, np.eye(JTJ.shape[0]))  
    
    # Estimate the uncertainty at the solution using SVD: More robust
    U, s, Vt = np.linalg.svd(result.jac, full_matrices=False)
    cov_x = residuals_var * (Vt.T / s**2) @ Vt
    condition_number = s[0] / s[-1]
    sigma_total = np.sqrt(np.trace(cov_x))  # [rad] Total rotaion uncertainty

    t_compute = time.time() - t_start
    print(f"Diagnostics for q_cam2imu: compute time = {t_compute:.3f}s, ",
          f"Total angular uncertainty = {np.rad2deg(sigma_total):.2} deg, ",
          f"Condition number = {condition_number:.1g}")

    return sigma_total, condition_number

# ------ Simulation functions for testing & analysis --------------------------

def _q_noise(noise_amp: float):
    """ Generates random quaternion noise. Noise amp is in radians """
    noise = np.radians(noise_amp) * np.random.randn(3)
    return quaternion.from_rotation_vector(noise)


def _add_noise_to_quaternion_list(qs: list_of_quats, noise_amp: float):
    """ Adds noise to a list of quaternions. noise_amp is in radians. """
    qs_out = []
    for q in qs:
        qs_out.append(_q_noise(noise_amp) * q)

    return qs_out

def _random_quaternions(N: int, max_rot=None) -> list_of_quats:
    """ 
    Returns a list of N random quaternions. If max_rot is None, the quaternions
    will be random. If specified, it limits the maximum swing angle from the
    previous orientation.
    """
    qs = []
    for ii in range(N):
        axis = np.random.randn(3)
        axis /= np.linalg.norm(axis)

        if (max_rot is None) or (ii == 0):
            angle = np.random.uniform(0, np.pi)
            q = quaternion.from_rotation_vector(axis * angle)
        else:
            angle = np.random.uniform(0, max_rot)
            dq = quaternion.from_rotation_vector(axis * angle)
            q = qs[-1] * dq

        qs.append(q)
    
    return qs


def simulate_measurements(q_cam2imu: quaternion.quaternion,  # True q_cam2imu (camera-to-IMU alignment)
                          N: int = 100,  # Number of samples to simulate
                          max_rot = None,  # Max rotation from previous orientation
                          camera_noise_amp: float = np.deg2rad(0.1),  # Camera noise amp in radians
                          imu_noise_amp: float = np.deg2rad(0.1),  # IMU noise amp in radians
                          seed=0  # Random seed. None to disable
                          ):
    """
    Simulate camera and IMU measurements
    """
    if seed is not None:
        np.random.seed(seed)
        
    # Generate random IMU orientations
    q_imu_true = _random_quaternions(N, max_rot=max_rot)

    # Generate corresponding camera orientations
    q_imu2cam = q_cam2imu.conjugate()
    q_cam_true = []
    for q in q_imu_true:
        q_cam_true.append(q * q_imu2cam)

    # Add noise
    q_cam = _add_noise_to_quaternion_list(q_cam_true, camera_noise_amp)
    q_imu = _add_noise_to_quaternion_list(q_imu_true, imu_noise_amp)

    return q_cam, q_imu


if __name__ == "__main__":
    """ 
    The main block simulates pairs of random IMU/camera measurements and solves
    for the camera-to-IMU alignment (q_cam2imu).
    """

    # Set the true camera-from-body rotation
    true_rotvec = np.radians([10, -5, 20])
    q_cam2imu_true = quaternion.from_rotation_vector(true_rotvec)

    # Simulate measurements:
    q_cam, q_imu = simulate_measurements(
        q_cam2imu_true, N=100, camera_noise_amp=np.deg2rad(0.1), 
        imu_noise_amp=np.deg2rad(0.1), seed=0)

    # Calibrate
    q_est, sigma_total, condition_number = calibrate_camera_imu(
        q_cam, q_imu, step=2, min_rotation=np.deg2rad(1.0))

    # Results
    print("\nTrue q_cam2imu:")
    print(quaternion.as_float_array(q_cam2imu_true))

    print("\nEstimated q_cam2imu:")
    print(quaternion.as_float_array(q_est))

    # Error
    q_error = q_est.conjugate() * q_cam2imu_true
    error_deg = np.rad2deg(
        np.linalg.norm(
            quaternion.as_rotation_vector(q_error)
        )
    )
    print(f"\nCalibration error: {error_deg:.6f} deg")
