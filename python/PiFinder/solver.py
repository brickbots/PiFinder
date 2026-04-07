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
import grpc

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
    """Create a new SQM calculator instance with current calibration."""
    camera_type = shared_state.camera_type()
    camera_type_processed = f"{camera_type}_processed"

    logger.info(f"Creating SQM calculator for camera: {camera_type_processed}")

    return SQMCalculator(camera_type=camera_type_processed)


def update_sqm(
    shared_state,
    sqm_calculator,
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
    Calculate SQM from image.

    Args:
        shared_state: SharedStateObj instance
        sqm_calculator: SQM calculator instance
        centroids: List of detected star centroids
        solution: Tetra3 solve solution with matched stars
        image_processed: Processed image array (numpy)
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
        # Calculate SQM from image
        sqm_value, details = sqm_calculator.calculate(
            centroids=centroids,
            solution=solution,
            image=image_processed,
            exposure_sec=exposure_sec,
            altitude_deg=altitude_deg,
            aperture_radius=aperture_radius,
            annulus_inner_radius=annulus_inner_radius,
            annulus_outer_radius=annulus_outer_radius,
        )

        # Update noise floor in shared state (for SNR auto-exposure)
        noise_floor_details = details.get("noise_floor_details")
        if noise_floor_details and "noise_floor_adu" in noise_floor_details:
            shared_state.set_noise_floor(noise_floor_details["noise_floor_adu"])

        # Store SQM details (filter out large per-star arrays)
        filtered_details = {
            k: v
            for k, v in details.items()
            if k
            not in ("star_centroids", "star_mags", "star_fluxes", "star_local_backgrounds", "star_mzeros")
        }
        shared_state.set_sqm_details(filtered_details)

        # Update shared state
        if sqm_value is not None:
            new_sqm_state = SQMState(
                value=sqm_value,
                source="Calculated",
                last_update=datetime.now().isoformat(),
            )
            shared_state.set_sqm(new_sqm_state)
            logger.info(f"SQM updated: {sqm_value:.2f} mag/arcsec²")
            return True

    except Exception as e:
        logger.error(f"Error calculating SQM: {e}")
        return False

    return False


class CedarConnectionError(Exception):
    """Raised when Cedar gRPC connection fails."""

    pass


class PFCedarDetectClient(cedar_detect_client.CedarDetectClient):
    def __init__(self, port=50551):
        """Set up the client without spawning the server as we
        run this as a service on the PiFinder

        Also changing this to a different default port
        """
        self._port = port
        time.sleep(2)
        # Will initialize on first use.
        self._stub = None
        self._shmem = None
        self._shmem_size = 0
        # Try shared memory, fall back if an error occurs.
        self._use_shmem = True

    def _get_stub(self):
        if self._stub is None:
            channel = grpc.insecure_channel("127.0.0.1:%d" % self._port)
            self._stub = cedar_detect_client.cedar_detect_pb2_grpc.CedarDetectStub(
                channel
            )
        return self._stub

    def extract_centroids(self, image, sigma, max_size, use_binned, detect_hot_pixels=True):
        """Override to raise CedarConnectionError on gRPC failure instead of returning empty list."""
        import numpy as np
        from tetra3 import cedar_detect_pb2

        np_image = np.asarray(image, dtype=np.uint8)
        (height, width) = np_image.shape
        centroids_result = None

        # Use shared memory path (same machine)
        if self._use_shmem:
            self._alloc_shmem(size=width * height)
            shimg = np.ndarray(np_image.shape, dtype=np_image.dtype, buffer=self._shmem.buf)
            shimg[:] = np_image[:]

            im = cedar_detect_pb2.Image(width=width, height=height, shmem_name=self._shmem.name)
            req = cedar_detect_pb2.CentroidsRequest(
                input_image=im,
                sigma=sigma,
                max_size=max_size,
                return_binned=False,
                use_binned_for_star_candidates=use_binned,
                detect_hot_pixels=detect_hot_pixels,
            )
            try:
                centroids_result = self._get_stub().ExtractCentroids(req)
            except grpc.RpcError as err:
                if err.code() == grpc.StatusCode.INTERNAL:
                    # Shared memory issue, fall back to non-shmem
                    self._del_shmem()
                    self._use_shmem = False
                else:
                    raise CedarConnectionError(f"Cedar gRPC failed: {err.details()}") from err

        if not self._use_shmem:
            im = cedar_detect_pb2.Image(width=width, height=height, image_data=np_image.tobytes())
            req = cedar_detect_pb2.CentroidsRequest(
                input_image=im,
                sigma=sigma,
                max_size=max_size,
                return_binned=False,
                use_binned_for_star_candidates=use_binned,
            )
            try:
                centroids_result = self._get_stub().ExtractCentroids(req)
            except grpc.RpcError as err:
                raise CedarConnectionError(f"Cedar gRPC failed: {err.details()}") from err

        tetra_centroids = []
        if centroids_result is not None:
            for sc in centroids_result.star_candidates:
                tetra_centroids.append((sc.centroid_position.y, sc.centroid_position.x))
        return tetra_centroids

    def __del__(self):
        self._del_shmem()


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
    solution = {}
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

    # Create SQM calculator - can be reloaded via command queue
    sqm_calculator = create_sqm_calculator(shared_state)

    while True:
        logger.info("Starting Solver Loop")
        # Try to start cedar detect server, fall back to tetra3 centroider if unavailable
        cedar_detect = None
        try:
            cedar_detect = PFCedarDetectClient()
        except FileNotFoundError as e:
            logger.warning(
                "Not using cedar_detect, as corresponding file '%s' could not be found",
                e.filename,
            )
        except ValueError:
            logger.exception("Not using cedar_detect")

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
                            logger.info("Reloading SQM calibration...")
                            sqm_calculator = create_sqm_calculator(shared_state)
                            logger.info("SQM calibration reloaded")

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
                        solved["last_solve_attempt"] = last_image_metadata[
                            "exposure_end"
                        ]

                        t0 = precision_timestamp()
                        if cedar_detect is not None:
                            # Try Cedar first
                            try:
                                centroids = cedar_detect.extract_centroids(
                                    np_image, sigma=8, max_size=10, use_binned=True
                                )
                            except CedarConnectionError as e:
                                logger.warning(f"Cedar connection failed: {e}, falling back to tetra3")
                                centroids = tetra3.get_centroids_from_image(np_image)
                        else:
                            # Cedar not available, use tetra3
                            centroids = tetra3.get_centroids_from_image(np_image)
                        t_extract = (precision_timestamp() - t0) * 1000

                        logger.debug(
                            "File %s, extracted %d centroids in %.2fms"
                            % ("camera", len(centroids), t_extract)
                        )

                        if len(centroids) == 0:
                            if log_no_stars_found:
                                logger.info(
                                    "No stars found, skipping (Logged only once)"
                                )
                                log_no_stars_found = False
                            # Clear solve results to mark solve as failed (otherwise old values persist)
                            solved["RA"] = None
                            solved["Dec"] = None
                            solved["Matches"] = 0
                        else:
                            log_no_stars_found = True
                            _solver_args = {}
                            if align_ra != 0 and align_dec != 0:
                                _solver_args["target_sky_coord"] = [
                                    [align_ra, align_dec]
                                ]

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

                            update_sqm(
                                shared_state=shared_state,
                                sqm_calculator=sqm_calculator,
                                centroids=centroids,
                                solution=solution,
                                image_processed=np_image,
                                exposure_sec=exposure_sec,
                                altitude_deg=solved.get("Alt") or 90.0,
                                calculation_interval_seconds=SQM_CALCULATION_INTERVAL_SECONDS,
                            )

                            # Don't clutter printed solution with these fields (use pop to safely remove)
                            solution.pop("matched_catID", None)
                            solution.pop("pattern_centroids", None)
                            solution.pop("epoch_equinox", None)
                            solution.pop("epoch_proper_motion", None)
                            solution.pop("cache_hit_fraction", None)

                        solved |= solution

                        if "T_solve" in solved:
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
                        solved["last_solve_attempt"] = last_image_metadata[
                            "exposure_end"
                        ]
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
