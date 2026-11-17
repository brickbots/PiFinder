"""Satellites on the chart: the target cross at the live position of a
satellite, and the satellites in the field with their symbol and track line.

The layer tests use a fake catalog with straight-line motion, so the
expected positions are simple. The catalog tests use the ISS fixture.
"""

import datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

# Installs the ``_()`` gettext builtin that PiFinder.ui modules rely on.
import PiFinder.i18n  # noqa: F401

import PiFinder.satellite_catalog as satellite_catalog
import PiFinder.satellites as satellites
from PiFinder import utils
from PiFinder.composite_object import CompositeObject, MagnitudeObject, SizeObject
from PiFinder.nearby import ClosestObjectsFinder
from PiFinder.obj_types import OBJ_TYPE_MARKERS
from PiFinder.ui import chart_satellites
from PiFinder.ui.chart import NEARBY_RADIUS_FACTOR, SATELLITE_SYMBOL, UIChart
from PiFinder.ui.chart_satellites import (
    BATCH_CAP,
    FIELD_CAP,
    REFRESH_SECONDS,
    TRACK_SECONDS,
    SatelliteLayer,
    track_segment,
)
from satellite_helpers import NOW, make_catalog, seed_groups

DT = datetime.datetime(2026, 11, 14, 23, 0, 0, tzinfo=datetime.timezone.utc)
# Each fake satellite moves this much in Dec per second.
RATE = 0.5


def _sat_obj(norad):
    return CompositeObject(
        object_id=-norad,
        ra=0.0,
        dec=0.0,
        obj_type=satellite_catalog.OBJ_TYPE,
        catalog_code=satellite_catalog.CATALOG_CODE,
        sequence=norad,
        names=[f"SAT {norad}"],
        mag=MagnitudeObject([]),
        size=SizeObject([]),
    )


class FakeSatCatalog:
    """The catalog calls of the chart. Satellite i is at ``(ra[i],
    dec[i] + RATE * t)`` at ``t`` seconds after DT, at altitude ``alt[i]``."""

    def __init__(self, ra, dec, alt, mag, selected=True):
        n = len(ra)
        self.ids = np.arange(1, n + 1, dtype=np.int64)
        self.ra = np.asarray(ra, dtype=float)
        self.dec = np.asarray(dec, dtype=float)
        self.alt = np.asarray(alt, dtype=float)
        self.mag = np.asarray(mag, dtype=float)
        self.objects = [_sat_obj(int(norad)) for norad in self.ids]
        self.selected = selected
        self.touches = 0
        self.track_calls = []
        self.catalog_code = satellite_catalog.CATALOG_CODE

    # -- Catalog API used by the chart
    def is_selected(self):
        return self.selected

    def get_filtered_objects(self):
        return self.objects

    def touch(self):
        self.touches += 1

    def sky_state(self, dt):
        t = (dt - DT).total_seconds()
        zeros = np.zeros(len(self.ids))
        return satellites.SkyState(
            time=dt,
            norad_ids=self.ids,
            ra=self.ra,
            dec=self.dec + RATE * t,
            alt=self.alt,
            az=zeros,
            range_km=zeros,
            mag=self.mag,
            sun_alt=-20.0,
        )

    def live_tracks(self, norad_ids, times):
        self.track_calls.append(list(norad_ids))
        rows = [int(norad) - 1 for norad in norad_ids]
        ts = np.array([(t - DT).total_seconds() for t in times])
        ra = np.repeat(self.ra[rows][:, None], len(times), axis=1)
        dec = self.dec[rows][:, None] + RATE * ts[None, :]
        alt = np.repeat(self.alt[rows][:, None], len(times), axis=1)
        return ra, dec, alt


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _field(
    catalog,
    layer=None,
    center=(10.0, 20.0),
    radius=5.0,
    dt=DT,
    mag=9.0,
    filtered=None,
    exclude=frozenset(),
):
    """The field of ``layer``, or of a new layer. ``filtered`` is the list of
    the catalog filter, all objects of ``catalog`` by default."""
    layer = layer or SatelliteLayer(clock=FakeClock())
    if filtered is None:
        filtered = catalog.get_filtered_objects()
    return layer.field(catalog, filtered, center, radius, dt, mag, exclude)


