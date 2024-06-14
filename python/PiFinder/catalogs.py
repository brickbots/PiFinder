# mypy: ignore-errors
import logging
import time
import datetime
import pytz
from pprint import pformat

from typing import List, Dict, DefaultDict, Optional
from collections import defaultdict
import PiFinder.calc_utils as calc_utils
from PiFinder.db.db import Database
from PiFinder.db.objects_db import ObjectsDatabase
from PiFinder.db.observations_db import ObservationsDatabase
from PiFinder.composite_object import CompositeObject
from PiFinder.calc_utils import sf_utils

# collection of all catalog-related classes

# CatalogBase : just the CompositeObjects
# Catalog: extends the CatalogBase with filtering
# CatalogIterator: TODO iterates over the composite_objects
# CatalogFilter: can be set on catalog to filter
# CatalogBuilder: builds catalogs from the database
# Catalogs: holds all catalogs


class ROArrayWrapper:
    """Read-only array wrapper, to protect the underlying array"""

    def __init__(self, composite_object_array):
        self._array = composite_object_array

    def __getitem__(self, key):
        return self._array[key]

    def __len__(self):
        return len(self._array)

    def __setitem__(self, key, value):
        raise TypeError("This array is read-only")

    def __delitem__(self, key):
        raise TypeError("This array is read-only")

    def __iter__(self):
        return iter(self._array)

    def __repr__(self):
        return str(self._array)


class Names:
    """
    Holds all name related info
    """

    db: Database
    names: DefaultDict[int, List[str]] = defaultdict(list)

    def __init__(self):
        self.db = ObjectsDatabase()
        self.id_to_names = self.db.get_object_id_to_names()
        self.name_to_id = self.db.get_name_to_object_id()
        self._sort_names()
        logging.debug(f"Loaded {len(self.names)} names from database")

    def _sort_names(self):
        """
        sort the names according to some hierarchy
        """
        pass

    def get_name(self, object_id: int) -> List[str]:
        return self.id_to_names[object_id]

    def get_id(self, name: str) -> Optional[int]:
        return self.name_to_id.get(name)


class CatalogFilter:
    """can be set on catalog to filter"""

    fast_aa = None

    def __init__(
        self,
        magnitude_filter=None,
        type_filter=None,
        altitude_filter=None,
        observed_filter=None,
        shared_state=None,
    ):
        self.shared_state = shared_state
        # When was the last time filter params were changed?
        self.dirty_time = time.time()
        self.set_values(magnitude_filter, type_filter, altitude_filter, observed_filter)

    def set_values(
        self, magnitude_filter, type_filter, altitude_filter, observed_filter
    ):
        self.magnitude_filter = magnitude_filter
        self.type_filter = type_filter
        self.altitude_filter = altitude_filter
        self.observed_filter = observed_filter
        self.dirty_time = time.time()

    def calc_fast_aa(self, shared_state):
        solution = shared_state.solution()
        location = shared_state.location()
        dt = shared_state.datetime()
        if location and dt and solution:
            self.fast_aa = calc_utils.FastAltAz(
                location["lat"],
                location["lon"],
                dt,
            )
        else:
            logging.warning(
                f"Calc_fast_aa: {'solution' if not solution else 'location' if not location else 'datetime' if not dt else 'nothing'} not set"
            )

    def apply_filter(self, obj: CompositeObject):
        if obj.last_filtered_time > self.dirty_time:
            return obj.last_filtered_result

        # check altitude
        if self.altitude_filter is not None and self.fast_aa:
            obj_altitude, _ = self.fast_aa.radec_to_altaz(
                obj.ra,
                obj.dec,
                alt_only=True,
            )
            if obj_altitude < self.altitude_filter:
                obj.last_filtered_result = False
                return False

        # check magnitude
        # first try to get object mag to float
        try:
            obj_mag = float(obj.mag)
        except (ValueError, TypeError):
            obj_mag = 99

        if self.magnitude_filter is not None and obj_mag >= self.magnitude_filter:
            obj.last_filtered_result = False
            return False

        # check type
        if self.type_filter is not None and obj.obj_type not in self.type_filter:
            obj.last_filtered_result = False
            return False

        # check observed
        if self.observed_filter != "Any" and self.observed_filter is not None:
            obj.last_filtered_result = (self.observed_filter == "Yes") == obj.logged
            return obj.last_filtered_result

        # object passed all the tests
        obj.last_filtered_result = True
        return True

    def apply(self, objects: List[CompositeObject]):
        self.calc_fast_aa(self.shared_state)
        return [obj for obj in objects if self.apply_filter(obj)]


