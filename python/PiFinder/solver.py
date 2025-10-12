#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is the solver
* runs loop looking for new images
* tries to solve them
* If solved, emits solution into queue

"""

from PiFinder.multiproclogging import MultiprocLogging
import queue
import numpy as np
import time
import logging
import sys
from time import perf_counter as precision_timestamp
import os
import threading

from PiFinder.utils import Timer
from PiFinder import state_utils
from PiFinder import utils
from PiFinder.sqm import SQM

sys.path.append(str(utils.tetra3_dir))
import tetra3
from tetra3 import cedar_detect_client

logger = logging.getLogger("Solver")
sqm = SQM()

def solver(
    shared_state,
    solver_queue,
    camera_image,
    bias_image,
    console_queue,
    log_queue,
    align_command_queue,
    align_result_queue,
    is_debug=False,
):
    MultiprocLogging.configurer(log_queue)
    logger.debug("Starting Solver")
    t3 = tetra3.Tetra3(
        str(utils.cwd_dir / "PiFinder/tetra3/tetra3/data/default_database.npz")
    )
    last_solve_time = 0
    align_ra = 0
    align_dec = 0
    solved = {
        # RA, Dec, Roll solved at the center of the camera FoV
        # update by integrator
        "camera_center": {
            "RA": None,
            "Dec": None,
            "Roll": None,
            "Alt": None,
            "Az": None,
        },
        # RA, Dec, Roll from the camera, not
        # affected by IMU in integrator
        "camera_solve": {
            "RA": None,
            "Dec": None,
            "Roll": None,
        },
        # RA, Dec, Roll at the target pixel
        "RA": None,
        "Dec": None,
        "Roll": None,
        "imu_pos": None,
        "solve_time": None,
        "cam_solve_time": 0,
    }

    centroids = []
    log_no_stars_found = True

    while True:
        logger.info("Starting Solver Loop")
        # Start cedar detect server
        try:
            cedar_detect = cedar_detect_client.CedarDetectClient(
                binary_path=str(utils.cwd_dir / "../bin/cedar-detect-server-")
                + shared_state.arch()
            )
        except FileNotFoundError as e:
            logger.warning(
                "Not using cedar_detect, as corresponding file '%s' could not be found",
                e.filename,
            )
            cedar_detect = None
        except ValueError:
            logger.exception("Not using cedar_detect")
            cedar_detect = None

        try:
            while True:
                # Loop over any pending commands
                # There may be more than one!
                command = True
                while command:
                    try:
                        command = align_command_queue.get(block=False)
                        print(f"the command is {command}")
                    except queue.Empty:
                        command = False

                    if command is not False:
                        if command[0] == "align_on_radec":
                            logger.debug("Align Command Received")
                            # search image pixels to find the best match
                            # for this RA/DEC and set it as alignment pixel
                            align_ra = command[1]
                            align_dec = command[2]

                        if command[0] == "align_cancel":
                            align_ra = 0
                            align_dec = 0

                state_utils.sleep_for_framerate(shared_state)

                # use the time the exposure started here to
                # reject images started before the last solve
                # which might be from the IMU
                try:
                    last_image_metadata = shared_state.last_image_metadata()
                except (BrokenPipeError, ConnectionResetError) as e:
                    logger.error(f"Lost connection to shared state manager: {e}")
                if (
                    last_image_metadata["exposure_end"] > (last_solve_time)
                    and last_image_metadata["imu_delta"] < 1
                ):
                    img = camera_image.copy()
                    img = img.convert(mode="L")
                    np_image = np.asarray(img, dtype=np.uint8)

                    t0 = precision_timestamp()
                    if cedar_detect is None:
                        # Use old tetr3 centroider
                        centroids = tetra3.get_centroids_from_image(np_image)
                    else:
                        centroids = cedar_detect.extract_centroids(
                            np_image, sigma=8, max_size=10, use_binned=True
                        )
                    t_extract = (precision_timestamp() - t0) * 1000

                    logger.debug(
                        "File %s, extracted %d centroids in %.2fms"
                        % ("camera", len(centroids), t_extract)
                    )

                    if len(centroids) == 0:
                        if log_no_stars_found:
                            logger.info("No stars found, skipping (Logged only once)")
                            log_no_stars_found = False
                        continue
                    else:
                        log_no_stars_found = True
                        _solver_args = {}
                        if align_ra != 0 and align_dec != 0:
                            _solver_args["target_sky_coord"] = [[align_ra, align_dec]]

                        solution = t3.solve_from_centroids(
                            centroids,
                            (512, 512),
                            fov_estimate=12.0,
                            fov_max_error=4.0,
                            match_max_error=0.005,
                            # return_matches=True,
                            target_pixel=shared_state.solve_pixel(),
                            solve_timeout=1000,
                            **_solver_args,
                        )

                        if "matched_centroids" in solution:
                            # Calculate SQM
                            measured_sqm = sqm.calculate(bias_image, centroids, solution, np_image, radius=2)
                            solved["SQM"] = measured_sqm

                            # Don't clutter printed solution with these fields.
                            del solution["matched_catID"]
                            del solution["pattern_centroids"]
                            del solution["epoch_equinox"]
                            del solution["epoch_proper_motion"]
                            del solution["cache_hit_fraction"]

                    solved |= solution

                    total_tetra_time = t_extract + solved["T_solve"]
                    if total_tetra_time > 1000:
                        console_queue.put(f"SLV: Long: {total_tetra_time}")
                        logger.warning("Long solver time: %i", total_tetra_time)

                    if solved["RA"] is not None:
                        # RA, Dec, Roll at the center of the camera's FoV:
                        solved["camera_center"]["RA"] = solved["RA"]
                        solved["camera_center"]["Dec"] = solved["Dec"]
                        solved["camera_center"]["Roll"] = solved["Roll"]

                        # RA, Dec, Roll at the center of the camera's not imu:
                        solved["camera_solve"]["RA"] = solved["RA"]
                        solved["camera_solve"]["Dec"] = solved["Dec"]
                        solved["camera_solve"]["Roll"] = solved["Roll"]
                        # RA, Dec, Roll at the target pixel:
                        solved["RA"] = solved["RA_target"]
                        solved["Dec"] = solved["Dec_target"]
                        if last_image_metadata["imu"]:
                            solved["imu_pos"] = last_image_metadata["imu"]["pos"]
                            solved["imu_quat"] = last_image_metadata["imu"]["quat"]
                        else:
                            solved["imu_pos"] = None
                            solved["imu_quat"] = None
                        solved["solve_time"] = time.time()
                        solved["cam_solve_time"] = solved["solve_time"]
                        solver_queue.put(solved)

                        # See if we are waiting for alignment
                        if align_ra != 0 and align_dec != 0:
                            if solved.get("x_target") is not None:
                                align_target_pixel = (
                                    solved["y_target"],
                                    solved["x_target"],
                                )
                                logger.debug(f"Align {align_target_pixel=}")
                                align_result_queue.put(["aligned", align_target_pixel])
                                align_ra = 0
                                align_dec = 0
                                solved["x_target"] = None
                                solved["y_target"] = None

                    last_solve_time = last_image_metadata["exposure_end"]
        except EOFError as eof:
            logger.error(f"Main process no longer running for solver: {eof}")
            logger.exception(eof)  # This logs the full stack trace
            # Optionally log additional context
            logger.error(f"Current solver state: {solved}")  # If you have state info
        except Exception as e:
            logger.error(f"Exception in Solver: {e.__class__.__name__}: {str(e)}")
            logger.exception(e)  # Logs the full stack trace
            # Log additional context that might be helpful
            logger.error(f"Current process ID: {os.getpid()}")
            logger.error(f"Current thread: {threading.current_thread().name}")
            try:
                logger.error(
                    f"Active threads: {[t.name for t in threading.enumerate()]}"
                )
            except Exception as e:
                pass  # Don't let diagnostic logging fail
