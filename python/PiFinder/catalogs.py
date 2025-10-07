# mypy: ignore-errors
import logging
import time
import datetime
import pytz
from pprint import pformat
from typing import List, Dict, DefaultDict, Optional, Union
from collections import defaultdict
import PiFinder.calc_utils as calc_utils
from PiFinder.calc_utils import sf_utils
from PiFinder.state import SharedStateObj
from PiFinder.db.db import Database
from PiFinder.db.objects_db import ObjectsDatabase
from PiFinder.db.observations_db import ObservationsDatabase
from PiFinder.composite_object import CompositeObject, MagnitudeObject
from PiFinder.utils import Timer
from PiFinder.config import Config
from PiFinder.catalog_base import (
    CatalogState,
    CatalogStatus,
    CatalogBase,
    TimerMixin,
    VirtualIDManager,
)

logger = logging.getLogger("Catalog")

# collection of all catalog-related classes

# CatalogBase : just the CompositeObjects (imported from catalog_base)
# Catalog: extends the CatalogBase with filtering
# CatalogIterator: TODO iterates over the composite_objects
# CatalogFilter: can be set on catalog to filter
# CatalogBuilder: builds catalogs from the database
# Catalogs: holds all catalogs


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
        constellations: list[str] = [],
        selected_catalogs: list[str] = [],
    ):
        self.shared_state = shared_state
        # When was the last time filter params were changed?
        self.dirty_time = time.time()

        self._magnitude = magnitude
        self._object_types = object_types
        self._altitude = altitude
        self._observed = observed
        self._constellations = constellations
        self._selected_catalogs = set(selected_catalogs)
        self.last_filtered_time = 0

    def load_from_config(self, config_object: Config):
        """
        Loads filter values from configuration object
        """
        self._magnitude = config_object.get_option("filter.magnitude")
        self._object_types = config_object.get_option("filter.object_types", [])
        self._altitude = config_object.get_option("filter.altitude", -1)
        self._observed = config_object.get_option("filter.observed", "Any")
        self._constellations = config_object.get_option("filter.constellations", [])
        self._selected_catalogs = config_object.get_option("filter.selected_catalogs")
        self.last_filtered_time = 0

    def mark_dirty(self):
        """Mark the filter as dirty, triggering a re-filter on next check"""
        self.dirty_time = time.time()

    @property
    def magnitude(self):
        return self._magnitude

    @magnitude.setter
    def magnitude(self, magnitude: Union[float, None]):
        self._magnitude = magnitude
        self.mark_dirty()

    @property
    def object_types(self):
        return self._object_types

    @object_types.setter
    def object_types(self, object_types: Union[list[str], None]):
        self._object_types = object_types
        self.mark_dirty()

    @property
    def altitude(self):
        return self._altitude

    @altitude.setter
    def altitude(self, altitude: int):
        self._altitude = altitude
        self.mark_dirty()

    @property
    def observed(self):
        return self._observed

    @observed.setter
    def observed(self, observed: str):
        self._observed = observed
        self.mark_dirty()

    @property
    def constellations(self):
        return self._constellations

    @constellations.setter
    def constellations(self, constellations: list[str]):
        self._constellations = constellations
        self.mark_dirty()

    @property
    def selected_catalogs(self):
        return self._selected_catalogs

    @selected_catalogs.setter
    def selected_catalogs(self, catalog_codes: list[str]):
        self._selected_catalogs = set(catalog_codes)
        self.mark_dirty()

    def calc_fast_aa(self, shared_state):
        location = shared_state.location()
        dt = shared_state.datetime()
        if shared_state.altaz_ready():
            self.fast_aa = calc_utils.FastAltAz(
                location.lat,
                location.lon,
                dt,
            )
        else:
            logger.warning(
                f"Calc_fast_aa: {'location' if not location else 'datetime' if not dt else 'nothing'} not set"
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

        # check constellation
        if self._constellations:
            if obj.const not in self._constellations:
                obj.last_filtered_result = False
                return False
        else:
            obj.last_filtered_result = False
            return False

        # check altitude
        if self._altitude != -1 and self.fast_aa:
            # quick sanity check of object coords
            try:
                ra = float(obj.ra)
                dec = float(obj.dec)
            except TypeError:
                print("Object coordinates error")
                print(f"{pformat(obj)}")
                return False

            obj_altitude, _ = self.fast_aa.radec_to_altaz(
                ra,
                dec,
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
        if self._object_types:
            if obj.obj_type not in self._object_types:
                obj.last_filtered_result = False
                return False
        else:
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


class Catalog(CatalogBase):
    """Extends the CatalogBase with filtering"""

    def __init__(self, catalog_code: str, desc: str, max_sequence: int = 0):
        super().__init__(catalog_code, desc, max_sequence)
        self.catalog_filter: Union[CatalogFilter, None] = None
        self.filtered_objects: List[CompositeObject] = self.get_objects()
        self.filtered_objects_seq: List[int] = self._filtered_objects_to_seq()
        self.last_filtered = 0
        self.initialized = True
        self._last_state: CatalogState = CatalogState.READY

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
            "FILTERED %s %d/%d",
            self.catalog_code,
            len(self.filtered_objects),
            len(self.get_objects()),
        )
        self.filtered_objects_seq = self._filtered_objects_to_seq()
        self.last_filtered = time.time()
        return self.filtered_objects

    def get_filtered_objects(self):
        return self.filtered_objects

    def get_filtered_count(self):
        return len(self.filtered_objects)

    def get_age(self) -> Optional[int]:
        """If the catalog data is time-sensitive, return age in days."""
        return None

    def get_status(self) -> CatalogStatus:
        """
        Return the current status of the catalog with transition tracking.
        Override this in subclasses to provide catalog-specific status.
        Default returns READY state (catalog is always ready).
        """
        status = CatalogStatus(
            current=CatalogState.READY,
            previous=self._last_state,
            data=None
        )
        self._last_state = status.current
        return status

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
                "Catalog %s already exists, not replaced (in Catalogs.add)",
                catalog.catalog_code,
            )

    def remove(self, catalog_code: str):
        for catalog in self.__catalogs:
            if catalog.catalog_code == catalog_code:
                self.__catalogs.remove(catalog)
                return

        logger.warning("Catalog %s does not exist, cannot remove", catalog_code)

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


