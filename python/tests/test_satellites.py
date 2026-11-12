"""Satellite element parsing, positions, magnitudes, passes and catalog."""

import datetime
import json
from pathlib import Path

import numpy as np
import pytest

import PiFinder.satellites as satellites
import PiFinder.satellite_catalog as satellite_catalog
import PiFinder.web_satellites as web_satellites
from PiFinder.catalog_base import CatalogState
from PiFinder.state import Location

DATA = Path(__file__).parent / "data" / "satellites"
ISS_NORAD = 25544
ISS_FORMATS = ("tle", "3le", "2le", "json", "csv", "xml", "kvn")


def iss_elements() -> satellites.SatElements:
    results, _errors = satellites.parse_elements((DATA / "25544.3le").read_text())
    return results[0]


# One day after the epoch of the fixture element set.
NOW = iss_elements().epoch + datetime.timedelta(days=1)
BRUSSELS = satellites.observer_topos(50.85, 4.35, 50.0)


@pytest.mark.unit
@pytest.mark.parametrize("suffix", ISS_FORMATS)
def test_every_format_gives_the_same_iss_elements(suffix):
    results, errors = satellites.parse_elements((DATA / f"25544.{suffix}").read_text())
    assert errors == []
    assert len(results) == 1
    element = results[0]
    assert element.norad_id == ISS_NORAD
    reference = iss_elements()
    assert abs((element.epoch - reference.epoch).total_seconds()) < 1e-3
    sat = satellites.TrackedSatellite.from_elements(element)
    ref_sat = satellites.TrackedSatellite.from_elements(reference)
    ra, dec = satellites.radec_at(sat, BRUSSELS, NOW)
    ref_ra, ref_dec = satellites.radec_at(ref_sat, BRUSSELS, NOW)
    assert ra == pytest.approx(ref_ra, abs=1e-3)
    assert dec == pytest.approx(ref_dec, abs=1e-3)


@pytest.mark.unit
def test_name_line_is_used_and_zero_prefix_is_removed():
    lines = (DATA / "25544.2le").read_text().strip().splitlines()
    text = "0 MY STATION\n" + "\n".join(lines)
    results, _errors = satellites.parse_elements(text)
    assert results[0].name == "MY STATION"
    no_name, _errors = satellites.parse_elements("\n".join(lines))
    assert no_name[0].name == f"NORAD {ISS_NORAD}"


@pytest.mark.unit
def test_many_sets_and_bad_checksum_are_reported_per_set():
    text = (DATA / "visual.tle").read_text()
    good, errors = satellites.parse_elements(text, "celestrak")
    assert len(good) == len(text.strip().splitlines()) // 3
    assert errors == []

    element = iss_elements()
    broken_digit = "1" if element.line2[68] != "1" else "2"
    broken = element.line2[:68] + broken_digit
    results, errors = satellites.parse_elements(
        f"BROKEN\n{element.line1}\n{broken}\n" + element.to_tle()
    )
    assert [r.name for r in results] == ["ISS (ZARYA)"]
    assert len(errors) == 1 and "checksum" in errors[0]


@pytest.mark.unit
def test_empty_or_unreadable_text_raises():
    with pytest.raises(satellites.ElementParseError):
        satellites.parse_elements("   ")
    with pytest.raises(satellites.ElementParseError):
        satellites.parse_elements("just some words")
    with pytest.raises(satellites.ElementParseError):
        satellites.parse_elements("{not json")


@pytest.mark.unit
def test_alpha5_catalog_numbers():
    assert satellites._alpha5_to_int("25544") == 25544
    assert satellites._alpha5_to_int("A0001") == 100001
    assert satellites._alpha5_to_int("Z9999") == 339999


@pytest.mark.unit
def test_standard_magnitude_is_the_value_at_1000_km_and_90_degrees():
    assert satellites.apparent_magnitude(2.0, 1000.0, 90.0) == pytest.approx(2.0)
    # Twice the distance is 1.5 mag fainter; a fuller phase is brighter.
    assert satellites.apparent_magnitude(2.0, 2000.0, 90.0) == pytest.approx(
        3.505, abs=1e-3
    )
    assert satellites.apparent_magnitude(2.0, 1000.0, 30.0) < 2.0
    assert satellites.apparent_magnitude(2.0, 1000.0, 150.0) > 2.0


@pytest.mark.unit
def test_magnitude_table_has_the_iss():
    assert satellites.std_magnitude(ISS_NORAD) == pytest.approx(-1.3)
    assert satellites.std_magnitude(999999999) == satellites.DEFAULT_STD_MAG


@pytest.mark.unit
def test_cylindrical_shadow():
    sun = np.array([1.5e8, 0.0, 0.0])
    assert satellites.in_sunlight(np.array([7000.0, 0.0, 0.0]), sun)
    assert not satellites.in_sunlight(np.array([-7000.0, 0.0, 0.0]), sun)
    assert satellites.in_sunlight(np.array([-7000.0, 7000.0, 0.0]), sun)
    many = np.array([[7000.0, -7000.0], [0.0, 0.0], [0.0, 0.0]])
    assert list(satellites.in_sunlight(many, sun)) == [True, False]


