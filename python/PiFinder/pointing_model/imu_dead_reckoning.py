"""
IMU dead-reckoning: estimate both the camera and aligned pointings in the
equatorial frame between plate-solves using IMU measurements.

The class maintains:
  * q_eq2x: a slowly-drifting reference-frame quaternion that is re-solved
    whenever a matched (plate-solve, IMU) pair is available.
  * q_cam2aligned: the static rotation from the camera optical axis to the
    aligned (eyepiece) axis, captured from the (camera, aligned) pair at
    each successful solve.

Between solves, dead-reckoning predictions are computed from the latest
IMU sample for the camera axis and composed with q_cam2aligned to yield
the aligned-axis prediction.

The IDR is a math primitive: it takes RaDecRoll in and returns
RaDecRoll out. It does not import the PointingEstimate dataclass.
All angles are in radians. See quaternion_transforms.py for conventions.
"""

import math
from typing import Optional, Tuple

import numpy as np
import quaternion

from PiFinder.types.coordinates import RaDecRoll
import PiFinder.pointing_model.quaternion_transforms as qt


def _quat_has_nan(q: quaternion.quaternion) -> bool:
    """True if any component of ``q`` is NaN.

    Detects the uninitialised sentinel ``quaternion(nan, 0, 0, 0)``.
    Uses :func:`math.isnan` per component rather than ``np.isnan(q)``
    because the latter raises a spurious 'invalid value encountered in
    isnan' ``RuntimeWarning`` whenever the quaternion already holds a NaN.
    """
    return math.isnan(q.w) or math.isnan(q.x) or math.isnan(q.y) or math.isnan(q.z)


