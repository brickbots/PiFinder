# Code that works on catalogs
from PiFinder.composite_object import CompositeObject
from typing import List
import numpy as np
from sklearn.neighbors import BallTree


def deduplicate_objects(
    unfiltered_objects: list[CompositeObject],
) -> list[CompositeObject]:
    """
    Make sure no duplicates are in the provided object list
    objects with the same object_id are considered duplicates.
    If there are duplicates, the one with the higher precedence catalog_code
    is kept.
    """
    deduplicated_results = []
    seen_ids = set()

    for obj in unfiltered_objects:
        if obj.object_id not in seen_ids:
            seen_ids.add(obj.object_id)
            deduplicated_results.append(obj)
        else:
            # If the object_id is already seen, we look at the catalog_code
            # and replace the existing object if the new object has a higher precedence catalog_code
            existing_obj_index = next(
                i
                for i, existing_obj in enumerate(deduplicated_results)
                if existing_obj.object_id == obj.object_id
            )
            existing_obj = deduplicated_results[existing_obj_index]

            if (obj.catalog_code == "M" and existing_obj.catalog_code != "M") or (
                obj.catalog_code == "NGC"
                and existing_obj.catalog_code not in ["M", "NGC"]
            ):
                deduplicated_results[existing_obj_index] = obj

    return deduplicated_results


class ClosestObjectsFinder:
    def __init__(self):
        self._objects_balltree = None
        self._objects = None
        pass

    def calculate_objects_balltree(self, objects: list[CompositeObject]) -> None:
        """
        Calculates a flat list of objects and the balltree for those objects
        """
        object_radecs = [[np.deg2rad(x.ra), np.deg2rad(x.dec)] for x in objects]
        self._objects = objects
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

        if n == 0:
            n = len(self._objects)

        query = [[np.deg2rad(ra), np.deg2rad(dec)]]
        _, obj_ind = self._objects_balltree.query(query, k=min(n, len(self._objects)))
        results = [self._objects[x] for x in obj_ind[0]]
        deduplicated = deduplicate_objects(results)
        return deduplicated
