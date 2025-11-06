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

from PiFinder import state_utils
from PiFinder import utils

sys.path.append(str(utils.tetra3_dir))
import tetra3
from tetra3 import cedar_detect_client
import datetime
from PIL import Image

logger = logging.getLogger("Solver")


def solver(
    shared_state,
    solver_queue,
    camera_image,
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
    cedar_error = False

    while True:
        logger.info("Starting Solver Loop")
        if not cedar_error:
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
        else:
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
                        centroids, cedar_errors = cedar_detect.extract_centroids(
                            np_image,
                            sigma=8,
                            max_size=10,
                            use_binned=True,
                            return_errors=True,
                        )
                        if len(cedar_errors) > 0:
                            for err in cedar_errors:
                                logger.error(f"Cedar Detect errors: {err}")
                            # Save the image with cedar detect errors for debugging
                            debug_dir = os.path.expanduser("~/PiFinder_data/")
                            os.makedirs(debug_dir, exist_ok=True)
                            timestamp = datetime.datetime.now().strftime(
                                "%Y%m%d_%H%M%S"
                            )
                            debug_filename = f"cedar_errors_{timestamp}.png"
                            debug_path = os.path.join(debug_dir, debug_filename)
                            Image.fromarray(np_image).save(debug_path)
                            logger.debug(
                                f"Saved image with cedar detect errors to {debug_path}"
                            )
                            # If there were errors, fall back to old tetra3 centroider
                            centroids = tetra3.get_centroids_from_image(np_image)
                            cedar_error = True  # Avoid using cedar detect next time
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


if __name__ == "__main__":
    import argparse
    from pathlib import Path

    # Set up argument parser
    parser = argparse.ArgumentParser(
        description="Process PNG images through the centroider"
    )
    parser.add_argument("paths", nargs="+", help="Directories or PNG files to process")
    args = parser.parse_args()

    # Collect all PNG files from provided paths
    png_files = []
    for path_str in args.paths:
        path = Path(path_str)
        if path.is_file() and path.suffix.lower() == ".png":
            png_files.append(path)
        elif path.is_dir():
            png_files.extend(path.glob("**/*.png"))

    if not png_files:
        print("No PNG files found in the provided paths")
        sys.exit(1)

    print(f"Found {len(png_files)} PNG files to process")

    # Initialize cedar detect if available (mimicking solver() logic)
    cedar_detect = None
    cedar_error = False

    if not cedar_error:
        try:
            # Try to detect architecture for cedar binary
            import platform

            arch = platform.machine()
            cedar_detect = cedar_detect_client.CedarDetectClient(
                binary_path=str(utils.cwd_dir / f"../bin/cedar-detect-server-{arch}")
            )
            print(f"Using cedar-detect for centroiding (architecture: {arch})")
        except FileNotFoundError as e:
            print(
                f"cedar-detect not found ({e.filename}), falling back to tetra3 centroider"
            )
            cedar_detect = None
        except ValueError as e:
            print(
                f"cedar-detect initialization failed ({e}), falling back to tetra3 centroider"
            )
            cedar_detect = None

    # Process each PNG file
    try:
        for i, png_file in enumerate(png_files, 1):
            try:
                # Load image
                imgFile = Image.open(png_file)
                img = imgFile.convert(mode="L")
                np_image = np.asarray(img, dtype=np.uint8)

                # Extract centroids (mimicking solver() logic)
                t0 = precision_timestamp()
                if cedar_detect is None:
                    # Use old tetra3 centroider
                    centroids = tetra3.get_centroids_from_image(np_image)
                else:
                    centroids, cedar_errors = cedar_detect.extract_centroids(
                        np_image,
                        sigma=8,
                        max_size=10,
                        use_binned=True,
                        return_errors=True,
                    )
                    if len(cedar_errors) > 0:
                        print(f"  Cedar errors: {cedar_errors}")
                        print("  Falling back to tetra3 centroider for this image")
                        centroids = tetra3.get_centroids_from_image(np_image)
                        cedar_error = True

                t_extract = (precision_timestamp() - t0) * 1000

                # Print results immediately
                print(
                    f"[{i}/{len(png_files)}] {png_file.name}: {len(centroids)} centroids in {t_extract:.2f}ms"
                )

            except Exception as e:
                print(f"[{i}/{len(png_files)}] {png_file.name}: ERROR - {e}")

        print(f"\nProcessed {len(png_files)} files")

    finally:
        # Gracefully shutdown cedar_detect if it was initialized
        if cedar_detect is not None:
            print("Shutting down cedar-detect server...")
            cedar_detect._subprocess.kill()
            cedar_detect._del_shmem()
            if hasattr(cedar_detect, "_log_file") and cedar_detect._log_file:
                cedar_detect._log_file.close()
