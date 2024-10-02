# mypy: ignore-errors
import logging
import time
import datetime
import pytz
from pprint import pformat
import threading
from typing import List, Dict, DefaultDict, Optional, Union
from collections import defaultdict
import PiFinder.calc_utils as calc_utils
from PiFinder.calc_utils import sf_utils
from PiFinder.state import SharedStateObj
from PiFinder.db.db import Database
from PiFinder.db.objects_db import ObjectsDatabase
from PiFinder.db.observations_db import ObservationsDatabase
from PiFinder.composite_object import CompositeObject, MagnitudeObject
import PiFinder.comets as comets
from PiFinder.utils import Timer, comet_file

logger = logging.getLogger("Catalog")

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
        logger.debug("Loaded %i names from database", len(self.names))

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
        shared_state: SharedStateObj,
        magnitude: Union[float, None] = None,
        object_types: Union[list[str], None] = None,
        altitude: int = -1,
        observed: str = "Any",
        selected_catalogs: list[str] = [],
    ):
        self.shared_state = shared_state
        # When was the last time filter params were changed?
        self.dirty_time = time.time()

        self._magnitude = magnitude
        self._object_types = object_types
        self._altitude = altitude
        self._observed = observed
        self._selected_catalogs = set(selected_catalogs)
        self.last_filtered_time = 0

    @property
    def magnitude(self):
        return self._magnitude

    @magnitude.setter
    def magnitude(self, magnitude: Union[float, None]):
        self._magnitude = magnitude
        self.dirty_time = time.time()

    @property
    def object_types(self):
        return self._object_types

    @object_types.setter
    def object_types(self, object_types: Union[list[str], None]):
        self._object_types = object_types
        self.dirty_time = time.time()

    @property
    def altitude(self):
        return self._altitude

    @altitude.setter
    def altitude(self, altitude: int):
        self._altitude = altitude
        self.dirty_time = time.time()

    @property
    def observed(self):
        return self._observed

    @observed.setter
    def observed(self, observed: str):
        self._observed = observed
        self.dirty_time = time.time()

    @property
    def selected_catalogs(self):
        return self._selected_catalogs

    @selected_catalogs.setter
    def selected_catalogs(self, catalog_codes: list[str]):
        self._selected_catalogs = set(catalog_codes)
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
            logger.warning(
                f"Calc_fast_aa: {'solution' if not solution else 'location' if not location else 'datetime' if not dt else 'nothing'} not set"
            )

    def is_dirty(self) -> bool:
        """
        Returns true if the filter parameters have changed since
        the last filter.  False if not
        """
        if self.last_filtered_time > self.dirty_time:
            return False
        else:
            return True

    def apply_filter(self, obj: CompositeObject):
        if obj.last_filtered_time > self.dirty_time:
            return obj.last_filtered_result

        obj.last_filtered_time = time.time()
        self.last_filtered_time = time.time()
        # check altitude
        if self._altitude != -1 and self.fast_aa:
            obj_altitude, _ = self.fast_aa.radec_to_altaz(
                obj.ra,
                obj.dec,
                alt_only=True,
            )
            if obj_altitude < self._altitude:
                obj.last_filtered_result = False
                return False

        # check magnitude
        obj_mag = obj.mag.filter_mag

        if self._magnitude is not None and obj_mag > self._magnitude:
            obj.last_filtered_result = False
            return False

        # check type
        if self._object_types is not None and obj.obj_type not in self._object_types:
            obj.last_filtered_result = False
            return False

        # check observed
        if self._observed is not None and self._observed != "Any":
            if self._observed == "Yes":
                if not obj.logged:
                    obj.last_filtered_result = False
                    return False
            else:
                if obj.logged:
                    obj.last_filtered_result = False
                    return False

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
        desc: str,
        max_sequence: int = 0,
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

    def _get_objects(self) -> List[CompositeObject]:
        return self.__objects

    def add_object(self, obj: CompositeObject):
        self._add_object(obj)
        self._sort_objects()
        self._update_id_to_pos()
        self._update_sequence_to_pos()
        assert self.check_sequences()

    def _add_object(self, obj: CompositeObject):
        self.__objects.append(obj)
        if (obj.sequence > self.max_sequence):
            self.max_sequence = obj.sequence

    def add_objects(self, objects: List[CompositeObject]):
        objects_copy = objects.copy()
        for obj in objects_copy:
            self._add_object(obj)
        self._sort_objects()
        self._update_id_to_pos()
        self._update_sequence_to_pos()
        assert self.check_sequences()

    def _sort_objects(self):
        # print(f"Sorting {self.catalog_code} with key {self.sort}")
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
            logger.error("Duplicate sequence catalog %s!", self.catalog_code)
            return False
        return True

    def _update_id_to_pos(self):
        self.id_to_pos = {obj.id: i for i, obj in enumerate(self.__objects)}

    def _update_sequence_to_pos(self):
        self.sequence_to_pos = {obj.sequence: i for i,
                                obj in enumerate(self.__objects)}

    def __repr__(self):
        return f"Catalog({self.catalog_code=}, {self.max_sequence=}, count={self.get_count()})"

    def __str__(self):
        return self.__repr__()