@pytest.mark.unit
def test_look_gives_consistent_geometry_and_rates():
    sat = satellites.TrackedSatellite.from_elements(iss_elements())
    now = satellites.look(sat, BRUSSELS, NOW)
    later = satellites.look(sat, BRUSSELS, NOW + datetime.timedelta(seconds=1))
    assert -90 <= now.alt <= 90 and 0 <= now.az < 360
    # The ISS orbits about 420 km up: its range is never below that.
    assert now.range_km > 380
    ra_step = (later.ra - now.ra + 540) % 360 - 180
    assert now.ra_rate == pytest.approx(ra_step, abs=1e-3)
    assert now.dec_rate == pytest.approx(later.dec - now.dec, abs=1e-3)
    assert (now.mag is None) == (not now.sunlit)


@pytest.mark.unit
def test_passes_rise_culminate_and_set_in_order():
    sat = satellites.TrackedSatellite.from_elements(iss_elements())
    passes = satellites.find_passes(sat, BRUSSELS, NOW, hours=48)
    # The ISS passes over Brussels several times a day.
    assert len(passes) >= 4
    for item in passes:
        assert item.rise <= item.culmination <= item.set
        assert item.max_alt >= 10.0
        assert (item.set - item.rise).total_seconds() < 15 * 60
        if item.visible:
            assert item.rise <= item.visible_start <= item.visible_end <= item.set
            assert item.min_mag is not None
            # A visible pass needs a dark sky at the start of the visible part.
            sun = satellites.sun_context(BRUSSELS, item.visible_start)
            assert sun.sun_alt < satellites.DARK_SUN_ALT_DEG
    first = passes[0].to_dict()
    json.dumps(first)
    assert set(first) >= {"rise", "max_alt", "visible", "min_mag"}


@pytest.mark.unit
def test_user_elements_are_saved_replaced_and_deleted(tmp_path):
    element = iss_elements()
    satellites.save_user_elements([element], tmp_path)
    renamed = satellites.SatElements(
        "STATION", element.norad_id, element.line1, element.line2
    )
    satellites.save_user_elements([renamed], tmp_path)
    stored = satellites.load_user_elements(tmp_path)
    assert [(e.name, e.source) for e in stored] == [("STATION", "user")]
    assert satellites.delete_user_element(ISS_NORAD, tmp_path)
    assert not satellites.delete_user_element(ISS_NORAD, tmp_path)
    assert satellites.load_user_elements(tmp_path) == []


@pytest.mark.unit
def test_all_elements_merge_groups_and_drop_old_sets(tmp_path):
    (tmp_path / "visual.tle").write_text((DATA / "visual.tle").read_text())
    (tmp_path / "stations.tle").write_text((DATA / "25544.3le").read_text())
    group_count = len(satellites.read_tle_file(tmp_path / "visual.tle", "celestrak"))
    merged = satellites.load_all_elements(NOW, tmp_path)
    ids = [e.norad_id for e in merged]
    assert len(ids) == len(set(ids))
    assert ISS_NORAD in ids
    assert len(merged) >= group_count
    far_future = NOW + datetime.timedelta(days=satellites.MAX_ELEMENT_AGE_DAYS + 5)
    assert satellites.load_all_elements(far_future, tmp_path) == []


@pytest.mark.unit
def test_an_older_user_set_does_not_replace_a_newer_download(tmp_path):
    element = iss_elements()
    (tmp_path / "stations.tle").write_text(element.to_tle())
    line1 = element.line1[:18] + "26300.50000000" + element.line1[32:68]
    line1 += str(satellites.tle_checksum(line1))
    old = satellites.parse_elements(f"OLD ISS\n{line1}\n{element.line2}\n")
    assert old[1] == [], old[1]
    satellites.save_user_elements(old[0], tmp_path)
    merged = {e.norad_id: e for e in satellites.load_all_elements(NOW, tmp_path)}
    assert merged[ISS_NORAD].source == "celestrak"


@pytest.mark.unit
def test_group_download_is_needed_only_when_old(tmp_path):
    now = datetime.datetime.now(datetime.timezone.utc)
    assert satellites.group_download_needed("visual", now, tmp_path)[0]
    (tmp_path / "visual.tle").write_text("x")
    assert not satellites.group_download_needed("visual", now, tmp_path)[0]
    later = now + datetime.timedelta(hours=satellites.DOWNLOAD_INTERVAL_HOURS + 1)
    assert satellites.group_download_needed("visual", later, tmp_path)[0]


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


class FixedSharedState:
    def __init__(self, dt):
        self.dt = dt
        self._location = Location(
            lat=50.85, lon=4.35, altitude=50.0, lock=True, timezone="Europe/Brussels"
        )

    def altaz_ready(self):
        return True

    def datetime(self):
        return self.dt

    def location(self):
        return self._location


