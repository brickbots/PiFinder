# Code that works on catalogs
from PiFinder.composite_object import CompositeObject
from typing import List
import numpy as np
from sklearn.neighbors import BallTree


def deduplicate_objects(unfiltered_objects: list[CompositeObject]) -> list[CompositeObject]:
    print(f"Before deduplication: {len(unfiltered_objects)}, {unfiltered_objects}")
    deduplicated_dict = {}

    precedence = {"M": 2, "NGC": 1}

    for obj in unfiltered_objects:
        if obj.object_id not in deduplicated_dict:
            deduplicated_dict[obj.object_id] = obj
        else:
            existing_obj = deduplicated_dict[obj.object_id]
            existing_precedence = precedence.get(existing_obj.catalog_code, 0)
            new_precedence = precedence.get(obj.catalog_code, 0)
            if new_precedence > existing_precedence:
                deduplicated_dict[obj.object_id] = obj

    results = list(deduplicated_dict.values())
    print(f"After deduplication: {len(results)}, {results}")
    return results


class ClosestObjectsFinder:
    def __init__(self):
        self._objects_balltree = None
        self._objects = None

    def calculate_objects_balltree(self, objects: list[CompositeObject]) -> None:
        """
        Calculates a flat list of objects and the balltree for those objects
        """
        deduplicated_objects = deduplicate_objects(objects)
        object_radecs = np.array([[np.deg2rad(x.ra), np.deg2rad(x.dec)] for x in deduplicated_objects])
        self._objects = np.array(deduplicated_objects)
        self._objects_balltree = BallTree(
            object_radecs, leaf_size=20, metric="haversine"
        )

    def get_closest_objects(self, ra, dec, n: int = 0) -> List[CompositeObject]:
        """
        Takes the current catalog or a list of catalogs, gets the filtered
        objects and returns the n closest objects to ra/dec
        """

        if self._objects_balltree is None:
            return []

        nr_objects = len(self._objects)

        if n == 0:
            n = nr_objects

        query = [[np.deg2rad(ra), np.deg2rad(dec)]]
        print(f"Query: {query}, objects: {self._objects}")
        _, obj_ind = self._objects_balltree.query(query, k=min(n, nr_objects))
        print(f"Found {len(obj_ind)} objects, from {nr_objects} objects, k={min(n, nr_objects)}")
        results = self._objects[obj_ind[0]]
        print(f"Found {len(results)} objects, from {nr_objects} objects, n={n}")
        return results
