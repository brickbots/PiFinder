"""
Proposed dataclasses for the solving / integration flow.

PROPOSAL ONLY — nothing in this module is referenced by existing code yet.
The goal is to replace the loose dicts and tagged-list messages that
travel between camera → solver → integrator → shared_state with named,
type-checked structures.

Dicts these types replace
-------------------------

1. The ``solved`` dict built by ``solver.get_initialized_solved_dict()``
   and merged with tetra3's ``solution`` return value.
   →  :class:`PointingEstimate`, which holds two
      :class:`PointingPair`\\ s — the published current pair
      (target-pixel + camera-center, possibly IMU-estimated) and the
      last actual plate-solve pair (never IMU-touched) — plus
      :class:`SolveDiagnostics` and :class:`AlignmentResult`.

2. The ``last_image_metadata`` dict stamped by the camera process and
   read by the solver via ``shared_state.last_image_metadata()``.
   →  :class:`CameraFrameMetadata`

3. The ``imu_data`` dict produced by ``imu_pi.py`` and read via
   ``shared_state.imu()``.
   →  :class:`ImuSample`

4. The tagged-list messages on the alignment queues.
   →  :class:`AlignOnRaDec`, :class:`AlignCancel`,
      :class:`ReloadSqmCalibration`, :class:`AlignedResult`
   →  Union aliases :data:`SolverCommand`, :data:`AlignResponse`

Design notes
------------

* All equatorial RA/Dec/Roll triples are represented by a single
  :class:`Pointing` dataclass. The same type is used for the
  target-pixel pointing (which the IMU may update) and the
  camera-center pointing (``camera_solve``, which the IMU never
  touches); the distinction is made by the field name on
  :class:`PointingEstimate`, not by a separate type.

* Field names that already exist as keys in the legacy dicts are
  preserved verbatim (including non-PEP-8 capitalisation like
  ``Matches`` / ``RMSE`` / ``RA``) to minimise churn during
  migration and to match the keys tetra3 returns in its
  ``solution`` dict.

* Angles remain in degrees here — the existing ``solved`` dict is in
  degrees end-to-end, and changing that is a separate refactor. For
  the radian-based, quaternion-aware form used by
  :class:`ImuDeadReckoning`, see
  :class:`PiFinder.types.coordinates.RaDecRoll`; bridge via
  :meth:`Pointing.as_radecroll`.

* All structures must remain picklable so they can ride on
  ``multiprocessing.Queue`` and ``SharedStateObj`` proxies.
  ``numpy.quaternion`` already pickles, dataclasses pickle by default,
  and we avoid lambdas/closures in defaults.

* ``to_legacy_dict()`` / ``from_legacy_dict()`` helpers are included
  on :class:`PointingEstimate` so consumers and shared-state setters
  can be migrated incrementally (write the dataclass, read either
  form).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Tuple, Union

import quaternion

from PiFinder.types.coordinates import RaDecRoll


# =====================================================================
# Enums
# =====================================================================


class SolveSource(str, Enum):
    """Replaces the free-form ``solved["solve_source"]`` string.

    Inherits from ``str`` so existing equality checks against literals
    (``solved["solve_source"] == "CAM"``) keep working during migration.
    """

    CAMERA = "CAM"
    CAMERA_FAILED = "CAM_FAILED"
    IMU = "IMU"


# =====================================================================
# The core triple: one Pointing dataclass used everywhere
# =====================================================================


@dataclass
class Pointing:
    """A single equatorial pointing direction: RA, Dec, Roll in **degrees**.

    Used everywhere RA/Dec/Roll appears in the solving/integration flow:

    * :attr:`PointingEstimate.pointing` — the published pointing at
      the target pixel (eyepiece direction; may be IMU-updated).
    * :attr:`PointingEstimate.camera_solve` — the pointing at the
      camera center from the most recent plate-solve (never
      IMU-updated; anchor for dead-reckoning).

    All three fields are required: a ``Pointing`` instance is always a
    fully-defined direction. The "no pointing yet" state is expressed
    by ``Optional[Pointing]`` on the containing record (see
    :attr:`PointingEstimate.pointing`), not by nullable fields here.

    For the radian-based, quaternion-aware form used by
    :class:`ImuDeadReckoning`, bridge via :meth:`as_radecroll`.
    """

    RA: float
    Dec: float
    Roll: float

    def as_radecroll(self) -> RaDecRoll:
        """Return a :class:`RaDecRoll` (radians internally)."""
        return RaDecRoll(self.RA, self.Dec, self.Roll, deg=True)

    def to_dict(self) -> dict:
        """Legacy dict shape: ``{"RA": ..., "Dec": ..., "Roll": ...}``."""
        return {"RA": self.RA, "Dec": self.Dec, "Roll": self.Roll}

    @classmethod
    def from_dict(cls, d: dict) -> "Pointing":
        """Strict inverse of :meth:`to_dict`. Raises ``KeyError`` if any
        of ``RA`` / ``Dec`` / ``Roll`` is missing. For the partially-
        populated dicts seen during migration, gate the call at the
        :class:`PointingEstimate` level instead."""
        return cls(RA=d["RA"], Dec=d["Dec"], Roll=d["Roll"])


# =====================================================================
# Helpers
# =====================================================================


def _pointing_from_legacy(d: dict) -> Optional[Pointing]:
    """Build a :class:`Pointing` from a legacy-shaped dict if all three
    of RA/Dec/Roll are populated; otherwise ``None``. Used by the
    :meth:`PointingEstimate.from_legacy_dict` migration shim where
    partially-populated dicts are expected."""
    ra, dec, roll = d.get("RA"), d.get("Dec"), d.get("Roll")
    if ra is None or dec is None or roll is None:
        return None
    return Pointing(RA=ra, Dec=dec, Roll=roll)


# =====================================================================
# PointingPair — target pixel + camera center, produced together
# =====================================================================


@dataclass
class PointingPair:
    """A pair of equatorial pointings that are produced together by a
    single procedure: the eyepiece direction (target pixel) and the
    camera-axis direction (camera center).

    * On a plate-solve, tetra3 reports the camera-center RA/Dec from
      the matched stars and the target-pixel RA/Dec from the
      configured ``target_pixel``; both are returned by the same call.
    * On an IMU dead-reckoning update (planned), the same
      ``ImuDeadReckoning`` instance projects both pointings forward
      from the IMU quaternion; they advance in lock-step.

    Both fields are required: a ``PointingPair`` instance is always
    fully-defined. The "not produced yet" state is expressed by
    ``Optional[PointingPair]`` on the containing record (see
    :class:`PointingEstimate`).

    When no alignment offset is calibrated, ``target_pixel`` and
    ``camera_center`` may be identical; once :data:`solve_pixel`
    diverges from the image center, they differ.
    """

    target_pixel: Pointing
    camera_center: Pointing


# =====================================================================
# Other nested records inside PointingEstimate
# =====================================================================


@dataclass
class SolveDiagnostics:
    """Plate-solver diagnostics carried alongside the pointing.
    Forwarded from tetra3's ``solution`` dict.

    Replaces the loose ``Matches`` / ``RMSE`` / ``T_solve`` / ``FOV`` /
    ``Prob`` / ``T_extract`` keys that today get merged onto ``solved``
    via ``solved |= solution``.

    ``Matches`` defaults to 0 (not ``None``) because auto-exposure reads
    it on every solve, including failures, and expects an int.
    """

    Matches: int = 0
    RMSE: Optional[float] = None
    Prob: Optional[float] = None
    FOV: Optional[float] = None
    T_solve: Optional[float] = None
    T_extract: Optional[float] = None


@dataclass
class AlignmentResult:
    """Pixel where the alignment target landed in the camera frame.

    Replaces ``solved["x_target"]`` / ``solved["y_target"]``, which
    today are populated when ``target_sky_coord`` was passed to tetra3
    and then cleared after the solver posts ``["aligned", (y, x)]``.
    """

    x_target: Optional[float] = None
    y_target: Optional[float] = None

    def is_set(self) -> bool:
        return self.x_target is not None and self.y_target is not None

    def as_pixel_yx(self) -> Optional[Tuple[float, float]]:
        """Return ``(y, x)`` in camera image space, matching the existing
        ``align_result_queue`` message convention."""
        if not self.is_set():
            return None
        return (self.y_target, self.x_target)


# =====================================================================
# The big one: replaces the `solved` dict
# =====================================================================


@dataclass
class PointingEstimate:
    """Canonical 'where are we pointing?' record.

    Replaces the dict returned by
    ``solver.get_initialized_solved_dict()`` and travels through
    ``solver_queue`` and ``shared_state.set_solution()``.

    Naming follows the existing TODO at the top of ``integrator.py``
    (``solved -> pointing_estimate``).

    Pointing semantics
    ------------------
    Four pointings are tracked, organised as two
    :class:`PointingPair`\\ s:

    * :attr:`pointing` — the **published, current** pair. Both
      ``target_pixel`` and ``camera_center`` are produced fresh on a
      plate-solve and then advanced together by IMU dead-reckoning
      between solves. This is the pair downstream consumers (UI,
      web, SkySafari) should read.
    * :attr:`last_solve` — the **last actual plate-solve** pair.
      Never touched by the IMU. Its ``camera_center`` is the anchor
      passed to :meth:`ImuDeadReckoning.solve`; its ``target_pixel``
      is the truth-value reference for diagnostics, drift checks,
      and recovery paths.

    On a successful plate-solve both fields are set to the same
    :class:`PointingPair`. On an IMU dead-reckoning update only
    :attr:`pointing` advances; :attr:`last_solve` stays anchored at
    the most recent camera-derived truth.

    :attr:`Alt` / :attr:`Az` are topocentric, derived in the
    integrator from ``pointing.target_pixel`` + GPS + datetime.

    Timing fields use ``time.time()`` for ``solve_time`` and
    ``cam_solve_time``, but ``last_solve_attempt`` and
    ``last_solve_success`` use the camera frame's ``exposure_end``
    (not wall clock) so the solver can dedupe stale frames precisely.
    """

    # --- Published pair (target pixel + camera center; may be IMU-estimated) ---
    # ``None`` until the first successful solve. Once set, both
    # pointings inside the pair are fully populated.
    pointing: Optional[PointingPair] = None

    # --- Last actual plate-solve (never IMU-touched) ---
    # Anchor for IMU dead-reckoning. Survives failed solves so the
    # IMU still has a reference point.
    last_solve: Optional[PointingPair] = None

    # --- IMU reference at the time of the last plate-solved frame ---
    # Paired with :attr:`last_solve`: this is the IMU quaternion that
    # was stamped on the frame that produced that plate-solve, and
    # together they form the anchor for IMU dead-reckoning.
    last_solve_imu: Optional[quaternion.quaternion] = None

    # --- Derived horizontal coords ---
    Alt: Optional[float] = None
    Az: Optional[float] = None

    # --- Source and timing ---
    solve_source: Optional[SolveSource] = None
    solve_time: Optional[float] = None
    cam_solve_time: float = 0.0
    last_solve_attempt: float = 0.0
    last_solve_success: Optional[float] = None

    # --- Annotation ---
    constellation: Optional[str] = None

    # --- Sub-records ---
    diagnostics: SolveDiagnostics = field(default_factory=SolveDiagnostics)
    alignment: AlignmentResult = field(default_factory=AlignmentResult)

    # ----------------------------------------------------------------
    # Convenience predicates
    # ----------------------------------------------------------------

    def has_pointing(self) -> bool:
        """True if a published pointing exists (regardless of source)."""
        return self.pointing is not None

    def is_camera_solve(self) -> bool:
        return self.solve_source == SolveSource.CAMERA

    def is_imu_solve(self) -> bool:
        return self.solve_source == SolveSource.IMU

    # ----------------------------------------------------------------
    # Compatibility shim — emit the legacy dict shape so existing
    # consumers (web/UI/SkySafari) can be migrated incrementally.
    # ----------------------------------------------------------------

    def to_legacy_dict(self) -> dict:
        """Render this estimate in the legacy ``solved`` dict shape so
        consumers that still expect a dict keep working during the
        rollout."""
        empty_pointing = {"RA": None, "Dec": None, "Roll": None}
        # Legacy mapping:
        #   solved["RA"/"Dec"/"Roll"]   ← pointing.target_pixel (current)
        #   solved["camera_solve"]      ← last_solve.camera_center
        #                                 (the never-IMU-touched anchor)
        target = self.pointing.target_pixel if self.pointing else None
        anchor = self.last_solve.camera_center if self.last_solve else None
        d: dict = {
            "RA": target.RA if target else None,
            "Dec": target.Dec if target else None,
            "Roll": target.Roll if target else None,
            "camera_solve": anchor.to_dict() if anchor else dict(empty_pointing),
            "imu_quat": self.last_solve_imu,
            "Alt": self.Alt,
            "Az": self.Az,
            "solve_source": (self.solve_source.value if self.solve_source else None),
            "solve_time": self.solve_time,
            "cam_solve_time": self.cam_solve_time,
            "last_solve_attempt": self.last_solve_attempt,
            "last_solve_success": self.last_solve_success,
            "constellation": self.constellation,
            "Matches": self.diagnostics.Matches,
        }
        # Optional diagnostic fields are only included when set, to
        # match how tetra3 merges its solution into `solved`.
        for k in ("RMSE", "Prob", "FOV", "T_solve", "T_extract"):
            v = getattr(self.diagnostics, k)
            if v is not None:
                d[k] = v
        if self.alignment.x_target is not None:
            d["x_target"] = self.alignment.x_target
            d["y_target"] = self.alignment.y_target
        return d

    @classmethod
    def from_legacy_dict(cls, d: dict) -> "PointingEstimate":
        """Inverse of :meth:`to_legacy_dict`. Tolerant of missing keys
        so it can absorb partially-built dicts during migration.

        Note this conversion is lossy: the legacy dict carries the
        current target-pixel direction and the last-solve camera-center
        direction, but not the current camera-center direction or the
        last-solve target-pixel direction. On migration we reconstruct
        a :class:`PointingPair` for :attr:`pointing` by reusing the
        legacy camera_solve as the camera_center side, and use the
        same pair for :attr:`last_solve`. New producers will populate
        both pairs natively."""
        source_str = d.get("solve_source")
        target = _pointing_from_legacy(d)
        anchor = _pointing_from_legacy(d.get("camera_solve") or {})
        pair: Optional[PointingPair] = None
        if target is not None and anchor is not None:
            pair = PointingPair(target_pixel=target, camera_center=anchor)
        return cls(
            pointing=pair,
            last_solve=pair,
            last_solve_imu=d.get("imu_quat"),
            Alt=d.get("Alt"),
            Az=d.get("Az"),
            solve_source=SolveSource(source_str) if source_str else None,
            solve_time=d.get("solve_time"),
            cam_solve_time=d.get("cam_solve_time", 0.0),
            last_solve_attempt=d.get("last_solve_attempt", 0.0),
            last_solve_success=d.get("last_solve_success"),
            constellation=d.get("constellation"),
            diagnostics=SolveDiagnostics(
                Matches=d.get("Matches", 0),
                RMSE=d.get("RMSE"),
                Prob=d.get("Prob"),
                FOV=d.get("FOV"),
                T_solve=d.get("T_solve"),
                T_extract=d.get("T_extract"),
            ),
            alignment=AlignmentResult(
                x_target=d.get("x_target"),
                y_target=d.get("y_target"),
            ),
        )


# =====================================================================
# IMU sample — replaces shared_state.imu() dict
# =====================================================================


@dataclass
class ImuSample:
    """Single IMU orientation reading.

    Replaces the ``imu_data`` dict in ``imu_pi.py`` (keys: ``moving``,
    ``move_start``, ``move_end``, ``quat``, ``status``). The
    ``move_start`` / ``move_end`` fields are flagged ``# TODO: Remove``
    in the source — leaving them here for now so this is a strict
    superset of today's shape; they can be dropped in a follow-up.

    ``quat`` is scalar-first ``(w, x, y, z)``, as produced by
    ``quaternion.from_float_array(imu.avg_quat)``.
    """

    quat: quaternion.quaternion
    status: int = 0  # 3 == fully calibrated (BNO055)
    moving: bool = False
    move_start: Optional[float] = None  # TODO: remove (unused)
    move_end: Optional[float] = None  # TODO: remove (unused)

    def is_calibrated(self) -> bool:
        return self.status == 3


# =====================================================================
# Camera frame metadata — replaces shared_state.last_image_metadata()
# =====================================================================


@dataclass
class CameraFrameMetadata:
    """Metadata stamped by the camera process when an exposure finishes.

    Replaces the ``image_metadata`` dict built in
    ``camera_interface.py`` and read by the solver via
    ``shared_state.last_image_metadata()``.

    ``exposure_time`` is in **microseconds** (matching the existing
    convention); convert with ``exposure_time / 1_000_000`` for
    seconds (the solver already does this for SQM).

    ``imu_delta`` is the angular delta between IMU quaternions sampled
    at the start and end of the exposure, in **degrees**. The solver's
    fast-path uses this to reject blurry frames captured while moving.
    """

    exposure_start: float
    exposure_end: float
    exposure_time: int  # microseconds
    gain: float = 1.0
    imu: Optional[ImuSample] = None
    imu_delta: float = 0.0  # degrees


# =====================================================================
# Queue messages
# =====================================================================
#
# Today these are tagged lists like ["align_on_radec", ra, dec] /
# ["aligned", (y, x)]. Receivers dispatch on the leading string.
# Dataclasses + isinstance() dispatch give the same ergonomics with
# proper field names and type checking.


@dataclass
class AlignOnRaDec:
    """Arm the solver: next solve should pass ``target_sky_coord``
    to tetra3 and return the pixel coordinate for (ra, dec).
    Degrees.

    Distinct from :class:`Pointing` because alignment supplies only
    RA/Dec — no Roll — and the semantics are "target sought," not
    "where we are pointing."
    """

    ra: float
    dec: float


@dataclass
class AlignCancel:
    """Clear any pending alignment target in the solver."""

    pass


@dataclass
class ReloadSqmCalibration:
    """Tell the solver to rebuild its :class:`SQMCalculator` (the
    camera calibration profile may have changed)."""

    pass


SolverCommand = Union[AlignOnRaDec, AlignCancel, ReloadSqmCalibration]
"""Anything that can travel on ``align_command_queue`` (note the queue
also carries non-alignment commands today, hence the broader name)."""


@dataclass
class AlignedResult:
    """Reply on ``align_result_queue`` carrying the pixel where the
    alignment target landed.

    Field order matches the existing ``(y, x)`` tuple convention used
    by ``ui/align.py`` and stored as ``solve_pixel``.
    """

    y_target: float
    x_target: float

    def as_solve_pixel(self) -> Tuple[float, float]:
        """Return ``(y, x)`` — the order used by ``solve_pixel`` in
        ``shared_state`` and persisted in ``Config``."""
        return (self.y_target, self.x_target)


# A failure / cancellation response would extend this union in future.
AlignResponse = Union[AlignedResult]


# =====================================================================
# Convenience: the tetra3 raw return is also a dict, but it isn't our
# code to retype. We document the merge boundary here so consumers can
# see what flows in.
# =====================================================================


def merge_tetra3_solution(
    estimate: PointingEstimate,
    solution: dict,
    imu_sample: Optional[ImuSample],
) -> PointingEstimate:
    """Reference implementation of how a tetra3 ``solution`` dict
    should be folded into a :class:`PointingEstimate`. This mirrors
    the existing ``solved |= solution`` step in ``solver.py``, plus
    the camera-vs-target-pixel swap.

    Not wired up — illustrative only. Lives here so the proposed
    dataclasses have a clear seam against the upstream library that
    still returns dicts.
    """
    estimate.diagnostics = SolveDiagnostics(
        Matches=solution.get("Matches", 0),
        RMSE=solution.get("RMSE"),
        Prob=solution.get("Prob"),
        FOV=solution.get("FOV"),
        T_solve=solution.get("T_solve"),
        T_extract=solution.get("T_extract"),
    )

    if solution.get("RA") is None:
        # Failed solve — clear the current pointing, but preserve
        # last_solve as the IMU anchor / recovery reference.
        estimate.pointing = None
        return estimate

    # On a successful tetra3 solve, RA / Dec / Roll are all populated.
    # Use direct indexing so a missing field surfaces loudly rather
    # than silently producing a half-defined pointing.
    camera_center = Pointing(
        RA=solution["RA"],
        Dec=solution["Dec"],
        Roll=solution["Roll"],
    )
    target_pixel = Pointing(
        RA=solution.get("RA_target", solution["RA"]),
        Dec=solution.get("Dec_target", solution["Dec"]),
        Roll=solution["Roll"],
    )
    pair = PointingPair(target_pixel=target_pixel, camera_center=camera_center)

    # Fresh plate-solve: both fields point at the same pair.
    # Subsequent IMU updates will advance ``pointing`` while leaving
    # ``last_solve`` anchored at this snapshot.
    estimate.pointing = pair
    estimate.last_solve = pair

    # Alignment pixel (only present when target_sky_coord was set)
    estimate.alignment = AlignmentResult(
        x_target=solution.get("x_target"),
        y_target=solution.get("y_target"),
    )

    # IMU anchor for the dead-reckoner
    if imu_sample is not None:
        estimate.last_solve_imu = imu_sample.quat

    return estimate


# =====================================================================
# Exports
# =====================================================================

__all__ = [
    "AlignCancel",
    "AlignOnRaDec",
    "AlignResponse",
    "AlignedResult",
    "AlignmentResult",
    "CameraFrameMetadata",
    "ImuSample",
    "Pointing",
    "PointingEstimate",
    "PointingPair",
    "ReloadSqmCalibration",
    "SolveDiagnostics",
    "SolveSource",
    "SolverCommand",
    "merge_tetra3_solution",
]
