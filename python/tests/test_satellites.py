"""Satellite element parsing, positions, magnitudes, passes and catalog."""

import datetime
import json
from pathlib import Path

import numpy as np
import pytest
from sgp4 import exporter
from sgp4.api import WGS72, Satrec
from skyfield.api import wgs84

import PiFinder.satellites as satellites
import PiFinder.satellite_catalog as satellite_catalog
import PiFinder.web_satellites as web_satellites
from PiFinder.calc_utils import sf_utils
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


# ---------------------------------------------------------------------------
# Pass search against Skyfield's find_events
# ---------------------------------------------------------------------------

# A geostationary satellite. Its inclination is 0.85 degrees.
GEO_TLE = """ASTRA 1KR
1 29055U 06012A   26316.93979443  .00000130  00000+0  00000+0 0  9998
2 29055   0.8523  82.1538 0003456 151.0788 176.1913  1.00270139 47187
"""


def reference_passes(sat, topos, start, hours, min_alt=10.0):
    """Passes from Skyfield's find_events, with rise, culmination and set
    only. A pass that is in progress at the start or the end of the window
    is left out."""
    ts = sf_utils.ts
    t0 = ts.from_datetime(start)
    t1 = ts.from_datetime(start + datetime.timedelta(hours=hours))
    times, events = sat.satellite.find_events(topos, t0, t1, altitude_degrees=min_alt)
    difference = sat.satellite - topos
    passes = []
    rise = culmination = None
    for t, event in zip(times, events):
        if event == 0:
            rise, culmination = t, None
        elif event == 1 and rise is not None:
            culmination = t
        elif event == 2 and rise is not None and culmination is not None:
            alt = difference.at(culmination).altaz()[0].degrees
            passes.append(
                (
                    rise.utc_datetime(),
                    culmination.utc_datetime(),
                    t.utc_datetime(),
                    float(alt),
                )
            )
            rise = culmination = None
    return passes


@pytest.mark.unit
def test_pass_search_agrees_with_find_events():
    sats = visual_satellites() + [
        satellites.TrackedSatellite.from_elements(iss_elements())
    ]
    found = satellites.find_passes_many(sats, BRUSSELS, NOW, hours=24)
    total = 0
    for sat, passes in zip(sats, found):
        inside = [
            item
            for item in passes
            if item.rise > NOW and item.set < NOW + datetime.timedelta(hours=24)
        ]
        expected = reference_passes(sat, BRUSSELS, NOW, 24)
        assert len(inside) == len(expected), sat.name
        for item, (rise, culmination, set_time, max_alt) in zip(inside, expected):
            assert abs((item.rise - rise).total_seconds()) < 3, sat.name
            assert abs((item.set - set_time).total_seconds()) < 3, sat.name
            assert abs((item.culmination - culmination).total_seconds()) < 3
            assert item.max_alt == pytest.approx(max_alt, abs=0.1)
        total += len(inside)
    assert total > 30


@pytest.mark.unit
def test_one_satellite_search_is_the_many_satellite_search():
    sats = visual_satellites()[:4]
    many = satellites.find_passes_many(sats, BRUSSELS, NOW, hours=12)
    for sat, passes in zip(sats, many):
        # The grid of a chunk has the smallest step of its satellites, so the
        # times differ a little.
        alone = satellites.find_passes(sat, BRUSSELS, NOW, hours=12)
        assert len(alone) == len(passes)
        for one, other in zip(alone, passes):
            for key in ("rise", "culmination", "set"):
                gap = getattr(one, key) - getattr(other, key)
                assert abs(gap.total_seconds()) < 1
            assert one.max_alt == pytest.approx(other.max_alt, abs=0.02)
            assert one.visible == other.visible


@pytest.mark.unit
def test_pass_visibility_follows_the_sun_and_the_shadow():
    sat = satellites.TrackedSatellite.from_elements(iss_elements())
    passes = satellites.find_passes(sat, BRUSSELS, NOW, hours=48)
    assert any(item.visible for item in passes)
    for item in passes:
        if not item.visible:
            continue
        for moment in (item.visible_start, item.visible_end):
            look = satellites.look(sat, BRUSSELS, moment, with_rates=False)
            # The samples are 10 s apart; the look is at a sample time.
            assert look.visible
            # min_mag is the brightest magnitude of the visible part.
            assert look.mag >= item.min_mag - 0.01