class Catalog(CatalogBase):
    """Extends the CatalogBase with filtering"""

    def __init__(self, catalog_code: str, desc: str, max_sequence: int = 0):
        super().__init__(catalog_code, desc, max_sequence)
        self.catalog_filter: Union[CatalogFilter, None] = None
        self.filtered_objects: List[CompositeObject] = self.get_objects()
        self.filtered_objects_seq: List[int] = self._filtered_objects_to_seq()
        self.last_filtered = 0
        self.initialised = True

    def is_selected(self):
        """
        Convenience function to see if this catalog is in the
        current filter list
        """
        if self.catalog_filter is None:
            return False
        return self.catalog_code in self.catalog_filter.selected_catalogs

    def has(self, sequence: int, filtered=True):
        return sequence in self.filtered_objects_seq

    def _filtered_objects_to_seq(self):
        return [obj.sequence for obj in self.filtered_objects]

    def filter_objects(self) -> List[CompositeObject]:
        if self.catalog_filter is None:
            return self.get_objects()

        self.filtered_objects = self.catalog_filter.apply(self.get_objects())
        logger.info(
            "FILTERED %s %d/%d", self.catalog_code, len(
                self.filtered_objects), len(self.get_objects())
        )
        self.filtered_objects_seq = self._filtered_objects_to_seq()
        self.last_filtered = time.time()
        return self.filtered_objects

    def get_filtered_objects(self):
        return self.filtered_objects

    def get_filtered_count(self):
        return len(self.filtered_objects)

    def get_age(self) -> Optional[int]:
        """ If the catalog data is time-sensitive, return age in days. """
        return None

    def __repr__(self):
        super().__repr__()
        return f"{super().__repr__()} - filtered={self.get_filtered_count()})"

    def __str__(self):
        return self.__repr__()


