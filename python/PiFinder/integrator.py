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
"""

from __future__ import annotations

import copy
import logging
import queue
import time
from typing import Optional, cast

import numpy as np
import quaternion  # numpy-quaternion

import PiFinder.calc_utils as calc_utils
from PiFinder import config
from PiFinder import state_utils
from PiFinder.multiproclogging import MultiprocLogging
from PiFinder.pointing_model.imu_dead_reckoning import ImuDeadReckoning
import PiFinder.pointing_model.quaternion_transforms as qt
from PiFinder.types.positioning import (
    FailedSolve,
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


def integrator(shared_state, solver_queue, console_queue, log_queue, is_debug=False):
    MultiprocLogging.configurer(log_queue)
    if is_debug:
        logger.setLevel(logging.DEBUG)
    logger.debug("Starting Integrator")

    try:
        cfg = config.Config()
        screen_direction = cfg.get_option("screen_direction")

        # Single IMU dead-reckoner handling both axes. Seeded with the
        # (camera, aligned) pair at each successful plate-solve.
        idr = ImuDeadReckoning(screen_direction)

        # Long-lived estimate. `solve` cells == anchor; `estimate` cells
        # are what consumers read. Empty until the first successful solve.
        estimate = PointingEstimate()
        last_solve_time = time.time()

        while True:
            state_utils.sleep_for_framerate(shared_state)

            pointing_updated = False

            # 1. Pull any pending solve result from the queue.
            solve_result: Optional[SolveResult] = None
            try:
                solve_result = solver_queue.get(block=False)
            except queue.Empty:
                pass

            if isinstance(solve_result, SuccessfulSolve):
                estimate = _apply_successful_solve(estimate, solve_result, idr)
                pointing_updated = True
            elif isinstance(solve_result, FailedSolve):
                estimate = _apply_failed_solve(estimate, solve_result)
                # set_solution derives solve_state from has_pointing(); the
                # failed solve cleared the estimate cells, so this publishes
                # the cleared pointing with solve_state=False.
                shared_state.set_solution(copy.deepcopy(estimate))

            # 2. If we have an anchor and didn't just do a fresh plate-solve,
            #    try to advance the estimate via IMU dead-reckoning.
            if (
                not pointing_updated
                and idr.is_initialized()
                and estimate.imu_anchor is not None
            ):
                imu = shared_state.imu()
                if imu:
                    if _advance_with_imu(estimate, idr, imu):
                        pointing_updated = True

            # 3. Publish if we updated something newer than what we last sent.
            if (
                pointing_updated
                and estimate.solve_time is not None
                and estimate.solve_time > last_solve_time
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
                last_solve_time = estimate.solve_time

    except EOFError:
        logger.error("Main no longer running for integrator")


def _apply_successful_solve(
    estimate: PointingEstimate,
    result: SuccessfulSolve,
    idr: ImuDeadReckoning,
) -> PointingEstimate:
    """Apply a :class:`SuccessfulSolve` onto the long-lived estimate.

    Fans the flat ``camera``/``aligned`` solve-truth into both the
    ``solve`` and ``estimate`` cells of each axis, refreshes the IMU
    anchor, and reseeds the dead-reckoner with the (camera, aligned)
    pair + anchor quaternion. The single ``solve_time`` on the message
    is assigned to both ``solve_time`` and ``cam_solve_time`` on the
    aggregate.
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
    estimate.solve_time = result.solve_time
    estimate.cam_solve_time = result.solve_time
    estimate.last_solve_attempt = result.last_solve_attempt
    estimate.last_solve_success = result.last_solve_success
    estimate.diagnostics = result.diagnostics
    estimate.alignment = result.alignment
    estimate.matched_centroids = result.matched_centroids
    estimate.matched_stars = result.matched_stars

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
    survive so dead-reckoning continues), refreshes diagnostics/timing,
    sets ``solve_source=CAMERA_FAILED``, and clears the ``estimate``
    cells so consumers stop reading a stale camera pointing.
    """
    estimate.diagnostics = result.diagnostics
    estimate.last_solve_attempt = result.last_solve_attempt
    estimate.last_solve_success = result.last_solve_success
    estimate.solve_source = SolveSource.CAMERA_FAILED
    estimate.constellation = ""  # may be overwritten below by IMU
    estimate.pointing.camera.estimate = None
    estimate.pointing.aligned.estimate = None
    return estimate


def _advance_with_imu(
    estimate: PointingEstimate,
    idr: ImuDeadReckoning,
    imu: dict,
) -> bool:
    """Advance ``estimate``'s ``estimate`` cells via IMU dead-reckoning.

    Returns ``True`` if cells were advanced, ``False`` if IMU motion
    was below the deadband.
    """
    q_x2imu = imu["quat"]
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

    # predict() returned non-None RaDecRoll, so .get() values are not None.
    ra_a, dec_a, roll_a = aligned_radecroll.get(deg=True)
    estimate.pointing.aligned.estimate = Pointing(
        RA=cast(float, ra_a),
        Dec=cast(float, dec_a),
        Roll=cast(float, roll_a),
    )

    ra_c, dec_c, roll_c = camera_radecroll.get(deg=True)
    estimate.pointing.camera.estimate = Pointing(
        RA=cast(float, ra_c),
        Dec=cast(float, dec_c),
        Roll=cast(float, roll_c),
    )

    estimate.solve_time = time.time()
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