@pytest.mark.unit
def test_geostationary_satellite_has_one_pass_for_the_full_window():
    results, _errors = satellites.parse_elements(GEO_TLE)
    sat = satellites.TrackedSatellite.from_elements(results[0])
    below = wgs84.subpoint_of(sat.satellite.at(sf_utils.ts.from_datetime(NOW)))
    topos = satellites.observer_topos(45.0, below.longitude.degrees, 0.0)
    passes = satellites.find_passes(sat, topos, NOW, hours=24)
    assert len(passes) == 1
    item = passes[0]
    assert item.rise == NOW
    assert item.set == NOW + datetime.timedelta(hours=24)
    assert NOW <= item.culmination <= item.set
    highest = max(
        satellites.look(sat, topos, NOW + datetime.timedelta(minutes=m)).alt
        for m in range(0, 24 * 60 + 1, 10)
    )
    assert 30 < item.max_alt == pytest.approx(highest, abs=0.05)


@pytest.mark.unit
def test_passes_in_progress_at_the_start_and_at_the_end_of_the_window():
    sat = satellites.TrackedSatellite.from_elements(iss_elements())
    first = satellites.find_passes(sat, BRUSSELS, NOW, hours=24)[0]
    # The window starts after the culmination and ends before the next one.
    start = first.culmination + datetime.timedelta(seconds=60)
    following = satellites.find_passes(sat, BRUSSELS, start, hours=24)[1]
    hours = (following.culmination - start).total_seconds() / 3600.0 - 0.01
    end = start + datetime.timedelta(hours=hours)
    passes = satellites.find_passes(sat, BRUSSELS, start, hours=hours)

    head, tail = passes[0], passes[-1]
    assert head.rise == head.culmination == start
    assert abs((head.set - first.set).total_seconds()) < 1
    assert head.max_alt == pytest.approx(
        satellites.look(sat, BRUSSELS, start).alt, abs=0.05
    )
    assert tail.culmination == tail.set == end
    assert abs((tail.rise - following.rise).total_seconds()) < 1
    assert tail.max_alt == pytest.approx(
        satellites.look(sat, BRUSSELS, end).alt, abs=0.05
    )


def decaying_elements() -> satellites.SatElements:
    """A satellite at 200 km with a very high drag term. SGP4 reports that
    it decays some hours after its epoch."""
    satrec = Satrec()
    epoch = iss_elements().epoch + datetime.timedelta(days=0.5)
    days = epoch - datetime.datetime(1949, 12, 31, tzinfo=datetime.timezone.utc)
    satrec.sgp4init(
        WGS72,
        "i",
        99999,
        days.total_seconds() / 86400.0,
        0.5,
        0.0,
        0.0,
        0.001,
        0.0,
        0.9,
        0.0,
        0.0675,
        0.0,
    )
    line1, line2 = exporter.export_tle(satrec)
    return satellites.SatElements("DECAYED", 99999, line1, line2, "user")


@pytest.mark.unit
def test_element_set_that_sgp4_cannot_propagate_is_skipped(caplog):
    bad = satellites.TrackedSatellite.from_elements(decaying_elements())
    iss = satellites.TrackedSatellite.from_elements(iss_elements())
    with caplog.at_level("WARNING", logger="Satellites"):
        found = satellites.find_passes_many([bad, iss], BRUSSELS, NOW, hours=24)
    assert found[0] == []
    assert len(found[1]) >= 2
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1 and "DECAYED" in warnings[0].getMessage()


@pytest.mark.unit
def test_pass_grid_step_is_a_fraction_of_the_orbit():
    iss = satellites.TrackedSatellite.from_elements(iss_elements()).satellite.model
    # 92.9 minute orbit: 1/20 of it.
    assert satellites._grid_step_seconds(iss) == pytest.approx(279, abs=2)
    results, _errors = satellites.parse_elements(GEO_TLE)
    geo = satellites.TrackedSatellite.from_elements(results[0]).satellite.model
    assert satellites._grid_step_seconds(geo) == satellites.PASS_GRID_MAX_SECONDS


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
        shared_state, data_directory=tmp_path, start_threads=False
    )
    # The pass worker runs in the calling thread, so a test sees the result.
    cat._spawn_pass_worker = cat._run_pass_updates
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


# ---------------------------------------------------------------------------
# Many satellites at one time
# ---------------------------------------------------------------------------


def visual_satellites() -> list:
    elements, _errors = satellites.parse_elements((DATA / "visual.tle").read_text())
    return [satellites.TrackedSatellite.from_elements(e) for e in elements]


