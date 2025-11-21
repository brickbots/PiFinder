import numpy as np
import logging
from typing import Tuple, Dict, Optional, Any
from datetime import datetime
import time
from PiFinder.state import SQM as SQMState
from .noise_floor import NoiseFloorEstimator

logger = logging.getLogger("Solver")


class SQM:
    """
    SQM (Sky Quality Meter) class to calculate sky background brightness.

    Implementation uses local annulus background measurement:
    - Proper photometric zero point calibration from catalog stars
    - Local background measurement from annulus around each star (handles uneven backgrounds)
    - Background subtraction from star aperture measurements
    - Atmospheric extinction correction
    - Pedestal/bias handling

    Formula:
        For each star: local_bg = median(annulus pixels)
        Star flux = aperture_sum - local_bg × aperture_area
        mzero = mean(catalog_mag + 2.5 × log10(star_flux_ADU))
        Sky background = median(all local_bg measurements)
        SQM = mzero - 2.5 × log10((sky_bg - pedestal) / pixel_area_arcsec²) + extinction

    This correctly compares star total flux (point sources) to background flux density
    (extended source), giving SQM in mag/arcsec².
    """

    def __init__(
        self,
        camera_type: str = "imx296",
        pedestal_from_background: bool = False,
        use_adaptive_noise_floor: bool = True,
    ):
        """
        Initialize SQM calculator.

        Args:
            camera_type: Camera model (imx296, imx462, imx290, hq) for noise estimation
            pedestal_from_background: If True, automatically estimate pedestal from
                median of local backgrounds. Default False (manual pedestal only).
            use_adaptive_noise_floor: If True, use adaptive noise floor estimation.
                If False, fall back to manual pedestal parameter. Default True.
        """
        super()
        self.pedestal_from_background = pedestal_from_background
        self.use_adaptive_noise_floor = use_adaptive_noise_floor

        # Initialize noise floor estimator if enabled
        self.noise_estimator: Optional[NoiseFloorEstimator] = None
        if use_adaptive_noise_floor:
            self.noise_estimator = NoiseFloorEstimator(
                camera_type=camera_type,
                enable_zero_sec_sampling=True,
                zero_sec_interval=300,  # Every 5 minutes
            )
            logger.info(
                f"SQM initialized with adaptive noise floor estimation (camera: {camera_type})"
            )
        else:
            logger.info("SQM initialized with manual pedestal mode")

    def _calc_field_parameters(self, fov_degrees: float) -> None:
        """Calculate field of view parameters."""
        self.fov_degrees = fov_degrees
        self.field_arcsec_squared = (fov_degrees * 3600) ** 2
        self.pixels_total = 512**2
        self.arcsec_squared_per_pixel = self.field_arcsec_squared / self.pixels_total

    def _calculate_background(
        self, image: np.ndarray, centroids: np.ndarray, exclusion_radius: int
    ) -> float:
        """
        Calculate background from star-free regions using median.

        Args:
            image: Image array
            centroids: All detected centroids (for masking)
            exclusion_radius: Radius around each star to exclude (pixels)

        Returns:
            Background level in ADU per pixel
        """
        height, width = image.shape
        mask = np.ones((height, width), dtype=bool)

        # Create coordinate grids
        y, x = np.ogrid[:height, :width]

        # Mask out regions around all stars
        for cx, cy in centroids:
            if 0 <= cx < width and 0 <= cy < height:
                star_mask = (x - cx) ** 2 + (y - cy) ** 2 <= exclusion_radius**2
                mask &= ~star_mask

        # Calculate median background from unmasked regions
        if np.sum(mask) > 100:  # Need enough pixels for reliable median
            background_per_pixel = np.median(image[mask])
        else:
            # Fallback to percentile if too many stars
            background_per_pixel = np.percentile(image, 10)
            logger.warning(
                f"Using 10th percentile for background (only {np.sum(mask)} unmasked pixels)"
            )

        return float(background_per_pixel)

    def _measure_star_flux_with_local_background(
        self,
        image: np.ndarray,
        centroids: np.ndarray,
        aperture_radius: int,
        annulus_inner_radius: int,
        annulus_outer_radius: int,
    ) -> Tuple[list, list]:
        """
        Measure star flux with local background from annulus around each star.

        Args:
            image: Image array
            centroids: Star centroids to measure
            aperture_radius: Aperture radius for star flux in pixels
            annulus_inner_radius: Inner radius of background annulus in pixels
            annulus_outer_radius: Outer radius of background annulus in pixels

        Returns:
            Tuple of (star_fluxes, local_backgrounds) where:
                star_fluxes: Background-subtracted star fluxes (total ADU above local background)
                local_backgrounds: Local background per pixel for each star (ADU/pixel)
        """
        height, width = image.shape
        star_fluxes = []
        local_backgrounds = []

        # Pre-compute squared radii
        aperture_r2 = aperture_radius**2
        annulus_inner_r2 = annulus_inner_radius**2
        annulus_outer_r2 = annulus_outer_radius**2

        for cy, cx in centroids:  # centroids are in (y, x) format after swap
            # Use bounding box instead of full-frame masks for huge speedup
            # Box needs to contain outer annulus radius
            box_size = annulus_outer_radius + 1
            y_min = max(0, int(cy) - box_size)
            y_max = min(height, int(cy) + box_size + 1)
            x_min = max(0, int(cx) - box_size)
            x_max = min(width, int(cx) + box_size + 1)

            # Extract image patch
            image_patch = image[y_min:y_max, x_min:x_max]

            # Create coordinate grids relative to star center (only for patch)
            y_grid, x_grid = np.ogrid[y_min:y_max, x_min:x_max]
            dist_squared = (x_grid - cx) ** 2 + (y_grid - cy) ** 2

            # Create aperture mask for star flux
            aperture_mask = dist_squared <= aperture_r2

            # Create annulus mask for local background
            annulus_mask = (dist_squared > annulus_inner_r2) & (
                dist_squared <= annulus_outer_r2
            )

            # Measure local background from annulus (median for robustness)
            annulus_pixels = image_patch[annulus_mask]
            if len(annulus_pixels) > 0:
                local_bg_per_pixel = float(np.median(annulus_pixels))
            else:
                # this is impossible
                local_bg_per_pixel = float(np.median(image))
                logger.warning(
                    f"Star at ({cx:.0f},{cy:.0f}) has no annulus pixels, using global median"
                )

            # Total flux in aperture (includes background)
            total_flux = np.sum(image_patch[aperture_mask])

            # Subtract background contribution
            aperture_area_pixels = np.sum(aperture_mask)
            background_contribution = local_bg_per_pixel * aperture_area_pixels
            star_flux = total_flux - background_contribution

            star_fluxes.append(star_flux)
            local_backgrounds.append(local_bg_per_pixel)

        return star_fluxes, local_backgrounds

    def _calculate_mzero(
        self, star_fluxes: list, star_mags: list
    ) -> Tuple[Optional[float], list]:
        """
        Calculate photometric zero point from calibrated stars.

        For point sources: mzero = catalog_mag + 2.5 × log10(total_flux_ADU)

        This zero point allows converting any ADU measurement to magnitudes:
            mag = mzero - 2.5 × log10(flux_ADU)

        Args:
            star_fluxes: Background-subtracted star fluxes (ADU)
            star_mags: Catalog magnitudes for matched stars

        Returns:
            Tuple of (mean_mzero, list_of_individual_mzeros)
            Note: The mzeros list will contain None for stars with invalid flux
        """
        mzeros: list[Optional[float]] = []

        for flux, mag in zip(star_fluxes, star_mags):
            if flux <= 0:
                logger.debug(
                    f"Skipping star with flux={flux:.1f} ADU (mag={mag:.2f})"
                )
                mzeros.append(None)  # Keep array aligned
                continue

            # Calculate zero point: ZP = m + 2.5*log10(F)
            mzero = mag + 2.5 * np.log10(flux)
            mzeros.append(mzero)

        # Filter out None values for statistics calculation
        valid_mzeros = [mz for mz in mzeros if mz is not None]

        if len(valid_mzeros) == 0:
            logger.error("No valid stars for mzero calculation")
            return None, mzeros

        # Return mean and the full mzeros list (which may contain None values)
        return float(np.mean(valid_mzeros)), mzeros

    def _detect_aperture_overlaps(
        self,
        centroids: np.ndarray,
        aperture_radius: int,
        annulus_inner_radius: int,
        annulus_outer_radius: int,
    ) -> set:
        """
        Detect stars with overlapping apertures or annuli.

        Returns set of indices for stars that should be excluded due to overlaps.
        We exclude stars involved in CRITICAL or HIGH severity overlaps:
        - CRITICAL: Aperture-aperture overlap (distance < 2*aperture_radius)
        - HIGH: Aperture inside another star's annulus (distance < aperture_radius + annulus_outer_radius)

        Args:
            centroids: Star centroids array (N x 2)
            aperture_radius: Aperture radius in pixels
            annulus_inner_radius: Inner annulus radius in pixels
            annulus_outer_radius: Outer annulus radius in pixels

        Returns:
            Set of star indices to exclude
        """
        excluded_stars = set()
        n_stars = len(centroids)

        # Check all pairs
        for i in range(n_stars):
            for j in range(i + 1, n_stars):
                x1, y1 = centroids[i]
                x2, y2 = centroids[j]
                distance = np.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)

                # CRITICAL: Aperture-aperture overlap (star flux contamination)
                if distance < 2 * aperture_radius:
                    excluded_stars.add(i)
                    excluded_stars.add(j)
                    logger.debug(
                        f"CRITICAL overlap: stars {i} and {j} (d={distance:.1f}px < {2*aperture_radius}px)"
                    )
                # HIGH: Aperture inside another star's annulus (background contamination)
                elif distance < aperture_radius + annulus_outer_radius:
                    excluded_stars.add(i)
                    excluded_stars.add(j)
                    logger.debug(
                        f"HIGH overlap: stars {i} and {j} (d={distance:.1f}px < {aperture_radius + annulus_outer_radius}px)"
                    )

        return excluded_stars

    def _atmospheric_extinction(self, altitude_deg: float) -> float:
        """
        Calculate atmospheric extinction correction to above-atmosphere equivalent.

        Uses simplified airmass model and typical V-band extinction coefficient.

        The atmosphere ALWAYS dims starlight - even at zenith there's 0.28 mag extinction.
        This correction accounts for the total atmospheric extinction to estimate what
        the sky brightness would be if measured from above the atmosphere.

        Args:
            altitude_deg: Altitude of field center in degrees

        Returns:
            Extinction correction in magnitudes (add to measured SQM)
            - At zenith (90°): 0.28 mag (minimum)
            - At 45°: ~0.40 mag
            - At 30°: 0.56 mag
        """
        if altitude_deg <= 0:
            logger.warning(
                f"Invalid altitude: {altitude_deg}°, skipping extinction correction"
            )
            return 0.0

        # Simplified airmass calculation
        altitude_rad = np.radians(altitude_deg)
        airmass = 1.0 / np.sin(altitude_rad)

        # Typical V-band extinction: 0.28 mag/airmass at sea level
        # Total extinction is always present (minimum 0.28 mag at zenith)
        extinction_correction = 0.28 * airmass

        return extinction_correction

    def calculate(
        self,
        centroids: list,
        solution: dict,
        image: np.ndarray,
        exposure_sec: float,
        bias_image: Optional[np.ndarray] = None,
        altitude_deg: float = 90.0,
        aperture_radius: int = 5,
        annulus_inner_radius: int = 6,
        annulus_outer_radius: int = 14,
        pedestal: float = 0.0,
        correct_overlaps: bool = False,
    ) -> Tuple[Optional[float], Dict]:
        """
        Calculate SQM (Sky Quality Meter) value using local background annuli.

        Args:
            centroids: All detected centroids (unused, kept for compatibility)
            solution: Tetra3 solution dict with 'FOV', 'matched_centroids', 'matched_stars'
            image: Image array (uint8 or float)
            exposure_sec: Exposure time in seconds (required for adaptive noise floor)
            bias_image: Optional bias/dark frame for pedestal calculation (default: None)
            altitude_deg: Altitude of field center for extinction correction (default: 90 = zenith)
            aperture_radius: Radius for star photometry in pixels (default: 5)
            annulus_inner_radius: Inner radius of background annulus in pixels (default: 6)
            annulus_outer_radius: Outer radius of background annulus in pixels (default: 14)
            pedestal: Bias/pedestal level to subtract from background (default: 0)
                     Only used if use_adaptive_noise_floor=False
                     If bias_image is provided and pedestal=0, pedestal is calculated from bias_image
            correct_overlaps: If True, exclude stars with overlapping apertures/annuli (default: False)
                            Excludes CRITICAL and HIGH overlaps to prevent contamination

        Returns:
            Tuple of (sqm_value, details_dict) where:
                sqm_value: SQM in mag/arcsec² (or None if calculation failed)
                details_dict: Dictionary with intermediate values for diagnostics

        Example:
            # Using local annulus backgrounds (handles uneven backgrounds)
            sqm_value, details = sqm_calculator.calculate(
                centroids=all_centroids,
                solution=tetra3_solution,
                image=np_image,
                bias_image=bias_frame,
                altitude_deg=45.0,
                aperture_radius=5,
                annulus_inner_radius=6,
                annulus_outer_radius=14,
                correct_overlaps=True  # Exclude overlapping stars
            )

            if sqm_value:
                print(f"SQM: {sqm_value:.2f} mag/arcsec²")
        """
        # Extract FOV from solution
        if "FOV" not in solution:
            logger.error("Solution missing 'FOV' field")
            return None, {}

        fov_estimate = solution["FOV"]
        self._calc_field_parameters(fov_estimate)

        # Validate solution has matched stars
        if "matched_centroids" not in solution or "matched_stars" not in solution:
            logger.error("Solution missing matched_centroids or matched_stars")
            return None, {}

        matched_centroids = np.array(solution["matched_centroids"])
        matched_stars = solution["matched_stars"]

        if len(matched_centroids) == 0 or len(matched_stars) == 0:
            logger.error("No matched stars in solution")
            return None, {}

        # Don't swap - centroids are already in (row, col) = (y, x) format
        matched_centroids_arr = matched_centroids
        star_mags = [s[2] for s in matched_stars]

        # 0a. Detect and filter overlapping stars if requested
        n_stars_original = len(matched_centroids_arr)
        n_stars_excluded = 0

        if correct_overlaps:
            excluded_indices = self._detect_aperture_overlaps(
                matched_centroids_arr,
                aperture_radius,
                annulus_inner_radius,
                annulus_outer_radius,
            )

            if excluded_indices:
                n_stars_excluded = len(excluded_indices)
                # Filter out overlapping stars
                valid_indices = [
                    i
                    for i in range(len(matched_centroids_arr))
                    if i not in excluded_indices
                ]
                matched_centroids_arr = matched_centroids_arr[valid_indices]
                star_mags = [star_mags[i] for i in valid_indices]

                logger.info(
                    f"Overlap correction: excluded {n_stars_excluded}/{n_stars_original} stars "
                    f"({n_stars_excluded*100//n_stars_original}%), using {len(valid_indices)} stars"
                )

                if len(valid_indices) < 3:
                    logger.warning(
                        f"Too few stars remaining after overlap correction ({len(valid_indices)})"
                    )
                    return None, {}

        # 0. Determine noise floor / pedestal
        noise_floor_details: Dict[str, Any] = {}

        if self.use_adaptive_noise_floor and self.noise_estimator is not None:
            # Use adaptive noise floor estimation
            noise_floor, noise_floor_details = (
                self.noise_estimator.estimate_noise_floor(
                    image=image,
                    exposure_sec=exposure_sec,
                    percentile=5.0,
                )
            )
            pedestal = noise_floor

            logger.info(
                f"Adaptive noise floor: {noise_floor:.1f} ADU "
                f"(dark_px={noise_floor_details['dark_pixel_smoothed']:.1f}, "
                f"theory={noise_floor_details['theoretical_floor']:.1f}, "
                f"valid={noise_floor_details['is_valid']})"
            )

            # Check if zero-sec sample requested
            if noise_floor_details.get("request_zero_sec_sample"):
                logger.info(
                    "Zero-second calibration sample requested by noise estimator "
                    "(will be captured in next cycle)"
                )
        else:
            # Use manual pedestal (legacy mode)
            if bias_image is not None and pedestal == 0.0:
                pedestal = float(np.median(bias_image))
                logger.debug(f"Pedestal from bias: {pedestal:.2f} ADU")
            elif pedestal > 0:
                logger.debug(f"Using manual pedestal: {pedestal:.2f} ADU")
            else:
                logger.debug("No pedestal applied")

        # 1. Measure star fluxes with local background from annulus
        star_fluxes, local_backgrounds = self._measure_star_flux_with_local_background(
            image,
            matched_centroids_arr,
            aperture_radius,
            annulus_inner_radius,
            annulus_outer_radius,
        )

        # 1a. Estimate pedestal from median local background if enabled and not already set
        if (
            self.pedestal_from_background
            and pedestal == 0.0
            and len(local_backgrounds) > 0
        ):
            pedestal = float(np.median(local_backgrounds))
            logger.debug(
                f"Pedestal estimated from median(local_backgrounds): {pedestal:.2f} ADU"
            )

        # 2. Calculate sky background from median of local backgrounds
        if len(local_backgrounds) == 0:
            logger.warning("No local backgrounds measured - no valid stars with annuli")
            return None, {}

        background_per_pixel = float(np.median(local_backgrounds))

        # 3. Apply pedestal correction (like ASTAP)
        background_corrected = background_per_pixel - pedestal

        if background_corrected <= 0:
            logger.warning(
                f"SQM calculation skipped: background ≤0 after pedestal correction "
                f"({background_per_pixel:.2f} - {pedestal:.2f} = {background_corrected:.2f})"
            )
            return None, {}

        # 4. Calculate photometric zero point
        mzero, mzeros = self._calculate_mzero(star_fluxes, star_mags)

        if mzero is None:
            return None, {}

        # 5. Convert background to flux density (ADU per arcsec²)
        background_flux_density = background_corrected / self.arcsec_squared_per_pixel

        # 6. Calculate raw SQM
        if background_flux_density <= 0:
            logger.error(f"Invalid background flux density: {background_flux_density}")
            return None, {}

        sqm_raw = mzero - 2.5 * np.log10(background_flux_density)

        # 7. Apply atmospheric extinction correction
        extinction_correction = self._atmospheric_extinction(altitude_deg)
        sqm_final = sqm_raw + extinction_correction

        # Filter out None values for statistics in diagnostics
        valid_mzeros_for_stats = [mz for mz in mzeros if mz is not None]

        # Assemble diagnostics
        details = {
            "fov_deg": fov_estimate,
            "n_centroids": len(centroids)
            if centroids is not None and len(centroids) > 0
            else 0,
            "n_matched_stars": len(matched_stars),
            "n_matched_stars_original": n_stars_original,
            "overlap_correction_enabled": correct_overlaps,
            "n_stars_excluded_overlaps": n_stars_excluded,
            "background_per_pixel": background_per_pixel,
            "background_method": "local_annulus",
            "pedestal": pedestal,
            "pedestal_source": (
                "adaptive_noise_floor"
                if self.use_adaptive_noise_floor and self.noise_estimator is not None
                else (
                    "bias_image"
                    if bias_image is not None
                    else (
                        "median_local_backgrounds"
                        if pedestal > 0
                        and bias_image is None
                        and self.pedestal_from_background
                        else ("manual" if pedestal > 0 else "none")
                    )
                )
            ),
            "noise_floor_details": noise_floor_details if noise_floor_details else None,
            "exposure_sec": exposure_sec,
            "background_corrected": background_corrected,
            "background_flux_density": background_flux_density,
            "arcsec_per_pixel": np.sqrt(self.arcsec_squared_per_pixel),
            "aperture_radius": aperture_radius,
            "annulus_inner_radius": annulus_inner_radius,
            "annulus_outer_radius": annulus_outer_radius,
            "mzero": mzero,
            "mzero_std": float(np.std(valid_mzeros_for_stats)),
            "mzero_range": (
                float(np.min(valid_mzeros_for_stats)),
                float(np.max(valid_mzeros_for_stats)),
            ),
            "sqm_raw": sqm_raw,
            "altitude_deg": altitude_deg,
            "extinction_correction": extinction_correction,
            "sqm_final": sqm_final,
            # Per-star details for diagnostics
            "star_centroids": matched_centroids_arr.tolist(),
            "star_mags": star_mags,
            "star_fluxes": star_fluxes,
            "star_local_backgrounds": local_backgrounds,
            "star_mzeros": mzeros,
        }

        logger.debug(
            f"SQM: mzero={mzero:.2f}±{np.std(valid_mzeros_for_stats):.2f}, "
            f"bg={background_flux_density:.6f} ADU/arcsec², pedestal={pedestal:.2f}, "
            f"raw={sqm_raw:.2f}, extinction={extinction_correction:.2f}, final={sqm_final:.2f}"
        )

        return sqm_final, details


