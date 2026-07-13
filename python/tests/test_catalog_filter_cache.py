"""Tests for the catalog-level filter cache in Catalog.filter_objects().

The cache reuses the previously filtered list while the filter's dirty_time
is unchanged. Its key is really (filter params, object set): any filter
parameter change advances dirty_time, and any object-set mutation
(add_object/add_objects/clear_objects) resets last_filtered — either one
must trigger a real re-filter on the next call.
"""

import pytest

from PiFinder.catalogs import Catalog, CatalogFilter
from PiFinder.composite_object import CompositeObject, MagnitudeObject


class FakeSharedState:
    """Minimal shared state; altaz_ready False skips altitude computation."""

    def location(self):
        return None

    def datetime(self):
        return None

    def altaz_ready(self):
        return False


def _make_obj(seq: int, mag: float = 10.0, logged: bool = False):
    return CompositeObject(
        id=seq,
        object_id=seq,
        ra=10.0 * seq,
        dec=1.0 * seq,
        catalog_code="TST",
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
    # the next dirty_time advance must pick the new state up.
    catalog.catalog_filter.observed = "No"
    assert _sequences(catalog.filter_objects()) == [1, 2, 3]

    catalog.get_objects()[1].logged = True
    catalog.catalog_filter.mark_dirty()
    assert _sequences(catalog.filter_objects()) == [1, 3]