class PlanetCatalog(Catalog):
    """Creates a catalog of planets with adaptive update frequency based on GPS lock status"""

    # Default time delay when we have GPS lock
    DEFAULT_DELAY = 307
    # Shorter time delay when waiting for GPS lock
    WAITING_FOR_GPS_DELAY = 10
    short_delay = True

    def __init__(self, dt: datetime.datetime, shared_state: SharedStateObj):
        super().__init__("PL", "Planets")
        self._timer = TimerMixin()
        self._virtual_id_manager = VirtualIDManager()

        self.shared_state = shared_state
        self._last_state: CatalogState = CatalogState.READY

        # Override Catalog's initialized=True since we need to wait for GPS/calculation
        self.initialized = False

        # Configure timer after initialization
        self._timer.do_timed_task = self.do_timed_task
        self._timer.time_delay_seconds = lambda: self.time_delay_seconds
        self._timer.start_timer()

    @property
    def time_delay_seconds(self) -> int:
        if self.initialized:
            # We've calculated at least once....
            return 307
        else:
            # Check for a lock/time every 10 seconds
            return 10

    def get_status(self) -> CatalogStatus:
        """Return the current status of the planet catalog"""
        if not self.shared_state.altaz_ready():
            current_state = CatalogState.NO_GPS
        elif not self.initialized:
            current_state = CatalogState.CALCULATING
        else:
            current_state = CatalogState.READY

        status = CatalogStatus(
            current=current_state,
            previous=self._last_state,
            data=None
        )
        self._last_state = status.current
        return status

    def init_planets(self, dt):
        planet_dict = sf_utils.calc_planets(dt)
        logger.debug(f"starting planet dict {planet_dict}")

        if not planet_dict:
            logger.debug("No GPS lock during initialization - will retry soon")
            self.initialised = True  # Still mark as initialized so timer starts
            return

        sequence = 0
        for name in sf_utils.planet_names:
            planet_data = planet_dict.get(name)
            if name.lower() != "sun" and planet_data:
                self.add_planet(sequence, name, planet_data)
                sequence += 1

        with self._virtual_id_manager.virtual_id_lock:
            new_low = self._virtual_id_manager.assign_virtual_object_ids(
                self, self._virtual_id_manager.virtual_id_low
            )
            self._virtual_id_manager.virtual_id_low = new_low
        self.initialized = True

    def add_planet(self, sequence: int, name: str, planet: Dict[str, Dict[str, float]]):
        try:
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
        except (KeyError, ValueError) as e:
            logger.error(f"Error adding planet {name}: {e}")

    def do_timed_task(self):
        with Timer("Planet Catalog periodic update"):
            """ updating planet catalog data """
            if not self.shared_state.altaz_ready():
                return

            dt = self.shared_state.datetime()
            if not self.initialized:
                self.init_planets(dt)

            planet_dict = sf_utils.calc_planets(dt)

            # If we just got GPS lock and previously had no planets, do a full reinit
            if not self.get_objects():
                logger.info("GPS lock acquired - reinitializing planet catalog")
                self.init_planets(dt)
                return

            # Regular update if we have GPS lock
            for obj in self._get_objects():
                try:
                    name = obj.names[0]
                    if name in planet_dict:
                        planet = planet_dict[name]
                        obj.ra, obj.dec = planet["radec"]
                        obj.mag = MagnitudeObject([planet["mag"]])
                        obj.const = sf_utils.radec_to_constellation(obj.ra, obj.dec)
                        obj.mag_str = obj.mag.calc_two_mag_representation()
                except (KeyError, ValueError) as e:
                    logger.error(f"Error updating planet {name}: {e}")




