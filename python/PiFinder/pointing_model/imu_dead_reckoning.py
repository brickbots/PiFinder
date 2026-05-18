"""
IMU dead-reckoning: estimate pointing in the equatorial frame between
plate-solves using IMU measurements.

The class maintains a single slowly-drifting reference-frame quaternion
(q_eq2x) which is re-solved whenever a matched (plate-solve, IMU) pair is
available. Between solves, dead-reckoning predictions are computed from
the latest IMU sample.

The class treats the plate-solve output as the pointing direction directly;
camera/scope alignment, if any, is applied upstream of solve(). All angles
are in radians. See quaternion_transforms.py for conventions.
"""

from typing import Optional

import numpy as np
import quaternion

from PiFinder.types.coordinates import RaDecRoll
import PiFinder.pointing_model.quaternion_transforms as qt


class ImuDeadReckoning:
    """Dead-reckoning of pointing from matched plate-solve / IMU samples.

    Stored state:
        q_imu2cam: fixed body rotation from IMU frame to the camera
            frame (hardware geometry), set at construction from
            `screen_direction`. The class treats the camera frame as the
            pointing frame.
        q_eq2x: rotation from EQ to the IMU's internal reference frame X.
            Initialised to NaN; set by solve() and cleared by reset().

    Math:
        solve:    q_eq2x = q_eq2pointing * (q_x2imu * q_imu2cam).conj()
        predict:  q_eq2pointing = q_eq2x * q_x2imu * q_imu2cam
    """

    q_imu2cam: quaternion.quaternion
    q_eq2x: quaternion.quaternion

    def __init__(self, screen_direction: str):
        self.q_imu2cam = self._q_imu2cam(screen_direction)
        self.q_eq2x = quaternion.quaternion(np.nan)

    def solve(
        self, pointing: RaDecRoll, q_x2imu: quaternion.quaternion
    ) -> None:
        """Solve for q_eq2x from a matched plate-solve and IMU sample.

        No-op if `pointing` is invalid or `q_x2imu` is NaN — both
        observations are needed to fix the drifting reference frame.
        """
        if not pointing.valid or np.isnan(q_x2imu):
            return
        q_eq2pointing = qt.radec2q_eq(pointing.ra, pointing.dec, pointing.roll)
        self.q_eq2x = (
            q_eq2pointing * (q_x2imu * self.q_imu2cam).conj()
        ).normalized()

    def predict(self, q_x2imu: quaternion.quaternion) -> Optional[RaDecRoll]:
        """Dead-reckon current pointing from the latest IMU sample.

        Returns None if solve() has never produced a valid q_eq2x.
        """
        if not self.is_initialized():
            return None
        q_eq2pointing = (
            self.q_eq2x * q_x2imu * self.q_imu2cam
        ).normalized()
        return RaDecRoll.from_quaternion(q_eq2pointing)

    def is_initialized(self) -> bool:
        """True once solve() has produced a valid q_eq2x."""
        return not bool(np.isnan(self.q_eq2x))

    def reset(self) -> None:
        """Clear q_eq2x so the next solve() re-establishes the reference."""
        self.q_eq2x = quaternion.quaternion(np.nan)

    @staticmethod
    def _q_imu2cam(screen_direction: str) -> quaternion.quaternion:
        """Fixed IMU-to-camera rotation for the given PiFinder geometry.

        Hardware geometry only; no per-unit calibration is applied.
        """
        if screen_direction == "left":
            q1 = qt.axis_angle2quat([1, 0, 0], np.pi / 2)
            q2 = qt.axis_angle2quat([0, 0, 1], np.pi / 2)
            return (q1 * q2).normalized()
        if screen_direction == "right":
            q1 = qt.axis_angle2quat([1, 0, 0], -np.pi / 2)
            q2 = qt.axis_angle2quat([0, 0, 1], np.pi / 2)
            return (q1 * q2).normalized()
        if screen_direction == "straight":
            q1 = qt.axis_angle2quat([0, 1, 0], np.pi)
            q2 = qt.axis_angle2quat([0, 0, 1], -np.pi / 2)
            return (q1 * q2).normalized()
        if screen_direction == "flat3":
            q1 = qt.axis_angle2quat([0, 1, 0], -np.pi * 2 / 3)
            q2 = qt.axis_angle2quat([0, 0, 1], -np.pi / 2)
            return (q1 * q2).normalized()
        if screen_direction == "flat":
            q1 = qt.axis_angle2quat([0, 1, 0], -np.pi / 2)
            q2 = qt.axis_angle2quat([0, 0, 1], -np.pi / 2)
            return (q1 * q2).normalized()
        if screen_direction == "as_bloom":
            return qt.axis_angle2quat([0, 0, 1], np.pi / 2)
        raise ValueError(f"Unsupported screen_direction: {screen_direction}")
