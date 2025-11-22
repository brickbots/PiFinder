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
from PIL import Image

from PiFinder import state_utils
from PiFinder import utils
from PiFinder.sqm import SQM as SQMCalculator
from PiFinder.state import SQM as SQMState

sys.path.append(str(utils.tetra3_dir))
import tetra3
from tetra3 import cedar_detect_client

logger = logging.getLogger("Solver")

# SQM calculation interval - calculate SQM every N seconds
SQM_CALCULATION_INTERVAL_SECONDS = 5.0


def create_sqm_calculator(shared_state):
    """Create a new SQM calculator instance for PROCESSED images with current calibration."""
    # Get camera type from shared state and use "_processed" profile
    # since images are already processed 8-bit (not raw)
    camera_type = shared_state.camera_type()
    camera_type_processed = f"{camera_type}_processed"

    logger.info(
        f"Creating processed SQM calculator for camera: {camera_type_processed}"
    )

    return SQMCalculator(
        camera_type=camera_type_processed,
        use_adaptive_noise_floor=True,
    )


def create_sqm_calculator_raw(shared_state):
    """Create a new SQM calculator instance for RAW 16-bit images with current calibration."""
    # Get camera type from shared state (raw profile, e.g., "imx296", "hq")
    camera_type_raw = shared_state.camera_type()

    logger.info(f"Creating raw SQM calculator for camera: {camera_type_raw}")

    return SQMCalculator(
        camera_type=camera_type_raw,
        use_adaptive_noise_floor=True,
    )


def update_sqm_dual_pipeline(
    shared_state,
    sqm_calculator,
    sqm_calculator_raw,
    camera_command_queue,
    centroids,
    solution,
    image_processed,
    exposure_sec,
    altitude_deg,
    calculation_interval_seconds=5.0,
    aperture_radius=5,
    annulus_inner_radius=6,
    annulus_outer_radius=14,
):
    """
    Calculate SQM for BOTH processed (8-bit) and raw (16-bit) images.

    This function:
    1. Checks if enough time has passed since last update
    2. Calculates SQM from processed 8-bit image
    3. Captures a raw 16-bit frame, loads it, and calculates raw SQM
    4. Updates shared state with both values

    Args:
        shared_state: SharedStateObj instance
        sqm_calculator: SQM calculator for processed images
        sqm_calculator_raw: SQM calculator for raw images
        camera_command_queue: Queue to send raw capture command
        centroids: List of detected star centroids
        solution: Tetra3 solve solution with matched stars
        image_processed: Processed 8-bit image array
        exposure_sec: Exposure time in seconds
        altitude_deg: Altitude in degrees for extinction correction
        calculation_interval_seconds: Minimum time between calculations (default: 5.0)
        aperture_radius: Aperture radius for photometry (default: 5)
        annulus_inner_radius: Inner annulus radius (default: 6)
        annulus_outer_radius: Outer annulus radius (default: 14)

    Returns:
        bool: True if SQM was calculated and updated, False otherwise
    """
    from datetime import datetime

    # Get current SQM state from shared state
    current_sqm = shared_state.sqm()
    current_time = time.time()

    # Check if we should calculate SQM
    should_calculate = current_sqm.last_update is None

    if current_sqm.last_update is not None:
        try:
            last_update_time = datetime.fromisoformat(
                current_sqm.last_update
            ).timestamp()
            should_calculate = (
                current_time - last_update_time
            ) >= calculation_interval_seconds
        except (ValueError, AttributeError):
            logger.warning("Failed to parse SQM timestamp, recalculating")
            should_calculate = True

    if not should_calculate:
        return False

    try:
        # ========== Calculate PROCESSED (8-bit) SQM ==========
        sqm_value_processed, _ = sqm_calculator.calculate(
            centroids=centroids,
            solution=solution,
            image=image_processed,
            exposure_sec=exposure_sec,
            altitude_deg=altitude_deg,
            aperture_radius=aperture_radius,
            annulus_inner_radius=annulus_inner_radius,
            annulus_outer_radius=annulus_outer_radius,
        )

        # ========== Calculate RAW (16-bit) SQM from shared state ==========
        sqm_value_raw = None

        try:
            # Get raw frame from shared state (already captured by camera)
            raw_array = shared_state.cam_raw()

            if raw_array is not None:
                raw_array = np.asarray(raw_array, dtype=np.float32)

                # Calculate raw SQM
                sqm_value_raw, _ = sqm_calculator_raw.calculate(
                    centroids=centroids,
                    solution=solution,
                    image=raw_array,
                    exposure_sec=exposure_sec,
                    altitude_deg=altitude_deg,
                    aperture_radius=aperture_radius,
                    annulus_inner_radius=annulus_inner_radius,
                    annulus_outer_radius=annulus_outer_radius,
                )

        except Exception as e:
            logger.warning(f"Failed to calculate raw SQM: {e}")
            # Continue with just processed SQM

        # ========== Update shared state with BOTH values ==========
        if sqm_value_processed is not None:
            new_sqm_state = SQMState(
                value=sqm_value_processed,
                value_raw=sqm_value_raw,  # May be None if raw failed
                source="Calculated",
                last_update=datetime.now().isoformat(),
            )
            shared_state.set_sqm(new_sqm_state)

            raw_str = (
                f", raw={sqm_value_raw:.2f}"
                if sqm_value_raw is not None
                else ", raw=N/A"
            )
            logger.info(f"SQM updated: processed={sqm_value_processed:.2f}{raw_str}")
            return True

    except Exception as e:
        logger.error(f"Error calculating SQM: {e}")
        return False

    return False


