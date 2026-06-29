"""
Roundtrip tests for obslist_formats.

Each format is tested by creating an ObsList, writing it to a string,
reading it back, and verifying the entries match.
"""

import pytest
from PiFinder.calc_utils import (
    ra_to_hms_exact,
    dec_to_dms_exact,
    ra_to_deg,
    dms_to_dec,
)
from PiFinder.composite_object import MagnitudeObject, SizeObject
from PiFinder.obslist_formats import (
    ObsList,
    ObsListEntry,
    PiFinderFormatError,
    detect_format,
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
    read_pifinder,
    write_pifinder,
)


def _sample_entries():
    return [
        ObsListEntry(
            name="NGC 224",
            ra=10.6847,
            dec=41.2689,
            obj_type="Gx",
            mag=MagnitudeObject([3.4]),
            catalog_code="NGC",
            sequence=224,
            description="Andromeda Galaxy",
        ),
        ObsListEntry(
            name="M 42",
            ra=83.8221,
            dec=-5.3911,
            obj_type="Nb",
            mag=MagnitudeObject([4.0]),
            catalog_code="M",
            sequence=42,
        ),
        ObsListEntry(
            name="NGC 7789",
            ra=359.33,
            dec=56.726,
            obj_type="OC",
            mag=MagnitudeObject([6.7]),
            catalog_code="NGC",
            sequence=7789,
        ),
    ]


def _sample_list():
    return ObsList(name="Test List", entries=_sample_entries())


def _assert_entries_close(
    original, parsed, check_type=True, check_mag=True, ra_tol=0.1, dec_tol=0.05
):
    """Verify parsed entries match originals within tolerance."""
    assert len(parsed) == len(original)
    for orig, got in zip(original, parsed):
        assert got.name == orig.name
        if orig.ra > 0 or orig.dec != 0:
            assert got.ra == pytest.approx(orig.ra, abs=ra_tol)
            assert got.dec == pytest.approx(orig.dec, abs=dec_tol)
        if check_type:
            assert got.obj_type == orig.obj_type
        if check_mag and orig.mag.filter_mag != MagnitudeObject.UNKNOWN_MAG:
            assert got.mag.filter_mag == pytest.approx(orig.mag.filter_mag, abs=0.15)
        assert got.catalog_code == orig.catalog_code
        assert got.sequence == orig.sequence


# ── Coordinate helper tests ─────────────────────────────────────────────


@pytest.mark.unit
class TestCoordinateHelpers:
    def test_ra_roundtrip(self):
        for ra in [0.0, 45.0, 90.0, 180.0, 270.0, 359.99]:
            h, m, s = ra_to_hms_exact(ra)
            assert ra_to_deg(h, m, s) == pytest.approx(ra, abs=0.01)

    def test_dec_roundtrip(self):
        for dec in [-89.5, -45.0, -0.5, 0.0, 41.27, 89.99]:
            sign, d, m, s = dec_to_dms_exact(dec)
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
def test_csv_import_decimal_degrees_lowercase_headers():
    # A typical third-party export: lowercase headers, decimal-degree coords.
    text = (
        "name,ra,dec,mag\n"
        "mess003,205.8583333,28.2441667,6.3\n"
        "mess013,250.6666667,36.4111111,5.8\n"
        "mess092,259.4916667,43.1088889,6.5\n"
    )
    parsed = read_csv(text)
    assert [e.name for e in parsed.entries] == ["mess003", "mess013", "mess092"]
    assert [round(e.ra, 2) for e in parsed.entries] == [205.86, 250.67, 259.49]
    assert [round(e.dec, 2) for e in parsed.entries] == [28.24, 36.41, 43.11]
    assert parsed.entries[0].mag.filter_mag == pytest.approx(6.3)


@pytest.mark.unit
def test_csv_import_header_aliases():
    text = "Name,RA_deg,DEC,VMag,Obj_Type\nComet X,12.5,-3.0,9.1,Cm\n"
    entry = read_csv(text).entries[0]
    assert entry.name == "Comet X"
    assert entry.ra == pytest.approx(12.5)
    assert entry.dec == pytest.approx(-3.0)
    assert entry.mag.filter_mag == pytest.approx(9.1)
    assert entry.obj_type == "Cm"


