"""
Solve-frame geometry and optical calibration.

The camera publishes two frames per exposure:

* the **display frame** — a 512x512 square crop of the sensor, consumed by the
  UI, focus, and SQM. Its geometry is unchanged from the square-crop pipeline.
* the **solve frame** — the full sensor area at native scale, consumed only by
  the plate solver. Removing the crop roughly doubles the sky area searched for
  stars.

Because the two frames have different origins and scales, anything that crosses
between them (``target_pixel``, alignment results, SQM's matched centroids) has
to be mapped. :class:`SolveGeometry` owns that mapping, built by composing the
affine transform of every stage of each pipeline.

:class:`OpticalCalibration` holds the FOV and lens distortion measured by the
first successful solve of a run, so later solves can be given tight bounds
instead of re-deriving them from scratch.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence, Tuple

import numpy as np

from PiFinder.camera_profiles import CAMERA_PROFILES

logger = logging.getLogger("Optics")

# Side length of the square display frame.
DISPLAY_FRAME_SIZE = 512

# Bounds of the shipped tetra3 database (degrees of horizontal FOV). A solve
# whose measured FOV falls outside this can never match.
DB_MIN_FOV = 10.0
DB_MAX_FOV = 30.0

# Half-width of the FOV search window once calibration has measured the true
# value, in degrees.
CALIBRATED_FOV_MAX_ERROR = 0.5


# Consecutive failures after which a calibration is assumed stale and the
# solver falls back to the wide search window.
FAILURES_BEFORE_RECALIBRATION = 20


def _identity() -> np.ndarray:
    return np.eye(3)


def _translate(dx: float, dy: float) -> np.ndarray:
    return np.array([[1.0, 0.0, dx], [0.0, 1.0, dy], [0.0, 0.0, 1.0]])


def _scale(sx: float, sy: float) -> np.ndarray:
    return np.array([[sx, 0.0, 0.0], [0.0, sy, 0.0], [0.0, 0.0, 1.0]])


def _rot90_ccw(width: int, height: int, k: int) -> Tuple[np.ndarray, int, int]:
    """Affine for ``np.rot90(array, k)`` on an array of shape ``(height, width)``.

    ``np.rot90`` with ``k=1`` maps input element ``(row, col)`` to output
    ``(width - 1 - col, row)``, i.e. in (x, y) terms ``x' = y`` and
    ``y' = (width - 1) - x``. Returns the transform plus the resulting
    ``(width, height)``.
    """
    matrix = _identity()
    for _ in range(k % 4):
        # x' = y, y' = (width - 1) - x
        step = np.array([[0.0, 1.0, 0.0], [-1.0, 0.0, width - 1], [0.0, 0.0, 1.0]])
        matrix = step @ matrix
        width, height = height, width
    return matrix, width, height


@dataclass(frozen=True)
class SolveGeometry:
    """Maps between the 512x512 display frame and the full-frame solve frame.

    Coordinates are handled in ``(y, x)`` order throughout, matching the
    convention used by tetra3 centroids and ``shared_state.target_pixel()``.
    """

    solve_width: int
    solve_height: int
    # Homogeneous (x, y, 1) transform taking display-frame pixels to
    # solve-frame pixels.
    display_to_solve_matrix: np.ndarray
    full_frame: bool

    @property
    def solve_size(self) -> Tuple[int, int]:
        """``(height, width)``, the order ``solve_from_centroids`` expects."""
        return (self.solve_height, self.solve_width)

    @property
    def solve_to_display_matrix(self) -> np.ndarray:
        return np.linalg.inv(self.display_to_solve_matrix)

    def display_to_solve(self, yx: Sequence[float]) -> Tuple[float, float]:
        """Map one ``(y, x)`` display-frame point into the solve frame."""
        y, x = yx
        vec = self.display_to_solve_matrix @ np.array([x, y, 1.0])
        return (float(vec[1]), float(vec[0]))

    def solve_to_display(self, yx: Sequence[float]) -> Tuple[float, float]:
        """Map one ``(y, x)`` solve-frame point into the display frame."""
        y, x = yx
        vec = self.solve_to_display_matrix @ np.array([x, y, 1.0])
        return (float(vec[1]), float(vec[0]))

    def solve_to_display_array(self, points_yx: np.ndarray) -> np.ndarray:
        """Vectorised :meth:`solve_to_display` over an ``(N, 2)`` array."""
        points_yx = np.asarray(points_yx, dtype=float)
        if points_yx.size == 0:
            return points_yx.reshape(0, 2)
        homogeneous = np.column_stack(
            (points_yx[:, 1], points_yx[:, 0], np.ones(len(points_yx)))
        )
        mapped = homogeneous @ self.solve_to_display_matrix.T
        return np.column_stack((mapped[:, 1], mapped[:, 0]))

    @property
    def display_width_in_solve_px(self) -> float:
        """Width of the display frame, measured in solve-frame pixels.

        The x basis vector's image under the mapping gives solve pixels per
        display pixel.
        """
        basis = self.display_to_solve_matrix[:2, 0]
        return DISPLAY_FRAME_SIZE * float(np.hypot(*basis))

    def display_fov(self, solve_fov: float) -> float:
        """Convert a horizontal FOV measured on the solve frame to the display frame.

        Uses the gnomonic relation ``f = (width / 2) / tan(fov / 2)`` rather than
        scaling the angle linearly, which would be off by over a percent at the
        fields these lenses produce.

        Note that "horizontal" is the solve frame's own x axis, which after the
        camera's quarter-turn is the sensor's *short* side. Full frame therefore
        widens the horizontal field only modestly (or not at all, on sensors
        whose square crop already spans the short side); most of the extra sky
        arrives vertically.
        """
        focal_px = (self.solve_width / 2.0) / math.tan(math.radians(solve_fov) / 2.0)
        return math.degrees(
            2.0 * math.atan((self.display_width_in_solve_px / 2.0) / focal_px)
        )

    def solve_fov(self, display_fov: float) -> float:
        """Inverse of :meth:`display_fov`."""
        focal_px = (self.display_width_in_solve_px / 2.0) / math.tan(
            math.radians(display_fov) / 2.0
        )
        return math.degrees(2.0 * math.atan((self.solve_width / 2.0) / focal_px))

    def as_dict(self) -> Dict[str, Any]:
        return {
            "solve_width": self.solve_width,
            "solve_height": self.solve_height,
            "display_to_solve_matrix": self.display_to_solve_matrix.tolist(),
            "full_frame": self.full_frame,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SolveGeometry":
        return cls(
            solve_width=int(data["solve_width"]),
            solve_height=int(data["solve_height"]),
            display_to_solve_matrix=np.array(data["display_to_solve_matrix"]),
            full_frame=bool(data["full_frame"]),
        )


def max_solve_frame_size() -> Tuple[int, int]:
    """Largest solve frame any supported camera can produce, in ``(width, height)``.

    The shared solve-frame buffer is allocated once in the main process, before
    the camera process has detected which sensor is fitted, so it is sized to
    fit the largest possibility. Each frame is published into the top-left
    corner and the solver crops it back to the published geometry.
    """
    largest = DISPLAY_FRAME_SIZE
    for profile in CAMERA_PROFILES.values():
        largest = max(largest, *profile.solve_frame_size)
    return (largest, largest)


def identity_geometry(size: int = DISPLAY_FRAME_SIZE) -> SolveGeometry:
    """Geometry for cameras whose solve frame *is* the display frame.

    Used by the debug and none cameras, and by the square-crop pipeline.
    """
    return SolveGeometry(
        solve_width=size,
        solve_height=size,
        display_to_solve_matrix=_identity(),
        full_frame=False,
    )


def build_geometry(
    profile,
    final_rotation: int,
    full_frame: bool,
) -> SolveGeometry:
    """Compose the display and solve pipelines into a display->solve mapping.

    ``final_rotation`` is the whole-frame rotation the camera loop applies after
    the profile's own crop/rotation, in degrees counter-clockwise.

    Display pipeline: crop -> ``rot90(profile.rotation_90)`` -> resize to
    512x512 -> ``final_rotation``.

    Solve pipeline: optional 2x2 Bayer bin -> ``rot90(profile.rotation_90)`` ->
    ``final_rotation``.
    """
    if not full_frame:
        return identity_geometry()

    raw_width, raw_height = profile.raw_size

    # --- display pipeline ---
    crop_top, crop_bottom = profile.crop_y
    crop_left, crop_right = profile.crop_x
    cropped_width = raw_width - crop_left - crop_right
    cropped_height = raw_height - crop_top - crop_bottom

    display = _translate(-crop_left, -crop_top)
    rot, width, height = _rot90_ccw(cropped_width, cropped_height, profile.rotation_90)
    display = rot @ display
    display = _scale(DISPLAY_FRAME_SIZE / width, DISPLAY_FRAME_SIZE / height) @ display
    rot, _, _ = _rot90_ccw(DISPLAY_FRAME_SIZE, DISPLAY_FRAME_SIZE, final_rotation // 90)
    display = rot @ display

    # --- solve pipeline: the whole sensor at native sampling ---
    solve = _identity()
    rot, width, height = _rot90_ccw(raw_width, raw_height, profile.rotation_90)
    solve = rot @ solve
    rot, width, height = _rot90_ccw(width, height, final_rotation // 90)
    solve = rot @ solve

    return SolveGeometry(
        solve_width=width,
        solve_height=height,
        display_to_solve_matrix=solve @ np.linalg.inv(display),
        full_frame=True,
    )


class OpticalCalibration:
    """Session-scoped cache of the measured FOV and lens distortion.

    The first successful solve of a run is made with a wide FOV window and
    ``distortion=0`` so cedar-solve derives both. Its measured values are then
    kept for the rest of the run: subsequent solves get a tight FOV window and
    the measured distortion as a starting point, which both speeds up pattern
    matching and improves centroid matching towards the frame corners — the part
    of the image the square crop used to throw away.

    Calibration is not persisted; it is cheap enough to redo at every startup,
    and it stays correct across lens or camera swaps for free.
    """

    def __init__(
        self,
        fallback_fov: Optional[float] = None,
        fallback_fov_max_error: Optional[float] = None,
    ) -> None:
        # Both None means "gate nothing". Frames from an unknown optical train
        # give no field of view to gate on, and a wrong gate is worse than no
        # gate: tetra3 discards candidates outside the window before it ever
        # verifies them. See the third-rung amendment to docs/adr/0029.
        self._fallback_fov = fallback_fov
        self._fallback_fov_max_error = fallback_fov_max_error
        self.fov: Optional[float] = None
        self.distortion: Optional[float] = None
        self._consecutive_failures = 0

    @property
    def gated(self) -> bool:
        """False when there is no field of view to gate against."""
        return self._fallback_fov is not None

    @property
    def calibrated(self) -> bool:
        return self.fov is not None

    def solver_args(self) -> Dict[str, Any]:
        """FOV and distortion arguments for ``solve_from_centroids``."""
        if not self.gated:
            # tetra3's own default for distortion, stated rather than implied.
            return {"distortion": 0}
        if not self.calibrated:
            return {
                "fov_estimate": self._fallback_fov,
                "fov_max_error": self._fallback_fov_max_error,
                "distortion": 0,
            }
        return {
            "fov_estimate": self.fov,
            "fov_max_error": CALIBRATED_FOV_MAX_ERROR,
            "distortion": self.distortion,
        }

    def record_success(self, solution: Dict[str, Any]) -> None:
        self._consecutive_failures = 0
        if self.calibrated:
            return
        if not self.gated:
            # Ungated frames are not this device's own sky. Measuring one and
            # then gating the rest on it would make the first replayed frame
            # decide what the others are allowed to be.
            return

        fov = solution.get("FOV")
        if fov is None:
            return
        if not DB_MIN_FOV <= fov <= DB_MAX_FOV:
            logger.warning(
                "Measured FOV %.2f deg is outside the database range %.1f-%.1f; "
                "not calibrating",
                fov,
                DB_MIN_FOV,
                DB_MAX_FOV,
            )
            return

        self.fov = float(fov)
        distortion = solution.get("distortion")
        self.distortion = float(distortion) if distortion is not None else 0.0
        logger.info(
            "Optical calibration: FOV %.3f deg, distortion %.4f "
            "(subsequent solves use +/-%.1f deg)",
            self.fov,
            self.distortion,
            CALIBRATED_FOV_MAX_ERROR,
        )

    def record_failure(self) -> None:
        if not self.calibrated:
            return
        self._consecutive_failures += 1
        if self._consecutive_failures >= FAILURES_BEFORE_RECALIBRATION:
            logger.warning(
                "%d consecutive solve failures; discarding optical calibration",
                self._consecutive_failures,
            )
            self.fov = None
            self.distortion = None
            self._consecutive_failures = 0

    @classmethod
    def for_train(
        cls, geometry: SolveGeometry, train: Optional[Any] = None
    ) -> "OpticalCalibration":
        """Seed the pre-calibration search window from the optical train.

        The train states the field of the *display* frame, because that is the
        extent its sensor profile's crop describes. The solve frame is wider,
        so the window is projected onto it with
        :meth:`SolveGeometry.solve_fov` -- gnomonically, not by scaling the
        angle, which is over a percent wrong at these fields.

        The train's own proportional margin (ADR 0027) is carried across
        rather than re-invented here: it is what covers lens-sample spread,
        barrel distortion and focus shift, and it was validated against real
        frames. This class only *tightens* the window afterwards, once a solve
        has measured the field for real.

        Pass ``train=None`` when the frames did not come through this
        device's optics -- a replayed capture, the debug camera -- and the
        result gates nothing at all.
        """
        if train is None:
            return cls()
        display_fov, display_max_error = train.solver_fov_params()
        estimate = geometry.solve_fov(display_fov)
        upper = geometry.solve_fov(display_fov + display_max_error)
        return cls(estimate, upper - estimate)

    def describe(self) -> str:
        if not self.gated:
            return "ungated (unknown optical train)"
        if not self.calibrated:
            return (
                f"uncalibrated (FOV est: {self._fallback_fov:.1f} deg, "
                f"max err: {self._fallback_fov_max_error:.1f} deg)"
            )
        return (
            f"FOV {self.fov:.2f} deg +/-{CALIBRATED_FOV_MAX_ERROR:.1f}, "
            f"distortion {self.distortion:.4f}"
        )