class Catalogs:
    """Holds all catalogs"""

    def __init__(self, catalogs: List[Catalog]):
        self.__catalogs: List[Catalog] = catalogs
        self.catalog_filter: Union[CatalogFilter, None] = None

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
        self.catalog_filter = catalog_filter
        for catalog in self.__catalogs:
            catalog.catalog_filter = catalog_filter

    def get_catalogs(self, only_selected: bool = True) -> List[Catalog]:
        return_list = []
        for catalog in self.__catalogs:
            if (only_selected and catalog.is_selected()) or not only_selected:
                return_list.append(catalog)

        return return_list

    def get_objects(
        self, only_selected: bool = True, filtered: bool = True
    ) -> list[CompositeObject]:
        return_list = []
        for catalog in self.__catalogs:
            if (only_selected and catalog.is_selected()) or not only_selected:
                if filtered:
                    return_list += catalog.get_filtered_objects()
                else:
                    return_list += catalog.get_objects()
        return return_list

    def select_catalogs(self, catalog_codes: List[str]):
        for catalog_code in catalog_codes:
            self.catalog_filter.selected_catalogs.add(catalog_code)

    def has_code(self, catalog_code: str, only_selected: bool = True) -> bool:
        return catalog_code in self.get_codes(only_selected)

    def has(self, catalog: Catalog, only_selected: bool = True) -> bool:
        return self.has_code(catalog.catalog_code, only_selected)

    def get_object(self, catalog_code: str, sequence: int) -> Optional[CompositeObject]:
        catalog = self.get_catalog_by_code(catalog_code)
        if catalog:
            return catalog.get_object_by_sequence(sequence)

    # this is memory efficient and doesn't hit the sdcard, but could be faster
    # also, it could be cached
    def search_by_text(self, search_text: str) -> List[CompositeObject]:
        objs = self.get_objects(only_selected=False, filtered=False)
        result = []
        if not search_text:
            return result
        for obj in objs:
            for name in obj.names:
                if search_text.lower() in name.lower():
                    result.append(obj)
                    # if not search_text == "":
                    logger.debug(
                        "Found %s in %s %i", name, obj.catalog_code, obj.sequence
                    )
                    break
        return result

    def set(self, catalogs: List[Catalog]):
        self.__catalogs = catalogs
        self.select_all_catalogs()

    def add(self, catalog: Catalog, select: bool = False):
        if catalog.catalog_code not in [x.catalog_code for x in self.__catalogs]:
            if select:
                self.catalog_filter.selected_catalogs.add(catalog.catalog_code)
            self.__catalogs.append(catalog)
        else:
            logger.warning(
                "Catalog %s already exists, not replaced (in Catalogs.add)", catalog.catalog_code
            )

    def remove(self, catalog_code: str):
        for catalog in self.__catalogs:
            if catalog.catalog_code == catalog_code:
                self.__catalogs.remove(catalog)
                return

        logger.warning(
            "Catalog %s does not exist, cannot remove", catalog_code)

    def get_codes(self, only_selected: bool = True) -> List[str]:
        return_list = []
        for catalog in self.__catalogs:
            if (only_selected and catalog.is_selected()) or not only_selected:
                return_list.append(catalog.catalog_code)

        return return_list

    def get_catalog_by_code(self, catalog_code: str) -> Optional[Catalog]:
        for catalog in self.__catalogs:
            if catalog.catalog_code == catalog_code:
                return catalog
        return None

    def count(self) -> int:
        return len(self.get_catalogs())

    def select_no_catalogs(self):
        self.catalog_filter.selected_catalogs = set()

    def select_all_catalogs(self):
        for catalog in self.__catalogs:
            self.catalog_filter.selected_catalogs.add(catalog.catalog_code)

    def __repr__(self):
        return f"Catalogs(\n{pformat(self.get_catalogs(only_selected=False))})"

    def __str__(self):
        return self.__repr__()

    def __iter__(self):
        return iter(self.get_catalogs())


class VirtualCatalog(Catalog):
    virtual_id_lock = threading.Lock()
    virtual_id_low = 0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @staticmethod
    def assign_virtual_object_ids(catalog: Catalog, low_id: int) -> int:
        """
        Assigns virtual object_ids for non-DB objects. Return new low.
        """
        for obj in catalog.get_objects():
            low_id -= 1
            obj.object_id = low_id
        return low_id