@pytest.mark.unit
def test_csv_import_colon_coordinates():
    text = "Name,RA,Dec\nNGC 224,00:42:44,+41:16:09\n"
    entry = read_csv(text).entries[0]
    assert entry.ra == pytest.approx(10.68, abs=0.05)
    assert entry.dec == pytest.approx(41.27, abs=0.05)


@pytest.mark.unit
def test_csv_import_ra_hours_header():
    # An `ra_h` header declares RA in hours; a bare decimal is scaled by 15.
    text = "Name,RA_h,Dec\nM 3,13.7239,28.2442\n"
    entry = read_csv(text).entries[0]
    assert entry.ra == pytest.approx(205.86, abs=0.05)
    assert entry.dec == pytest.approx(28.24, abs=0.05)


@pytest.mark.unit
def test_csv_import_ra_hours_header_ignores_sexagesimal():
    # The hours hint only scales bare decimals, never an already-HMS value.
    text = "Name,RA_hours,Dec\nNGC 224,00:42:44,+41:16:09\n"
    entry = read_csv(text).entries[0]
    assert entry.ra == pytest.approx(10.68, abs=0.05)


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
        obs.entries,
        parsed.entries,
        ra_tol=0.02,
        dec_tol=0.01,
        check_type=False,
        check_mag=False,
    )


@pytest.mark.unit
def test_pifinder_roundtrip():
    obs = _sample_list()
    text = write_pifinder(obs)
    parsed = read_pifinder(text)
    assert parsed.name == "Test List"
    # Catalog-keyed entries carry only catalog_code/sequence through the
    # native format; coordinates are restored at resolution time.
    assert len(parsed.entries) == 3
    for orig, got in zip(obs.entries, parsed.entries):
        assert got.catalog_code == orig.catalog_code
        assert got.sequence == orig.sequence
        assert got.description == orig.description


@pytest.mark.unit
def test_pifinder_coordinate_entry_roundtrip():
    obs = ObsList(
        name="Custom",
        entries=[
            ObsListEntry(
                name="My Nova",
                ra=123.456,
                dec=-12.345,
                obj_type="Nova",
                mag=MagnitudeObject([8.2]),
                description="discovered last night",
            )
        ],
    )
    text = write_pifinder(obs)
    parsed = read_pifinder(text)
    _assert_entries_close(obs.entries, parsed.entries, ra_tol=0.001, dec_tol=0.001)
    assert parsed.entries[0].description == "discovered last night"


@pytest.mark.unit
def test_pifinder_extents_roundtrip():
    # The native writer must emit size/extent geometry so a round trip is
    # lossless for everything PiFinder holds.
    obs = ObsList(
        name="Extents",
        entries=[
            ObsListEntry(
                name="Ellipse",
                ra=10.0,
                dec=20.0,
                obj_type="Gx",
                size=SizeObject([180.0, 60.0], position_angle=45.0),
            ),
            ObsListEntry(
                name="Asterism",
                ra=30.0,
                dec=40.0,
                obj_type="Ast",
                size=SizeObject(
                    [[30.0, 40.0], [30.1, 40.1], [30.2, 39.9]],
                    geometry="polyline",
                ),
            ),
        ],
    )
    parsed = read_pifinder(write_pifinder(obs)).entries
    assert parsed[0].size.extents == [180.0, 60.0]
    assert parsed[0].size.position_angle == 45.0
    assert parsed[1].size.geometry == "polyline"
    assert parsed[1].size.extents == [[30.0, 40.0], [30.1, 40.1], [30.2, 39.9]]


