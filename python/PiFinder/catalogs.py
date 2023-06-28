import logging
import sqlite3
import time
import numpy as np
import pandas as pd
from typing import List, Dict, Optional
from PiFinder import calc_utils
import PiFinder.utils as utils
from PiFinder import obslog
from sklearn.neighbors import BallTree

# collection of all catalog-related classes


class Catalog:
    """Keeps catalog data + keeps track of current catalog/object"""

    last_filtered: float = 0

    def __init__(self, catalog_name):
        self.name = catalog_name
        self.objects = {}
        self.objects_keys_sorted = []
        self.filtered_objects = {}
        self.filtered_objects_keys_sorted = []
        self.max_sequence = 0
        self.desc = "No description"
        self._load_catalog()

    def get_count(self):
        return len(self.objects)

    def get_filtered_count(self):
        return len(self.filtered_objects)

    def _load_catalog(self):
        """
        Loads all catalogs into memory

        """
        self.conn = sqlite3.connect(utils.pifinder_db)
        self.conn.row_factory = sqlite3.Row
        cat_objects = self.conn.execute(
            f"""
            SELECT * from objects
            where catalog='{self.name}'
            order by sequence
        """
        ).fetchall()
        cat_data = self.conn.execute(
            f"""
                SELECT * from catalogs
                where catalog='{self.name}'
            """
        ).fetchone()
        print(cat_data)
        if cat_data:
            self.max_sequence = cat_data["max_sequence"]
            self.desc = cat_data["desc"]
        else:
            logging.debug(f"no catalog data for {self.name}")
        self.objects = {dict(row)["sequence"]: dict(row) for row in cat_objects}
        self.objects_keys_sorted = self._get_sorted_keys(self.objects)
        assert (
            self.objects_keys_sorted[-1] == self.max_sequence
        ), f"{self.name} max sequence mismatch"
        logging.info(f"loaded {len(self.objects)} objects for {self.name}")
        self.conn.close()

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

        if observed_filter != "Any":
            # setup
            observed_list = obslog.get_observed_objects()

        for key, obj in self.objects.items():
            # print(f"filtering {obj}")
            include_obj = True

            # try to get object mag to float
            try:
                obj_mag = float(obj["mag"])
            except (ValueError, TypeError):
                obj_mag = 99

            if magnitude_filter != "None" and obj_mag >= magnitude_filter:
                include_obj = False

            if type_filter != ["None"] and obj["obj_type"] not in type_filter:
                include_obj = False

            if fast_aa:
                obj_altitude = fast_aa.radec_to_altaz(
                    obj["ra"],
                    obj["dec"],
                    alt_only=True,
                )
                if obj_altitude < altitude_filter:
                    include_obj = False

            if observed_filter != "Any":
                if (obj["catalog"], obj["sequence"]) in observed_list:
                    if observed_filter == "No":
                        include_obj = False
                else:
                    if observed_filter == "Yes":
                        include_obj = False

            if include_obj:
                self.filtered_objects[key] = obj
        self.filtered_objects_keys_sorted = self._get_sorted_keys(self.filtered_objects)


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
        self.catalogs: Dict[str, Catalog] = self._load_catalogs(catalog_names)
        self.designator_tracker = {
            c: CatalogDesignator(c, self.catalogs[c].max_sequence)
            for c in self.catalog_names
        }
        self.set_current_catalog(catalog_names[0])
        self.object_tracker = {c: None for c in self.catalog_names}

    def set_current_catalog(self, catalog_name):
        assert catalog_name in self.catalogs
        self.current = self.catalogs[catalog_name]
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
            self.current.filtered_objects_keys_sorted
            if filtered
            else self.current.objects_keys_sorted
        )
        current_key = self.object_tracker[self.current_catalog_name]
        designator = self.get_designator()
        # there is no current object, so set the first object the first or last
        if current_key is None:
            next_index = 0 if direction == 1 else len(keys_sorted) - 1
            next_key = keys_sorted[next_index]
            designator.set_number(next_key)

        else:
            current_index = keys_sorted.index(current_key)
            next_index = current_index + direction
            if next_index == -1:
                next_key = None  # hack to get around the fact that 0 is a valid key
                designator.set_number(0)  # todo use -1 in designator as well
            else:
                next_key = keys_sorted[next_index % len(keys_sorted)]
                designator.set_number(next_key)
        self.set_current_object(next_key)
        return self.get_current_object()

    def previous_object(self):
        return self.next_object(-1)

    def get_objects(self, catalogs=None):
        catalog_list = self._select_catalogs(catalogs)
        return [catalog.objects for catalog in catalog_list]

    def does_filtered_have_current_object(self):
        return (
            self.object_tracker[self.current_catalog_name]
            in self.current.filtered_objects
        )

    def get_current_object(self):
        object_key = self.object_tracker[self.current_catalog_name]
        if object_key is None:
            return None
        return self.current.objects[object_key]

    def set_current_object(self, object_number, catalog_name=None):
        catalog_name = self._get_catalog_name(catalog_name)
        self.current_catalog_name = catalog_name
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
            result[catalog] = Catalog(catalog)
        return result

    def _get_catalog_name(self, catalog: Optional[str]) -> str:
        catalog = catalog or self.current_catalog_name
        return catalog

    def _select_catalog(self, catalog: Optional[str]) -> Catalog:
        catalog = self._get_catalog_name(catalog)
        return self.catalogs.get(catalog)

    def _select_catalogs(self, catalogs: Optional[List[str]]) -> List[Catalog]:
        if catalogs is None:
            catalog_list = [self.current]
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
        if self.current not in catalog_list:
            self.current.filter(
                self.shared_state,
                magnitude_filter,
                type_filter,
                altitude_filter,
                observed_filter,
            )

    def get_closest_objects(self, ra, dec, n, catalogs=None):
        """
        Takes the current catalog or a list of catalogs, gets the filtered
        objects and returns the n closest objects to ra/dec
        """
        catalog_list: List[Catalog] = self._select_catalogs(catalogs=catalogs)
        catalog_list_flat = [x for y in catalog_list for x in y.filtered_objects]
        object_ras = [np.deg2rad(x["ra"]) for x in catalog_list_flat]
        object_decs = [np.deg2rad(x["dec"]) for x in catalog_list_flat]

        objects_df = pd.DataFrame(
            {
                "ra": object_ras,
                "dec": object_decs,
            }
        )
        objects_bt = BallTree(
            objects_df[["ra", "dec"]], leaf_size=4, metric="haversine"
        )

        query_df = pd.DataFrame({"ra": [np.deg2rad(ra)], "dec": [np.deg2rad(dec)]})
        _dist, obj_ind = objects_bt.query(query_df, k=n)
        return [catalog_list_flat[x] for x in obj_ind[0]]

    def __repr__(self):
        return f"CatalogTracker(Current:{self.current_catalog_name} {self.object_tracker[self.current_catalog_name]}, Designator:{self.designator_tracker})"