@pytest.mark.unit
class TestSatelliteLayer:
    def test_in_and_out_of_the_field(self):
        cat = FakeSatCatalog(
            ra=[10.0, 10.0, 30.0],
            dec=[20.0, 24.0, 20.0],
            alt=[40, 40, 40],
            mag=[3, 3, 3],
        )
        field = _field(cat)
        assert [sat.obj.sequence for sat in field] == [1, 2]

    def test_live_position_and_track(self):
        cat = FakeSatCatalog(ra=[10.0], dec=[20.0], alt=[40], mag=[3])
        layer = SatelliteLayer(clock=FakeClock())
        _field(cat, layer)
        later = DT + datetime.timedelta(seconds=2)
        (sat,) = _field(cat, layer, dt=later)
        # The second frame moves the batch of the first one: no new SGP4 call.
        assert len(cat.track_calls) == 1
        assert sat.dec == pytest.approx(20.0 + RATE * 2)
        assert sat.ahead_dec == pytest.approx(20.0 + RATE * (2 + TRACK_SECONDS))
        assert sat.ra == pytest.approx(10.0)

    def test_below_the_horizon(self):
        cat = FakeSatCatalog(ra=[10.0, 10.0], dec=[20.0, 21.0], alt=[-3, 5], mag=[3, 3])
        assert [sat.obj.sequence for sat in _field(cat)] == [2]

    def test_earth_shadow_and_magnitude_limit(self):
        # In shadow (NaN), fainter than the limit, at the limit.
        cat = FakeSatCatalog(
            ra=[10.0] * 3, dec=[20.0] * 3, alt=[40] * 3, mag=[np.nan, 9.5, 9.0]
        )
        assert [sat.obj.sequence for sat in _field(cat, mag=9.0)] == [3]

    def test_filter_decides(self):
        cat = FakeSatCatalog(
            ra=[10.0, 10.0], dec=[20.0, 21.0], alt=[40, 40], mag=[3, 3]
        )
        field = _field(cat, filtered=[cat.objects[1]])
        assert [sat.obj.sequence for sat in field] == [2]

    def test_cap_keeps_the_brightest(self):
        n = FIELD_CAP + 5
        mags = list(np.linspace(6.0, 1.0, n))
        cat = FakeSatCatalog(ra=[10.0] * n, dec=[20.0] * n, alt=[40] * n, mag=mags)
        field = _field(cat)
        assert len(field) == FIELD_CAP
        got = [sat.mag for sat in field]
        assert got == sorted(got)
        assert got[0] == pytest.approx(1.0)

    def test_exclude(self):
        cat = FakeSatCatalog(
            ra=[10.0, 10.0], dec=[20.0, 21.0], alt=[40, 40], mag=[3, 3]
        )
        field = _field(cat, exclude=frozenset([1]))
        assert [sat.obj.sequence for sat in field] == [2]

    def test_many_satellites_cost_is_bounded(self):
        # 10,000 satellites, 400 of them near the chart: one SGP4 call per
        # batch, with at most BATCH_CAP satellites, and none between batches.
        rng = np.random.default_rng(1)
        n = 10_000
        ra = rng.uniform(0, 360, n)
        dec = rng.uniform(-60, 60, n)
        ra[:400] = 10.0 + rng.uniform(-2, 2, 400)
        dec[:400] = 20.0 + rng.uniform(-2, 2, 400)
        cat = FakeSatCatalog(ra=ra, dec=dec, alt=[40] * n, mag=rng.uniform(1, 8, n))
        clock = FakeClock()
        layer = SatelliteLayer(clock=clock)
        assert len(_field(cat, layer)) == FIELD_CAP
        assert len(cat.track_calls) == 1
        assert len(cat.track_calls[0]) == BATCH_CAP
        clock.now += REFRESH_SECONDS / 2
        _field(cat, layer, dt=DT + datetime.timedelta(seconds=0.1))
        assert len(cat.track_calls) == 1
        clock.now += REFRESH_SECONDS
        _field(cat, layer, dt=DT + datetime.timedelta(seconds=0.4))
        assert len(cat.track_calls) == 2

    def test_slew_beyond_the_batch_makes_a_new_batch(self):
        cat = FakeSatCatalog(
            ra=[10.0, 60.0], dec=[20.0, 20.0], alt=[40, 40], mag=[3, 3]
        )
        layer = SatelliteLayer(clock=FakeClock())
        assert [s.obj.sequence for s in _field(cat, layer)] == [1]
        moved = _field(cat, layer, center=(60.0, 20.0))
        assert [s.obj.sequence for s in moved] == [2]
        assert len(cat.track_calls) == 2


