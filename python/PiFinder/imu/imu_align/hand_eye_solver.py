"""
Core solver functionalities for solving the quaternion form of the hand-eye
problem: 

q1 * q_12 = q_12 * q2

Where the goal is to solve for the rotation q_12. Given enough measurements of 
q1 and q2, we can solve for q_12.
"""
from dataclasses import dataclass
import logging
import numpy as np
import quaternion  # Note: numpy-quaternion convention: quaternion(w, x, y, z)
from scipy.optimize import least_squares, OptimizeResult
import time
from typing import Union

import PiFinder.pointing_model.quaternion_transforms as qt

# Typing:
list_of_quats = list[quaternion.quaternion]
list_of_float_pairs = list[tuple[float, float]]

logger = logging.getLogger("IMU.AlignSolver")

N_UNKNOWN_PARAMS = 3  # Number of unknown parameters in the problem to solve

class HandEyeSolverDiagnostics:
    lsq_result: OptimizeResult  # Result from scipy.optimize.least_squares

    sample_timestamps: Union[list_of_float_pairs, None]  # Timestamps of each sample-pair
    sample_time_differences: Union[np.ndarray, None]  # Time differences between each sample [s]
    residual_norms: np.ndarray  # Residual norms of each sample [rad]
    rotation_angles: np.ndarray  # Rotation angles of each sample [rad]
    sol_cov_matrix: np.ndarray  # Solution covariance matrix
    sol_angle_error: np.ndarray  # Solution angle error [rad]

    # Optional
    meta_data: dict

    def __init__(self, lsq_result, q1_list: list_of_quats, q2_list: list_of_quats, 
                 sample_timestamps: Union[list_of_float_pairs, None] = None):
                
        if len(q1_list) != len(q2_list):
            raise ValueError("q1_list and q2_list must be the same length")
        if sample_timestamps is None:
            self.sample_timestamps = None
            self.sample_time_differences = None
        else:
            if len(sample_timestamps) != len(q1_list):
                raise ValueError("sample_timestamps must be the same length as q1_list and q2_list")
            self.sample_timestamps = sample_timestamps.copy()
            self.sample_time_differences = np.array([t2 - t1 for t1, t2 in self.sample_timestamps])

        self.lsq_result = lsq_result

        # Residual norm per sample (collapse the 3 measurements per sample into one)
        resid = lsq_result.fun.reshape((-1, N_UNKNOWN_PARAMS))  # Each row corresponds to a sample 
        self.residual_norms = np.linalg.norm(resid, axis=1)  # Residual per sample in radians

        # Calculate rotations of each sample [rad]
        self.rotation_angles = [qt.get_quat_angular_diff(q1, q2) for q1, q2 in zip(q1_list, q2_list)]

        self.sol_cov_matrix, self.sol_angle_error =self._calculate_solution_uncertainty()
        self.meta_data = {}

    def _calculate_solution_uncertainty(self):
        """
        Calculate the standard error of the solution:
        Cov = sigma ** 2 * inv(J.T @ J)
        """
        # Extract Jacobian from least_squares result
        J = self.lsq_result.jac  # Jacobian matrix (m_meas, n_sol)
        m_meas, n_sol = J.shape

        # Calculate the inverse using "backslash": Solve: (J.T @ J) @ X = I
        # NOTE: Could be speeded up using QR decomposition but this is good enough
        inv_JTJ, _, _, _ = np.linalg.lstsq(J.T @ J, np.eye(n_sol), rcond=None)

        # Calculate reduced Chi-square
        dof = m_meas - n_sol  # Degrees of freedom
        rss = 2 * self.lsq_result.cost  # Because cost = 0.5 * sum(residuals**2)
        chi_square = rss / dof

        # Estimate uncertainty about the solution
        sol_cov_matrix = chi_square * inv_JTJ
        sol_angle_error = np.sqrt(np.trace(sol_cov_matrix))  # [rad]

        return sol_cov_matrix, sol_angle_error