class CatalogBuilder:
    """
    Builds catalogs from the database
    Merges object table data and catalog_object table data
    """

    def build(self, shared_state) -> Catalogs:
        db: Database = ObjectsDatabase()
        obs_db: Database = ObservationsDatabase()
        # list of dicts, one dict for each entry in the catalog_objects table
        catalog_objects: List[Dict] = [dict(row) for row in db.get_catalog_objects()]
        objects = db.get_objects()
        common_names = Names()
        catalogs_info = db.get_catalogs_dict()

        # Disable WDS for now to work on
        # performance and sort/nearest bug
        catalogs_info.pop("WDS")

        objects = {row["id"]: dict(row) for row in objects}
        composite_objects: List[CompositeObject] = self._build_composite(
            catalog_objects, objects, common_names, obs_db
        )
        # This is used for caching catalog dicts
        # to speed up repeated searches
        self.catalog_dicts = {}
        logger.debug("Loaded %i objects from database", len(composite_objects))
        all_catalogs: Catalogs = self._get_catalogs(composite_objects, catalogs_info)
        # Initialize planet catalog with whatever date we have for now
        # This will be re-initialized on activation of Catalog ui module
        # if we have GPS lock
        planet_catalog: Catalog = PlanetCatalog(
            dt=datetime.datetime.now().replace(tzinfo=pytz.timezone("UTC")),
            shared_state=shared_state,
        )
        all_catalogs.add(planet_catalog)

        # Import CometCatalog locally to avoid circular import
        from PiFinder.comet_catalog import CometCatalog

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
                logger.error("Duplicate sequence catalog %s!", catalog.catalog_code)
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
