from PiFinder.catalogs import CompositeObject
from typing import List, Optional
import time
import numpy as np
import logging
from PiFinder.lazy_import import lazy_module
from PiFinder.object_sequence import ObjectSequence

sklearn_neighbors = lazy_module("sklearn.neighbors")

logger = logging.getLogger("Catalog.Nearby")

# Great-circle degrees the pointing may drift before the ranking is stale.
MAX_DEVIATION = 1.0
# Seconds before the ranking is re-run regardless of pointing. This exists to
# pick up catalog/filter changes and altitude drift, not pointing changes --
# the sky turns 15 deg/hour, so a short cadence buys nothing.
MAX_TIME = 10
# The Nearby list is a window onto the closest objects, not a total ordering of
# the catalog. See ADR 0030.
NEAREST_LIST_CAP = 200


def great_circle_degrees(ra_a, dec_a, ra_b, dec_b) -> float:
    """
    Angular separation between two RA/Dec pairs, in degrees. Scalar helper for
    the refresh trigger; the ranking itself uses the BallTree.
    """
    ra_a, dec_a, ra_b, dec_b = np.deg2rad([ra_a, dec_a, ra_b, dec_b])
    cos_sep = np.sin(dec_a) * np.sin(dec_b) + np.cos(dec_a) * np.cos(dec_b) * np.cos(
        ra_a - ra_b
    )
    return float(np.rad2deg(np.arccos(np.clip(cos_sep, -1.0, 1.0))))


class Nearby:
    """Nearby class to calculate and display the closest objects"""

    def __init__(self, shared_state) -> None:
        self.shared_state = shared_state
        self.closest_objects_finder = ClosestObjectsFinder()
        self.last_ra: Optional[float] = None
        self.last_dec: Optional[float] = None
        self.last_refresh = 0.0
        self.result: ObjectSequence = ObjectSequence()

    def set_items(self, items):
        self.closest_objects_finder.calculate_objects_balltree(
            objects=items,
        )

    def has_pointing(self) -> bool:
        solution = self.shared_state.solution()
        return bool(solution and solution.has_pointing())

    def should_refresh(self):
        if not self.closest_objects_finder.is_ready():
            # No index yet -- set_items() has not run for the current list.
            # Ranking now would replace a populated list with an empty one.
            return False
        solution = self.shared_state.solution()
        if not solution or not solution.has_pointing():
            # No solution yet (initial state before first successful solve)
            return False
        if self.last_ra is None or self.last_dec is None:
            return True
        aligned = solution.pointing.aligned.estimate
        ra, dec = aligned.RA, aligned.Dec
        # After first successful solve, RA/Dec are guaranteed to be valid.
        # Compare on the sky: one degree of RA spans cos(dec) degrees, so a
        # per-axis test re-ranks for invisible movement near the poles and
        # fires permanently across the RA 0 wrap.
        deviation = great_circle_degrees(ra, dec, self.last_ra, self.last_dec)
        should = (
            deviation > MAX_DEVIATION or (time.time() - self.last_refresh) > MAX_TIME
        )
        logger.debug(
            "Should refresh? %s, %s deg, %s s",
            should,
            deviation,
            time.time() - self.last_refresh,
        )
        return should

    def refresh(self) -> ObjectSequence:
        solution = self.shared_state.solution()
        if not solution or not solution.has_pointing():
            # No solution yet (initial state before first successful solve)
            return ObjectSequence()
        # After first successful solve, RA/Dec are guaranteed to be valid
        aligned = solution.pointing.aligned.estimate
        ra, dec = aligned.RA, aligned.Dec
        self.last_ra = ra
        self.last_dec = dec
        self.last_refresh = time.time()

        self.result = self.closest_objects_finder.get_closest_objects(
            ra, dec, n=NEAREST_LIST_CAP
        )
        return self.result


