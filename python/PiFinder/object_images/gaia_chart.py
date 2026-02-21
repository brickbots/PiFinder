#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Gaia star chart generator for objects without DSS/POSS images

Generates on-demand star charts using HEALPix-indexed Gaia star catalog.
Features:
- Equipment-aware FOV and magnitude limits
- Stereographic projection (matching chart.py)
- Center marker for target object
- Info overlays (FOV, magnification, eyepiece)
- Caching for performance
"""

import logging
from pathlib import Path
from typing import Generator, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from PiFinder import utils
from PiFinder.object_images.star_catalog import CatalogState, GaiaStarCatalog
from PiFinder.object_images.image_utils import (
    pad_to_display_resolution,
    add_image_overlays,
)

logger = logging.getLogger("PiFinder.GaiaChart")

# Global singleton instance to ensure same catalog across all uses
_gaia_chart_generator_instance = None


def get_gaia_chart_generator(config, shared_state):
    """Get or create the global chart generator singleton"""
    global _gaia_chart_generator_instance
    logger.debug(
        f">>> get_gaia_chart_generator() called, instance exists: {_gaia_chart_generator_instance is not None}"
    )
    if _gaia_chart_generator_instance is None:
        logger.info(">>> Creating new GaiaChartGenerator instance...")
        _gaia_chart_generator_instance = GaiaChartGenerator(config, shared_state)
        logger.info(
            f">>> GaiaChartGenerator created, state: {_gaia_chart_generator_instance.get_catalog_state()}"
        )
    else:
        logger.debug(
            f">>> Returning existing instance, state: {_gaia_chart_generator_instance.get_catalog_state()}"
        )
    return _gaia_chart_generator_instance


class GaiaChartGenerator:
    """
    Generate on-demand star charts with equipment-aware settings

    Usage:
        gen = GaiaChartGenerator(config, shared_state)
        image = gen.generate_chart(catalog_object, (128, 128), burn_in=True)
    """

    def __init__(self, config, shared_state):
        """
        Initialize chart generator

        Args:
            config: PiFinder config object
            shared_state: Shared state object
        """
        logger.info(">>> GaiaChartGenerator.__init__() called")
        self.config = config
        self.shared_state = shared_state
        self.catalog = None
        self.chart_cache = {}
        self._lm_cache = None  # Cache (sqm, eyepiece_id, lm) to avoid recalculation

        # Initialize font for text overlays
        font_path = Path(Path.cwd(), "../fonts/RobotoMonoNerdFontMono-Bold.ttf")
        try:
            self.small_font = ImageFont.truetype(str(font_path), 8)
        except Exception as e:
            logger.warning(f"Failed to load font {font_path}: {e}, using default")
            self.small_font = ImageFont.load_default()

    def get_catalog_state(self) -> CatalogState:
        """Get current catalog loading state"""
        if self.catalog is None:
            return CatalogState.NOT_LOADED
        return self.catalog.state

    def ensure_catalog_loading(self):
        """
        Ensure catalog is loading or loaded
        Triggers background load if needed
        """
        logger.debug(
            f">>> ensure_catalog_loading() called, catalog is None: {self.catalog is None}"
        )

        if self.catalog is None:
            logger.info(">>> Calling initialize_catalog()...")
            self.initialize_catalog()
            logger.info(f">>> initialize_catalog() done, state: {self.catalog.state}")

        if self.catalog.state == CatalogState.NOT_LOADED:
            # Trigger background load
            location = self.shared_state.location()
            sqm = self.shared_state.sqm()

            observer_lat = location.lat if location and location.lock else None
            limiting_mag = self.get_limiting_magnitude(sqm)

            logger.info(
                f">>> Starting background catalog load: lat={observer_lat}, mag_limit={limiting_mag:.1f}"
            )
            self.catalog.start_background_load(observer_lat, limiting_mag)
            logger.info(
                f">>> start_background_load() called, new state: {self.catalog.state}"
            )

    def initialize_catalog(self):
        """Create catalog instance (doesn't load data yet)"""
        catalog_path = Path(utils.data_dir, "gaia_stars")
        logger.info(f">>> initialize_catalog() - catalog_path: {catalog_path}")

        # Check if catalog exists before initializing
        metadata_file = catalog_path / "metadata.json"
        if not metadata_file.exists():
            logger.warning(f"Gaia star catalog not found at {catalog_path}")
            logger.warning(
                "To build catalog, run: python -m PiFinder.catalog_tools.gaia_downloader --mag-limit 12 --output /tmp/gaia.csv"
            )
            logger.warning(
                "Then: python -m PiFinder.catalog_tools.healpix_builder --input /tmp/gaia.csv --output {}/astro_data/gaia_stars".format(
                    Path.home() / "PiFinder"
                )
            )

        logger.info(">>> Creating GaiaStarCatalog instance...")
        import time

        t0 = time.time()
        self.catalog = GaiaStarCatalog(str(catalog_path))
        t_init = (time.time() - t0) * 1000
        logger.info(f">>> GaiaStarCatalog.__init__() took {t_init:.1f}ms")
        logger.info(
            f">>> Catalog initialized: {catalog_path}, state: {self.catalog.state}"
        )

    def generate_chart(
        self,
        catalog_object,
        resolution: Tuple[int, int],
        burn_in: bool = True,
        display_class=None,
        roll=None,
    ) -> Generator[Optional[Image.Image], None, None]:
        """
        Generate chart for object at current equipment settings

        Args:
            catalog_object: CompositeObject with RA/Dec
            resolution: (width, height) tuple
            burn_in: Add FOV/mag/eyepiece overlays

        Returns:
            PIL Image in RGB (red colorspace), or None if catalog not ready
        """
        logger.info(f">>> generate_chart() ENTRY: object={catalog_object.display_name}")

        # Ensure catalog is loading
        self.ensure_catalog_loading()

        # Check state
        if self.catalog.state != CatalogState.READY:
            logger.info(
                f">>> Chart generation skipped: catalog state = {self.catalog.state}"
            )
            yield None
            return

        logger.info(">>> Catalog state is READY, proceeding...")

        # Check cache
        cache_key = self.get_cache_key(catalog_object)
        if cache_key in self.chart_cache:
            # Return cached base image, adding overlays if needed
            # Crosshair will be added by add_pulsating_crosshair() each frame
            logger.debug(f"Chart cache HIT for {cache_key}")
            cached_image = self.chart_cache[cache_key]

            # Make a copy to avoid modifying cached image
            image = cached_image.copy()

            # ALWAYS pad to display resolution when display_class is provided
            if display_class is not None:
                image = pad_to_display_resolution(image, display_class)

            # Add overlays if burn_in requested
            if burn_in and display_class is not None:
                # Add FOV circle
                draw = ImageDraw.Draw(image)
                width, height = display_class.resolution
                cx, cy = width / 2.0, height / 2.0
                radius = min(width, height) / 2.0 - 2
                marker_color = display_class.colors.get(64)
                bbox = [cx - radius, cy - radius, cx + radius, cy + radius]
                draw.ellipse(bbox, outline=marker_color, width=1)

                # Add text overlays
                sqm = self.shared_state.sqm()
                mag_limit_calculated = self.get_limiting_magnitude(sqm)
                equipment = self.config.equipment
                fov = equipment.calc_tfov()
                mag = equipment.calc_magnification()

                image = add_image_overlays(
                    image,
                    display_class,
                    fov,
                    mag,
                    equipment.active_eyepiece,
                    burn_in=True,
                    limiting_magnitude=mag_limit_calculated,
                )

            yield image
            return

        # Get equipment settings
        equipment = self.config.equipment
        fov = equipment.calc_tfov()
        if fov <= 0:
            fov = 10.0  # Default fallback

        mag = equipment.calc_magnification()
        if mag <= 0:
            mag = 50.0  # Default fallback

        logger.info(
            f">>> Chart Generation: object={catalog_object.display_name}, center=({catalog_object.ra:.4f}, {catalog_object.dec:.4f}), fov={fov:.4f}°, mag={mag:.1f}x, eyepiece={equipment.active_eyepiece}"
        )

        sqm = self.shared_state.sqm()
        mag_limit_calculated = self.get_limiting_magnitude(sqm)
        # For query, cap at catalog max
        mag_limit_query = min(mag_limit_calculated, 17.0)

        logger.info(
            f">>> Mag Limit: calculated={mag_limit_calculated:.2f}, query={mag_limit_query:.2f}, sqm={sqm.value if sqm else 'None'}"
        )

        # Query stars PROGRESSIVELY (bright to faint)
        # This is a generator that yields partial results as each magnitude band loads
        import time

        t0 = time.time()

        logger.info(
            f"Chart for {catalog_object.catalog_code}{catalog_object.sequence}: "
            f"Center RA={catalog_object.ra:.4f}° Dec={catalog_object.dec:.4f}°, "
            f"FOV={fov:.4f}°, Roll={roll if roll is not None else 0:.1f}°, "
            f"Starting PROGRESSIVE loading (mag_limit={mag_limit_query:.1f})"
        )

        # Use progressive loading to show bright stars first
        stars_generator = self.catalog.get_stars_for_fov_progressive(
            ra_deg=catalog_object.ra,
            dec_deg=catalog_object.dec,
            fov_deg=fov,
            mag_limit=mag_limit_query,
        )

        # Calculate rotation angle for roll / telescope orientation
        # Reflectors (Newtonian, SCT) invert the image 180°
        # Refractors typically don't invert (depends on eyepiece design)
        # Use obstruction as heuristic: obstruction > 0 = reflector
        telescope = equipment.active_telescope
        if telescope and telescope.obstruction_perc > 0:
            # Reflector telescope (Newtonian, SCT) - inverts image
            image_rotate = 180
        else:
            # Refractor or unknown - no base rotation
            image_rotate = 0

        if roll is not None:
            image_rotate += roll

        # Get flip/flop settings from telescope config
        flip_image = telescope.flip_image if telescope else False
        flop_image = telescope.flop_image if telescope else False

        # Progressive rendering: Yield image after each magnitude band loads
        # Re-render all stars each time (simple, correct, fast enough)
        final_image = None
        iteration_count = 0

        logger.info(">>> Starting star generator loop...")
        for stars, is_complete in stars_generator:
            iteration_count += 1
            logger.info(
                f">>> Star generator iteration {iteration_count}: got {len(stars)} stars, complete={is_complete}"
            )
            t_render_start = time.time()

            # Render ALL stars from scratch (base image without overlays)
            base_image = self.render_chart(
                stars,
                catalog_object.ra,
                catalog_object.dec,
                fov,
                resolution,
                mag,
                image_rotate,
                mag_limit_query,
                flip_image=flip_image,
                flop_image=flop_image,
            )

            # Store base image for caching (without overlays)
            final_base_image = base_image

            # Make a copy for display (don't modify the base image)
            display_image = base_image.copy()

            # ALWAYS pad to display resolution when display_class is provided
            if display_class is not None:
                display_image = pad_to_display_resolution(display_image, display_class)

            # Add overlays if burn_in requested
            if burn_in and display_class is not None:
                # Add FOV circle BEFORE text overlays so it appears behind them
                draw = ImageDraw.Draw(display_image)
                width, height = display_class.resolution
                cx, cy = width / 2.0, height / 2.0
                radius = min(width, height) / 2.0 - 2  # Leave 2 pixel margin
                marker_color = display_class.colors.get(64)  # Subtle but visible
                bbox = [cx - radius, cy - radius, cx + radius, cy + radius]
                draw.ellipse(bbox, outline=marker_color, width=1)

                # Add text overlays (using shared utility)
                display_image = add_image_overlays(
                    display_image,
                    display_class,
                    fov,
                    mag,
                    equipment.active_eyepiece,
                    burn_in=True,
                    limiting_magnitude=mag_limit_calculated,  # Pass uncapped value for display
                )

            t_render_end = time.time()
            logger.info(
                f"PROGRESSIVE: Total render time {(t_render_end - t_render_start) * 1000:.1f}ms "
                f"(complete={is_complete}, total_stars={len(stars)})"
            )

            # Yield display image (with or without overlays)
            if not is_complete:
                yield display_image
            # If complete, will yield final image after loop

        # Final yield with complete image
        t1 = time.time()
        logger.info(
            f">>> Star generator loop complete: {iteration_count} iterations, {(t1 - t0) * 1000:.1f}ms total"
        )

        if iteration_count == 0:
            logger.warning(
                f">>> WARNING: Star generator yielded NO results! FOV={fov:.4f}°, center=({catalog_object.ra:.4f}, {catalog_object.dec:.4f})"
            )
            # Generate blank chart (no stars) - this is the base image
            final_base_image = self.render_chart(
                np.array([]).reshape(0, 3),  # Empty star array
                catalog_object.ra,
                catalog_object.dec,
                fov,
                resolution,
                mag,
                image_rotate,
                mag_limit_query,
                flip_image=flip_image,
                flop_image=flop_image,
            )

        # Cache base image (without overlays) so it can be reused
        if "final_base_image" in locals() and final_base_image is not None:
            self.chart_cache[cache_key] = final_base_image
            if len(self.chart_cache) > 10:
                # Remove oldest
                oldest = next(iter(self.chart_cache))
                del self.chart_cache[oldest]

            # Create final display image
            final_display_image = final_base_image.copy()

            # ALWAYS pad to display resolution when display_class is provided
            if display_class is not None:
                final_display_image = pad_to_display_resolution(
                    final_display_image, display_class
                )

            # Add overlays if burn_in requested
            if burn_in and display_class is not None:
                # Add FOV circle
                draw = ImageDraw.Draw(final_display_image)
                width, height = display_class.resolution
                cx, cy = width / 2.0, height / 2.0
                radius = min(width, height) / 2.0 - 2
                marker_color = display_class.colors.get(64)
                bbox = [cx - radius, cy - radius, cx + radius, cy + radius]
                draw.ellipse(bbox, outline=marker_color, width=1)

                # Add overlays
                final_display_image = add_image_overlays(
                    final_display_image,
                    display_class,
                    fov,
                    mag,
                    equipment.active_eyepiece,
                    burn_in=True,
                    limiting_magnitude=mag_limit_calculated,
                )

            yield final_display_image
        else:
            yield None

    def render_chart(
        self,
        stars: np.ndarray,
        center_ra: float,
        center_dec: float,
        fov: float,
        resolution: Tuple[int, int],
        magnification: float = 50.0,
        rotation: float = 0.0,
        mag_limit: float = 17.0,
        flip_image: bool = False,
        flop_image: bool = False,
    ) -> Image.Image:
        """
        Render stars to PIL Image with center crosshair
        Uses fast vectorized stereographic projection

        Args:
            stars: Numpy array (N, 3) of (ra, dec, mag)
            center_ra: Center RA in degrees
            center_dec: Center Dec in degrees
            fov: Field of view in degrees
            resolution: (width, height) tuple
            magnification: Magnification factor
            rotation: Rotation angle in degrees (applied to coordinates)

        Returns:
            PIL Image in RGB (black background, red stars)
        """
        import time

        t_start = time.time()

        width, height = resolution
        # Use NumPy array for fast pixel operations
        image_array = np.zeros((height, width, 3), dtype=np.uint8)
        image = Image.new("RGB", (width, height), (0, 0, 0))
        ImageDraw.Draw(image)

        logger.info(
            f"Render Chart: {len(stars)} stars input, center=({center_ra:.4f}, {center_dec:.4f}), fov={fov:.4f}, res={resolution}"
        )

        # stars is already a numpy array (N, 3)
        stars_array = stars
        ra_arr = stars_array[:, 0]
        dec_arr = stars_array[:, 1]
        mag_arr = stars_array[:, 2]
        t2 = time.time()
        # logger.debug(f"  Array conversion: {(t2-t1)*1000:.1f}ms")

        # Fast stereographic projection (vectorized)
        # Convert degrees to radians
        center_ra_rad = np.radians(center_ra)
        center_dec_rad = np.radians(center_dec)
        ra_rad = np.radians(ra_arr)
        dec_rad = np.radians(dec_arr)

        # Use simple tangent plane projection (like POSS images)
        # This gives linear scaling: pixels_per_degree is constant
        # x = tan(ra - ra0) * cos(dec0)
        # y = (tan(dec) - tan(dec0)) / cos(ra - ra0)
        # Simplified for small angles: x ≈ (ra - ra0), y ≈ (dec - dec0)

        # Tangent plane projection (matches POSS images)
        # For small FOV (< 10°), linear approximation works well
        # IMPORTANT: Scale RA by CENTER declination, not individual star declinations
        cos_center_dec = np.cos(center_dec_rad)

        dra = ra_rad - center_ra_rad
        # Handle RA wrapping at 0°/360°
        dra = np.where(dra > np.pi, dra - 2 * np.pi, dra)
        dra = np.where(dra < -np.pi, dra + 2 * np.pi, dra)
        ddec = dec_rad - center_dec_rad

        # Project onto tangent plane
        # X: RA offset scaled by CENTER declination (matches POSS projection)
        # Y: Dec offset (linear)
        x_proj = dra * cos_center_dec
        y_proj = ddec

        # Simple linear pixel scale (matches POSS behavior)
        # fov degrees should map to width pixels
        pixel_scale = width / np.radians(fov)

        if fov < 0.2:  # Debug small FOVs
            logger.info(
                f">>> SMALL FOV DEBUG: fov={fov:.4f}°, pixel_scale={pixel_scale:.1f} px/rad"
            )
            if len(stars) > 0:
                logger.info(
                    f">>> Star RA range: [{np.min(ra_arr):.4f}, {np.max(ra_arr):.4f}]"
                )
                logger.info(
                    f">>> Star Dec range: [{np.min(dec_arr):.4f}, {np.max(dec_arr):.4f}]"
                )
                logger.info(f">>> Center: RA={center_ra:.4f}, Dec={center_dec:.4f}")

        # Convert to screen coordinates FIRST
        # Center of field should always be at width/2, height/2
        # IMPORTANT: Flip X-axis to match POSS image orientation
        # RA increases EASTWARD, which is to the LEFT when facing south
        # So positive RA offset should go to the LEFT (subtract from center)
        x_screen = width / 2.0 - x_proj * pixel_scale  # FLIPPED: RA increases to LEFT
        y_screen = height / 2.0 - y_proj * pixel_scale

        # Apply rotation to SCREEN coordinates (after scaling)
        # This avoids magnifying small numerical errors
        if rotation != 0:
            rot_rad = np.radians(rotation)
            cos_rot = np.cos(rot_rad)
            sin_rot = np.sin(rot_rad)

            # Rotate around center
            center_x = width / 2.0
            center_y = height / 2.0
            x_rel = x_screen - center_x
            y_rel = y_screen - center_y

            x_rotated = x_rel * cos_rot - y_rel * sin_rot
            y_rotated = x_rel * sin_rot + y_rel * cos_rot

            x_screen = x_rotated + center_x
            y_screen = y_rotated + center_y

        # Filter stars within screen bounds only (no circular mask)
        mask = (
            (x_screen >= 0) & (x_screen < width) & (y_screen >= 0) & (y_screen < height)
        )

        x_visible = x_screen[mask]
        y_visible = y_screen[mask]
        mag_visible = mag_arr[mask]
        ra_arr[mask]
        dec_arr[mask]

        logger.info(
            f"Render Chart: {len(x_visible)} stars visible on screen (of {len(stars)} total)"
        )

        # Scale brightness based on FIXED magnitude range
        # Use brightest visible star and LIMITING MAGNITUDE (not faintest loaded star)
        # This ensures consistent intensity scaling across progressive renders

        if len(mag_visible) == 0:
            intensities = np.array([])
        else:
            brightest_mag = np.min(mag_visible)
            faintest_mag = mag_limit  # Use limiting magnitude, not max(mag_visible)

            # Always use proper magnitude scaling
            # Linear scaling from brightest (255) to limiting magnitude (50)
            # Note: Lower magnitude = brighter star
            mag_range = faintest_mag - brightest_mag
            if mag_range < 0.01:
                mag_range = 0.01  # Avoid division by zero

            intensities = 255 - ((mag_visible - brightest_mag) / mag_range * 205)
            intensities = np.clip(intensities, 50, 255).astype(int)

        # Render stars: crosses for bright ones, single pixels for faint
        t3 = time.time()
        ix = np.round(x_visible).astype(int)
        iy = np.round(y_visible).astype(int)
        t4 = time.time()
        logger.debug(f"  Star projection: {(t3 - t2) * 1000:.1f}ms")

        for i in range(len(ix)):
            px = ix[i]
            py = iy[i]
            intensity = intensities[i]

            # Draw all stars as single pixels (no crosses)
            if 0 <= px < width and 0 <= py < height:
                # Use max to avoid bright blobs from overlapping stars
                image_array[py, px, 0] = max(image_array[py, px, 0], intensity)

        np.clip(image_array[:, :, 0], 0, 255, out=image_array[:, :, 0])
        t5 = time.time()
        logger.debug(f"  Star drawing loop: {(t5 - t4) * 1000:.1f}ms ({len(ix)} stars)")

        # Convert NumPy array back to PIL Image
        image = Image.fromarray(image_array, mode="RGB")
        t6 = time.time()
        logger.debug(f"  Image conversion: {(t6 - t5) * 1000:.1f}ms")

        # Apply telescope flip/flop transformations
        # flip_image = vertical flip (mirror top to bottom)
        # flop_image = horizontal flip (mirror left to right)
        if flip_image:
            image = image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        if flop_image:
            image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)

        # Note: Limiting magnitude display added by add_image_overlays() in generate_chart()
        # Note: Pulsating crosshair added separately via add_pulsating_crosshair()
        # so base chart can be cached

        t_end = time.time()
        logger.debug(f"  Total render time: {(t_end - t_start) * 1000:.1f}ms")

        # Tag image as a Gaia chart (not a loading placeholder)
        # This enables the correct marking menu in UIObjectDetails
        image.is_loading_placeholder = False  # type: ignore[attr-defined]

        return image

    def render_chart_incremental(
        self,
        new_stars: np.ndarray,
        base_image: Optional[Image.Image],
        center_ra: float,
        center_dec: float,
        fov: float,
        resolution: Tuple[int, int],
        magnification: float = 50.0,
        rotation: float = 0.0,
        mag_limit: float = 17.0,
        fixed_brightest_mag: Optional[float] = None,
        fixed_faintest_mag: Optional[float] = None,
    ) -> Image.Image:
        """
        Incrementally render new stars onto existing base image.
        Uses FIXED intensity scaling to maintain consistent brightness across bands.

        Args:
            new_stars: Only the new stars to render
            base_image: Existing image to draw onto (None for first render)
            center_ra: Center RA in degrees
            center_dec: Center Dec in degrees
            fov: Field of view in degrees
            resolution: (width, height) tuple
            magnification: Magnification factor
            rotation: Rotation angle in degrees
            mag_limit: Limiting magnitude
            fixed_brightest_mag: Brightest magnitude for intensity scaling (from first band)
            fixed_faintest_mag: Faintest magnitude for intensity scaling (limiting mag)

        Returns:
            PIL Image with new stars added
        """
        import time

        t_start = time.time()

        width, height = resolution

        # Start with base image or create new blank one
        if base_image is None:
            image_array = np.zeros((height, width, 3), dtype=np.uint8)
        else:
            image_array = np.array(base_image)

        logger.info(f"Render Chart INCREMENTAL: {len(new_stars)} new stars")

        if len(new_stars) == 0:
            return Image.fromarray(image_array, mode="RGB")

        # Use FIXED intensity scaling (established from first band + limiting mag)
        if fixed_brightest_mag is None or fixed_faintest_mag is None:
            # Fallback: calculate from new stars only
            new_mags = new_stars[:, 2]
            brightest_mag = np.min(new_mags)
            faintest_mag = np.max(new_mags)
            logger.warning(
                f"INCREMENTAL: No fixed scale provided, using fallback: {brightest_mag:.2f} to {faintest_mag:.2f}"
            )
        else:
            brightest_mag = fixed_brightest_mag
            faintest_mag = fixed_faintest_mag

        # Convert new stars to numpy arrays
        ra_arr = new_stars[:, 0]
        dec_arr = new_stars[:, 1]
        mag_arr = new_stars[:, 2]

        # Projection (same as render_chart)
        center_ra_rad = np.radians(center_ra)
        center_dec_rad = np.radians(center_dec)
        ra_rad = np.radians(ra_arr)
        dec_rad = np.radians(dec_arr)

        cos_center_dec = np.cos(center_dec_rad)

        dra = ra_rad - center_ra_rad
        dra = np.where(dra > np.pi, dra - 2 * np.pi, dra)
        dra = np.where(dra < -np.pi, dra + 2 * np.pi, dra)
        ddec = dec_rad - center_dec_rad

        x_proj = dra * cos_center_dec
        y_proj = ddec

        pixel_scale = width / np.radians(fov)

        x_screen = width / 2.0 - x_proj * pixel_scale
        y_screen = height / 2.0 - y_proj * pixel_scale

        # Apply rotation
        if rotation != 0:
            rot_rad = np.radians(rotation)
            cos_rot = np.cos(rot_rad)
            sin_rot = np.sin(rot_rad)

            center_x = width / 2.0
            center_y = height / 2.0
            x_rel = x_screen - center_x
            y_rel = y_screen - center_y

            x_rotated = x_rel * cos_rot - y_rel * sin_rot
            y_rotated = x_rel * sin_rot + y_rel * cos_rot

            x_screen = x_rotated + center_x
            y_screen = y_rotated + center_y

        # Filter visible stars
        mask = (
            (x_screen >= 0) & (x_screen < width) & (y_screen >= 0) & (y_screen < height)
        )

        x_visible = x_screen[mask]
        y_visible = y_screen[mask]
        mag_visible = mag_arr[mask]

        logger.info(
            f"Render Chart INCREMENTAL: {len(x_visible)} of {len(new_stars)} new stars visible"
        )

        # Calculate intensities using GLOBAL magnitude range (from all_stars)
        if len(mag_visible) == 0:
            intensities = np.array([])
        elif faintest_mag - brightest_mag < 0.1:
            intensities = np.full_like(mag_visible, 255, dtype=int)
        else:
            # Use global magnitude range for consistent scaling
            intensities = 255 - (
                (mag_visible - brightest_mag) / (faintest_mag - brightest_mag) * 205
            )
            intensities = intensities.astype(int)

        # Draw new stars
        ix = np.round(x_visible).astype(int)
        iy = np.round(y_visible).astype(int)

        for i in range(len(ix)):
            px = ix[i]
            py = iy[i]
            intensity = intensities[i]

            if 0 <= px < width and 0 <= py < height:
                # Use max instead of add to avoid bright blobs from overlapping stars
                image_array[py, px, 0] = max(image_array[py, px, 0], intensity)

        np.clip(image_array[:, :, 0], 0, 255, out=image_array[:, :, 0])

        image = Image.fromarray(image_array, mode="RGB")

        # Tag as Gaia chart
        image.is_loading_placeholder = False  # type: ignore[attr-defined]

        t_end = time.time()
        logger.debug(f"  Incremental render time: {(t_end - t_start) * 1000:.1f}ms")

        return image

    def _draw_star_antialiased_fast(self, image_array, ix, iy, fx, fy, intensity):
        """
        Draw star with bilinear anti-aliasing using fast NumPy operations

        Args:
            image_array: NumPy array (height, width, 3)
            ix, iy: Integer pixel coordinates (top-left)
            fx, fy: Fractional offsets (0-1)
            intensity: Peak intensity (0-255)
        """
        # Bilinear interpolation weights
        w00 = (1 - fx) * (1 - fy)  # Top-left
        w10 = fx * (1 - fy)  # Top-right
        w01 = (1 - fx) * fy  # Bottom-left
        w11 = fx * fy  # Bottom-right

        # Apply to 2x2 region using NumPy (much faster than getpixel/putpixel)
        # Red channel only (index 0)
        if w00 > 0.01:
            image_array[iy, ix, 0] = min(
                255, image_array[iy, ix, 0] + int(intensity * w00)
            )
        if w10 > 0.01:
            image_array[iy, ix + 1, 0] = min(
                255, image_array[iy, ix + 1, 0] + int(intensity * w10)
            )
        if w01 > 0.01:
            image_array[iy + 1, ix, 0] = min(
                255, image_array[iy + 1, ix, 0] + int(intensity * w01)
            )
        if w11 > 0.01:
            image_array[iy + 1, ix + 1, 0] = min(
                255, image_array[iy + 1, ix + 1, 0] + int(intensity * w11)
            )

    def mag_to_intensity(self, mag: float) -> int:
        """
        Convert magnitude to red pixel intensity (0-255)

        Args:
            mag: Stellar magnitude

        Returns:
            Red pixel value (0-255)
        """
        if mag < 3:
            return 255
        elif mag < 6:
            return 200
        elif mag < 9:
            return 150
        elif mag < 12:
            return 100
        elif mag < 14:
            return 75
        else:
            return 50

    @staticmethod
    def sqm_to_nelm(sqm: float) -> float:
        """
        Convert SQM reading (sky brightness) to NELM (naked eye limiting magnitude)

        Formula: NELM ≈ (SQM - 8.89) / 2 + 0.5

        Reference: https://www.unihedron.com/projects/darksky/faq.php
        Unihedron manufacturer formula for SQM-L devices

        Args:
            sqm: Sky Quality Meter reading in mag/arcsec²

        Returns:
            Naked Eye Limiting Magnitude

        Examples:
            SQM 22.0 (pristine dark sky) → NELM 7.1
            SQM 21.0 (good dark sky) → NELM 6.6
            SQM 20.0 (rural sky) → NELM 6.1
            SQM 19.0 (suburban) → NELM 5.6
            SQM 18.0 (suburban/urban) → NELM 5.1
            SQM 17.0 (urban) → NELM 4.6
        """
        nelm = (sqm - 8.89) / 2.0 + 0.5
        return nelm

    @staticmethod
    def feijth_comello_limiting_magnitude(
        mv: float, D: float, d: float, M: float, t: float
    ) -> float:
        """
        Calculate limiting magnitude using Feijth & Comello formula

        Formula: mg = mv - 2 + 2.5 × log₁₀(√(D² - d²) × M × t)

        Where:
        - mv = naked eye limiting magnitude
        - D = telescope aperture [cm]
        - d = central obstruction diameter [cm] (0 for unobstructed)
        - M = magnification
        - t = transmission (100% = 1.0, typically 0.5-0.9)

        This practical formula is based on over 100,000 observations by Henk Feijth
        and Georg Comello (mid-1990s). Unlike simple aperture formulas, it accounts
        for obstruction, magnification, and transmission.

        References:
        - https://astrobasics.de/en/basics/physical-quantities/limiting-magnitude/
        - https://www.y-auriga.de/astro/formeln.html (section 14)
        - https://fr.wikipedia.org/wiki/Magnitude_limite_visuelle

        Args:
            mv: Naked eye limiting magnitude
            D: Aperture in cm
            d: Central obstruction diameter in cm
            M: Magnification
            t: Transmission (0-1)

        Returns:
            Telescopic limiting magnitude

        Example:
            With mv=6.04, D=25cm, d=4cm, M=400, t=0.54 → mg=13.36
        """
        from math import log10, sqrt

        # Effective aperture accounting for central obstruction
        # Only the (D² - d²) term is under the square root
        effective_aperture = sqrt(D**2 - d**2)

        # Complete formula: mg = mv - 2 + 2.5 × log₁₀(√(D² - d²) × M × t)
        mg = mv - 2.0 + 2.5 * log10(effective_aperture * M * t)
        return mg

    def get_limiting_magnitude(self, sqm) -> float:
        """
        Get limiting magnitude based on config mode (auto or fixed)

        Args:
            sqm: SQM state object for sky brightness

        Returns:
            Limiting magnitude value
        """
        # Build cache key from sqm, telescope, and eyepiece focal lengths
        # Round SQM to 1 decimal to avoid floating point comparison issues
        equipment = self.config.equipment
        telescope = equipment.active_telescope
        eyepiece = equipment.active_eyepiece

        # Cache key includes all factors that affect LM calculation
        telescope_fl = telescope.focal_length_mm if telescope else None
        telescope_aperture = telescope.aperture_mm if telescope else None
        eyepiece_fl = eyepiece.focal_length_mm if eyepiece else None
        sqm_value = (
            round(sqm.value, 1) if sqm and hasattr(sqm, "value") and sqm.value else None
        )

        # Include config mode and fixed value in cache key to handle mode switching
        lm_mode = self.config.get_option("obj_chart_lm_mode")
        lm_fixed = self.config.get_option("obj_chart_lm_fixed")

        cache_key = (
            sqm_value,
            telescope_aperture,
            telescope_fl,
            eyepiece_fl,
            lm_mode,
            lm_fixed,
        )

        # Check cache - return cached value without logging
        if self._lm_cache is not None and self._lm_cache[0] == cache_key:
            return self._lm_cache[1]

        if lm_mode == "fixed":
            # Use fixed limiting magnitude from config
            lm = self.config.get_option("obj_chart_lm_fixed")
            try:
                lm = float(lm)
                logger.info(f"Using fixed LM from config: {lm:.1f}")
                self._lm_cache = (cache_key, lm)
                return lm
            except (ValueError, TypeError):
                # Invalid fixed value, fall back to auto
                logger.warning(f"Invalid fixed LM value: {lm}, falling back to auto")
                lm = self.calculate_limiting_magnitude(sqm)
                self._lm_cache = (cache_key, lm)
                return lm
        else:
            # Auto mode: calculate based on equipment and sky brightness
            lm = self.calculate_limiting_magnitude(sqm)
            self._lm_cache = (cache_key, lm)
            return lm

    def calculate_limiting_magnitude(self, sqm) -> float:
        """
        Calculate limiting magnitude using Feijth & Comello formula

        Converts SQM to NELM, then applies Feijth & Comello formula accounting
        for telescope aperture, obstruction, magnification, and transmission.

        Args:
            sqm: SQM state object for sky brightness

        Returns:
            Limiting magnitude (uncapped - caller caps for catalog queries)
        """

        equipment = self.config.equipment
        telescope = equipment.active_telescope
        eyepiece = equipment.active_eyepiece

        # Get naked eye limiting magnitude from SQM
        if sqm and hasattr(sqm, "value") and sqm.value:
            sqm_value = sqm.value
            mv = self.sqm_to_nelm(sqm_value)
        else:
            sqm_value = 19.5  # Default suburban sky
            mv = self.sqm_to_nelm(sqm_value)  # ≈ 5.8

        # Calculate telescopic limiting magnitude
        if telescope and telescope.aperture_mm > 0 and eyepiece:
            # Convert aperture from mm to cm for formula
            D_cm = telescope.aperture_mm / 10.0

            # Calculate magnification
            magnification = telescope.focal_length_mm / eyepiece.focal_length_mm
            exit_pupil_mm = telescope.aperture_mm / magnification

            # No obstruction assumed (we don't know the secondary mirror size)
            d_cm = 0.0

            # Transmission (typical value for good optics)
            transmission = 0.85

            # Apply Feijth & Comello formula directly
            # The formula already accounts for magnification effects
            lm = self.feijth_comello_limiting_magnitude(
                mv, D_cm, d_cm, magnification, transmission
            )

            logger.info(
                f"LM calculation: mv={mv:.1f} (SQM={sqm_value:.1f}), "
                f"aperture={telescope.aperture_mm:.0f}mm, mag={magnification:.1f}x, "
                f"exit_pupil={exit_pupil_mm:.1f}mm → LM={lm:.1f}"
            )
        elif telescope and telescope.aperture_mm > 0:
            # No eyepiece: assume minimum useful magnification (exit pupil = 7mm)
            D_cm = telescope.aperture_mm / 10.0
            min_magnification = telescope.aperture_mm / 7.0
            transmission = 0.85

            lm = self.feijth_comello_limiting_magnitude(
                mv, D_cm, 0.0, min_magnification, transmission
            )
            logger.info(
                f"LM calculation: aperture={telescope.aperture_mm}mm (no eyepiece, min mag={min_magnification:.1f}x) → LM={lm:.1f}"
            )
        else:
            # No telescope: use naked eye
            lm = mv
            logger.info(f"LM calculation: no telescope, NELM={lm:.1f}")

        # Return uncapped value (caller will cap for queries if needed)
        return lm

    def get_cache_key(self, catalog_object) -> str:
        """
        Generate cache key for object + eyepiece + limiting magnitude combination

        Args:
            catalog_object: CompositeObject

        Returns:
            Cache key string
        """
        obj_key = f"{catalog_object.catalog_code}{catalog_object.sequence}"
        eyepiece = self.config.equipment.active_eyepiece
        eyepiece_key = str(eyepiece) if eyepiece else "none"

        # Include limiting magnitude in cache key
        sqm = self.shared_state.sqm()
        lm = self.get_limiting_magnitude(sqm)
        lm_key = f"{lm:.1f}"

        return f"{obj_key}_{eyepiece_key}_lm{lm_key}"

    def invalidate_cache(self):
        """Clear chart cache (call when equipment changes)"""
        self.chart_cache.clear()
        logger.debug("Chart cache invalidated")