def renumbered_tle(norad_id: int, name: str = "HAND MADE") -> str:
    """The ISS element set with another catalog number, as a typed TLE."""
    element = iss_elements()
    lines = []
    for line in (element.line1, element.line2):
        line = line[:2] + f"{norad_id:05d}" + line[7:68]
        lines.append(line + str(satellites.tle_checksum(line)))
    return f"{name}\n{lines[0]}\n{lines[1]}\n"


@pytest.mark.unit
def test_look_many_agrees_with_look():
    sats = visual_satellites()
    assert len(sats) > 10
    many = satellites.look_many(sats, BRUSSELS, NOW)
    for sat, fast in zip(sats, many):
        slow = satellites.look(sat, BRUSSELS, NOW)
        assert fast.alt == pytest.approx(slow.alt, abs=1e-3)
        assert (fast.az - slow.az + 180) % 360 - 180 == pytest.approx(0, abs=1e-2)
        assert (fast.ra - slow.ra + 180) % 360 - 180 == pytest.approx(0, abs=1e-2)
        assert fast.dec == pytest.approx(slow.dec, abs=1e-3)
        assert fast.range_km == pytest.approx(slow.range_km, rel=1e-5)
        assert fast.sunlit == slow.sunlit
        assert (fast.mag is None) == (slow.mag is None)
        if fast.mag is not None:
            assert fast.mag == pytest.approx(slow.mag, abs=1e-3)
    assert satellites.look_many([], BRUSSELS, NOW) == []


@pytest.mark.unit
def test_seconds_until_set_is_the_horizon_crossing():
    iss = satellites.TrackedSatellite.from_elements(iss_elements())
    moment = satellites.find_passes(iss, BRUSSELS, NOW, hours=24)[0].culmination
    sats = visual_satellites() + [iss]
    looks = satellites.look_many(sats, BRUSSELS, moment)
    waits = satellites.seconds_until_set(sats, BRUSSELS, moment)
    assert waits[-1] is not None
    checked = 0
    for sat, now, wait in zip(sats, looks, waits):
        if now.alt <= 0:
            assert wait is None
            continue
        if wait is None:
            continue
        before = moment + datetime.timedelta(seconds=max(wait - 15, 0))
        after = moment + datetime.timedelta(seconds=wait + 15)
        assert satellites.look(sat, BRUSSELS, before).alt > 0
        assert satellites.look(sat, BRUSSELS, after).alt < 0
        checked += 1
    assert checked > 0


@pytest.mark.unit
def test_epoch_is_computed_once():
    element = iss_elements()
    assert element.epoch is element.epoch


# ---------------------------------------------------------------------------
# User data: magnitudes and the selection
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_delete_removes_the_magnitude_and_the_selection_entry(tmp_path):
    satellites.save_user_elements([iss_elements()], tmp_path)
    satellites.save_user_mag(ISS_NORAD, 1.5, tmp_path)
    satellites.set_user_enabled(ISS_NORAD, False, tmp_path)
    assert satellites.delete_user_element(ISS_NORAD, tmp_path)
    assert satellites.load_user_mags(tmp_path) == {}
    assert satellites.load_selection(tmp_path).user_enabled(ISS_NORAD)


@pytest.mark.unit
def test_selection_is_stored_and_filters_the_elements(tmp_path):
    (tmp_path / "visual.tle").write_text((DATA / "visual.tle").read_text())
    web_satellites.add_elements(renumbered_tle(90001), directory=tmp_path)
    every = {e.norad_id for e in satellites.load_all_elements(NOW, tmp_path)}
    assert 90001 in every and len(every) > 10

    satellites.set_group_enabled("visual", False, tmp_path)
    assert json.loads((tmp_path / satellites.SELECTION_FILE_NAME).read_text())
    ids = {e.norad_id for e in satellites.load_all_elements(NOW, tmp_path)}
    assert ids == {90001}
    stored = satellites.load_all_elements(NOW, tmp_path, include_disabled=True)
    assert {e.norad_id for e in stored} == every

    satellites.set_user_enabled(90001, False, tmp_path)
    assert satellites.load_all_elements(NOW, tmp_path) == []
    assert [e.norad_id for e in satellites.load_user_elements(tmp_path)] == [90001]

    satellites.set_group_enabled("visual", True, tmp_path)
    satellites.set_user_enabled(90001, True, tmp_path)
    assert {e.norad_id for e in satellites.load_all_elements(NOW, tmp_path)} == every
    with pytest.raises(ValueError):
        satellites.set_group_enabled("no-such-group", False, tmp_path)


