# mypy: ignore-errors
import logging
import time
import datetime
import threading
from collections import OrderedDict
from pprint import pformat
from typing import List, Dict, Optional, Union

import numpy as np

import PiFinder.calc_utils as calc_utils
from PiFinder.calc_utils import sf_utils
from PiFinder.state import SharedStateObj
from PiFinder.state_snapshot import ReadableState
from PiFinder.db.observations_db import ObservationsDatabase
from PiFinder.composite_object import CompositeObject, MagnitudeObject, SizeObject
from PiFinder.utils import Timer
from PiFinder.config import Config
from PiFinder.catalog_base import (
    CatalogState,
    CatalogStatus,
    CatalogBase,
    TimerMixin,
    VirtualIDManager,
)
from PiFinder import catalog_arrays
from PiFinder.catalog_arrays import (  # noqa: F401  (public keypad maps)
    KEYPAD_DIGIT_TO_CHARS,
    LETTER_TO_DIGIT_MAP,
    CatalogColumns,
    name_to_t9_digits,
)
from PiFinder.object_sequence import (
    NO_DISTANCE,
    NO_OPPOSITION,
    ListSource,
    ObjectSequence,
    catalog_code_id,
)
from PiFinder import timez

logger = logging.getLogger("Catalog")

# collection of all catalog-related classes

# CatalogBase : just the CompositeObjects (imported from catalog_base)
# Catalog: extends the CatalogBase with filtering; holds Python objects
# ArrayCatalog: a DB catalog backed by numpy columns (catalog_arrays)
# CatalogFilter: can be set on catalog to filter
# CatalogBuilder: opens the DB catalogs and adds planets and comets
# Catalogs: holds all catalogs


