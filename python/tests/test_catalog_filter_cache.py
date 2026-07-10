"""Tests for the catalog-level filter cache in Catalog.filter_objects().

The cache reuses the previously filtered list while the filter's dirty_time
is unchanged. Its key is really (filter params, object set): any filter
parameter change advances dirty_time, and any object-set mutation
(add_object/add_objects/clear_objects) resets last_filtered — either one
must trigger a real re-filter on the next call.

Freshness triggers layered on top of that contract (ADR 0020):
logging an object (Catalogs.mark_logged) invalidates when an observed
criterion is active, and altitude verdicts go stale as the sky rotates
or when an alt/az fix first arrives (CatalogFilter.is_stale, promoted
to a dirty bump by Catalogs.filter_catalogs).
"""

import datetime
from types import SimpleNamespace
from typing import Optional

import pytest

from PiFinder.catalogs import Catalog, CatalogFilter, Catalogs
from PiFinder.composite_object import CompositeObject, MagnitudeObject


class FakeSharedState:
    """Minimal shared state; altaz_ready False skips altitude computation."""

    def location(self):
        return None

    def datetime(self):
        return None

    def altaz_ready(self):
        return False


class FakeAltAzSharedState:
    """Shared state with a switchable alt/az fix at lat 45N, lon 0.

    At that latitude an object at dec +89 is circumpolar (altitude always
    >= 44 deg) and one at dec -89 never rises (altitude always <= -44 deg),
    so altitude-filter verdicts are independent of RA and time of day.
    """

    def __init__(self, ready: bool = True):
        self.ready = ready

    def location(self):
        return SimpleNamespace(lat=45.0, lon=0.0)

    def datetime(self):
        return datetime.datetime(2026, 7, 9, 3, 0, tzinfo=datetime.timezone.utc)

    def altaz_ready(self):
        return self.ready


def _make_obj(
    seq: int,
    mag: float = 10.0,
    logged: bool = False,
    dec: Optional[float] = None,
    object_id: Optional[int] = None,
    catalog_code: str = "TST",
):
    return CompositeObject(
        id=seq,
        object_id=seq if object_id is None else object_id,
        ra=10.0 * seq,
        dec=1.0 * seq if dec is None else dec,
        catalog_code=catalog_code,
        sequence=seq,
        description=f"obj {seq}",
        mag=MagnitudeObject([mag]),
        logged=logged,
    )


def _sequences(objects):
    return [obj.sequence for obj in objects]


@pytest.fixture
def catalog():
    cat = Catalog("TST", "test catalog")
    cat.catalog_filter = CatalogFilter(shared_state=FakeSharedState())
    for seq in (1, 2, 3):
        cat.add_object(_make_obj(seq, mag=float(seq)))
    return cat


@pytest.mark.unit
def test_unchanged_filter_reuses_cached_list(catalog):
    first = catalog.filter_objects()
    second = catalog.filter_objects()
    assert second is first
    assert _sequences(second) == [1, 2, 3]


@pytest.mark.unit
def test_filter_param_change_triggers_refilter(catalog):
    assert _sequences(catalog.filter_objects()) == [1, 2, 3]
    catalog.catalog_filter.magnitude = 2.5  # setter advances dirty_time
    assert _sequences(catalog.filter_objects()) == [1, 2]


@pytest.mark.unit
def test_add_object_invalidates_cache(catalog):
    assert _sequences(catalog.filter_objects()) == [1, 2, 3]
    catalog.add_object(_make_obj(4))
    assert _sequences(catalog.filter_objects()) == [1, 2, 3, 4]


@pytest.mark.unit
def test_add_objects_after_empty_filter_invalidates_cache():
    # Deferred-load pattern: catalog is filtered while still empty, then
    # the background loader batch-adds its objects.
    cat = Catalog("TST", "test catalog")
    cat.catalog_filter = CatalogFilter(shared_state=FakeSharedState())
    assert cat.filter_objects() == []
    cat.add_objects([_make_obj(1), _make_obj(2)])
    assert _sequences(cat.filter_objects()) == [1, 2]


