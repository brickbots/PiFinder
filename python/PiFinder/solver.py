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

from PiFinder.sqm.wings import WingEstimator
from PiFinder.sqm.clouds import CloudEstimator
from PiFinder.sqm.black_level import BlackLevelTracker
from PiFinder.sqm.radiometer import (
    RadiometerAccumulator,
    extract_photometry_image,
)
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

import tetra3
from tetra3 import cedar_detect_client

logger = logging.getLogger("Solver")

# The primary radiometer publishes only after a new frame, capped at 1 Hz.
SQM_CALCULATION_INTERVAL_SECONDS = 1.0
# Solved stellar photometry is a slower transmission/cloud/dew diagnostic. It
# need not track the five-second primary radiometer publication cadence.
SQM_STELLAR_DIAGNOSTIC_INTERVAL_SECONDS = 10.0


def create_sqm_calculator(shared_state):
    """Create a new SQM calculator instance with current calibration.

    Photometry always runs on the raw linear frame (green channel for Bayer
    sensors); the 8-bit processed image is for solving/display only.
    """
    camera_type = shared_state.camera_type()
    logger.info(f"Creating raw-green SQM calculator for camera: {camera_type}")
    return SQMCalculator(camera_type=camera_type)


def _extract_raw_photometry_image(raw, profile):
    """Build the linear photometry image from the stored raw frame.

    For Bayer sensors (SRGGB*) returns the averaged green channel (half-res);
    for mono sensors returns the raw frame as-is. Returns None on any shape/
    dtype problem so the caller can skip the SQM cycle.
    """
    return extract_photometry_image(raw, profile)


def _scale_solution_centroids(solution, scale):
    """Return a shallow copy of solution with matched_centroids scaled.

    The solve runs on the 512x512 processed image; the raw photometry image has a
    different pixel pitch, so the matched star positions must be rescaled to it.
    """
    scaled = dict(solution)
    mc = np.asarray(solution["matched_centroids"], dtype=np.float64) * scale
    scaled["matched_centroids"] = mc
    return scaled


def _derotate_centroids(points, rotation_deg, size):
    """Map (y, x) centroids from the display-rotated solve image back onto
    the unrotated raw frame's pixel grid.

    The camera process rotates the solve/display image by ``rotation_deg``
    (PIL CCW) relative to the raw it stores in shared state; photometry runs
    on the raw, so star positions must be counter-rotated or every aperture
    lands on the wrong sky (SQM then reads magnitudes too bright).

    Args:
        points: (N, 2) array of (y, x) positions in the rotated image.
        rotation_deg: degrees the solve image was rotated (PIL CCW).
        size: side length of the (square) pixel grid the points live on.
    """
    pts = np.asarray(points, dtype=np.float64)
    k = int(rotation_deg) % 360
    y, x = pts[:, 0], pts[:, 1]
    m = size - 1
    if k == 0:
        return pts
    if k == 90:
        # solve = raw rotated 90 CCW: raw_y = x, raw_x = m - y
        return np.stack([x, m - y], axis=1)
    if k == 180:
        return np.stack([m - y, m - x], axis=1)
    if k == 270:
        # solve = raw rotated 270 CCW: raw_y = m - x, raw_x = y
        return np.stack([m - x, y], axis=1)
    # Arbitrary angle: rotate about the image centre. PIL's rotate(a) fills
    # dest(x2, y2) from src at c + R(a)·(p2 − c) in (x, y) with y down.
    c = m / 2.0
    a = np.radians(k)
    dx, dy = x - c, y - c
    rx = c + np.cos(a) * dx - np.sin(a) * dy
    ry = c + np.sin(a) * dx + np.cos(a) * dy
    return np.stack([ry, rx], axis=1)


