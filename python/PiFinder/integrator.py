#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Integrator process.

Owns the long-lived :class:`PointingEstimate`. Applies per-attempt
:class:`SolveResult` messages from ``solver_queue`` onto the long-lived
estimate, advances the ``estimate`` cells via IMU dead-reckoning between
solves, and publishes the result to ``shared_state``.

Responsibility split:

* The **solver** holds no long-lived state. It builds a
  :class:`SolveResult` per attempt (a :class:`SuccessfulSolve` or
  :class:`FailedSolve`) and pushes it to ``solver_queue``.

* The **integrator** holds the anchor and is the sole owner of the
  :class:`PointingEstimate`. ``pointing.<axis>.solve`` cells are the IMU
  dead-reckoning reference, updated only on a :class:`SuccessfulSolve`.
  On a :class:`FailedSolve` it preserves the previous ``solve`` cells so
  dead-reckoning continues.

A single :class:`ImuDeadReckoning` instance handles both axes: it
captures the (camera, aligned) pair at each successful solve as a
static ``q_cam2aligned`` rotation, and reapplies it to the camera
prediction during dead-reckoning. The IDR remains a math primitive
(``RaDecRoll`` in, ``RaDecRoll`` out); this module bridges between it
and :class:`PointingEstimate`.

Telemetry record/replay is handled by :class:`TelemetryManager`
(``telemetry.py``). Replayed sessions are converted back into
:class:`SolveResult` / :class:`ImuSample` messages and fed through the
same ``_apply_*`` / ``_advance_with_imu`` paths as live data.
"""

from __future__ import annotations

import copy
import logging
import queue
import time
from typing import Optional

import numpy as np
import quaternion  # numpy-quaternion

import PiFinder.calc_utils as calc_utils
from PiFinder import config
from PiFinder import state_utils
from PiFinder.multiproclogging import MultiprocLogging
from PiFinder.pointing_model.imu_dead_reckoning import ImuDeadReckoning
import PiFinder.pointing_model.quaternion_transforms as qt
from PiFinder.telemetry import TelemetryManager
from PiFinder.types.positioning import (
    FailedSolve,
    ImuSample,
    Pointing,
    PointingAxis,
    PointingEstimate,
    SolveResult,
    SolveSource,
    SuccessfulSolve,
)

logger = logging.getLogger("IMU.Integrator")

# Use IMU tracking if the angle moved is above this deadband.
IMU_MOVED_ANG_THRESHOLD = np.deg2rad(0.06)


def integrator(
    shared_state,
    solver_queue,
    console_queue,
    log_queue,
    is_debug=False,
    command_queue=None,
    camera_command_queue=None,
):
    MultiprocLogging.configurer(log_queue)
    if is_debug:
        logger.setLevel(logging.DEBUG)
    logger.debug("Starting Integrator")

    telemetry = None
    try:
        cfg = config.Config()
        screen_direction = cfg.get_option("screen_direction")

        # Single IMU dead-reckoner handling both axes. Seeded with the
        # (camera, aligned) pair at each successful plate-solve.
        idr = ImuDeadReckoning(screen_direction)

        # Long-lived estimate. `solve` cells == anchor; `estimate` cells
        # are what consumers read. Empty until the first successful solve.
        estimate = PointingEstimate()
        # Epoch of the last estimate we published; gate re-publishing on it.
        last_published_time = time.time()

        was_replaying = False
        telemetry = TelemetryManager(
            cfg, shared_state, console_queue, camera_command_queue
        )

        while True:
            state_utils.sleep_for_framerate(shared_state)

            telemetry.poll_commands(command_queue)

            pointing_updated = False

            # 1. Pull the next message — from the replay stream when
            #    replaying, otherwise from the solver queue.
            solve_result: Optional[SolveResult] = None
            replay_imu: Optional[ImuSample] = None

            if telemetry.replaying:
                if not was_replaying:
                    was_replaying = True
                    # Recorded epochs are in the past; rewind the publish
                    # gate so replayed estimates pass the newer-than check.
                    last_published_time = 0.0
                # The solver keeps running during replay; discard its output.
                _drain_queue(solver_queue)
                message = telemetry.next_replay_message()
                if isinstance(message, (SuccessfulSolve, FailedSolve)):
                    solve_result = message
                elif isinstance(message, ImuSample):
                    replay_imu = message
            else:
                if was_replaying:
                    # Replay ended — reset to a clean unanchored state.
                    was_replaying = False
                    estimate = PointingEstimate()
                    idr.reset()
                    last_published_time = time.time()
                    logger.info("Replay ended, integrator state reset")
                try:
                    solve_result = solver_queue.get(block=False)
                except queue.Empty:
                    pass

            if isinstance(solve_result, SuccessfulSolve):
                telemetry.record_solve(
                    solve_result, predicted=estimate.pointing.aligned.estimate
                )
                estimate = _apply_successful_solve(estimate, solve_result, idr)
                pointing_updated = True
            elif isinstance(solve_result, FailedSolve):
                telemetry.record_solve(
                    solve_result, predicted=estimate.pointing.aligned.estimate
                )
                estimate = _apply_failed_solve(estimate, solve_result)
                # Publish unconditionally so auto-exposure sees the failed
                # attempt (Matches=0, fresh last_solve_attempt). The estimate
                # cells are preserved, so once anchored this keeps solve_state
                # True and the last pointing visible; the IMU advance below
                # progresses it when motion exceeds the deadband.
                shared_state.set_solution(copy.deepcopy(estimate))

            # 2. Pull the current IMU sample — from the replay stream when
            #    replaying — and record it. Recording happens before the
            #    anchor gate so sessions capture IMU data from the start,
            #    not only once the first solve has anchored dead-reckoning.
            #    (record_imu dedupes on sample timestamp and is a no-op
            #    while replaying or when recording is off.)
            imu = replay_imu if telemetry.replaying else shared_state.imu()
            if imu:
                telemetry.record_imu(imu)

            # If we have an anchor and didn't just do a fresh plate-solve,
            # try to advance the estimate via IMU dead-reckoning.
            if (
                imu
                and not pointing_updated
                and idr.is_initialized()
                and estimate.imu_anchor is not None
            ):
                if _advance_with_imu(estimate, idr, imu):
                    pointing_updated = True

            # 3. Publish if we updated something newer than what we last sent.
            if (
                pointing_updated
                and estimate.estimate_time is not None
                and estimate.estimate_time > last_published_time
                and estimate.pointing.aligned.estimate is not None
            ):
                aligned = estimate.pointing.aligned.estimate
                estimate.constellation = _get_constellation(aligned.RA, aligned.Dec)
                estimate.Alt, estimate.Az = _get_alt_az(
                    aligned.RA,
                    aligned.Dec,
                    shared_state.location(),
                    shared_state.datetime(),
                )

                shared_state.set_solution(copy.deepcopy(estimate))
                last_published_time = estimate.estimate_time

            telemetry.flush()

    except EOFError:
        logger.error("Main no longer running for integrator")
    finally:
        if telemetry is not None:
            telemetry.stop()


def _apply_successful_solve(
    estimate: PointingEstimate,
    result: SuccessfulSolve,
    idr: ImuDeadReckoning,
) -> PointingEstimate:
    """Apply a :class:`SuccessfulSolve` onto the long-lived estimate.

    Fans the flat ``camera``/``aligned`` solve-truth into both the
    ``solve`` and ``estimate`` cells of each axis, refreshes the IMU
    anchor, and reseeds the dead-reckoner with the (camera, aligned)
    pair + anchor quaternion. The solved frame's epoch
    (``last_solve_success`` == the frame's ``exposure_end``) becomes
    the aggregate's ``estimate_time``.
    """
    estimate.pointing.camera = PointingAxis(
        solve=result.camera,
        estimate=result.camera,
    )
    estimate.pointing.aligned = PointingAxis(
        solve=result.aligned,
        estimate=result.aligned,
    )

    estimate.imu_anchor = result.imu_anchor
    estimate.solve_source = SolveSource.CAMERA
    estimate.estimate_time = result.last_solve_success
    estimate.last_solve_attempt = result.last_solve_attempt
    estimate.last_solve_success = result.last_solve_success
    estimate.diagnostics = result.diagnostics
    estimate.alignment = result.alignment
    estimate.matched_centroids = result.matched_centroids
    estimate.matched_stars = result.matched_stars
    estimate.matched_catID = result.matched_catID

    # Reseed the dead-reckoner from the new anchor. camera/aligned are
    # always present on a SuccessfulSolve, so no None-guard is needed.
    q_anchor = result.imu_anchor
    if q_anchor is None:
        q_anchor = quaternion.quaternion(np.nan)
    idr.solve(
        result.camera.as_radecroll(),
        result.aligned.as_radecroll(),
        q_anchor,
    )

    return estimate


def _apply_failed_solve(
    estimate: PointingEstimate,
    result: FailedSolve,
) -> PointingEstimate:
    """Apply a :class:`FailedSolve` onto the long-lived estimate.

    Preserves the ``solve`` cells and ``imu_anchor`` (the anchor must
    survive so dead-reckoning continues) and refreshes diagnostics/timing
    with ``solve_source=CAMERA_FAILED``.

    The ``estimate`` cells are **preserved**, not cleared: once anchored,
    the last (IMU-progressed) pointing remains the best available answer
    and the IMU advance progresses it on subsequent loops. Clearing them
    here would drop ``solve_state`` to False ("no solve") whenever a solve
    failed while the IMU sat in its deadband — even though dead-reckoning
    still knows where we point. ``estimate_time`` is likewise left intact;
    a fresh epoch only attaches when the IMU actually advances the cells.
    """
    estimate.diagnostics = result.diagnostics
    estimate.last_solve_attempt = result.last_solve_attempt
    estimate.last_solve_success = result.last_solve_success
    estimate.solve_source = SolveSource.CAMERA_FAILED
    return estimate


def _advance_with_imu(
    estimate: PointingEstimate,
    idr: ImuDeadReckoning,
    imu: ImuSample,
) -> bool:
    """Advance ``estimate``'s ``estimate`` cells via IMU dead-reckoning.

    Returns ``True`` if cells were advanced, ``False`` if IMU motion
    was below the deadband.
    """
    q_x2imu = imu.quat
    assert isinstance(
        q_x2imu, quaternion.quaternion
    ), "Expecting quaternion.quaternion type"

    angle_moved = qt.get_quat_angular_diff(estimate.imu_anchor, q_x2imu)
    if angle_moved <= IMU_MOVED_ANG_THRESHOLD:
        return False

    logger.debug(
        "Track using IMU: angle moved since anchor = %.4f deg (> threshold %.4f deg)",
        np.rad2deg(angle_moved),
        np.rad2deg(IMU_MOVED_ANG_THRESHOLD),
    )

    predicted = idr.predict(q_x2imu)
    if predicted is None:
        return False
    camera_radecroll, aligned_radecroll = predicted

    # predict() returned non-None RaDecRoll, so these are valid pointings.
    estimate.pointing.aligned.estimate = Pointing.from_radecroll(aligned_radecroll)
    estimate.pointing.camera.estimate = Pointing.from_radecroll(camera_radecroll)

    estimate.estimate_time = imu.timestamp
    estimate.solve_source = SolveSource.IMU
    return True


def _get_constellation(ra_deg, dec_deg) -> str:
    if ra_deg is None or dec_deg is None:
        return ""
    return calc_utils.sf_utils.radec_to_constellation(ra_deg, dec_deg)


def _get_alt_az(ra_deg, dec_deg, location, dt) -> tuple[float | None, float | None]:
    if ra_deg is None or dec_deg is None or location is None or dt is None:
        return None, None
    calc_utils.sf_utils.set_location(location.lat, location.lon, location.altitude)
    return calc_utils.sf_utils.radec_to_altaz(ra_deg, dec_deg, dt)


def _drain_queue(q):
    """Discard all pending items from a queue."""
    try:
        while True:
            q.get(block=False)
    except queue.Empty:
        pass