def update_sqm_if_needed(
    shared_state,
    sqm_calculator: SQM,
    centroids: list,
    solution: dict,
    image: np.ndarray,
    exposure_sec: float,
    altitude_deg: float,
    calculation_interval_seconds: float = 5.0,
    aperture_radius: int = 5,
    annulus_inner_radius: int = 6,
    annulus_outer_radius: int = 14,
) -> bool:
    """
    Check if SQM needs updating and calculate/store new value if needed.

    This function encapsulates all the logic for time-based SQM updates:
    - Checks if enough time has passed since last update
    - Calculates new SQM value if needed
    - Updates shared state with new SQM object
    - Handles all timestamp conversions and error cases

    Args:
        shared_state: SharedStateObj instance to read/write SQM state
        sqm_calculator: SQM calculator instance
        centroids: List of detected star centroids
        solution: Tetra3 solve solution with matched stars
        image: Raw image array
        exposure_sec: Exposure time in seconds (required for adaptive noise floor)
        altitude_deg: Altitude in degrees for extinction correction
        calculation_interval_seconds: Minimum time between calculations (default: 5.0)
        aperture_radius: Aperture radius for photometry (default: 5)
        annulus_inner_radius: Inner annulus radius (default: 6)
        annulus_outer_radius: Outer annulus radius (default: 14)

    Returns:
        bool: True if SQM was calculated and updated, False otherwise
    """
    # Get current SQM state from shared state
    current_sqm = shared_state.sqm()
    current_time = time.time()

    # Check if we should calculate SQM:
    # - No previous calculation (last_update is None), OR
    # - Enough time has passed since last update
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
            # If timestamp parsing fails, recalculate
            logger.warning("Failed to parse SQM timestamp, recalculating")
            should_calculate = True

    if not should_calculate:
        return False

    # Calculate new SQM value
    try:
        sqm_value, _ = sqm_calculator.calculate(
            centroids=centroids,
            solution=solution,
            image=image,
            exposure_sec=exposure_sec,
            altitude_deg=altitude_deg,
            aperture_radius=aperture_radius,
            annulus_inner_radius=annulus_inner_radius,
            annulus_outer_radius=annulus_outer_radius,
        )

        if sqm_value is not None:
            # Create new SQM state object
            new_sqm_state = SQMState(
                value=sqm_value,
                source="Calculated",
                last_update=datetime.now().isoformat(),
            )
            shared_state.set_sqm(new_sqm_state)
            # logger.debug(f"SQM: {sqm_value:.2f} mag/arcsec²")
            return True
        else:
            logger.warning("SQM calculation returned None")
            return False

    except Exception as e:
        logger.error(f"SQM calculation failed: {e}", exc_info=True)
        return False