def update_radiometric_sqm(
    shared_state,
    sqm_calculator,
    accumulator,
    sample,
    calculation_interval_seconds=1.0,
    now=None,
    black_level_tracker=None,
):
    """Collect every frame and publish a solve-independent value at cadence."""
    from datetime import datetime

    fresh_sample = accumulator.add(sample)
    current_time = time.time() if now is None else float(now)

    # Every fresh radiometer sample carries (exposure, background) — feed the
    # black-level tracker here rather than only from the 10-second stellar
    # diagnostics: this cadence conditions its fit in minutes and keeps working
    # through failed solves. Withheld while the last transmission diagnostic
    # said cloud (a moving sky breaks the intercept's single-line model; the
    # tracker's own stderr gate catches drift the flag misses).
    if black_level_tracker is not None and fresh_sample:
        cloudy_now = shared_state.sqm_details().get("cloud_flag") is True
        black_level_tracker.add_sample(
            float(sample["exposure_sec"]),
            float(sample["background_per_pixel"]),
            stable=not cloudy_now,
        )

    current_sqm = shared_state.sqm()
    if current_sqm.last_update is not None:
        try:
            last_update = datetime.fromisoformat(current_sqm.last_update).timestamp()
            if current_time - last_update < calculation_interval_seconds:
                return False
        except (ValueError, AttributeError):
            logger.warning("Failed to parse SQM timestamp, recalculating")

    noise = sqm_calculator.noise_floor_estimator

    def pedestal_for_exposure(exposure_sec):
        if not noise.dark_current_calibrated:
            # Zero-touch path: the tracked black level supersedes the static
            # profile constant (the real pedestal wanders ±2 ADU night to
            # night — negligible over a city background, 0.2–0.4 mag at a
            # dark site). A wizard calibration remains authoritative.
            if black_level_tracker is not None:
                tracked = black_level_tracker.pedestal()
                if tracked is not None:
                    return tracked
            return sqm_calculator.profile.bias_offset
        return (
            sqm_calculator.profile.bias_offset
            + sqm_calculator.profile.dark_current_rate * exposure_sec
        )

    sqm_value, details = accumulator.estimate(
        sqm_calculator.profile,
        current_time,
        pedestal_for_exposure=pedestal_for_exposure,
    )
    if sqm_value is None:
        previous = shared_state.sqm_details()
        shared_state.set_sqm_details({**previous, **details})
        return False

    previous = shared_state.sqm_details()
    diagnostic_at = previous.get("transmission_diagnostic_at")
    diagnostic_age = current_time - diagnostic_at if diagnostic_at is not None else None
    if (
        previous.get("optics_attenuation_candidate")
        and diagnostic_age is not None
        and 0 <= diagnostic_age <= 15.0
    ):
        deficit = previous.get("transmission_deficit")
        if deficit is not None and 0.0 < deficit <= 2.0:
            details["sqm_radiometric_uncorrected"] = sqm_value
            details["optics_attenuation_correction"] = -float(deficit)
            sqm_value -= float(deficit)

    if black_level_tracker is not None:
        tracked, tracked_stderr, _ = black_level_tracker.state()
        details["black_level_tracked"] = (
            tracked is not None and not noise.dark_current_calibrated
        )
        details["black_level_pedestal"] = tracked
        details["black_level_stderr"] = tracked_stderr
        details["window_black_level"] = black_level_tracker.dump()
    details["window_radiometer"] = accumulator.dump()
    details["measurement_role"] = "primary_radiometer"
    shared_state.set_sqm_details({**previous, **details})
    shared_state.set_sqm(
        SQMState(
            value=sqm_value,
            source="Radiometer",
            last_update=timez.local_now().isoformat(),
        )
    )
    logger.info("Radiometric SQM updated: %.2f mag/arcsec²", sqm_value)
    return True