def solver(
    shared_state,
    solver_queue,
    camera_image,
    console_queue,
    log_queue,
    align_command_queue,
    align_result_queue,
    camera_command_queue,
    is_debug=False,
):
    MultiprocLogging.configurer(log_queue)
    logger.debug("Starting Solver")
    t3 = tetra3.Tetra3(
        str(utils.cwd_dir / "PiFinder/tetra3/tetra3/data/default_database.npz")
    )
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
        "last_solve_attempt": 0,  # Timestamp of last solve attempt - tracks exposure_end of last processed image
        "last_solve_success": None,  # Timestamp of last successful solve
    }

    centroids = []
    log_no_stars_found = True

    # Create SQM calculators (processed and raw) - can be reloaded via command queue
    sqm_calculator = create_sqm_calculator(shared_state)
    sqm_calculator_raw = create_sqm_calculator_raw(shared_state)

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

                        if command[0] == "reload_sqm_calibration":
                            logger.info(
                                "Reloading SQM calibration (both processed and raw)..."
                            )
                            sqm_calculator = create_sqm_calculator(shared_state)
                            sqm_calculator_raw = create_sqm_calculator_raw(shared_state)
                            logger.info("SQM calibration reloaded for both pipelines")

                state_utils.sleep_for_framerate(shared_state)

                # use the time the exposure started here to
                # reject images started before the last solve
                # which might be from the IMU
                try:
                    last_image_metadata = shared_state.last_image_metadata()
                except (BrokenPipeError, ConnectionResetError) as e:
                    logger.error(f"Lost connection to shared state manager: {e}")

                # Check if we should process this image
                is_new_image = (
                    last_image_metadata["exposure_end"] > solved["last_solve_attempt"]
                )
                is_stationary = last_image_metadata["imu_delta"] < 1

                if is_new_image and not is_stationary:
                    logger.debug(
                        f"Skipping image - IMU delta {last_image_metadata['imu_delta']:.2f}° >= 1° (moving)"
                    )

                if is_new_image and is_stationary:
                    try:
                        img = camera_image.copy()
                        img = img.convert(mode="L")
                        np_image = np.asarray(img, dtype=np.uint8)

                        # Mark that we're attempting a solve - use image exposure_end timestamp
                        # This is more accurate than wall clock and ties the attempt to the actual image
                        solved["last_solve_attempt"] = last_image_metadata["exposure_end"]

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

                        # Initialize solution to prevent UnboundLocalError
                        solution = {}

                        if len(centroids) == 0:
                            if log_no_stars_found:
                                logger.info("No stars found, skipping (Logged only once)")
                                log_no_stars_found = False
                            # Clear solve results to mark solve as failed (otherwise old values persist)
                            solved["RA"] = None
                            solved["Dec"] = None
                            solved["Matches"] = 0
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
                            return_matches=True,  # Required for SQM calculation
                            target_pixel=shared_state.solve_pixel(),
                            solve_timeout=1000,
                            **_solver_args,
                        )

                        if "matched_centroids" in solution:
                            # Update SQM for BOTH processed and raw pipelines
                            # Convert exposure time from microseconds to seconds
                            exposure_sec = (
                                last_image_metadata["exposure_time"] / 1_000_000.0
                            )

                            update_sqm_dual_pipeline(
                                shared_state=shared_state,
                                sqm_calculator=sqm_calculator,
                                sqm_calculator_raw=sqm_calculator_raw,
                                camera_command_queue=camera_command_queue,
                                centroids=centroids,
                                solution=solution,
                                image_processed=np_image,
                                exposure_sec=exposure_sec,
                                altitude_deg=solved.get("Alt") or 90.0,
                                calculation_interval_seconds=SQM_CALCULATION_INTERVAL_SECONDS,
                            )

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
                            # Mark successful solve - use same timestamp as last_solve_attempt for comparison
                            solved["last_solve_success"] = solved["last_solve_attempt"]

                            logger.info(
                                f"Solve SUCCESS - {len(centroids)} centroids → "
                                f"{solved.get('Matches', 0)} matches, "
                                f"RMSE: {solved.get('RMSE', 0):.1f}px"
                            )

                            # See if we are waiting for alignment
                            if align_ra != 0 and align_dec != 0:
                                if solved.get("x_target") is not None:
                                    align_target_pixel = (
                                        solved["y_target"],
                                        solved["x_target"],
                                    )
                                    logger.debug(f"Align {align_target_pixel=}")
                                    align_result_queue.put(
                                        ["aligned", align_target_pixel]
                                    )
                                    align_ra = 0
                                    align_dec = 0
                                    solved["x_target"] = None
                                    solved["y_target"] = None
                        else:
                            # Centroids found but solve failed - clear Matches
                            solved["Matches"] = 0
                            logger.warning(
                                f"Solve FAILED - {len(centroids)} centroids detected but "
                                f"pattern match failed (FOV est: 12.0°, max err: 4.0°)"
                            )

                        # Always push to queue after every solve attempt (success or failure)
                        solver_queue.put(solved)
                    except Exception as e:
                        # If solve attempt fails, still send update with Matches=0
                        # so auto-exposure can continue running
                        logger.error(
                            f"Exception during solve attempt: {e.__class__.__name__}: {str(e)}"
                        )
                        logger.exception(e)
                        solved["last_solve_attempt"] = last_image_metadata["exposure_end"]
                        solved["Matches"] = 0
                        solved["RA"] = None
                        solved["Dec"] = None
                        solver_queue.put(solved)
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
