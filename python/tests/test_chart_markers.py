"""
Unit tests for the chart's DSO-marker logic: the zoom-scaled magnitude limit
(``dso_mag_limit``), the nearby-catalog marker selection (mag filter + cap +
drawable-type filter, with a rebuild-on-dirty spatial index), and the
dedup/precedence in ``_collect_dso_markers``.

``UIChart`` is exercised via ``__new__`` with hand-injected collaborators so
the tests never construct ``plot.Starfield`` (which needs ``hip_main.dat``) --
only the pure marker-selection paths are under test here.
"""

from types import SimpleNamespace

import pytest

# Installs the ``_()`` gettext builtin that PiFinder.ui modules rely on.
import PiFinder.i18n  # noqa: F401

from PiFinder.composite_object import CompositeObject, MagnitudeObject, SizeObject
from PiFinder.nearby import ClosestObjectsFinder
from PiFinder.ui.chart import (
    NEARBY_MARKER_CAP,
    UIChart,
    dso_mag_limit,
)


def _dso(object_id, ra, dec, mag=None, obj_type="Gx", catalog_code="NGC", size=None):
    magobj = MagnitudeObject([str(mag)]) if mag is not None else MagnitudeObject([])
    return CompositeObject(
        object_id=object_id,
        ra=ra,
        dec=dec,
        obj_type=obj_type,
        catalog_code=catalog_code,
        mag=magobj,
        size=size if size is not None else SizeObject([]),
    )


def _solution(ra, dec):
    est = SimpleNamespace(RA=ra, Dec=dec)
    return SimpleNamespace(
        pointing=SimpleNamespace(aligned=SimpleNamespace(estimate=est))
    )


class _StubCatalogs:
    """Minimal stand-in exposing what _get_nearby_markers reads."""

    def __init__(self, objects, dirty_time=1.0):
        self._objects = objects
        self.catalog_filter = SimpleNamespace(dirty_time=dirty_time)

    def get_objects(self, only_selected=True, filtered=True):
        return list(self._objects)


def _chart(catalogs, solution, fov=5.0, observing_list=()):
    chart = UIChart.__new__(UIChart)
    chart.catalogs = catalogs
    chart._nearby_finder = ClosestObjectsFinder()
    chart._nearby_filter_dirty_time = None
    chart.solution = solution
    chart.fov = fov
    chart.ui_state = SimpleNamespace(observing_list=lambda: list(observing_list))
    return chart


@pytest.mark.unit
class TestDsoMagLimit:
    def test_endpoints(self):
        assert dso_mag_limit(5.0) == 11.0
        assert dso_mag_limit(60.0) == 7.0

    def test_clamps_outside_zoom_range(self):
        assert dso_mag_limit(1.0) == 11.0  # below the 5deg endpoint
        assert dso_mag_limit(120.0) == 7.0  # above the 60deg endpoint

    def test_linear_midpoint(self):
        # Halfway through the FOV range -> halfway through the mag range.
        assert dso_mag_limit(32.5) == pytest.approx(9.0, abs=1e-6)

    def test_monotonic_decreasing(self):
        assert dso_mag_limit(10.0) > dso_mag_limit(30.0) > dso_mag_limit(50.0)


