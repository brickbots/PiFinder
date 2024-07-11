#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is the solver
* runs loop looking for new images
* tries to solve them
* If solved, emits solution into queue

"""

from PiFinder.multiproclogging import MultiprocLogging
import numpy as np
import time
import logging
import sys
from time import perf_counter as precision_timestamp

from PiFinder import state_utils
from PiFinder import utils

sys.path.append(str(utils.tetra3_dir))
import PiFinder.tetra3.tetra3 as tetra3
from PiFinder.tetra3.tetra3 import cedar_detect_client

logger = logging.getLogger("Solver")


def solver(
    shared_state, solver_queue, camera_image, console_queue, log_queue, is_debug=False
):
    MultiprocLogging.configurer(log_queue)
    logger.debug("Starting Solver")
    t3 = tetra3.Tetra3(
        str(utils.cwd_dir / "PiFinder/tetra3/tetra3/data/default_database.npz")
    )
    last_solve_time = 0
    solved = {
        # RA, Dec, Roll solved at the center of the camera FoV:
        "RA_camera": None,
        "Dec_camera": None,
        "Roll_camera": None,
        # RA, Dec, Roll at the target pixel
        "RA": None,
        "Dec": None,
        "Roll": None,
        "imu_pos": None,
        "solve_time": None,
        "cam_solve_time": 0,
    }

    # Start cedar detect server
    try:
        cedar_detect = cedar_detect_client.CedarDetectClient(
            binary_path=str(utils.cwd_dir / "../bin/cedar-detect-server-")
            + shared_state.arch()
        )
    except FileNotFoundError as e:
        logger.warn(
            "Not using cedar_detect, as corresponding file '%s' could not be found",
            e.filename,
        )
        cedar_detect = None

    try:
        while True:
            state_utils.sleep_for_framerate(shared_state)

            # use the time the exposure started here to
            # reject images started before the last solve
            # which might be from the IMU
            last_image_metadata = shared_state.last_image_metadata()
            if (
                last_image_metadata["exposure_end"] > (last_solve_time)
                and last_image_metadata["imu_delta"] < 1
            ):
                img = camera_image.copy()
                img = img.convert(mode="L")
                np_image = np.asarray(img, dtype=np.uint8)

                t0 = precision_timestamp()
                if cedar_detect is None or shared_state.camera_align():
                    # Use old tetr3 centroider to handle bloated/overexposed
                    # stars in alignment
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
                    logger.warn("No stars found, skipping")
                    continue
                else:
                    solution = t3.solve_from_centroids(
                        centroids,
                        (512, 512),
                        fov_estimate=12.0,
                        fov_max_error=4.0,
                        match_max_error=0.005,
                        return_matches=True,
                        target_pixel=shared_state.solve_pixel(),
                        solve_timeout=1000,
                    )

                    if "matched_centroids" in solution:
                        # Don't clutter printed solution with these fields.
                        # del solution['matched_centroids']
                        # del solution['matched_stars']
                        del solution["matched_catID"]
                        del solution["pattern_centroids"]
                        del solution["epoch_equinox"]
                        del solution["epoch_proper_motion"]
                        del solution["cache_hit_fraction"]

                solved |= solution

                total_tetra_time = t_extract + solved["T_solve"]
                if total_tetra_time > 1000:
                    console_queue.put(f"SLV: Long: {total_tetra_time}")
                    logger.warn("Long solver time: %i", total_tetra_time)

                if solved["RA"] is not None:
                    # RA, Dec, Roll at the center of the camera's FoV:
                    solved["RA_camera"] = solved["RA"]
                    solved["Dec_camera"] = solved["Dec"]
                    solved["Roll_camera"] = solved["Roll"]
                    # RA, Dec, Roll at the target pixel:
                    solved["RA"] = solved["RA_target"]  
                    solved["Dec"] = solved["Dec_target"]
                    solved["Roll"] = None  # To be calculated in integrator.py
                    if last_image_metadata["imu"]:
                        solved["imu_pos"] = last_image_metadata["imu"]["pos"]
                        solved["imu_quat"] = last_image_metadata["imu"]["quat"]
                    else:
                        solved["imu_pos"] = None
                        solved["imu_quat"] = None
                    solved["solve_time"] = time.time()
                    solved["cam_solve_time"] = solved["solve_time"]
                    solver_queue.put(solved)

                last_solve_time = last_image_metadata["exposure_end"]
    except EOFError:
        logger.error("Main no longer running for solver")
    except Exception as e:
        logger.error("Exception in Solver")
        logger.exception(e)