class ClosestObjectsFinder:
    def __init__(self):
        self._objects_balltree = None
        self._objects: Optional[ObjectSequence] = None

    def is_ready(self) -> bool:
        """True once an index has been built over a non-empty object set."""
        return self._objects_balltree is not None

    def calculate_objects_balltree(self, objects) -> None:
        """
        Builds the balltree over ``objects`` (a list or an ObjectSequence),
        one entry per sky object (see deduplicate_objects). The tree is built
        from the RA/Dec columns, so no object is made here.

        Rows are ``[dec_rad, ra_rad]``: sklearn's haversine metric reads
        dimension 0 as latitude and dimension 1 as longitude. Feeding it
        ``[ra, dec]`` computes separations on a swapped sphere -- correct only
        between objects sharing a meridian, and increasingly wrong towards the
        poles. See ADR 0030.
        """
        deduplicated_objects = deduplicate_objects(objects)
        if not len(deduplicated_objects):
            self._objects = ObjectSequence()
            self._objects_balltree = None
            return
        object_decras = np.column_stack(
            [
                np.deg2rad(deduplicated_objects.column("dec")),
                np.deg2rad(deduplicated_objects.column("ra")),
            ]
        )
        self._objects = deduplicated_objects
        self._objects_balltree = sklearn_neighbors.BallTree(
            object_decras, leaf_size=20, metric="haversine"
        )

    def get_closest_objects(self, ra, dec, n: int = 0) -> ObjectSequence:
        """
        Returns the n closest objects to ra/dec, nearest first. n=0 ranks the
        whole set -- callers drawing a list should pass a cap instead, since
        the query and everything downstream of it is then O(n) rather than
        O(catalog).
        """

        if self._objects_balltree is None or self._objects is None:
            return ObjectSequence()

        nr_objects = len(self._objects)

        # If n is 0, we want to find all objects
        if n == 0:
            n = nr_objects

        query = [[np.deg2rad(dec), np.deg2rad(ra)]]
        _, obj_ind = self._objects_balltree.query(query, k=min(n, nr_objects))
        return self._objects.take(obj_ind[0])

    def get_objects_within_radius(
        self, ra, dec, radius_deg: float
    ) -> List[CompositeObject]:
        """
        Returns every object within ``radius_deg`` great-circle degrees of
        ra/dec (unordered). Uses the haversine BallTree's ``query_radius``,
        so the radius is converted to radians. Returns ``[]`` when the tree
        is empty. Unlike ``get_closest_objects`` (k-NN), this bounds the
        result by angular distance rather than count -- what the chart needs
        to plot the objects that actually fall inside the current field.

        The query row is ``[dec_rad, ra_rad]`` to match the tree's layout.
        """
        if self._objects_balltree is None or self._objects is None:
            return []
        if len(self._objects) == 0:
            return []

        query = [[np.deg2rad(dec), np.deg2rad(ra)]]
        obj_ind = self._objects_balltree.query_radius(query, r=np.deg2rad(radius_deg))
        return list(self._objects.take(obj_ind[0]))


# Catalog precedence when one sky object has several listings: M first, then
# NGC, then the rest.
_PRECEDENCE = {"M": 2, "NGC": 1}


def deduplicate_objects(unfiltered_objects) -> ObjectSequence:
    """
    One listing per sky object (object_id): the listing of the catalog with
    the highest precedence, and of those the first. The result keeps the
    order in which each sky object first appears.
    """
    objects = ObjectSequence.of(unfiltered_objects)
    if not len(objects):
        return objects
    object_ids = objects.column("object_id")
    codes = objects.column("catalog_code")
    precedence = np.zeros(len(objects), dtype=np.int64)
    for code, rank in _PRECEDENCE.items():
        precedence[codes == code] = rank
    positions = np.arange(len(objects))
    # Sort by object_id, then highest precedence, then earliest position:
    # the first entry of each object_id group is the listing to keep.
    order = np.lexsort((positions, -precedence, object_ids))
    sorted_ids = object_ids[order]
    group_start = np.r_[True, sorted_ids[1:] != sorted_ids[:-1]]
    keep = order[group_start]
    # Both keep and first_seen are in object_id order.
    _, first_seen = np.unique(object_ids, return_index=True)
    return objects.take(keep[np.argsort(first_seen, kind="stable")])