@pytest.mark.unit
def test_clear_objects_invalidates_cache(catalog):
    # Comet-refresh pattern: objects are cleared, recalculation may fail
    # and never re-add any — the old filtered list must not survive.
    assert _sequences(catalog.filter_objects()) == [1, 2, 3]
    catalog.clear_objects()
    assert catalog.filter_objects() == []
    assert catalog.get_filtered_count() == 0


@pytest.mark.unit
def test_emptied_catalog_never_serves_stale_list(catalog):
    # Even if a clear path bypasses clear_objects() and forgets to
    # invalidate, the empty-catalog check runs before the cache guard,
    # so an empty catalog can never return a stale non-empty list.
    assert _sequences(catalog.filter_objects()) == [1, 2, 3]
    catalog._get_objects().clear()
    assert catalog.filter_objects() == []


@pytest.mark.unit
def test_object_mutation_applied_after_mark_dirty(catalog):
    # Object attributes (like logged) changing does not itself invalidate;
    # the next dirty_time advance must pick the new state up. The sanctioned
    # wrapper pairing the two for logging is Catalogs.mark_logged.
    catalog.catalog_filter.observed = "No"
    assert _sequences(catalog.filter_objects()) == [1, 2, 3]

    catalog.get_objects()[1].logged = True
    catalog.catalog_filter.mark_dirty()
    assert _sequences(catalog.filter_objects()) == [1, 3]


def _make_catalogs(cat: Catalog, shared_state, **filter_kwargs) -> Catalogs:
    catalogs = Catalogs([cat])
    catalogs.set_catalog_filter(
        CatalogFilter(shared_state=shared_state, **filter_kwargs)
    )
    return catalogs


def _age_filter(catalog_filter: CatalogFilter, seconds: float) -> None:
    """Simulate `seconds` of wall clock passing since the last dirty bump."""
    catalog_filter.dirty_time -= seconds


@pytest.mark.unit
def test_mark_logged_drops_object_from_observed_no_list():
    cat = Catalog("TST", "test catalog")
    for seq in (1, 2, 3):
        cat.add_object(_make_obj(seq))
    catalogs = _make_catalogs(cat, FakeSharedState(), observed="No")
    catalogs.filter_catalogs()
    assert _sequences(cat.get_filtered_objects()) == [1, 2, 3]

    catalogs.mark_logged(cat.get_objects()[1])
    catalogs.filter_catalogs()
    assert _sequences(cat.get_filtered_objects()) == [1, 3]


@pytest.mark.unit
def test_mark_logged_appears_in_observed_yes_list():
    cat = Catalog("TST", "test catalog")
    for seq in (1, 2, 3):
        cat.add_object(_make_obj(seq))
    catalogs = _make_catalogs(cat, FakeSharedState(), observed="Yes")
    catalogs.filter_catalogs()
    assert _sequences(cat.get_filtered_objects()) == []

    catalogs.mark_logged(cat.get_objects()[1])
    catalogs.filter_catalogs()
    assert _sequences(cat.get_filtered_objects()) == [2]


@pytest.mark.unit
def test_mark_logged_propagates_to_sibling_listings():
    # M 31 / NGC 224 pattern: one sky object listed in two catalogs.
    # Observed status is a sky-object property, so logging either listing
    # marks both — matching what check_logged derives after a restart.
    cat_m = Catalog("M", "Messier")
    cat_m.add_object(_make_obj(31, object_id=42, catalog_code="M"))
    cat_ngc = Catalog("NGC", "New General Catalog")
    cat_ngc.add_object(_make_obj(224, object_id=42, catalog_code="NGC"))
    cat_ngc.add_object(_make_obj(225, object_id=43, catalog_code="NGC"))
    catalogs = Catalogs([cat_m, cat_ngc])
    catalogs.set_catalog_filter(
        CatalogFilter(shared_state=FakeSharedState(), observed="No")
    )
    catalogs.filter_catalogs()
    assert _sequences(cat_ngc.get_filtered_objects()) == [224, 225]

    catalogs.mark_logged(cat_m.get_objects()[0])
    assert cat_ngc.get_objects()[0].logged is True
    catalogs.filter_catalogs()
    assert _sequences(cat_m.get_filtered_objects()) == []
    assert _sequences(cat_ngc.get_filtered_objects()) == [225]


