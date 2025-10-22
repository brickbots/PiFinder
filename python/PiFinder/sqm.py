import numpy as np
import logging
from typing import Tuple, Dict, Optional

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

    def __init__(self):
        super()

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
        y, x = np.ogrid[:height, :width]
        star_fluxes = []
        local_backgrounds = []

        for cy, cx in centroids:  # centroids are in (y, x) format after swap
            # Create aperture mask for star flux
            aperture_mask = (x - cx) ** 2 + (y - cy) ** 2 <= aperture_radius**2

            # Create annulus mask for local background
            dist_squared = (x - cx) ** 2 + (y - cy) ** 2
            annulus_mask = (dist_squared > annulus_inner_radius**2) & (
                dist_squared <= annulus_outer_radius**2
            )

            # Measure local background from annulus (median for robustness)
            annulus_pixels = image[annulus_mask]
            if len(annulus_pixels) > 0:
                local_bg_per_pixel = float(np.median(annulus_pixels))
            else:
                # this is impossible
                local_bg_per_pixel = float(np.median(image))
                logger.warning(
                    f"Star at ({cx:.0f},{cy:.0f}) has no annulus pixels, using global median"
                )

            # Total flux in aperture (includes background)
            total_flux = np.sum(image[aperture_mask])

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
        """
        mzeros = []

        for flux, mag in zip(star_fluxes, star_mags):
            if flux <= 0:
                logger.warning(
                    f"Skipping star with flux={flux:.1f} ADU (mag={mag:.2f})"
                )
                continue

            # Calculate zero point: ZP = m + 2.5*log10(F)
            mzero = mag + 2.5 * np.log10(flux)
            mzeros.append(mzero)

        if len(mzeros) == 0:
            logger.error("No valid stars for mzero calculation")
            return None, []

        return float(np.mean(mzeros)), mzeros

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
        bias_image: Optional[np.ndarray] = None,
        altitude_deg: float = 90.0,
        aperture_radius: int = 5,
        annulus_inner_radius: int = 6,
        annulus_outer_radius: int = 14,
        pedestal: float = 0.0,
    ) -> Tuple[Optional[float], Dict]:
        """
        Calculate SQM (Sky Quality Meter) value using local background annuli.

        Args:
            centroids: All detected centroids (unused, kept for compatibility)
            solution: Tetra3 solution dict with 'FOV', 'matched_centroids', 'matched_stars'
            image: Image array (uint8 or float)
            bias_image: Optional bias/dark frame for pedestal calculation (default: None)
            altitude_deg: Altitude of field center for extinction correction (default: 90 = zenith)
            aperture_radius: Radius for star photometry in pixels (default: 5)
            annulus_inner_radius: Inner radius of background annulus in pixels (default: 6)
            annulus_outer_radius: Outer radius of background annulus in pixels (default: 14)
            pedestal: Bias/pedestal level to subtract from background (default: 0)
                     If bias_image is provided and pedestal=0, pedestal is calculated from bias_image

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
                annulus_outer_radius=14
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

        # 0. Calculate pedestal from bias image if provided
        if bias_image is not None and pedestal == 0.0:
            pedestal = float(np.median(bias_image))
            logger.debug(f"Pedestal from bias: {pedestal:.2f} ADU")
        elif pedestal > 0:
            logger.debug(f"Using pedestal: {pedestal:.2f} ADU")

        # 1. Measure star fluxes with local background from annulus
        star_fluxes, local_backgrounds = self._measure_star_flux_with_local_background(
            image,
            matched_centroids_arr,
            aperture_radius,
            annulus_inner_radius,
            annulus_outer_radius,
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

        # Assemble diagnostics
        details = {
            "fov_deg": fov_estimate,
            "n_centroids": len(centroids) if centroids else 0,
            "n_matched_stars": len(matched_stars),
            "background_per_pixel": background_per_pixel,
            "background_method": "local_annulus",
            "pedestal": pedestal,
            "pedestal_source": "bias_image"
            if bias_image is not None
            else ("manual" if pedestal > 0 else "none"),
            "background_corrected": background_corrected,
            "background_flux_density": background_flux_density,
            "arcsec_per_pixel": np.sqrt(self.arcsec_squared_per_pixel),
            "aperture_radius": aperture_radius,
            "annulus_inner_radius": annulus_inner_radius,
            "annulus_outer_radius": annulus_outer_radius,
            "mzero": mzero,
            "mzero_std": float(np.std(mzeros)),
            "mzero_range": (float(np.min(mzeros)), float(np.max(mzeros))),
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
            f"SQM: mzero={mzero:.2f}±{np.std(mzeros):.2f}, "
            f"bg={background_flux_density:.6f} ADU/arcsec², pedestal={pedestal:.2f}, "
            f"raw={sqm_raw:.2f}, extinction={extinction_correction:.2f}, final={sqm_final:.2f}"
        )

        return sqm_final, details