def residual_rotation_vector(x,  # (3,) Trial solution (q as rotation vector) 
                             q1_list: list_of_quats,  # List of rotation quaternions
                             q2_list: list_of_quats 
                             ) -> np.ndarray:
    """
    For solving q_cam2imu in the quaternion form of the hand-eye problem: 
    q1 * q_12 = q_12 * q2

    Calculate the esiduals at the trial solution x for least squares
    optimization.
    """
    # Convert trial solution (rotation vector) to quaternion
    q_12 = quaternion.from_rotation_vector(x)

    n_meas = len(q1_list)
    residuals = np.zeros(3 * n_meas)
    for ii, (q1, q2) in enumerate(zip(q1_list, q2_list)):
        q_err = (q1 * q_12) * (q_12 * q2).conjugate()  # Error quaternion
        # Convert to rotation vector (Lie algebra logarithm map)
        residuals[(3 * ii):(3 * ii + 3)] = quaternion.as_rotation_vector(q_err)

    return np.array(residuals)


def solve_rotation(
        q1_list: list_of_quats,  # List of rotation quaternions
        q2_list: list_of_quats,
        x0: Union[np.ndarray, list] = np.zeros(N_UNKNOWN_PARAMS),  # Initial guess
        sample_timestamps: Union[list_of_float_pairs, None] = None,
        ) -> tuple[Union[quaternion.quaternion, None], HandEyeSolverDiagnostics]:
    """
    Solve the quaternion form of the hand-eye problem using least-squares
    optimization of the rotation q_12 parameterized as a rotation vector:

    dq1 * q_12 = q_12 * dq2

    Where q_12 is the unknown rotation that rotates q1 to q2.

    x0 is the initial guess for q_12 as a rotation vector. The default (zeros)
    is the identity rotation.

    Returns None for q_12 if the solver failed to converge. 
    """
    if len(q1_list) != len(q2_list):
        raise ValueError("q1_list and q2_list must be the same length")
    if len(q1_list) < N_UNKNOWN_PARAMS:
        raise ValueError(f"q1_list and q2_list must have at least "
                        f"{N_UNKNOWN_PARAMS} elements. Got {len(q1_list)}")
    if len(x0) != N_UNKNOWN_PARAMS:
        raise ValueError("x0 must be a length-3 vector")

    logger.debug(f"Solving for relative rotation from {len(q1_list)} sample pairs.")

    # TODO: Tune LM params
    # TODO: Calculate the Jacobians analytically? Current numerical Jacobians is probably fast enough?
    result = least_squares(residual_rotation_vector, x0, method='lm', 
                           args=(q1_list, q2_list))

    # Convert estimate from rotation vector to quaternion
    q_12 = quaternion.from_rotation_vector(result.x)

    diagnostics = HandEyeSolverDiagnostics(result, q1_list, q2_list, sample_timestamps=sample_timestamps)
    logger.debug(f"Ran solver for relative rotation: Solution q_12={q_12}, "
            f"Solution uncertainty: {np.rad2deg(diagnostics.sol_angle_error):.2f} degrees, "
            f"Func evaluations: {result.nfev}, Cost = {result.cost:.4g}, "
            f"Success: {result.success}, {result.message}")

    if not result.success:
        return None, diagnostics

    return q_12, diagnostics