@pytest.mark.unit
class TestTrackSegment:
    def test_starts_after_the_gap_in_the_direction_of_motion(self):
        x0, y0, x1, y1 = track_segment(50, 50, 60, 50, 6, 4, 14)
        assert (x0, y0) == (56, 50)
        assert (x1, y1) == (66, 50)

    def test_long_and_short_tracks_are_limited(self):
        assert track_segment(50, 50, 50, 150, 6, 4, 14)[3] == 50 + 6 + 14
        assert track_segment(50, 50, 51, 50, 6, 4, 14)[2] == 50 + 6 + 4

    def test_no_line_without_motion(self):
        assert track_segment(50, 50, 50.2, 50, 6, 4, 14) is None
        assert track_segment(50, 50, float("nan"), 50, 6, 4, 14) is None


@pytest.mark.unit
def test_satellite_symbol_exists():
    assert OBJ_TYPE_MARKERS[satellite_catalog.OBJ_TYPE] == SATELLITE_SYMBOL == "sat"
    path = Path(utils.pifinder_dir, "markers", f"mrk_{SATELLITE_SYMBOL}.png")
    with Image.open(path) as marker:
        assert marker.size == (11, 11)
        assert marker.convert("L").getbbox() is not None


# -- the chart -----------------------------------------------------------------


class FakeStarfield:
    """Records the markers; projects RA/Dec to x = ra, y = dec."""

    def __init__(self):
        self.marker_lists = []

    def plot_markers(self, marker_list):
        self.marker_lists.append(list(marker_list))
        return Image.new("RGB", (128, 128))

    def radec_to_xy(self, ra, dec):
        return ra, dec

    def radec_to_xy_many(self, ras, decs):
        return list(ras), list(decs)


class FakeCatalogs:
    def __init__(self, sat_catalog):
        self.sat_catalog = sat_catalog
        self.catalog_filter = SimpleNamespace(dirty_time=1.0)

    def get_catalog_by_code(self, code):
        return self.sat_catalog if code == satellite_catalog.CATALOG_CODE else None

    def get_catalogs(self, only_selected=True):
        return []

    def filter_catalogs(self, catalogs=None):
        pass

    def get_objects(self, only_selected=True, filtered=True):
        return []


class FakeColors:
    def get(self, value):
        return (value, 0, 0)


def _chart(sat_catalog, target=None, center=(10.0, 20.0), fov=10.0, dso=128):
    chart = UIChart.__new__(UIChart)
    chart.catalogs = FakeCatalogs(sat_catalog)
    chart._nearby_finder = ClosestObjectsFinder()
    chart._nearby_filter_dirty_time = None
    chart._satellite_layer = SatelliteLayer(clock=FakeClock())
    chart._live_radec = {}
    chart._satellites_shown = False
    chart._markers_time = 0.0
    est = SimpleNamespace(RA=center[0], Dec=center[1])
    chart.solution = SimpleNamespace(
        pointing=SimpleNamespace(aligned=SimpleNamespace(estimate=est)),
        has_pointing=lambda: True,
    )
    chart.fov = fov
    chart.ui_state = SimpleNamespace(observing_list=lambda: [], target=lambda: target)
    chart.snapshot = SimpleNamespace(datetime=lambda: DT)
    chart.config_object = SimpleNamespace(get_option=lambda name, default=None: dso)
    chart.display_class = SimpleNamespace(resolution=(128, 128), resX=128, resY=128)
    chart.colors = FakeColors()
    chart.starfield = FakeStarfield()
    chart.screen = Image.new("RGB", (128, 128))
    chart.draw = SimpleNamespace(
        text=lambda *a, **k: None, line=lambda *a, **k: chart.lines.append(a[0])
    )
    chart.lines = []
    chart.fonts = SimpleNamespace(base=SimpleNamespace(font=None))
    return chart