def catalog_base_id_sort(obj: CompositeObject):
    return obj.id


def catalog_base_sequence_sort(obj: CompositeObject):
    return obj.sequence


class CatalogBase:
    """Base class for Catalog, contains only the objects"""

    def __init__(
        self,
        catalog_code: str,
        max_sequence: int,
        desc: str,
        sort=catalog_base_sequence_sort,
    ):
        self.catalog_code = catalog_code
        self.max_sequence = max_sequence
        self.desc = desc
        self.sort = sort
        self.__objects: List[CompositeObject] = []
        self.id_to_pos: Dict[int, int]
        self.sequence_to_pos: Dict[int, int]
        self.catalog_code: str
        self.max_sequence: int
        self.desc: str
        self.sort = sort

    def get_objects(self) -> ROArrayWrapper:
        return ROArrayWrapper(self.__objects)

    def add_object(self, obj: CompositeObject):
        self._add_object(obj)
        self._sort_objects()
        self._update_id_to_pos()
        self._update_sequence_to_pos()
        assert self.check_sequences()

    def _add_object(self, obj: CompositeObject):
        self.__objects.append(obj)

    def add_objects(self, objects: List[CompositeObject]):
        objects_copy = objects.copy()
        for obj in objects_copy:
            self._add_object(obj)
        self._sort_objects()
        self._update_id_to_pos()
        self._update_sequence_to_pos()
        assert self.check_sequences()

    def _sort_objects(self):
        self.__objects.sort(key=self.sort)

    def get_object_by_id(self, id: int) -> CompositeObject:
        if id in self.id_to_pos:
            return self.__objects[self.id_to_pos[id]]
        else:
            return None

    def get_object_by_sequence(self, sequence: int) -> CompositeObject:
        if sequence in self.sequence_to_pos:
            return self.__objects[self.sequence_to_pos[sequence]]
        else:
            return None

    def get_count(self) -> int:
        return len(self.__objects)

    def check_sequences(self):
        sequences = [x.sequence for x in self.get_objects()]
        if not len(sequences) == len(set(sequences)):
            logging.error(f"Duplicate sequence catalog {self.catalog_code}!")
            return False
        return True

    def _update_id_to_pos(self):
        self.id_to_pos = {obj.id: i for i, obj in enumerate(self.__objects)}

    def _update_sequence_to_pos(self):
        self.sequence_to_pos = {obj.sequence: i for i, obj in enumerate(self.__objects)}

    def __repr__(self):
        return f"Catalog({self.catalog_code=}, {self.max_sequence=}, count={self.get_count()})"

    def __str__(self):
        return self.__repr__()


class Catalog(CatalogBase):
    """Extends the CatalogBase with filtering"""

    def __init__(self, catalog_code: str, max_sequence: int, desc: str):
        super().__init__(catalog_code, max_sequence, desc)
        self.catalog_filter: CatalogFilter = CatalogFilter()
        self.filtered_objects: List[CompositeObject] = self.get_objects()
        self.filtered_objects_seq: List[int] = self._filtered_objects_to_seq()
        self.last_filtered = 0
        self.is_selected = True

    def has(self, sequence: int, filtered=True):
        return sequence in self.filtered_objects_seq

    def _filtered_objects_to_seq(self):
        return [obj.sequence for obj in self.filtered_objects]

    def filter_objects(self) -> List[CompositeObject]:
        self.filtered_objects = self.catalog_filter.apply(self.get_objects())
        self.filtered_objects_seq = self._filtered_objects_to_seq()
        self.last_filtered = time.time()
        return self.filtered_objects

    def get_filtered_objects(self):
        return self.filtered_objects

    def get_filtered_count(self):
        return len(self.filtered_objects)

    def __repr__(self):
        super().__repr__()
        return f"{super().__repr__()} - filtered={self.get_filtered_count()})"

    def __str__(self):
        return self.__repr__()


