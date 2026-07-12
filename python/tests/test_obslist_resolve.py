"""
Tests for name-based observing-list resolution: constellation-genitive
normalization and exact name lookup. These let lists that identify objects
only by name (e.g. carbon stars "VY Andromedae") match the catalog.

Also covers read_list()'s error handling: a single bad entry is skipped and the
rest still load, while a systemic resolution failure is returned as the error
dict (never propagated -- UIObsList.key_right has no handler and would crash).
"""

from types import SimpleNamespace

import pytest

from PiFinder import obslist
from PiFinder.obslist import _normalize_designation, resolve_by_name
from PiFinder.obslist_formats import ObsList, ObsListEntry
from PiFinder.ui.ui_utils import normalize


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
        index = {normalize("Andromeda Galaxy"): "M31", normalize("VY And"): "SaR7"}
        assert resolve_by_name("Andromeda Galaxy", index) == "M31"

    def test_normalized_match(self):
        index = {normalize("VY And"): "SaR7"}
        assert resolve_by_name("VY Andromedae", index) == "SaR7"

    def test_exact_preferred_over_normalized(self):
        index = {normalize("VY Andromedae"): "EXACT", normalize("VY And"): "NORM"}
        assert resolve_by_name("VY Andromedae", index) == "EXACT"

    def test_no_match(self):
        assert resolve_by_name("CGCS135", {normalize("VY And"): "SaR7"}) is None

    def test_spacing_insensitive(self):
        # A CSV "M 13" matches an object stored as "M13" (no space), and vice versa.
        index = {normalize("M13"): "OBJ"}
        assert resolve_by_name("M 13", index) == "OBJ"
        assert resolve_by_name("M13", index) == "OBJ"

    def test_empty_name(self):
        assert resolve_by_name("", {"x": 1}) is None


@pytest.mark.unit
class TestCoordinateObjectType:
    def test_unknown_type_becomes_question_mark(self):
        # A raw source type string ("Nebula") matches no Type filter entry,
        # which would hide the object from every filtered list.
        entry = ObsListEntry(name="Ring Nebula", ra=283.4, dec=33.0, obj_type="Nebula")
        assert obslist._coordinate_object(entry, 0).obj_type == "?"

    def test_known_code_kept(self):
        entry = ObsListEntry(name="M 57", ra=283.4, dec=33.0, obj_type="PN")
        assert obslist._coordinate_object(entry, 0).obj_type == "PN"

    def test_empty_type_becomes_question_mark(self):
        entry = ObsListEntry(name="X", ra=1.0, dec=2.0)
        assert obslist._coordinate_object(entry, 0).obj_type == "?"


def _entry(name, code, seq, desc=""):
    """Minimal catalog-resolvable entry (read_list reads catalog_code+sequence)."""
    return ObsListEntry(
        name=name,
        ra=10.0,
        dec=20.0,
        obj_type="Gx",
        catalog_code=code,
        sequence=seq,
        description=desc,
    )


@pytest.mark.unit
class TestReadListErrorHandling:
    """read_list's resolution loop must not propagate exceptions to the UI."""

    def test_per_entry_failure_skips_and_continues(self, monkeypatch):
        # First entry's lookup raises, second resolves -- the list still loads.
        obs_list = ObsList(
            name="Mixed",
            entries=[_entry("NGC 224", "NGC", 224), _entry("M 42", "M", 42)],
        )
        monkeypatch.setattr(obslist, "formats_read_file", lambda path: obs_list)

        resolved = SimpleNamespace(list_descriptions={})

        def fake_resolve(catalog_numbers, catalogs):
            if "NGC 224" in catalog_numbers:
                raise RuntimeError("bad row")
            return resolved

        monkeypatch.setattr(obslist, "resolve_object", fake_resolve)

        result = obslist.read_list(catalogs=None, name="Mixed.skylist")

        assert result["result"] == "success"
        assert result["objects_parsed"] == 2
        # The bad entry is dropped (not turned into a coordinate object); only
        # the one that resolved survives.
        assert result["catalog_objects"] == [resolved]

    def test_all_entries_fail_returns_error(self, monkeypatch):
        # Every lookup raises (e.g. catalog DB unavailable): systemic, so report
        # an error rather than a silent "0 objects" success.
        obs_list = ObsList(
            name="AllBad",
            entries=[_entry("NGC 224", "NGC", 224), _entry("M 42", "M", 42)],
        )
        monkeypatch.setattr(obslist, "formats_read_file", lambda path: obs_list)

        def fake_resolve(catalog_numbers, catalogs):
            raise RuntimeError("catalog db gone")

        monkeypatch.setattr(obslist, "resolve_object", fake_resolve)

        result = obslist.read_list(catalogs=None, name="AllBad.skylist")

        assert result["result"] == "error"
        assert result["objects_parsed"] == 2
        assert result["catalog_objects"] == []
        assert "catalog db gone" in result["message"]

    def test_catastrophic_iteration_failure_returns_error(self, monkeypatch):
        # Failure outside the per-entry guard (the entries iterable itself
        # raises) hits the outer safety net and returns the error dict.
        class ExplodingList:
            name = "Boom"

            @property
            def entries(self):
                raise RuntimeError("entries unavailable")

        monkeypatch.setattr(obslist, "formats_read_file", lambda path: ExplodingList())

        result = obslist.read_list(catalogs=None, name="Boom.skylist")

        assert result["result"] == "error"
        assert result["catalog_objects"] == []
        assert "entries unavailable" in result["message"]
