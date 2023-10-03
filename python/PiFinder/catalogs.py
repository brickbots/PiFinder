import logging
import time
from typing import List, Dict, DefaultDict, Optional
import numpy as np
import pandas as pd
from collections import defaultdict
from sklearn.neighbors import BallTree

import PiFinder.calc_utils as calc_utils
from PiFinder.db.db import Database
from PiFinder.db.objects_db import ObjectsDatabase
from PiFinder.db.observations_db import ObservationsDatabase
from PiFinder.composite_object import CompositeObject

# collection of all catalog-related classes


class Objects:
    """
    Holds all object_ids and their data.
    Merges object table data and catalog_object table data
    """

    db: Database
    # key:object_id value:all data from an Object table row
    objects: Dict[int, Dict] = {}
    # key:object_id values:list of CompositeObjects pointing to that object_id
    composite_objects: Dict[int, List[CompositeObject]] = {}

    def __init__(self):
        self.db = ObjectsDatabase()
        cat_objects: List[Dict] = [dict(row) for row in self.db.get_catalog_objects()]
        objects = self.db.get_objects()
        self.objects = {row["id"]: dict(row) for row in objects}
        self.composite_objects = self._init_composite_objects(cat_objects)
        # This is used for caching catalog dicts
        # to speed up repeated searches
        self.catalog_dicts = {}
        logging.debug(f"Loaded {len(self.objects)} objects from database")

    def _init_composite_objects(self, catalog_objects: List[Dict]):
        composite_objects = defaultdict(list)

        for catalog_obj in catalog_objects:
            object_id = catalog_obj["object_id"]

            # Merge the two dictionaries
            composite_data = self.objects[object_id] | catalog_obj

            # Assuming you have a CompositeObject class that can be instantiated with the merged dictionary
            composite_instance = CompositeObject(composite_data)

            # Append to the result dictionary
            composite_objects[object_id].append(composite_instance)
        return composite_objects

    def get_catalog_dict(self, catalog_code: str) -> Dict[int, CompositeObject]:
        if self.catalog_dicts.get(catalog_code) == None:
            self.catalog_dicts[catalog_code] = {
                composite_obj.sequence: composite_obj
                for object_list in self.composite_objects.values()
                for composite_obj in object_list
                if composite_obj.catalog_code == catalog_code
            }

        return self.catalog_dicts[catalog_code]

    def get_object_by_catalog_sequence(self, catalog_code: str, sequence: int):
        return self.get_catalog_dict(catalog_code).get(sequence, None)


class Names:
    """
    Holds all name related info
    """

    db: Database
    names: DefaultDict[int, List[str]] = {}

    def __init__(self):
        self.db = ObjectsDatabase()
        self.names = self.db.get_names()
        self._sort_names()
        logging.debug(f"Loaded {len(self.names)} names from database")

    def _sort_names(self):
        """
        sort the names according to some hierarchy
        """
        pass

    def get(self, object_id) -> List[str]:
        return self.names[object_id]


class Catalog:
    """Keeps catalog data + filtered objects"""

    last_filtered: float = 0
    db: Database

    def __init__(self, catalog_code, obj: Objects):
        self.db = ObjectsDatabase()
        self.observations_db = ObservationsDatabase()
        self.name = catalog_code
        self.common_names: Names = Names()
        self.obj = obj
        self.cobjects: Dict[int, CompositeObject] = {}
        self.cobjects_keys_sorted: List[int] = []
        self.filtered_objects: Dict[int, CompositeObject] = {}
        self.filtered_objects_keys_sorted: List[int] = []
        self.max_sequence = 0
        self.desc = "No description"
        self._load_catalog()

    def get_count(self):
        return len(self.cobjects)

    def get_filtered_count(self):
        return len(self.filtered_objects)

    def _load_catalog(self):
        """
        Loads the catalog data, compositing objects and this catalogs extra data

        """
        catalog = self.db.get_catalog_by_code(self.name)
        if catalog:
            self.max_sequence = catalog["max_sequence"]
        else:
            logging.error(f"catalog {self.name} not found")
            return
        self.desc = catalog["desc"]
        self.cobjects = self.obj.get_catalog_dict(self.name)
        self.cobjects_keys_sorted = self._get_sorted_keys(self.cobjects)
        self.filtered_objects = self.cobjects
        self.filtered_objects_keys_sorted = self.cobjects_keys_sorted
        assert (
            self.cobjects_keys_sorted[-1] == self.max_sequence
        ), f"{self.name} max sequence mismatch, {self.cobjects_keys_sorted[-1]} != {self.max_sequence}"
        logging.info(f"loaded {len(self.cobjects)} objects for {self.name}")

    def _get_sorted_keys(self, dictionary):
        return sorted(dictionary.keys())

    def filter(
        self,
        shared_state,
        magnitude_filter,
        type_filter,
        altitude_filter,
        observed_filter,
    ):
        """
        Does filtering based on params
        populates self._filtered_catalog
        from in-memory catalogs
        does not try to maintain current index because it has no notion of that
        should be done in catalog.py
        """
        self.last_filtered = time.time()

        self.filtered_objects = {}

        if observed_filter != "Any":
            # prep observations db cache
            self.observations_db.load_observed_objects_cache()

        fast_aa = None
        if altitude_filter != "None":
            # setup
            solution = shared_state.solution()
            location = shared_state.location()
            dt = shared_state.datetime()
            if location and dt and solution:
                fast_aa = calc_utils.FastAltAz(
                    location["lat"],
                    location["lon"],
                    dt,
                )

        for key, obj in self.cobjects.items():
            # print(f"filtering {obj}")
            include_obj = True

            # try to get object mag to float
            try:
                obj_mag = float(obj.mag)
            except (ValueError, TypeError):
                obj_mag = 99

            if magnitude_filter != "None" and obj_mag >= magnitude_filter:
                include_obj = False

            if type_filter != ["None"] and obj.obj_type not in type_filter:
                include_obj = False

            if fast_aa:
                obj_altitude = fast_aa.radec_to_altaz(
                    obj.ra,
                    obj.dec,
                    alt_only=True,
                )
                if obj_altitude < altitude_filter:
                    include_obj = False

            if observed_filter != "Any":
                observed = self.observations_db.check_logged(obj)
                if observed:
                    if observed_filter == "No":
                        include_obj = False
                else:
                    if observed_filter == "Yes":
                        include_obj = False

            if include_obj:
                self.filtered_objects[key] = obj
        self.filtered_objects_keys_sorted = self._get_sorted_keys(self.filtered_objects)

    def __repr__(self):
        return "catalog repr"
        # return f"Catalog({self.name=}, {self.max_sequence=})"

    def __str__(self):
        return self.__repr__()