class Catalogs:
    """Holds all catalogs"""

    def __init__(self, catalogs: List[Catalog]):
        self.__catalogs: List[Catalog] = catalogs
        self._select_all_catalogs()
        self.catalog_filter: CatalogFilter = CatalogFilter()

    def filter_catalogs(self):
        """
        Applies filter to all catalogs
        """
        for catalog in self.__catalogs:
            catalog.filter_objects()

    def set_catalog_filter(self, catalog_filter: CatalogFilter) -> None:
        """
        Sets the catalog filter object for all the catalogs
        to a single shared filter object so they can all
        be changed at once
        """
        self._filter = catalog_filter
        for catalog in self.__catalogs:
            catalog.catalog_filter = catalog_filter

    def get_catalogs(self, only_selected: bool = True) -> List[Catalog]:
        return_list = []
        for catalog in self.__catalogs:
            if (only_selected and catalog.is_selected) or not only_selected:
                return_list.append(catalog)

        return return_list

    def get_objects(
        self, only_selected: bool = True, filtered: bool = True
    ) -> List[CompositeObject]:
        return_list = []
        for catalog in self.__catalogs:
            if (only_selected and catalog.is_selected) or not only_selected:
                if filtered:
                    return_list += catalog.get_filtered_objects()
                else:
                    return_list += catalog.get_objects()
        return return_list

    def select_catalogs(self, catalog_codes: List[str]):
        for catalog in self.__catalogs:
            if catalog.catalog_code in catalog_codes:
                catalog.is_selected = True

    def has_code(self, catalog_code: str, only_selected: bool = True) -> bool:
        return catalog_code in self.get_codes(only_selected)

    def has(self, catalog: Catalog, only_selected: bool = True) -> bool:
        return self.has_code(catalog.catalog_code, only_selected)

    def get_object(self, catalog_code: str, sequence: int) -> Optional[CompositeObject]:
        catalog = self.get_catalog_by_code(catalog_code)
        if catalog:
            return catalog.get_object_by_sequence(sequence)

    def set(self, catalogs: List[Catalog]):
        self.__catalogs = catalogs
        self._select_all_catalogs()

    def add(self, catalog: Catalog, select: bool = False):
        if catalog.catalog_code not in [x.catalog_code for x in self.__catalogs]:
            if select:
                catalog.is_selected = True
            self.__catalogs.append(catalog)
        else:
            logging.warning(f"Catalog {catalog.catalog_code} already exists")

    def remove(self, catalog_code: str):
        for catalog in self.__catalogs:
            if catalog.catalog_code == catalog_code:
                self.__catalogs.remove(catalog)
                return

        logging.warning(f"Catalog {catalog_code} does not exist")

    def get_codes(self, only_selected: bool = True) -> List[str]:
        return_list = []
        for catalog in self.__catalogs:
            if (only_selected and catalog.is_selected) or not only_selected:
                return_list.append(catalog.catalog_code)

        return return_list

    def get_catalog_by_code(self, catalog_code: str) -> Optional[Catalog]:
        for catalog in self.__catalogs:
            if catalog.catalog_code == catalog_code:
                return catalog

            return None

    def count(self) -> int:
        return len(self.get_catalogs())

    def _select_all_catalogs(self):
        for catalog in self.__catalogs:
            catalog.is_selected = True

    def __repr__(self):
        return f"Catalogs(\n{pformat(self.get_catalogs(only_selected=False))})"

    def __str__(self):
        return self.__repr__()

    def __iter__(self):
        return iter(self.get_catalogs())


