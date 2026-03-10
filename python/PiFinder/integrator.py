#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Integrator: combines plate solves and IMU dead-reckoning into a single
pointing estimate, then pushes to shared_state.

Telemetry record/replay is handled by TelemetryManager; pointing math
lives in pointing.py.
"""

import queue
import time
import copy
import logging

from PiFinder import config
from PiFinder import state_utils
from PiFinder.multiproclogging import MultiprocLogging
from PiFinder.solver import get_initialized_solved_dict
from PiFinder.pointing_model.imu_dead_reckoning import ImuDeadReckoning
from PiFinder.pointing import (
    finalize_and_push_solution,
    update_imu,
    update_plate_solve_and_imu,
)
from PiFinder.telemetry import TelemetryManager


logger = logging.getLogger("IMU.Integrator")


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

    try:
        solved = get_initialized_solved_dict()
        cfg = config.Config()

        mount_type = cfg.get_option("mount_type")
        logger.debug(f"mount_type = {mount_type}")

        imu_dead_reckoning = ImuDeadReckoning(cfg.get_option("screen_direction"))

        last_image_solve = None
        last_solve_time = time.time()
        was_replaying = False

        telemetry = TelemetryManager(
            cfg, shared_state, console_queue, camera_command_queue
        )

        while True:
            telemetry.poll_commands(command_queue)

            # --- Replay mode ---
            if telemetry.replaying:
                was_replaying = True
                state_utils.sleep_for_framerate(shared_state)
                _drain_queue(solver_queue)
                event = telemetry.next_replay_event()
                if event is not None:
                    last_image_solve = telemetry.handle_replay_event(
                        event,
                        solved,
                        last_image_solve,
                        imu_dead_reckoning,
                        mount_type,
                    )
                continue

            # Reset integrator state when replay finishes
            if was_replaying:
                was_replaying = False
                last_image_solve = None
                solved = get_initialized_solved_dict()
                last_solve_time = time.time()
                logger.info("Replay ended, integrator state reset")

            # --- Normal mode ---
            state_utils.sleep_for_framerate(shared_state)

            # Check for new camera solve in queue
            next_image_solve = None
            try:
                next_image_solve = solver_queue.get(block=False)
            except queue.Empty:
                pass

            if isinstance(next_image_solve, dict):
                telemetry.record_solve(
                    next_image_solve,
                    predicted_ra=solved.get("RA"),
                    predicted_dec=solved.get("Dec"),
                )

                # For camera solves, always start from last successful camera solve
                # NOT from shared_state (which may contain IMU drift)
                if last_image_solve:
                    solved = copy.deepcopy(last_image_solve)

                # Update solve metadata (always needed for auto-exposure)
                for key in [
                    "Matches",
                    "RMSE",
                    "last_solve_attempt",
                    "last_solve_success",
                ]:
                    if key in next_image_solve:
                        solved[key] = next_image_solve[key]

                # Only update position data if solve succeeded (RA not None)
                if next_image_solve.get("RA") is not None:
                    solved.update(next_image_solve)

                if solved["RA"] is not None:
                    last_image_solve = copy.deepcopy(solved)
                    solved["solve_source"] = "CAM"
                    shared_state.set_solve_state(True)
                    update_plate_solve_and_imu(imu_dead_reckoning, solved)
                    finalize_and_push_solution(shared_state, solved, mount_type)
                else:
                    solved["solve_source"] = "CAM_FAILED"
                    solved["constellation"] = ""
                    shared_state.set_solution(solved)
                    shared_state.set_solve_state(False)

            elif imu_dead_reckoning.tracking:
                imu = shared_state.imu()
                if imu:
                    telemetry.record_imu(imu)
                    update_imu(imu_dead_reckoning, solved, last_image_solve, imu)

            # Push IMU updates only if newer than last push
            if solved["RA"] and solved["solve_time"] > last_solve_time:
                last_solve_time = time.time()
                finalize_and_push_solution(shared_state, solved, mount_type)

            telemetry.flush()

    except EOFError:
        logger.error("Main no longer running for integrator")
    finally:
        telemetry.stop()


def _drain_queue(q):
    """Discard all pending items from a queue."""
    try:
        while True:
            q.get(block=False)
    except queue.Empty:
        pass
