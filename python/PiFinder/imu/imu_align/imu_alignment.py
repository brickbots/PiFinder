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

from dataclasses import dataclass

import logging
import numpy as np
import quaternion
import time

from PiFinder.types.coordinates import RaDecRoll
from PiFinder.pointing_model import quaternion_transforms as qt
from PiFinder.imu.imu_align.hand_eye_solver import solve_rotation_with_outlier_removal

list_of_quats = list[quaternion.quaternion]

logger = logging.getLogger("IMU.Align")


@dataclass
class CameraImuSample:
    """ """

    timestamp: float
    q_cam: quaternion.quaternion
    q_imu: quaternion.quaternion


class SampleBuffer:
    """
    Buffer of samples
    """

    buffer: list
    max_buffer_length: int

    def __init__(self, max_buffer_length=10):
        self.max_buffer_length = max_buffer_length
        self.reset_buffer()

    def reset_buffer(self):
        self.buffer = []

    @property
    def len(self):
        """Number of samples in buffer"""
        return len(self.buffer)

    def add_sample(self, sample: CameraImuSample):
        if len(self.buffer) >= self.max_buffer_length:
            self.buffer.pop(0)  # Remove oldest sample from buffer
        self.buffer.append(sample)

    def pop_sample(self, idx: int):
        """Remove and return the sample at the given index"""
        return self.buffer.pop(idx)

    def remove_samples(self, idx_list: set[int]):
        """Remove multiple samples by indices"""
        self.buffer = [
            self.buffer[i] for i in range(len(self.buffer)) if i not in idx_list
        ]

    def trim_to_max_length(self):
        if self.len > self.max_buffer_length:
            self.buffer = self.buffer[-self.max_buffer_length :]


