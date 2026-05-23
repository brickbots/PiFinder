#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Integrator process.

Owns the long-lived :class:`PointingEstimate`. Merges per-attempt solver
snapshots from ``solver_queue`` into the long-lived estimate, advances
the ``estimate`` cells via IMU dead-reckoning between solves, and
publishes the result to ``shared_state``.

Responsibility split:

* The **solver** holds no long-lived state. It builds a fresh
  :class:`PointingEstimate` per attempt and pushes to ``solver_queue``.
  On failure, the pushed estimate has empty pointing cells.

* The **integrator** holds the anchor. ``pointing.<axis>.solve`` cells
  on its long-lived estimate are the IMU dead-reckoning reference,
  updated only on a successful solve. On a failed solve the integrator
  preserves the previous ``solve`` cells so dead-reckoning continues.

Two :class:`ImuDeadReckoning` instances run in parallel, one per axis.
After the IDR simplification (commit 321579b3) the class treats its
input pointing as the truth direction directly; the alignment offset is
applied upstream by tetra3 via ``target_sky_coord`` / ``RA_target``.
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
    Pointing,
    PointingAxis,
    PointingEstimate,
    SolveSource,
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

        # One IMU dead-reckoner per axis. Both fed independently with
        # the matching `solve` cell at each successful plate-solve.
        idr_camera = ImuDeadReckoning(screen_direction)
        idr_aligned = ImuDeadReckoning(screen_direction)

        # Long-lived estimate. `solve` cells == anchor; `estimate` cells
        # are what consumers read. Empty until the first successful solve.
        estimate = PointingEstimate()
        last_solve_time = time.time()

        while True:
            state_utils.sleep_for_framerate(shared_state)

            pointing_updated = False

            # 1. Pull any pending solver snapshot from the queue.
            solver_snapshot: Optional[PointingEstimate] = None
            try:
                solver_snapshot = solver_queue.get(block=False)
            except queue.Empty:
                pass

            if solver_snapshot is not None:
                if solver_snapshot.solve_source == SolveSource.CAMERA:
                    estimate = _apply_successful_solve(
                        estimate, solver_snapshot, idr_camera, idr_aligned
                    )
                    shared_state.set_solve_state(True)
                    pointing_updated = True
                else:
                    # Failed solve: preserve solve cells + imu_anchor.
                    # Refresh diagnostics/timing/source; clear estimate cells.
                    estimate.diagnostics = solver_snapshot.diagnostics
                    estimate.last_solve_attempt = solver_snapshot.last_solve_attempt
                    estimate.last_solve_success = solver_snapshot.last_solve_success
                    estimate.solve_source = SolveSource.CAMERA_FAILED
                    estimate.constellation = ""  # may be overwritten below by IMU
                    estimate.pointing.camera.estimate = None
                    estimate.pointing.aligned.estimate = None
                    shared_state.set_solution(copy.deepcopy(estimate))
                    shared_state.set_solve_state(False)

            # 2. If we have an anchor and didn't just do a fresh plate-solve,
            #    try to advance the estimate via IMU dead-reckoning.
            if (
                not pointing_updated
                and idr_aligned.is_initialized()
                and estimate.imu_anchor is not None
            ):
                imu = shared_state.imu()
                if imu:
                    if _advance_with_imu(estimate, idr_camera, idr_aligned, imu):
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
                shared_state.set_solve_state(True)
                last_solve_time = estimate.solve_time

    except EOFError:
        logger.error("Main no longer running for integrator")


def _apply_successful_solve(
    estimate: PointingEstimate,
    snapshot: PointingEstimate,
    idr_camera: ImuDeadReckoning,
    idr_aligned: ImuDeadReckoning,
) -> PointingEstimate:
    """Merge a successful solver snapshot into the long-lived estimate.

    Replaces both ``solve`` and ``estimate`` cells on both axes and
    refreshes the IMU anchor. Reseeds both dead-reckoners with the
    matching ``solve`` cell + anchor quaternion.
    """
    snap = snapshot.pointing
    estimate.pointing.camera = PointingAxis(
        solve=snap.camera.solve,
        estimate=snap.camera.estimate,
    )
    estimate.pointing.aligned = PointingAxis(
        solve=snap.aligned.solve,
        estimate=snap.aligned.estimate,
    )

    estimate.imu_anchor = snapshot.imu_anchor
    estimate.solve_source = SolveSource.CAMERA
    estimate.solve_time = snapshot.solve_time
    estimate.cam_solve_time = snapshot.cam_solve_time
    estimate.last_solve_attempt = snapshot.last_solve_attempt
    estimate.last_solve_success = snapshot.last_solve_success
    estimate.diagnostics = snapshot.diagnostics
    estimate.alignment = snapshot.alignment
    estimate.matched_centroids = snapshot.matched_centroids
    estimate.matched_stars = snapshot.matched_stars

    # Reseed the dead-reckoners from the new anchor.
    q_anchor = snapshot.imu_anchor
    if q_anchor is None:
        q_anchor = quaternion.quaternion(np.nan)
    if snap.camera.solve is not None:
        idr_camera.solve(snap.camera.solve.as_radecroll(), q_anchor)
    if snap.aligned.solve is not None:
        idr_aligned.solve(snap.aligned.solve.as_radecroll(), q_anchor)

    return estimate


def _advance_with_imu(
    estimate: PointingEstimate,
    idr_camera: ImuDeadReckoning,
    idr_aligned: ImuDeadReckoning,
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

    aligned_radecroll = idr_aligned.predict(q_x2imu)
    camera_radecroll = idr_camera.predict(q_x2imu)
    if aligned_radecroll is None or camera_radecroll is None:
        return False

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
