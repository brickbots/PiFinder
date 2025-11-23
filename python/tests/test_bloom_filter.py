#!/usr/bin/env python3
"""
Unit tests for TileBloomFilter implementation.

Tests cover:
- Basic functionality (add, might_contain)
- False positive rate validation
- Save/load persistence
- Edge cases (empty filter, large capacity)
- Integration with star catalog
"""

import math
import tempfile
from pathlib import Path

import pytest

from PiFinder.star_catalog import TileBloomFilter


class TestTileBloomFilterBasics:
    """Test basic bloom filter operations."""

    def test_empty_filter(self):
        """Test empty filter returns False for all queries."""
        bloom = TileBloomFilter(capacity=100, fp_rate=0.01)

        # Empty filter should never contain anything
        assert not bloom.might_contain(1)
        assert not bloom.might_contain(100)
        assert not bloom.might_contain(999999)

    def test_single_item(self):
        """Test filter with single item."""
        bloom = TileBloomFilter(capacity=100, fp_rate=0.01)

        bloom.add(42)

        # Should definitely contain the added item
        assert bloom.might_contain(42)

        # Should not contain other items (with high probability)
        # Note: Can't guarantee 100% due to false positives, but very unlikely for single item
        assert not bloom.might_contain(1)
        assert not bloom.might_contain(43)

    def test_multiple_items(self):
        """Test filter with multiple items."""
        bloom = TileBloomFilter(capacity=100, fp_rate=0.01)

        items = [10, 20, 30, 40, 50]
        for item in items:
            bloom.add(item)

        # All added items should be present
        for item in items:
            assert bloom.might_contain(item), f"Item {item} should be in filter"

        # Items not added should mostly not be present
        # (allowing for false positives)
        not_added = [11, 21, 31, 41, 51, 100, 200, 300]
        false_positives = sum(1 for item in not_added if bloom.might_contain(item))

        # With 1% FP rate and 8 queries, expect ~0.08 false positives
        # Allow up to 3 for statistical variation
        assert false_positives <= 3, f"Too many false positives: {false_positives}/8"

    def test_large_dataset(self):
        """Test filter with many items."""
        capacity = 1000
        bloom = TileBloomFilter(capacity=capacity, fp_rate=0.01)

        # Add 1000 items
        items = list(range(1000, 2000))
        for item in items:
            bloom.add(item)

        # All added items should be present
        for item in items:
            assert bloom.might_contain(item)

        # Check false positive rate on items not added
        not_added = list(range(3000, 4000))  # 1000 items
        false_positives = sum(1 for item in not_added if bloom.might_contain(item))
        actual_fp_rate = false_positives / len(not_added)

        # Should be close to 1% (allow 0-3% due to statistical variation)
        assert 0 <= actual_fp_rate <= 0.03, f"FP rate {actual_fp_rate:.2%} outside expected range"

    def test_duplicate_adds(self):
        """Test that adding same item multiple times doesn't break filter."""
        bloom = TileBloomFilter(capacity=100, fp_rate=0.01)

        # Add same item multiple times
        for _ in range(10):
            bloom.add(42)

        # Should still contain the item
        assert bloom.might_contain(42)

        # Should not affect other items
        assert not bloom.might_contain(43)


class TestTileBloomFilterMath:
    """Test bloom filter mathematical properties."""

    def test_optimal_bit_calculation(self):
        """Test optimal bit array size calculation."""
        # Formula: m = -(n * ln(p)) / (ln(2)^2)
        # For n=1000, p=0.01: m ≈ 9586 bits

        bits = TileBloomFilter._optimal_num_bits(1000, 0.01)

        expected = -(1000 * math.log(0.01)) / (math.log(2) ** 2)
        assert abs(bits - expected) < 1  # Allow for rounding

    def test_optimal_hash_calculation(self):
        """Test optimal number of hash functions calculation."""
        # Formula: k = (m/n) * ln(2)
        # For m=9586, n=1000: k ≈ 7

        num_hashes = TileBloomFilter._optimal_num_hashes(9586, 1000)

        expected = (9586 / 1000) * math.log(2)
        assert abs(num_hashes - expected) < 1

        # Should always have at least 1 hash function
        assert num_hashes >= 1

    def test_actual_fp_rate_calculation(self):
        """Test actual false positive rate calculation."""
        bloom = TileBloomFilter(capacity=1000, fp_rate=0.01)

        actual_fp = bloom.get_actual_fp_rate()

        # Should be close to configured 1%
        assert actual_fp is not None
        assert 0.005 <= actual_fp <= 0.015  # Within 0.5%-1.5%

    def test_zero_capacity(self):
        """Test filter with zero capacity."""
        bloom = TileBloomFilter(capacity=0, fp_rate=0.01)

        # get_actual_fp_rate should return None for empty filter
        assert bloom.get_actual_fp_rate() is None