@pytest.mark.unit
def test_mark_logged_virtual_ids_stay_per_listing():
    # Virtual objects (planets, comets, coordinate objects) carry
    # session-minted negative object_ids — and the CompositeObject
    # default -1 is shared by many. Id-keyed propagation would
    # cross-mark them: logging Mars must not mark Jupiter.
    cat = Catalog("PL", "Planets")
    cat.add_object(_make_obj(1, object_id=-1, catalog_code="PL"))
    cat.add_object(_make_obj(2, object_id=-1, catalog_code="PL"))
    catalogs = _make_catalogs(cat, FakeSharedState(), observed="No")

    catalogs.mark_logged(cat.get_objects()[0])
    assert cat.get_objects()[0].logged is True
    assert cat.get_objects()[1].logged is False


@pytest.mark.unit
def test_mark_logged_without_observed_criterion_keeps_cache():
    # With observed == "Any" no verdict can change, so logging must not
    # cost a re-scan — the cached filtered list survives.
    cat = Catalog("TST", "test catalog")
    for seq in (1, 2, 3):
        cat.add_object(_make_obj(seq))
    catalogs = _make_catalogs(cat, FakeSharedState())
    catalogs.filter_catalogs()
    first = cat.get_filtered_objects()

    catalogs.mark_logged(cat.get_objects()[1])
    assert cat.get_objects()[1].logged is True
    catalogs.filter_catalogs()
    assert cat.get_filtered_objects() is first


@pytest.mark.unit
def test_altitude_verdicts_refresh_after_ttl():
    cat = Catalog("TST", "test catalog")
    cat.add_object(_make_obj(1, dec=89.0))
    cat.add_object(_make_obj(2, dec=-89.0))
    catalogs = _make_catalogs(cat, FakeAltAzSharedState(), altitude=10)
    catalogs.filter_catalogs()
    assert _sequences(cat.get_filtered_objects()) == [1]

    # Within the TTL the cached list is reused
    first = cat.get_filtered_objects()
    catalogs.filter_catalogs()
    assert cat.get_filtered_objects() is first

    # Simulate the sky rotating: the below-horizon object "rises" while
    # the TTL runs out — staleness must force fresh verdicts.
    cat.get_objects()[1].dec = 89.0
    _age_filter(catalogs.catalog_filter, CatalogFilter.ALTITUDE_STALE_SECONDS + 1)
    assert catalogs.catalog_filter.is_dirty()  # refresh paths see staleness
    catalogs.filter_catalogs()
    assert _sequences(cat.get_filtered_objects()) == [1, 2]


@pytest.mark.unit
def test_no_ttl_refilter_without_altitude_criterion():
    # The TTL only applies with an altitude criterion; without one the
    # cached list must survive any amount of elapsed time (PR #526 perf).
    cat = Catalog("TST", "test catalog")
    for seq in (1, 2, 3):
        cat.add_object(_make_obj(seq))
    catalogs = _make_catalogs(cat, FakeAltAzSharedState())
    catalogs.filter_catalogs()
    first = cat.get_filtered_objects()

    _age_filter(catalogs.catalog_filter, CatalogFilter.ALTITUDE_STALE_SECONDS + 1)
    assert not catalogs.catalog_filter.is_stale()
    assert not catalogs.catalog_filter.is_dirty()
    catalogs.filter_catalogs()
    assert cat.get_filtered_objects() is first


@pytest.mark.unit
def test_gps_lock_arrival_applies_altitude_filter():
    # Verdicts computed without an alt/az fix skip the altitude test, so
    # everything passes; the fix arriving must trigger a real re-filter.
    cat = Catalog("TST", "test catalog")
    cat.add_object(_make_obj(1, dec=89.0))
    cat.add_object(_make_obj(2, dec=-89.0))
    shared_state = FakeAltAzSharedState(ready=False)
    catalogs = _make_catalogs(cat, shared_state, altitude=10)
    catalogs.filter_catalogs()
    assert _sequences(cat.get_filtered_objects()) == [1, 2]

    shared_state.ready = True
    assert catalogs.catalog_filter.is_stale()
    catalogs.filter_catalogs()
    assert _sequences(cat.get_filtered_objects()) == [1]