class TimerCatalog(VirtualCatalog):
    """Catalog that runs a task periodically"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.initialised = False
        logger.debug("in init of timercatalog")
        self.timer: Optional[threading.Timer] = None
        self.is_running: bool = False
        logger.debug("Starting timer")
        self.start_timer()

    @property
    def time_delay_seconds(self) -> int:
        return 300  # 5 minutes

    def start_timer(self) -> None:
        """Start the timer if it's not already running"""
        if not self.is_running:
            self.is_running = True
            self._schedule_next_run()

    def _schedule_next_run(self) -> None:
        """Schedule the next run of the timed task"""
        self.timer = threading.Timer(self.time_delay_seconds, self._run)
        self.timer.start()

    def _run(self) -> None:
        """Execute the timed task in a separate thread and reschedule if still running"""
        threading.Thread(target=self._execute_task).start()
        if self.is_running:
            self._schedule_next_run()

    def _execute_task(self) -> None:
        """Execute the timed task"""
        try:
            self.do_timed_task()
        except Exception as e:
            logger.error(f"Error in timed task: {e}", exc_info=True)

    def do_timed_task(self) -> None:
        """Override this method in subclasses to define the timed task"""
        logger.warning("Executing uninitialized timed task")

    def stop(self) -> None:
        """Stop the timer"""
        self.is_running = False
        if self.timer:
            self.timer.cancel()
            self.timer = None

    def __del__(self) -> None:
        """Ensure the timer is stopped when the object is deleted"""
        self.stop()


class PlanetCatalog(TimerCatalog):
    """Creates a catalog of planets"""

    def __init__(self, dt: datetime.datetime, shared_state: SharedStateObj):
        super().__init__("PL", "Planets")
        self.shared_state = shared_state
        self.init_planets(dt)

    @property
    def time_delay_seconds(self) -> int:
        return 307

    def init_planets(self, dt):
        planet_dict = sf_utils.calc_planets(dt)
        sequence = 0
        for name in sf_utils.planet_names:
            if name.lower() != "sun":
                self.add_planet(sequence, name, planet_dict[name])
                sequence += 1
        with self.virtual_id_lock:
            new_low = self.assign_virtual_object_ids(self, self.virtual_id_low)
            self.virtual_id_low = new_low
        self.initialised = True

    def add_planet(self, sequence: int, name: str, planet: Dict[str, Dict[str, float]]):
        ra, dec = planet["radec"]
        constellation = sf_utils.radec_to_constellation(ra, dec)

        obj = CompositeObject.from_dict(
            {
                "id": 0,
                "obj_type": "Pla",
                "ra": ra,
                "dec": dec,
                "const": constellation,
                "size": "",
                "mag": MagnitudeObject([planet["mag"]]),
                "names": [name.capitalize()],
                "catalog_code": "PL",
                "sequence": sequence + 1,
                "description": "",
            }
        )
        self.add_object(obj)

    def do_timed_task(self):
        if not self.initialised:
            return
        with Timer("Planet Catalog periodic update"):
            """ updating planet catalog data """
            dt = self.shared_state.datetime()
            if not dt or not sf_utils.observer_loc:
                return
            planet_dict = sf_utils.calc_planets(dt)
            for obj in self._get_objects():
                name = obj.names[0]
                if name in planet_dict:
                    planet = planet_dict[name]
                    obj.ra, obj.dec = planet["radec"]
                    obj.mag = MagnitudeObject([planet["mag"]])
                    obj.const = sf_utils.radec_to_constellation(
                        obj.ra, obj.dec)
                    obj.mag_str = obj.mag.calc_two_mag_representation()


