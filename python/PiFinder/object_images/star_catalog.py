#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
HEALPix-indexed star catalog loader with background loading and CPU throttling

This module provides efficient loading of Gaia star catalogs for chart generation.
Features:
- Background loading with thread safety
- CPU throttling to avoid blocking other processes
- LRU tile caching
- Hemisphere filtering for memory efficiency
- Proper motion corrections
"""

import json
import logging
import mmap
import struct
import threading
import time
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

# Import healpy at module level to avoid first-use delay
# This ensures the slow import happens during initialization, not during first chart render
try:
    import healpy as hp  # type: ignore[import-untyped]

    _HEALPY_AVAILABLE = True
except ImportError:
    hp = None
    _HEALPY_AVAILABLE = False

logger = logging.getLogger("PiFinder.StarCatalog")

# Optimized tile format: header + star records (no redundant HEALPix per star)
TILE_HEADER_FORMAT = "<IH"  # [HEALPix:4][NumStars:2]
TILE_HEADER_SIZE = 6
STAR_RECORD_FORMAT = "<BBB"  # [RA_offset:1][Dec_offset:1][Mag:1]
STAR_RECORD_SIZE = 3

# Numpy dtype for vectorized parsing (star records only, no HEALPix)
# NOTE: Proper motion has been pre-applied at catalog build time
STAR_RECORD_DTYPE = np.dtype(
    [
        ("ra_offset", "u1"),
        ("dec_offset", "u1"),
        ("mag", "u1"),
    ]
)

# Index cache size limit (tiles per magnitude band)
# At ~50 bytes per tile entry, 10000 tiles = ~500KB per band
# With 6 mag bands, total cache size ~3MB (acceptable on Pi)
# This accommodates the full mag 0-6 index (6465 tiles) without trimming
MAX_INDEX_CACHE_SIZE = 10000


class CatalogState(Enum):
    """Catalog loading state"""

    NOT_LOADED = 0
    LOADING = 1
    READY = 2


class CompressedIndex:
    """
    Memory-efficient compressed index reader with mmap support.

    Uses run-length encoding format:
    - Header: version(4), num_tiles(4), num_runs(4)
    - Run directory: [start_tile_id(4), data_offset(8)] per run (in RAM)
    - Run data: [length(2), offset_base(8), sizes...] (mmap'd)
    """

    def __init__(self, index_file: Path):
        """Load compressed index with run directory in memory"""
        self.index_file = index_file
        self.run_directory: List[Tuple[int, int]] = []  # (start_tile_id, data_offset)

        # Open file for mmap
        self._file = open(index_file, "rb")
        self._mm = mmap.mmap(self._file.fileno(), 0, access=mmap.ACCESS_READ)

        # Read header
        version, self.num_tiles, num_runs = struct.unpack_from("<III", self._mm, 0)
        if version != 3:
            raise ValueError(f"Expected compressed index v3, got v{version}")

        # Read run directory into memory (fast!)
        offset = 12
        for _ in range(num_runs):
            start_tile, data_offset = struct.unpack_from("<IQ", self._mm, offset)
            self.run_directory.append((start_tile, data_offset))
            offset += 12

        logger.debug(
            f"CompressedIndex: loaded {num_runs} runs for {self.num_tiles:,} tiles"
        )

    def get(self, tile_id: int) -> Optional[Tuple[int, int]]:
        """
        Get (offset, size) for a tile ID.

        Returns None if tile doesn't exist.
        """
        # Binary search in run directory
        left, right = 0, len(self.run_directory) - 1
        run_idx = -1

        while left <= right:
            mid = (left + right) // 2
            start_tile = self.run_directory[mid][0]

            # Check if tile is in this run
            if mid < len(self.run_directory) - 1:
                next_start = self.run_directory[mid + 1][0]
                if start_tile <= tile_id < next_start:
                    run_idx = mid
                    break
            else:
                # Last run
                if start_tile <= tile_id:
                    run_idx = mid
                    break

            if tile_id < start_tile:
                right = mid - 1
            else:
                left = mid + 1

        if run_idx == -1:
            return None

        # Read run data from mmap
        start_tile, data_offset = self.run_directory[run_idx]
        offset_in_run = tile_id - start_tile

        # Read run header
        run_length, offset_base = struct.unpack_from("<HQ", self._mm, data_offset)

        if offset_in_run >= run_length:
            return None

        # Read sizes up to and including our tile
        sizes_offset = data_offset + 10  # After length(2) + offset_base(8)
        sizes_data = self._mm[sizes_offset : sizes_offset + (offset_in_run + 1) * 2]
        sizes = struct.unpack(f"<{offset_in_run + 1}H", sizes_data)

        # Calculate tile offset and size
        tile_offset = offset_base + sum(sizes[:-1])
        tile_size = sizes[-1]

        return (tile_offset, tile_size)

    def close(self):
        """Close mmap and file"""
        if self._mm:
            self._mm.close()
        if self._file:
            self._file.close()

    def __del__(self):
        """Cleanup on deletion"""
        self.close()


class GaiaStarCatalog:
    """
    HEALPix-indexed star catalog with background loading

    Usage:
        catalog = GaiaStarCatalog("/path/to/gaia_stars")
        catalog.start_background_load(observer_lat=40.0, limiting_mag=14.0)
        # ... wait for catalog.state == CatalogState.READY ...
        stars = catalog.get_stars_for_fov(ra=180.0, dec=45.0, fov=10.0, mag_limit=12.0)
    """

    def __init__(self, catalog_path: str):
        """
        Initialize catalog (doesn't load data yet)

        Args:
            catalog_path: Path to gaia_stars directory containing metadata.json
        """
        logger.info(f">>> GaiaStarCatalog.__init__() called with path: {catalog_path}")
        self.catalog_path = Path(catalog_path)
        self.state = CatalogState.NOT_LOADED
        self.metadata: Optional[Dict[str, Any]] = None
        self.nside: Optional[int] = None
        self.observer_lat: Optional[float] = None
        self.limiting_magnitude: float = 12.0
        self.visible_tiles: Optional[Set[int]] = None
        self.tile_cache: Dict[Tuple[int, float], np.ndarray] = {}
        self.cache_lock = threading.Lock()
        self.load_thread: Optional[threading.Thread] = None
        self.load_progress: str = ""  # Status message for UI
        self.load_percent: int = 0  # Progress percentage (0-100)
        self._index_cache: Dict[str, Any] = {}
        # Cache of existing tile IDs per magnitude band to avoid scanning for non-existent tiles
        self._existing_tiles_cache: Dict[str, Set[int]] = {}
        logger.info(">>> GaiaStarCatalog.__init__() completed")

    def start_background_load(
        self, observer_lat: Optional[float] = None, limiting_mag: float = 12.0
    ):
        """
        Start loading catalog in background thread

        Args:
            observer_lat: Observer latitude for hemisphere filtering (None = full sky)
            limiting_mag: Magnitude limit for preloading bright stars
        """
        logger.info(f">>> start_background_load() called, current state: {self.state}")
        if self.state != CatalogState.NOT_LOADED:
            logger.warning(
                f">>> Catalog already loading or loaded (state={self.state}), skipping"
            )
            return

        logger.info(
            f">>> Starting background load: lat={observer_lat}, mag={limiting_mag}, path={self.catalog_path}"
        )

        self.state = CatalogState.LOADING
        self.observer_lat = observer_lat
        self.limiting_magnitude = limiting_mag

        # Start background thread
        logger.info(">>> Creating background thread...")
        self.load_thread = threading.Thread(
            target=self._background_load_worker, daemon=True, name="CatalogLoader"
        )
        self.load_thread.start()
        logger.info(
            f">>> Background thread started, thread alive: {self.load_thread.is_alive()}"
        )

    def _background_load_worker(self):
        """Background worker - just loads metadata"""
        logger.info(">>> _background_load_worker() started")
        try:
            # Load metadata
            self.load_progress = "Loading..."
            self.load_percent = 50
            logger.info(f">>> Loading catalog metadata from {self.catalog_path}")

            metadata_file = self.catalog_path / "metadata.json"

            if not metadata_file.exists():
                logger.error(f">>> Catalog metadata not found: {metadata_file}")
                logger.error(
                    ">>> Please build catalog using: python -m PiFinder.catalog_tools.gaia_downloader"
                )
                self.load_progress = "Error: catalog not built"
                self.state = CatalogState.NOT_LOADED
                return

            with open(metadata_file, "r") as f:
                self.metadata = json.load(f)
            logger.info(">>> metadata.json loaded")

            self.nside = self.metadata.get("nside", 512)
            star_count = self.metadata.get("star_count", 0)
            logger.info(
                f">>> Catalog metadata ready: {star_count:,} stars, "
                f"mag limit {self.metadata.get('mag_limit', 0):.1f}, nside={self.nside}"
            )

            # Log available bands
            bands = self.metadata.get("mag_bands", [])
            logger.info(f">>> Catalog mag bands: {json.dumps(bands)}")

            # Preload all compressed indices (run directories) into memory (~2-12 MB total)
            # This eliminates first-query delays (70ms per band → 420ms total stuttering)
            self._preload_compressed_indices()

            # Initialize empty structures (no preloading)
            self.visible_tiles = None  # Load full sky on-demand

            # Mark ready
            self.load_progress = "Ready"
            self.load_percent = 100
            self.state = CatalogState.READY
            logger.info(f">>> _background_load_worker() completed, state: {self.state}")

        except Exception as e:
            logger.error(f">>> Catalog loading failed: {e}", exc_info=True)
            self.load_progress = f"Error: {str(e)}"
            self.state = CatalogState.NOT_LOADED

    def _calc_visible_tiles(self, observer_lat: float) -> Optional[Set[int]]:
        """
        Calculate HEALPix tiles visible from observer latitude

        DISABLED: Too slow (iterates 3M+ pixels)
        TODO: Pre-compute hemisphere mask during catalog build

        Args:
            observer_lat: Observer latitude in degrees

        Returns:
            None (full sky always loaded for now)
        """
        return None

    def _preload_mag_band(self, mag_min: float, mag_max: float):
        """
        Preload all tiles for a magnitude band

        Args:
            mag_min: Minimum magnitude
            mag_max: Maximum magnitude
        """
        band_dir = self.catalog_path / f"mag_{mag_min:02.0f}_{mag_max:02.0f}"
        if not band_dir.exists():
            return

        # Get all tile files in this band
        tile_files = sorted(band_dir.glob("tile_*.bin"))

        for tile_file in tile_files:
            # Extract tile ID from filename
            tile_id = int(tile_file.stem.split("_")[1])

            # Filter by hemisphere if applicable
            if self.visible_tiles and tile_id not in self.visible_tiles:
                continue

            # Load tile
            self._load_tile_from_file(tile_file, mag_min, mag_max)

            # CPU throttle: 10ms pause between tiles
            # (50ms was too conservative, slowing down loading significantly)
            time.sleep(0.01)

    def get_stars_for_fov_progressive(
        self,
        ra_deg: float,
        dec_deg: float,
        fov_deg: float,
        mag_limit: Optional[float] = None,
    ):
        """
        Query stars in field of view progressively (bright to faint)

        This is a generator that yields (stars, is_complete) tuples as each
        magnitude band is loaded. This allows the UI to display bright stars
        immediately while continuing to load fainter stars in the background.

        Uses background thread to load magnitude bands asynchronously, eliminating
        UI event loop blocking. The UI consumes results at its own pace (~10 FPS)
        while catalog loading continues uninterrupted.

        Blocks if state == LOADING (waits for load to complete)
        Returns empty array if state == NOT_LOADED

        Args:
            ra_deg: Center RA in degrees
            dec_deg: Center Dec in degrees
            fov_deg: Field of view in degrees
            mag_limit: Limiting magnitude (uses catalog default if None)

        Yields:
            (stars, is_complete) tuples where:
                - stars: Numpy array (N, 3) of (ra, dec, mag) with proper motion corrected
                - is_complete: True if this is the final yield with all stars
        """
        if self.state == CatalogState.NOT_LOADED:
            logger.warning("Catalog not loaded")
            yield (np.empty((0, 3)), True)
            return

        # Wait for catalog to be loaded
        while self.state == CatalogState.LOADING:
            import time

            time.sleep(0.1)

        if mag_limit is None:
            mag_limit = self.metadata.get("mag_limit", 17.0) if self.metadata else 17.0

        if not _HEALPY_AVAILABLE:
            logger.error("healpy not available - cannot perform HEALPix queries")
            yield (np.empty((0, 3)), True)
            return

        # Calculate HEALPix tiles covering FOV
        # fov_deg is the diagonal field width, query_disc expects radius
        # For square FOV rotated arbitrarily, need circumscribed circle radius = diagonal/2
        # Add 10% margin to ensure edge tiles are fully covered
        # Use inclusive=True to ensure boundary tiles are included (critical for small FOVs)
        vec = hp.ang2vec(ra_deg, dec_deg, lonlat=True)
        radius_rad = np.radians(fov_deg / 2 * 1.1)
        tiles = hp.query_disc(self.nside, vec, radius_rad, inclusive=True)
        logger.debug(
            f"HEALPix query_disc: FOV={fov_deg:.4f}°, radius={np.degrees(radius_rad):.4f}°, nside={self.nside}, returned {len(tiles)} tiles"
        )

        # Filter by visible hemisphere
        if self.visible_tiles:
            tiles = [t for t in tiles if t in self.visible_tiles]

        if not self.metadata:
            yield (np.empty((0, 3)), True)
            return

        # Background loading using producer-consumer pattern
        import queue
        import threading
        import time

        # Queue to pass star arrays from background thread to generator
        result_queue: queue.Queue = queue.Queue(
            maxsize=6
        )  # Buffer up to 6 magnitude bands

        def load_bands_background():
            """Background thread that loads magnitude bands continuously"""
            try:
                all_stars_list = []
                mag_bands = self.metadata.get("mag_bands", [])

                for i, mag_band_info in enumerate(mag_bands):
                    mag_min = mag_band_info["min"]
                    mag_max = mag_band_info["max"]

                    # Skip bands fainter than limit
                    if mag_min >= mag_limit:
                        break

                    logger.debug(
                        f">>> BACKGROUND: Loading mag band {mag_min}-{mag_max}, tiles={len(tiles)}"
                    )

                    # Load stars from this magnitude band only
                    band_stars = self._load_tiles_for_mag_band(
                        tiles, mag_band_info, mag_limit, ra_deg, dec_deg, fov_deg
                    )

                    # Add to cumulative list
                    if len(band_stars) > 0:
                        all_stars_list.append(band_stars)

                    # Concatenate for this yield
                    if all_stars_list:
                        current_total = np.concatenate(all_stars_list)
                    else:
                        current_total = np.empty((0, 3))

                    is_last_band = mag_max >= mag_limit

                    # Push to queue (blocks if queue is full - back-pressure)
                    result_queue.put((current_total, is_last_band, len(band_stars)))

                    logger.info(
                        f">>> BACKGROUND: mag {mag_min}-{mag_max}: "
                        f"stars={len(band_stars)}, cumulative={len(current_total)}"
                    )

                    if is_last_band:
                        break

            except Exception as e:
                logger.error(f">>> BACKGROUND: Error loading bands: {e}", exc_info=True)
                # Push error marker
                result_queue.put((None, True, 0))

        # Start background loading thread
        loader_thread = threading.Thread(
            target=load_bands_background, daemon=True, name="StarCatalogLoader"
        )
        loader_thread.start()
        logger.info(">>> PROGRESSIVE: Background loading thread started")

        # Yield results as they become available
        while True:
            try:
                # Get next result from queue
                # Use timeout to avoid blocking forever if thread crashes
                current_total, is_last_band, band_star_count = result_queue.get(
                    timeout=10.0
                )

                if current_total is None:
                    # Error in background thread
                    logger.error(">>> PROGRESSIVE: Background thread encountered error")
                    yield (np.empty((0, 3)), True)
                    break

                # Yield to consumer (UI)
                yield (current_total, is_last_band)

                logger.info(
                    f">>> PROGRESSIVE: stars_in_band={band_star_count}, cumulative={len(current_total)}"
                )

                if is_last_band:
                    logger.info(
                        f"PROGRESSIVE: Complete! Total {len(current_total)} stars loaded"
                    )
                    break

            except queue.Empty:
                logger.error(">>> PROGRESSIVE: Timeout waiting for background thread")
                yield (np.empty((0, 3)), True)
                break

    def get_stars_for_fov(
        self,
        ra_deg: float,
        dec_deg: float,
        fov_deg: float,
        mag_limit: Optional[float] = None,
    ) -> np.ndarray:
        """
        Query stars in field of view

        Blocks if state == LOADING (waits for load to complete)
        Returns empty array if state == NOT_LOADED

        Args:
            ra_deg: Center RA in degrees
            dec_deg: Center Dec in degrees
            fov_deg: Field of view in degrees
            mag_limit: Limiting magnitude (uses catalog default if None)

        Returns:
            Numpy array (N, 3) of (ra, dec, mag) with proper motion corrected
        """
        if self.state == CatalogState.NOT_LOADED:
            logger.warning("Catalog not loaded")
            return np.empty((0, 3))

        if self.state == CatalogState.LOADING:
            # Wait for loading to complete (with timeout)
            logger.info("Waiting for catalog to finish loading...")
            timeout = 30  # seconds
            start = time.time()
            while self.state == CatalogState.LOADING:
                time.sleep(0.1)
                if time.time() - start > timeout:
                    logger.error("Catalog loading timeout")
                    return np.empty((0, 3))

        # State is READY - metadata must be loaded by now
        assert self.metadata is not None, (
            "metadata should be loaded when state is READY"
        )
        assert self.nside is not None, "nside should be set when state is READY"

        mag_limit = mag_limit or self.limiting_magnitude

        if not _HEALPY_AVAILABLE:
            logger.error("healpy not installed")
            return np.empty((0, 3))

        # Calculate HEALPix tiles covering FOV
        # fov_deg is the diagonal field width, query_disc expects radius
        # For square FOV rotated arbitrarily, need circumscribed circle radius = diagonal/2
        # Add 10% margin to ensure edge tiles are fully covered
        vec = hp.ang2vec(ra_deg, dec_deg, lonlat=True)
        radius_rad = np.radians(fov_deg / 2 * 1.1)
        tiles = hp.query_disc(self.nside, vec, radius_rad)
        logger.debug(
            f"HEALPix: Querying {len(tiles)} tiles for FOV={fov_deg:.2f}° (radius={np.degrees(radius_rad):.3f}°) at nside={self.nside}"
        )

        # Filter by visible hemisphere
        if self.visible_tiles:
            tiles = [t for t in tiles if t in self.visible_tiles]

        # Load stars from tiles (batch load for better performance)
        stars: np.ndarray = np.empty((0, 3))
        tile_star_counts = {}

        # Try batch loading if catalog is compact format
        # Only batch for moderate tile counts (10-50) to avoid UI blocking
        is_compact = self.metadata.get("format") == "compact"
        if is_compact and 10 < len(tiles) <= 50:
            # Batch load is much faster for many tiles
            # Note: batch loading returns PM-corrected (ra, dec, mag) tuples
            logger.info(f"Using BATCH loading for {len(tiles)} tiles")
            stars = self._load_tiles_batch(tiles, mag_limit)
            logger.info(f"Batch load complete: {len(stars)} stars")
            tile_star_counts = {
                t: 0 for t in tiles
            }  # Don't track individual counts for batch
        else:
            # Load one by one (better for small queries or legacy format)
            logger.info(
                f"Using SINGLE-TILE loading for {len(tiles)} tiles (compact={is_compact})"
            )
            stars_raw_list = []

            # To prevent UI blocking, limit the number of tiles loaded at once
            # For small FOVs (<1°), 20-30 tiles is more than enough
            MAX_TILES = 25
            if len(tiles) > MAX_TILES:
                logger.warning(
                    f"Large tile count ({len(tiles)}) detected! Limiting to {MAX_TILES} tiles to prevent UI freeze"
                )
                # Tiles from query_disc are roughly ordered by distance from center
                # Keep the first MAX_TILES which are closest to FOV center
                tiles = tiles[:MAX_TILES]

            cache_hits = 0
            cache_misses = 0

            for i, tile_id in enumerate(tiles):
                # Check if this tile is cached (for performance tracking)
                cache_key = (tile_id, mag_limit)
                was_cached = cache_key in self.tile_cache

                # Returns (N, 5) array
                tile_stars = self._load_tile_data(tile_id, mag_limit)
                tile_star_counts[tile_id] = len(tile_stars)

                if len(tile_stars) > 0:
                    stars_raw_list.append(tile_stars)

                if was_cached:
                    cache_hits += 1
                else:
                    cache_misses += 1

            # Log cache performance
            logger.debug(
                f"Tile cache: {cache_hits} hits, {cache_misses} misses ({cache_hits / (cache_hits + cache_misses) * 100:.1f}% hit rate)"
            )

            total_raw = sum(len(x) for x in stars_raw_list)
            logger.debug(f"Single-tile loading complete: {total_raw} stars")

            # Log tile loading stats
            if tile_star_counts:
                logger.debug(
                    f"Loaded from {len(tile_star_counts)} tiles: "
                    + f"min={min(tile_star_counts.values())} max={max(tile_star_counts.values())} "
                    + f"total={sum(tile_star_counts.values())}"
                )

            # Apply proper motion correction (for non-batch path only)
            t_pm_start = time.time()

            if stars_raw_list:
                stars_raw_combined = np.concatenate(stars_raw_list)
                ras = stars_raw_combined[:, 0]
                decs = stars_raw_combined[:, 1]
                mags = stars_raw_combined[:, 2]
                pmras = stars_raw_combined[:, 3]
                pmdecs = stars_raw_combined[:, 4]
                stars = self._apply_proper_motion((ras, decs, mags, pmras, pmdecs))
            else:
                stars = np.empty((0, 3))

            t_pm_end = time.time()
            logger.debug(
                f"Proper motion correction: {len(stars)} stars in {(t_pm_end - t_pm_start) * 1000:.1f}ms"
            )

        return stars

    def _load_tiles_for_mag_band(
        self,
        tile_ids: List[int],
        mag_band_info: dict,
        mag_limit: float,
        ra_deg: float,
        dec_deg: float,
        fov_deg: float,
    ) -> np.ndarray:
        """
        Load tiles for a specific magnitude band (used by progressive loading)

        Args:
            tile_ids: List of HEALPix tile IDs to load
            mag_band_info: Magnitude band metadata dict with 'min', 'max' keys
            mag_limit: Maximum magnitude to include
            ra_deg: Center RA (for logging)
            dec_deg: Center Dec (for logging)
            fov_deg: Field of view (for logging)

        Returns:
            Numpy array (N, 3) of (ra, dec, mag) with proper motion corrected
        """
        mag_min = mag_band_info["min"]
        mag_max = mag_band_info["max"]
        band_dir = self.catalog_path / f"mag_{mag_min:02.0f}_{mag_max:02.0f}"

        # logger.info(f">>> _load_tiles_for_mag_band: mag {mag_min}-{mag_max}, band_dir={band_dir}, tiles={len(tile_ids)}")

        # Check if this band directory exists
        if not band_dir.exists():
            logger.warning(f">>> Magnitude band directory not found: {band_dir}")
            return np.empty((0, 3))

        # For compact format, use vectorized batch loading per band
        assert self.metadata is not None, "metadata must be loaded"
        is_compact = self.metadata.get("format") == "compact"
        # logger.info(f">>> Format is_compact={is_compact}, calling _load_tiles_batch_single_band...")
        if is_compact:
            result = self._load_tiles_batch_single_band(
                tile_ids, mag_band_info, mag_limit
            )
            # logger.info(f">>> _load_tiles_batch_single_band returned {len(result)} stars")
            return result
        else:
            # Legacy format - load tiles one by one (will load all bands for each tile)
            # This is less efficient but legacy format doesn't support per-band loading
            stars_raw_list = []
            for tile_id in tile_ids:
                tile_stars = self._load_tile_data(tile_id, mag_limit)
                # Filter to just this magnitude band
                # tile_stars is (N, 5)
                if len(tile_stars) > 0:
                    mags = tile_stars[:, 2]
                    mask = (mags >= mag_min) & (mags < mag_max)
                    if np.any(mask):
                        stars_raw_list.append(tile_stars[mask])

            if stars_raw_list:
                stars_raw_combined = np.concatenate(stars_raw_list)
                ras = stars_raw_combined[:, 0]
                decs = stars_raw_combined[:, 1]
                mags = stars_raw_combined[:, 2]
                pmras = stars_raw_combined[:, 3]
                pmdecs = stars_raw_combined[:, 4]
                return self._apply_proper_motion((ras, decs, mags, pmras, pmdecs))
            else:
                return np.empty((0, 3))

    def _load_tile_data(self, tile_id: int, mag_limit: float) -> np.ndarray:
        """
        Load star data for a HEALPix tile

        Args:
            tile_id: HEALPix tile ID
            mag_limit: Maximum magnitude to load

        Returns:
            Numpy array of shape (N, 5) containing (ra, dec, mag, pmra, pmdec)
        """
        assert self.metadata is not None, (
            "metadata must be loaded before calling _load_tile_data"
        )

        cache_key = (tile_id, mag_limit)

        # Check cache
        with self.cache_lock:
            if cache_key in self.tile_cache:
                return self.tile_cache[cache_key]

        # Load from disk
        stars_list = []

        # Check catalog format
        is_compact = self.metadata.get("format") == "compact"

        # Determine which magnitude bands to load
        for mag_band_info in self.metadata.get("mag_bands", []):
            mag_min = mag_band_info["min"]
            mag_max = mag_band_info["max"]

            if mag_min >= mag_limit:
                continue  # Band too faint

            band_dir = self.catalog_path / f"mag_{mag_min:02.0f}_{mag_max:02.0f}"

            if is_compact:
                # Compact format: read from consolidated file using index
                ras, decs, mags, pmras, pmdecs = self._load_tile_compact(
                    band_dir, tile_id, mag_min, mag_max
                )
            else:
                # Legacy format: one file per tile
                tile_file = band_dir / f"tile_{tile_id:06d}.bin"
                if tile_file.exists():
                    ras, decs, mags, pmras, pmdecs = self._load_tile_from_file(
                        tile_file, mag_min, mag_max
                    )
                else:
                    ras, decs, mags, pmras, pmdecs = (
                        np.array([]),
                        np.array([]),
                        np.array([]),
                        np.array([]),
                        np.array([]),
                    )

            if len(ras) > 0:
                # Filter by magnitude
                mask = mags <= mag_limit
                if np.any(mask):
                    # Stack into (N, 5) array for this band
                    band_stars = np.column_stack(
                        (ras[mask], decs[mask], mags[mask], pmras[mask], pmdecs[mask])
                    )
                    stars_list.append(band_stars)
                    logger.debug(
                        f"  Tile {tile_id} Band {mag_min}-{mag_max}: {len(band_stars)} stars (file: {tile_file if not is_compact else 'compact'})"
                    )
                else:
                    logger.debug(
                        f"  Tile {tile_id} Band {mag_min}-{mag_max}: 0 stars (mask empty)"
                    )

        if not stars_list:
            stars = np.empty((0, 5))
        else:
            stars = np.concatenate(stars_list)

        # Cache result
        with self.cache_lock:
            self.tile_cache[cache_key] = stars
            # Simple cache size management (keep last 100 tiles)
            if len(self.tile_cache) > 100:
                # Remove oldest (first) entry
                oldest_key = next(iter(self.tile_cache))
                del self.tile_cache[oldest_key]

        return stars

    def _load_tile_from_file(
        self, tile_file: Path, mag_min: float, mag_max: float
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """
        Load stars from a tile file

        Args:
            tile_file: Path to tile binary file
            mag_min: Minimum magnitude in this band
            mag_max: Maximum magnitude in this band

        Returns:
            Tuple of (ras, decs, mags, pmras, pmdecs) arrays
        """
        if not _HEALPY_AVAILABLE:
            return (
                np.array([]),
                np.array([]),
                np.array([]),
                np.array([]),
                np.array([]),
            )

        # Read entire file at once
        with open(tile_file, "rb") as f:
            data = f.read()

        return self._parse_records(data)

    def _load_tile_compact(
        self, band_dir: Path, tile_id: int, mag_min: float, mag_max: float
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """
        Load stars from compact format (consolidated tiles.bin + v3 compressed index)

        Args:
            band_dir: Magnitude band directory
            tile_id: HEALPix tile ID
            mag_min: Minimum magnitude
            mag_max: Maximum magnitude

        Returns:
            Tuple of (ras, decs, mags, pmras, pmdecs) arrays
        """
        if not _HEALPY_AVAILABLE:
            return (
                np.array([]),
                np.array([]),
                np.array([]),
                np.array([]),
                np.array([]),
            )

        index_file = band_dir / "index.bin"
        tiles_file = band_dir / "tiles.bin"

        if not tiles_file.exists():
            return (
                np.array([]),
                np.array([]),
                np.array([]),
                np.array([]),
                np.array([]),
            )

        if not index_file.exists():
            raise FileNotFoundError(
                f"Compressed index not found: {index_file}\n"
                f"This catalog requires v3 format. Please rebuild using healpix_builder_compact.py"
            )

        # Load index (cached per band)
        cache_key = f"index_{mag_min}_{mag_max}"
        if cache_key not in self._index_cache:
            self._index_cache[cache_key] = CompressedIndex(index_file)

        index = self._index_cache[cache_key]

        # Get tile offset and size from compressed index
        result = index.get(tile_id)
        if result is None:
            return (
                np.array([]),
                np.array([]),
                np.array([]),
                np.array([]),
                np.array([]),
            )
        offset, size = result

        # Read tile data
        with open(tiles_file, "rb") as f:
            f.seek(offset)
            data = f.read(size)
            return self._parse_records(data)

    def _parse_records(
        self, data: bytes
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """
        Parse binary tile data into numpy arrays (VECTORIZED)

        New format: [Tile Header: 6 bytes][Star Records: 5 bytes each]

        Args:
            data: Binary tile data (header + star records)

        Returns:
            Tuple of (ras, decs, mags, pmras, pmdecs) as numpy arrays
        """
        if len(data) < TILE_HEADER_SIZE:
            return (
                np.array([]),
                np.array([]),
                np.array([]),
                np.array([]),
                np.array([]),
            )

        # Parse tile header
        healpix_pixel, num_stars = struct.unpack(
            TILE_HEADER_FORMAT, data[:TILE_HEADER_SIZE]
        )

        # Extract star records
        star_data = data[TILE_HEADER_SIZE:]

        if len(star_data) == 0:
            return (
                np.array([]),
                np.array([]),
                np.array([]),
                np.array([]),
                np.array([]),
            )

        # Verify data size matches expected
        expected_size = num_stars * STAR_RECORD_SIZE
        if len(star_data) != expected_size:
            logger.warning(
                f"Tile {healpix_pixel}: size mismatch. Expected {expected_size} bytes "
                f"for {num_stars} stars, got {len(star_data)} bytes"
            )
            # Truncate to valid records
            num_stars = len(star_data) // STAR_RECORD_SIZE

        # Parse all star records using numpy
        records = np.frombuffer(star_data, dtype=STAR_RECORD_DTYPE, count=num_stars)

        # Get pixel center (same for all stars in this tile)
        pixel_ra, pixel_dec = hp.pix2ang(self.nside, healpix_pixel, lonlat=True)

        # Calculate pixel size once
        pixel_size_deg = np.sqrt(hp.nside2pixarea(self.nside, degrees=True))
        max_offset_arcsec = pixel_size_deg * 3600.0 * 0.75

        # Decode all offsets
        ra_offset_arcsec = (records["ra_offset"] / 127.5 - 1.0) * max_offset_arcsec
        dec_offset_arcsec = (records["dec_offset"] / 127.5 - 1.0) * max_offset_arcsec

        # Calculate final positions (broadcast pixel center to all stars)
        decs = pixel_dec + dec_offset_arcsec / 3600.0
        ras = pixel_ra + ra_offset_arcsec / 3600.0 / np.cos(np.radians(decs))

        # Decode magnitudes
        mags = records["mag"] / 10.0

        # v2.1: Proper motion has been pre-applied at build time
        # Return empty arrays for backward compatibility
        pmras = np.zeros(len(records))
        pmdecs = np.zeros(len(records))

        return ras, decs, mags, pmras, pmdecs

    def _preload_compressed_indices(self) -> None:
        """
        Preload all v3 compressed indices (run directories) into memory during startup.

        Loads compressed index run directories (~2-12 MB total) to eliminate first-query
        delays during chart generation. Each compressed index loads its run directory
        into RAM for fast binary search, while keeping run data in mmap.

        This runs in background thread during catalog startup and trades a one-time
        ~200ms startup cost for eliminating 6 × 70ms = 420ms of stuttering during
        first chart generation.
        """
        if not self.metadata or "mag_bands" not in self.metadata:
            logger.warning(
                ">>> No metadata available, skipping compressed index preload"
            )
            return

        t0_total = time.time()
        bands_loaded = 0

        logger.info(">>> Preloading v3 compressed indices for all magnitude bands...")

        for band_info in self.metadata["mag_bands"]:
            mag_min = int(band_info["min"])
            mag_max = int(band_info["max"])
            cache_key = f"index_{mag_min}_{mag_max}"

            # Load compressed index (v3 format stored as index.bin)
            index_file = (
                self.catalog_path / f"mag_{mag_min:02d}_{mag_max:02d}" / "index.bin"
            )

            if not index_file.exists():
                raise FileNotFoundError(
                    f"Compressed index not found: {index_file}\n"
                    f"This catalog requires v3 format. Please rebuild using healpix_builder_compact.py"
                )

            t0 = time.time()

            # Load compressed index (v3 only)
            self._index_cache[cache_key] = CompressedIndex(index_file)
            t_load = (time.time() - t0) * 1000

            compressed_idx = self._index_cache[cache_key]
            bands_loaded += 1

            logger.info(
                f">>> Loaded compressed index {cache_key}: "
                f"{compressed_idx.num_tiles:,} tiles, {len(compressed_idx.run_directory):,} runs "
                f"in {t_load:.1f}ms"
            )

        t_total = (time.time() - t0_total) * 1000
        logger.info(
            f">>> Compressed index preload complete: {bands_loaded} indices "
            f"in {t_total:.1f}ms"
        )

    def _load_existing_tiles_set(self, index_file: Path) -> Set[int]:
        """
        Quickly load the set of all existing tile IDs from an index file.
        This is much faster than scanning for specific tiles when we just need
        to know "does this tile exist?" to avoid wasteful searches.

        Args:
            index_file: Path to binary index file

        Returns:
            Set of existing tile IDs (as integers)
        """
        existing_tiles: set[int] = set()

        if not index_file.exists():
            return existing_tiles

        with open(index_file, "rb") as f:
            # Read header
            header = f.read(8)
            if len(header) < 8:
                return existing_tiles

            version, num_tiles = struct.unpack("<II", header)

            # Define dtype to read just tile IDs (we don't need offset/size)
            if version == 1:
                # [tile_id:4][offset:8][size:4]
                tile_id_dtype = np.dtype(
                    [("tile_id", "<u4"), ("_skip", "V12")]
                )  # Skip 12 bytes
            elif version == 2:
                # [tile_id:4][offset:8][compressed_size:4][uncompressed_size:4]
                tile_id_dtype = np.dtype(
                    [("tile_id", "<u4"), ("_skip", "V16")]
                )  # Skip 16 bytes
            else:
                logger.error(f"Unsupported index version: {version}")
                return existing_tiles

            # Read all tile IDs at once (very fast, just reading integers)
            data = f.read()
            if not data:
                return existing_tiles

            records = np.frombuffer(data, dtype=tile_id_dtype)

            # Convert to set (numpy → set is fast for integers)
            existing_tiles = set(records["tile_id"].tolist())

        return existing_tiles

    def _apply_proper_motion(
        self, stars: Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]
    ) -> np.ndarray:
        """
        Apply proper motion corrections from J2016.0 to current epoch (VECTORIZED)

        Args:
            stars: Tuple of (ras, decs, mags, pmras, pmdecs) arrays

        Returns:
            Numpy array of shape (N, 3) containing (ra, dec, mag)
        """
        ras, decs, mags, pmras, pmdecs = stars

        if len(ras) == 0:
            return np.empty((0, 3))

        # Calculate years from J2016.0 to current date
        current_year = datetime.now().year + (
            datetime.now().timetuple().tm_yday / 365.25
        )
        years_elapsed = current_year - 2016.0

        # Apply proper motion forward to current epoch
        # pmra is in mas/year and needs cos(dec) correction for RA
        # Vectorized calculation
        ra_corrections = (
            (pmras / 1000 / 3600) / np.cos(np.radians(decs)) * years_elapsed
        )
        dec_corrections = (pmdecs / 1000 / 3600) * years_elapsed

        ra_corrected = ras + ra_corrections
        dec_corrected = decs + dec_corrections

        # Keep dec in valid range
        dec_corrected = np.clip(dec_corrected, -90, 90)

        # Stack into (N, 3) array
        return np.column_stack((ra_corrected, dec_corrected, mags))

    def _trim_index_cache(self, cache_key: str, protected_tile_ids: List[int]) -> None:
        """
        Trim index cache to stay within MAX_INDEX_CACHE_SIZE limit.

        Strategy: Remove oldest tiles not in the current request (protected_tile_ids).
        This ensures we keep tiles needed for the current chart while evicting others.

        Args:
            cache_key: Cache key (e.g., "index_12_14")
            protected_tile_ids: Tile IDs that must NOT be evicted (current FOV)
        """
        index = self._index_cache.get(cache_key)
        if not index:
            return

        cache_size = len(index)
        if cache_size <= MAX_INDEX_CACHE_SIZE:
            return  # Within limit, nothing to do

        # Calculate how many to remove
        tiles_to_remove = cache_size - MAX_INDEX_CACHE_SIZE
        logger.info(
            f">>> Cache {cache_key} exceeds limit ({cache_size} > {MAX_INDEX_CACHE_SIZE}), removing {tiles_to_remove} tiles"
        )

        # Build set of protected tiles
        protected_set = {str(tid) for tid in protected_tile_ids}

        # Find eviction candidates (tiles not in current request)
        candidates = [
            tile_key for tile_key in index.keys() if tile_key not in protected_set
        ]

        if len(candidates) < tiles_to_remove:
            # Not enough non-protected tiles, just remove what we can
            logger.warning(
                f">>> Only {len(candidates)} evictable tiles, removing all of them"
            )
            tiles_to_remove = len(candidates)

        # Remove the first N candidates (simple FIFO-ish eviction)
        # Could enhance this with LRU tracking later
        for i in range(tiles_to_remove):
            tile_key = candidates[i]
            del index[tile_key]

        logger.info(f">>> Cache trimmed: {cache_size} → {len(index)} tiles")

    def _load_tiles_batch_single_band(
        self,
        tile_ids: List[int],
        mag_band_info: dict,
        mag_limit: float,
    ) -> np.ndarray:
        """
        Batch load multiple tiles for a SINGLE magnitude band (compact format only)
        Used by progressive loading to load one mag band at a time

        Args:
            tile_ids: List of HEALPix tile IDs
            mag_band_info: Magnitude band metadata dict
            mag_limit: Maximum magnitude

        Returns:
            Numpy array of shape (N, 3) containing (ra, dec, mag)
        """
        if not _HEALPY_AVAILABLE:
            return np.empty((0, 3))

        mag_min = mag_band_info["min"]
        mag_max = mag_band_info["max"]

        band_dir = self.catalog_path / f"mag_{mag_min:02.0f}_{mag_max:02.0f}"
        index_file = band_dir / "index.bin"
        tiles_file = band_dir / "tiles.bin"

        if not tiles_file.exists():
            return np.empty((0, 3))

        if not index_file.exists():
            raise FileNotFoundError(
                f"Compressed index not found: {index_file}\n"
                f"This catalog requires v3 format. Please rebuild using healpix_builder_compact.py"
            )

        cache_key = f"index_{mag_min}_{mag_max}"

        # Load v3 compressed index (cached)
        if not hasattr(self, "_index_cache"):
            self._index_cache = {}

        t_index_start = time.time()
        logger.debug(f"Checking index cache for {cache_key}")
        if cache_key not in self._index_cache:
            logger.info(f">>> Loading v3 compressed index from {index_file}")
            t0 = time.time()
            self._index_cache[cache_key] = CompressedIndex(index_file)
            t_read_index = (time.time() - t0) * 1000
            logger.info(f">>> Compressed index loaded in {t_read_index:.1f}ms")
        else:
            logger.debug(f">>> Using cached index for {cache_key}")

        index = self._index_cache[cache_key]
        t_index_total = (time.time() - t_index_start) * 1000
        logger.debug(f">>> Index cache operations took {t_index_total:.1f}ms")

        t_readops_start = time.time()
        logger.debug(f"Building read_ops for {len(tile_ids)} tiles...")

        # Collect all tile read operations from v3 compressed index
        read_ops: List[Tuple[int, Dict[str, int]]] = []
        missing_tiles = 0
        for tile_id in tile_ids:
            # Ensure tile_id is a Python int (not numpy.int64)
            tile_id_int = int(tile_id)
            tile_tuple = index.get(tile_id_int)
            if tile_tuple:
                offset, size = tile_tuple
                read_ops.append((tile_id_int, {"offset": offset, "size": size}))
            else:
                missing_tiles += 1

        if missing_tiles > 0:
            logger.debug(
                f"{missing_tiles} of {len(tile_ids)} tiles missing from index for mag {mag_min}-{mag_max}"
            )

        if not read_ops:
            logger.debug(
                f"No tiles to load (all {len(tile_ids)} requested tiles are empty)"
            )
            return np.empty((0, 3))

        # Sort by offset to minimize seeks
        read_ops.sort(key=lambda x: x[1]["offset"])
        t_readops = (time.time() - t_readops_start) * 1000
        logger.debug(f"Built {len(read_ops)} read_ops in {t_readops:.1f}ms")

        # Read data in larger sequential chunks when possible
        MAX_GAP = 100 * 1024  # 100KB gap tolerance

        # Accumulate arrays
        all_ras = []
        all_decs = []
        all_mags = []
        all_pmras = []
        all_pmdecs = []

        t_io_start = time.time()
        t_decode_total = 0.0
        bytes_read = 0
        logger.debug(f"Batch loading {len(read_ops)} tiles for mag {mag_min}-{mag_max}")
        with open(tiles_file, "rb") as f:
            i = 0
            chunk_num = 0
            while i < len(read_ops):
                chunk_num += 1
                # logger.debug(f">>> Processing chunk {chunk_num}, tile {i+1}/{len(read_ops)}")

                tile_id, tile_info = read_ops[i]
                offset = tile_info["offset"]
                chunk_end = offset + tile_info["size"]

                # Find consecutive tiles for chunk reading
                tiles_in_chunk: List[Tuple[int, Dict[str, int]]] = [
                    (tile_id, tile_info)
                ]
                j = i + 1
                inner_iterations = 0
                while j < len(read_ops):
                    inner_iterations += 1
                    if inner_iterations > 1000:
                        logger.error(
                            f">>> INFINITE LOOP DETECTED in chunk consolidation! j={j}, len={len(read_ops)}, i={i}"
                        )
                        break  # Safety break

                    next_tile_id, next_tile_info = read_ops[j]
                    next_offset = next_tile_info["offset"]
                    if next_offset - chunk_end <= MAX_GAP:
                        chunk_end = next_offset + next_tile_info["size"]
                        tiles_in_chunk.append((next_tile_id, next_tile_info))
                        j += 1
                    else:
                        break

                # Read entire chunk
                chunk_size = chunk_end - offset
                # logger.debug(f">>> Reading chunk: {len(tiles_in_chunk)} tiles, size={chunk_size} bytes")
                f.seek(offset)
                chunk_data = f.read(chunk_size)
                bytes_read += chunk_size
                # logger.debug(f">>> Chunk read complete, processing tiles...")

                # Process each tile in chunk
                for tile_idx, (tile_id, tile_info) in enumerate(tiles_in_chunk):
                    # logger.debug(f">>> Processing tile {tile_idx+1}/{len(tiles_in_chunk)} (id={tile_id})")
                    tile_offset = tile_info["offset"] - offset
                    size = tile_info["size"]
                    data = chunk_data[tile_offset : tile_offset + size]

                    # Parse records using shared helper
                    t_decode_start = time.time()
                    ras, decs, mags, pmras, pmdecs = self._parse_records(data)
                    t_decode_total += time.time() - t_decode_start

                    # Filter by magnitude
                    mask = mags <= mag_limit

                    if np.any(mask):
                        all_ras.append(ras[mask])
                        all_decs.append(decs[mask])
                        all_mags.append(mags[mask])
                        all_pmras.append(pmras[mask])
                        all_pmdecs.append(pmdecs[mask])

                i = j

        if not all_ras:
            return np.empty((0, 3))

        # Concatenate all arrays
        t_concat_start = time.time()
        ras_final = np.concatenate(all_ras)
        decs_final = np.concatenate(all_decs)
        mags_final = np.concatenate(all_mags)
        pmras_final = np.concatenate(all_pmras)
        pmdecs_final = np.concatenate(all_pmdecs)
        (time.time() - t_concat_start) * 1000

        # Apply proper motion
        t_pm_start = time.time()
        result = self._apply_proper_motion(
            (ras_final, decs_final, mags_final, pmras_final, pmdecs_final)
        )
        (time.time() - t_pm_start) * 1000

        # Log performance breakdown
        t_io_total = (time.time() - t_io_start) * 1000
        logger.debug(
            f"Tile I/O for mag {mag_min}-{mag_max}: "
            f"{t_io_total:.1f}ms, {len(result)} stars, {bytes_read / 1024:.1f}KB"
        )

        return result

    def _load_tiles_batch(self, tile_ids: List[int], mag_limit: float) -> np.ndarray:
        """
        Batch load multiple tiles efficiently (compact format only)
        Much faster than loading tiles one-by-one due to reduced I/O overhead

        Args:
            tile_ids: List of HEALPix tile IDs
            mag_limit: Maximum magnitude

        Returns:
            Numpy array of shape (N, 3) containing (ra, dec, mag)
        """
        assert self.metadata is not None, (
            "metadata must be loaded before calling _load_tiles_batch"
        )

        if not _HEALPY_AVAILABLE:
            return np.empty((0, 3))

        all_ras = []
        all_decs = []
        all_mags = []
        all_pmras = []
        all_pmdecs = []

        logger.info(f"_load_tiles_batch: Starting batch load of {len(tile_ids)} tiles")

        # Process each magnitude band
        for mag_band_info in self.metadata.get("mag_bands", []):
            mag_min = mag_band_info["min"]
            mag_max = mag_band_info["max"]

            if mag_min >= mag_limit:
                continue  # Skip faint bands

            logger.info(f"_load_tiles_batch: Processing mag band {mag_min}-{mag_max}")
            band_dir = self.catalog_path / f"mag_{mag_min:02.0f}_{mag_max:02.0f}"
            index_file = band_dir / "index.bin"
            tiles_file = band_dir / "tiles.bin"

            if not tiles_file.exists():
                continue

            if not index_file.exists():
                raise FileNotFoundError(
                    f"Compressed index not found: {index_file}\n"
                    f"This catalog requires v3 format. Please rebuild using healpix_builder_compact.py"
                )

            # Load v3 compressed index
            cache_key = f"index_{mag_min}_{mag_max}"
            if not hasattr(self, "_index_cache"):
                self._index_cache = {}

            if cache_key not in self._index_cache:
                self._index_cache[cache_key] = CompressedIndex(index_file)

            index = self._index_cache[cache_key]

            # Collect all tile read operations from v3 compressed index
            read_ops = []
            for tile_id in tile_ids:
                tile_tuple = index.get(tile_id)
                if tile_tuple:
                    offset, size = tile_tuple
                    read_ops.append((tile_id, {"offset": offset, "size": size}))

            if not read_ops:
                continue

            logger.info(
                f"_load_tiles_batch: Found {len(read_ops)} tiles in mag band {mag_min}-{mag_max}"
            )

            # Sort by offset to minimize seeks
            read_ops.sort(key=lambda x: x[1]["offset"])

            # Optimize: Read data in larger sequential chunks when possible
            # Group tiles that are close together (within 100KB)
            MAX_GAP = 100 * 1024  # 100KB gap tolerance

            logger.info(f"_load_tiles_batch: Opening {tiles_file}")
            # Open file once and read all tiles
            with open(tiles_file, "rb") as f:
                i = 0
                while i < len(read_ops):
                    tile_id, tile_info = read_ops[i]
                    offset = tile_info["offset"]
                    size = tile_info["size"]

                    # Check if next tiles are sequential (within gap tolerance)
                    chunk_end = offset + size
                    tiles_in_chunk = [(tile_id, tile_info)]

                    j = i + 1
                    while j < len(read_ops):
                        next_tile_id, next_tile_info = read_ops[j]
                        next_offset = next_tile_info["offset"]

                        # If next tile is within gap tolerance, include in chunk
                        if next_offset - chunk_end <= MAX_GAP:
                            tiles_in_chunk.append((next_tile_id, next_tile_info))
                            next_size = next_tile_info["size"]
                            chunk_end = next_offset + next_size
                            j += 1
                        else:
                            break

                    # Read entire chunk at once
                    chunk_size = chunk_end - offset
                    logger.info(
                        f"_load_tiles_batch: Reading chunk at offset {offset}, size {chunk_size / 1024:.1f}KB with {len(tiles_in_chunk)} tiles"
                    )
                    f.seek(offset)
                    chunk_data = f.read(chunk_size)
                    logger.info(
                        f"_load_tiles_batch: Read complete, processing {len(tiles_in_chunk)} tiles"
                    )

                    # Process each tile in the chunk using vectorized operations
                    for tile_id, tile_info in tiles_in_chunk:
                        tile_offset = (
                            tile_info["offset"] - offset
                        )  # Relative offset in chunk
                        size = tile_info["size"]
                        data = chunk_data[tile_offset : tile_offset + size]

                        # Parse records using shared helper
                        ras, decs, mags, pmras, pmdecs = self._parse_records(data)

                        # Filter by magnitude
                        mask = mags <= mag_limit

                        if np.any(mask):
                            all_ras.append(ras[mask])
                            all_decs.append(decs[mask])
                            all_mags.append(mags[mask])
                            all_pmras.append(pmras[mask])
                            all_pmdecs.append(pmdecs[mask])

                    # Move to next chunk
                    i = j

        logger.info(
            f"_load_tiles_batch: Loaded {len(all_ras)} batches of stars, applying proper motion"
        )

        if not all_ras:
            return np.empty((0, 3))

        # Concatenate all arrays
        ras_final = np.concatenate(all_ras)
        decs_final = np.concatenate(all_decs)
        mags_final = np.concatenate(all_mags)
        pmras_final = np.concatenate(all_pmras)
        pmdecs_final = np.concatenate(all_pmdecs)

        # Apply proper motion
        result = self._apply_proper_motion(
            (ras_final, decs_final, mags_final, pmras_final, pmdecs_final)
        )
        logger.info(f"_load_tiles_batch: Complete, returning {len(result)} stars")
        return result
