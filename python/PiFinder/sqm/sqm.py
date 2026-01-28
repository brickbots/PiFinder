import numpy as np
import logging
from typing import Tuple, Dict, Optional
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
    ):
        """
        Initialize SQM calculator.

        Args:
            camera_type: Camera model (imx296, imx462, imx290, hq) for noise estimation.
                Use "_processed" suffix for 8-bit ISP-processed images.
        """
        self.noise_estimator = NoiseFloorEstimator(
            camera_type=camera_type,
            enable_zero_sec_sampling=True,
            zero_sec_interval=300,  # Every 5 minutes
        )
        logger.info(
            f"SQM initialized with adaptive noise floor estimation (camera: {camera_type})"
        )

    def _calc_field_parameters(self, fov_degrees: float) -> None:
        """Calculate field of view parameters."""
        self.fov_degrees = fov_degrees
        self.field_arcsec_squared = (fov_degrees * 3600) ** 2
        self.pixels_total = 512**2
        self.arcsec_squared_per_pixel = self.field_arcsec_squared / self.pixels_total

    def _pickering_airmass(self, altitude_deg: float) -> float:
        """
        Calculate airmass using Pickering (2002) formula.

        More accurate than simple 1/sin(alt) near the horizon.
        Accounts for atmospheric refraction.

        Reference: Pickering, K.A. (2002), "The Southern Limits of the Ancient
        Star Catalogs", DIO 12, 1-15.

        Args:
            altitude_deg: Altitude in degrees (must be > 0)

        Returns:
            Airmass value (1.0 at zenith, increases toward horizon)
        """
        h = altitude_deg
        return 1.0 / np.sin(np.radians(h + 244.0 / (165.0 + 47.0 * h**1.1)))

    def _measure_star_flux_with_local_background(
        self,
        image: np.ndarray,
        centroids: np.ndarray,
        aperture_radius: int,
        annulus_inner_radius: int,
        annulus_outer_radius: int,
        saturation_threshold: int = 250,
    ) -> Tuple[list, list, int]:
        """
        Measure star flux with local background from annulus around each star.

        Args:
            image: Image array
            centroids: Star centroids to measure
            aperture_radius: Aperture radius for star flux in pixels
            annulus_inner_radius: Inner radius of background annulus in pixels
            annulus_outer_radius: Outer radius of background annulus in pixels
            saturation_threshold: Pixel value threshold for saturation detection (default: 250)
                                  Stars with any aperture pixel >= this value are marked saturated

        Returns:
            Tuple of (star_fluxes, local_backgrounds, n_saturated) where:
                star_fluxes: Background-subtracted star fluxes (total ADU above local background)
                            Saturated stars have flux set to -1 to be excluded from mzero calculation
                local_backgrounds: Local background per pixel for each star (ADU/pixel)
                n_saturated: Number of stars excluded due to saturation
        """
        height, width = image.shape
        star_fluxes = []
        local_backgrounds = []
        n_saturated = 0

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

            # Check for saturation in aperture
            aperture_pixels = image_patch[aperture_mask]
            max_aperture_pixel = np.max(aperture_pixels) if len(aperture_pixels) > 0 else 0

            if max_aperture_pixel >= saturation_threshold:
                # Mark saturated star with flux=-1 to be excluded from mzero calculation
                star_fluxes.append(-1)
                local_backgrounds.append(local_bg_per_pixel)
                n_saturated += 1
                continue

            # Total flux in aperture (includes background)
            total_flux = np.sum(aperture_pixels)

            # Subtract background contribution
            aperture_area_pixels = np.sum(aperture_mask)
            background_contribution = local_bg_per_pixel * aperture_area_pixels
            star_flux = total_flux - background_contribution

            star_fluxes.append(star_flux)
            local_backgrounds.append(local_bg_per_pixel)

        return star_fluxes, local_backgrounds, n_saturated

    def _calculate_mzero(
        self, star_fluxes: list, star_mags: list
    ) -> Tuple[Optional[float], list]:
        """
        Calculate photometric zero point from calibrated stars using flux-weighted mean.

        For point sources: mzero = catalog_mag + 2.5 × log10(total_flux_ADU)

        This zero point allows converting any ADU measurement to magnitudes:
            mag = mzero - 2.5 × log10(flux_ADU)

        Uses flux-weighted mean: brighter stars have higher SNR so their
        mzero estimates are more reliable.

        Args:
            star_fluxes: Background-subtracted star fluxes (ADU)
            star_mags: Catalog magnitudes for matched stars

        Returns:
            Tuple of (weighted_mean_mzero, list_of_individual_mzeros)
            Note: The mzeros list will contain None for stars with invalid flux
        """
        mzeros: list[Optional[float]] = []
        valid_mzeros = []
        valid_fluxes = []

        for flux, mag in zip(star_fluxes, star_mags):
            if flux <= 0:
                logger.warning(
                    f"Skipping star with flux={flux:.1f} ADU (mag={mag:.2f})"
                )
                mzeros.append(None)  # Keep array aligned
                continue

            # Calculate zero point: ZP = m + 2.5*log10(F)
            mzero = mag + 2.5 * np.log10(flux)
            mzeros.append(mzero)
            valid_mzeros.append(mzero)
            valid_fluxes.append(flux)

        if len(valid_mzeros) == 0:
            logger.error("No valid stars for mzero calculation")
            return None, mzeros

        # Flux-weighted mean: brighter stars contribute more
        valid_mzeros_arr = np.array(valid_mzeros)
        valid_fluxes_arr = np.array(valid_fluxes)
        weighted_mzero = float(
            np.average(valid_mzeros_arr, weights=valid_fluxes_arr)
        )

        return weighted_mzero, mzeros

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
        Calculate atmospheric extinction correction.

        Uses Pickering (2002) airmass formula for improved accuracy near horizon.
        Zenith is the reference point (extinction=0), with additional extinction
        added for lower altitudes.

        Args:
            altitude_deg: Altitude of field center in degrees

        Returns:
            Extinction correction in magnitudes (add to measured SQM)
            - At zenith (90°): 0.0 mag (reference point)
            - At 45°: ~0.12 mag
            - At 30°: ~0.28 mag
        """
        if altitude_deg <= 0:
            logger.warning(
                f"Invalid altitude: {altitude_deg}°, skipping extinction correction"
            )
            return 0.0

        # Use Pickering (2002) airmass formula for better accuracy near horizon
        airmass = self._pickering_airmass(altitude_deg)

        # V-band extinction coefficient: 0.28 mag/airmass
        # Following ASTAP convention: zenith is reference point (extinction=0 at zenith)
        # Only the ADDITIONAL extinction below zenith is added: k * (airmass - 1)
        extinction_correction = 0.28 * (airmass - 1)

        return extinction_correction

    def _determine_pedestal_source(self) -> str:
        """Determine the source of the pedestal value for diagnostics."""
        return "adaptive_noise_floor"

    def calculate(
        self,
        centroids: list,
        solution: dict,
        image: np.ndarray,
        exposure_sec: float,
        altitude_deg: float = 90.0,
        aperture_radius: int = 5,
        annulus_inner_radius: int = 6,
        annulus_outer_radius: int = 14,
        correct_overlaps: bool = False,
        saturation_threshold: int = 250,
    ) -> Tuple[Optional[float], Dict]:
        """
        Calculate SQM (Sky Quality Meter) value using local background annuli.

        Args:
            centroids: All detected centroids (unused, kept for compatibility)
            solution: Tetra3 solution dict with 'FOV', 'matched_centroids', 'matched_stars'
            image: Image array (uint8 or float)
            exposure_sec: Exposure time in seconds (required for noise floor estimation)
            altitude_deg: Altitude of field center for extinction correction (default: 90 = zenith)
            aperture_radius: Radius for star photometry in pixels (default: 5)
            annulus_inner_radius: Inner radius of background annulus in pixels (default: 6)
            annulus_outer_radius: Outer radius of background annulus in pixels (default: 14)
            correct_overlaps: If True, exclude stars with overlapping apertures/annuli (default: False)
            saturation_threshold: Pixel value threshold for saturation detection (default: 250)

        Returns:
            Tuple of (sqm_value, details_dict) where:
                sqm_value: SQM in mag/arcsec² (or None if calculation failed)
                details_dict: Dictionary with intermediate values for diagnostics

        Example:
            sqm_value, details = sqm_calculator.calculate(
                centroids=all_centroids,
                solution=tetra3_solution,
                image=np_image,
                exposure_sec=0.5,
                altitude_deg=45.0,
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

        # 0. Determine noise floor / pedestal using adaptive estimation
        noise_floor, noise_floor_details = self.noise_estimator.estimate_noise_floor(
            image=image,
            exposure_sec=exposure_sec,
            percentile=5.0,
        )
        # Pedestal = bias_offset + dark_current_contribution
        # - Bias offset: electronic pedestal, systematic offset - SUBTRACT
        # - Dark current mean: thermal electrons, systematic offset - SUBTRACT
        # - Read noise: random fluctuation around 0 - do NOT subtract
        # For processed images, dark_current_contribution is ~0 (ISP handles it)
        bias_offset = noise_floor_details.get("bias_offset", 0.0)
        dark_current_contrib = noise_floor_details.get("dark_current_contribution", 0.0)
        pedestal = bias_offset + dark_current_contrib

        logger.info(
            f"Adaptive noise floor: {noise_floor:.1f} ADU, "
            f"pedestal={pedestal:.1f} (bias={bias_offset:.1f} + dark={dark_current_contrib:.1f}) "
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

        # 1. Measure star fluxes with local background from annulus
        star_fluxes, local_backgrounds, n_saturated = (
            self._measure_star_flux_with_local_background(
                image,
                matched_centroids_arr,
                aperture_radius,
                annulus_inner_radius,
                annulus_outer_radius,
                saturation_threshold,
            )
        )

        if n_saturated > 0:
            logger.info(
                f"Excluded {n_saturated}/{len(matched_centroids_arr)} saturated stars "
                f"(threshold={saturation_threshold})"
            )

        # 2. Calculate sky background from median of local backgrounds
        if len(local_backgrounds) == 0:
            logger.warning("No local backgrounds measured - no valid stars with annuli")
            return None, {}

        background_per_pixel = float(np.median(local_backgrounds))

        # 3. Apply pedestal correction (like ASTAP)
        background_corrected = background_per_pixel - pedestal

        # Clamp background to minimum of 1 ADU to prevent negative/zero values
        if background_corrected <= 0:
            logger.warning(
                f"Background clamped to 1.0 ADU after pedestal correction "
                f"({background_per_pixel:.2f} - {pedestal:.2f} = {background_corrected:.2f})"
            )
            background_corrected = 1.0

        # 4. Calculate photometric zero point
        mzero, mzeros = self._calculate_mzero(star_fluxes, star_mags)

        if mzero is None:
            return None, {}

        # 5. Convert background to flux density (ADU per arcsec²)
        background_flux_density = background_corrected / self.arcsec_squared_per_pixel

        # 6. Calculate SQM (before extinction correction)
        if background_flux_density <= 0:
            logger.error(f"Invalid background flux density: {background_flux_density}")
            return None, {}

        sqm_uncorrected = mzero - 2.5 * np.log10(background_flux_density)

        # 7. Apply atmospheric extinction correction (ASTAP convention)
        # Following ASTAP: zenith is reference point where extinction = 0
        # Only ADDITIONAL extinction below zenith is added: 0.28 * (airmass - 1)
        # This allows comparing measurements at different altitudes
        extinction_for_altitude = self._atmospheric_extinction(altitude_deg)  # 0.28*(airmass-1)

        # Main SQM value: no extinction correction (raw measurement)
        sqm_final = sqm_uncorrected
        # Altitude-corrected value: adds extinction for altitude comparison
        sqm_altitude_corrected = sqm_uncorrected + extinction_for_altitude

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
            "n_stars_excluded_saturation": n_saturated,
            "saturation_threshold": saturation_threshold,
            "background_per_pixel": background_per_pixel,
            "background_method": "local_annulus",
            "pedestal": pedestal,
            "pedestal_source": self._determine_pedestal_source(),
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
            "sqm_uncorrected": sqm_uncorrected,
            "altitude_deg": altitude_deg,
            "extinction_for_altitude": extinction_for_altitude,
            "sqm_final": sqm_final,
            "sqm_altitude_corrected": sqm_altitude_corrected,
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
            f"raw={sqm_uncorrected:.2f}, ext_alt={extinction_for_altitude:.2f}, "
            f"final={sqm_final:.2f}, alt_corr={sqm_altitude_corrected:.2f}"
        )

        return sqm_final, details
