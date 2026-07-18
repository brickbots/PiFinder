"""
Dataclasses for the plate-solving / integration flow.

These types implement the canonical Positioning vocabulary
(see ``docs/ax/positioning/CONTEXT.md`` and
``docs/adr/0001-positioning-vocabulary.md``).

* Two **axes**: ``camera`` (optical axis) and ``aligned`` (eyepiece
  direction, calibrated via the **target pixel**).
* Two **states** per axis: ``solve`` (latest plate-solve value;
  never IMU-touched) and ``estimate`` (current value, equal to ``solve``
  immediately after a plate-solve and advanced by IMU dead-reckoning
  between solves).
* Canonical access shape: ``pointing.<axis>.<state>.<RA|Dec|Roll>`` —
  e.g. ``pointing.aligned.estimate.RA``.
* Bare "pointing" in prose means ``pointing.aligned.estimate``.

The data structures here replace four legacy dicts:

1. The ``solved`` dict, which was split by role:
   →  :class:`PointingEstimate`, the canonical record published via
      ``shared_state.set_solution()``. Its :attr:`pointing` field holds a
      :class:`PointingMatrix` with the four cells of the 2 × 2 matrix,
      plus :class:`SolveDiagnostics` and :class:`AlignmentResult`. Built
      and owned by the integrator.
   →  :class:`SolveResult` (``SuccessfulSolve`` | ``FailedSolve``), the
      message the solver puts on ``solver_queue`` describing one
      plate-solve attempt. See
      ``docs/adr/0012-solver-integrator-message.md``.

2. The tagged-list messages on the alignment queues.
   →  :class:`AlignOnRaDec`, :class:`AlignCancel`,
      :class:`ReloadSqmCalibration` (commands → solver)
   →  :class:`AlignedResult` (response → UI)
   →  Union aliases :data:`SolverCommand`, :data:`AlignResponse`

The ``last_image_metadata`` and ``imu_data`` dicts continue to travel as
plain dicts; :class:`CameraFrameMetadata` / :class:`ImuSample` are
defined here for a future migration of those interfaces.

Design notes
------------

* All equatorial RA/Dec/Roll triples are represented by a single
  :class:`Pointing` dataclass. The same type is used for every cell of
  the 2 × 2 matrix; the cell is identified by its position
  (``pointing.<axis>.<state>``), not by a separate type.

* Angles remain in degrees here — :class:`PiFinder.types.coordinates.RaDecRoll`
  is the radian-based, quaternion-aware form used by
  :class:`ImuDeadReckoning`. Bridge via :meth:`Pointing.as_radecroll`.

* All structures must remain picklable so they can ride on
  ``multiprocessing.Queue`` and ``SharedStateObj`` proxies. Dataclasses
  pickle by default and we avoid lambdas/closures in defaults — but a bare
  ``numpy.quaternion`` must **not** be pickled directly: it leaks in
  numpy-quaternion 2023.0.4 (see ``_quat_to_floats`` and
  ``memory/imu-quaternion-pickle-leak``). The dataclasses carrying a
  quaternion field (:class:`ImuSample`, :class:`PointingEstimate`,
  :class:`SuccessfulSolve`) override ``__getstate__``/``__setstate__`` to
  pickle it as 4 floats; the in-process attribute stays a quaternion.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple, Union

import quaternion

from PiFinder.types.coordinates import RaDecRoll


# =====================================================================
# Pickle helpers: never serialise a bare numpy.quaternion
# =====================================================================
#
# ``pickle.dumps(numpy.quaternion)`` leaks memory in numpy-quaternion
# 2023.0.4 (~16 MB/min when a hot loop publishes one across a multiprocessing
# Manager proxy — see ``memory/imu-quaternion-pickle-leak``). A tuple of plain
# floats pickles cleanly. Dataclasses that carry a bare quaternion field
# therefore override ``__getstate__``/``__setstate__`` to round-trip it through
# these helpers: the in-process attribute stays a real ``numpy.quaternion``
# (zero consumer changes), only the pickled form is 4 floats. The float
# round-trip is bit-exact.


def _quat_to_floats(q):
    """Scalar-first ``(w, x, y, z)`` floats for pickling, or ``None``."""
    if q is None:
        return None
    return (float(q.w), float(q.x), float(q.y), float(q.z))


def _floats_to_quat(v):
    """Inverse of :func:`_quat_to_floats`: rebuild a ``numpy.quaternion``.

    Idempotent and ``None``-safe — only a 4-tuple is converted, so an
    already-rebuilt value (or ``None``) passes through unchanged.
    """
    return quaternion.quaternion(*v) if isinstance(v, tuple) else v


# =====================================================================
# Enums
# =====================================================================


class SolveSource(str, Enum):
    """Records which subsystem produced the current pointing estimate.

    Inherits from ``str`` so equality checks against literals
    (``estimate.solve_source == "CAM"``) keep working in any consumer
    that hasn't been migrated to the enum yet.
    """

    CAMERA = "CAM"
    CAMERA_FAILED = "CAM_FAILED"
    IMU = "IMU"


# =====================================================================
# The leaf triple: one Pointing dataclass per cell of the matrix
# =====================================================================


@dataclass
class Pointing:
    """A single equatorial pointing direction: RA, Dec, Roll in **degrees**.

    Used at every leaf of the pointing matrix:

    * ``pointing.camera.solve`` — camera-axis RA/Dec/Roll from the
      latest plate-solve.
    * ``pointing.camera.estimate`` — current camera-axis value
      (may be IMU-progressed).
    * ``pointing.aligned.solve`` — aligned-axis (eyepiece) RA/Dec/Roll
      from the latest plate-solve.
    * ``pointing.aligned.estimate`` — current aligned-axis value;
      this is what bare "pointing" means in prose, and what every
      downstream consumer ultimately reads.

    All three fields are required: a ``Pointing`` instance is always a
    fully-defined direction. The "no value yet" state is expressed by
    ``Optional[Pointing]`` on the containing :class:`PointingAxis`.

    For the radian-based, quaternion-aware form used by
    :class:`ImuDeadReckoning`, bridge via :meth:`as_radecroll`.
    """

    RA: float
    Dec: float
    Roll: float

    def as_radecroll(self) -> RaDecRoll:
        """Return a :class:`RaDecRoll` (radians internally)."""
        return RaDecRoll(self.RA, self.Dec, self.Roll, deg=True)

    @classmethod
    def from_radecroll(cls, rdr: RaDecRoll) -> "Pointing":
        """Build a degrees-based :class:`Pointing` from a radian
        :class:`RaDecRoll` — the inverse of :meth:`as_radecroll`.

        Lives on ``Pointing`` (not ``RaDecRoll``) so the dependency only
        runs ``positioning`` → ``coordinates``, never back. Reads the
        radian fields directly: they are always plain floats (``nan`` for
        an unset axis), matching ``Pointing``'s invariant that every
        instance is a full triple. The caller is responsible for only
        converting a valid (non-``nan``) ``RaDecRoll``.
        """
        return cls(
            RA=math.degrees(rdr.ra),
            Dec=math.degrees(rdr.dec),
            Roll=math.degrees(rdr.roll),
        )


# =====================================================================
# PointingAxis — one axis, both states
# =====================================================================


@dataclass
class PointingAxis:
    """One axis of pointing, tracked across both states.

    Holds the two values for a single axis (``camera`` or ``aligned``):

    * :attr:`solve` — RA/Dec/Roll from the latest plate-solve.
      ``None`` until the first successful solve. Never IMU-touched
      once set.
    * :attr:`estimate` — the current value. Equal to ``solve``
      immediately after a plate-solve; may be IMU-progressed between
      solves. This is what downstream consumers should read.

    Both fields are ``Optional[Pointing]`` because a fresh
    :class:`PointingEstimate` may exist before any solve has happened.
    """

    solve: Optional[Pointing] = None
    estimate: Optional[Pointing] = None


# =====================================================================
# PointingMatrix — both axes, both states (the 2 × 2 matrix)
# =====================================================================


@dataclass
class PointingMatrix:
    """The 2 × 2 matrix of pointings.

    Two axes (``camera`` for the optical-axis direction, ``aligned``
    for the eyepiece-aligned direction), each as a :class:`PointingAxis`
    holding ``solve`` and ``estimate`` values. Canonical access shape
    is ``<matrix>.<axis>.<state>.<RA|Dec|Roll>``.

    On a successful plate-solve, both axes' ``solve`` and ``estimate``
    are populated together: ``camera.{solve,estimate}`` from tetra3's
    matched-stars solution, and ``aligned.{solve,estimate}`` from the
    target-pixel solution. Between solves, the IMU advances only the
    ``estimate`` cells; the ``solve`` cells stay anchored at the last
    plate-solve.

    When no alignment offset is calibrated (target pixel at image
    center), :attr:`aligned` may equal :attr:`camera`.
    """

    camera: PointingAxis = field(default_factory=PointingAxis)
    aligned: PointingAxis = field(default_factory=PointingAxis)


# =====================================================================
# Other nested records inside PointingEstimate
# =====================================================================


@dataclass
class SolveDiagnostics:
    """Plate-solver diagnostics carried alongside the pointing.
    Forwarded from tetra3's ``solution`` dict.

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

    In the canonical vocabulary this **is** the target pixel — the
    ``(Y, X)`` image-space coordinate produced by the alignment system.

    Field names ``x_target`` / ``y_target`` match the tetra3
    ``solution`` dict keys; use :meth:`target_pixel` to retrieve the
    canonical ``(Y, X)`` tuple.
    """

    x_target: Optional[float] = None
    y_target: Optional[float] = None

    def is_set(self) -> bool:
        return self.x_target is not None and self.y_target is not None

    def target_pixel(self) -> Optional[Tuple[float, float]]:
        """Return the target pixel as ``(Y, X)`` in camera image space,
        matching the convention used by alignment queue messages and
        the persisted target-pixel config value."""
        if self.x_target is None or self.y_target is None:
            return None
        return (self.y_target, self.x_target)


# =====================================================================
# The big one: the published pointing record
# =====================================================================


@dataclass
class PointingEstimate:
    """Canonical 'where are we pointing?' record.

    Travels through ``solver_queue`` and ``shared_state.set_solution()``.

    Pointing semantics
    ------------------
    The pointing matrix is :attr:`pointing`, a :class:`PointingMatrix`
    holding the four cells of the 2 × 2 matrix
    (``camera``/``aligned`` × ``solve``/``estimate``). Canonical access
    is ``estimate.pointing.<axis>.<state>.<RA|Dec|Roll>``; downstream
    consumers (UI, web, SkySafari) read ``pointing.aligned.estimate``.

    The IMU anchor used for dead-reckoning is the pair of
    ``pointing.camera.solve`` (camera-axis truth) and :attr:`imu_anchor`
    (the IMU quaternion sampled at the same frame).

    :attr:`Alt` / :attr:`Az` are topocentric, derived in the integrator
    from ``pointing.aligned.estimate`` + GPS + datetime.

    :attr:`estimate_time` is the **measurement epoch** of the data behind
    the current estimate — *when the reading this value is based on was
    captured*, not when the integrator produced it. Camera estimate →
    the frame's ``exposure_end``; IMU-progressed estimate → the IMU
    sample's ``timestamp``. Both ride the same ``time.time()`` clock, so
    ``time.time() - estimate_time`` is a true "age of the fix" regardless
    of source. ``last_solve_attempt`` / ``last_solve_success`` are the
    camera frame's ``exposure_end`` (so the solver can dedupe stale
    frames precisely); "solve" there means plate-solve, never IMU.

    :attr:`matched_centroids`, :attr:`matched_stars`, and
    :attr:`matched_catID` carry raw
    tetra3 matched-star outputs needed by the SQM calibration UI for
    offline replay of SQM calculations against cached frames, and by the
    Focus screen's stable star-identity slots. A failed solve
    preserves the last successful set, so consumers must also match
    ``last_solve_success`` to the frame timestamp.
    """

    # --- The 2 × 2 pointing matrix ---
    # Fresh default has all four cells = None. Populated by the solver
    # on a successful plate-solve; advanced on the estimate side by the
    # integrator's IMU dead-reckoning.
    pointing: PointingMatrix = field(default_factory=PointingMatrix)

    # --- IMU anchor ---
    # The IMU quaternion sampled on the frame that produced the current
    # ``pointing.<axis>.solve`` cells. Paired with
    # ``pointing.camera.solve`` to seed IMU dead-reckoning.
    imu_anchor: Optional[quaternion.quaternion] = None

    # --- Derived horizontal coords ---
    Alt: Optional[float] = None
    Az: Optional[float] = None

    # --- Source and timing ---
    solve_source: Optional[SolveSource] = None
    # Measurement epoch of the current estimate's data: camera frame
    # ``exposure_end`` on a solve, IMU sample ``timestamp`` on an IMU
    # advance. See class docstring.
    estimate_time: Optional[float] = None
    last_solve_attempt: float = 0.0
    last_solve_success: Optional[float] = None

    # --- Annotation ---
    constellation: Optional[str] = None

    # --- Sub-records ---
    diagnostics: SolveDiagnostics = field(default_factory=SolveDiagnostics)
    alignment: AlignmentResult = field(default_factory=AlignmentResult)

    # --- Raw tetra3 output kept for SQM replay ---
    # ``matched_centroids``: list of (y, x) tuples for stars tetra3
    # matched to known references.
    # ``matched_stars``: parallel list of catalog star records, where
    # index [2] is the catalog magnitude (consumed by SQM).
    # Retained from the last successful solve across failed attempts; pair
    # with ``last_solve_success`` before consuming.
    matched_centroids: Optional[List[Tuple[float, float]]] = None
    matched_stars: Optional[list] = None
    matched_catID: Optional[list] = None

    # ----------------------------------------------------------------
    # Convenience predicates
    # ----------------------------------------------------------------

    def has_pointing(self) -> bool:
        """True if a published pointing exists — i.e.
        ``pointing.aligned.estimate`` is populated."""
        return self.pointing.aligned.estimate is not None

    def is_camera_solve(self) -> bool:
        return self.solve_source == SolveSource.CAMERA

    def is_imu_solve(self) -> bool:
        return self.solve_source == SolveSource.IMU

    # Pickle the ``imu_anchor`` quaternion as floats (see _quat_to_floats):
    # the integrator publishes a deepcopy of this estimate across the proxy
    # via ``set_solution`` on every cycle.
    def __getstate__(self) -> dict:
        state = self.__dict__.copy()
        state["imu_anchor"] = _quat_to_floats(state["imu_anchor"])
        return state

    def __setstate__(self, state: dict) -> None:
        state["imu_anchor"] = _floats_to_quat(state.get("imu_anchor"))
        self.__dict__.update(state)


# =====================================================================
# SolveResult — the solver → integrator message (rides solver_queue)
# =====================================================================
#
# The solver produces *solve-truth only*; it has no ``estimate`` concept
# (IMU progression happens in the integrator). So the message carries
# flat per-axis :class:`Pointing`s, not the 2 × 2 matrix. The integrator
# alone builds the canonical :class:`PointingEstimate`, applying a
# ``SolveResult`` onto its long-lived instance.
#
# Two concrete types under a union, dispatched by ``isinstance()`` in the
# integrator (mirroring :data:`SolverCommand` / :data:`AlignResponse`).
# See ``docs/adr/0012-solver-integrator-message.md``.


@dataclass
class SuccessfulSolve:
    """A plate-solve attempt that produced a pointing.

    Carries solve-truth for both axes as **flat** :class:`Pointing`s
    (no ``solve``/``estimate`` split — the solver never IMU-progresses).
    The integrator fans ``camera``/``aligned`` into both the ``solve``
    and ``estimate`` cells of its long-lived :class:`PointingEstimate`
    and reseeds the dead-reckoner.

    ``imu_anchor`` is ``Optional``: a solve can succeed on a frame that
    carried no IMU sample.

    There is no separate ``solve_time``: the solved frame's epoch is
    ``last_solve_success`` (== ``last_solve_attempt`` == the frame's
    ``exposure_end`` on a success), which the integrator assigns to
    :attr:`PointingEstimate.estimate_time`.
    """

    camera: Pointing
    aligned: Pointing
    imu_anchor: Optional[quaternion.quaternion]
    last_solve_attempt: float
    last_solve_success: float
    diagnostics: SolveDiagnostics = field(default_factory=SolveDiagnostics)
    alignment: AlignmentResult = field(default_factory=AlignmentResult)
    matched_centroids: Optional[List[Tuple[float, float]]] = None
    matched_stars: Optional[list] = None
    matched_catID: Optional[list] = None

    # Pickle the ``imu_anchor`` quaternion as floats (see _quat_to_floats):
    # this message rides ``solver_queue``, a pickle boundary.
    def __getstate__(self) -> dict:
        state = self.__dict__.copy()
        state["imu_anchor"] = _quat_to_floats(state["imu_anchor"])
        return state

    def __setstate__(self, state: dict) -> None:
        state["imu_anchor"] = _floats_to_quat(state.get("imu_anchor"))
        self.__dict__.update(state)


@dataclass
class FailedSolve:
    """A solve attempt that produced no pointing.

    Carries only the diagnostics and timing the integrator needs to
    refresh auto-exposure and dedupe stale frames. Triggers the
    integrator to preserve its ``solve`` cells + anchor **and** its
    ``estimate`` cells (so once anchored, dead-reckoning keeps a pointing
    and ``solve_state`` stays true), refresh diagnostics, and publish with
    ``solve_source=CAMERA_FAILED``.
    """

    diagnostics: SolveDiagnostics = field(default_factory=SolveDiagnostics)
    last_solve_attempt: float = 0.0
    last_solve_success: Optional[float] = None


SolveResult = Union[SuccessfulSolve, FailedSolve]
"""The message on ``solver_queue`` describing one plate-solve attempt.
The integrator dispatches on ``isinstance()``."""


# =====================================================================
# IMU sample — future replacement for shared_state.imu() dict
# =====================================================================


@dataclass
class ImuSample:
    """Single IMU orientation reading.

    The value carried on ``shared_state`` via ``set_imu()`` / ``imu()``
    and bundled into each camera frame's metadata. Replaces the legacy
    ``{"quat": ..., "status": ..., "moving": ...}`` dict (the unused
    ``move_start`` / ``move_end`` keys were dropped in the migration).

    ``quat`` is scalar-first ``(w, x, y, z)``, as produced by
    ``quaternion.from_float_array(imu.avg_quat)``. It pickles as 4 plain
    floats (see ``__getstate__``) to dodge the numpy-quaternion leak — the
    IMU loop publishes this sample across the proxy every cycle; keep those
    hooks.

    ``timestamp`` is the wall-clock (``time.time()``) instant the IMU
    process sampled this orientation — the IMU-side input to
    :attr:`PointingEstimate.estimate_time`. It is the sample epoch, not
    the (later) moment a consumer reads the sample.

    ``gyro`` / ``accel`` are the raw sensor readings at the same sample,
    recorded for telemetry. ``None`` when the sensor doesn't expose them
    (e.g. the fake IMU).
    """

    quat: quaternion.quaternion
    timestamp: float
    status: int = 0  # 3 == fully calibrated (BNO055)
    moving: bool = False
    # Raw gyroscope angular velocity (rad/s) and linear acceleration
    # (m/s², gravity removed) — captured for telemetry recording.
    gyro: Optional[Tuple[float, float, float]] = None
    accel: Optional[Tuple[float, float, float]] = None

    def is_calibrated(self) -> bool:
        return self.status == 3

    def to_dict(self) -> dict:
        """JSON-friendly form for the web API. ``quat`` becomes a
        scalar-first ``[w, x, y, z]`` list."""
        return {
            "quat": quaternion.as_float_array(self.quat).tolist(),
            "timestamp": self.timestamp,
            "status": self.status,
            "moving": self.moving,
            "gyro": list(self.gyro) if self.gyro is not None else None,
            "accel": list(self.accel) if self.accel is not None else None,
        }

    # Pickle ``quat`` as floats (see _quat_to_floats): the IMU loop publishes
    # this sample across the proxy via ``set_imu`` on every cycle.
    def __getstate__(self) -> dict:
        state = self.__dict__.copy()
        state["quat"] = _quat_to_floats(state["quat"])
        return state

    def __setstate__(self, state: dict) -> None:
        state["quat"] = _floats_to_quat(state.get("quat"))
        self.__dict__.update(state)


# =====================================================================
# Camera frame metadata — future replacement for shared_state.last_image_metadata()
# =====================================================================


@dataclass
class CameraFrameMetadata:
    """Metadata stamped by the camera process when an exposure finishes.

    Not wired into ``shared_state`` yet — frame metadata still travels
    as a dict; this dataclass is the destination shape for a future
    migration.

    ``exposure_time`` is in **microseconds** (matching the existing
    convention); convert with ``exposure_time / 1_000_000`` for
    seconds.

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
# Replace tagged lists like ["align_on_radec", ra, dec] /
# ["aligned", (y, x)]. Receivers dispatch on isinstance() with proper
# field names and type checking.


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
    by ``ui/align.py`` and persisted as the target pixel.
    """

    y_target: float
    x_target: float

    def as_target_pixel(self) -> Tuple[float, float]:
        """Return ``(y, x)`` — the order used by the target pixel
        on ``shared_state`` and persisted in ``Config``."""
        return (self.y_target, self.x_target)


# A failure / cancellation response would extend this union in future.
AlignResponse = Union[AlignedResult]


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
    "FailedSolve",
    "ImuSample",
    "Pointing",
    "PointingAxis",
    "PointingEstimate",
    "PointingMatrix",
    "ReloadSqmCalibration",
    "SolveDiagnostics",
    "SolveResult",
    "SolveSource",
    "SolverCommand",
    "SuccessfulSolve",
]