def solve_rotation_with_outlier_removal(
        q1_list: list_of_quats,  # List of rotation quaternions
        q2_list: list_of_quats,
        x0: Union[np.ndarray, list] = np.zeros(N_UNKNOWN_PARAMS),  # Initial guess
        sample_timestamps: Union[list_of_float_pairs, None] = None,
        mad_threshold = 4.45,  # Reject outlier above this multiple of MAD in first pass
        n_min_samples = N_UNKNOWN_PARAMS,  # Minimum number of sample pairs for a solution
        ):
    """
    Solve the hand-eye problem with a single pass of outlier rejection (see 
    solve_rotation() for details).
    """
    # First pass:
    q12_solution, diagnostics = solve_rotation(q1_list, q2_list, x0, sample_timestamps)
    if q12_solution is None:
        logger.debug("First-pass solve for imu/camera alignment failed to converge.")
        return None, diagnostics
    if mad_threshold is None:
        return q12_solution, diagnostics

    # Second pass: Re-run least-squares with outliers removed
    # Detect outliers above MAD threshold
    median = np.median(diagnostics.residual_norms)
    mad = np.median(np.abs(diagnostics.residual_norms - median))
    mean = np.mean(diagnostics.residual_norms)
    sd = np.std(diagnostics.residual_norms)
    logger.debug("After first pass: "
        f"Solution uncertainty: {np.rad2deg(diagnostics.sol_angle_error):.2f} degrees "
        f"MAD: {np.rad2deg(mad):.2f} degrees SD: {np.rad2deg(sd):.2f} degrees.")
                 
    msk_accept = np.logical_and(diagnostics.residual_norms < (median + mad_threshold * mad),
                                diagnostics.residual_norms < (mean + 3 * sd))
    if np.all(msk_accept):
        logger.debug("No outliers. Returning solution from first-pass.")
        return q12_solution, diagnostics
    
    logger.debug("Outlier removal. Keeping"
        f"{np.sum(msk_accept)}/{diagnostics.residual_norms.shape[0]} samples.")

    if np.sum(msk_accept) < n_min_samples:
        np.info(f"Less than {n_min_samples} samples after outlier removal. "
                "Not enough samples for second pass. Returning solution from first-pass.")
        return q12_solution, diagnostics

    # Remove outliers
    q1_accepted = [q for ii, q in enumerate(q1_list) if msk_accept[ii]]
    q2_accepted = [q for ii, q in enumerate(q2_list) if msk_accept[ii]]
    timestamps_accepted = [t for ii, t in enumerate(sample_timestamps) if msk_accept[ii]]

    # Solve again after outlier removal, using previous solution as the initial guess
    x0 = quaternion.as_rotation_vector(q12_solution)
    q12_solution_new, diagnostics_new = solve_rotation(
        q1_accepted, q2_accepted, x0, timestamps_accepted)
    # Store solutions and diagnostics from first pass
    diagnostics_new.meta_data['first_pass_solution'] = q12_solution
    diagnostics_new.meta_data['first_pass_diagnostics'] = diagnostics

    return q12_solution_new, diagnostics_new


def _solution_diagnostics(result):
    """ 
    Returns the diagnostics of the least-squares solution. The input, 
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


# ------- Helper functions -------

def ensure_quat_list_continuity(q_list: list_of_quats) -> list_of_quats:
    """
    Ensures that consecutive quaternions in the list have consistent signs (due
    to the double coverage property of quaternions where q and -q represent
    same rotation).
    TODO: Possibly not needed. If so, remove.
    """
    q_list_out = [q_list[0]]
    for q in q_list[1:]:
        q = qt.ensure_quat_continuity(q_list_out[-1], q)
        q_list_out.append(q)

    return q_list_out


def calculate_relative_rotations(q1_list: list_of_quats, q2_list: list_of_quats) -> list_of_quats:
    """
    Calculate the relative rotation between q1_list and the corresponding q2_list:
    dq[k] = q1[k].conjugate() * q2[k]
    """
    return [q1.conjugate() * q2 for q1, q2 in zip(q1_list, q2_list)]


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


def simulate_quaternion_measurements(
        q_12: quaternion.quaternion,  # True rel. orientations (q1 ro q2 alignment)
        N: int = 100,  # Number of samples to simulate
        max_rot = None,  # Max rotation from previous orientation
        q1_noise_amp: float = np.deg2rad(0.1),  # Noise amp in radians
        q2_noise_amp: float = np.deg2rad(0.1),  # Noise amp in radians
        seed=0  # Random seed. None to disable
        ):
    """
    Simulate camera and IMU measurements
    """
    if seed is not None:
        np.random.seed(seed)
        
    # Generate random IMU orientations
    q2_true = _random_quaternions(N, max_rot=max_rot)

    # Generate corresponding camera orientations
    q_21 = q_12.conjugate()
    q1_true = []
    for q in q2_true:
        q1_true.append(q * q_21)

    # Add noise
    q1 = _add_noise_to_quaternion_list(q1_true, q1_noise_amp)
    q2 = _add_noise_to_quaternion_list(q2_true, q2_noise_amp)

    return q1, q2


if __name__ == "__main__":
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
        q_12_true, N=100, camera_noise_amp=np.deg2rad(0.1), 
        imu_noise_amp=np.deg2rad(0.1), seed=0)

    # Optional steps: 
    # Pair up and calculate relative rotations
    # Reject small rotations

    # solve
    q_12_est, diagnostics = solve_rotation(
        q1, q2, residual_threshold = 0.01, verbose=True)

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
    print(f"\nCalibration error: {error_deg:.6f} deg")