def update_sqm(
    shared_state,
    sqm_calculator,
    centroids,
    solution,
    exposure_sec,
    altitude_deg,
    calculation_interval_seconds=5.0,
    aperture_radius=5,
    annulus_inner_radius=10,
    annulus_outer_radius=18,
    wing_estimator=None,
    cloud_estimator=None,
    black_level_tracker=None,
    publish=True,
):
    """
    Calculate SQM from image.

    Args:
        shared_state: SharedStateObj instance
        sqm_calculator: SQM calculator instance
        centroids: List of detected star centroids
        solution: Tetra3 solve solution with matched stars
        exposure_sec: Exposure time in seconds
        altitude_deg: Altitude in degrees for extinction correction
        calculation_interval_seconds: Minimum time between calculations (default: 5.0)
        aperture_radius: Aperture radius for photometry (default: 5)
        annulus_inner_radius: Inner annulus radius (default: 10)
        annulus_outer_radius: Outer annulus radius (default: 18)
        wing_estimator: WingEstimator that supplies the rolling aperture
            (wing-loss) mzero correction and is fed each frame's photometry
            image + matched centroids.

    Returns:
        bool: True if SQM was calculated and updated, False otherwise
    """
    from datetime import datetime

    # Get current SQM state from shared state
    current_sqm = shared_state.sqm()
    current_time = time.time()

    # Check if we should calculate SQM
    should_calculate = not publish or current_sqm.last_update is None

    if publish and current_sqm.last_update is not None:
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

    profile = sqm_calculator.profile

    try:
        raw = shared_state.cam_raw()
    except (BrokenPipeError, ConnectionResetError):
        raw = None
    green = _extract_raw_photometry_image(raw, profile)
    if green is None or green.shape[0] < 256:
        # cam_raw() is None until the first real capture (test mode never
        # fills it), and a malformed frame comes through far smaller than a
        # real one. A genuine green frame is several hundred px per side —
        # e.g. ~490 for the imx462/imx290 crop, larger for the imx296 — so
        # the floor only rejects missing/garbage frames, not valid sensors.
        # Photometry runs at the green frame's own scale, so a side shorter
        # than the 512px solve image is fine.
        logger.debug("Raw frame unavailable/invalid for SQM; skipping this cycle")
        return False
    scale = green.shape[0] / 512.0
    calc_image = green
    calc_solution = _scale_solution_centroids(solution, scale)
    # All detected centroids, scaled to the photometry image: sqm masks them
    # out of background annuli (neighbour-star contamination in dense fields).
    calc_centroids = (
        np.asarray(centroids, dtype=np.float64) * scale
        if centroids is not None and len(centroids) > 0
        else None
    )

    # The solve image is display-rotated relative to the raw; counter-rotate
    # all star positions onto the raw's grid before photometry.
    try:
        solve_rotation = shared_state.solve_image_rotation()
    except (BrokenPipeError, ConnectionResetError, AttributeError):
        solve_rotation = None
    if solve_rotation:
        side = green.shape[0]
        calc_solution["matched_centroids"] = _derotate_centroids(
            calc_solution["matched_centroids"], solve_rotation, side
        )
        if calc_centroids is not None:
            calc_centroids = _derotate_centroids(calc_centroids, solve_rotation, side)
    image_pixels_per_side = int(green.shape[0])
    # 0.70 of full scale, not ~1.0: CMOS response bends well before hard
    # clip, and stars peaking at 75-90% already read systematically low.
    saturation_threshold = int(0.70 * (2**profile.bit_depth - 1))

    mzero_correction = 0.0
    if wing_estimator is not None:
        mzero_correction = wing_estimator.correction()

    # Track the wandering sensor pedestal from the sky-vs-exposure intercept
    # (see sqm.black_level). Only in the zero-touch path: when the user has run
    # the calibration wizard, its measured bias + dark-current constants are
    # authoritative and the tracker (which fits bias only) must not override.
    pedestal_override = None
    if (
        black_level_tracker is not None
        and not sqm_calculator.noise_floor_estimator.dark_current_calibrated
    ):
        pedestal_override = black_level_tracker.pedestal()

    try:
        # Calculate SQM from image
        sqm_value, details = sqm_calculator.calculate(
            centroids=calc_centroids,
            solution=calc_solution,
            image=calc_image,
            exposure_sec=exposure_sec,
            altitude_deg=altitude_deg,
            aperture_radius=aperture_radius,
            annulus_inner_radius=annulus_inner_radius,
            annulus_outer_radius=annulus_outer_radius,
            saturation_threshold=saturation_threshold,
            image_pixels_per_side=image_pixels_per_side,
            mzero_correction=mzero_correction,
            pedestal_override=pedestal_override,
        )

        # Feed this frame's stars into the rolling wing (aperture-loss) fit.
        if (
            wing_estimator is not None
            and calc_solution.get("matched_centroids") is not None
        ):
            wing_estimator.add_frame(
                calc_image,
                calc_solution["matched_centroids"],
                saturation_threshold,
            )

        # Stellar photometry is now a live transmission diagnostic. The primary
        # sky value is the fixed-calibration radiometer and remains meaningful
        # through cloud; stars classify cloud versus instrument attenuation.
        # Feed the estimator and report the deficit. Only a recent non-cloud
        # deficit against a conditioned session baseline may compensate the
        # next radiometric publication for instrument-side attenuation.
        cloud_flag = None
        if cloud_estimator is not None and details.get("mzero") is not None:
            try:
                pointing = shared_state.solution()
                pointing_alt = getattr(pointing, "Alt", None)
            except (BrokenPipeError, ConnectionResetError, AttributeError):
                pointing_alt = None
            # sky_brightness is the independent radiometric measurement,
            # UNCORRECTED: the guard asks whether the raw sky is anomalously
            # bright vs the device's learned clear-sky level (cloud brightens
            # the sky; dew/optics dim stars and sky together). Feeding the
            # optics-compensated published value back would let a transient
            # correction overshoot masquerade as sky excess and mislabel dew
            # onset as cloud.
            previous_details = shared_state.sqm_details()
            radiometric_sky = previous_details.get("sqm_radiometric")
            if radiometric_sky is None:
                radiometric_sky = shared_state.sqm().value
            cloud_deficit = cloud_estimator.add_sample(
                details["mzero"],
                exposure_sec,
                sky_brightness=radiometric_sky,
                # details['mzero'] already includes the wing correction.
                wing_correction=0.0,
                altitude_deg=pointing_alt,
            )
            cloud_flag = cloud_estimator.is_cloudy()
            details["cloud_extinction"] = cloud_deficit
            details["cloud_flag"] = cloud_flag
            details["transmission_deficit"] = cloud_deficit
            details["optics_attenuation_candidate"] = bool(
                cloud_deficit is not None
                and cloud_deficit > cloud_estimator.cloud_threshold
                and cloud_flag is False
                and cloud_estimator.conditioned()
            )
            details["transmission_diagnostic_at"] = time.time()
            primary_value = shared_state.sqm().value
            if details["optics_attenuation_candidate"]:
                details["sqm_optics_compensated"] = primary_value - cloud_deficit

        # The tracker is fed from the radiometer samples (denser cadence, and
        # the same background estimator its pedestal is applied to); here it is
        # only consumed, so stellar diagnostics report the pedestal actually
        # used for their photometry.
        if black_level_tracker is not None:
            details["black_level_tracked"] = pedestal_override is not None

        details["sqm_star_calibrated"] = sqm_value
        details["measurement_role"] = "stellar_transmission_diagnostic"

        # Full rolling-window state of every tracker, so diagnostics dumps
        # (exposure sweeps in particular) carry the samples behind each
        # published number, not just the summary.
        if wing_estimator is not None:
            details["window_wings"] = wing_estimator.dump()
        if cloud_estimator is not None:
            details["window_clouds"] = cloud_estimator.dump()
        if black_level_tracker is not None:
            details["window_black_level"] = black_level_tracker.dump()

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
        previous = shared_state.sqm_details()
        shared_state.set_sqm_details({**previous, **filtered_details})

        # Update shared state
        if publish and sqm_value is not None:
            new_sqm_state = SQMState(
                value=sqm_value,
                source="Calculated",
                last_update=timez.local_now().isoformat(),
            )
            shared_state.set_sqm(new_sqm_state)
            logger.info(f"SQM updated: {sqm_value:.2f} mag/arcsec²")
            return True
        if sqm_value is not None:
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

    def _alloc_shmem(self, size):
        # Report a freshly created segment (not just a resized one) so the
        # request sets reopen_shmem and the server drops its stale cached fd.
        fresh = self._shmem is None
        resized = super()._alloc_shmem(size)
        return resized or fresh

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
            reopen = self._alloc_shmem(size=width * height)
            shimg = np.ndarray(
                np_image.shape, dtype=np_image.dtype, buffer=self._shmem.buf
            )
            shimg[:] = np_image[:]

            im = cedar_detect_pb2.Image(
                width=width,
                height=height,
                shmem_name=self._shmem.name,
                reopen_shmem=reopen,
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
                    logger.warning(
                        "Cedar shmem transfer failed (%s); "
                        "falling back to inline image passing",
                        err.details(),
                    )
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
        matched_catID=solution.get("matched_catID"),
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
    # Load tetra3's bundled pattern database by name; tetra3 resolves it from
    # its own package data dir (shipped inside the cedar-solve wheel).
    t3 = tetra3.Tetra3("default_database")
    align_ra = 0
    align_dec = 0
    last_solve_attempt: float = 0.0
    last_solve_success = None  # exposure_end of most recent successful solve

    centroids = []
    log_no_stars_found = True

    # SQM calculator is created lazily on the first radiometer sample (or solve
    # in test mode), not here: at solver
    # startup shared_state.camera_type() still holds the pre-camera default,
    # and a calculator built from it would photometer with the wrong sensor
    # profile (pedestal etc.). The camera process records the real type before
    # it captures its first frame, and a solve requires a captured frame, so
    # first real-frame use is guaranteed to see the real camera type.
    sqm_calculator = None
    # Rolling aperture (wing-loss) correction, fed by bright matched stars
    sqm_wing_estimator = WingEstimator()
    # Cloud/dew estimator and black-level tracker are created with the
    # calculator (below) so they get the real sensor's profile seeds; the
    # camera type is not yet known here.
    sqm_cloud_estimator = None
    sqm_black_level = None
    sqm_radiometer = RadiometerAccumulator()
    last_stellar_diagnostic = 0.0

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
                        # Invalidate; the next solve recreates the calculator
                        # with fresh calibration (single creation site).
                        logger.info("Reloading SQM calibration...")
                        sqm_calculator = None
                        sqm_wing_estimator.reset()
                        # Cloud estimator and black-level tracker are recreated
                        # from the fresh profile on the next solve; drop them
                        # here so stale seeds/history cannot carry over.
                        sqm_cloud_estimator = None
                        sqm_black_level = None
                        sqm_radiometer.reset()
                        last_stellar_diagnostic = 0.0
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

                # Every camera frame already carries a tiny radiometer sample
                # reduced in the camera process. Collect all of them and publish
                # at most once per second for CPU/battery stability.
                try:
                    radiometer_sample = shared_state.sqm_radiometer_sample()
                except (BrokenPipeError, ConnectionResetError, AttributeError):
                    radiometer_sample = None
                if radiometer_sample is not None and sqm_calculator is None:
                    sqm_calculator = create_sqm_calculator(shared_state)
                    sqm_wing_estimator.reset()
                    profile = sqm_calculator.profile
                    sqm_cloud_estimator = CloudEstimator(
                        clear_zero_point=profile.clear_zero_point,
                        clear_sky_brightness=profile.clear_sky_brightness,
                    )
                    sqm_black_level = BlackLevelTracker(profile.bias_offset)
                if sqm_calculator is not None:
                    update_radiometric_sqm(
                        shared_state,
                        sqm_calculator,
                        sqm_radiometer,
                        radiometer_sample,
                        calculation_interval_seconds=SQM_CALCULATION_INTERVAL_SECONDS,
                        black_level_tracker=sqm_black_level,
                    )

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
                        if sqm_calculator is None:
                            sqm_calculator = create_sqm_calculator(shared_state)
                            sqm_wing_estimator.reset()
                            profile = sqm_calculator.profile
                            sqm_cloud_estimator = CloudEstimator(
                                clear_zero_point=profile.clear_zero_point,
                                clear_sky_brightness=profile.clear_sky_brightness,
                            )
                            sqm_black_level = BlackLevelTracker(profile.bias_offset)

                        # Expensive stellar photometry is diagnostic-only in the
                        # radiometer-first path and remains limited to 10 seconds.
                        exposure_sec = (
                            last_image_metadata["exposure_time"] / 1_000_000.0
                        )
                        # Topocentric altitude is computed later by the
                        # integrator. Do not mislabel an unavailable value as
                        # zenith; the published SQM remains uncorrected and the
                        # optional comparison diagnostic stays absent.
                        altitude_for_sqm = None

                        diagnostic_now = time.time()
                        if (
                            diagnostic_now - last_stellar_diagnostic
                            >= SQM_STELLAR_DIAGNOSTIC_INTERVAL_SECONDS
                        ):
                            update_sqm(
                                shared_state=shared_state,
                                sqm_calculator=sqm_calculator,
                                centroids=centroids,
                                solution=solution,
                                exposure_sec=exposure_sec,
                                altitude_deg=altitude_for_sqm,
                                calculation_interval_seconds=SQM_CALCULATION_INTERVAL_SECONDS,
                                wing_estimator=sqm_wing_estimator,
                                cloud_estimator=sqm_cloud_estimator,
                                black_level_tracker=sqm_black_level,
                                publish=False,
                            )
                            last_stellar_diagnostic = diagnostic_now

                        # Don't clutter printed solution with these fields (use pop to safely remove)
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
                        solution.pop("matched_catID", None)

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
