"""
Roundtrip tests for obslist_formats.

Each format is tested by creating an ObsList, writing it to a string,
reading it back, and verifying the entries match.
"""

import pytest
from PiFinder.obslist_formats import (
    ObsList,
    ObsListEntry,
    detect_format,
    ra_to_hms,
    dec_to_dms,
    hms_to_ra,
    dms_to_dec,
    read_skylist,
    write_skylist,
    read_csv,
    write_csv,
    read_text,
    write_text,
    read_stellarium,
    write_stellarium,
    read_autostar,
    write_autostar,
    read_argo,
    write_argo,
    read_nextour,
    write_nextour,
    read_eqmod,
    write_eqmod,
)


def _sample_entries():
    return [
        ObsListEntry(
            name="NGC 224",
            ra=10.6847,
            dec=41.2689,
            obj_type="Gx",
            mag=3.4,
            catalog_code="NGC",
            sequence=224,
            description="Andromeda Galaxy",
        ),
        ObsListEntry(
            name="M 42",
            ra=83.8221,
            dec=-5.3911,
            obj_type="Nb",
            mag=4.0,
            catalog_code="M",
            sequence=42,
        ),
        ObsListEntry(
            name="NGC 7789",
            ra=359.33,
            dec=56.726,
            obj_type="OC",
            mag=6.7,
            catalog_code="NGC",
            sequence=7789,
        ),
    ]


def _sample_list():
    return ObsList(name="Test List", entries=_sample_entries())


def _assert_entries_close(original, parsed, check_type=True, check_mag=True, ra_tol=0.1, dec_tol=0.05):
    """Verify parsed entries match originals within tolerance."""
    assert len(parsed) == len(original)
    for orig, got in zip(original, parsed):
        assert got.name == orig.name
        if orig.ra > 0 or orig.dec != 0:
            assert got.ra == pytest.approx(orig.ra, abs=ra_tol)
            assert got.dec == pytest.approx(orig.dec, abs=dec_tol)
        if check_type:
            assert got.obj_type == orig.obj_type
        if check_mag and orig.mag is not None:
            assert got.mag == pytest.approx(orig.mag, abs=0.15)
        assert got.catalog_code == orig.catalog_code
        assert got.sequence == orig.sequence


# ── Coordinate helper tests ─────────────────────────────────────────────


@pytest.mark.unit
class TestCoordinateHelpers:
    def test_ra_roundtrip(self):
        for ra in [0.0, 45.0, 90.0, 180.0, 270.0, 359.99]:
            h, m, s = ra_to_hms(ra)
            assert hms_to_ra(h, m, s) == pytest.approx(ra, abs=0.01)

    def test_dec_roundtrip(self):
        for dec in [-89.5, -45.0, 0.0, 41.27, 89.99]:
            sign, d, m, s = dec_to_dms(dec)
            assert dms_to_dec(sign, d, m, s) == pytest.approx(dec, abs=0.01)


# ── Format roundtrip tests ──────────────────────────────────────────────


@pytest.mark.unit
def test_skylist_roundtrip():
    obs = _sample_list()
    text = write_skylist(obs)
    assert "SkySafariObservingListVersion" in text
    parsed = read_skylist(text)
    assert len(parsed.entries) == 3
    for orig, got in zip(obs.entries, parsed.entries):
        assert got.catalog_code == orig.catalog_code
        assert got.sequence == orig.sequence
        if orig.ra:
            assert got.ra == pytest.approx(orig.ra, abs=0.1)
        if orig.dec:
            assert got.dec == pytest.approx(orig.dec, abs=0.05)
        if orig.description:
            assert got.description == orig.description


@pytest.mark.unit
def test_csv_roundtrip():
    obs = _sample_list()
    text = write_csv(obs)
    parsed = read_csv(text)
    _assert_entries_close(obs.entries, parsed.entries, ra_tol=0.15, dec_tol=0.15)


@pytest.mark.unit
def test_text_roundtrip():
    obs = _sample_list()
    text = write_text(obs)
    parsed = read_text(text)
    assert len(parsed.entries) == 3
    for orig, got in zip(obs.entries, parsed.entries):
        assert got.name == orig.name
        assert got.catalog_code == orig.catalog_code
        assert got.sequence == orig.sequence


@pytest.mark.unit
def test_stellarium_roundtrip():
    obs = _sample_list()
    text = write_stellarium(obs)
    parsed = read_stellarium(text)
    assert parsed.name == "Test List"
    _assert_entries_close(obs.entries, parsed.entries, ra_tol=0.15, dec_tol=0.15)


@pytest.mark.unit
def test_autostar_roundtrip():
    obs = _sample_list()
    text = write_autostar(obs)
    parsed = read_autostar(text)
    assert parsed.name == "Test List"
    # Autostar rounds coordinates to whole seconds
    _assert_entries_close(
        obs.entries, parsed.entries, ra_tol=0.5, dec_tol=0.5, check_type=True
    )


@pytest.mark.unit
def test_argo_roundtrip():
    obs = _sample_list()
    text = write_argo(obs)
    parsed = read_argo(text)
    # Argo rounds to whole seconds, type map loses some info
    _assert_entries_close(obs.entries, parsed.entries, ra_tol=0.5, dec_tol=0.5)


@pytest.mark.unit
def test_nextour_roundtrip():
    obs = _sample_list()
    text = write_nextour(obs)
    parsed = read_nextour(text)
    # NexTour stores fractional minutes, moderate precision
    _assert_entries_close(
        obs.entries, parsed.entries, ra_tol=0.5, dec_tol=0.5, check_type=False
    )


@pytest.mark.unit
def test_eqmod_roundtrip():
    obs = _sample_list()
    text = write_eqmod(obs)
    parsed = read_eqmod(text)
    assert parsed.name == "Test List"
    # EQMOD stores 4 decimal places, good precision
    _assert_entries_close(
        obs.entries, parsed.entries, ra_tol=0.02, dec_tol=0.01, check_type=False, check_mag=False
    )


# ── Format detection tests ──────────────────────────────────────────────


@pytest.mark.unit
class TestDetectFormat:
    def test_by_extension(self):
        assert detect_format("", "mylist.skylist") == "skylist"
        assert detect_format("", "mylist.sol") == "stellarium"
        assert detect_format("", "mylist.hct") == "nextour"
        assert detect_format("", "mylist.lst") == "eqmod"
        assert detect_format("", "mylist.csv") == "csv"

    def test_by_content_skylist(self):
        assert detect_format("SkySafariObservingListVersion=3.0\n") == "skylist"

    def test_by_content_stellarium(self):
        assert detect_format('{"version": "1.0"}') == "stellarium"

    def test_by_content_eqmod(self):
        assert detect_format("!J2000\n1.234; 45.678; NGC 224\n") == "eqmod"

    def test_by_content_argo(self):
        assert detect_format("NGC 224|00:42:44|+41:16:09|GALAXY|3.4|\n") == "argo"

    def test_by_content_autostar(self):
        text = '/ comment\nTITLE "Test"\nUSER 00:42:44 41d16m09s "NGC 224" "Gx"\n'
        assert detect_format(text) == "autostar"

    def test_by_content_csv(self):
        assert detect_format("Name,RA,Dec,Magnitude\n") == "csv"

    def test_by_content_text_fallback(self):
        assert detect_format("NGC 224\nM 42\n") == "text"