class FakeActiveCatalog:
    """The registry catalog that ``satellite_catalog.live_radec`` asks."""

    def __init__(self):
        self.asked = []

    def radec_of(self, norad_id, dt):
        self.asked.append((norad_id, dt))
        seconds = (dt - DT).total_seconds()
        return 100.0, 30.0 + seconds


@pytest.mark.unit
class TestChartSatellites:
    def test_target_cross_at_live_position(self, monkeypatch):
        active = FakeActiveCatalog()
        monkeypatch.setattr(satellite_catalog, "_active_catalog", active)
        target = _sat_obj(25544)
        # The 5 s catalog position, degrees away from the live one.
        target.ra, target.dec = 90.0, 25.0
        chart = _chart(FakeSatCatalog([], [], [], []), target=target)
        chart.plot_markers()
        first = chart.starfield.marker_lists[0]
        assert first[0][2] == "target"
        assert first[0][0] == pytest.approx(100.0 / 15.0)
        assert first[0][1] == pytest.approx(30.0)
        assert active.asked == [(25544, DT)]
        assert chart._live_radec[id(target)] == (100.0, 30.0)
        # The catalog object keeps its catalog position.
        assert (target.ra, target.dec) == (90.0, 25.0)
        assert chart._satellites_shown

    def test_non_satellite_target_is_unchanged(self, monkeypatch):
        monkeypatch.setattr(satellite_catalog, "_active_catalog", FakeActiveCatalog())
        target = CompositeObject(object_id=1, ra=45.0, dec=10.0, obj_type="Gx")
        chart = _chart(FakeSatCatalog([], [], [], []), target=target)
        chart.plot_markers()
        assert chart.starfield.marker_lists[0][0][:2] == (3.0, 10.0)
        assert not chart._satellites_shown

    def test_field_satellites_drawn_with_symbol_and_track(self):
        cat = FakeSatCatalog(
            ra=[10.0, 10.0, 80.0],
            dec=[20.0, 22.0, 20.0],
            alt=[40, -5, 40],
            mag=[3, 3, 3],
        )
        chart = _chart(cat)
        chart.plot_markers()
        (markers,) = chart.starfield.marker_lists
        assert [m[2] for m in markers] == [SATELLITE_SYMBOL]
        assert markers[0][1] == pytest.approx(20.0)
        assert [o.sequence for o in chart._drawn_objects] == [1]
        assert len(chart.lines) == 1
        assert cat.touches == 1
        assert chart._satellites_shown

    def test_field_uses_the_chart_radius(self):
        radius = 10.0 * NEARBY_RADIUS_FACTOR
        cat = FakeSatCatalog(
            ra=[10.0, 10.0],
            dec=[20.0 + radius - 0.1, 20.0 + radius + 0.5],
            alt=[40, 40],
            mag=[3, 3],
        )
        chart = _chart(cat)
        chart.plot_markers()
        assert [o.sequence for o in chart._drawn_objects] == [1]

    def test_open_chart_uses_a_selected_catalog_with_no_satellite_in_view(self):
        # The only satellite is far from the chart center.
        cat = FakeSatCatalog(ra=[200.0], dec=[-40.0], alt=[40], mag=[3])
        chart = _chart(cat)
        chart.plot_markers()
        assert chart._drawn_objects == []
        assert cat.touches == 1

    def test_no_satellites_when_the_catalog_is_not_selected(self):
        cat = FakeSatCatalog(ra=[10.0], dec=[20.0], alt=[40], mag=[3], selected=False)
        chart = _chart(cat)
        chart.plot_markers()
        assert chart.starfield.marker_lists == []
        assert cat.touches == 0
        assert cat.track_calls == []
        assert not chart._satellites_shown

    def test_no_satellites_with_markers_off(self):
        cat = FakeSatCatalog(ra=[10.0], dec=[20.0], alt=[40], mag=[3])
        chart = _chart(cat, dso=0)
        chart.plot_markers()
        assert chart.starfield.marker_lists == []

    def test_target_satellite_is_not_drawn_twice(self, monkeypatch):
        monkeypatch.setattr(satellite_catalog, "_active_catalog", FakeActiveCatalog())
        cat = FakeSatCatalog(
            ra=[10.0, 10.0], dec=[20.0, 21.0], alt=[40, 40], mag=[3, 3]
        )
        chart = _chart(cat, target=cat.objects[0])
        chart.plot_markers()
        _target_list, markers = chart.starfield.marker_lists
        assert [m[2] for m in markers] == [SATELLITE_SYMBOL]
        assert [o.sequence for o in chart._drawn_objects] == [1, 2]

    def test_redraw_due_only_with_satellites(self, monkeypatch):
        cat = FakeSatCatalog(ra=[10.0], dec=[20.0], alt=[40], mag=[3])
        chart = _chart(cat)
        chart._starfield_base = Image.new("RGB", (128, 128))
        chart.plot_markers()
        assert not chart._satellite_frame_due()
        chart._markers_time -= chart_satellites.REFRESH_SECONDS
        assert chart._satellite_frame_due()
        cat.alt[:] = -10.0
        chart._satellite_layer.reset()
        chart.plot_markers()
        chart._markers_time -= chart_satellites.REFRESH_SECONDS
        assert not chart._satellite_frame_due()