@pytest.mark.unit
def test_web_rows_show_the_selection(tmp_path):
    web_satellites.add_elements(renumbered_tle(90001), directory=tmp_path)
    web_satellites.set_enabled("group", "stations", False, tmp_path)
    web_satellites.set_enabled("user", "90001", False, tmp_path)
    groups = {
        r["group"]: r["enabled"] for r in web_satellites.group_status(NOW, tmp_path)
    }
    assert groups == {"visual": True, "stations": False}
    assert [r["enabled"] for r in web_satellites.user_satellites(NOW, tmp_path)] == [
        False
    ]
    with pytest.raises(ValueError):
        web_satellites.set_enabled("other", "1", True, tmp_path)
    with pytest.raises(ValueError):
        web_satellites.set_enabled("user", "abc", True, tmp_path)


@pytest.mark.unit
def test_hand_made_tle_outside_every_group_enters_the_catalog(catalog):
    directory = catalog.data_directory
    assert catalog.get_object_by_sequence(90001) is None
    found, errors = web_satellites.add_elements(
        renumbered_tle(90001, "USA 999"), directory=directory
    )
    assert errors == [] and [e.norad_id for e in found] == [90001]
    catalog.do_timed_task()
    obj = catalog.get_object_by_sequence(90001)
    assert obj is not None and obj.names == ["USA 999"]
    cache = satellites.read_pass_cache(directory)
    assert any(s["norad_id"] == 90001 for s in cache["satellites"])
    detail = web_satellites.satellite_detail(
        90001, NOW, catalog.shared_state.location(), days=0.0, directory=directory
    )
    assert detail["enabled"] and detail["source"] == "user"


@pytest.mark.unit
def test_catalog_follows_the_selection_without_a_restart(catalog):
    directory = catalog.data_directory
    web_satellites.add_elements(renumbered_tle(90001), directory=directory)
    catalog.do_timed_task()
    count = len(catalog.get_objects())
    assert catalog.get_object_by_sequence(90001) is not None

    web_satellites.set_enabled("user", "90001", False, directory)
    web_satellites.set_enabled("group", "visual", False, directory)
    catalog.do_timed_task()
    # The stations group stays, and it holds only the ISS.
    assert [obj.sequence for obj in catalog.get_objects()] == [ISS_NORAD]
    cache = satellites.read_pass_cache(directory)
    assert [s["norad_id"] for s in cache["satellites"]] == [ISS_NORAD]
    rows, _cache = web_satellites.upcoming_passes(NOW, False, directory)
    assert {row["norad_id"] for row in rows} == {ISS_NORAD}
    detail = web_satellites.satellite_detail(
        90001, NOW, catalog.shared_state.location(), days=0.0, directory=directory
    )
    assert detail is not None and not detail["enabled"]

    web_satellites.set_enabled("user", "90001", True, directory)
    web_satellites.set_enabled("group", "visual", True, directory)
    catalog.do_timed_task()
    assert len(catalog.get_objects()) == count


@pytest.mark.unit
def test_pass_table_hides_a_satellite_before_the_cache_is_new(catalog):
    directory = catalog.data_directory
    before, _cache = web_satellites.upcoming_passes(NOW, False, directory)
    assert any(row["norad_id"] != ISS_NORAD for row in before)
    # The catalog did not run after this change, so the cache is the old one.
    web_satellites.set_enabled("group", "visual", False, directory)
    after, _cache = web_satellites.upcoming_passes(NOW, False, directory)
    assert after and {row["norad_id"] for row in after} == {ISS_NORAD}


# ---------------------------------------------------------------------------
# Web form checks
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_norad_number_messages(tmp_path, monkeypatch):
    def no_elements(norad):
        raise satellites.ElementParseError("no element sets found")

    monkeypatch.setattr(satellites, "fetch_by_norad", no_elements)
    _found, errors = web_satellites.add_elements("", norad="99999", directory=tmp_path)
    assert errors == ["CelesTrak has no elements for NORAD 99999"]
    for text in ("abc", "-4", "0"):
        _found, errors = web_satellites.add_elements("", norad=text, directory=tmp_path)
        assert errors == [f"not a NORAD number: {text}"]

    def network_down(norad):
        raise OSError("no route")

    monkeypatch.setattr(satellites, "fetch_by_norad", network_down)
    _found, errors = web_satellites.add_elements("", norad="25544", directory=tmp_path)
    assert errors == ["CelesTrak: no route"]