class ImuDeadReckoning:
    """Dead-reckoning of camera and aligned pointings from matched
    plate-solve / IMU samples.

    Stored state:
        q_imu2cam: fixed body rotation from IMU frame to the camera
            frame (hardware geometry), set at construction from
            `screen_direction`.
        q_eq2x: rotation from EQ to the IMU's internal reference frame X.
            Initialised to NaN; set by solve() and cleared by reset().
        q_cam2aligned: static rotation from the camera axis to the
            aligned (eyepiece) axis. Initialised to NaN; (re)set by
            solve() and cleared by reset().

    Math:
        solve:
            q_eq2cam       = q_eq2pointing(camera)
            q_eq2aligned   = q_eq2pointing(aligned)
            q_eq2x         = q_eq2cam * (q_x2imu * q_imu2cam).conj()
            q_cam2aligned  = q_eq2cam.conj() * q_eq2aligned

        predict:
            q_eq2cam       = q_eq2x * q_x2imu * q_imu2cam
            q_eq2aligned   = q_eq2cam * q_cam2aligned
    """

    q_imu2cam: quaternion.quaternion
    q_eq2x: quaternion.quaternion
    q_cam2aligned: quaternion.quaternion

    def __init__(self, screen_direction: str):
        self.q_imu2cam = self._q_imu2cam(screen_direction)
        self.q_eq2x = quaternion.quaternion(np.nan)
        self.q_cam2aligned = quaternion.quaternion(np.nan)

    def solve(
        self,
        camera: RaDecRoll,
        aligned: RaDecRoll,
        q_x2imu: quaternion.quaternion,
    ) -> None:
        """Solve for q_eq2x and q_cam2aligned from a matched plate-solve
        pair and an IMU sample.

        No-op if either pointing is invalid or `q_x2imu` is NaN — all
        three observations are needed to fix the drifting reference
        frame and the alignment offset.
        """
        if not camera.valid or not aligned.valid or _quat_has_nan(q_x2imu):
            return
        q_eq2cam = qt.radec2q_eq(camera.ra, camera.dec, camera.roll)
        q_eq2aligned = qt.radec2q_eq(aligned.ra, aligned.dec, aligned.roll)
        self.q_eq2x = (q_eq2cam * (q_x2imu * self.q_imu2cam).conj()).normalized()
        self.q_cam2aligned = (q_eq2cam.conj() * q_eq2aligned).normalized()

    def predict(
        self, q_x2imu: quaternion.quaternion
    ) -> Optional[Tuple[RaDecRoll, RaDecRoll]]:
        """Dead-reckon current (camera, aligned) pointings from the
        latest IMU sample.

        Returns None if solve() has never produced a valid q_eq2x. Both
        returned pointings share the predicted timing.
        """
        if not self.is_initialized():
            return None
        q_eq2cam = (self.q_eq2x * q_x2imu * self.q_imu2cam).normalized()
        q_eq2aligned = (q_eq2cam * self.q_cam2aligned).normalized()
        return (
            RaDecRoll.from_quaternion(q_eq2cam),
            RaDecRoll.from_quaternion(q_eq2aligned),
        )

    def is_initialized(self) -> bool:
        """True once solve() has produced a valid q_eq2x. Because
        q_cam2aligned is set inside the same solve() call, it is also
        valid whenever q_eq2x is."""
        return not _quat_has_nan(self.q_eq2x)

    def reset(self) -> None:
        """Clear q_eq2x and q_cam2aligned so the next solve()
        re-establishes both."""
        self.q_eq2x = quaternion.quaternion(np.nan)
        self.q_cam2aligned = quaternion.quaternion(np.nan)

    @staticmethod
    def _q_imu2cam(screen_direction: str) -> quaternion.quaternion:
        """Fixed IMU-to-camera rotation for the given PiFinder geometry.

        Hardware geometry only; no per-unit calibration is applied.

        Each entry is paired with the variant's SCREEN_ROTATE_AMOUNTS value
        in camera_interface.py -- the camera frame is defined on the image
        *after* that software rotation, so the two constants are only valid
        together. Derive new entries (and verify these) with the visual
        imu2cam tool at docs/imu2cam_tool.html; its presets are pinned to
        this table by tests/test_imu2cam_tool_presets.py.
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
            # As Bloom (rev4 board: IMU on the back side of the UI board):
            # Rotate 180° around y_imu so that z_imu' points along z_camera
            q1 = qt.axis_angle2quat([0, 1, 0], np.pi)
            # Rotate 180° around z_imu' to align with the camera coordinates
            q2 = qt.axis_angle2quat([0, 0, 1], np.pi)
            return (q1 * q2).normalized()
        if screen_direction == "as_heart":
            # As Heart (rev4 board: IMU on the back side of the UI board):
            # Rotate 90° around x_imu so that z_imu' points along z_camera
            q1 = qt.axis_angle2quat([1, 0, 0], np.pi / 2)
            # Rotate 180° around z_imu' to align with the camera coordinates
            q2 = qt.axis_angle2quat([0, 0, 1], np.pi)
            return (q1 * q2).normalized()
        if screen_direction == "rev4_left":
            # Rev4 Left (rev4 board: IMU on the back side of the UI board):
            # Rotate 90° around x_imu so that z_imu' points along z_camera
            q1 = qt.axis_angle2quat([1, 0, 0], np.pi / 2)
            # Rotate -90° around z_imu' to align with the camera coordinates
            q2 = qt.axis_angle2quat([0, 0, 1], -np.pi / 2)
            return (q1 * q2).normalized()
        if screen_direction == "rev4_right":
            # Rev4 Right (rev4 board: IMU on the back side of the UI board):
            # Rotate -90° around x_imu so that z_imu' points along z_camera
            q1 = qt.axis_angle2quat([1, 0, 0], -np.pi / 2)
            # Rotate -90° around z_imu' to align with the camera coordinates
            q2 = qt.axis_angle2quat([0, 0, 1], -np.pi / 2)
            return (q1 * q2).normalized()
        if screen_direction == "rev4_straight":
            # Rev4 Straight (rev4 board: IMU on the back side of the UI board;
            # 45° mount -- no camera axis coincides with an IMU axis):
            # Rotate 45° around y_imu so that z_imu' points along z_camera
            q1 = qt.axis_angle2quat([0, 1, 0], np.pi / 4)
            # Rotate -135° around z_imu' to align with the camera coordinates
            q2 = qt.axis_angle2quat([0, 0, 1], -np.pi * 3 / 4)
            return (q1 * q2).normalized()
        raise ValueError(f"Unsupported screen_direction: {screen_direction}")
