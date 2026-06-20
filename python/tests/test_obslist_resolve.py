"""
Tests for name-based observing-list resolution: constellation-genitive
normalization and exact name lookup. These let lists that identify objects
only by name (e.g. carbon stars "VY Andromedae") match the catalog.
"""

import pytest

from PiFinder.obslist import _normalize_designation, resolve_by_name


@pytest.mark.unit
class TestNormalizeDesignation:
    def test_single_word_genitive(self):
        assert _normalize_designation("VY Andromedae") == "VY And"
        assert _normalize_designation("R Leonis") == "R Leo"

    def test_two_word_genitive(self):
        assert _normalize_designation("RS Canum Venaticorum") == "RS CVn"
        assert _normalize_designation("T Coronae Borealis") == "T CrB"

    def test_not_a_constellation(self):
        assert _normalize_designation("M 31") is None
        assert _normalize_designation("NGC7640") is None
        assert _normalize_designation("Andromeda") is None  # single token

    def test_case_insensitive(self):
        assert _normalize_designation("vy andromedae") == "vy And"


@pytest.mark.unit
class TestResolveByName:
    def test_exact_match(self):
        index = {"andromeda galaxy": "M31", "vy and": "SaR7"}
        assert resolve_by_name("Andromeda Galaxy", index) == "M31"

    def test_normalized_match(self):
        index = {"vy and": "SaR7"}
        assert resolve_by_name("VY Andromedae", index) == "SaR7"

    def test_exact_preferred_over_normalized(self):
        index = {"vy andromedae": "EXACT", "vy and": "NORM"}
        assert resolve_by_name("VY Andromedae", index) == "EXACT"

    def test_no_match(self):
        assert resolve_by_name("CGCS135", {"vy and": "SaR7"}) is None

    def test_empty_name(self):
        assert resolve_by_name("", {"x": 1}) is None
