from PiFinder.catalogs import CompositeObject
from typing import List, Optional, Sequence
import time
import numpy as np
import logging

logger = logging.getLogger("Catalog.Nearby")

# Great-circle degrees the pointing may drift before the ranking is stale.
MAX_DEVIATION = 1.0
# Seconds before the ranking is re-run regardless of pointing. This exists to
# pick up catalog/filter changes and altitude drift, not pointing changes --
# the sky turns 15 deg/hour, so a short cadence buys nothing.
MAX_TIME = 10
# The Nearby list is a window onto the closest objects, not a total ordering of
# the catalog. See ADR 0029.
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
        self.result: Sequence[CompositeObject] = []

    def set_items(self, items: list[CompositeObject]):
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

    def refresh(self):
        solution = self.shared_state.solution()
        if not solution or not solution.has_pointing():
            # No solution yet (initial state before first successful solve)
            return []
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
        self._objects = None

    def is_ready(self) -> bool:
        """True once an index has been built over a non-empty object set."""
        return self._objects_balltree is not None

    def calculate_objects_balltree(self, objects: list[CompositeObject]) -> None:
        """
        Calculates a flat list of objects and the balltree for those objects.

        Rows are ``[dec_rad, ra_rad]``: sklearn's haversine metric reads
        dimension 0 as latitude and dimension 1 as longitude. Feeding it
        ``[ra, dec]`` computes separations on a swapped sphere -- correct only
        between objects sharing a meridian, and increasingly wrong towards the
        poles. See ADR 0029.
        """
        deduplicated_objects = deduplicate_objects(objects)
        if not deduplicated_objects:
            self._objects = np.array([])
            self._objects_balltree = None
            return
        object_decras = np.array(
            [[np.deg2rad(x.dec), np.deg2rad(x.ra)] for x in deduplicated_objects]
        )
        from sklearn.neighbors import BallTree

        self._objects = np.array(deduplicated_objects)
        self._objects_balltree = BallTree(
            object_decras, leaf_size=20, metric="haversine"
        )

    def get_closest_objects(self, ra, dec, n: int = 0) -> Sequence[CompositeObject]:
        """
        Returns the n closest objects to ra/dec, nearest first. n=0 ranks the
        whole set -- callers drawing a list should pass a cap instead, since
        the query and everything downstream of it is then O(n) rather than
        O(catalog).
        """

        if self._objects_balltree is None or self._objects is None:
            return []

        nr_objects = len(self._objects)

        # If n is 0, we want to find all objects
        if n == 0:
            n = nr_objects

        query = [[np.deg2rad(dec), np.deg2rad(ra)]]
        _, obj_ind = self._objects_balltree.query(query, k=min(n, nr_objects))
        return self._objects[obj_ind[0]]

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
        return list(self._objects[obj_ind[0]])


def deduplicate_objects(
    unfiltered_objects: list[CompositeObject],
) -> list[CompositeObject]:
    deduplicated_dict = {}

    # Define precedence for catalog codes
    # M (Messier) objects have highest precedence, followed by NGC objects
    precedence = {"M": 2, "NGC": 1}

    for obj in unfiltered_objects:
        if obj.object_id not in deduplicated_dict:
            # If the object ID is not in the dictionary, add it
            deduplicated_dict[obj.object_id] = obj
        else:
            # If the object ID already exists, get it
            existing_obj = deduplicated_dict[obj.object_id]
            # Get precedence for existing object, default to 0 if not in precedence dict
            existing_precedence = precedence.get(existing_obj.catalog_code, 0)
            # Get precedence for new object, default to 0 if not in precedence dict
            new_precedence = precedence.get(obj.catalog_code, 0)
            # Replace existing object if new object has higher precedence
            if new_precedence > existing_precedence:
                deduplicated_dict[obj.object_id] = obj
    results = list(deduplicated_dict.values())
    return results