@pytest.mark.unit
@pytest.mark.parametrize("text", ["nan", "inf", "-inf", "bright"])
def test_magnitude_must_be_a_finite_number(tmp_path, text):
    found, errors = web_satellites.add_elements(
        (DATA / "25544.3le").read_text(), std_mag=text, directory=tmp_path
    )
    assert found and errors == [f"not a magnitude: {text}"]
    assert satellites.load_user_mags(tmp_path) == {}


# ---------------------------------------------------------------------------
# Downloads
# ---------------------------------------------------------------------------


class FakeDownloads:
    """Replaces the network. Writes the fixture file when ``success`` is set."""

    def __init__(self, success=True):
        self.success = success
        self.groups = []

    def __call__(self, group, directory=None, progress_callback=None):
        self.groups.append(group)
        if self.success:
            satellites.group_file(group, directory).write_text(
                (DATA / "25544.3le").read_text()
            )
        return satellites.DownloadResult(self.success, None, None)


def system_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


@pytest.mark.unit
def test_forced_download_is_refused_a_short_time_after_a_download(
    tmp_path, monkeypatch
):
    downloads = FakeDownloads()
    monkeypatch.setattr(satellites, "download_group", downloads)
    first = satellites.refresh_groups(system_now(), True, tmp_path)
    assert first.status == "downloaded" and first.ok
    assert downloads.groups == list(satellites.CELESTRAK_GROUPS)

    again = satellites.refresh_groups(system_now(), True, tmp_path)
    assert again.status == "too_soon" and not again.ok
    assert 0 < again.wait_seconds <= satellites.MIN_FORCED_DOWNLOAD_SECONDS
    assert len(downloads.groups) == len(satellites.CELESTRAK_GROUPS)
    assert "Wait 5 min" in web_satellites.refresh_message(again)[1]

    later = system_now() + datetime.timedelta(
        seconds=satellites.MIN_FORCED_DOWNLOAD_SECONDS + 1
    )
    assert satellites.refresh_groups(later, True, tmp_path).status == "downloaded"
    assert satellites.refresh_groups(later, False, tmp_path).status == "current"


@pytest.mark.unit
def test_only_one_download_runs_at_a_time(tmp_path, monkeypatch):
    results = []

    def download_during_a_download(group, directory=None, progress_callback=None):
        results.append(satellites.refresh_groups(system_now(), True, tmp_path))
        return satellites.DownloadResult(True, None, None)

    monkeypatch.setattr(satellites, "download_group", download_during_a_download)
    assert satellites.refresh_groups(system_now(), True, tmp_path).status == (
        "downloaded"
    )
    assert results and {result.status for result in results} == {"busy"}
    assert web_satellites.refresh_message(results[0])[1]


@pytest.mark.unit
def test_failed_download_is_tried_again_soon_and_shows_an_error(tmp_path, monkeypatch):
    downloads = FakeDownloads(success=False)
    monkeypatch.setattr(satellites, "download_group", downloads)
    cat = satellite_catalog.SatelliteCatalog(
        FixedSharedState(NOW), data_directory=tmp_path, start_threads=False
    )
    assert cat.get_status().current == CatalogState.CALCULATING
    result = cat._refresh_sources()
    assert result.status == "failed"
    assert result.failed == satellites.CELESTRAK_GROUPS
    assert cat._download_wait_seconds(result) == cat.DOWNLOAD_FAILED_RETRY_SECONDS
    assert cat.DOWNLOAD_FAILED_RETRY_SECONDS <= 60
    assert cat.get_status().current == CatalogState.ERROR
    assert "Download failed" in web_satellites.refresh_message(result)[1]

    downloads.success = True
    result = cat._refresh_sources()
    assert result.status == "downloaded"
    assert cat._download_wait_seconds(result) == cat.DOWNLOAD_RETRY_SECONDS
    assert cat.get_status().current == CatalogState.CALCULATING
    cat._spawn_pass_worker = lambda: None
    cat.do_timed_task()
    assert cat.get_status().current == CatalogState.READY