class CometCatalog(TimerCatalog):
    """Creates a catalog of comets"""

    def __init__(self, dt: datetime.datetime, shared_state: SharedStateObj):
        super().__init__("CM", "Comets")
        self.age = None
        self.shared_state = shared_state
        self._init_lock = threading.Lock()
        self._start_background_init(dt)

    def get_age(self) -> Optional[int]:
        """ Return the age of the comet data in days """
        return self.age

    def _start_background_init(self, dt):
        def init_task():
            while True:
                success, self.age = comets.comet_data_download(comet_file)
                if success:
                    with self._init_lock:
                        self.initialised = self.calc_comet_first_time(dt)
                    with self.virtual_id_lock:
                        new_low = self.assign_virtual_object_ids(
                            self, self.virtual_id_low)
                        self.virtual_id_low = new_low
                    break
                time.sleep(60)  # retry every minute to download comet data

        threading.Thread(target=init_task, daemon=True).start()

    def calc_comet_first_time(self, dt):
        with Timer("CometCatalog.__init__"):
            comet_dict = comets.calc_comets(dt)
            if not comet_dict:
                return False
            for sequence, (name, comet) in enumerate(comet_dict.items()):
                self.add_comet(sequence, name, comet)
            return True

    @property
    def time_delay_seconds(self) -> int:
        return 293

    def add_comet(self, sequence: int, name: str, comet: Dict[str, Dict[str, float]]):
        ra, dec = comet["radec"]
        constellation = sf_utils.radec_to_constellation(ra, dec)
        # desc = f"{comet['radec_pretty']}, AltAZ: {comet['altaz']}\nAltAz2: {comet['altaz2']}\nAltAz3: {comet['altaz3']}\n{comet['radec_pretty']}, Earth distance: {comet['earth_distance']} AU\n"
        desc = f"Distance to\nEarth: {comet['earth_distance']:.2f} AU\nSun: {comet['sun_distance']:.2f} AU"

        mag = MagnitudeObject([comet.get("mag", [])])
        obj = CompositeObject.from_dict(
            {
                "id": -1,
                "obj_type": "Com",
                "ra": ra,
                "dec": dec,
                "const": constellation,
                "size": "",
                # Use '?' if magnitude is not available
                "mag": mag,
                "mag_str": mag.calc_two_mag_representation(),
                "names": [name],
                "catalog_code": "CM",
                "sequence": sequence + 1,
                "description": desc,
            }
        )
        self.add_object(obj)

    def do_timed_task(self):
        """ updating comet catalog data """
        with Timer("Comet Catalog periodic update"):
            with self._init_lock:
                if not self.initialised:
                    logging.debug("Comets not yet initialised, skip periodic update...")
                    return
            dt = self.shared_state.datetime()
            comet_dict = comets.calc_comets(
                dt, [x.names[0] for x in self._get_objects()])
            if not comet_dict:
                return
            for obj in self._get_objects():
                name = obj.names[0]
                logger.debug("Processing %s")
                comet = comet_dict.get(name, {})
                obj.ra, obj.dec = comet["radec"]
                obj.mag = MagnitudeObject([comet["mag"]])
                obj.const = sf_utils.radec_to_constellation(obj.ra, obj.dec)
                obj.mag_str = obj.mag.calc_two_mag_representation()
                obj.description = obj.description + "."
            logger.debug("Updated comet catalog")


class CatalogBuilder:
    """
    Builds catalogs from the database
    Merges object table data and catalog_object table data
    """

    def build(self, shared_state) -> Catalogs:
        db: Database = ObjectsDatabase()
        obs_db: Database = ObservationsDatabase()
        # list of dicts, one dict for each entry in the catalog_objects table
        catalog_objects: List[Dict] = [
            dict(row) for row in db.get_catalog_objects()]
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
        logger.debug("Loaded %i objects from database", len(composite_objects))
        all_catalogs: Catalogs = self._get_catalogs(
            composite_objects, catalogs_info)
        # Initialize planet catalog with whatever date we have for now
        # This will be re-initialized on activation of Catalog ui module
        # if we have GPS lock
        planet_catalog: Catalog = PlanetCatalog(
            dt=datetime.datetime.now().replace(tzinfo=pytz.timezone("UTC")),
            shared_state=shared_state,
        )
        all_catalogs.add(planet_catalog)
        comet_catalog: Catalog = CometCatalog(
            datetime.datetime.now().replace(tzinfo=pytz.timezone("UTC")),
            shared_state=shared_state,
        )
        all_catalogs.add(comet_catalog)

        assert self.check_catalogs_sequences(all_catalogs) is True
        return all_catalogs

    def check_catalogs_sequences(self, catalogs: Catalogs):
        for catalog in catalogs.get_catalogs(only_selected=False):
            result = catalog.check_sequences()
            if not result:
                logger.error("Duplicate sequence catalog %s!",
                             catalog.catalog_code)
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
            mag = MagnitudeObject.from_json(composite_instance.mag)
            composite_instance.mag = mag
            composite_instance.mag_str = mag.calc_two_mag_representation()
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
                desc=catalog_info["desc"],
                max_sequence=catalog_info["max_sequence"],
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