# class CatalogIterator:
#     def __init__(self, catalogs_instance):
#         self.catalogs_instance = catalogs_instance
#         self.index = 0
#         self.direction = 1  # 1 for forward, -1 for backward

#     def next(self):
#         catalogs = self.catalogs_instance.get_catalogs()
#         if catalogs:
#             self.index += self.direction

#             if self.index < 0:
#                 self.index = len(catalogs) - 1
#             elif self.index >= len(catalogs):
#                 self.index = 0

#             return catalogs[self.index]
#         else:
#             return None

#     def previous(self):
#         catalogs = self.catalogs_instance.get_catalogs()
#         if catalogs:
#             self.index -= self.direction

#             if self.index < 0:
#                 self.index = len(catalogs) - 1
#             elif self.index >= len(catalogs):
#                 self.index = 0

#             return catalogs[self.index]
#         else:
#             return None

#     def reverse(self):
#         self.direction *= -1


class PlanetCatalog(Catalog):
    """Creates a catalog of planets"""

    def __init__(self, dt: datetime.datetime):
        super().__init__("PL", 10, "The planets")
        planet_dict = sf_utils.calc_planets(dt)
        sequence = 0
        for name in sf_utils.planet_names:
            if name.lower() != "sun":
                self.add_planet(sequence, name, planet_dict[name])
                sequence += 1

    def add_planet(self, sequence: int, name: str, planet: Dict[str, Dict[str, float]]):
        ra, dec = planet["radec"]
        constellation = sf_utils.radec_to_constellation(ra, dec)

        obj = CompositeObject.from_dict(
            {
                "id": -1,
                "obj_type": "Pla",
                "ra": ra,
                "dec": dec,
                "const": constellation,
                "size": "",
                "mag": planet["mag"],
                "names": [name.capitalize()],
                "catalog_code": "PL",
                "sequence": sequence + 1,
                "description": "",
            }
        )
        self.add_object(obj)


class CatalogBuilder:
    """
    Builds catalogs from the database
    Merges object table data and catalog_object table data
    """

    def build(self) -> Catalogs:
        db: Database = ObjectsDatabase()
        obs_db: Database = ObservationsDatabase()
        # list of dicts, one dict for each entry in the catalog_objects table
        catalog_objects: List[Dict] = [dict(row) for row in db.get_catalog_objects()]
        objects = db.get_objects()
        common_names = Names()
        catalogs_info = db.get_catalogs_dict()
        objects = {row["id"]: dict(row) for row in objects}
        composite_objects: List[CompositeObject] = self._build_composite(
            catalog_objects, objects, common_names, obs_db
        )
        # This is used for caching catalog dicts
        # to speed up repeated searches
        self.catalog_dicts = {}
        logging.debug(f"Loaded {len(composite_objects)} objects from database")
        all_catalogs: Catalogs = self._get_catalogs(composite_objects, catalogs_info)
        # Initialize planet catalog with whatever date we have for now
        # This will be re-initialized on activation of Catalog ui module
        # if we have GPS lock
        planet_catalog: Catalog = PlanetCatalog(
            datetime.datetime.now().replace(tzinfo=pytz.timezone("UTC"))
        )
        all_catalogs.add(planet_catalog)

        assert self.check_catalogs_sequences(all_catalogs) is True
        return all_catalogs

    def check_catalogs_sequences(self, catalogs: Catalogs):
        for catalog in catalogs.get_catalogs():
            result = catalog.check_sequences()
            if not result:
                logging.error(f"Duplicate sequence catalog {catalog.catalog_code}!")
                return False
            return True

    def _build_composite(
        self,
        catalog_objects: List[Dict],
        objects: Dict[int, Dict],
        common_names: Names,
        obs_db: ObservationsDatabase,
    ) -> List[CompositeObject]:
        composite_objects: List[CompositeObject] = []

        for catalog_obj in catalog_objects:
            object_id = catalog_obj["object_id"]

            # Merge the two dictionaries
            composite_data = objects[object_id] | catalog_obj

            # Create an instance from the merged dictionaries
            composite_instance = CompositeObject.from_dict(composite_data)
            composite_instance.logged = obs_db.check_logged(composite_instance)
            composite_instance.names = common_names.get_name(object_id)

            # Append to the result dictionary
            composite_objects.append(composite_instance)
        return composite_objects

    def _get_catalogs(
        self, composite_objects: List[CompositeObject], catalogs_info: Dict[str, Dict]
    ) -> Catalogs:
        # group composite_objects per catalog_code in a dictionary
        composite_dict: Dict[str, List[CompositeObject]] = {}
        for obj in composite_objects:
            composite_dict.setdefault(obj.catalog_code, []).append(obj)

        # convert dict of composite_objects into a List of Catalog
        catalog_list: List[Catalog] = []
        for catalog_code in catalogs_info.keys():
            catalog_info = catalogs_info[catalog_code]
            catalog = Catalog(
                catalog_code,
                max_sequence=catalog_info["max_sequence"],
                desc=catalog_info["desc"],
            )
            catalog.add_objects(composite_dict.get(catalog_code, []))
            catalog_list.append(catalog)
            catalog = None
        return Catalogs(catalog_list)


