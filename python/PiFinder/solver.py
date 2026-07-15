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
import platform
import shutil
import socket
import subprocess
import threading
from multiprocessing import shared_memory
import grpc

from PiFinder import state_utils
from PiFinder import utils
from PiFinder import timez
from PiFinder.sqm import SQM as SQMCalculator
from PiFinder.state import SQM as SQMState
from PiFinder.types.positioning import (
    AlignCancel,
    AlignOnRaDec,
    AlignedResult,
    AlignmentResult,
    FailedSolve,
    Pointing,
    ReloadSqmCalibration,
    SolveDiagnostics,
    SuccessfulSolve,
)

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
            not in (
                "star_centroids",
                "star_mags",
                "star_fluxes",
                "star_local_backgrounds",
                "star_mzeros",
            )
        }
        shared_state.set_sqm_details(filtered_details)

        # Update shared state
        if sqm_value is not None:
            new_sqm_state = SQMState(
                value=sqm_value,
                source="Calculated",
                last_update=timez.local_now().isoformat(),
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


# Must match the hard-coded segment name in
# tetra3/cedar_detect_client.py:_alloc_shmem(). The segment is unlinked on a
# clean close(), but a solver process that is killed (or crashes) leaves it in
# /dev/shm, so the next run's create=True fails with FileExistsError.
_CEDAR_DETECT_SHMEM_NAME = "/cedar_detect_image"


class PFCedarDetectClient(cedar_detect_client.CedarDetectClient):
    def __init__(self, port=50551):
        """Connect to cedar-detect-server.

        On the PiFinder the server runs as a systemd service, so normally we
        just connect to it. In a development checkout no service is running;
        rather than require a manual start, if nothing is listening on the
        port we spawn the bundled ``bin/cedar-detect-server-<arch>`` ourselves
        and tear it down again in ``__del__``.

        Also changes this to a different default port.
        """
        self._port = port
        self._subprocess = None
        # Will initialize on first use.
        self._stub = None
        self._shmem = None
        self._shmem_size = 0
        # Try shared memory, fall back if an error occurs.
        self._use_shmem = True
        # A killed solver leaves its shmem segment behind; clear any stale one
        # so this run can re-create it instead of dying on FileExistsError.
        self._clear_stale_shmem()
        if self._server_reachable():
            # An external server (systemd service) is already running.
            time.sleep(2)
        else:
            self._spawn_server()

    def _server_reachable(self):
        """True if cedar-detect-server is already listening on our port."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.2)
            return sock.connect_ex(("127.0.0.1", self._port)) == 0

    def _spawn_server(self):
        """Spawn the bundled cedar-detect-server (development fallback)."""
        binary = self._find_server_binary()
        if binary is None:
            raise FileNotFoundError(
                f"cedar-detect-server is not listening on port {self._port} "
                "and no bundled binary was found in bin/; start it manually."
            )
        env = os.environ.copy()
        env["RUST_BACKTRACE"] = "1"
        logger.info("Spawning cedar-detect-server: %s", binary)
        self._subprocess = subprocess.Popen(
            [str(binary), "--port", str(self._port)], env=env
        )
        time.sleep(1)

    @staticmethod
    def _find_server_binary():
        """Locate the bin/cedar-detect-server binary matching this arch.

        Falls back to a ``cedar-detect-server`` found on ``PATH``.
        """
        machine = platform.machine().lower()
        if machine in ("aarch64", "arm64"):
            prefer = ("aarch64", "arm64")
        else:
            prefer = ("x86_64", "amd64", "x86")
        candidates = sorted((utils.pifinder_dir / "bin").glob("cedar-detect-server*"))
        for suffix in prefer:
            for candidate in candidates:
                if candidate.name.endswith(suffix) and os.access(candidate, os.X_OK):
                    return candidate
        for candidate in candidates:  # any executable cedar binary
            if os.access(candidate, os.X_OK):
                return candidate
        on_path = shutil.which("cedar-detect-server")
        return on_path if on_path else None

    def _clear_stale_shmem(self):
        """Unlink a leaked cedar_detect_image segment from a prior solver.

        Makes solver restarts self-healing. Safe because PiFinder runs a
        single solver process, so any existing segment is necessarily stale.
        """
        try:
            stale = shared_memory.SharedMemory(_CEDAR_DETECT_SHMEM_NAME)
        except FileNotFoundError:
            return
        stale.close()
        stale.unlink()
        logger.warning(
            "Cleared stale %s shared memory segment from a prior solver",
            _CEDAR_DETECT_SHMEM_NAME,
        )

    def _get_stub(self):
        if self._stub is None:
            channel = grpc.insecure_channel("127.0.0.1:%d" % self._port)
            self._stub = cedar_detect_client.cedar_detect_pb2_grpc.CedarDetectStub(
                channel
            )
        return self._stub

    def extract_centroids(
        self, image, sigma, max_size, use_binned, detect_hot_pixels=True
    ):
        """Override to raise CedarConnectionError on gRPC failure instead of returning empty list."""
        import numpy as np
        from tetra3 import cedar_detect_pb2

        np_image = np.asarray(image, dtype=np.uint8)
        (height, width) = np_image.shape
        centroids_result = None

        # Use shared memory path (same machine)
        if self._use_shmem:
            self._alloc_shmem(size=width * height)
            shimg = np.ndarray(
                np_image.shape, dtype=np_image.dtype, buffer=self._shmem.buf
            )
            shimg[:] = np_image[:]

            im = cedar_detect_pb2.Image(
                width=width, height=height, shmem_name=self._shmem.name
            )
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
                    raise CedarConnectionError(
                        f"Cedar gRPC failed: {err.details()}"
                    ) from err

        if not self._use_shmem:
            im = cedar_detect_pb2.Image(
                width=width, height=height, image_data=np_image.tobytes()
            )
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
                raise CedarConnectionError(
                    f"Cedar gRPC failed: {err.details()}"
                ) from err

        tetra_centroids = []
        if centroids_result is not None:
            for sc in centroids_result.star_candidates:
                tetra_centroids.append((sc.centroid_position.y, sc.centroid_position.x))
        return tetra_centroids

    def __del__(self):
        # __del__ can run on a partially-constructed instance (e.g. if __init__
        # raised), so attributes may be missing -- access defensively.
        subprocess_handle = getattr(self, "_subprocess", None)
        if subprocess_handle is not None:
            subprocess_handle.kill()
        self._del_shmem()


def _build_successful_solve(
    solution: dict,
    last_image_metadata: dict,
    last_solve_attempt: float,
    last_solve_success: float,
) -> SuccessfulSolve:
    """Fold a successful tetra3 ``solution`` dict into a
    :class:`SuccessfulSolve` message.

    Carries flat per-axis solve-truth (no ``solve``/``estimate`` split);
    the integrator fans ``camera``/``aligned`` into both cells of its
    long-lived :class:`PointingEstimate` and advances only the
    ``estimate`` cells via IMU dead-reckoning between solves.
    """
    camera_value = Pointing(
        RA=solution["RA"],
        Dec=solution["Dec"],
        Roll=solution["Roll"],
    )
    aligned_value = Pointing(
        RA=solution.get("RA_target", solution["RA"]),
        Dec=solution.get("Dec_target", solution["Dec"]),
        Roll=solution["Roll"],
    )

    imu_anchor = None
    if last_image_metadata.get("imu"):
        imu_anchor = last_image_metadata["imu"].quat

    return SuccessfulSolve(
        camera=camera_value,
        aligned=aligned_value,
        imu_anchor=imu_anchor,
        last_solve_attempt=last_solve_attempt,
        last_solve_success=last_solve_success,
        diagnostics=SolveDiagnostics(
            Matches=solution.get("Matches", 0),
            RMSE=solution.get("RMSE"),
            Prob=solution.get("Prob"),
            FOV=solution.get("FOV"),
            T_solve=solution.get("T_solve"),
            T_extract=solution.get("T_extract"),
        ),
        alignment=AlignmentResult(
            x_target=solution.get("x_target"),
            y_target=solution.get("y_target"),
        ),
        matched_centroids=solution.get("matched_centroids"),
        matched_stars=solution.get("matched_stars"),
    )


def _build_failed_solve(
    last_solve_attempt: float,
    last_solve_success,
    t_extract_ms: float,
) -> FailedSolve:
    """Build a :class:`FailedSolve` message for an attempt that produced
    no pointing. The integrator's long-lived estimate preserves the
    previous ``solve`` cells so IMU dead-reckoning continues."""
    return FailedSolve(
        last_solve_attempt=last_solve_attempt,
        last_solve_success=last_solve_success,
        diagnostics=SolveDiagnostics(
            Matches=0,
            T_extract=t_extract_ms,
        ),
    )


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
    max_imu_ang_during_exposure=1.0,  # Max allowed turn during exp [degrees]
):
    MultiprocLogging.configurer(log_queue)
    logger.debug("Starting Solver")
    t3 = tetra3.Tetra3(str(utils.tetra3_dir / "data" / "default_database.npz"))
    align_ra = 0
    align_dec = 0
    last_solve_attempt: float = 0.0
    last_solve_success = None  # exposure_end of most recent successful solve

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
                # Drain any pending command queue messages.
                while True:
                    try:
                        command = align_command_queue.get(block=False)
                    except queue.Empty:
                        break

                    if isinstance(command, AlignOnRaDec):
                        logger.debug("Align Command Received: %s", command)
                        align_ra = command.ra
                        align_dec = command.dec
                    elif isinstance(command, AlignCancel):
                        align_ra = 0
                        align_dec = 0
                    elif isinstance(command, ReloadSqmCalibration):
                        logger.info("Reloading SQM calibration...")
                        sqm_calculator = create_sqm_calculator(shared_state)
                        logger.info("SQM calibration reloaded")
                    else:
                        logger.warning(
                            "Unknown solver command (type=%s): %r",
                            type(command).__name__,
                            command,
                        )

                state_utils.sleep_for_framerate(shared_state)

                # use the time the exposure started here to
                # reject images started before the last solve
                # which might be from the IMU
                try:
                    last_image_metadata = shared_state.last_image_metadata()
                except (BrokenPipeError, ConnectionResetError) as e:
                    logger.error(f"Lost connection to shared state manager: {e}")
                    continue

                # Check if we should process this image
                is_new_image = last_image_metadata["exposure_end"] > last_solve_attempt

                if not is_new_image:
                    continue

                try:
                    img = camera_image.copy()
                    img = img.convert(mode="L")
                    np_image = np.asarray(img, dtype=np.uint8)

                    # Mark that we're attempting a solve - use image exposure_end timestamp.
                    # This is more accurate than wall clock and ties the attempt to the
                    # actual image so the integrator can dedupe.
                    last_solve_attempt = last_image_metadata["exposure_end"]

                    t0 = precision_timestamp()
                    if cedar_detect is not None:
                        # Try Cedar first
                        try:
                            centroids = cedar_detect.extract_centroids(
                                np_image, sigma=8, max_size=10, use_binned=True
                            )
                        except CedarConnectionError as e:
                            logger.warning(
                                f"Cedar connection failed: {e}, falling back to tetra3"
                            )
                            centroids = tetra3.get_centroids_from_image(np_image)
                    else:
                        # Cedar not available, use tetra3
                        centroids = tetra3.get_centroids_from_image(np_image)
                    t_extract = (precision_timestamp() - t0) * 1000

                    logger.debug(
                        "File %s, extracted %d centroids in %.2fms"
                        % ("camera", len(centroids), t_extract)
                    )

                    solution: dict = {}

                    if len(centroids) == 0:
                        if log_no_stars_found:
                            logger.info("No stars found, skipping (Logged only once)")
                            log_no_stars_found = False
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
                            target_pixel=shared_state.target_pixel(),
                            solve_timeout=1000,
                            **_solver_args,
                        )

                    if "matched_centroids" in solution:
                        # Update SQM (auto-exposure consumes the noise floor)
                        exposure_sec = (
                            last_image_metadata["exposure_time"] / 1_000_000.0
                        )
                        altitude_for_sqm = 90.0  # Topocentric Alt is computed in the integrator; SQM uses zenith fallback here

                        update_sqm(
                            shared_state=shared_state,
                            sqm_calculator=sqm_calculator,
                            centroids=centroids,
                            solution=solution,
                            image_processed=np_image,
                            exposure_sec=exposure_sec,
                            altitude_deg=altitude_for_sqm,
                            calculation_interval_seconds=SQM_CALCULATION_INTERVAL_SECONDS,
                        )

                        # Don't clutter printed solution with these fields (use pop to safely remove)
                        solution.pop("matched_catID", None)
                        solution.pop("pattern_centroids", None)
                        solution.pop("epoch_equinox", None)
                        solution.pop("epoch_proper_motion", None)
                        solution.pop("cache_hit_fraction", None)

                    if solution and solution.get("RA") is not None:
                        last_solve_success = last_solve_attempt
                        solve_result = _build_successful_solve(
                            solution=solution,
                            last_image_metadata=last_image_metadata,
                            last_solve_attempt=last_solve_attempt,
                            last_solve_success=last_solve_success,
                        )

                        total_tetra_time = t_extract + (solution.get("T_solve") or 0)
                        if total_tetra_time > 1000:
                            console_queue.put(f"SLV: Long: {total_tetra_time}")
                            logger.warning("Long solver time: %i", total_tetra_time)

                        logger.info(
                            f"Solve SUCCESS - {len(centroids)} centroids → "
                            f"{solve_result.diagnostics.Matches} matches, "
                            f"RMSE: {solve_result.diagnostics.RMSE:.1f}px"
                        )

                        # See if we are waiting for alignment
                        if align_ra != 0 and align_dec != 0:
                            if solve_result.alignment.is_set():
                                align_result_queue.put(
                                    AlignedResult(
                                        y_target=solve_result.alignment.y_target,
                                        x_target=solve_result.alignment.x_target,
                                    )
                                )
                                logger.debug(
                                    "Align target_pixel=(%s, %s)",
                                    solve_result.alignment.y_target,
                                    solve_result.alignment.x_target,
                                )
                            align_ra = 0
                            align_dec = 0
                            # Clear alignment fields from the message now that
                            # the result has been consumed.
                            solve_result.alignment = AlignmentResult()

                        solver_queue.put(solve_result)
                    else:
                        if solution:
                            logger.warning(
                                f"Solve FAILED - {len(centroids)} centroids detected but "
                                f"pattern match failed (FOV est: 12.0°, max err: 4.0°)"
                            )
                        solver_queue.put(
                            _build_failed_solve(
                                last_solve_attempt=last_solve_attempt,
                                last_solve_success=last_solve_success,
                                t_extract_ms=t_extract,
                            )
                        )
                except Exception as e:
                    logger.error(
                        f"Exception during solve attempt: {e.__class__.__name__}: {str(e)}"
                    )
                    logger.exception(e)
                    last_solve_attempt = last_image_metadata["exposure_end"]
                    solver_queue.put(
                        _build_failed_solve(
                            last_solve_attempt=last_solve_attempt,
                            last_solve_success=last_solve_success,
                            t_extract_ms=0.0,
                        )
                    )
        except EOFError as eof:
            logger.error(f"Main process no longer running for solver: {eof}")
            logger.exception(eof)
            logger.error(
                f"Last solve attempt: {last_solve_attempt}, last success: {last_solve_success}"
            )
        except Exception as e:
            logger.error(f"Exception in Solver: {e.__class__.__name__}: {str(e)}")
            logger.exception(e)
            logger.error(f"Current process ID: {os.getpid()}")
            logger.error(f"Current thread: {threading.current_thread().name}")
            try:
                logger.error(
                    f"Active threads: {[t.name for t in threading.enumerate()]}"
                )
            except Exception:
                pass  # Don't let diagnostic logging fail