class CatalogFilter:
    """can be set on catalog to filter"""

    fast_aa = None
    # With an altitude criterion active, object altitudes drift as the sky
    # rotates (<= 15 deg/hour), so cached verdicts age out even though no
    # filter parameter changed. 600s bounds the drift to ~2.5 deg — well
    # inside the 10-degree steps the altitude filter is set in.
    ALTITUDE_STALE_SECONDS = 600

    def __init__(
        self,
        shared_state: ReadableState,
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
        # Dynamic catalogs can replace their objects without changing the
        # active filter criteria. Wake open lists without invalidating every
        # unchanged catalog's cached result.
        self._catalog_content_dirty = False
        # Whether alt/az was available when verdicts were last computed.
        # Verdicts computed without it skip the altitude test entirely, so
        # they go stale the moment a fix arrives (see is_stale).
        self._last_filtered_altaz_ready = False

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
        self._catalog_content_dirty = False

    def mark_dirty(self):
        """Mark the filter as dirty, triggering a re-filter on next check"""
        self.dirty_time = time.time()

    def mark_catalog_content_dirty(self) -> None:
        self._catalog_content_dirty = True

    def clear_catalog_content_dirty(self) -> None:
        self._catalog_content_dirty = False

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
        self._last_filtered_altaz_ready = shared_state.altaz_ready()
        if self._last_filtered_altaz_ready:
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
        Returns true if the filtered verdicts need recomputing: a filter
        parameter changed since the last filter (dirty), or time-sensitive
        criteria have aged out (stale — see is_stale).  False if not
        """
        if self._catalog_content_dirty:
            return True
        if self.last_filtered_time > self.dirty_time:
            return self.is_stale()
        else:
            return True

    def is_stale(self) -> bool:
        """
        Returns true when altitude verdicts are outdated even though no
        filter parameter changed: enough time has passed that the sky has
        rotated appreciably, or an alt/az fix arrived (GPS lock) after
        verdicts were computed without one.

        Always false without an altitude criterion, so the
        no-altitude-filter case keeps its O(catalogs) cached fast path.
        Staleness does not invalidate anything by itself — see
        Catalogs.filter_catalogs, which promotes it to a dirty bump.
        """
        if self._altitude == -1:
            return False
        if self.last_filtered_time == 0:
            # never filtered yet — is_dirty already reports True
            return False
        if not self._last_filtered_altaz_ready:
            return self.shared_state.altaz_ready()
        if time.time() - self.dirty_time > self.ALTITUDE_STALE_SECONDS:
            return self.shared_state.altaz_ready()
        return False

    def verdicts(self, items) -> np.ndarray:
        """
        Filter verdict for each item, as a boolean array in order.

        ``items`` is a list of objects, or an ObjectSequence. Each active
        criterion is evaluated for all items at once with numpy; a criterion
        that is not set costs nothing. Call calc_fast_aa first so the
        altitude test uses the current time.
        """
        column = (
            items.column
            if isinstance(items, ObjectSequence)
            else ListSource(items).column
        )
        keep = np.ones(len(items), dtype=bool)
        if len(items) == 0:
            return keep

        if self._constellations:
            keep &= np.isin(column("const"), list(self._constellations))

        if self._altitude != -1 and self.fast_aa:
            # An object without valid coordinates has a NaN altitude, which
            # fails the comparison and so never passes the altitude test.
            altitude = self.fast_aa.radec_to_alt_array(column("ra"), column("dec"))
            keep &= altitude >= self._altitude

        if self._magnitude is not None:
            keep &= ~(column("filter_mag") > self._magnitude)

        if self._object_types:
            keep &= np.isin(column("obj_type"), list(self._object_types))

        if self._observed is not None and self._observed != "Any":
            logged = column("logged")
            keep &= logged if self._observed == "Yes" else ~logged

        return keep

    def evaluate(self, items) -> np.ndarray:
        """The verdicts for ``items`` at the current time and location."""
        self.calc_fast_aa(self.shared_state)
        self.last_filtered_time = time.time()
        return self.verdicts(items)

    def apply(self, items):
        """
        Returns the items that pass the filter: an ObjectSequence for an
        ObjectSequence, else a list. For a list, also records the verdict on
        each object (last_filtered_result / last_filtered_time); rows of an
        ArrayCatalog get their catalog's verdict when they are made.
        """
        keep = self.evaluate(items)
        if isinstance(items, ObjectSequence):
            return items.mask(keep)
        now = self.last_filtered_time
        passed = []
        for obj, ok in zip(items, keep.tolist()):
            obj.last_filtered_time = now
            obj.last_filtered_result = ok
            if ok:
                passed.append(obj)
        return passed


class Catalog(CatalogBase):
    """Extends the CatalogBase with filtering"""

    def __init__(self, catalog_code: str, desc: str, max_sequence: int = 0):
        super().__init__(catalog_code, desc, max_sequence)
        self.catalog_filter: Union[CatalogFilter, None] = None
        self.filtered_objects: List[CompositeObject] = self.get_objects()
        self.filtered_objects_seq: List[int] = self._filtered_objects_to_seq()
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

        # Skip filtering if catalog is empty (deferred catalogs not loaded yet).
        # Checked before the cache guard so an emptied catalog (e.g. comet
        # refresh clearing objects) always yields an empty list, never a stale
        # cached one.
        if self.get_count() == 0:
            logger.debug(
                "Skipping filter for empty catalog %s (deferred loading)",
                self.catalog_code,
            )
            self.filtered_objects = []
            self.filtered_objects_seq = []
            self.last_filtered = time.time()
            return self.filtered_objects

        # Already filtered against the current criteria — reuse the cached
        # result. filter_catalogs() runs this for every catalog on each list
        # open; dirty_time only advances when a filter parameter changes, so an
        # unchanged filter returns here in O(1) instead of rescanning objects.
        if self.last_filtered > self.catalog_filter.dirty_time:
            return self.filtered_objects

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

    def invalidate_filter_cache(self) -> None:
        """Invalidate only this catalog after its runtime objects change."""
        self.last_filtered = 0
        for obj in self._get_objects():
            obj.last_filtered_time = 0

    def get_filtered_objects(self):
        return self.filtered_objects

    def get_filtered_count(self):
        return len(self.filtered_objects)

    def as_sequence(self, filtered: bool) -> ObjectSequence:
        """The catalog's objects (only those that pass the filter when
        ``filtered``) as an ObjectSequence."""
        objects = self.get_filtered_objects() if filtered else self.get_objects()
        return ObjectSequence.of(list(objects))

    def get_age(self) -> Optional[int]:
        """If the catalog data is time-sensitive, return age in days."""
        return None

    def get_data_label(self) -> Optional[str]:
        """Optional compact source-edition label for object-list headers."""
        return None

    def get_status(self) -> CatalogStatus:
        """
        Return the current status of the catalog with transition tracking.
        Override this in subclasses to provide catalog-specific status.
        Default returns READY state (catalog is always ready).
        """
        status = CatalogStatus(
            current=CatalogState.READY, previous=self._last_state, data=None
        )
        self._last_state = status.current
        return status

    def __repr__(self):
        super().__repr__()
        return f"{super().__repr__()} - filtered={self.get_filtered_count()})"

    def __str__(self):
        return self.__repr__()


class ArrayCatalog(Catalog):
    """
    A DB catalog backed by numpy columns (see catalog_arrays).

    It keeps no CompositeObject per catalog listing: ``row(i)`` builds one
    when code asks for it, and keeps the last ``ROW_CACHE_SIZE`` of them, so
    a row on screen stays the same object from frame to frame. Lists of its
    objects are ObjectSequences.

    Runtime state per listing lives next to the read-only columns:
    ``logged`` (bool array), ``verdict`` (the filter result, bool array)
    and the observing-list descriptions (a dict by sequence).
    """

    ROW_CACHE_SIZE = 5000

    def __init__(self, columns: CatalogColumns, logged: np.ndarray):
        self.columns = columns
        self.logged = logged
        self.verdict = np.ones(len(columns), dtype=bool)
        self._list_descriptions: Dict[int, dict] = {}
        self._rows: "OrderedDict[int, CompositeObject]" = OrderedDict()
        self._rows_lock = threading.Lock()
        self._listing_keys: Optional[np.ndarray] = None
        super().__init__(columns.catalog_code, columns.desc, columns.max_sequence)

    # --- rows -------------------------------------------------------------

    def row(self, i: int) -> CompositeObject:
        with self._rows_lock:
            obj = self._rows.get(i)
            if obj is not None:
                self._rows.move_to_end(i)
                return obj
        obj = self._make_row(i)
        with self._rows_lock:
            obj = self._rows.setdefault(i, obj)
            while len(self._rows) > self.ROW_CACHE_SIZE:
                self._rows.popitem(last=False)
        return obj

    def _make_row(self, i: int) -> CompositeObject:
        columns = self.columns
        try:
            mag = MagnitudeObject.from_json(columns.text("mag", i))
            mag_str = mag.calc_two_mag_representation()
        except Exception:
            mag = MagnitudeObject([])
            mag_str = "-"
        sequence = int(columns.sequence[i])
        return CompositeObject(
            id=int(columns.id[i]),
            object_id=int(columns.object_id[i]),
            obj_type=str(columns.obj_type_table[columns.obj_type_codes[i]]),
            ra=float(columns.ra[i]),
            dec=float(columns.dec[i]),
            const=str(columns.const_table[columns.const_codes[i]]),
            size=SizeObject.from_json(columns.text("size", i)),
            mag=mag,
            mag_str=mag_str,
            catalog_code=self.catalog_code,
            sequence=sequence,
            description=columns.text("description", i),
            names=columns.names(i),
            logged=bool(self.logged[i]),
            last_filtered_result=bool(self.verdict[i]),
            list_descriptions=self._list_descriptions.setdefault(sequence, {}),
        )

    def _cached_rows(self) -> List[tuple]:
        with self._rows_lock:
            return list(self._rows.items())

    def column(self, name: str) -> np.ndarray:
        columns = self.columns
        if name in ("ra", "dec", "filter_mag", "object_id", "sequence"):
            return getattr(columns, name)
        if name == "obj_type":
            return columns.obj_type()
        if name == "const":
            return columns.const()
        if name == "logged":
            return self.logged
        if name == "catalog_code":
            return np.full(self.get_count(), self.catalog_code)
        if name == "earth_distance_au":
            return np.full(self.get_count(), NO_DISTANCE)
        if name == "opposition_ordinal":
            return np.full(self.get_count(), NO_OPPOSITION, dtype=np.int64)
        if name == "listing_key":
            if self._listing_keys is None:
                self._listing_keys = (
                    np.int64(catalog_code_id(self.catalog_code)) << 32
                ) + columns.sequence.astype(np.int64)
            return self._listing_keys
        raise KeyError(name)

    # --- the Catalog interface ---------------------------------------------

    def get_objects(self) -> ObjectSequence:
        return ObjectSequence.from_rows(self, np.arange(self.get_count()))

    def get_count(self) -> int:
        return len(self.columns)

    def as_sequence(self, filtered: bool) -> ObjectSequence:
        return self.filtered_objects if filtered else self.get_objects()

    def get_object_by_sequence(self, sequence: int) -> Optional[CompositeObject]:
        sequences = self.columns.sequence
        i = int(np.searchsorted(sequences, sequence))
        if i < len(sequences) and sequences[i] == sequence:
            return self.row(i)
        return None

    def get_object_by_id(self, id: int) -> Optional[CompositeObject]:
        hits = np.flatnonzero(self.columns.id == id)
        return self.row(int(hits[0])) if len(hits) else None

    def check_sequences(self) -> bool:
        sequences = self.columns.sequence
        if len(np.unique(sequences)) != len(sequences):
            logger.error("Duplicate sequence catalog %s!", self.catalog_code)
            return False
        return True

    def _filtered_objects_to_seq(self):
        return self.filtered_objects.column("sequence")

    def _read_only(self, *args):
        raise TypeError(f"catalog {self.catalog_code} is read-only")

    add_object = add_objects = clear_objects = _read_only

    def filter_objects(self) -> ObjectSequence:
        if self.catalog_filter is None:
            return self.filtered_objects
        # Already filtered against the current criteria: reuse the result.
        if self.last_filtered > self.catalog_filter.dirty_time:
            return self.filtered_objects

        self.verdict = self.catalog_filter.evaluate(self.get_objects())
        self.filtered_objects = ObjectSequence.from_rows(
            self, np.flatnonzero(self.verdict)
        )
        self.filtered_objects_seq = self._filtered_objects_to_seq()
        for i, obj in self._cached_rows():
            obj.last_filtered_result = bool(self.verdict[i])
        logger.info(
            "FILTERED %s %d/%d",
            self.catalog_code,
            len(self.filtered_objects),
            self.get_count(),
        )
        self.last_filtered = time.time()
        return self.filtered_objects

    # --- logged, search, names ---------------------------------------------

    def set_logged(self, object_id: int) -> None:
        """Marks every listing of the sky object ``object_id`` logged."""
        rows = np.flatnonzero(self.columns.object_id == object_id)
        if not len(rows):
            return
        self.logged[rows] = True
        for i, obj in self._cached_rows():
            if obj.object_id == object_id:
                obj.logged = True

    def search(self, field: str, pattern: str) -> ObjectSequence:
        """Listings whose names contain ``pattern``: T9 digits for field
        "t9", lower-case text for field "lower"."""
        return ObjectSequence.from_rows(self, self.columns.search(field, pattern))

    def iter_names(self):
        """(name, row) for every name of every listing, in row order."""
        for i in range(self.get_count()):
            for name in self.columns.names(i):
                yield name, i


class Catalogs:
    """Holds all catalogs"""

    def __init__(self, catalogs: List[Catalog]):
        self.__catalogs: List[Catalog] = catalogs
        self.catalog_filter: Union[CatalogFilter, None] = None

    def filter_catalogs(self, catalogs: Optional[List[Catalog]] = None):
        """
        Applies the filter to the given catalogs, or to all catalogs when
        catalogs is None. A screen passes only the catalogs it shows, so
        opening a small catalog does not filter the large ones.

        Staleness (time-sensitive criteria outdated, see
        CatalogFilter.is_stale) is promoted to a dirty bump here, so every
        catalog re-evaluates on its next filter, not just the ones filtered
        now. The bump also records the current alt/az state, so the filter
        is not stale again until time passes.
        """
        if self.catalog_filter is not None and self.catalog_filter.is_stale():
            self.catalog_filter.mark_dirty()
            self.catalog_filter.calc_fast_aa(self.catalog_filter.shared_state)
        for catalog in self.__catalogs if catalogs is None else catalogs:
            catalog.filter_objects()
        if self.catalog_filter is not None:
            self.catalog_filter.clear_catalog_content_dirty()

    def mark_logged(self, obj: CompositeObject) -> None:
        """
        Record that obj was just logged (observed) and invalidate the
        filter, so lists with an observed criterion reflect it on their
        next refresh.  Without an observed criterion no verdict can
        change, so the cached lists are kept.

        Observed status is a sky-object property: sibling listings of
        the same object (M 31 / NGC 224 share an object_id) are marked
        too, matching what check_logged derives from the DB after a
        restart.  Virtual objects stay per listing — their negative
        object_ids are minted per session, so id-keyed propagation
        would cross-mark unrelated objects.
        """
        obj.logged = True
        if obj.object_id is not None and obj.object_id >= 0:
            for catalog in self.__catalogs:
                if isinstance(catalog, ArrayCatalog):
                    catalog.set_logged(obj.object_id)
                    continue
                for sibling in catalog.get_objects():
                    if sibling.object_id == obj.object_id:
                        sibling.logged = True
        if self.catalog_filter is not None and self.catalog_filter.observed not in (
            None,
            "Any",
        ):
            self.catalog_filter.mark_dirty()

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
    ) -> ObjectSequence:
        return ObjectSequence.concat(
            catalog.as_sequence(filtered)
            for catalog in self.get_catalogs(only_selected)
        )

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

    def search_by_t9(self, search_digits: str) -> ObjectSequence:
        """Search catalog objects using keypad digits.

        Uses the keypad letter mapping (including its non-conventional
        layout) to convert object names to their digit representation and
        returns all objects with a name whose digit string contains the
        search pattern.
        """
        return self._search(
            "t9",
            search_digits,
            lambda obj: any(
                search_digits in name_to_t9_digits(name) for name in obj.names
            ),
        )

    def search_by_text(self, search_text: str) -> ObjectSequence:
        pattern = search_text.lower()
        return self._search(
            "lower",
            pattern,
            lambda obj: any(pattern in name.lower() for name in obj.names),
        )

    def _search(self, field: str, pattern: str, matches) -> ObjectSequence:
        """Every catalog's objects that match, in catalog order. An
        ArrayCatalog searches its precomputed text ``field``; other catalogs
        test each object with ``matches``."""
        if not pattern:
            return ObjectSequence()
        parts = []
        for catalog in self.__catalogs:
            if isinstance(catalog, ArrayCatalog):
                parts.append(catalog.search(field, pattern))
            else:
                found = [obj for obj in catalog.get_objects() if matches(obj)]
                parts.append(ObjectSequence.from_objects(found))
        return ObjectSequence.concat(parts)

    def iter_names(self):
        """
        (name, resolve) for every name of every object, in catalog order.
        ``resolve()`` returns the object; for an ArrayCatalog it makes the
        object only when called.
        """
        for catalog in self.__catalogs:
            if isinstance(catalog, ArrayCatalog):
                for name, i in catalog.iter_names():
                    yield name, (lambda c=catalog, i=i: c.row(i))
            else:
                for obj in catalog.get_objects():
                    for name in obj.names:
                        yield name, (lambda o=obj: o)

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
            current=current_state, previous=self._last_state, data=None
        )
        self._last_state = status.current
        return status

    def init_planets(self, dt):
        planet_dict = sf_utils.calc_planets(dt)
        logger.debug(f"starting planet dict {planet_dict}")

        if not planet_dict:
            logger.debug("No GPS lock during initialization - will retry soon")
            return

        sequence = 0
        for name in sf_utils.planet_names:
            planet_data = planet_dict.get(name)
            if name.lower() != "sun" and planet_data:
                self.add_planet(sequence, name, planet_data)
                sequence += 1

        self._virtual_id_manager.mint_ids(self)
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
                    "size": SizeObject([]),
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
                return

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
            self.invalidate_filter_cache()
            if self.catalog_filter is not None:
                self.catalog_filter.mark_catalog_content_dirty()


class CatalogBuilder:
    """
    Opens the DB catalogs from their numpy columns (see catalog_arrays), sets
    their logged state from the observations DB, and adds the planet and
    comet catalogs.
    """

    def build(self, shared_state) -> Catalogs:
        catalog_arrays.remove_old_pickle_cache()
        directory = catalog_arrays.locate()
        obs_db = ObservationsDatabase()
        obs_db.load_observed_objects_cache()
        catalog_list: List[Catalog] = [
            ArrayCatalog(columns, self._logged(columns, obs_db))
            for columns in catalog_arrays.open_catalogs(directory)
        ]
        logger.info(
            "Opened %d catalogs, %d listings, from %s",
            len(catalog_list),
            sum(c.get_count() for c in catalog_list),
            directory,
        )
        all_catalogs = Catalogs(catalog_list)

        # Initialize planet catalog with whatever date we have for now
        # This will be re-initialized on activation of Catalog ui module
        # if we have GPS lock
        planet_catalog: Catalog = PlanetCatalog(
            dt=timez.utc_now(),
            shared_state=shared_state,
        )
        all_catalogs.add(planet_catalog)

        # Import CometCatalog locally to avoid circular import
        from PiFinder.comet_catalog import CometCatalog

        comet_catalog: Catalog = CometCatalog(
            timez.utc_now(),
            shared_state=shared_state,
        )
        all_catalogs.add(comet_catalog)

        from PiFinder.asteroid_catalog import AsteroidCatalog

        asteroid_catalog: Catalog = AsteroidCatalog(
            timez.utc_now(),
            shared_state=shared_state,
        )
        all_catalogs.add(asteroid_catalog)

        assert self.check_catalogs_sequences(all_catalogs) is True
        return all_catalogs

    def check_catalogs_sequences(self, catalogs: Catalogs):
        for catalog in catalogs.get_catalogs(only_selected=False):
            result = catalog.check_sequences()
            if not result:
                logger.error("Duplicate sequence catalog %s!", catalog.catalog_code)
                return False
        return True

    @staticmethod
    def _logged(columns: CatalogColumns, obs_db: ObservationsDatabase) -> np.ndarray:
        """
        Logged state per listing, as ObservationsDatabase.check_logged: a log
        entry for the listing itself, or for any listing of the same sky
        object.
        """
        observed_ids = np.fromiter(obs_db.observed_object_ids, dtype=np.int64)
        observed_sequences = np.array(
            [
                sequence
                for catalog, sequence in obs_db.observed_objects_cache
                if catalog == columns.catalog_code
            ],
            dtype=np.int64,
        )
        return np.isin(columns.object_id, observed_ids) | np.isin(
            columns.sequence, observed_sequences
        )


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