class TestTileBloomFilterPersistence:
    """Test bloom filter save/load functionality."""

    def test_save_and_load(self):
        """Test saving and loading bloom filter."""
        # Create and populate filter
        bloom1 = TileBloomFilter(capacity=100, fp_rate=0.01)
        items = [10, 20, 30, 40, 50]
        for item in items:
            bloom1.add(item)

        # Save to temporary file
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
            temp_path = Path(f.name)

        try:
            bloom1.save(temp_path)

            # Load from file
            bloom2 = TileBloomFilter.load(temp_path)

            # Check all properties match
            assert bloom2.capacity == bloom1.capacity
            assert bloom2.fp_rate == bloom1.fp_rate
            assert bloom2.num_bits == bloom1.num_bits
            assert bloom2.num_hashes == bloom1.num_hashes
            assert bloom2.bit_array == bloom1.bit_array

            # Check functionality preserved
            for item in items:
                assert bloom2.might_contain(item), f"Item {item} should be in loaded filter"

            assert not bloom2.might_contain(99)

        finally:
            temp_path.unlink(missing_ok=True)

    def test_load_nonexistent_file(self):
        """Test loading from non-existent file."""
        with pytest.raises(FileNotFoundError):
            TileBloomFilter.load(Path("/nonexistent/bloom.bin"))

    def test_load_corrupted_file(self):
        """Test loading from corrupted file."""
        # Create corrupted file (too small)
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
            temp_path = Path(f.name)
            f.write(b"corrupted")

        try:
            with pytest.raises(ValueError, match="too small"):
                TileBloomFilter.load(temp_path)
        finally:
            temp_path.unlink(missing_ok=True)

    def test_save_creates_valid_format(self):
        """Test that saved file has correct binary format."""
        bloom = TileBloomFilter(capacity=100, fp_rate=0.02)
        bloom.add(42)

        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
            temp_path = Path(f.name)

        try:
            bloom.save(temp_path)

            # Verify file structure
            with open(temp_path, "rb") as f:
                # Header should be 24 bytes
                import struct
                header = f.read(24)
                assert len(header) == 24

                version, capacity, fp_rate, num_bits, num_hashes = struct.unpack('<IIdII', header)

                assert version == 1
                assert capacity == 100
                assert abs(fp_rate - 0.02) < 0.001
                assert num_bits == bloom.num_bits
                assert num_hashes == bloom.num_hashes

                # Bit array should follow
                bit_array_size = (num_bits + 7) // 8
                bit_array = f.read(bit_array_size)
                assert len(bit_array) == bit_array_size

        finally:
            temp_path.unlink(missing_ok=True)


class TestTileBloomFilterEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_very_small_capacity(self):
        """Test filter with capacity of 1."""
        bloom = TileBloomFilter(capacity=1, fp_rate=0.01)

        bloom.add(42)

        assert bloom.might_contain(42)

    def test_very_large_capacity(self):
        """Test filter with large capacity (realistic for star catalog)."""
        # This simulates mag 12-14 band with ~2.7M tiles
        bloom = TileBloomFilter(capacity=2_700_000, fp_rate=0.01)

        # Add some representative tiles
        tiles = [100000, 500000, 1000000, 1500000, 2000000]
        for tile in tiles:
            bloom.add(tile)

        # Verify all are present
        for tile in tiles:
            assert bloom.might_contain(tile)

        # Bit array should be ~3.2 MB
        assert len(bloom.bit_array) > 3_000_000  # ~3 MB

    def test_high_fp_rate(self):
        """Test filter with high false positive rate (10%)."""
        bloom = TileBloomFilter(capacity=100, fp_rate=0.10)

        items = list(range(100))
        for item in items:
            bloom.add(item)

        # Should still contain all added items
        for item in items:
            assert bloom.might_contain(item)

        # FP rate should be close to 10%
        actual_fp = bloom.get_actual_fp_rate()
        assert 0.05 <= actual_fp <= 0.15  # Allow 5-15% range

    def test_low_fp_rate(self):
        """Test filter with very low false positive rate (0.1%)."""
        bloom = TileBloomFilter(capacity=100, fp_rate=0.001)

        items = list(range(100))
        for item in items:
            bloom.add(item)

        # Should contain all added items
        for item in items:
            assert bloom.might_contain(item)

        # Bit array should be larger (lower FP rate = more bits)
        bloom_high_fp = TileBloomFilter(capacity=100, fp_rate=0.01)
        assert len(bloom.bit_array) > len(bloom_high_fp.bit_array)

    def test_tile_id_range(self):
        """Test with realistic HEALPix tile IDs."""
        # HEALPix nside=512 has 3,145,728 tiles
        # Tile IDs range from 0 to 3,145,727
        bloom = TileBloomFilter(capacity=10000, fp_rate=0.01)

        # Add some tiles from different parts of the sky
        tiles = [0, 1, 100, 1000, 10000, 100000, 1000000, 3145727]
        for tile_id in tiles:
            bloom.add(tile_id)

        # All should be present
        for tile_id in tiles:
            assert bloom.might_contain(tile_id), f"Tile {tile_id} should be in filter"

    def test_hash_distribution(self):
        """Test that hash function distributes items evenly."""
        bloom = TileBloomFilter(capacity=1000, fp_rate=0.01)

        # Add 1000 sequential tile IDs
        for tile_id in range(1000):
            bloom.add(tile_id)

        # Count set bits
        set_bits = sum(
            1 for byte in bloom.bit_array
            for bit in range(8)
            if byte & (1 << bit)
        )

        # With good hash distribution, ~50-70% of bits should be set
        # (depends on num_hashes and capacity)
        bit_fill_ratio = set_bits / bloom.num_bits
        assert 0.3 <= bit_fill_ratio <= 0.8, f"Bit fill ratio {bit_fill_ratio:.2%} suggests poor distribution"


class TestTileBloomFilterIntegration:
    """Test integration with star catalog use cases."""

    def test_sparse_sky_coverage(self):
        """Test bloom filter behavior with sparse tile coverage (like mag 0-6)."""
        # Mag 0-6 has only 6,465 tiles out of 3.1M possible
        # Most queries will be for non-existent tiles
        bloom = TileBloomFilter(capacity=6465, fp_rate=0.01)

        # Add actual tiles (scattered across sky)
        actual_tiles = [i * 500 for i in range(6465)]  # Sparse distribution
        for tile_id in actual_tiles:
            bloom.add(tile_id)

        # Query for tiles in a typical FOV (48 tiles)
        query_tiles = list(range(1000, 1048))  # Probably no bright stars here

        # Most should be filtered out (not in bloom filter)
        passed = [t for t in query_tiles if bloom.might_contain(t)]

        # Expect ~1% false positive rate: 48 * 0.01 = 0.48, so 0-2 tiles
        assert len(passed) <= 3, f"Too many tiles passed filter: {len(passed)}/48"

    def test_dense_sky_coverage(self):
        """Test bloom filter behavior with dense tile coverage (like mag 14-17)."""
        # Mag 14-17 has 3.1M tiles (98% coverage)
        # Most queries will find tiles
        bloom = TileBloomFilter(capacity=3_100_000, fp_rate=0.01)

        # Add most tiles (simulating 98% coverage)
        # For testing, add every tile except multiples of 50
        for tile_id in range(3_100_000):
            if tile_id % 50 != 0:
                bloom.add(tile_id)

        # Query for tiles in a typical FOV (48 tiles)
        query_tiles = list(range(1000000, 1000048))

        # Most should pass filter (they exist)
        passed = [t for t in query_tiles if bloom.might_contain(t)]

        # Should pass most tiles (minus the 2% that don't exist + some FP)
        assert len(passed) >= 44, f"Too few tiles passed: {len(passed)}/48"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
