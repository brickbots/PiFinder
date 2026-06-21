"""
Regression tests for VirtualIDManager.

Every virtual object_id must be unique across both id paths: the bulk-assign
path used by the planet/comet catalogs and the single-mint path used for
observing-list coordinate objects. They previously used separate counters that
both started at 0, so coordinate objects collided with planets/comets.
"""

import pytest

from PiFinder.catalog_base import VirtualIDManager
from PiFinder.composite_object import CompositeObject


class _FakeCatalog:
    def __init__(self, objects):
        self._objects = objects

    def get_objects(self):
        return self._objects


@pytest.mark.unit
def test_assign_and_mint_share_one_counter():
    planets = [CompositeObject(object_id=0) for _ in range(3)]
    comets = [CompositeObject(object_id=0) for _ in range(2)]

    VirtualIDManager.mint_ids(_FakeCatalog(planets))
    VirtualIDManager.mint_ids(_FakeCatalog(comets))
    minted = [VirtualIDManager.mint_id() for _ in range(3)]

    all_ids = [p.object_id for p in planets] + [c.object_id for c in comets] + minted
    assert len(all_ids) == len(set(all_ids))  # no collisions across the paths
    assert all(i < 0 for i in all_ids)  # virtual ids are negative


@pytest.mark.unit
def test_minted_objects_are_distinct():
    a = CompositeObject(object_id=VirtualIDManager.mint_id())
    b = CompositeObject(object_id=VirtualIDManager.mint_id())
    assert a != b
    assert hash(a) != hash(b)