class CatalogDesignator:
    """Holds the string that represents the catalog input/search field.
    Usually looks like 'NGC----' or 'M-13'"""

    def __init__(self, catalog_name, max_sequence):
        self.catalog_name = catalog_name
        self.object_number = 0
        self.width = len(str(max_sequence))
        self.field = self.get_designator()

    def set_target(self, catalog_index, number=0):
        assert len(str(number)) <= self.get_catalog_width()
        self.catalog_index = catalog_index
        self.object_number = number
        self.field = self.get_designator()

    def append_number(self, number):
        number_str = str(self.object_number) + str(number)
        if len(number_str) > self.get_catalog_width():
            number_str = number_str[1:]
        self.object_number = int(number_str)
        self.field = self.get_designator()

    def set_number(self, number):
        self.object_number = number
        self.field = self.get_designator()

    def has_number(self):
        return self.object_number > 0

    def reset_number(self):
        self.object_number = 0
        self.field = self.get_designator()

    def increment_number(self):
        self.object_number += 1
        self.field = self.get_designator()

    def decrement_number(self):
        self.object_number -= 1
        self.field = self.get_designator()

    def get_catalog_name(self):
        return self.catalog_name

    def get_catalog_width(self):
        return self.width

    def get_designator(self):
        number_str = str(self.object_number) if self.has_number() else ""
        return (
            f"{self.get_catalog_name(): >3} {number_str:->{self.get_catalog_width()}}"
        )

    def __str__(self):
        return self.field

    def __repr__(self):
        return self.field


