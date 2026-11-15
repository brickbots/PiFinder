import json
import shutil
import struct
import tempfile
import unittest
from pathlib import Path

import healpy as hp  # type: ignore[import-untyped]
import numpy as np
import pytest

from PiFinder.object_images.star_catalog import (
    CatalogState,
    GaiaStarCatalog,
    TileIndex,
    tile_byte_size,
    tile_star_count,
)

pytestmark = pytest.mark.unit


def build_dense_index(counts, num_pixels=256, stride=16, mag_bits=8, version=4):
    """Bytes of a dense tile index (see TileIndex).

    counts: {pixel: number of stars}. Tiles are back to back in pixel order.
    """
    full = [counts.get(p, 0) for p in range(num_pixels)]
    sizes = [tile_byte_size(n, mag_bits) for n in full]
    starts = [sum(sizes[:p]) for p in range(0, num_pixels, stride)]
    overflow = [(p, n) for p, n in enumerate(full) if n >= 255]
    data = struct.pack("<IIII", version, num_pixels, stride, len(overflow))
    data += bytes(min(n, 255) for n in full)
    data += struct.pack(f"<{len(starts)}Q", *starts)
    for p, n in overflow:
        data += struct.pack("<II", p, n)
    return data


class TestTileIndex(unittest.TestCase):
    """Tests for the dense tile index reader."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.path = Path(self.test_dir) / "index.bin"

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def _open(self, data, mag_bits=8):
        self.path.write_bytes(data)
        idx = TileIndex(self.path, mag_bits)
        self.addCleanup(idx.close)
        return idx

    def test_offsets_add_up_the_tiles_before(self):
        idx = self._open(build_dense_index({10: 3, 11: 5, 13: 1}))
        self.assertEqual(idx.num_tiles, 3)
        self.assertEqual(idx.get(10), (0, 9))
        self.assertEqual(idx.get(11), (9, 15))
        self.assertEqual(idx.get(13), (24, 3))

    def test_checkpoint_starts_each_stride(self):
        # Stride 4: pixels 5 and 9 are in later strides than pixel 2.
        idx = self._open(build_dense_index({2: 1, 5: 2, 9: 4}, 16, 4))
        self.assertEqual(idx.get(2), (0, 3))
        self.assertEqual(idx.get(5), (3, 6))
        self.assertEqual(idx.get(9), (9, 12))

    def test_count_of_255_or_more_is_in_the_overflow_list(self):
        idx = self._open(build_dense_index({3: 300, 4: 255, 5: 2}))
        self.assertEqual(idx.get(3), (0, 900))
        self.assertEqual(idx.get(4), (900, 765))
        self.assertEqual(idx.get(5), (1665, 6))

    def test_four_bit_tile_sizes(self):
        idx = self._open(build_dense_index({0: 3, 1: 2}, mag_bits=4), mag_bits=4)
        self.assertEqual(idx.get(0), (0, 8))
        self.assertEqual(idx.get(1), (8, 5))

    def test_missing_tiles_return_none(self):
        idx = self._open(build_dense_index({10: 3}))
        self.assertIsNone(idx.get(9))
        self.assertIsNone(idx.get(11))
        self.assertIsNone(idx.get(-1))
        self.assertIsNone(idx.get(256))
        self.assertIsNone(idx.get(2**33))

    def test_close_twice(self):
        idx = self._open(build_dense_index({10: 3}))
        idx.close()
        idx.close()
        self.assertIsNone(idx.get(10))

    def test_wrong_version_raises(self):
        self.path.write_bytes(build_dense_index({0: 1}, version=3))
        with self.assertRaises(ValueError):
            TileIndex(self.path, 8)


def columnar_tile(ra, dec, tenths, mag_bits, mag_base=0):
    """Bytes of one columnar tile: ra[n], dec[n], then the magnitudes."""
    data = bytes(ra) + bytes(dec)
    if mag_bits == 8:
        return data + bytes(tenths)
    rel = [t - mag_base for t in tenths]
    nibbles = bytearray((len(rel) + 1) // 2)
    for k, value in enumerate(rel):
        nibbles[k // 2] |= value << (4 * (k & 1))
    return data + bytes(nibbles)


BAND_8 = {"min": 14, "max": 16, "mag_bits": 8, "mag_base": 0}
BAND_4 = {"min": 16, "max": 17, "mag_bits": 4, "mag_base": 160}


class TestTileSizes(unittest.TestCase):
    def test_star_count_inverts_byte_size(self):
        for mag_bits in (4, 8):
            for n in range(0, 200):
                size = tile_byte_size(n, mag_bits)
                self.assertEqual(tile_star_count(size, mag_bits), n)


class TestColumnarDecode(unittest.TestCase):
    def setUp(self):
        self.catalog = GaiaStarCatalog(tempfile.mkdtemp())
        self.catalog.nside = 512
        self.addCleanup(shutil.rmtree, str(self.catalog.catalog_path))

    def test_eight_bit_magnitudes(self):
        data = columnar_tile([0, 255, 128], [10, 20, 30], [140, 151, 159], 8)
        ras, _, mags, _, _ = self.catalog._parse_records(data, 1000, BAND_8)
        np.testing.assert_allclose(mags, [14.0, 15.1, 15.9])
        self.assertEqual(len(ras), 3)

    def test_four_bit_magnitudes_odd_count(self):
        # Star 2k in the low nibble, star 2k+1 in the high nibble.
        data = columnar_tile([1, 2, 3], [4, 5, 6], [160, 169, 163], 4, 160)
        self.assertEqual(len(data), 2 * 3 + 2)
        _, _, mags, _, _ = self.catalog._parse_records(data, 1000, BAND_4)
        np.testing.assert_allclose(mags, [16.0, 16.9, 16.3])

    def test_four_bit_magnitudes_even_count(self):
        data = columnar_tile([1, 2], [4, 5], [165, 161], 4, 160)
        _, _, mags, _, _ = self.catalog._parse_records(data, 1000, BAND_4)
        np.testing.assert_allclose(mags, [16.5, 16.1])

    def test_columns_are_ra_then_dec(self):
        # The same offset bytes give the pixel centre plus the same shift.
        tile = 12345
        data = columnar_tile([255, 0], [0, 255], [150, 150], 8)
        ras, decs, _, _, _ = self.catalog._parse_records(data, tile, BAND_8)
        centre_ra, centre_dec = hp.pix2ang(512, tile, lonlat=True)
        self.assertGreater(ras[0], centre_ra)
        self.assertLess(decs[0], centre_dec)
        self.assertLess(ras[1], centre_ra)
        self.assertGreater(decs[1], centre_dec)

    def test_size_that_is_not_whole_stars_is_rejected(self):
        ras, _, _, _, _ = self.catalog._parse_records(b"\x00" * 4, 1, BAND_8)
        self.assertEqual(len(ras), 0)

    def test_empty_tile(self):
        ras, _, _, _, _ = self.catalog._parse_records(b"", 1, BAND_4)
        self.assertEqual(len(ras), 0)


class TestCatalogFiles(unittest.TestCase):
    """A small catalog on disk, read through the public load path."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(self.root))

    def write_catalog(self, fmt="columnar", version="3.0"):
        tiles = {
            100: ([10, 200], [30, 40], [160, 167]),
            101: ([50], [60], [169]),
        }
        blob = b""
        for tile_id in sorted(tiles):
            ra, dec, tenths = tiles[tile_id]
            blob += columnar_tile(ra, dec, tenths, 4, 160)
        counts = {tile_id: len(tiles[tile_id][0]) for tile_id in tiles}
        band_dir = self.root / "mag_16_17"
        band_dir.mkdir()
        (band_dir / "tiles.bin").write_bytes(blob)
        (band_dir / "index.bin").write_bytes(build_dense_index(counts, mag_bits=4))
        meta = {
            "format": fmt,
            "catalog_version": version,
            "nside": 512,
            "mag_limit": 17.0,
            "star_count": 3,
            "mag_bands": [dict(BAND_4, tiles=2, stars=3)],
        }
        (self.root / "metadata.json").write_text(json.dumps(meta))

    def load(self):
        catalog = GaiaStarCatalog(str(self.root))
        catalog._background_load_worker()
        return catalog

    def test_band_load_returns_all_stars(self):
        self.write_catalog()
        catalog = self.load()
        self.assertEqual(catalog.state, CatalogState.READY)
        band = catalog.metadata["mag_bands"][0]
        stars = catalog._load_tiles_batch_single_band([100, 101, 102], band, 17.0)
        np.testing.assert_allclose(sorted(stars[:, 2]), [16.0, 16.7, 16.9])

    def test_magnitude_limit_filters_stars(self):
        self.write_catalog()
        catalog = self.load()
        band = catalog.metadata["mag_bands"][0]
        stars = catalog._load_tiles_batch_single_band([100, 101], band, 16.5)
        np.testing.assert_allclose(stars[:, 2], [16.0])

    def test_older_format_is_refused(self):
        self.write_catalog(fmt="compact", version="2.1")
        catalog = self.load()
        self.assertEqual(catalog.state, CatalogState.NOT_LOADED)
        self.assertIsNone(catalog.metadata)


if __name__ == "__main__":
    unittest.main()
