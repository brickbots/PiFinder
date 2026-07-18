import struct
import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np

from PiFinder.object_images.star_catalog import CompressedIndex, GaiaStarCatalog


def build_v3_index(runs, version=3):
    """Build a v3 run-length-encoded index file image.

    Format (see CompressedIndex):
      header:        <III  version, num_tiles, num_runs
      run directory: <IQ   start_tile, data_offset   (one per run)
      run data:      <HQ   run_length, offset_base    (at data_offset)
                     <H*   per-tile sizes             (run_length of them)

    runs: list of (start_tile, offset_base, [tile_size, ...]).
    """
    num_runs = len(runs)
    num_tiles = sum(len(sizes) for _, _, sizes in runs)

    header = struct.pack("<III", version, num_tiles, num_runs)
    directory_size = num_runs * 12  # <IQ per run
    data_cursor = len(header) + directory_size

    directory = b""
    blocks = []
    for start_tile, offset_base, sizes in runs:
        directory += struct.pack("<IQ", start_tile, data_cursor)
        block = struct.pack("<HQ", len(sizes), offset_base)
        block += struct.pack(f"<{len(sizes)}H", *sizes)
        blocks.append(block)
        data_cursor += len(block)

    return header + directory + b"".join(blocks)


class TestCompressedIndex(unittest.TestCase):
    """Tests for the v3 run-length-encoded binary tile index reader."""

    # Two runs with a gap (tiles 13-19 do not exist):
    #   run A: tiles 10,11,12  offset_base 1000  sizes 100,200,50
    #   run B: tiles 20,21     offset_base 5000  sizes 300,400
    RUNS = [(10, 1000, [100, 200, 50]), (20, 5000, [300, 400])]

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.path = Path(self.test_dir) / "index_v3.bin"

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def _open(self, data):
        with open(self.path, "wb") as f:
            f.write(data)
        idx = CompressedIndex(self.path)
        self.addCleanup(idx.close)
        return idx

    def test_header_tile_count(self):
        idx = self._open(build_v3_index(self.RUNS))
        self.assertEqual(idx.num_tiles, 5)
        self.assertEqual(len(idx.run_directory), 2)

    def test_offsets_are_cumulative_within_a_run(self):
        idx = self._open(build_v3_index(self.RUNS))
        # tile_offset = offset_base + sum(preceding sizes in run); tile_size = own size
        self.assertEqual(idx.get(10), (1000, 100))
        self.assertEqual(idx.get(11), (1100, 200))
        self.assertEqual(idx.get(12), (1300, 50))

    def test_second_run_uses_its_own_offset_base(self):
        idx = self._open(build_v3_index(self.RUNS))
        self.assertEqual(idx.get(20), (5000, 300))
        self.assertEqual(idx.get(21), (5300, 400))

    def test_missing_tiles_return_none(self):
        idx = self._open(build_v3_index(self.RUNS))
        self.assertIsNone(idx.get(5))  # before the first run
        self.assertIsNone(idx.get(13))  # past run A length, still in run A's id span
        self.assertIsNone(idx.get(17))  # in the gap between runs
        self.assertIsNone(idx.get(22))  # past the last run's length

    def test_single_run_lookup(self):
        idx = self._open(build_v3_index([(0, 0, [42])]))
        self.assertEqual(idx.get(0), (0, 42))
        self.assertIsNone(idx.get(1))

    def test_wrong_version_raises(self):
        with open(self.path, "wb") as f:
            f.write(build_v3_index([(0, 0, [1])], version=2))
        with self.assertRaises(ValueError):
            CompressedIndex(self.path)


class TestGaiaStarCatalog(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.catalog = GaiaStarCatalog(self.test_dir)
        self.catalog.nside = 512

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_return_empty_on_missing_file(self):
        # Returns an empty array instead of crashing on a missing tile file.
        result = self.catalog._load_tile_from_file(Path("/nonexistent"), 0, 20)
        self.assertEqual(len(result[0]), 0)
        self.assertTrue(isinstance(result[0], np.ndarray))


if __name__ == "__main__":
    unittest.main()