class CatalogTracker:
    object_tracker: Dict[str, Optional[int]]
    designator_tracker: Dict[str, Optional[CatalogDesignator]]
    current: Catalog
    current_catalog_name: str

    def __init__(self, catalog_names: List[str], shared_state, config_options):
        self.catalog_names = catalog_names
        self.shared_state = shared_state
        self.config_options = config_options
        self.obj = Objects()
        self.catalogs: Dict[str, Catalog] = self._load_catalogs(catalog_names)
        self.designator_tracker = {
            c: CatalogDesignator(c, self.catalogs[c].max_sequence)
            for c in self.catalog_names
        }
        self.set_current_catalog(catalog_names[0])
        self.object_tracker = {c: None for c in self.catalog_names}

    def set_current_catalog(self, catalog_name):
        assert catalog_name in self.catalogs, f"{catalog_name} not in {self.catalogs}"
        self.current_catalog = self.catalogs[catalog_name]
        self.current_catalog_name = catalog_name

    def next_catalog(self, direction=1):
        current_index = self.catalog_names.index(self.current_catalog_name)
        next_index = (current_index + direction) % len(self.catalog_names)
        self.set_current_catalog(self.catalog_names[next_index])

    def previous_catalog(self):
        self.next_catalog(-1)

    def next_object(self, direction=1, filtered=True):
        """
        direction: 1 for next, -1 for previous

        """
        keys_sorted = (
            self.current_catalog.filtered_objects_keys_sorted
            if filtered
            else self.current_catalog.cobjects_keys_sorted
        )
        current_key = self.object_tracker[self.current_catalog_name]
        designator = self.get_designator()
        # there is no current object, so set the first object the first or last
        if current_key is None or current_key not in keys_sorted:
            next_index = 0 if direction == 1 else len(keys_sorted) - 1
            next_key = keys_sorted[next_index]
            designator.set_number(next_key)

        else:
            current_index = keys_sorted.index(current_key)
            next_index = current_index + direction
            if next_index == -1 or next_index >= len(keys_sorted):
                next_key = None  # hack to get around the fact that 0 is a valid key
                designator.set_number(0)  # todo use -1 in designator as well
            else:
                next_key = keys_sorted[next_index % len(keys_sorted)]
                designator.set_number(next_key)
        self.set_current_object(next_key)
        return self.get_current_object()

    def previous_object(self):
        return self.next_object(-1)

    def get_objects(self, catalogs=None, filtered=False) -> List[Dict]:
        catalog_list = self._select_catalogs(catalogs)
        object_values = []
        for catalog in catalog_list:
            if filtered:
                object_values.extend(catalog.filtered_objects.values())
            else:
                object_values.extend(catalog.cobjects.values())
        flattened_objects = [obj for entry in catalog_list for obj in object_values]
        return flattened_objects

    def does_filtered_have_current_object(self):
        return (
            self.object_tracker[self.current_catalog_name]
            in self.current_catalog.filtered_objects
        )

    def get_current_object(self) -> CompositeObject:
        object_key = self.object_tracker[self.current_catalog_name]
        if object_key is None:
            return None
        return self.current_catalog.cobjects[object_key]

    def set_current_object(self, object_number: int, catalog_name: str = None):
        if catalog_name is not None:
            try:
                self.set_current_catalog(catalog_name)
            except AssertionError:
                # Requested catalog not in tracker!
                # Set to current catalog/zero
                catalog_name = self.current_catalog_name
                self.designator_tracker[catalog_name].set_number(0)
                return
        else:
            catalog_name = self.current_catalog_name
        self.object_tracker[catalog_name] = object_number
        self.designator_tracker[catalog_name].set_number(
            object_number if object_number else 0
        )

    def get_designator(self, catalog_name=None) -> CatalogDesignator:
        catalog_name = self._get_catalog_name(catalog_name)
        return self.designator_tracker[catalog_name]

    def _load_catalogs(self, catalogs: List[str]) -> Dict[str, Catalog]:
        result = {}
        for catalog in catalogs:
            result[catalog] = Catalog(catalog, self.obj)
        return result

    def _get_catalog_name(self, catalog: Optional[str]) -> str:
        catalog: str = catalog or self.current_catalog_name
        return catalog

    def _select_catalog(self, catalog: Optional[str]) -> Catalog:
        catalog = self._get_catalog_name(catalog)
        return self.catalogs.get(catalog)

    def _select_catalogs(self, catalogs: Optional[List[str]]) -> List[Catalog]:
        catalog_list: List[Catalog] = []
        if catalogs is None:
            catalog_list = [self.current_catalog]
        else:
            catalog_list = [self.catalogs.get(key) for key in catalogs]
        return catalog_list

    def filter(self, catalogs=None):
        catalog_list: List[Catalog] = self._select_catalogs(catalogs=catalogs)
        magnitude_filter = self.config_options["Magnitude"]["value"]
        type_filter = self.config_options["Obj Types"]["value"]
        altitude_filter = self.config_options["Alt Limit"]["value"]
        observed_filter = self.config_options["Observed"]["value"]

        for catalog in catalog_list:
            catalog.filter(
                self.shared_state,
                magnitude_filter,
                type_filter,
                altitude_filter,
                observed_filter,
            )
        #  do we need this? might just be hiding a bug somewhere
        if self.current_catalog not in catalog_list:
            self.current_catalog.filter(
                self.shared_state,
                magnitude_filter,
                type_filter,
                altitude_filter,
                observed_filter,
            )

    def get_closest_objects(self, ra, dec, n, catalogs: Optional[List[str]] = None):
        """
        Takes the current catalog or a list of catalogs, gets the filtered
        objects and returns the n closest objects to ra/dec
        """
        catalog_list: List[Catalog] = self._select_catalogs(catalogs=catalogs)
        catalog_list_flat = [
            obj for catalog in catalog_list for obj in catalog.filtered_objects.values()
        ]
        if len(catalog_list_flat) < n:
            n = len(catalog_list_flat)
        object_radecs = [
            [np.deg2rad(x.ra), np.deg2rad(x.dec)] for x in catalog_list_flat
        ]
        objects_bt = BallTree(object_radecs, leaf_size=4, metric="haversine")
        query = [[np.deg2rad(ra), np.deg2rad(dec)]]
        _dist, obj_ind = objects_bt.query(query, k=n)
        results = [catalog_list_flat[x] for x in obj_ind[0]]
        deduplicated = self._deduplicate(results)
        return deduplicated

    def _deduplicate(self, unfiltered_results):
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

    def __repr__(self):
        return f"CatalogTracker(Current:{self.current_catalog_name} {self.object_tracker[self.current_catalog_name]}, Designator:{self.designator_tracker})"