@pytest.fixture
def catalog(tmp_path):
    (tmp_path / "visual.tle").write_text((DATA / "visual.tle").read_text())
    (tmp_path / "stations.tle").write_text((DATA / "25544.3le").read_text())
    shared_state = FixedSharedState(NOW)
    cat = satellite_catalog.SatelliteCatalog(
        NOW, shared_state, data_directory=tmp_path, start_threads=False
    )
    cat._start_pass_update = lambda dt: cat._update_passes(dt)
    cat.do_timed_task()
    return cat


@pytest.mark.unit
def test_catalog_builds_objects_with_norad_sequences(catalog):
    assert catalog.initialized
    assert catalog.get_status().current == CatalogState.READY
    iss = catalog.get_object_by_sequence(ISS_NORAD)
    assert iss is not None
    assert iss.obj_type == "Sat"
    assert iss.catalog_code == "SA"
    assert iss.names == ["ISS (ZARYA)"]
    assert "NORAD 25544" in iss.description
    assert iss.mag.filter_mag < 5


@pytest.mark.unit
def test_catalog_updates_objects_in_place(catalog):
    iss = catalog.get_object_by_sequence(ISS_NORAD)
    first = (iss.ra, iss.dec)
    catalog.shared_state.dt = NOW + datetime.timedelta(minutes=5)
    catalog.do_timed_task()
    assert catalog.get_object_by_sequence(ISS_NORAD) is iss
    assert (iss.ra, iss.dec) != first


@pytest.mark.unit
def test_live_radec_follows_the_satellite(catalog):
    iss = catalog.get_object_by_sequence(ISS_NORAD)
    later = NOW + datetime.timedelta(seconds=30)
    ra, dec = satellite_catalog.live_radec(iss, later)
    sat = catalog.tracked(ISS_NORAD)
    assert (ra, dec) == pytest.approx(satellites.radec_at(sat, BRUSSELS, later))
    assert satellite_catalog.live_radec(object(), later) is None


@pytest.mark.unit
def test_catalog_writes_the_pass_cache_for_the_web_page(catalog):
    cache = satellites.read_pass_cache(catalog.data_directory)
    assert cache is not None
    assert any(s["norad_id"] == ISS_NORAD for s in cache["satellites"])
    rises = [row["rise"] for row in cache["passes"]]
    assert rises == sorted(rises)
    rows, _cache = web_satellites.upcoming_passes(NOW, False, catalog.data_directory)
    assert rows and {"rise_local", "rise_dir"} <= set(rows[0])
    iss = catalog.get_object_by_sequence(ISS_NORAD)
    assert iss.next_pass_ts is None or iss.next_pass_ts > 0


@pytest.mark.unit
def test_web_entry_is_picked_up_by_the_catalog(catalog):
    found, errors = web_satellites.add_elements(
        "", name="", norad="", directory=catalog.data_directory
    )
    assert found == [] and errors == []
    record = json.loads((DATA / "25544.json").read_text())[0]
    record["NORAD_CAT_ID"] = 99901
    record["OBJECT_NAME"] = "TEST SAT"
    found, errors = web_satellites.add_elements(
        json.dumps(record), name="My test", directory=catalog.data_directory
    )
    assert errors == [] and [e.name for e in found] == ["My test"]
    catalog.do_timed_task()
    obj = catalog.get_object_by_sequence(99901)
    assert obj is not None and obj.names == ["My test"]
    assert "web entry" in obj.description


@pytest.mark.unit
def test_satellite_detail_for_the_web_page(catalog):
    detail = web_satellites.satellite_detail(
        ISS_NORAD,
        NOW,
        catalog.shared_state.location(),
        days=1.0,
        directory=catalog.data_directory,
    )
    assert detail["name"] == "ISS (ZARYA)"
    assert detail["now"]["range_km"] > 380
    assert detail["now"]["rate_arcmin_s"] > 0
    assert detail["passes"]


@pytest.mark.unit
def test_user_standard_magnitude_replaces_the_table(catalog):
    found, errors = web_satellites.add_elements(
        (DATA / "25544.3le").read_text(),
        std_mag="0.5",
        directory=catalog.data_directory,
    )
    assert errors == [] and found
    catalog.do_timed_task()
    assert catalog.tracked(ISS_NORAD).std_mag == pytest.approx(0.5)
    satellites.save_user_mag(ISS_NORAD, None, catalog.data_directory)
    catalog.do_timed_task()
    assert catalog.tracked(ISS_NORAD).std_mag == pytest.approx(-1.3)


@pytest.mark.unit
def test_bright_pass_filter(catalog):
    every, _cache = web_satellites.upcoming_passes(NOW, True, catalog.data_directory)
    bright, _cache = web_satellites.upcoming_passes(
        NOW, True, catalog.data_directory, max_mag=3.0
    )
    assert len(bright) <= len(every)
    assert all(row["min_mag"] <= 3.0 for row in bright)