class ImuCameraAlignment:
    """
    Note that max_time_diff should be kept to a few seconds at most to avoid
    gyro drift over the time between samples.
    """

    candidate_buffer: SampleBuffer  # Buffer of camera/IMU samples
    pair_buffer: SampleBuffer  # Buffer of paired samples ofcamera/IMU samples

    min_n_solve: int  # Minimum number of samples for solve
    max_time_diff: float  # [s] Maximum time difference between pairs of samples
    min_angle_diff: float  # [rad] Pair samples with large enough angle difference
    max_age: float  # [s] Maximum age of sample compared to current time

    def __init__(
        self,
        candidate_buffer_length: int = 60,
        min_n_solve: int = 20,
        max_time_diff: float = 20.0,
        min_angle_diff: float = np.deg2rad(5.0),
        max_age: float = 600.0,
    ):
        """
        candidate_buffer_length: Should be around sample_freq * max_time_diff

        :param candidate_buffer_length: [int] Number of candidate samples to buffer
        :param min_n_solve: [int] Minimum number of samples required for solve
        :param max_time_diff: [s] Maximum allowed time difference between pairs of samples
        :param min_angle_diff: [rad] Minimum allowed angle difference between pairs of samples
        :param max_age: [s] Remove samples older than this. None to ignore
        """
        self.candidate_buffer = SampleBuffer(
            max_buffer_length=max(candidate_buffer_length, min_n_solve)
        )
        diff_buffer_length = candidate_buffer_length
        self.pair_buffer = SampleBuffer(max_buffer_length=diff_buffer_length)

        self.min_n_solve = min_n_solve
        self.max_time_diff = max_time_diff
        self.min_angle_diff = min_angle_diff
        self.max_age = max_age

        self._samples_since_last_pair_attempt = 0

    def add_candidate_attempt_solve(
        self, timestamp: float, cam_eq: RaDecRoll, q_x2imu: quaternion.quaternion
    ):
        """
        For general use, call this pipeline method. Add a new candidate to the
        buffer. When the buffer fills up, pair samples and solve.
        """
        self._add_candidate(timestamp, cam_eq, q_x2imu)

        # Pair samples: Runs periodically
        if (self._samples_since_last_pair_attempt >= self.min_n_solve) or (
            self.candidate_buffer.len >= self.candidate_buffer.max_buffer_length
        ):
            self._purge_old_samples(timestamp)
            self._purge_old_candidates()
            self._pair_samples()

            # If the candidate buffer is still full after pairing, remove a
            # batch of the older samples from the buffer
            if self.candidate_buffer.len >= self.candidate_buffer.max_buffer_length:
                remove_set = set(range(self.min_n_solve))
                self.candidate_buffer.remove_samples(remove_set)

            self._samples_since_last_pair_attempt = 0
        else:
            self._samples_since_last_pair_attempt += 1

        # Solve if there are enough samples
        if self.pair_buffer.len >= self.min_n_solve:
            t_start = time.time()
            q_cam2imu, diagnostics = self._solve()
            diagnostics.meta_data["total_solve_time"] = time.time() - t_start

            self.pair_buffer.reset_buffer()  # Flush the values used for solve
            self.candidate_buffer.trim_to_max_length()

            return q_cam2imu, diagnostics
        else:
            return None, None

    def _reset_buffers(self):
        self.candidate_buffer.reset_buffer()
        self.pair_buffer.reset_buffer()

    def _trim_buffers(self):
        self.candidate_buffer.trim_to_max_length()
        self.pair_buffer.trim_to_max_length()

    def _add_candidate(
        self, timestamp: float, cam_eq: RaDecRoll, q_x2imu: quaternion.quaternion
    ):
        """
        Add to the candidate_buffer the camera solve & corresponding IMU sample
        from integrator.
        """
        if (
            timestamp is None
            or cam_eq is None
            or cam_eq.valid is False
            or q_x2imu is None
        ):
            return

        # Ensure quaternion continuity from previous candidate sample
        q_cam = cam_eq.as_quaternion()
        if self.candidate_buffer.len == 0:
            self.candidate_buffer.add_sample(CameraImuSample(timestamp, q_cam, q_x2imu))
        else:
            last_candidate = self.candidate_buffer.buffer[-1]
            q_cam = qt.ensure_quat_continuity(last_candidate.q_cam, q_cam)
            q_imu = qt.ensure_quat_continuity(last_candidate.q_imu, q_x2imu)
            self.candidate_buffer.add_sample(CameraImuSample(timestamp, q_cam, q_imu))

    def _purge_old_samples(self, ref_time: float):
        """
        Remove samples from the candidate_buffer that are older than max_age
        relative to ref_time. This should be run on a schedule every
        self.max_age [s].
        """
        if self.max_age is None:
            return

        allowed_timestamp = ref_time - self.max_age  # Purge anything older than this

        # Purge candidate_buffer:
        remove_idx_list = [
            i
            for i, samp in enumerate(self.candidate_buffer.buffer)
            if samp.timestamp < allowed_timestamp
        ]
        if remove_idx_list:
            self.candidate_buffer.remove_samples(set(remove_idx_list))

        # Purge diff_buffer:
        remove_idx_list = [
            i
            for i, (samp1, samp2) in enumerate(self.pair_buffer.buffer)
            if samp1.timestamp < allowed_timestamp
            or samp2.timestamp < allowed_timestamp
        ]
        if remove_idx_list:
            self.pair_buffer.remove_samples(set(remove_idx_list))

    def _purge_old_candidates(self):
        """
        Remove samples from candidate_buffer that are older than
        self.max_time_diff from other samples in buffer because these will be
        never paired.

        This should be run on a schedule every self.max_time_diff [s].
        """
        if self.candidate_buffer.len <= 1:
            return

        remove_ids = set()
        timestamps = np.array([samp.timestamp for samp in self.candidate_buffer.buffer])
        for isamp in range(timestamps.shape[0]):
            dt = np.abs(timestamps - timestamps[isamp])
            if np.sum(dt < self.max_time_diff) <= 1:
                remove_ids.add(isamp)

        if remove_ids:
            self.candidate_buffer.remove_samples(remove_ids)

    def _pair_samples(self) -> int:
        """
        Go through the candidate_buffer from the first sample in the buffer.
        Pair two sets of camera/IMU samples from the candidate buffer that meet
        the criteria and remove them from the buffer. Repeat all pairable
        samples have been removed from the candidate_buffer.
        """
        n_pairs = 0
        if self.candidate_buffer.len == 0:
            logger.debug("No samples in candidate buffer for pairing.")
            return n_pairs

        remove_ids = set()
        for isamp1, samp1 in enumerate(self.candidate_buffer.buffer[:-1]):
            for isamp2 in range(isamp1 + 1, self.candidate_buffer.len):
                samp2 = self.candidate_buffer.buffer[isamp2]
                # Check time difference between samples:
                dt = samp2.timestamp - samp1.timestamp
                if dt > self.max_time_diff or dt <= 0:
                    # 1) Samples too far apart in time (subsequent samp2 will be even newer), or
                    # 2) Duplicate samples or out-of-order (sample1 is newer). Remove sample1
                    remove_ids.add(isamp1)
                    break

                # Check angle difference (from camera solve) between samples:
                dtheta = qt.get_quat_angular_diff(samp1.q_cam, samp2.q_cam)
                if np.abs(dtheta) < self.min_angle_diff:
                    continue  # Samples too close in angle

                # Pair samples and remove samp1 from candidate buffer after FOR
                # loops. This prevents the same pair being used again if this
                # method is re-run. Note that this loop will continue pairing
                # with samp1.
                self.pair_buffer.add_sample((samp1, samp2))
                n_pairs += 1
                remove_ids.add(isamp1)
                if self.pair_buffer.len >= self.pair_buffer.max_buffer_length:
                    break
            if self.pair_buffer.len >= self.pair_buffer.max_buffer_length:
                break

        logger.debug(
            f"Created {n_pairs}-way pairs from {self.candidate_buffer.len} candidate samples."
        )

        if remove_ids:
            self.candidate_buffer.remove_samples(remove_ids)
        logger.debug(
            f"Removed {len(remove_ids)} samples from candidate buffer. "
            f"New candidate buffer length: {self.candidate_buffer.len}. "
            f"Pair buffer length: {self.pair_buffer.len}."
        )

        return n_pairs  # Number of successful pairings

    def _solve(self, n_pairs=None):
        """
        Solve for the alignment between the camera and IMU using at least the
        last n_pairs or all available pairs (if None) in diff_buffer.
        """
        if n_pairs is None:
            n_pairs = self.pair_buffer.len  # Use all available data
        if n_pairs < self.min_n_solve:
            raise ValueError(
                f"Oly {n_pairs} samples available for solve. Need {self.min_n_solve}."
            )

        # Generate relative rotation quaternions between paired samp1 and samp2
        # The amount of relative rotation for camera and IMU should be the same
        # and this will solve the relative rotation between them.
        dq_cam_list = []
        dq_imu_list = []
        sample_timestamps = []
        for samp1, samp2 in self.pair_buffer.buffer:
            dq_cam_list.append(samp1.q_cam.conj() * samp2.q_cam)
            dq_imu_list.append(samp1.q_imu.conj() * samp2.q_imu)
            sample_timestamps.append((samp1.timestamp, samp2.timestamp))

        # Solve
        # q_cam2imu, diagnostics = solve_rotation(dq_cam_list, dq_imu_list)
        q_cam2imu, diagnostics = solve_rotation_with_outlier_removal(
            dq_cam_list, dq_imu_list, sample_timestamps=sample_timestamps
        )
        return q_cam2imu, diagnostics
