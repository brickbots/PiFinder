#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is the solver
* runs loop looking for new images
* tries to solve them
* If solved, emits solution into queue

"""
from PiFinder import utils

import sys
import logging

sys.path.append(str(utils.tetra3_dir))
import PiFinder.tetra3
import cedar_detect_client


# Select method used for star detection and centroiding. True for cedar-detect,
# False for Tetra3.
USE_CEDAR_DETECT = True

if USE_CEDAR_DETECT:
    cedar_detect = cedar_detect_client.CedarDetectClient(
        binary_path=str(utils.tetra3_dir / "bin/cedar-detect-server")
    )


def solver(shared_state, solver_queue, camera_image, console_queue):
    logging.getLogger("tetra3.Tetra3").addHandler(logging.NullHandler())
    t3 = PiFinder.tetra3.tetra3.Tetra3(
        str(utils.cwd_dir / "PiFinder/tetra3/tetra3/data/default_database.npz")
    )
    last_solve_time = 0
    solved = {
        "RA": None,
        "Dec": None,
        "imu_pos": None,
        "solve_time": None,
        "cam_solve_time": 0,
    }
    try:
        while True:
            if shared_state.power_state() <= 0:
                time.sleep(0.5)
            # use the time the exposure started here to
            # reject images startede before the last solve
            # which might be from the IMU
            last_image_metadata = shared_state.last_image_metadata()
            if (
                last_image_metadata["exposure_end"] > (last_solve_time)
                and last_image_metadata["imu_delta"] < 0.1
            ):
                solve_image = camera_image.copy()

                new_solve = t3.solve_from_image(
                    solve_image,
                    fov_estimate=10.2,
                    fov_max_error=0.5,
                    solve_timeout=500,
                    target_pixel=shared_state.solve_pixel(),
                )

                solved |= new_solve

                total_tetra_time = solved["T_extract"] + solved["T_solve"]
                if total_tetra_time > 1000:
                    console_queue.put(f"SLV: Long: {total_tetra_time}")

                if solved["RA"] != None:
                    # map the RA/DEC to the target pixel RA/DEC
                    solved["RA"] = solved["RA_target"]
                    solved["Dec"] = solved["Dec_target"]
                    if last_image_metadata["imu"]:
                        solved["imu_pos"] = last_image_metadata["imu"]["pos"]
                    else:
                        solved["imu_pos"] = None
                    solved["solve_time"] = time.time()
                    solved["cam_solve_time"] = solved["solve_time"]
                    solver_queue.put(solved)

                last_solve_time = last_image_metadata["exposure_end"]
    except EOFError:
        logging.error("Main no longer running for solver")
