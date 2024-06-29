#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is the solver
* runs loop looking for new images
* tries to solve them
* If solved, emits solution into queue

"""

import numpy as np
import time
import logging
import sys
from time import perf_counter as precision_timestamp


from PiFinder import utils

sys.path.append(str(utils.tetra3_dir))
import PiFinder.tetra3.tetra3 as tetra3
from PiFinder.tetra3.tetra3 import cedar_detect_client


def solver(shared_state, solver_queue, camera_image, console_queue, is_debug=False):
    logging.getLogger("tetra3.Tetra3").addHandler(logging.NullHandler())
    logging.debug("Starting Solver")
    t3 = tetra3.Tetra3(
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

    # Start cedar detext server
    cedar_detect = cedar_detect_client.CedarDetectClient(
        binary_path=str(utils.cwd_dir / "../bin/cedar-detect-server-")
        + shared_state.arch()
    )

    try:
        while True:
            utils.sleep_for_framerate(shared_state)

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
                if shared_state.camera_align():
                    # Use old tetr3 centroider to handle bloated/overexposed
                    # stars in alignment
                    centroids = tetra3.get_centroids_from_image(np_image)
                else:
                    centroids = cedar_detect.extract_centroids(
                        np_image, sigma=8, max_size=10, use_binned=True
                    )
                t_extract = (precision_timestamp() - t0) * 1000
                logging.debug(
                    "File %s, extracted %d centroids in %.2fms"
                    % ("camera", len(centroids), t_extract)
                )

                if len(centroids) == 0:
                    # logging.debug("No stars found, skipping")
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

                if solved["RA"] is not None:
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
    except Exception as e:
        logging.error("Solver exception %s", e)
