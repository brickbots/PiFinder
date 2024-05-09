# Code that works on catalogs
from PiFinder.catalogs import Catalogs, Catalog
from PiFinder.composite_object import CompositeObject
from typing import List, Tuple
import numpy as np
from sklearn.neighbors import BallTree


class ClosestObjectsFinder:
    def __init__(self):
        pass

    def calculate_objects_balltree(
        self, ra, dec, catalogs: Catalogs
    ) -> Tuple[List[CompositeObject], Tuple[List[CompositeObject], BallTree]]:
        """
        Calculates a flat list of objects and the balltree for those objects
        """
        catalog_list_flat: List[CompositeObject] = catalogs.get_objects(
            only_selected=True, filtered=True
        )
        object_radecs = [
            [np.deg2rad(x.ra), np.deg2rad(x.dec)] for x in catalog_list_flat
        ]
        objects_bt = BallTree(object_radecs, leaf_size=20, metric="haversine")
        return (catalog_list_flat, objects_bt)

    def get_closest_objects(
        self, ra, dec, n, cache: Tuple[List[CompositeObject], BallTree]
    ) -> List[CompositeObject]:
        """
        Takes the current catalog or a list of catalogs, gets the filtered
        objects and returns the n closest objects to ra/dec
        """
        catalog_list_flat, balltree = cache
        query = [[np.deg2rad(ra), np.deg2rad(dec)]]
        _, obj_ind = balltree.query(query, k=min(n, len(catalog_list_flat)))
        results = [catalog_list_flat[x] for x in obj_ind[0]]
        deduplicated = self._deduplicate(results)
        return deduplicated

    def _deduplicate(self, unfiltered_results):
        """
        Make sure no duplicates are in the balltree results.
        objects with the same object_id are considered duplicates.
        If there are duplicates, the one with the higher precedence catalog_code
        is kept.
        """
        deduplicated_results = []
        seen_ids = set()

        for obj in unfiltered_results:
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
