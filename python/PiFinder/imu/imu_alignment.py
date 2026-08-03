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
import logging
import numpy as np
import quaternion
from dataclasses import dataclass

from PiFinder.types.coordinates import RaDecRoll
from PiFinder.pointing_model import quaternion_transforms as qt

list_of_quats = list[quaternion.quaternion]

logger = logging.getLogger("IMU.Align")


@dataclass
class CameraImuSample:
    """
    """
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
        if len(self.samples) >= self.max_buffer_length:
            self.samples.pop(0)  # Remove oldest sample from buffer
        self.buffer.append(sample)

    def pop_sample(self, idx: int):
        """Remove and return the sample at the given index"""
        return self.buffer.pop(idx)
    
    def remove_samples(self, idx_list: list[int]):
        """Remove multiple samples by indices"""
        self.buffer = [self.buffer[i] for i in range(len(self.buffer)) if i not in idx_list]

    def trim_to_max_length(self):
        if self.len > self.max_buffer_length:
            self.buffer = self.buffer[-self.max_buffer_length:]


class ImuCameraAlignment:
    """
    """
    candidate_buffer: SampleBuffer  # Buffer of camera/IMU samples
    diff_buffer: SampleBuffer  # Buffer of paired differences in camera/IMU samples

    max_time_diff: float  # [s] Maximum time difference between pairs of samples
    min_angle_diff: float  # [rad] Pair samples with large enough angle difference
    max_age: float  # [s] Maximum age of sample compared to current time

    def __init__(self, candidate_buffer_length=10, diff_buffer_length=10,
                 max_time_diff=10, min_angle_diff=np.deg2rad(5), max_age=1200):
        self.candidate_buffer = SampleBuffer(max_buffer_length=candidate_buffer_length)
        self.diff_buffer = SampleBuffer(max_buffer_length=diff_buffer_length)

        self.max_time_diff = max_time_diff
        self.min_angle_diff = min_angle_diff
        self.max_age = max_age

    def reset_buffers(self):
        self.candidate_buffer.reset_buffer()
        self.diff_buffer.reset_buffer()

    def trim_buffers(self):
        self.candidate_buffer.trim_to_max_length()
        self.diff_buffer.trim_to_max_length()

    def add_sample(self, timestamp: float, cam_eq: RaDecRoll, q_x2imu: quaternion.quaternion):
        """
        Add to the candidate_buffer the camera solve & corresponding IMU sample
        from integrator.
        """
        if timestamp is None or cam_eq is None or cam_eq.valid is False or q_x2imu is None:
            return
        self.candidate_buffer.add_sample(
            CameraImuSample(timestamp, cam_eq.as_quaternion(), q_x2imu))

    def purge_old_samples(self, current_time: float):
        """
        Remove samples from the candidate_buffer that are older than the current
        time.
        """
        allowed_timestamp = current_time - self.max_age  # Purge anything older than this
        
        # Purge candidate_buffer:
        remove_idx_list = [i for i, samp in enumerate(self.candidate_buffer) 
                           if samp.timestamp < allowed_timestamp]
        if remove_idx_list:
            self.candidate_buffer.remove_samples(remove_idx_list)

        # Purge diff_buffer:
        remove_idx_list = [i for i, (samp1, samp2) in enumerate(self.diff_buffer) 
                           if samp1.timestamp < allowed_timestamp 
                           or samp2.timestamp < allowed_timestamp]
        if remove_idx_list:
            self.diff_buffer.remove_samples(remove_idx_list)

    def pair_samples(self):
        """
        Go through the candidate_buffer from the first sample in the buffer.
        Pair two sets of camera/IMU samples from the candidate buffer that meet
        the criteria and remove them from the buffer. Repeat all pairable
        samples have been removed from the candidate_buffer.
        """
        remove_idx_list = []
        for isamp1, samp1 in enumerate(self.candidate_buffer[:-1]):
            if isamp1 in remove_idx_list:
                continue

            for isamp2 in range(isamp1 + 1, self.candidate_buffer.len):
                if isamp2 in remove_idx_list:
                    continue
                samp2 = self.candidate_buffer[isamp2]

                # Check time difference between samples:
                dt = samp2.timestamp - samp1.timestamp
                if dt > self.max_time_diff:
                    continue  # Samples too far apart in time
                if dt <= 0:
                    # Duplicate samples or sample1 is newer. Remove sample1
                    remove_idx_list.append(isamp1)
                    continue
                
                # Check angle difference (from camera solve) between samples:
                dtheta = qt.get_quat_angular_diff(samp1.q_cam, samp2.q_cam)
                if np.abs(dtheta) < self.min_angle_diff:
                    continue  # Samples too close in angle

                # Pair samples and remove from candidate buffer:
                self.diff_buffer.add_sample((samp1, samp2))
                remove_idx_list.append(isamp1)
                remove_idx_list.append(isamp2)

        if remove_idx_list:
            self.candidate_buffer.remove_samples(remove_idx_list)
        self.trim_buffers()  # Clean up

    def solve(self, n_pairs=None):
        """
        Solve for the alignment between the camera and IMU using the last
        n_pairs or all available pairs (if None).
        """
        if n_pairs is None:
            n_pairs = self.diff_buffer.len
        