# -- the catalog ---------------------------------------------------------------


@pytest.fixture
def iss_catalog(tmp_path, monkeypatch):
    monkeypatch.setattr(satellite_catalog, "_active_catalog", None)
    seed_groups(tmp_path, files=("stations",))
    return make_catalog(tmp_path, sync_passes=False), NOW


@pytest.mark.unit
class TestCatalogSkyState:
    def test_update_state_is_reused_while_recent(self, iss_catalog):
        cat, now = iss_catalog
        state = cat.sky_state(now + datetime.timedelta(seconds=3))
        assert state is cat._sky
        assert state.time == now
        obj = cat.get_object_by_sequence(25544)
        assert list(state.norad_ids) == [25544]
        assert state.ra[0] == pytest.approx(obj.ra)
        assert state.dec[0] == pytest.approx(obj.dec)

    def test_old_state_is_made_again(self, iss_catalog):
        cat, now = iss_catalog
        later = now + datetime.timedelta(minutes=5)
        state = cat.sky_state(later)
        assert state.time == later
        ra, dec = cat.radec_of(25544, later)
        assert state.ra[0] == pytest.approx(ra, abs=1e-6)
        assert state.dec[0] == pytest.approx(dec, abs=1e-6)

    def test_sky_state_is_not_a_use(self, iss_catalog):
        cat, now = iss_catalog
        cat._last_use = None
        cat.sky_state(now + datetime.timedelta(minutes=5))
        assert not cat.in_use()

    def test_live_tracks_match_radec_of(self, iss_catalog):
        cat, now = iss_catalog
        times = [now, now + datetime.timedelta(seconds=TRACK_SECONDS)]
        ra, dec, alt = cat.live_tracks([25544, 99999], times)
        for column, dt in enumerate(times):
            expected = cat.radec_of(25544, dt)
            assert ra[0, column] == pytest.approx(expected[0], abs=1e-6)
            assert dec[0, column] == pytest.approx(expected[1], abs=1e-6)
        assert np.isnan(ra[1]).all() and np.isnan(alt[1]).all()

    def test_looks_are_the_rows_of_the_state(self, iss_catalog):
        cat, now = iss_catalog
        state = cat.sky_state(now)
        state.mag[0] = np.nan
        (look,) = state.looks()
        assert (look.ra, look.dec, look.alt) == (
            state.ra[0],
            state.dec[0],
            state.alt[0],
        )
        assert (look.az, look.range_km) == (state.az[0], state.range_km[0])
        assert look.mag is None and not look.sunlit