@pytest.mark.unit
def test_device_refresh_is_refused_after_a_recent_download(catalog, monkeypatch):
    # The fixture wrote the group files a moment ago.
    downloads = FakeDownloads()
    monkeypatch.setattr(satellites, "download_group", downloads)
    wait = catalog.refresh()
    assert wait is not None and 0 < wait <= satellites.MIN_FORCED_DOWNLOAD_SECONDS
    assert downloads.groups == []


# ---------------------------------------------------------------------------
# Catalog updates
# ---------------------------------------------------------------------------


class CountingSharedState(FixedSharedState):
    def __init__(self, dt):
        super().__init__(dt)
        self.calls = {"altaz_ready": 0, "datetime": 0, "location": 0}

    def altaz_ready(self):
        self.calls["altaz_ready"] += 1
        return True

    def datetime(self):
        self.calls["datetime"] += 1
        return self.dt

    def location(self):
        self.calls["location"] += 1
        return self._location


@pytest.mark.unit
def test_one_update_reads_the_shared_state_once(tmp_path):
    (tmp_path / "visual.tle").write_text((DATA / "visual.tle").read_text())
    shared_state = CountingSharedState(NOW)
    cat = satellite_catalog.SatelliteCatalog(
        shared_state, data_directory=tmp_path, start_threads=False
    )
    cat._spawn_pass_worker = cat._run_pass_updates
    cat.do_timed_task()
    assert len(cat.get_objects()) > 10
    assert shared_state.calls == {"altaz_ready": 1, "datetime": 1, "location": 1}

    shared_state.dt = NOW + datetime.timedelta(seconds=5)
    cat.do_timed_task()
    assert shared_state.calls == {"altaz_ready": 2, "datetime": 2, "location": 2}

    obj = cat.get_objects()[0]
    for second in range(10):
        moment = shared_state.dt + datetime.timedelta(seconds=second)
        assert satellite_catalog.live_radec(obj, moment) is not None
    assert shared_state.calls == {"altaz_ready": 2, "datetime": 2, "location": 2}


@pytest.mark.unit
def test_position_update_does_not_make_the_lists_build_again(catalog):
    invalidations = []
    invalidate = catalog.invalidate_filter_cache
    catalog.invalidate_filter_cache = lambda: (
        invalidations.append(catalog.shared_state.dt),
        invalidate(),
    )
    iss = catalog.get_object_by_sequence(ISS_NORAD)
    position = (iss.ra, iss.dec)
    # The same time again: no satellite crosses the horizon.
    catalog.do_timed_task()
    assert invalidations == []

    # Updates five seconds apart. The positions change on each update. The
    # lists build again only when the set of satellites above the horizon
    # changes.
    up_sets = [catalog._list_state[1]]
    for step in range(1, 55):
        catalog.shared_state.dt = NOW + datetime.timedelta(seconds=5 * step)
        catalog.do_timed_task()
        up_sets.append(catalog._list_state[1])
    assert (iss.ra, iss.dec) != position
    changes = sum(1 for a, b in zip(up_sets, up_sets[1:]) if a != b)
    assert len(invalidations) == changes
    assert changes < 54

    # A change of the object set makes the lists build again.
    before = len(invalidations)
    web_satellites.set_enabled("group", "visual", False, catalog.data_directory)
    catalog.do_timed_task()
    assert len(invalidations) == before + 1


@pytest.mark.unit
def test_new_pass_data_makes_the_lists_build_again(catalog):
    catalog.do_timed_task()
    marker = catalog.last_filtered = 123.0
    catalog.do_timed_task()
    assert catalog.last_filtered == marker
    catalog._update_passes(
        NOW + datetime.timedelta(seconds=1), catalog.shared_state.location()
    )
    catalog.do_timed_task()
    assert catalog.last_filtered == 0


@pytest.mark.unit
def test_pass_request_during_a_run_causes_one_more_run(catalog):
    location = catalog.shared_state.location()
    spawned = []
    runs = []
    catalog._spawn_pass_worker = lambda: spawned.append(True)
    first = NOW + datetime.timedelta(minutes=1)
    second = NOW + datetime.timedelta(minutes=2)
    third = NOW + datetime.timedelta(minutes=3)

    def update_passes(dt, place):
        runs.append((dt, sorted(catalog._tracked)))
        if dt == first:
            # Two requests arrive while this run is busy. The newest one wins.
            del catalog._tracked[ISS_NORAD]
            catalog._start_pass_update(second, location)
            catalog._start_pass_update(third, location)

    catalog._update_passes = update_passes
    catalog._start_pass_update(first, location)
    assert spawned == [True]
    catalog._run_pass_updates()
    assert spawned == [True]
    assert [dt for dt, _ids in runs] == [first, third]
    assert ISS_NORAD in runs[0][1] and ISS_NORAD not in runs[1][1]
    assert not catalog._pass_running

    catalog._start_pass_update(first, location)
    assert spawned == [True, True]


