#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
HEALPix-indexed star catalog loader with background loading and CPU throttling

This module provides efficient loading of deep star catalogs for chart generation.
Features:
- Background loading with thread safety
- CPU throttling to avoid blocking other processes
- LRU tile caching
- Hemisphere filtering for memory efficiency
- Proper motion corrections
"""

import json
import logging
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

# Star record format (must match healpix_builder.py)
STAR_RECORD_FORMAT = "<IBBBbb"
STAR_RECORD_SIZE = 9

# Numpy dtype for efficient batch parsing
# Format: <I (uint32), B (uint8), B (uint8), B (uint8), b (int8), b (int8)
STAR_RECORD_DTYPE = np.dtype([
    ('healpix', '<u4'),      # HEALPix pixel ID (24-bit, upper 8 bits unused)
    ('ra_offset', 'u1'),     # RA offset encoded 0-255
    ('dec_offset', 'u1'),    # Dec offset encoded 0-255
    ('mag', 'u1'),           # Magnitude * 10
    ('pmra', 'i1'),          # Proper motion RA (mas/yr / 50)
    ('pmdec', 'i1'),         # Proper motion Dec (mas/yr / 50)
])


class CatalogState(Enum):
    """Catalog loading state"""

    NOT_LOADED = 0
    LOADING = 1
    READY = 2


class DeepStarCatalog:
    """
    HEALPix-indexed star catalog with background loading

    Usage:
        catalog = DeepStarCatalog("/path/to/deep_stars")
        catalog.start_background_load(observer_lat=40.0, limiting_mag=14.0)
        # ... wait for catalog.state == CatalogState.READY ...
        stars = catalog.get_stars_for_fov(ra=180.0, dec=45.0, fov=10.0, mag_limit=12.0)
    """

    def __init__(self, catalog_path: str):
        """
        Initialize catalog (doesn't load data yet)

        Args:
            catalog_path: Path to deep_stars directory containing metadata.json
        """
        logger.info(f">>> DeepStarCatalog.__init__() called with path: {catalog_path}")
        t0 = time.time()
        self.catalog_path = Path(catalog_path)
        self.state = CatalogState.NOT_LOADED
        self.metadata: Optional[Dict[str, Any]] = None
        self.nside: Optional[int] = None
        self.observer_lat: Optional[float] = None
        self.limiting_magnitude: float = 12.0
        self.visible_tiles: Optional[Set[int]] = None
        self.spatial_index: Optional[Any] = None
        self.tile_cache: Dict[Tuple[int, float], List[Tuple[float, float, float, float, float]]] = {}
        self.cache_lock = threading.Lock()
        self.load_thread: Optional[threading.Thread] = None
        self.load_progress: str = ""  # Status message for UI
        self.load_percent: int = 0  # Progress percentage (0-100)
        self._index_cache: Dict[str, Any] = {}
        t_init = (time.time() - t0) * 1000
        logger.info(f">>> DeepStarCatalog.__init__() completed in {t_init:.1f}ms")

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
            logger.warning(f">>> Catalog already loading or loaded (state={self.state}), skipping")
            return

        logger.info(f">>> Starting background load: lat={observer_lat}, mag={limiting_mag}, path={self.catalog_path}")

        self.state = CatalogState.LOADING
        self.observer_lat = observer_lat
        self.limiting_magnitude = limiting_mag

        # Start background thread
        logger.info(">>> Creating background thread...")
        self.load_thread = threading.Thread(
            target=self._background_load_worker, daemon=True, name="CatalogLoader"
        )
        self.load_thread.start()
        logger.info(f">>> Background thread started, thread alive: {self.load_thread.is_alive()}")

    def _background_load_worker(self):
        """Background worker - just loads metadata"""
        logger.info(">>> _background_load_worker() started")
        t_worker_start = time.time()
        try:
            # Load metadata
            self.load_progress = "Loading..."
            self.load_percent = 50
            logger.info(f">>> Loading catalog metadata from {self.catalog_path}")

            metadata_file = self.catalog_path / "metadata.json"

            if not metadata_file.exists():
                logger.error(f">>> Catalog metadata not found: {metadata_file}")
                logger.error(f">>> Please build catalog using: python -m PiFinder.catalog_tools.gaia_downloader")
                self.load_progress = "Error: catalog not built"
                self.state = CatalogState.NOT_LOADED
                return

            t0 = time.time()
            with open(metadata_file, "r") as f:
                self.metadata = json.load(f)
            t_json = (time.time() - t0) * 1000
            logger.info(f">>> metadata.json loaded in {t_json:.1f}ms")

            self.nside = self.metadata.get("nside", 512)
            star_count = self.metadata.get('star_count', 0)
            logger.info(
                f">>> Catalog metadata ready: {star_count:,} stars, "
                f"mag limit {self.metadata.get('mag_limit', 0):.1f}, nside={self.nside}"
            )

            # Initialize empty structures (no preloading)
            self.spatial_index = {}
            self.visible_tiles = None  # Load full sky on-demand

            # Mark ready
            self.load_progress = "Ready"
            self.load_percent = 100
            self.state = CatalogState.READY
            t_worker_total = (time.time() - t_worker_start) * 1000
            logger.info(f">>> _background_load_worker() completed in {t_worker_total:.1f}ms, state: {self.state}")

        except Exception as e:
            logger.error(f">>> Catalog loading failed: {e}", exc_info=True)
            self.load_progress = f"Error: {str(e)}"
            self.state = CatalogState.NOT_LOADED

    def _load_binary_spatial_index(self, bin_path: Path) -> dict:
        """
        Load binary spatial index

        Binary format:
        - Header: [version: 4][num_tiles: 4][nside: 4]
        - Per tile: [tile_id: 4][num_bands: 1][bands: (mag_min:1, mag_max:1)*num_bands]

        Returns:
            Dict mapping tile_id -> [(mag_min, mag_max), ...]
        """
        with open(bin_path, "rb") as f:
            # Read header
            header = f.read(12)
            version, num_tiles, nside = struct.unpack("<III", header)

            if version != 1:
                logger.error(f"Unsupported spatial index version: {version}")
                return {}

            # Read tiles
            index = {}
            for _ in range(num_tiles):
                tile_data = f.read(5)
                if len(tile_data) < 5:
                    break

                tile_id, num_bands = struct.unpack("<IB", tile_data)
                bands = []

                for _ in range(num_bands):
                    band_data = f.read(2)
                    if len(band_data) < 2:
                        break
                    mag_min, mag_max = struct.unpack("<BB", band_data)
                    bands.append((mag_min, mag_max))

                index[tile_id] = bands

        return index

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

        Blocks if state == LOADING (waits for load to complete)
        Returns empty list if state == NOT_LOADED

        Args:
            ra_deg: Center RA in degrees
            dec_deg: Center Dec in degrees
            fov_deg: Field of view in degrees
            mag_limit: Limiting magnitude (uses catalog default if None)

        Yields:
            (stars, is_complete) tuples where:
                - stars: List of (ra, dec, mag) tuples with proper motion corrected
                - is_complete: True if this is the final yield with all stars
        """
        if self.state == CatalogState.NOT_LOADED:
            logger.warning("Catalog not loaded")
            yield ([], True)
            return

        # Wait for catalog to be loaded
        while self.state == CatalogState.LOADING:
            import time
            time.sleep(0.1)

        if mag_limit is None:
            mag_limit = self.metadata.get("mag_limit", 17.0) if self.metadata else 17.0

        if not _HEALPY_AVAILABLE:
            logger.error("healpy not available - cannot perform HEALPix queries")
            yield ([], True)
            return

        # Calculate HEALPix tiles covering FOV
        vec = hp.ang2vec(ra_deg, dec_deg, lonlat=True)
        radius_rad = np.radians(fov_deg * 0.85)
        tiles = hp.query_disc(self.nside, vec, radius_rad)
        logger.info(f"HEALPix PROGRESSIVE: Querying {len(tiles)} tiles for FOV={fov_deg:.2f}° at nside={self.nside}")

        # Filter by visible hemisphere
        if self.visible_tiles:
            tiles = [t for t in tiles if t in self.visible_tiles]

        # Limit tile count to prevent excessive loading
        # For small FOVs (<1°), 20-30 tiles is more than enough
        MAX_TILES = 25
        if len(tiles) > MAX_TILES:
            logger.warning(f"Large tile count ({len(tiles)}) detected! Limiting to {MAX_TILES} tiles")
            tiles = tiles[:MAX_TILES]

        # Load stars progressively by magnitude band (bright to faint)
        all_stars = []

        if not self.metadata:
            yield ([], True)
            return

        for mag_band_info in self.metadata.get("mag_bands", []):
            mag_min = mag_band_info["min"]
            mag_max = mag_band_info["max"]

            # Skip bands fainter than limit
            if mag_min >= mag_limit:
                break

            logger.info(f"PROGRESSIVE: Loading mag band {mag_min}-{mag_max}")
            import time
            t_band_start = time.time()

            # Load stars from this magnitude band only
            band_stars = self._load_tiles_for_mag_band(
                tiles, mag_band_info, mag_limit, ra_deg, dec_deg, fov_deg
            )

            t_band_end = time.time()
            logger.info(f"PROGRESSIVE: Mag band {mag_min}-{mag_max} loaded {len(band_stars)} stars in {(t_band_end-t_band_start)*1000:.1f}ms")

            # Add to cumulative list
            all_stars.extend(band_stars)

            # Yield current results (not complete yet unless this is the last band)
            is_last_band = mag_max >= mag_limit
            yield (all_stars.copy(), is_last_band)

            if is_last_band:
                break

        # Final yield (should already be done above, but just in case)
        logger.info(f"PROGRESSIVE: Complete! Total {len(all_stars)} stars loaded")

    def get_stars_for_fov(
        self,
        ra_deg: float,
        dec_deg: float,
        fov_deg: float,
        mag_limit: Optional[float] = None,
    ) -> List[Tuple[float, float, float]]:
        """
        Query stars in field of view

        Blocks if state == LOADING (waits for load to complete)
        Returns empty list if state == NOT_LOADED

        Args:
            ra_deg: Center RA in degrees
            dec_deg: Center Dec in degrees
            fov_deg: Field of view in degrees
            mag_limit: Limiting magnitude (uses catalog default if None)

        Returns:
            List of (ra, dec, mag) tuples with proper motion corrected
        """
        if self.state == CatalogState.NOT_LOADED:
            logger.warning("Catalog not loaded")
            return []

        if self.state == CatalogState.LOADING:
            # Wait for loading to complete (with timeout)
            logger.info("Waiting for catalog to finish loading...")
            timeout = 30  # seconds
            start = time.time()
            while self.state == CatalogState.LOADING:
                time.sleep(0.1)
                if time.time() - start > timeout:
                    logger.error("Catalog loading timeout")
                    return []

        # State is READY - metadata must be loaded by now
        assert self.metadata is not None, "metadata should be loaded when state is READY"
        assert self.nside is not None, "nside should be set when state is READY"

        mag_limit = mag_limit or self.limiting_magnitude

        if not _HEALPY_AVAILABLE:
            logger.error("healpy not installed")
            return []

        # Calculate HEALPix tiles covering FOV
        # Query larger area to account for rectangular screen and rotation
        # Diagonal of square is sqrt(2) * side, with rotation could be any angle
        vec = hp.ang2vec(ra_deg, dec_deg, lonlat=True)
        # Use full diagonal + margin to ensure corners are covered even when rotated
        radius_rad = np.radians(fov_deg * 0.85)  # sqrt(2)/2 ≈ 0.707, add extra for rotation
        tiles = hp.query_disc(self.nside, vec, radius_rad)
        logger.info(f"HEALPix: Querying {len(tiles)} tiles for FOV={fov_deg:.2f}° at nside={self.nside}")

        # Filter by visible hemisphere
        if self.visible_tiles:
            tiles = [t for t in tiles if t in self.visible_tiles]

        # Load stars from tiles (batch load for better performance)
        stars: List[Tuple[float, float, float]] = []
        tile_star_counts = {}

        # Try batch loading if catalog is compact format
        # Only batch for moderate tile counts (10-50) to avoid UI blocking
        is_compact = self.metadata.get("format") == "compact"
        if is_compact and 10 < len(tiles) <= 50:
            # Batch load is much faster for many tiles
            # Note: batch loading returns PM-corrected (ra, dec, mag) tuples
            logger.info(f"Using BATCH loading for {len(tiles)} tiles")
            import time
            t_batch_start = time.time()
            stars = self._load_tiles_batch(tiles, mag_limit)
            t_batch_end = time.time()
            logger.info(f"Batch load complete: {len(stars)} stars in {(t_batch_end-t_batch_start)*1000:.1f}ms")
            tile_star_counts = {t: 0 for t in tiles}  # Don't track individual counts for batch
        else:
            # Load one by one (better for small queries or legacy format)
            logger.info(f"Using SINGLE-TILE loading for {len(tiles)} tiles (compact={is_compact})")
            import time
            t_single_start = time.time()
            stars_raw: List[Tuple[float, float, float, float, float]] = []

            # To prevent UI blocking, limit the number of tiles loaded at once
            # For small FOVs (<1°), 20-30 tiles is more than enough
            MAX_TILES = 25
            if len(tiles) > MAX_TILES:
                logger.warning(f"Large tile count ({len(tiles)}) detected! Limiting to {MAX_TILES} tiles to prevent UI freeze")
                # Tiles from query_disc are roughly ordered by distance from center
                # Keep the first MAX_TILES which are closest to FOV center
                tiles = tiles[:MAX_TILES]

            cache_hits = 0
            cache_misses = 0

            for i, tile_id in enumerate(tiles):
                # Check if this tile is cached (for performance tracking)
                cache_key = (tile_id, mag_limit)
                was_cached = cache_key in self.tile_cache

                tile_stars = self._load_tile_data(tile_id, mag_limit)
                tile_star_counts[tile_id] = len(tile_stars)
                stars_raw.extend(tile_stars)

                if was_cached:
                    cache_hits += 1
                else:
                    cache_misses += 1

                # Log progress every 25 tiles
                if (i + 1) % 25 == 0:
                    elapsed = (time.time() - t_single_start) * 1000
                    logger.info(f"Progress: {i+1}/{len(tiles)} tiles loaded ({elapsed:.0f}ms elapsed)")

            t_single_end = time.time()
            elapsed_ms = (t_single_end - t_single_start) * 1000

            # Log cache performance
            logger.info(f"Tile cache: {cache_hits} hits, {cache_misses} misses ({cache_hits/(cache_hits+cache_misses)*100:.1f}% hit rate)")
            logger.info(f"Single-tile loading complete: {len(stars_raw)} stars in {elapsed_ms:.1f}ms ({elapsed_ms/len(tiles):.2f}ms/tile)")

            # Log tile loading stats
            if tile_star_counts:
                logger.debug(f"Loaded from {len(tile_star_counts)} tiles: " +
                            f"min={min(tile_star_counts.values())} max={max(tile_star_counts.values())} " +
                            f"total={sum(tile_star_counts.values())}")

            # Apply proper motion correction (for non-batch path only)
            t_pm_start = time.time()
            stars = self._apply_proper_motion(stars_raw)
            t_pm_end = time.time()
            logger.info(f"Proper motion correction: {len(stars)} stars in {(t_pm_end-t_pm_start)*1000:.1f}ms")

        return stars

    def _load_tiles_for_mag_band(
        self,
        tile_ids: List[int],
        mag_band_info: dict,
        mag_limit: float,
        ra_deg: float,
        dec_deg: float,
        fov_deg: float,
    ) -> List[Tuple[float, float, float]]:
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
            List of (ra, dec, mag) tuples with proper motion corrected
        """
        mag_min = mag_band_info["min"]
        mag_max = mag_band_info["max"]
        band_dir = self.catalog_path / f"mag_{mag_min:02.0f}_{mag_max:02.0f}"

        # Check if this band directory exists
        if not band_dir.exists():
            logger.debug(f"Magnitude band directory not found: {band_dir}")
            return []

        # For compact format, use vectorized batch loading per band
        assert self.metadata is not None, "metadata must be loaded"
        is_compact = self.metadata.get("format") == "compact"
        if is_compact:
            return self._load_tiles_batch_single_band(
                tile_ids, mag_band_info, mag_limit
            )
        else:
            # Legacy format - load tiles one by one (will load all bands for each tile)
            # This is less efficient but legacy format doesn't support per-band loading
            stars_raw = []
            for tile_id in tile_ids:
                tile_stars = self._load_tile_data(tile_id, mag_limit)
                # Filter to just this magnitude band
                tile_stars_filtered = [
                    (ra, dec, mag, pmra, pmdec)
                    for ra, dec, mag, pmra, pmdec in tile_stars
                    if mag_min <= mag < mag_max
                ]
                stars_raw.extend(tile_stars_filtered)

            # Apply proper motion
            return self._apply_proper_motion(stars_raw)

    def _load_tile_data(
        self, tile_id: int, mag_limit: float
    ) -> List[Tuple[float, float, float, float, float]]:
        """
        Load star data for a HEALPix tile

        Args:
            tile_id: HEALPix tile ID
            mag_limit: Maximum magnitude to load

        Returns:
            List of (ra, dec, mag, pmra, pmdec) tuples
        """
        assert self.metadata is not None, "metadata must be loaded before calling _load_tile_data"

        cache_key = (tile_id, mag_limit)

        # Check cache
        with self.cache_lock:
            if cache_key in self.tile_cache:
                return self.tile_cache[cache_key]

        # Load from disk
        stars = []

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
                tile_stars = self._load_tile_compact(band_dir, tile_id, mag_min, mag_max)
            else:
                # Legacy format: one file per tile
                tile_file = band_dir / f"tile_{tile_id:06d}.bin"
                if tile_file.exists():
                    tile_stars = self._load_tile_from_file(tile_file, mag_min, mag_max)
                else:
                    tile_stars = []

            # Filter by magnitude
            tile_stars = [s for s in tile_stars if s[2] <= mag_limit]
            stars.extend(tile_stars)

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
    ) -> List[Tuple[float, float, float, float, float]]:
        """
        Load stars from a tile file

        Args:
            tile_file: Path to tile binary file
            mag_min: Minimum magnitude in this band
            mag_max: Maximum magnitude in this band

        Returns:
            List of (ra, dec, mag, pmra, pmdec) tuples
        """
        if not _HEALPY_AVAILABLE:
            return []

        # Read entire file at once
        with open(tile_file, "rb") as f:
            data = f.read()

        if len(data) == 0:
            return []

        # VECTORIZED: Parse all records at once
        num_records = len(data) // STAR_RECORD_SIZE
        records = np.frombuffer(data, dtype=STAR_RECORD_DTYPE, count=num_records)

        # Mask healpix to 24 bits
        healpix_pixels = records['healpix'] & 0xFFFFFF

        # VECTORIZED: Get all pixel centers at once
        pixel_ras, pixel_decs = hp.pix2ang(self.nside, healpix_pixels, lonlat=True)

        # Calculate pixel size once (not per star!)
        pixel_size_deg = np.sqrt(hp.nside2pixarea(self.nside, degrees=True))
        max_offset_arcsec = pixel_size_deg * 3600.0 / 2.0

        # VECTORIZED: Decode all offsets at once
        ra_offset_arcsec = (records['ra_offset'] / 127.5 - 1.0) * max_offset_arcsec
        dec_offset_arcsec = (records['dec_offset'] / 127.5 - 1.0) * max_offset_arcsec

        # VECTORIZED: Calculate final positions
        decs = pixel_decs + dec_offset_arcsec / 3600.0
        ras = pixel_ras + ra_offset_arcsec / 3600.0 / np.cos(np.radians(decs))

        # VECTORIZED: Decode magnitudes and proper motions
        mags = records['mag'] / 10.0
        pmras = records['pmra'] * 50
        pmdecs = records['pmdec'] * 50

        # Build result list
        stars = [(ras[i], decs[i], mags[i], pmras[i], pmdecs[i]) for i in range(num_records)]

        return stars

    def _load_tile_compact(
        self, band_dir: Path, tile_id: int, mag_min: float, mag_max: float
    ) -> List[Tuple[float, float, float, float, float]]:
        """
        Load stars from compact format (consolidated tiles.bin + index.json)

        Args:
            band_dir: Magnitude band directory
            tile_id: HEALPix tile ID
            mag_min: Minimum magnitude
            mag_max: Maximum magnitude

        Returns:
            List of (ra, dec, mag, pmra, pmdec) tuples
        """
        if not _HEALPY_AVAILABLE:
            return []

        # Try binary index first, fall back to JSON for backward compat
        index_file_bin = band_dir / "index.bin"
        index_file_json = band_dir / "index.json"
        tiles_file = band_dir / "tiles.bin"

        if not tiles_file.exists():
            return []

        # Determine index format
        if index_file_bin.exists():
            index_file = index_file_bin
            is_binary = True
        elif index_file_json.exists():
            index_file = index_file_json
            is_binary = False
        else:
            return []

        # Load index (cached per band)
        tile_key = str(tile_id)

        cache_key = f"index_{mag_min}_{mag_max}"
        if cache_key not in self._index_cache:
            if is_binary:
                self._index_cache[cache_key] = self._read_binary_index(index_file)
            else:
                with open(index_file, "r") as f:
                    self._index_cache[cache_key] = json.load(f)

        index = self._index_cache[cache_key]

        if tile_key not in index:
            return []  # No stars in this tile

        # Get tile offset and size
        tile_info = index[tile_key]
        offset = tile_info["offset"]
        size = tile_info["size"]
        compressed_size = tile_info.get("compressed_size")

        # Read tile data
        stars = []
        with open(tiles_file, "rb") as f:
            f.seek(offset)

            if compressed_size:
                # Compressed tile - decompress in memory
                import zlib
                compressed_data = f.read(compressed_size)
                data = zlib.decompress(compressed_data)
            else:
                # Uncompressed tile
                data = f.read(size)

            # VECTORIZED: Decode all records in this tile at once
            num_records = len(data) // STAR_RECORD_SIZE

            # Parse all records using numpy
            records = np.frombuffer(data, dtype=STAR_RECORD_DTYPE, count=num_records)

            # Mask healpix to 24 bits
            healpix_pixels = records['healpix'] & 0xFFFFFF

            # VECTORIZED: Get all pixel centers at once
            pixel_ras, pixel_decs = hp.pix2ang(self.nside, healpix_pixels, lonlat=True)

            # Calculate pixel size once (not per star!)
            pixel_size_deg = np.sqrt(hp.nside2pixarea(self.nside, degrees=True))
            max_offset_arcsec = pixel_size_deg * 3600.0 / 2.0

            # VECTORIZED: Decode all offsets at once
            ra_offset_arcsec = (records['ra_offset'] / 127.5 - 1.0) * max_offset_arcsec
            dec_offset_arcsec = (records['dec_offset'] / 127.5 - 1.0) * max_offset_arcsec

            # VECTORIZED: Calculate final positions
            decs = pixel_decs + dec_offset_arcsec / 3600.0
            ras = pixel_ras + ra_offset_arcsec / 3600.0 / np.cos(np.radians(decs))

            # VECTORIZED: Decode magnitudes and proper motions
            mags = records['mag'] / 10.0
            pmras = records['pmra'] * 50
            pmdecs = records['pmdec'] * 50

            # Build result list
            stars = [(ras[i], decs[i], mags[i], pmras[i], pmdecs[i]) for i in range(num_records)]

        return stars

    def _read_binary_index(self, index_file: Path) -> dict:
        """
        Read binary index file

        Format v1 (uncompressed):
            Header: [version:4][num_tiles:4]
            Per tile: [tile_id:4][offset:8][size:4]

        Format v2 (compressed):
            Header: [version:4][num_tiles:4]
            Per tile: [tile_id:4][offset:8][compressed_size:4][uncompressed_size:4]

        Returns:
            Dict mapping tile_id (as string) -> {"offset": int, "size": int, "compressed_size": int (optional)}
        """
        index = {}

        with open(index_file, "rb") as f:
            # Read header
            header = f.read(8)
            version, num_tiles = struct.unpack("<II", header)

            if version == 1:
                # Uncompressed format
                for _ in range(num_tiles):
                    tile_data = f.read(16)
                    if len(tile_data) < 16:
                        break

                    tile_id, offset, size = struct.unpack("<IQI", tile_data)
                    index[str(tile_id)] = {"offset": offset, "size": size}

            elif version == 2:
                # Compressed format
                for _ in range(num_tiles):
                    tile_data = f.read(20)
                    if len(tile_data) < 20:
                        break

                    tile_id, offset, compressed_size, uncompressed_size = struct.unpack("<IQII", tile_data)
                    index[str(tile_id)] = {
                        "offset": offset,
                        "size": uncompressed_size,
                        "compressed_size": compressed_size
                    }

            else:
                logger.error(f"Unsupported index version: {version}")
                return {}

        return index

    def _apply_proper_motion(
        self, stars: List[Tuple[float, float, float, float, float]]
    ) -> List[Tuple[float, float, float]]:
        """
        Apply proper motion corrections from J2016.0 to current epoch

        Shows stars at their current positions in the sky (today), not historical
        J2000 positions. This provides the most accurate representation for
        real-time telescope pointing.

        Args:
            stars: List of (ra, dec, mag, pmra, pmdec) tuples in J2016.0

        Returns:
            List of (ra, dec, mag) tuples with positions corrected to current epoch
        """
        # Calculate years from J2016.0 to current date
        current_year = datetime.now().year + (datetime.now().timetuple().tm_yday / 365.25)
        years_elapsed = current_year - 2016.0

        corrected = []
        for ra, dec, mag, pmra, pmdec in stars:
            # Apply proper motion forward to current epoch
            # pmra is in mas/year and needs cos(dec) correction for RA
            ra_correction = (pmra / 1000 / 3600) / np.cos(np.radians(dec)) * years_elapsed
            dec_correction = (pmdec / 1000 / 3600) * years_elapsed

            ra_corrected = ra + ra_correction
            dec_corrected = dec + dec_correction

            # Keep dec in valid range
            dec_corrected = max(-90, min(90, dec_corrected))

            corrected.append((ra_corrected, dec_corrected, mag))

        return corrected

    def _load_tiles_batch_single_band(
        self,
        tile_ids: List[int],
        mag_band_info: dict,
        mag_limit: float,
    ) -> List[Tuple[float, float, float]]:
        """
        Batch load multiple tiles for a SINGLE magnitude band (compact format only)
        Used by progressive loading to load one mag band at a time

        Args:
            tile_ids: List of HEALPix tile IDs
            mag_band_info: Magnitude band metadata dict
            mag_limit: Maximum magnitude

        Returns:
            List of (ra, dec, mag) tuples (already PM-corrected)
        """
        if not _HEALPY_AVAILABLE:
            return []

        mag_min = mag_band_info["min"]
        mag_max = mag_band_info["max"]

        band_dir = self.catalog_path / f"mag_{mag_min:02.0f}_{mag_max:02.0f}"
        index_file_bin = band_dir / "index.bin"
        index_file_json = band_dir / "index.json"
        tiles_file = band_dir / "tiles.bin"

        if not tiles_file.exists():
            return []

        # Load index
        cache_key = f"index_{mag_min}_{mag_max}"
        if not hasattr(self, '_index_cache'):
            self._index_cache = {}

        if cache_key not in self._index_cache:
            if index_file_bin.exists():
                self._index_cache[cache_key] = self._read_binary_index(index_file_bin)
            elif index_file_json.exists():
                with open(index_file_json, "r") as f:
                    self._index_cache[cache_key] = json.load(f)
            else:
                return []

        index = self._index_cache[cache_key]

        # Collect all tile read operations
        read_ops = []
        for tile_id in tile_ids:
            tile_key = str(tile_id)
            if tile_key in index:
                tile_info = index[tile_key]
                read_ops.append((tile_id, tile_info))

        if not read_ops:
            return []

        # Sort by offset to minimize seeks
        read_ops.sort(key=lambda x: x[1]["offset"])

        # Read data in larger sequential chunks when possible
        MAX_GAP = 100 * 1024  # 100KB gap tolerance
        all_stars = []

        logger.info(f">>> Batch loading {len(read_ops)} tiles for mag {mag_min}-{mag_max}")
        with open(tiles_file, "rb") as f:
            i = 0
            chunk_num = 0
            while i < len(read_ops):
                chunk_num += 1
                logger.debug(f">>> Processing chunk {chunk_num}, tile {i+1}/{len(read_ops)}")

                tile_id, tile_info = read_ops[i]
                offset = tile_info["offset"]
                chunk_end = offset + tile_info.get("compressed_size", tile_info["size"])

                # Find consecutive tiles for chunk reading
                tiles_in_chunk = [(tile_id, tile_info)]
                j = i + 1
                inner_iterations = 0
                while j < len(read_ops):
                    inner_iterations += 1
                    if inner_iterations > 1000:
                        logger.error(f">>> INFINITE LOOP DETECTED in chunk consolidation! j={j}, len={len(read_ops)}, i={i}")
                        break  # Safety break

                    next_tile_id, next_tile_info = read_ops[j]
                    next_offset = next_tile_info["offset"]
                    if next_offset - chunk_end <= MAX_GAP:
                        chunk_end = next_offset + next_tile_info.get("compressed_size", next_tile_info["size"])
                        tiles_in_chunk.append((next_tile_id, next_tile_info))
                        j += 1
                    else:
                        break

                # Read entire chunk
                chunk_size = chunk_end - offset
                logger.debug(f">>> Reading chunk: {len(tiles_in_chunk)} tiles, size={chunk_size} bytes")
                f.seek(offset)
                chunk_data = f.read(chunk_size)
                logger.debug(f">>> Chunk read complete, processing tiles...")

                # Process each tile in chunk
                for tile_idx, (tile_id, tile_info) in enumerate(tiles_in_chunk):
                    logger.debug(f">>> Processing tile {tile_idx+1}/{len(tiles_in_chunk)} (id={tile_id})")
                    tile_offset = tile_info["offset"] - offset
                    compressed_size = tile_info.get("compressed_size")
                    size = tile_info["size"]

                    if compressed_size:
                        import zlib
                        compressed_data = chunk_data[tile_offset:tile_offset + compressed_size]
                        data = zlib.decompress(compressed_data)
                    else:
                        data = chunk_data[tile_offset:tile_offset + size]

                    # VECTORIZED: Parse all star records at once
                    num_records = len(data) // STAR_RECORD_SIZE
                    records = np.frombuffer(data, dtype=STAR_RECORD_DTYPE, count=num_records)

                    # Mask healpix to 24 bits
                    healpix_pixels = records['healpix'] & 0xFFFFFF

                    # VECTORIZED: Get all pixel centers at once
                    pixel_ras, pixel_decs = hp.pix2ang(self.nside, healpix_pixels, lonlat=True)

                    # Calculate pixel size once
                    pixel_size_deg = np.sqrt(hp.nside2pixarea(self.nside, degrees=True))
                    max_offset_arcsec = pixel_size_deg * 3600.0 / 2.0

                    # VECTORIZED: Decode all offsets
                    ra_offset_arcsec = (records['ra_offset'] / 127.5 - 1.0) * max_offset_arcsec
                    dec_offset_arcsec = (records['dec_offset'] / 127.5 - 1.0) * max_offset_arcsec

                    # VECTORIZED: Calculate final positions
                    decs = pixel_decs + dec_offset_arcsec / 3600.0
                    ras = pixel_ras + ra_offset_arcsec / 3600.0 / np.cos(np.radians(decs))

                    # VECTORIZED: Decode magnitudes and proper motions
                    mags = records['mag'] / 10.0
                    pmras = records['pmra'] * 50
                    pmdecs = records['pmdec'] * 50

                    # Filter by magnitude
                    mag_mask = mags < mag_limit

                    # Collect stars
                    for idx in np.where(mag_mask)[0]:
                        all_stars.append((ras[idx], decs[idx], mags[idx], pmras[idx], pmdecs[idx]))

                i = j

        # Apply proper motion
        return self._apply_proper_motion(all_stars)

    def _load_tiles_batch(
        self, tile_ids: List[int], mag_limit: float
    ) -> List[Tuple[float, float, float]]:
        """
        Batch load multiple tiles efficiently (compact format only)
        Much faster than loading tiles one-by-one due to reduced I/O overhead

        Args:
            tile_ids: List of HEALPix tile IDs
            mag_limit: Maximum magnitude

        Returns:
            List of (ra, dec, mag) tuples (already PM-corrected)
        """
        assert self.metadata is not None, "metadata must be loaded before calling _load_tiles_batch"

        if not _HEALPY_AVAILABLE:
            return []

        all_stars = []

        logger.info(f"_load_tiles_batch: Starting batch load of {len(tile_ids)} tiles")

        # Process each magnitude band
        for mag_band_info in self.metadata.get("mag_bands", []):
            mag_min = mag_band_info["min"]
            mag_max = mag_band_info["max"]

            if mag_min >= mag_limit:
                continue  # Skip faint bands

            logger.info(f"_load_tiles_batch: Processing mag band {mag_min}-{mag_max}")
            band_dir = self.catalog_path / f"mag_{mag_min:02.0f}_{mag_max:02.0f}"
            index_file_bin = band_dir / "index.bin"
            index_file_json = band_dir / "index.json"
            tiles_file = band_dir / "tiles.bin"

            if not tiles_file.exists():
                continue

            # Load index
            cache_key = f"index_{mag_min}_{mag_max}"
            if not hasattr(self, '_index_cache'):
                self._index_cache = {}

            if cache_key not in self._index_cache:
                if index_file_bin.exists():
                    self._index_cache[cache_key] = self._read_binary_index(index_file_bin)
                elif index_file_json.exists():
                    with open(index_file_json, "r") as f:
                        self._index_cache[cache_key] = json.load(f)
                else:
                    continue

            index = self._index_cache[cache_key]

            # Collect all tile read operations
            read_ops = []
            for tile_id in tile_ids:
                tile_key = str(tile_id)
                if tile_key in index:
                    tile_info = index[tile_key]
                    read_ops.append((tile_id, tile_info))

            if not read_ops:
                continue

            logger.info(f"_load_tiles_batch: Found {len(read_ops)} tiles in mag band {mag_min}-{mag_max}")

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
                    compressed_size = tile_info.get("compressed_size")
                    size = tile_info["size"]

                    # Check if next tiles are sequential (within gap tolerance)
                    chunk_end = offset + (compressed_size or size)
                    tiles_in_chunk = [(tile_id, tile_info)]

                    j = i + 1
                    while j < len(read_ops):
                        next_tile_id, next_tile_info = read_ops[j]
                        next_offset = next_tile_info["offset"]

                        # If next tile is within gap tolerance, include in chunk
                        if next_offset - chunk_end <= MAX_GAP:
                            tiles_in_chunk.append((next_tile_id, next_tile_info))
                            next_size = next_tile_info.get("compressed_size") or next_tile_info["size"]
                            chunk_end = next_offset + next_size
                            j += 1
                        else:
                            break

                    # Read entire chunk at once
                    chunk_size = chunk_end - offset
                    logger.info(f"_load_tiles_batch: Reading chunk at offset {offset}, size {chunk_size/1024:.1f}KB with {len(tiles_in_chunk)} tiles")
                    f.seek(offset)
                    chunk_data = f.read(chunk_size)
                    logger.info(f"_load_tiles_batch: Read complete, processing {len(tiles_in_chunk)} tiles")

                    # Process each tile in the chunk using vectorized operations
                    for tile_id, tile_info in tiles_in_chunk:
                        tile_offset = tile_info["offset"] - offset  # Relative offset in chunk
                        compressed_size = tile_info.get("compressed_size")
                        size = tile_info["size"]

                        if compressed_size:
                            import zlib
                            compressed_data = chunk_data[tile_offset:tile_offset + compressed_size]
                            logger.info(f"_load_tiles_batch: Decompressing tile {tile_id}, {compressed_size} → {size} bytes")
                            data = zlib.decompress(compressed_data)
                        else:
                            data = chunk_data[tile_offset:tile_offset + size]

                        # VECTORIZED: Parse all star records at once using numpy
                        num_records = len(data) // STAR_RECORD_SIZE
                        logger.info(f"_load_tiles_batch: Decoding {num_records} stars from tile {tile_id} (vectorized)")

                        records = np.frombuffer(data, dtype=STAR_RECORD_DTYPE, count=num_records)

                        # Mask healpix to 24 bits
                        healpix_pixels = records['healpix'] & 0xFFFFFF

                        # VECTORIZED: Get all pixel centers at once (healpy handles arrays efficiently)
                        pixel_ras, pixel_decs = hp.pix2ang(self.nside, healpix_pixels, lonlat=True)

                        # Calculate pixel size once (not per star!)
                        pixel_size_deg = np.sqrt(hp.nside2pixarea(self.nside, degrees=True))
                        max_offset_arcsec = pixel_size_deg * 3600.0 / 2.0

                        # VECTORIZED: Decode all offsets at once
                        ra_offset_arcsec = (records['ra_offset'] / 127.5 - 1.0) * max_offset_arcsec
                        dec_offset_arcsec = (records['dec_offset'] / 127.5 - 1.0) * max_offset_arcsec

                        # VECTORIZED: Calculate final positions
                        decs = pixel_decs + dec_offset_arcsec / 3600.0
                        ras = pixel_ras + ra_offset_arcsec / 3600.0 / np.cos(np.radians(decs))

                        # VECTORIZED: Decode magnitudes and proper motions
                        mags = records['mag'] / 10.0
                        pmras = records['pmra'] * 50
                        pmdecs = records['pmdec'] * 50

                        # VECTORIZED: Filter by magnitude
                        mag_mask = mags <= mag_limit

                        # Collect stars that pass magnitude filter
                        for i in np.where(mag_mask)[0]:
                            all_stars.append((ras[i], decs[i], mags[i], pmras[i], pmdecs[i]))

                    # Move to next chunk
                    i = j

        logger.info(f"_load_tiles_batch: Loaded {len(all_stars)} stars total, applying proper motion")
        # Apply proper motion
        result = self._apply_proper_motion(all_stars)
        logger.info(f"_load_tiles_batch: Complete, returning {len(result)} stars")
        return result
