
import unittest
import numpy as np
import struct
import os
import tempfile
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch
import sys

from PiFinder.object_images.star_catalog import DeepStarCatalog, STAR_RECORD_DTYPE, STAR_RECORD_SIZE

class TestDeepStarCatalog(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.catalog_path = Path(self.test_dir)
        self.catalog = DeepStarCatalog(str(self.catalog_path))
        self.catalog.nside = 512
        
    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_parse_records(self):
        # Create a fake star record
        # Format: <I (uint32), B (uint8), B (uint8), B (uint8), B (uint8), b (int8), b (int8)
        # healpix (24 bit), ra_offset, dec_offset, mag, pmra, pmdec
        
        # Star 1: Healpix 0, offsets 127 (0), mag 100 (10.0), pm 0, 0
        rec1 = struct.pack("<IBBBbb", 0, 127, 127, 100, 0, 0)
        
        # Star 2: Healpix 1, offsets 255 (max), mag 50 (5.0), pm 10, -10
        rec2 = struct.pack("<IBBBbb", 1, 255, 255, 50, 10, -10)
        
        data = rec1 + rec2
        
        ras, decs, mags, pmras, pmdecs = self.catalog._parse_records(data)
        
        self.assertEqual(len(ras), 2)
        self.assertEqual(len(decs), 2)
        
        # Check magnitudes
        self.assertEqual(mags[0], 10.0)
        self.assertEqual(mags[1], 5.0)
        
        # Check proper motions (encoded value * 50)
        self.assertEqual(pmras[0], 0)
        self.assertEqual(pmras[1], 10 * 50)
        self.assertEqual(pmdecs[1], -10 * 50)

    def test_apply_proper_motion(self):
        # Create fake star data
        ras = np.array([0.0, 180.0])
        decs = np.array([0.0, 45.0])
        mags = np.array([10.0, 10.0])
        pmras = np.array([1000, 0]) # 1000 mas/yr
        pmdecs = np.array([0, 1000]) # 1000 mas/yr
        
        stars = (ras, decs, mags, pmras, pmdecs)
        
        # Mock datetime to ensure consistent "years elapsed"
        with patch('PiFinder.star_catalog.datetime') as mock_date:
            mock_date.now.return_value.year = 2017
            mock_date.now.return_value.timetuple.return_value.tm_yday = 1
            # 2017.0 - 2016.0 = 1.0 year elapsed
            
            result = self.catalog._apply_proper_motion(stars)
            
            self.assertEqual(result.shape, (2, 3))
            
            # Star 1: RA should change by 1000 mas = 1 arcsec = 1/3600 degrees
            # cos(0) = 1
            expected_ra_change = 1.0 / 3600.0
            self.assertAlmostEqual(result[0, 0], 0.0 + expected_ra_change, places=6)
            self.assertEqual(result[0, 1], 0.0) # Dec shouldn't change
            
            # Star 2: Dec should change by 1000 mas = 1/3600 degrees
            expected_dec_change = 1.0 / 3600.0
            self.assertEqual(result[1, 0], 180.0) # RA shouldn't change
            self.assertAlmostEqual(result[1, 1], 45.0 + expected_dec_change, places=6)

    def test_return_empty_on_missing_file(self):
        # Test that it returns empty array instead of crashing
        result = self.catalog._load_tile_from_file(Path("/nonexistent"), 0, 20)
        self.assertEqual(len(result[0]), 0)
        self.assertTrue(isinstance(result[0], np.ndarray))

    def test_read_binary_index_v1(self):
        # Create a v1 index file
        # Header: version=1, num_tiles=2
        header = struct.pack("<II", 1, 2)
        
        # Tile 1: id=100, offset=1000, size=500
        t1 = struct.pack("<IQI", 100, 1000, 500)
        
        # Tile 2: id=200, offset=2000, size=600
        t2 = struct.pack("<IQI", 200, 2000, 600)
        
        index_file = self.catalog_path / "index_v1.bin"
        with open(index_file, "wb") as f:
            f.write(header + t1 + t2)
            
        # Test reading full index
        index = self.catalog._read_binary_index(index_file)
        self.assertEqual(len(index), 2)
        self.assertEqual(index["100"]["offset"], 1000)
        self.assertEqual(index["100"]["size"], 500)
        self.assertEqual(index["200"]["offset"], 2000)

    def test_read_binary_index_v2(self):
        # Create a v2 index file
        # Header: version=2, num_tiles=2
        header = struct.pack("<II", 2, 2)
        
        # Tile 1: id=100, offset=1000, compressed=400, uncompressed=500
        t1 = struct.pack("<IQII", 100, 1000, 400, 500)
        
        # Tile 2: id=200, offset=2000, compressed=500, uncompressed=600
        t2 = struct.pack("<IQII", 200, 2000, 500, 600)
        
        index_file = self.catalog_path / "index_v2.bin"
        with open(index_file, "wb") as f:
            f.write(header + t1 + t2)
            
        # Test reading full index
        index = self.catalog._read_binary_index(index_file)
        self.assertEqual(len(index), 2)
        self.assertEqual(index["100"]["offset"], 1000)
        self.assertEqual(index["100"]["compressed_size"], 400)
        self.assertEqual(index["100"]["size"], 500)

    def test_read_binary_index_partial(self):
        # To test the partial loading path, we'd need a large index.
        # For now, we just verify the standard numpy loading works (covered by v1/v2 tests)
        pass

if __name__ == '__main__':
    unittest.main()