@pytest.mark.unit
def test_pass_worker_stays_usable_after_an_error(catalog):
    location = catalog.shared_state.location()

    def fail(dt, place):
        raise RuntimeError("no passes")

    catalog._update_passes = fail
    catalog._start_pass_update(NOW, location)
    assert not catalog._pass_running


@pytest.mark.unit
def test_slow_pass_run_does_not_cause_a_request_on_each_update(catalog):
    requests = []
    catalog._spawn_pass_worker = lambda: requests.append(catalog.shared_state.dt)
    catalog.shared_state.dt = NOW + datetime.timedelta(
        seconds=catalog.PASS_UPDATE_SECONDS + 1
    )
    catalog.do_timed_task()
    assert len(requests) == 1
    # The run is not complete. The next updates do not ask again.
    for second in (5, 10, 15):
        catalog.shared_state.dt += datetime.timedelta(seconds=second)
        catalog.do_timed_task()
    assert len(requests) == 1
    assert catalog._pass_request is not None


# ---------------------------------------------------------------------------
# In the sky now
# ---------------------------------------------------------------------------


def time_with_iss_up() -> datetime.datetime:
    sat = satellites.TrackedSatellite.from_elements(iss_elements())
    passes = satellites.find_passes(sat, BRUSSELS, NOW, hours=24)
    return passes[0].culmination


@pytest.mark.unit
def test_description_starts_with_altitude_and_azimuth_when_up(catalog):
    catalog.shared_state.dt = time_with_iss_up()
    catalog.do_timed_task()
    iss = catalog.get_object_by_sequence(ISS_NORAD)
    sat = catalog.tracked(ISS_NORAD)
    now = satellites.look(sat, BRUSSELS, catalog.shared_state.dt)
    assert now.alt >= 10
    first_line = iss.description.splitlines()[0]
    assert first_line == (
        f"Alt {now.alt:.0f}° Az {now.az:.0f}° {satellites.compass(now.az)}"
    )
    down = [
        obj
        for obj in catalog.get_objects()
        if obj.description.startswith("Below horizon")
    ]
    assert down


@pytest.mark.unit
def test_next_pass_sort_puts_satellites_above_the_horizon_first(catalog):
    catalog.shared_state.dt = time_with_iss_up()
    catalog.do_timed_task()
    objects = catalog.get_objects()
    up = [obj for obj in objects if obj.description.startswith("Alt ")]
    down = [obj for obj in objects if not obj.description.startswith("Alt ")]
    assert up and down
    assert all(obj.next_pass_ts < 0 for obj in up)
    assert all(obj.next_pass_ts is None or obj.next_pass_ts > 0 for obj in down)
    # The object list sorts by this key and puts None last.
    key = lambda obj: np.inf if obj.next_pass_ts is None else obj.next_pass_ts  # noqa: E731
    ordered = sorted(objects, key=key)
    assert set(map(id, ordered[: len(up)])) == set(map(id, up))
    altitudes = [-obj.next_pass_ts for obj in ordered[: len(up)]]
    assert altitudes == sorted(altitudes, reverse=True)


@pytest.mark.unit
def test_sky_now_lists_the_satellites_above_the_horizon(catalog):
    moment = time_with_iss_up()
    location = catalog.shared_state.location()
    directory = catalog.data_directory
    rows = web_satellites.sky_now(moment, location, directory)
    assert rows
    altitudes = [row["alt"] for row in rows]
    assert altitudes == sorted(altitudes, reverse=True)
    assert all(alt > 0 for alt in altitudes)
    iss = next(row for row in rows if row["norad_id"] == ISS_NORAD)
    sat = satellites.TrackedSatellite.from_elements(iss_elements())
    now = satellites.look(sat, BRUSSELS, moment)
    assert iss["alt"] == pytest.approx(now.alt, abs=0.01)
    assert iss["az"] == pytest.approx(now.az, abs=0.05)
    assert iss["dir"] == satellites.compass(now.az)
    assert iss["sunlit"] == now.sunlit
    assert (iss["mag"] is None) == (now.mag is None)
    # The ISS is at the top of a pass, so it sets in a few minutes.
    assert 60 < iss["sets_in_seconds"] < 600
    assert "min" in iss["sets_in"]

    everything = satellites.load_all_elements(moment, directory)
    assert len(rows) < len(everything)

    web_satellites.set_enabled("group", "visual", False, directory)
    web_satellites.set_enabled("group", "stations", False, directory)
    assert web_satellites.sky_now(moment, location, directory) == []
    assert web_satellites.sky_now(moment, None, directory) is None


