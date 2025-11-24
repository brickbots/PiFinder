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

import hashlib
import json
import logging
import math
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
        self._file = open(index_file, 'rb')
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

        logger.debug(f"CompressedIndex: loaded {num_runs} runs for {self.num_tiles:,} tiles")

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
        sizes_data = self._mm[sizes_offset:sizes_offset + (offset_in_run + 1) * 2]
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


class TileBloomFilter:
    """
    Bloom filter for tile existence checks.

    A space-efficient probabilistic data structure for testing set membership.
    False positives are possible (might say a tile exists when it doesn't),
    but false negatives are impossible (never says a tile doesn't exist when it does).

    Uses k hash functions with optimal sizing for target false positive rate.
    Typical configuration: 10 bits per element for 1% false positive rate.
    """

    def __init__(self, capacity: int, fp_rate: float = 0.01):
        """
        Initialize bloom filter.

        Args:
            capacity: Expected number of items (tiles) to store
            fp_rate: Target false positive rate (e.g., 0.01 = 1%)
        """
        self.capacity = capacity
        self.fp_rate = fp_rate
        self.num_bits = self._optimal_num_bits(capacity, fp_rate)
        self.num_hashes = self._optimal_num_hashes(self.num_bits, capacity)
        self.bit_array = bytearray((self.num_bits + 7) // 8)

    @staticmethod
    def _optimal_num_bits(n: int, p: float) -> int:
        """
        Calculate optimal bit array size.

        Formula: m = -(n * ln(p)) / (ln(2)^2)

        Args:
            n: Number of elements (capacity)
            p: Target false positive rate

        Returns:
            Optimal number of bits
        """
        m = -(n * math.log(p)) / (math.log(2) ** 2)
        return int(m)

    @staticmethod
    def _optimal_num_hashes(m: int, n: int) -> int:
        """
        Calculate optimal number of hash functions.

        Formula: k = (m/n) * ln(2)

        Args:
            m: Number of bits in array
            n: Number of elements (capacity)

        Returns:
            Optimal number of hash functions
        """
        if n == 0:
            return 1  # Avoid division by zero for empty filter
        k = (m / n) * math.log(2)
        return max(1, int(k))

    def _hash(self, item: int, seed: int) -> int:
        """
        Hash function using MD5 with seed mixing.

        Args:
            item: Tile ID to hash
            seed: Seed for this hash function (0 to k-1)

        Returns:
            Bit position in range [0, num_bits)
        """
        h = hashlib.md5(f"{item}:{seed}".encode()).digest()
        return int.from_bytes(h[:4], 'little') % self.num_bits

    def add(self, tile_id: int) -> None:
        """
        Add tile_id to bloom filter.

        Args:
            tile_id: HEALPix tile ID to add
        """
        for i in range(self.num_hashes):
            bit_pos = self._hash(tile_id, i)
            byte_pos = bit_pos // 8
            bit_offset = bit_pos % 8
            self.bit_array[byte_pos] |= (1 << bit_offset)

    def might_contain(self, tile_id: int) -> bool:
        """
        Check if tile_id might exist in the set.

        Args:
            tile_id: HEALPix tile ID to check

        Returns:
            True: tile might exist (or false positive)
            False: tile definitely does not exist
        """
        for i in range(self.num_hashes):
            bit_pos = self._hash(tile_id, i)
            byte_pos = bit_pos // 8
            bit_offset = bit_pos % 8
            if not (self.bit_array[byte_pos] & (1 << bit_offset)):
                return False  # Definitely not in set
        return True  # Probably in set

    def save(self, path: Path) -> None:
        """
        Save bloom filter to binary file.

        Format:
            Header (24 bytes):
                [version:4][capacity:4][fp_rate:8][num_bits:4][num_hashes:4]
            Body (variable):
                [bit_array:N] where N = (num_bits + 7) / 8 bytes

        Args:
            path: Path to save bloom filter
        """
        with open(path, 'wb') as f:
            # Header: version, capacity, fp_rate, num_bits, num_hashes
            f.write(struct.pack('<IIdII',
                               1,                  # version
                               self.capacity,      # number of items
                               self.fp_rate,       # false positive rate
                               self.num_bits,      # bit array size
                               self.num_hashes))   # number of hash functions
            # Body: bit array
            f.write(self.bit_array)

    @classmethod
    def load(cls, path: Path) -> 'TileBloomFilter':
        """
        Load bloom filter from binary file.

        Args:
            path: Path to bloom filter file

        Returns:
            Loaded TileBloomFilter instance

        Raises:
            ValueError: If file format is unsupported or corrupted
            FileNotFoundError: If file doesn't exist
        """
        with open(path, 'rb') as f:
            # Read header (24 bytes)
            header = f.read(24)
            if len(header) < 24:
                raise ValueError(f"Bloom filter file too small: {len(header)} bytes")

            version, capacity, fp_rate, num_bits, num_hashes = struct.unpack('<IIdII', header)

            if version != 1:
                raise ValueError(f"Unsupported bloom filter version: {version}")

            # Read bit array
            bit_array_bytes = (num_bits + 7) // 8
            bit_array = bytearray(f.read(bit_array_bytes))

            if len(bit_array) != bit_array_bytes:
                raise ValueError(
                    f"Bloom filter file corrupted: expected {bit_array_bytes} bytes, "
                    f"got {len(bit_array)}"
                )

            # Reconstruct bloom filter
            bf = cls.__new__(cls)
            bf.capacity = capacity
            bf.fp_rate = fp_rate
            bf.num_bits = num_bits
            bf.num_hashes = num_hashes
            bf.bit_array = bit_array

            return bf

    def get_actual_fp_rate(self) -> Optional[float]:
        """
        Calculate actual false positive rate based on stored parameters.

        Formula: FP = (1 - e^(-k*n/m))^k

        Returns:
            Estimated false positive rate, or None if capacity is 0
        """
        if self.capacity == 0:
            return None

        # FP rate = (1 - e^(-k*n/m))^k
        exponent = -self.num_hashes * self.capacity / self.num_bits
        fp = (1 - math.exp(exponent)) ** self.num_hashes
        return fp


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
        self.tile_cache: Dict[Tuple[int, float], np.ndarray] = {}
        self.cache_lock = threading.Lock()
        self.load_thread: Optional[threading.Thread] = None
        self.load_progress: str = ""  # Status message for UI
        self.load_percent: int = 0  # Progress percentage (0-100)
        self._index_cache: Dict[str, Any] = {}
        # Cache of existing tile IDs per magnitude band to avoid scanning for non-existent tiles
        self._existing_tiles_cache: Dict[str, Set[int]] = {}
        # Bloom filters for fast tile existence checks (space-efficient)
        self._bloom_filters: Dict[str, TileBloomFilter] = {}
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
            
            # Log available bands
            bands = self.metadata.get("mag_bands", [])
            logger.info(f">>> Catalog mag bands: {json.dumps(bands)}")

            # Preload all bloom filters into memory (~12 MB total)
            # DISABLED: Bloom filters not currently used (testing performance on Pi)
            # self._preload_bloom_filters()

            # Preload all compressed indices (run directories) into memory (~2-12 MB total)
            # This eliminates first-query delays (70ms per band → 420ms total stuttering)
            self._preload_compressed_indices()

            # Initialize empty structures (no preloading)
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
        vec = hp.ang2vec(ra_deg, dec_deg, lonlat=True)
        radius_rad = np.radians(fov_deg / 2 * 1.1)
        tiles = hp.query_disc(self.nside, vec, radius_rad)
        logger.debug(f"HEALPix PROGRESSIVE: Querying {len(tiles)} tiles for FOV={fov_deg:.2f}° (radius={np.degrees(radius_rad):.3f}°) at nside={self.nside}")

        # Filter by visible hemisphere
        if self.visible_tiles:
            tiles = [t for t in tiles if t in self.visible_tiles]

        # Load stars progressively by magnitude band (bright to faint)
        all_stars_list = []

        if not self.metadata:
            yield (np.empty((0, 3)), True)
            return

        for mag_band_info in self.metadata.get("mag_bands", []):
            mag_min = mag_band_info["min"]
            mag_max = mag_band_info["max"]

            # Skip bands fainter than limit
            if mag_min >= mag_limit:
                break

            logger.debug(f">>> PROGRESSIVE: Loading mag band {mag_min}-{mag_max}, tiles={len(tiles)}, mag_limit={mag_limit}")
            import time
            t_band_start = time.time()

            # Load stars from this magnitude band only
            # logger.info(f">>> Calling _load_tiles_for_mag_band...")
            band_stars = self._load_tiles_for_mag_band(
                tiles, mag_band_info, mag_limit, ra_deg, dec_deg, fov_deg
            )
            # logger.info(f">>> _load_tiles_for_mag_band returned {len(band_stars)} stars")

            t_load = (time.time() - t_band_start) * 1000

            # Add to cumulative list
            t_append_start = time.time()
            if len(band_stars) > 0:
                all_stars_list.append(band_stars)
            t_append = (time.time() - t_append_start) * 1000

            # Yield current results (not complete yet unless this is the last band)
            is_last_band = mag_max >= mag_limit

            t_concat_start = time.time()
            if all_stars_list:
                current_total = np.concatenate(all_stars_list)
            else:
                current_total = np.empty((0, 3))
            t_concat = (time.time() - t_concat_start) * 1000

            t_yield_start = time.time()
            yield (current_total, is_last_band)
            t_yield = (time.time() - t_yield_start) * 1000

            logger.info(
                f">>> PROGRESSIVE TIMING: mag {mag_min}-{mag_max}: "
                f"load={t_load:.1f}ms, append={t_append:.1f}ms, "
                f"concat={t_concat:.1f}ms, yield={t_yield:.1f}ms, "
                f"total={(t_load+t_append+t_concat+t_yield):.1f}ms, "
                f"stars={len(band_stars)}, cumulative={len(current_total)}"
            )

            if is_last_band:
                break

        # Final yield (should already be done above, but just in case)
        if all_stars_list:
            final_total = np.concatenate(all_stars_list)
        else:
            final_total = np.empty((0, 3))
        logger.info(f"PROGRESSIVE: Complete! Total {len(final_total)} stars loaded")

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
        assert self.metadata is not None, "metadata should be loaded when state is READY"
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
        logger.debug(f"HEALPix: Querying {len(tiles)} tiles for FOV={fov_deg:.2f}° (radius={np.degrees(radius_rad):.3f}°) at nside={self.nside}")

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
            stars_raw_list = []

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
                
                # Returns (N, 5) array
                tile_stars = self._load_tile_data(tile_id, mag_limit)
                tile_star_counts[tile_id] = len(tile_stars)
                
                if len(tile_stars) > 0:
                    stars_raw_list.append(tile_stars)

                if was_cached:
                    cache_hits += 1
                else:
                    cache_misses += 1

                # Log progress every 25 tiles
                if (i + 1) % 25 == 0:
                    elapsed = (time.time() - t_single_start) * 1000
                    logger.debug(f"Progress: {i+1}/{len(tiles)} tiles loaded ({elapsed:.0f}ms elapsed)")

            t_single_end = time.time()
            elapsed_ms = (t_single_end - t_single_start) * 1000

            # Log cache performance
            logger.debug(f"Tile cache: {cache_hits} hits, {cache_misses} misses ({cache_hits/(cache_hits+cache_misses)*100:.1f}% hit rate)")
            
            total_raw = sum(len(x) for x in stars_raw_list)
            logger.debug(f"Single-tile loading complete: {total_raw} stars in {elapsed_ms:.1f}ms ({elapsed_ms/len(tiles):.2f}ms/tile)")

            # Log tile loading stats
            if tile_star_counts:
                logger.debug(f"Loaded from {len(tile_star_counts)} tiles: " +
                            f"min={min(tile_star_counts.values())} max={max(tile_star_counts.values())} " +
                            f"total={sum(tile_star_counts.values())}")

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
            logger.debug(f"Proper motion correction: {len(stars)} stars in {(t_pm_end-t_pm_start)*1000:.1f}ms")

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

    def _load_tile_data(
        self, tile_id: int, mag_limit: float
    ) -> np.ndarray:
        """
        Load star data for a HEALPix tile

        Args:
            tile_id: HEALPix tile ID
            mag_limit: Maximum magnitude to load

        Returns:
            Numpy array of shape (N, 5) containing (ra, dec, mag, pmra, pmdec)
        """
        assert self.metadata is not None, "metadata must be loaded before calling _load_tile_data"

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
                ras, decs, mags, pmras, pmdecs = self._load_tile_compact(band_dir, tile_id, mag_min, mag_max)
            else:
                # Legacy format: one file per tile
                tile_file = band_dir / f"tile_{tile_id:06d}.bin"
                if tile_file.exists():
                    ras, decs, mags, pmras, pmdecs = self._load_tile_from_file(tile_file, mag_min, mag_max)
                else:
                    ras, decs, mags, pmras, pmdecs = (np.array([]), np.array([]), np.array([]), np.array([]), np.array([]))

            if len(ras) > 0:
                # Filter by magnitude
                mask = mags <= mag_limit
                if np.any(mask):
                    # Stack into (N, 5) array for this band
                    band_stars = np.column_stack((ras[mask], decs[mask], mags[mask], pmras[mask], pmdecs[mask]))
                    stars_list.append(band_stars)
                    logger.debug(f"  Tile {tile_id} Band {mag_min}-{mag_max}: {len(band_stars)} stars (file: {tile_file if not is_compact else 'compact'})")
                else:
                    logger.debug(f"  Tile {tile_id} Band {mag_min}-{mag_max}: 0 stars (mask empty)")

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
            return (np.array([]), np.array([]), np.array([]), np.array([]), np.array([]))

        # Read entire file at once
        with open(tile_file, "rb") as f:
            data = f.read()

        return self._parse_records(data)

    def _load_tile_compact(
        self, band_dir: Path, tile_id: int, mag_min: float, mag_max: float
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """
        Load stars from compact format (consolidated tiles.bin + index.json)

        Args:
            band_dir: Magnitude band directory
            tile_id: HEALPix tile ID
            mag_min: Minimum magnitude
            mag_max: Maximum magnitude

        Returns:
            Tuple of (ras, decs, mags, pmras, pmdecs) arrays
        """
        if not _HEALPY_AVAILABLE:
            return (np.array([]), np.array([]), np.array([]), np.array([]), np.array([]))

        # Try binary index first, fall back to JSON for backward compat
        index_file_bin = band_dir / "index.bin"
        index_file_json = band_dir / "index.json"
        tiles_file = band_dir / "tiles.bin"

        if not tiles_file.exists():
            return (np.array([]), np.array([]), np.array([]), np.array([]), np.array([]))

        # Determine index format
        if index_file_bin.exists():
            index_file = index_file_bin
            is_binary = True
        elif index_file_json.exists():
            index_file = index_file_json
            is_binary = False
        else:
            return (np.array([]), np.array([]), np.array([]), np.array([]), np.array([]))

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
            return (np.array([]), np.array([]), np.array([]), np.array([]), np.array([]))

        # Get tile offset and size
        tile_info = index[tile_key]
        offset = tile_info["offset"]
        size = tile_info["size"]
        compressed_size = tile_info.get("compressed_size")

        # Read tile data
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

            return self._parse_records(data)

    def _parse_records(self, data: bytes) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """
        Parse binary star records into numpy arrays (VECTORIZED)

        Args:
            data: Binary data containing star records

        Returns:
            Tuple of (ras, decs, mags, pmras, pmdecs) as numpy arrays
        """
        if len(data) == 0:
            return (np.array([]), np.array([]), np.array([]), np.array([]), np.array([]))

        # Parse all records using numpy
        num_records = len(data) // STAR_RECORD_SIZE
        records = np.frombuffer(data, dtype=STAR_RECORD_DTYPE, count=num_records)

        # Mask healpix to 24 bits
        healpix_pixels = records['healpix'] & 0xFFFFFF

        # Get all pixel centers at once
        pixel_ras, pixel_decs = hp.pix2ang(self.nside, healpix_pixels, lonlat=True)

        # Calculate pixel size once
        pixel_size_deg = np.sqrt(hp.nside2pixarea(self.nside, degrees=True))
        max_offset_arcsec = pixel_size_deg * 3600.0 / 2.0

        # Decode all offsets
        ra_offset_arcsec = (records['ra_offset'] / 127.5 - 1.0) * max_offset_arcsec
        dec_offset_arcsec = (records['dec_offset'] / 127.5 - 1.0) * max_offset_arcsec

        # Calculate final positions
        decs = pixel_decs + dec_offset_arcsec / 3600.0
        ras = pixel_ras + ra_offset_arcsec / 3600.0 / np.cos(np.radians(decs))

        # Decode magnitudes and proper motions
        mags = records['mag'] / 10.0
        pmras = records['pmra'] * 50
        pmdecs = records['pmdec'] * 50

        return ras, decs, mags, pmras, pmdecs

    def _read_binary_index(self, index_file: Path, needed_tiles: Optional[set] = None) -> dict:
        """
        Read binary index file - optimized to only load needed tiles for large indices

        Format v1 (uncompressed):
            Header: [version:4][num_tiles:4]
            Per tile: [tile_id:4][offset:8][size:4]

        Format v2 (compressed):
            Header: [version:4][num_tiles:4]
            Per tile: [tile_id:4][offset:8][compressed_size:4][uncompressed_size:4]

        Args:
            index_file: Path to the index file
            needed_tiles: Set of tile IDs we actually need. If provided and index is large (>100K tiles),
                         only load these specific tiles instead of the whole index.

        Returns:
            Dict mapping tile_id (as string) -> {"offset": int, "size": int, "compressed_size": int (optional)}
        """
        index = {}

        if not index_file.exists():
            return {}

        with open(index_file, "rb") as f:
            # Read header
            header = f.read(8)
            if len(header) < 8:
                return {}
            
            version, num_tiles = struct.unpack("<II", header)

            # Define dtypes for vectorized reading
            if version == 1:
                # [tile_id:4][offset:8][size:4]
                dtype = np.dtype([
                    ('tile_id', '<u4'),
                    ('offset', '<u8'),
                    ('size', '<u4')
                ])
                entry_size = 16
            elif version == 2:
                # [tile_id:4][offset:8][compressed_size:4][uncompressed_size:4]
                dtype = np.dtype([
                    ('tile_id', '<u4'),
                    ('offset', '<u8'),
                    ('compressed_size', '<u4'),
                    ('uncompressed_size', '<u4')
                ])
                entry_size = 20
            else:
                logger.error(f"Unsupported index version: {version}")
                return {}

            # If specific tiles requested, use range query (much faster than chunk scanning)
            if needed_tiles is not None:
                # Convert to list of integers
                needed_list = sorted([int(t) if isinstance(t, str) else t for t in needed_tiles])

                logger.debug(f">>> Selective loading: {len(needed_list)} tiles out of {num_tiles:,} total")

                # Use range query for spatially localized tiles
                # Range query does binary search + sequential read, much faster than chunked scan
                index = self._load_tile_range(index_file, needed_list, version, entry_size, num_tiles)

                logger.info(f">>> Loaded {len(index)} entries using range query")
                return index

            # For small indices or when we need everything, load all entries at once
            data = f.read()
            records = np.frombuffer(data, dtype=dtype)
            
            # Convert to dictionary (this part is still Python loop but unavoidable for dict creation)
            # However, iterating over numpy array is faster than struct.unpack loop
            
            # Pre-allocate dict for speed? Not easily possible in Python
            # But we can use a comprehension which is slightly faster
            
            if version == 1:
                for record in records:
                    index[str(record['tile_id'])] = {
                        "offset": int(record['offset']),
                        "size": int(record['size'])
                    }
            else:
                for record in records:
                    index[str(record['tile_id'])] = {
                        "offset": int(record['offset']),
                        "size": int(record['uncompressed_size']),
                        "compressed_size": int(record['compressed_size'])
                    }

        return index

    def _preload_bloom_filters(self) -> None:
        """
        Preload all bloom filters into memory during catalog initialization.

        Loads all bloom filters (~12 MB total) to eliminate on-demand loading
        delays during chart generation. Bloom filters provide fast tile existence
        checks with minimal memory overhead.

        This runs in background thread during catalog startup.
        """
        if not self.metadata or "mag_bands" not in self.metadata:
            logger.warning(">>> No metadata available, skipping bloom filter preload")
            return

        t0_total = time.time()
        total_bytes = 0
        bands_loaded = 0

        logger.info(">>> Preloading bloom filters for all magnitude bands...")

        for band_info in self.metadata["mag_bands"]:
            mag_min = int(band_info["min"])
            mag_max = int(band_info["max"])
            cache_key = f"index_{mag_min}_{mag_max}"

            bloom_file = self.catalog_path / f"mag_{mag_min:02d}_{mag_max:02d}" / "bloom.bin"

            if not bloom_file.exists():
                logger.warning(
                    f">>> Bloom filter missing for {cache_key}: {bloom_file} - "
                    f"Run catalog_tools/generate_bloom_filters.py"
                )
                continue

            t0 = time.time()
            self._bloom_filters[cache_key] = TileBloomFilter.load(bloom_file)
            t_load = (time.time() - t0) * 1000

            bloom = self._bloom_filters[cache_key]
            bloom_bytes = len(bloom.bit_array)
            total_bytes += bloom_bytes
            bands_loaded += 1

            logger.info(
                f">>> Loaded bloom filter {cache_key}: "
                f"{bloom.capacity:,} tiles, {bloom_bytes / 1024:.1f} KB, "
                f"FP={bloom.get_actual_fp_rate():.2%} in {t_load:.1f}ms"
            )

        t_total = (time.time() - t0_total) * 1000
        logger.info(
            f">>> Bloom filter preload complete: {bands_loaded} filters, "
            f"{total_bytes / 1024 / 1024:.1f} MB total in {t_total:.1f}ms"
        )

    def _preload_compressed_indices(self) -> None:
        """
        Preload all compressed indices (run directories) into memory during startup.

        Loads compressed index run directories (~2-12 MB total) to eliminate first-query
        delays during chart generation. Each compressed index loads its run directory
        into RAM for fast binary search, while keeping run data in mmap.

        This runs in background thread during catalog startup and trades a one-time
        ~200ms startup cost for eliminating 6 × 70ms = 420ms of stuttering during
        first chart generation.
        """
        if not self.metadata or "mag_bands" not in self.metadata:
            logger.warning(">>> No metadata available, skipping compressed index preload")
            return

        t0_total = time.time()
        bands_loaded = 0

        logger.info(">>> Preloading compressed indices for all magnitude bands...")

        for band_info in self.metadata["mag_bands"]:
            mag_min = int(band_info["min"])
            mag_max = int(band_info["max"])
            cache_key = f"index_{mag_min}_{mag_max}"

            # Try compressed index first (v3)
            index_file_v3 = self.catalog_path / f"mag_{mag_min:02d}_{mag_max:02d}" / "index_v3.bin"

            if not index_file_v3.exists():
                logger.debug(
                    f">>> Compressed index not found for {cache_key}: {index_file_v3} - "
                    f"Will fall back to v1/v2 index on first query"
                )
                continue

            t0 = time.time()
            self._index_cache[cache_key] = CompressedIndex(index_file_v3)
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

    def _ensure_bloom_filter(self, cache_key: str, mag_min: int, mag_max: int) -> None:
        """
        Ensure bloom filter is loaded for given magnitude band.

        This is a fallback in case preloading failed for a specific band.
        Normally all bloom filters are preloaded during catalog initialization.

        Args:
            cache_key: Cache key for this magnitude band (e.g., "index_12_14")
            mag_min: Minimum magnitude for this band
            mag_max: Maximum magnitude for this band

        Raises:
            FileNotFoundError: If bloom filter file is missing (catalog corruption)
        """
        if cache_key in self._bloom_filters:
            return  # Already loaded (normal case - preloaded at startup)

        # Fallback: load on-demand if preloading missed this band
        logger.warning(f">>> Bloom filter {cache_key} not preloaded, loading on-demand...")

        bloom_file = self.catalog_path / f"mag_{mag_min:02d}_{mag_max:02d}" / "bloom.bin"

        if not bloom_file.exists():
            raise FileNotFoundError(
                f"Bloom filter missing for {cache_key}: {bloom_file}\n"
                f"Catalog may be corrupted or incomplete. "
                f"Run catalog_tools/generate_bloom_filters.py to create missing bloom filters."
            )

        t0 = time.time()
        self._bloom_filters[cache_key] = TileBloomFilter.load(bloom_file)
        t_load = (time.time() - t0) * 1000

        bloom = self._bloom_filters[cache_key]
        actual_fp = bloom.get_actual_fp_rate()
        logger.info(
            f">>> Loaded bloom filter for {cache_key}: {bloom.capacity} tiles, "
            f"{len(bloom.bit_array)} bytes, FP rate={actual_fp:.2%}, load_time={t_load:.1f}ms"
        )

    def _binary_search_tile_position(
        self,
        f,
        target_tile_id: int,
        num_tiles: int,
        entry_size: int,
        find_first: bool = True
    ) -> Optional[int]:
        """
        Binary search for tile position in sorted binary index file.

        Args:
            f: Open file handle positioned after header
            target_tile_id: Tile ID to search for
            num_tiles: Total number of tiles in index
            entry_size: Size of each entry in bytes (16 or 20)
            find_first: If True, find first tile >= target. If False, find last tile <= target.

        Returns:
            File position (offset from file start) of matching entry, or None if not found
        """
        left, right = 0, num_tiles - 1
        result_pos = None

        while left <= right:
            mid = (left + right) // 2
            pos = 8 + mid * entry_size  # 8-byte header + entry offset

            f.seek(pos)
            tile_id_bytes = f.read(4)
            if len(tile_id_bytes) < 4:
                break

            tile_id = struct.unpack("<I", tile_id_bytes)[0]

            if tile_id == target_tile_id:
                return pos  # Exact match
            elif tile_id < target_tile_id:
                if not find_first:
                    result_pos = pos  # Keep track of largest tile < target
                left = mid + 1
            else:  # tile_id > target_tile_id
                if find_first:
                    result_pos = pos  # Keep track of smallest tile > target
                right = mid - 1

        return result_pos

    def _load_tile_range(
        self,
        index_file: Path,
        tile_ids: List[int],
        version: int,
        entry_size: int,
        num_tiles: int
    ) -> Dict[str, Any]:
        """
        Load a contiguous range of tiles using binary search + sequential read.

        This is much faster than seeking to each individual tile, especially on SD cards
        where random seeks are expensive.

        Args:
            index_file: Path to binary index file
            tile_ids: List of tile IDs to load (must be sorted)
            version: Index file version (1 or 2)
            entry_size: Size of each entry (16 for v1, 20 for v2)
            num_tiles: Total number of tiles in index

        Returns:
            Dictionary mapping tile_id (as string) to tile metadata
        """
        if not tile_ids:
            return {}

        # Determine range to load
        min_tile = min(tile_ids)
        max_tile = max(tile_ids)
        tile_set = set(tile_ids)

        index = {}

        with open(index_file, "rb") as f:
            # Find starting position (first tile >= min_tile)
            start_pos = self._binary_search_tile_position(
                f, min_tile, num_tiles, entry_size, find_first=True
            )

            if start_pos is None:
                logger.debug(f">>> No tiles found in range [{min_tile}, {max_tile}]")
                return {}

            # Sequential read from start_pos until we pass max_tile
            f.seek(start_pos)
            tiles_read = 0
            tiles_matched = 0

            while True:
                entry_data = f.read(entry_size)
                if len(entry_data) < entry_size:
                    break  # End of file

                tiles_read += 1

                if version == 1:
                    tile_id, offset, size = struct.unpack("<IQI", entry_data)
                    if tile_id > max_tile:
                        break  # Passed our range

                    if tile_id in tile_set:
                        index[str(tile_id)] = {
                            "offset": int(offset),
                            "size": int(size)
                        }
                        tiles_matched += 1
                else:  # version == 2
                    tile_id, offset, compressed_size, uncompressed_size = struct.unpack("<IQII", entry_data)
                    if tile_id > max_tile:
                        break  # Passed our range

                    if tile_id in tile_set:
                        index[str(tile_id)] = {
                            "offset": int(offset),
                            "size": int(uncompressed_size),
                            "compressed_size": int(compressed_size)
                        }
                        tiles_matched += 1

                # Early exit if we've found all requested tiles
                if tiles_matched >= len(tile_set):
                    break

            logger.debug(
                f">>> Range query: read {tiles_read} entries, "
                f"matched {tiles_matched}/{len(tile_ids)} requested tiles"
            )

        return index

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
                entry_size = 16
                tile_id_dtype = np.dtype([('tile_id', '<u4'), ('_skip', 'V12')])  # Skip 12 bytes
            elif version == 2:
                # [tile_id:4][offset:8][compressed_size:4][uncompressed_size:4]
                entry_size = 20
                tile_id_dtype = np.dtype([('tile_id', '<u4'), ('_skip', 'V16')])  # Skip 16 bytes
            else:
                logger.error(f"Unsupported index version: {version}")
                return existing_tiles

            # Read all tile IDs at once (very fast, just reading integers)
            data = f.read()
            if not data:
                return existing_tiles

            records = np.frombuffer(data, dtype=tile_id_dtype)

            # Convert to set (numpy → set is fast for integers)
            existing_tiles = set(records['tile_id'].tolist())

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
        current_year = datetime.now().year + (datetime.now().timetuple().tm_yday / 365.25)
        years_elapsed = current_year - 2016.0

        # Apply proper motion forward to current epoch
        # pmra is in mas/year and needs cos(dec) correction for RA
        # Vectorized calculation
        ra_corrections = (pmras / 1000 / 3600) / np.cos(np.radians(decs)) * years_elapsed
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
        logger.info(f">>> Cache {cache_key} exceeds limit ({cache_size} > {MAX_INDEX_CACHE_SIZE}), removing {tiles_to_remove} tiles")

        # Build set of protected tiles
        protected_set = {str(tid) for tid in protected_tile_ids}

        # Find eviction candidates (tiles not in current request)
        candidates = [tile_key for tile_key in index.keys() if tile_key not in protected_set]

        if len(candidates) < tiles_to_remove:
            # Not enough non-protected tiles, just remove what we can
            logger.warning(f">>> Only {len(candidates)} evictable tiles, removing all of them")
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
        index_file_bin = band_dir / "index.bin"
        index_file_json = band_dir / "index.json"
        tiles_file = band_dir / "tiles.bin"

        if not tiles_file.exists():
            return np.empty((0, 3))

        cache_key = f"index_{mag_min}_{mag_max}"

        # Bloom filter pre-check: DISABLED for performance testing
        # TODO: Re-enable after Pi performance comparison
        # Saves ~4ms per query by checking bloom filter (0.24ms) vs compressed index (2.4ms)
        # Trade-off: 12 MB RAM for bloom filters vs 4ms per query
        #
        # if cache_key in self._bloom_filters:
        #     bloom = self._bloom_filters[cache_key]
        #     has_any_tile = any(bloom.might_contain(tile_id) for tile_id in tile_ids)
        #     if not has_any_tile:
        #         logger.debug(
        #             f">>> Bloom filter: No tiles exist in {cache_key} for query region, "
        #             f"skipping band"
        #         )
        #         return np.empty((0, 3))

        # Load index - prefer compressed v3 format
        if not hasattr(self, '_index_cache'):
            self._index_cache = {}

        t_index_start = time.time()
        logger.info(f">>> Checking index cache for {cache_key}, in_cache={cache_key in self._index_cache}")
        if cache_key not in self._index_cache:
            # Try compressed index first (v3)
            index_file_v3 = band_dir / "index_v3.bin"
            if index_file_v3.exists():
                logger.info(f">>> Loading compressed index from {index_file_v3}")
                t0 = time.time()
                self._index_cache[cache_key] = CompressedIndex(index_file_v3)
                t_read_index = (time.time() - t0) * 1000
                logger.info(f">>> Compressed index loaded in {t_read_index:.1f}ms")
            elif index_file_bin.exists():
                logger.info(f">>> Loading FULL index from {index_file_bin} (v1/v2 format)")
                t0 = time.time()
                self._index_cache[cache_key] = self._read_binary_index(index_file_bin, needed_tiles=None)
                t_read_index = (time.time() - t0) * 1000
                logger.info(f">>> FULL index loaded, {len(self._index_cache[cache_key])} tiles in {t_read_index:.1f}ms")
            elif index_file_json.exists():
                logger.info(f">>> Reading JSON index from {index_file_json}")
                with open(index_file_json, "r") as f:
                    self._index_cache[cache_key] = json.load(f)
                logger.info(f">>> JSON index loaded, {len(self._index_cache[cache_key])} tiles in cache")
            else:
                logger.warning(f">>> No index file found for {cache_key}")
                return np.empty((0, 3))
        else:
            logger.debug(f">>> Using cached index for {cache_key}")

        index = self._index_cache[cache_key]
        t_index_total = (time.time() - t_index_start) * 1000
        logger.debug(f">>> Index cache operations took {t_index_total:.1f}ms")

        t_readops_start = time.time()
        logger.debug(f">>> Building read_ops for {len(tile_ids)} tiles...")

        # Collect all tile read operations
        # Handle both CompressedIndex and dict formats
        read_ops: List[Tuple[int, Dict[str, int]]] = []
        if isinstance(index, CompressedIndex):
            # Compressed index: use .get() method
            for tile_id in tile_ids:
                tile_tuple = index.get(tile_id)
                if tile_tuple:
                    offset, size = tile_tuple
                    read_ops.append((tile_id, {"offset": offset, "size": size}))
        else:
            # Dict-based index (v1/v2 or JSON)
            for tile_id in tile_ids:
                tile_key = str(tile_id)
                if tile_key in index:
                    tile_info: Dict[str, int] = index[tile_key]
                    read_ops.append((tile_id, tile_info))

        if not read_ops:
            logger.debug(f">>> No tiles to load (all {len(tile_ids)} requested tiles are empty)")
            return np.empty((0, 3))

        # Sort by offset to minimize seeks
        read_ops.sort(key=lambda x: x[1]["offset"])
        t_readops = (time.time() - t_readops_start) * 1000
        logger.debug(f">>> Built {len(read_ops)} read_ops in {t_readops:.1f}ms")

        # Read data in larger sequential chunks when possible
        MAX_GAP = 100 * 1024  # 100KB gap tolerance
        
        # Accumulate arrays
        all_ras = []
        all_decs = []
        all_mags = []
        all_pmras = []
        all_pmdecs = []

        t_io_start = time.time()
        t_decompress_total = 0.0
        t_decode_total = 0.0
        bytes_read = 0
        logger.info(f">>> Batch loading {len(read_ops)} tiles for mag {mag_min}-{mag_max}")
        with open(tiles_file, "rb") as f:
            i = 0
            chunk_num = 0
            while i < len(read_ops):
                chunk_num += 1
                # logger.debug(f">>> Processing chunk {chunk_num}, tile {i+1}/{len(read_ops)}")

                tile_id, tile_info = read_ops[i]
                offset = tile_info["offset"]
                chunk_end = offset + tile_info.get("compressed_size", tile_info["size"])

                # Find consecutive tiles for chunk reading
                tiles_in_chunk: List[Tuple[int, Dict[str, int]]] = [(tile_id, tile_info)]
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
                # logger.debug(f">>> Reading chunk: {len(tiles_in_chunk)} tiles, size={chunk_size} bytes")
                f.seek(offset)
                chunk_data = f.read(chunk_size)
                bytes_read += chunk_size
                # logger.debug(f">>> Chunk read complete, processing tiles...")

                # Process each tile in chunk
                for tile_idx, (tile_id, tile_info) in enumerate(tiles_in_chunk):
                    # logger.debug(f">>> Processing tile {tile_idx+1}/{len(tiles_in_chunk)} (id={tile_id})")
                    tile_offset = tile_info["offset"] - offset
                    compressed_size = tile_info.get("compressed_size")
                    size = tile_info["size"]

                    if compressed_size:
                        t_decomp_start = time.time()
                        import zlib
                        compressed_data = chunk_data[tile_offset:tile_offset + compressed_size]
                        data = zlib.decompress(compressed_data)
                        t_decompress_total += (time.time() - t_decomp_start)
                    else:
                        data = chunk_data[tile_offset:tile_offset + size]

                    # Parse records using shared helper
                    t_decode_start = time.time()
                    ras, decs, mags, pmras, pmdecs = self._parse_records(data)
                    t_decode_total += (time.time() - t_decode_start)
                    
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
        t_concat = (time.time() - t_concat_start) * 1000

        # Apply proper motion
        t_pm_start = time.time()
        result = self._apply_proper_motion((ras_final, decs_final, mags_final, pmras_final, pmdecs_final))
        t_pm = (time.time() - t_pm_start) * 1000

        # Log performance breakdown
        t_io_total = (time.time() - t_io_start) * 1000
        logger.info(
            f">>> Tile I/O performance for mag {mag_min}-{mag_max}: "
            f"total={t_io_total:.1f}ms, decompress={t_decompress_total*1000:.1f}ms, "
            f"decode={t_decode_total*1000:.1f}ms, concat={t_concat:.1f}ms, pm={t_pm:.1f}ms, "
            f"bytes={bytes_read/1024:.1f}KB, stars={len(result)}"
        )

        return result

    def _load_tiles_batch(
        self, tile_ids: List[int], mag_limit: float
    ) -> np.ndarray:
        """
        Batch load multiple tiles efficiently (compact format only)
        Much faster than loading tiles one-by-one due to reduced I/O overhead

        Args:
            tile_ids: List of HEALPix tile IDs
            mag_limit: Maximum magnitude

        Returns:
            Numpy array of shape (N, 3) containing (ra, dec, mag)
        """
        assert self.metadata is not None, "metadata must be loaded before calling _load_tiles_batch"

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
                            # logger.info(f"_load_tiles_batch: Decompressing tile {tile_id}, {compressed_size} → {size} bytes")
                            data = zlib.decompress(compressed_data)
                        else:
                            data = chunk_data[tile_offset:tile_offset + size]

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

        logger.info(f"_load_tiles_batch: Loaded {len(all_ras)} batches of stars, applying proper motion")
        
        if not all_ras:
            return np.empty((0, 3))
            
        # Concatenate all arrays
        ras_final = np.concatenate(all_ras)
        decs_final = np.concatenate(all_decs)
        mags_final = np.concatenate(all_mags)
        pmras_final = np.concatenate(all_pmras)
        pmdecs_final = np.concatenate(all_pmdecs)
        
        # Apply proper motion
        result = self._apply_proper_motion((ras_final, decs_final, mags_final, pmras_final, pmdecs_final))
        logger.info(f"_load_tiles_batch: Complete, returning {len(result)} stars")
        return result