@pytest.mark.unit
def test_pifinder_writer_infers_geometry_for_nested_shape():
    # A nested RA/Dec shape with no explicit geometry must still write a valid
    # file: the reader rejects nested shapes that lack 'geometry'.
    obs = ObsList(
        name="Inferred",
        entries=[
            ObsListEntry(
                name="Line",
                ra=10.0,
                dec=20.0,
                obj_type="?",
                size=SizeObject([[10.0, 20.0], [10.5, 20.5]]),  # geometry=""
            )
        ],
    )
    text = write_pifinder(obs)
    assert '"geometry": "polyline"' in text
    parsed = read_pifinder(text).entries  # must not raise
    assert parsed[0].size.extents == [[10.0, 20.0], [10.5, 20.5]]


@pytest.mark.unit
def test_pifinder_writer_file_epoch_with_overrides():
    # The file declares one epoch (always present); an entry only carries its own
    # epoch when it overrides the file default -- no per-entry repetition.
    obs = ObsList(
        name="x",
        entries=[
            ObsListEntry(name="a", ra=1.0, dec=2.0, obj_type="*"),  # inherits J2000
            ObsListEntry(
                name="b", ra=3.0, dec=4.0, obj_type="*", epoch="J2016.0"
            ),  # override
        ],
    )
    text = write_pifinder(obs)
    assert text.count('"epoch"') == 2  # one file-level + one override, not three
    assert '"epoch": "J2000"' in text  # file-level default
    assert '"epoch": "J2016.0"' in text  # override on entry b only


@pytest.mark.unit
def test_pifinder_file_epoch_applies_to_entries():
    # An entry with no epoch of its own inherits the file-level epoch on read.
    data = (
        '{"version": 1, "name": "x", "epoch": "J2016.0", '
        '"objects": [{"name": "t", "obj_type": "?", "ra": 10.0, "dec": 20.0}]}'
    )
    entry = read_pifinder(data).entries[0]
    # J2016 file epoch applied -> precessed to J2000 (RA moved ~0.2 deg).
    assert entry.ra != 10.0
    assert entry.ra == pytest.approx(10.0, abs=0.5)


@pytest.mark.unit
def test_pifinder_epoch_precession():
    import json

    data = {
        "version": 1,
        "name": "Epoch test",
        "objects": [
            {
                "name": "Target",
                "obj_type": "?",
                "ra": 10.0,
                "dec": 20.0,
                "epoch": "J2016.0",
            }
        ],
    }
    parsed = read_pifinder(json.dumps(data))
    entry = parsed.entries[0]
    # J2016 coordinates must be precessed to J2000 — moved, but only by
    # roughly 16 years of precession (~0.2 deg in RA).
    assert entry.ra != 10.0
    assert entry.ra == pytest.approx(10.0, abs=0.5)
    assert entry.dec == pytest.approx(20.0, abs=0.5)


@pytest.mark.unit
class TestPiFinderValidation:
    def test_missing_top_level_field(self):
        with pytest.raises(PiFinderFormatError, match="objects"):
            read_pifinder('{"version": 1, "name": "x"}')

    def test_unsupported_version(self):
        with pytest.raises(PiFinderFormatError, match="version"):
            read_pifinder('{"version": 99, "name": "x", "objects": []}')

    def test_catalog_entry_missing_sequence(self):
        with pytest.raises(PiFinderFormatError, match="sequence"):
            read_pifinder(
                '{"version": 1, "name": "x", "objects": [{"catalog_code": "M"}]}'
            )

    def test_custom_entry_missing_coords(self):
        with pytest.raises(PiFinderFormatError, match="ra"):
            read_pifinder(
                '{"version": 1, "name": "x",'
                ' "objects": [{"name": "n", "obj_type": "?", "dec": 1.0}]}'
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
        assert detect_format("", "mylist.pifinder") == "pifinder"

    def test_by_content_pifinder(self):
        assert detect_format('{"version": 1, "objects": []}') == "pifinder"

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

    def test_by_content_csv_lowercase(self):
        assert detect_format("name,ra,dec,mag\nM 3,205.8,28.2,6.3\n") == "csv"

    def test_by_content_csv_without_extension(self):
        # A mis-named CSV is still detected by its header row.
        assert detect_format("Name,RA,Dec\nNGC 224,10.7,41.3\n", "list.txt") == "csv"

    def test_by_content_text_fallback(self):
        assert detect_format("NGC 224\nM 42\n") == "text"