def shifted_iss(minutes: float) -> satellites.SatElements:
    """The ISS set with another mean anomaly and the same epoch."""
    element = iss_elements()
    body = element.line2[:43] + f"{float(element.line2[43:51]) + minutes:8.4f}"
    body += element.line2[51:68]
    return satellites.SatElements(
        element.name,
        element.norad_id,
        element.line1,
        body + str(satellites.tle_checksum(body)),
    )


@pytest.mark.unit
def test_corrected_name_has_the_mark_and_the_time():
    when = datetime.datetime(2026, 11, 13, 21, 4, 30, tzinfo=datetime.timezone.utc)
    assert satellites.corrected_name("ISS (ZARYA)", when) == (
        "ISS (ZARYA) corr 2026-11-13 21:04"
    )
    again = satellites.corrected_name("ISS (ZARYA) corr 2026-11-12 20:00", when)
    assert again == "ISS (ZARYA) corr 2026-11-13 21:04"


@pytest.mark.unit
def test_a_corrected_set_replaces_its_base_until_a_newer_download(tmp_path):
    (tmp_path / "stations.tle").write_text(iss_elements().to_tle())
    when = NOW
    satellites.save_corrected_element(shifted_iss(0.5), when, tmp_path)
    satellites.save_corrected_element(shifted_iss(1.0), when, tmp_path)
    stored = satellites.load_corrected_elements(tmp_path)
    assert len(stored) == 1 and stored[0].source == "corrected"
    assert stored[0].line2 == shifted_iss(1.0).line2
    merged = {e.norad_id: e for e in satellites.load_all_elements(NOW, tmp_path)}
    assert merged[ISS_NORAD].source == "corrected"
    assert merged[ISS_NORAD].name.startswith("ISS")
    assert satellites.CORRECTED_MARK in merged[ISS_NORAD].name

    # A newer download replaces the correction.
    element = iss_elements()
    line1 = element.line1[:18] + "26330.50000000" + element.line1[32:68]
    line1 += str(satellites.tle_checksum(line1))
    newer = satellites.SatElements(element.name, ISS_NORAD, line1, element.line2)
    (tmp_path / "stations.tle").write_text(newer.to_tle())
    later = newer.epoch + datetime.timedelta(days=1)
    merged = {e.norad_id: e for e in satellites.load_all_elements(later, tmp_path)}
    assert merged[ISS_NORAD].source == "celestrak"


@pytest.mark.unit
def test_corrected_sets_can_be_disabled_and_deleted(tmp_path):
    (tmp_path / "stations.tle").write_text(iss_elements().to_tle())
    satellites.save_corrected_element(shifted_iss(0.5), NOW, tmp_path)
    satellites.set_user_enabled(90001, False, tmp_path)
    web_satellites.set_enabled("corrected", str(ISS_NORAD), False, tmp_path)
    selection = satellites.load_selection(tmp_path)
    assert not selection.corrected_enabled(ISS_NORAD)
    assert not selection.user_enabled(90001)
    merged = {e.norad_id: e for e in satellites.load_all_elements(NOW, tmp_path)}
    assert merged[ISS_NORAD].source == "celestrak"
    rows = web_satellites.corrected_satellites(NOW, tmp_path)
    assert [(r["enabled"], r["in_use"]) for r in rows] == [(False, False)]

    web_satellites.set_enabled("corrected", str(ISS_NORAD), True, tmp_path)
    rows = web_satellites.corrected_satellites(NOW, tmp_path)
    assert [(r["enabled"], r["in_use"]) for r in rows] == [(True, True)]

    web_satellites.set_enabled("corrected", str(ISS_NORAD), False, tmp_path)
    assert satellites.delete_corrected_element(ISS_NORAD, tmp_path)
    assert not satellites.delete_corrected_element(ISS_NORAD, tmp_path)
    selection = satellites.load_selection(tmp_path)
    assert selection.corrected_enabled(ISS_NORAD)
    assert not selection.user_enabled(90001)
