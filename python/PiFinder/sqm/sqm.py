import logging
import math
from typing import Tuple, Dict, List, Optional

import numpy as np

from . import color_index
from . import gaia_ref
from .noise_floor import NoiseFloorEstimator

logger = logging.getLogger("Solver")

# The colour term V - T*(B-V) is linear only over the B-V range it was fitted
# on (~0 to ~1). Clamp lookups so very red giants aren't over-corrected.
BV_CLAMP_MIN = -0.5
BV_CLAMP_MAX = 1.2


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

    # Zero-point stars are taken from this catalog-magnitude band (see
    # _calculate_mzero); outside-band stars still get per-star mzeros for
    # diagnostics but don't vote on the frame zero point.
    MZERO_MAG_BAND = (3.5, 6.5)
    MZERO_MAG_BAND_MIN_STARS = 5

    def __init__(
        self,
        camera_type: str = "imx296",
    ):
        """
        Initialize SQM calculator.

        Args:
            camera_type: Camera model (imx296, imx462, imx290, hq).
        """
        self.camera_type = camera_type
        # Keep one estimator for the calculator's lifetime so diagnostics and
        # its per-instance calibrated profile cannot drift apart. Periodic
        # zero-exposure requests are disabled: no runtime camera path services
        # that request; the explicit calibration wizard owns dark captures.
        self.noise_floor_estimator = NoiseFloorEstimator(
            camera_type=camera_type,
            enable_zero_sec_sampling=False,
        )
        self.profile = self.noise_floor_estimator.profile
        logger.info(
            f"SQM initialized (camera: {camera_type}, bias_offset: {self.profile.bias_offset})"
        )

    def _calc_field_parameters(
        self, fov_degrees: float, pixels_per_side: int = 512
    ) -> None:
        """Calculate field of view parameters.

        pixels_per_side is the side length of the image the photometry runs on
        (512 for the processed image, but e.g. 490/760 for a Bayer green channel).
        The per-pixel solid angle depends on it, so it must match the image.
        """
        self.fov_degrees = fov_degrees
        self.field_arcsec_squared = (fov_degrees * 3600) ** 2
        self.pixels_total = pixels_per_side**2
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
        exclusion_centroids=None,
    ) -> Tuple[list, list, int]:
        """
        Measure star flux with local background from annulus around each star.

        Args:
            image: Image array
            centroids: Star centroids to measure, shape (N, 2).
                       Each row is (row_idx, col_idx) = (y, x) to match numpy indexing.
                       This is the convention used by Tetra3 matched_centroids.
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

        # Exclusion disks: every *detected* star in the frame (matched or not)
        # is masked out of background annuli so neighbours cannot inflate the
        # local sky in dense fields. Radius: the photometry aperture.
        excl = (
            np.asarray(exclusion_centroids, dtype=np.float64)
            if exclusion_centroids is not None and len(exclusion_centroids) > 0
            else None
        )
        excl_r2 = float(aperture_radius**2)

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

            # Mask out every known star (except this one) from the annulus.
            if excl is not None:
                near = excl[
                    (np.abs(excl[:, 0] - cy) <= annulus_outer_radius + aperture_radius)
                    & (
                        np.abs(excl[:, 1] - cx)
                        <= annulus_outer_radius + aperture_radius
                    )
                ]
                for ey, ex in near:
                    if (ey - cy) ** 2 + (ex - cx) ** 2 <= 4.0:
                        continue  # this star itself
                    annulus_mask &= ((x_grid - ex) ** 2 + (y_grid - ey) ** 2) > excl_r2

            # Measure local background from the cleaned annulus: median after
            # one sigma-clip pass (backstop for stars the detector missed).
            annulus_pixels = image_patch[annulus_mask]
            if len(annulus_pixels) >= 8:
                med = np.median(annulus_pixels)
                sig = np.std(annulus_pixels)
                kept = annulus_pixels[np.abs(annulus_pixels - med) <= 3.0 * sig]
                local_bg_per_pixel = float(np.median(kept) if len(kept) >= 8 else med)
            elif len(annulus_pixels) > 0:
                local_bg_per_pixel = float(np.median(annulus_pixels))
            else:
                # Exclusion emptied the annulus (extremely dense field):
                # fall back to the uncleaned annulus median.
                raw_annulus = image_patch[
                    (dist_squared > annulus_inner_r2)
                    & (dist_squared <= annulus_outer_r2)
                ]
                local_bg_per_pixel = (
                    float(np.median(raw_annulus))
                    if len(raw_annulus) > 0
                    else float(np.median(image))
                )

            # Check for saturation in aperture
            aperture_pixels = image_patch[aperture_mask]
            max_aperture_pixel = (
                np.max(aperture_pixels) if len(aperture_pixels) > 0 else 0
            )

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
        Calculate a robust photometric zero point from calibrated stars.

        For point sources: mzero = catalog_mag + 2.5 × log10(total_flux_ADU)

        This zero point allows converting any ADU measurement to magnitudes:
            mag = mzero - 2.5 × log10(flux_ADU)

        Uses the median over stars, not a flux-weighted mean: a flux-weighted
        mean hands most of the vote to the 1-2 brightest stars, which are
        exactly the ones prone to systematic error (sensor nonlinearity near
        saturation, colour-term extrapolation on very red giants). One such
        star can drag a weighted mzero by half a magnitude; the median is
        unmoved.

        The median is taken over stars inside a fixed catalog-magnitude band
        (MZERO_MAG_BAND) when enough are present: per-star mzero has a mild
        magnitude dependence, and the set of matched stars shifts several
        magnitudes across the auto-exposure range, so an all-star median
        drifts ~0.1-0.2 mag/decade of exposure. A fixed band samples the same
        physical stars at every exposure (measured: drift -0.10 -> -0.01
        mag/decade on the imx462 sweep ramps). Falls back to all stars when
        the field is too poor for the band. A 3-MAD rejection inside that
        selected population removes catalog, blend, and residual colour
        outliers without changing the exposure-invariant selection rule.

        Args:
            star_fluxes: Background-subtracted star fluxes (ADU)
            star_mags: Catalog magnitudes for matched stars

        Returns:
            Tuple of (median_mzero, list_of_individual_mzeros)
            Note: The mzeros list will contain None for stars with invalid flux
        """
        mzeros: list[Optional[float]] = []
        valid: list[tuple[int, float, float]] = []  # index, mzero, magnitude

        for index, (flux, mag) in enumerate(zip(star_fluxes, star_mags)):
            if flux <= 0 or not np.isfinite(flux) or not np.isfinite(mag):
                logger.debug(f"Skipping star with flux={flux:.1f} ADU (mag={mag:.2f})")
                mzeros.append(None)  # Keep array aligned
                continue

            # Calculate zero point: ZP = m + 2.5*log10(F)
            mzero = mag + 2.5 * np.log10(flux)
            mzeros.append(mzero)
            valid.append((index, mzero, mag))

        if len(valid) == 0:
            logger.error("No valid stars for mzero calculation")
            return None, mzeros

        lo, hi = self.MZERO_MAG_BAND
        in_band = [entry for entry in valid if lo <= entry[2] <= hi]
        pool = in_band if len(in_band) >= self.MZERO_MAG_BAND_MIN_STARS else valid
        values = np.asarray([entry[1] for entry in pool], dtype=np.float64)
        median = float(np.median(values))
        deviations = np.abs(values - median)
        mad = float(np.median(deviations))
        if len(values) >= 3:
            if mad > 0:
                robust_sigma = 1.4826 * mad
                inliers = deviations <= 3.0 * robust_sigma
            else:
                # A majority of identical values gives MAD=0. Retain that
                # consensus and reject any isolated nonzero deviation.
                inliers = deviations == 0
            for entry, is_inlier in zip(pool, inliers):
                if not is_inlier:
                    mzeros[entry[0]] = None
            values = values[inliers]

        return float(np.median(values)), mzeros

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
                        f"CRITICAL overlap: stars {i} and {j} (d={distance:.1f}px < {2 * aperture_radius}px)"
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
        if self.noise_floor_estimator.dark_current_calibrated:
            return "calibrated_bias_plus_mean_dark_current"
        return "factory_bias_offset"

    def calculate(
        self,
        centroids: list,
        solution: dict,
        image: np.ndarray,
        exposure_sec: float,
        altitude_deg: Optional[float] = None,
        aperture_radius: int = 5,
        annulus_inner_radius: int = 10,
        annulus_outer_radius: int = 18,
        correct_overlaps: bool = False,
        saturation_threshold: int = 250,
        pedestal_override: Optional[float] = None,
        color_coefficient: Optional[float] = None,
        image_pixels_per_side: Optional[int] = None,
        mzero_correction: float = 0.0,
    ) -> Tuple[Optional[float], Dict]:
        """
        Calculate SQM (Sky Quality Meter) value using local background annuli.

        Args:
            centroids: All detected centroids in the frame, (y, x) rows in
                the SAME pixel space as `image`; masked out of background
                annuli so neighbouring stars cannot inflate the local sky.
                Pass None/[] to skip exclusion.
            solution: Tetra3 solution dict with 'FOV', 'matched_centroids', 'matched_stars'.
                      Note: matched_centroids uses (row, col) = (y, x) convention to match
                      numpy array indexing (image[row, col]).
            image: Image array (uint8 or float)
            exposure_sec: Exposure time in seconds (required for noise floor estimation)
            altitude_deg: Altitude of field center for optional comparison-only
                extinction correction. ``None`` means altitude is unavailable.
            aperture_radius: Radius for star photometry in pixels (default: 5)
            annulus_inner_radius: Inner radius of background annulus in pixels (default: 10)
            annulus_outer_radius: Outer radius of background annulus in pixels (default: 18)
            correct_overlaps: If True, exclude stars with overlapping apertures/annuli (default: False)
            saturation_threshold: Pixel value threshold for saturation detection (default: 250)
            pedestal_override: If given, use this total black-level pedestal instead
                of ``bias + mean dark current`` (e.g. a per-frame estimate).
            color_coefficient: If given (and non-zero), correct each star's catalog V
                magnitude to the sensor passband via mag_eff = V - T*(B-V), with B-V
                looked up by HIP from solution['matched_catID']. Defaults to the
                camera profile's color_coefficient when None; pass 0.0 to disable.
            image_pixels_per_side: Side length of `image` (defaults to image.shape).
                Controls the per-pixel solid angle; must match the photometry image.
            mzero_correction: Additive aperture (wing-loss) correction to mzero,
                ``-2.5*log10(enclosed_fraction)`` from a WingEstimator (default 0).

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
        if image.ndim != 2 or image.size == 0:
            logger.error("SQM requires a non-empty two-dimensional image")
            return None, {}

        # Extract FOV from solution
        if "FOV" not in solution:
            logger.error("Solution missing 'FOV' field")
            return None, {}

        fov_estimate = solution["FOV"]
        pixels_per_side = (
            image_pixels_per_side
            if image_pixels_per_side is not None
            else int(image.shape[0])
        )
        self._calc_field_parameters(fov_estimate, pixels_per_side)

        # Validate solution has matched stars
        if "matched_centroids" not in solution or "matched_stars" not in solution:
            logger.error("Solution missing matched_centroids or matched_stars")
            return None, {}

        matched_centroids = np.array(solution["matched_centroids"])
        matched_stars = solution["matched_stars"]

        if len(matched_centroids) == 0 or len(matched_stars) == 0:
            logger.error("No matched stars in solution")
            return None, {}
        if len(matched_centroids) != len(matched_stars):
            logger.error(
                "Matched centroid/star length mismatch: %d != %d",
                len(matched_centroids),
                len(matched_stars),
            )
            return None, {}

        _noise_floor, noise_floor_details = (
            self.noise_floor_estimator.estimate_noise_floor(
                image=image,
                exposure_sec=exposure_sec,
            )
        )

        # Don't swap - centroids are already in (row, col) = (y, x) format
        matched_centroids_arr = matched_centroids
        star_mags = [s[2] for s in matched_stars]  # Johnson V catalog magnitudes

        # Colour term: catalog is Johnson V but flux is in the sensor passband.
        # Correct to mag_eff = V - T*(B-V) per star (B-V looked up by HIP).
        color_coef = (
            color_coefficient
            if color_coefficient is not None
            else self.profile.color_coefficient
        )
        star_bv: Optional[List[float]] = None
        star_gaia = None
        if self.profile.reference_band == "gaia_g" and "matched_catID" in solution:
            star_gaia = gaia_ref.get_g_bprp(solution["matched_catID"])
        if color_coef and "matched_catID" in solution:
            star_bv = list(color_index.get_bv(solution["matched_catID"]))

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
                if star_bv is not None:
                    star_bv = [star_bv[i] for i in valid_indices]

                logger.info(
                    f"Overlap correction: excluded {n_stars_excluded}/{n_stars_original} stars "
                    f"({n_stars_excluded * 100 // n_stars_original}%), using {len(valid_indices)} stars"
                )

                if len(valid_indices) < 3:
                    logger.warning(
                        f"Too few stars remaining after overlap correction ({len(valid_indices)})"
                    )
                    return None, {}

        # Pedestal = static bias plus *measured* mean dark signal. Factory
        # dark-current values are unverified engineering estimates and the
        # shipped sensor offsets were validated without subtracting them, so
        # preserve the bias-only zero-touch path until a device calibration has
        # measured the rate. Read noise is zero-mean and is never subtracted.
        dark_current_rate = self.profile.dark_current_rate or 0.0
        dark_current_model_contribution = dark_current_rate * exposure_sec
        dark_current_contribution = (
            dark_current_model_contribution
            if self.noise_floor_estimator.dark_current_calibrated
            else 0.0
        )
        pedestal = (
            pedestal_override
            if pedestal_override is not None
            else self.profile.bias_offset + dark_current_contribution
        )

        # Default to 0.0 so an incomplete calibration cannot crash SQM.
        read_noise = self.profile.read_noise_adu or 0.0
        temporal_noise = read_noise

        logger.debug(
            f"Calibration: pedestal={pedestal:.1f} ADU "
            f"({self._determine_pedestal_source()}), "
            f"read_noise={read_noise:.2f}, dark_current={dark_current_contribution:.2f} "
            f"(model={dark_current_model_contribution:.2f}, "
            f"rate={dark_current_rate:.3f} ADU/s × {exposure_sec:.2f}s), "
            f"temporal_noise={temporal_noise:.2f}"
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
                exclusion_centroids=centroids,
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

        # A sub-ADU result is unresolved at the detector's quantization/noise
        # scale. Reject it rather than manufacturing a plausible value by
        # clamping the background to 1 ADU.
        if background_corrected <= 1.0:
            logger.warning(
                f"Background unresolved after pedestal correction "
                f"({background_per_pixel:.2f} - {pedestal:.2f} = {background_corrected:.2f})"
            )
            return None, {
                "background_per_pixel": background_per_pixel,
                "background_corrected": background_corrected,
                "pedestal": pedestal,
                "pedestal_source": (
                    "per_frame_estimate"
                    if pedestal_override is not None
                    else self._determine_pedestal_source()
                ),
                "failure_reason": "background_not_resolved_above_pedestal",
                "noise_floor_details": noise_floor_details,
                "exposure_sec": exposure_sec,
            }

        # 4. Calculate photometric zero point.
        # Reference band per sensor: bare sensors (reference_band "gaia_g")
        # use Gaia G with a small BP-RP trim -- G's 330-1050 nm passband is
        # nearly the sensor's own, so star scatter drops ~25% vs Johnson V
        # (see gaia_ref). IR-cut sensors stay on Hipparcos V with the linear
        # B-V term, which is their native band. Stars missing from the Gaia
        # table fall back per star to the V path. B-V is clamped to the range
        # the linear colour term was fitted on -- extrapolating T*(B-V) to
        # very red giants (B-V > 1.2) over-corrects them by up to a magnitude.
        n_color_corrected = 0
        use_gaia = star_gaia is not None
        if use_gaia or (star_bv is not None and color_coef):
            effective_mags = []
            for i, v_mag in enumerate(star_mags):
                if use_gaia and math.isfinite(star_gaia[i][0]):
                    g_mag, bprp = star_gaia[i]
                    trim = color_coef * bprp if math.isfinite(bprp) else 0.0
                    effective_mags.append(g_mag - trim)
                    n_color_corrected += 1
                    continue
                bv = star_bv[i] if star_bv is not None else None
                if color_coef and bv is not None and math.isfinite(bv):
                    bv_clamped = min(max(bv, BV_CLAMP_MIN), BV_CLAMP_MAX)
                    effective_mags.append(v_mag - color_coef * bv_clamped)
                    n_color_corrected += 1
                else:
                    effective_mags.append(v_mag)
        else:
            effective_mags = star_mags

        mzero, mzeros = self._calculate_mzero(star_fluxes, effective_mags)

        if mzero is None:
            return None, {}

        # Aperture (wing-loss) correction: the finite aperture misses PSF-wing
        # flux, biasing mzero low. The caller supplies -2.5*log10(f) from a
        # rolling WingEstimator; f is the aperture's enclosed-flux fraction.
        mzero += mzero_correction

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
        extinction_for_altitude = (
            self._atmospheric_extinction(altitude_deg)
            if altitude_deg is not None
            else None
        )

        # Sky-passband offset: the colour term matches the stars to the sensor
        # passband, so the sky is measured in that passband too. A bare sensor
        # sees NIR sky emission a V-band meter doesn't; this per-sensor
        # constant converts back to the meter's V-band scale. See
        # CameraProfile.sqm_band_offset and docs/adr/0020.
        band_offset = self.profile.sqm_band_offset

        # Main SQM value: no extinction correction (raw measurement)
        sqm_final = sqm_uncorrected + band_offset
        # Altitude-corrected value: adds extinction for altitude comparison
        sqm_altitude_corrected = (
            sqm_uncorrected + band_offset + extinction_for_altitude
            if extinction_for_altitude is not None
            else None
        )

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
            "pedestal_source": (
                "per_frame_estimate"
                if pedestal_override is not None
                else self._determine_pedestal_source()
            ),
            "color_coefficient": color_coef or 0.0,
            "n_color_corrected": n_color_corrected,
            "pixels_per_side": pixels_per_side,
            "mzero_correction": mzero_correction,
            "sqm_band_offset": band_offset,
            "read_noise_adu": read_noise,
            "dark_current_rate": self.profile.dark_current_rate,
            "dark_current_contribution": dark_current_contribution,
            "dark_current_model_contribution": dark_current_model_contribution,
            "dark_current_calibrated": (
                self.noise_floor_estimator.dark_current_calibrated
            ),
            "temporal_noise": temporal_noise,
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
            "noise_floor_details": noise_floor_details,
        }

        logger.debug(
            f"SQM: mzero={mzero:.2f}±{np.std(valid_mzeros_for_stats):.2f}, "
            f"bg={background_flux_density:.6f} ADU/arcsec², pedestal={pedestal:.2f}, "
            f"raw={sqm_uncorrected:.2f}, ext_alt={extinction_for_altitude}, "
            f"final={sqm_final:.2f}, alt_corr={sqm_altitude_corrected}"
        )

        return sqm_final, details