@pytest.mark.unit
class TestNearbyMarkerSelection:
    def test_hides_unknown_faint_and_undrawable(self):
        objs = [
            _dso(1, 0.0, 0.0, mag=8.0, obj_type="Gx"),  # bright galaxy -> keep
            _dso(2, 0.0, 0.2, mag=12.0, obj_type="Gx"),  # fainter than limit -> drop
            _dso(3, 0.0, 0.3, mag=None, obj_type="Gx"),  # unknown mag -> drop
            _dso(4, 0.0, 0.4, mag=6.0, obj_type="*"),  # star: no marker -> drop
        ]
        chart = _chart(_StubCatalogs(objs), _solution(0.0, 0.0), fov=5.0)
        result = chart._get_nearby_markers()
        assert {o.object_id for o in result} == {1}

    def test_excludes_objects_outside_radius(self):
        # At fov=5, radius = 5 * 0.75 = 3.75 deg.
        objs = [
            _dso(1, 0.0, 0.0, mag=8.0),  # centre
            _dso(2, 0.0, 3.0, mag=8.0),  # inside 3.75 deg
            _dso(3, 0.0, 10.0, mag=8.0),  # outside
        ]
        chart = _chart(_StubCatalogs(objs), _solution(0.0, 0.0), fov=5.0)
        result = chart._get_nearby_markers()
        assert {o.object_id for o in result} == {1, 2}

    def test_caps_and_keeps_brightest(self):
        # 25 eligible galaxies; cap keeps the brightest NEARBY_MARKER_CAP.
        objs = [
            _dso(i + 1, 0.0, i * 0.05, mag=5.0 + i * 0.1, obj_type="Gx")
            for i in range(25)
        ]
        chart = _chart(_StubCatalogs(objs), _solution(0.0, 0.0), fov=5.0)
        result = chart._get_nearby_markers()
        assert len(result) == NEARBY_MARKER_CAP
        # brightest 20 are object_ids 1..20 (mags 5.0..6.9).
        assert {o.object_id for o in result} == set(range(1, NEARBY_MARKER_CAP + 1))

    def test_index_rebuilds_only_when_filter_dirty(self):
        cats = _StubCatalogs([_dso(1, 0.0, 0.0, mag=8.0)], dirty_time=1.0)
        chart = _chart(cats, _solution(0.0, 0.0), fov=5.0)

        assert {o.object_id for o in chart._get_nearby_markers()} == {1}

        # Swap the underlying set but keep dirty_time -> cached tree, no rebuild.
        cats._objects = [_dso(2, 0.0, 0.0, mag=8.0)]
        assert {o.object_id for o in chart._get_nearby_markers()} == {1}

        # Bump dirty_time -> index rebuilds and reflects the new set.
        cats.catalog_filter.dirty_time = 2.0
        assert {o.object_id for o in chart._get_nearby_markers()} == {2}

    def test_no_catalogs_returns_empty(self):
        chart = _chart(None, _solution(0.0, 0.0), fov=5.0)
        assert chart._get_nearby_markers() == []


@pytest.mark.unit
class TestCollectDsoMarkers:
    def test_dedupes_with_target_obslist_nearby_precedence(self):
        obs = [_dso(2, 0.0, 0.1, mag=8.0, obj_type="Gx")]
        nearby_objs = [
            _dso(1, 0.0, 0.0, mag=8.0, obj_type="Gx"),  # == target -> excluded
            _dso(2, 0.0, 0.1, mag=8.0, obj_type="Gx"),  # dup of obs -> obs wins
            _dso(3, 0.0, 0.2, mag=8.0, obj_type="Gx"),  # nearby only -> kept
        ]
        chart = _chart(
            _StubCatalogs(nearby_objs),
            _solution(0.0, 0.0),
            fov=5.0,
            observing_list=obs,
        )
        marker_list, vertex_objects = chart._collect_dso_markers({1})

        # Exactly objects 2 and 3 (target 1 excluded, dup 2 not doubled).
        assert len(marker_list) == 2
        decs = sorted(round(m[1], 3) for m in marker_list)
        assert decs == [0.1, 0.2]
        assert vertex_objects == []

    def test_observing_list_vertices_collected_nearby_symbols_only(self):
        asterism = _dso(
            5,
            0.0,
            0.1,
            mag=8.0,
            obj_type="Ast",
            size=SizeObject([[0.0, 0.0], [1.0, 1.0]], geometry="polyline"),
        )
        chart = _chart(
            _StubCatalogs([]),  # no nearby objects
            _solution(0.0, 0.0),
            fov=5.0,
            observing_list=[asterism],
        )
        marker_list, vertex_objects = chart._collect_dso_markers(set())

        assert asterism in vertex_objects
        assert len(marker_list) == 1
