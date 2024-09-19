from PiFinder.catalogs import CompositeObject
from typing import List
import time
import numpy as np
from sklearn.neighbors import BallTree
import logging

logger = logging.getLogger("Catalog.Nearby")
MAX_DEVIATION = 1.0
MAX_TIME = 2


class Nearby:
    """Nearby class to calcluate and display the closest objects"""

    def __init__(self, shared_state) -> None:
        self.shared_state = shared_state
        self.closest_objects_finder = ClosestObjectsFinder()
        self.last_ra = 0
        self.last_dec = 0
        self.last_refresh = 0

    def set_items(self, items: list[CompositeObject]):
        self.closest_objects_finder.calculate_objects_balltree(
            objects=items,
        )

    def should_refresh(self):
        if not self.shared_state.solution():
            return False
        ra, dec = (
            self.shared_state.solution()["RA"],
            self.shared_state.solution()["Dec"],
        )
        should = (
            abs(ra - self.last_ra) > MAX_DEVIATION
            or abs(dec - self.last_dec) > MAX_DEVIATION
            or (time.time() - self.last_refresh) > MAX_TIME
        )
        logger.debug(
            "Should refresh? %s, %s, %s, %s",
            should,
            ra - self.last_ra,
            dec - self.last_dec,
            time.time() - self.last_refresh,
        )
        return should

    def refresh(self):
        if not self.shared_state.solution():
            return None
        else:
            # with Timer("Nearby.refresh"):
            ra, dec = (
                self.shared_state.solution()["RA"],
                self.shared_state.solution()["Dec"],
            )
            self.last_ra = ra
            self.last_dec = dec
            self.last_refresh = time.time()

            self.result = self.closest_objects_finder.get_closest_objects(ra, dec)
            return self.result


class ClosestObjectsFinder:
    def __init__(self):
        self._objects_balltree = None
        self._objects = None

    def calculate_objects_balltree(self, objects: list[CompositeObject]) -> None:
        """
        Calculates a flat list of objects and the balltree for those objects
        """
        deduplicated_objects = deduplicate_objects(objects)
        object_radecs = np.array(
            [[np.deg2rad(x.ra), np.deg2rad(x.dec)] for x in deduplicated_objects]
        )
        self._objects = np.array(deduplicated_objects)
        self._objects_balltree = BallTree(
            object_radecs, leaf_size=20, metric="haversine"
        )

    def get_closest_objects(self, ra, dec, n: int = 0) -> List[CompositeObject]:
        """
        Takes the current catalog or a list of catalogs, gets the filtered
        objects and returns the n closest objects to ra/dec
        """

        if self._objects_balltree is None or self._objects is None:
            return []

        nr_objects = len(self._objects)

        # If n is 0, we want to find all objects
        if n == 0:
            n = nr_objects

        query = [[np.deg2rad(ra), np.deg2rad(dec)]]
        # logger.debug("Query: %s, objects: %s", query, self._objects)
        _, obj_ind = self._objects_balltree.query(query, k=min(n, nr_objects))
        # logger.debug("Found %i objects, from %i objects, k=%i", len(obj_ind), nr_objects, min(n, nr_objects))
        results = self._objects[obj_ind[0]]
        # logger.debug("Found %i objects, from %i objects, n=%i", len(results), nr_objects, n)
        return results


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