class CatalogDesignator:
    """Holds the string that represents the catalog input/search field.
    Usually looks like 'NGC----' or 'M-13'"""

    def __init__(self, catalog_name: str, max_sequence: int):
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
    current_catalog_code: str

    def __init__(self, catalogs: Catalogs, shared_state, config_options):
        self.shared_state = shared_state
        self.config_options = config_options
        self.catalogs: Catalogs = catalogs
        self.refresh_catalogs()

    def get_current_catalog(self) -> Optional[Catalog]:
        return self.catalogs.get_catalog_by_code(self.current_catalog_code)

    def refresh_catalogs(self):
        self.object_tracker = {}
        self.designator_tracker = {}
        logging.debug(
            f"refresh_catalogs: {self.catalogs=}, {self.object_tracker=}, {self.designator_tracker=}"
        )
        self.designator_tracker = {
            c.catalog_code: CatalogDesignator(c.catalog_code, c.max_sequence)
            for c in self.catalogs.get_catalogs()
        }
        catalog_codes = self.catalogs.get_codes()
        self.set_default_current_catalog()
        self.object_tracker = {c: None for c in catalog_codes}
        logging.debug(
            f"refresh_catalogs: {self.catalogs=}, {self.object_tracker=}, {self.designator_tracker=}"
        )

    def select_catalogs(self, catalog_names: List[str]):
        self.catalogs.select_catalogs(catalog_names)
        self.refresh_catalogs()

    def add_foreign_catalog(self, catalog_name):
        """foreign objects not in our database, e.g. skysafari coords"""
        ui_state = self.shared_state.ui_state()
        logging.debug(f"adding foreign catalog {catalog_name}")
        logging.debug(f"current catalog codes: {self.catalogs.get_codes()}")
        logging.debug(f"current catalog: {self.current_catalog_code}")
        logging.debug(f"current object: {self.get_current_object()}")
        logging.debug(f"current designator: {self.get_designator()}")
        logging.debug(f"current target: {ui_state.target()}")
        logging.debug(f"ui state: {str(ui_state)}")
        push_catalog = Catalog("PUSH", 1, "Skysafari push")
        target = ui_state.target()
        if target is None:
            logging.warning("No target to push")
            return push_catalog
        push_catalog.add_object(
            CompositeObject(
                id=-1,
                sequence=1,
                catalog_code="PUSH",
                ra=target.ra,
                dec=target.dec,
                mag="0",
                obj_type="",
                description="Skysafari push target",
                logged=False,
                names=[],
            )
        )
        self.catalogs.add(push_catalog)
        self.designator_tracker[catalog_name] = CatalogDesignator(catalog_name, 1)
        self.object_tracker[catalog_name] = None

    def set_current_catalog(self, catalog_code: str):
        if self.catalogs.has_code(catalog_code):
            self.current_catalog_code = catalog_code
        elif self.catalogs.has_code(catalog_code, only_selected=False):
            self.set_default_current_catalog()
        else:
            self.add_foreign_catalog(catalog_code)
            self.current_catalog_code = catalog_code

    def set_default_current_catalog(self):
        self.current_catalog_code = self.catalogs.get_codes()[0]

    def next_catalog(self, direction=1):
        next = self.catalogs.next_catalog(self.current_catalog_code, direction)
        self.set_current_catalog(next.catalog_code)

    def previous_catalog(self):
        self.next_catalog(-1)

    def next_object(self, direction=1, filtered=True):
        """
        direction: 1 for next, -1 for previous

        """
        current_catalog = self.get_current_catalog()
        objects = (
            current_catalog.filtered_objects
            if filtered
            else current_catalog.get_objects()
        )
        object_ids = [x.sequence for x in objects]
        current_key = self.object_tracker[self.current_catalog_code]
        next_key = None
        designator = self.get_designator()
        # there is no current object, so set the first object the first or last
        if current_key is None or current_key not in object_ids:
            next_index = 0 if direction == 1 else len(object_ids) - 1
            next_key = object_ids[next_index]
            designator.set_number(next_key)

        else:
            current_index = object_ids.index(current_key)
            next_index = current_index + direction
            if next_index == -1 or next_index >= len(object_ids):
                next_key = None  # hack to get around the fact that 0 is a valid key
                designator.set_number(0)  # todo use -1 in designator as well
            else:
                next_key = object_ids[next_index % len(object_ids)]
                designator.set_number(next_key)
        self.set_current_object(next_key)
        return self.get_current_object()

    def previous_object(self):
        return self.next_object(-1)

    def get_current_object(self) -> Optional[CompositeObject]:
        object_key = self.object_tracker[self.current_catalog_code]
        current_catalog = self.get_current_catalog()
        if object_key is None or current_catalog is None:
            return None
        return current_catalog.get_object_by_sequence(object_key)

    def set_current_object(self, object_number: int, catalog_code: str = ""):
        if catalog_code:
            try:
                self.set_current_catalog(catalog_code)
            except AssertionError:
                # Requested catalog not in tracker!
                # Set to current catalog/zero
                self.designator_tracker[catalog_code].set_number(0)
                return
        else:
            catalog_code = self.current_catalog_code
        self.object_tracker[catalog_code] = object_number

        # Make sure this catalog is in the designator tracker
        # if not, add it so it can be set
        if self.designator_tracker.get(catalog_code) is None:
            _c = self.catalogs.get_catalog_by_code(catalog_code)
            self.designator_tracker[catalog_code] = CatalogDesignator(
                catalog_code, _c.max_sequence
            )

        self.designator_tracker[catalog_code].set_number(
            object_number if object_number else 0
        )

    def get_designator(self, catalog_code: str = "") -> CatalogDesignator:
        catalog_code: str = catalog_code or self.current_catalog_code
        return self.designator_tracker[catalog_code]

    def filter(self):
        catalog_list = self.catalogs.get_catalogs()
        magnitude_filter = self.config_options["Magnitude"]["value"]
        type_filter = self.config_options["Obj Types"]["value"]
        altitude_filter = self.config_options["Alt Limit"]["value"]
        observed_filter = self.config_options["Observed"]["value"]

        for catalog in catalog_list:
            catalog.catalog_filter.set_values(
                magnitude_filter,
                type_filter,
                altitude_filter,
                observed_filter,
            )
            catalog.filter_objects(self.shared_state)

        current_object = self.object_tracker[self.current_catalog_code]
        if current_object is not None and not self.get_current_catalog().has(
            current_object
        ):
            self.set_current_object(None, catalog_list[0].catalog_code)

    def __repr__(self):
        return f"CatalogTracker(Current:{self.current_catalog_code} {self.object_tracker[self.current_catalog_code]}, Designator:{self.designator_tracker})"
