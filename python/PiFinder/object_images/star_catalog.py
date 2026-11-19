#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Reader for the HEALPix-tiled Gaia star catalog used by the deep charts.

The catalog has one directory per magnitude band, each with index.bin (the
star count of each HEALPix pixel) and tiles.bin (the stars of each tile in
columns). Both files are read through mmap. Proper motion is applied when the
catalog is built. The format is described in
docs/ax/catalog/gaia-star-catalog.md.
"""

import json
import logging
import mmap
import struct
import threading
import time
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

from PiFinder import timez

# Import healpy at module level to avoid first-use delay
# This ensures the slow import happens during initialization, not during first chart render
import healpy as hp  # type: ignore[import-untyped]

logger = logging.getLogger("PiFinder.StarCatalog")

# The catalog format this reader accepts (metadata.json "format" and the major
# part of "catalog_version").
CATALOG_FORMAT = "columnar"
CATALOG_MAJOR_VERSION = 3


def tile_star_count(size: int, mag_bits: int) -> int:
    """Number of stars in a tile of `size` bytes.

    A tile is ra_offset[n], dec_offset[n], then the magnitudes: n bytes, or
    (n + 1) // 2 bytes of nibbles. So size is 3n, or 2n + (n + 1) // 2.
    """
    if mag_bits == 4:
        return (2 * size) // 5
    return size // 3


def tile_byte_size(num_stars: int, mag_bits: int) -> int:
    """Bytes of a tile with `num_stars` stars."""
    if mag_bits == 4:
        return 2 * num_stars + (num_stars + 1) // 2
    return 3 * num_stars


class CatalogState(Enum):
    """Catalog loading state"""

    NOT_LOADED = 0
    LOADING = 1
    READY = 2


TILE_INDEX_VERSION = 4
OVERFLOW_DTYPE = np.dtype([("pixel", "<u4"), ("count", "<u4")])


class TileIndex:
    """
    Reader for index.bin, the dense tile index of one band.

    Format, little-endian:
    - Header: version(4) = 4, num_pixels(4), stride(4), num_overflow(4)
    - Counts: u8 per HEALPix pixel, the number of stars in its tile. 255
      means the count is in the overflow list.
    - Checkpoints: u64 per `stride` pixels, the offset in tiles.bin of the
      tile of pixel k * stride.
    - Overflow: num_overflow x [pixel u32, count u32], sorted by pixel.

    tiles.bin holds the tiles in pixel order, back to back. The offset of a
    tile is its checkpoint plus the sizes of the tiles before it in its
    stride. Everything stays on the mmap except the overflow pixels.
    """

    def __init__(self, index_file: Path, mag_bits: int):
        """Open the tile index of a band that stores `mag_bits` magnitudes."""
        self.index_file = index_file
        self.mag_bits = mag_bits
        self._counts: Optional[np.ndarray] = None
        self._checkpoints: Optional[np.ndarray] = None
        self._mm: Optional[mmap.mmap] = None
        self._file = None
        self._file = open(index_file, "rb")
        self._mm = mmap.mmap(self._file.fileno(), 0, access=mmap.ACCESS_READ)

        version, num_pixels, stride, num_overflow = struct.unpack_from(
            "<IIII", self._mm, 0
        )
        if version != TILE_INDEX_VERSION:
            raise ValueError(
                f"Expected tile index version {TILE_INDEX_VERSION}, got {version}"
            )
        self.num_pixels = num_pixels
        self.stride = stride
        num_checkpoints = -(-num_pixels // stride)
        self._counts = np.frombuffer(
            self._mm, dtype=np.uint8, count=num_pixels, offset=16
        )
        self._checkpoints = np.frombuffer(
            self._mm, dtype="<u8", count=num_checkpoints, offset=16 + num_pixels
        )
        overflow = np.frombuffer(
            self._mm,
            dtype=OVERFLOW_DTYPE,
            count=num_overflow,
            offset=16 + num_pixels + 8 * num_checkpoints,
        )
        self._overflow_pixels = np.array(overflow["pixel"], dtype=np.int64)
        self._overflow_counts = np.array(overflow["count"], dtype=np.int64)
        self.num_tiles = int(np.count_nonzero(self._counts))

        logger.debug(
            f"TileIndex: {self.num_tiles:,} tiles, {num_overflow} overflow counts"
        )

    def _star_counts(self, first: int, last: int) -> np.ndarray:
        """Star counts of the pixels first..last-1, with the overflow applied."""
        assert self._counts is not None
        counts = self._counts[first:last].astype(np.int64)
        big = np.nonzero(counts == 255)[0]
        if len(big):
            where = np.searchsorted(self._overflow_pixels, big + first)
            counts[big] = self._overflow_counts[where]
        return counts

    def get(self, tile_id: int) -> Optional[Tuple[int, int]]:
        """
        Get (offset, size) in tiles.bin for a tile ID.

        Returns None if the tile doesn't exist.
        """
        if self._counts is None or self._checkpoints is None:
            return None
        if not 0 <= tile_id < self.num_pixels:
            return None
        if self._counts[tile_id] == 0:
            return None
        block = tile_id // self.stride
        first = block * self.stride
        counts = self._star_counts(first, tile_id + 1)
        if self.mag_bits == 4:
            sizes = 2 * counts + (counts + 1) // 2
        else:
            sizes = 3 * counts
        offset = int(self._checkpoints[block]) + int(sizes[:-1].sum())
        return (offset, int(sizes[-1]))

    def close(self):
        """Close mmap and file (idempotent)"""
        # The numpy views hold the mmap's buffer; mmap.close() refuses while
        # they exist.
        self._counts = None
        self._checkpoints = None
        if self._mm is not None:
            self._mm.close()
            self._mm = None
        if self._file is not None:
            self._file.close()
            self._file = None

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
                self.load_progress = "Error: catalog not found"
                self.state = CatalogState.NOT_LOADED
                return

            with open(metadata_file, "r") as f:
                metadata = json.load(f)
            logger.info(">>> metadata.json loaded")

            version = str(metadata.get("catalog_version", "0"))
            if metadata.get("format") != CATALOG_FORMAT or version.split(".")[0] != str(
                CATALOG_MAJOR_VERSION
            ):
                logger.error(
                    f">>> Unsupported catalog: format={metadata.get('format')} "
                    f"version={version}, expected {CATALOG_FORMAT} "
                    f"{CATALOG_MAJOR_VERSION}.x"
                )
                self.load_progress = "Error: unsupported catalog"
                self.state = CatalogState.NOT_LOADED
                return
            self.metadata = metadata

            self.nside = self.metadata.get("nside", 512)
            star_count = self.metadata.get("star_count", 0)
            logger.info(
                f">>> Catalog metadata ready: {star_count:,} stars, "
                f"mag limit {self.metadata.get('mag_limit', 0):.1f}, nside={self.nside}"
            )

            # Log available bands
            bands = self.metadata.get("mag_bands", [])
            logger.info(f">>> Catalog mag bands: {json.dumps(bands)}")

            # Open the index of each band now, so the first chart does not wait
            # for it.
            self._preload_tile_indices()

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
        assert (
            self.metadata is not None
        ), "metadata should be loaded when state is READY"
        assert self.nside is not None, "nside should be set when state is READY"

        mag_limit = mag_limit or self.limiting_magnitude

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

        # Batch loading only for moderate tile counts (10-50), to avoid UI
        # blocking
        if 10 < len(tiles) <= 50:
            # Batch load is much faster for many tiles
            # Note: batch loading returns PM-corrected (ra, dec, mag) tuples
            logger.info(f"Using BATCH loading for {len(tiles)} tiles")
            stars = self._load_tiles_batch(tiles, mag_limit)
            logger.info(f"Batch load complete: {len(stars)} stars")
            tile_star_counts = {
                t: 0 for t in tiles
            }  # Don't track individual counts for batch
        else:
            # Load one by one (better for small queries)
            logger.info(f"Using SINGLE-TILE loading for {len(tiles)} tiles")
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

        return self._load_tiles_batch_single_band(tile_ids, mag_band_info, mag_limit)

    def _load_tile_data(self, tile_id: int, mag_limit: float) -> np.ndarray:
        """
        Load star data for a HEALPix tile

        Args:
            tile_id: HEALPix tile ID
            mag_limit: Maximum magnitude to load

        Returns:
            Numpy array of shape (N, 5) containing (ra, dec, mag, pmra, pmdec)
        """
        assert (
            self.metadata is not None
        ), "metadata must be loaded before calling _load_tile_data"

        cache_key = (tile_id, mag_limit)

        # Check cache
        with self.cache_lock:
            if cache_key in self.tile_cache:
                return self.tile_cache[cache_key]

        # Load from disk
        stars_list = []

        # Determine which magnitude bands to load
        for mag_band_info in self.metadata.get("mag_bands", []):
            mag_min = mag_band_info["min"]
            mag_max = mag_band_info["max"]

            if mag_min >= mag_limit:
                continue  # Band too faint

            band_dir = self.catalog_path / f"mag_{mag_min:02.0f}_{mag_max:02.0f}"
            ras, decs, mags, pmras, pmdecs = self._load_tile_compact(
                band_dir, tile_id, mag_band_info
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
                        f"  Tile {tile_id} Band {mag_min}-{mag_max}: {len(band_stars)} stars"
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

    def _load_tile_compact(
        self, band_dir: Path, tile_id: int, band: dict
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """
        Load the stars of one tile of one band.

        Args:
            band_dir: Magnitude band directory
            tile_id: HEALPix tile ID
            band: Magnitude band metadata dict

        Returns:
            Tuple of (ras, decs, mags, pmras, pmdecs) arrays
        """
        empty = (np.array([]), np.array([]), np.array([]), np.array([]), np.array([]))
        index_file = band_dir / "index.bin"
        tiles_file = band_dir / "tiles.bin"

        if not tiles_file.exists():
            return empty

        if not index_file.exists():
            raise FileNotFoundError(f"Tile index not found: {index_file}")

        # Load index (cached per band)
        cache_key = f"index_{band['min']}_{band['max']}"
        if cache_key not in self._index_cache:
            self._index_cache[cache_key] = TileIndex(
                index_file, int(band.get("mag_bits", 8))
            )

        index = self._index_cache[cache_key]

        result = index.get(tile_id)
        if result is None:
            return empty
        offset, size = result

        with open(tiles_file, "rb") as f:
            f.seek(offset)
            data = f.read(size)
            return self._parse_records(data, tile_id, band)

    def _parse_records(
        self, data: bytes, tile_id: int, band: dict
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """
        Decode one tile into numpy arrays.

        A tile has no header: index.bin gives its HEALPix id and its size. The
        stars are in three columns: ra_offset[n], dec_offset[n], then the
        magnitudes. band["mag_bits"] is 8 (one byte per star, tenths of a
        magnitude) or 4 (one nibble per star, tenths above band["mag_base"];
        star 2k in the low nibble of byte k, star 2k+1 in the high nibble).

        Args:
            data: The bytes of the tile
            tile_id: HEALPix pixel of the tile (nested scheme)
            band: Magnitude band metadata dict

        Returns:
            Tuple of (ras, decs, mags, pmras, pmdecs) as numpy arrays
        """
        mag_bits = int(band.get("mag_bits", 8))
        num_stars = tile_star_count(len(data), mag_bits)
        if num_stars == 0:
            return (
                np.array([]),
                np.array([]),
                np.array([]),
                np.array([]),
                np.array([]),
            )
        if tile_byte_size(num_stars, mag_bits) != len(data):
            logger.warning(
                f"Tile {tile_id}: {len(data)} bytes is not a whole number of "
                f"stars for {mag_bits}-bit magnitudes"
            )
            return (
                np.array([]),
                np.array([]),
                np.array([]),
                np.array([]),
                np.array([]),
            )

        raw = np.frombuffer(data, dtype=np.uint8)
        ra_offset = raw[:num_stars]
        dec_offset = raw[num_stars : 2 * num_stars]
        mag_bytes = raw[2 * num_stars :]
        tenths = np.empty(num_stars, dtype=np.int16)
        if mag_bits == 4:
            tenths[0::2] = mag_bytes[: (num_stars + 1) // 2] & 0x0F
            tenths[1::2] = mag_bytes[: num_stars // 2] >> 4
            tenths += int(band["mag_base"])
        else:
            tenths[:] = mag_bytes

        # Get pixel center (same for all stars in this tile)
        pixel_ra, pixel_dec = hp.pix2ang(self.nside, tile_id, lonlat=True)

        # The offsets span +-0.75 of the pixel size in 255 steps.
        pixel_size_deg = np.sqrt(hp.nside2pixarea(self.nside, degrees=True))
        max_offset_arcsec = pixel_size_deg * 3600.0 * 0.75

        ra_offset_arcsec = (ra_offset / 127.5 - 1.0) * max_offset_arcsec
        dec_offset_arcsec = (dec_offset / 127.5 - 1.0) * max_offset_arcsec

        # Calculate final positions (broadcast pixel center to all stars)
        decs = pixel_dec + dec_offset_arcsec / 3600.0
        ras = pixel_ra + ra_offset_arcsec / 3600.0 / np.cos(np.radians(decs))

        mags = tenths / 10.0

        # Proper motion is applied when the catalog is built. The zero arrays
        # keep the (ras, decs, mags, pmras, pmdecs) shape the callers use.
        pmras = np.zeros(num_stars)
        pmdecs = np.zeros(num_stars)

        return ras, decs, mags, pmras, pmdecs

    def _preload_tile_indices(self) -> None:
        """
        Open the index of each magnitude band during startup.

        Each index is an mmap; only its overflow list (about 0.3 MB for all
        bands) is copied into RAM. This runs in the background load thread, so
        the first chart does not wait for the indices.
        """
        if not self.metadata or "mag_bands" not in self.metadata:
            logger.warning(">>> No metadata available, skipping tile index preload")
            return

        t0_total = time.time()
        bands_loaded = 0

        logger.info(">>> Opening the tile index of each magnitude band...")

        for band_info in self.metadata["mag_bands"]:
            mag_min = int(band_info["min"])
            mag_max = int(band_info["max"])
            cache_key = f"index_{mag_min}_{mag_max}"

            index_file = (
                self.catalog_path / f"mag_{mag_min:02d}_{mag_max:02d}" / "index.bin"
            )

            if not index_file.exists():
                raise FileNotFoundError(f"Tile index not found: {index_file}")

            t0 = time.time()

            tile_index = TileIndex(index_file, int(band_info.get("mag_bits", 8)))
            self._index_cache[cache_key] = tile_index
            t_load = (time.time() - t0) * 1000
            bands_loaded += 1

            logger.info(
                f">>> Loaded tile index {cache_key}: "
                f"{tile_index.num_tiles:,} tiles in {t_load:.1f}ms"
            )

        t_total = (time.time() - t0_total) * 1000
        logger.info(
            f">>> Tile index preload complete: {bands_loaded} indices "
            f"in {t_total:.1f}ms"
        )

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
        now = timez.utc_now()
        current_year = now.year + (now.timetuple().tm_yday / 365.25)
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

        mag_min = mag_band_info["min"]
        mag_max = mag_band_info["max"]

        band_dir = self.catalog_path / f"mag_{mag_min:02.0f}_{mag_max:02.0f}"
        index_file = band_dir / "index.bin"
        tiles_file = band_dir / "tiles.bin"

        if not tiles_file.exists():
            return np.empty((0, 3))

        if not index_file.exists():
            raise FileNotFoundError(f"Tile index not found: {index_file}")

        cache_key = f"index_{mag_min}_{mag_max}"

        # Load the tile index (cached)
        if not hasattr(self, "_index_cache"):
            self._index_cache = {}

        t_index_start = time.time()
        logger.debug(f"Checking index cache for {cache_key}")
        if cache_key not in self._index_cache:
            logger.info(f">>> Loading tile index from {index_file}")
            t0 = time.time()
            self._index_cache[cache_key] = TileIndex(
                index_file, int(mag_band_info.get("mag_bits", 8))
            )
            t_read_index = (time.time() - t0) * 1000
            logger.info(f">>> Tile index loaded in {t_read_index:.1f}ms")
        else:
            logger.debug(f">>> Using cached index for {cache_key}")

        index = self._index_cache[cache_key]
        t_index_total = (time.time() - t_index_start) * 1000
        logger.debug(f">>> Index cache operations took {t_index_total:.1f}ms")

        t_readops_start = time.time()
        logger.debug(f"Building read_ops for {len(tile_ids)} tiles...")

        # Collect all tile read operations from the tile index
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
                    ras, decs, mags, pmras, pmdecs = self._parse_records(
                        data, tile_id, mag_band_info
                    )
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
        assert (
            self.metadata is not None
        ), "metadata must be loaded before calling _load_tiles_batch"

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
                raise FileNotFoundError(f"Tile index not found: {index_file}")

            # Load the tile index
            cache_key = f"index_{mag_min}_{mag_max}"
            if not hasattr(self, "_index_cache"):
                self._index_cache = {}

            if cache_key not in self._index_cache:
                self._index_cache[cache_key] = TileIndex(
                    index_file, int(mag_band_info.get("mag_bits", 8))
                )

            index = self._index_cache[cache_key]

            # Collect all tile read operations from the tile index
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
                        ras, decs, mags, pmras, pmdecs = self._parse_records(
                            data, tile_id, mag_band_info
                        )

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
