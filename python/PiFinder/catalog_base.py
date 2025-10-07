"""
Base catalog classes shared across catalog implementations.
Contains the core catalog functionality without filtering logic.
"""
import logging
import threading
from enum import Enum
from typing import Optional, Dict, Any, NamedTuple, List, Union, Callable

logger = logging.getLogger("CatalogBase")


class CatalogState(Enum):
    """Status codes for catalog readiness"""

    READY = "ready"  # Catalog is ready, empty list is due to filtering
    NO_GPS = "no_gps"  # Waiting for GPS lock
    DOWNLOADING = "downloading"  # Downloading data files
    CALCULATING = "calculating"  # Calculating/initializing
    ERROR = "error"  # Error state


class CatalogStatus(NamedTuple):
    """
    Catalog status with state transition tracking.

    current: Current state of the catalog
    previous: Previous state (for detecting transitions)
    data: Optional dict with additional state-specific data (e.g., progress info)
    """

    current: CatalogState
    previous: CatalogState
    data: Optional[Dict[str, Any]] = None


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


def catalog_base_id_sort(obj):
    return obj.id


def catalog_base_sequence_sort(obj):
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
        self.__objects: List = []
        self.id_to_pos: Dict[int, int] = {}
        self.sequence_to_pos: Dict[int, int] = {}

    def get_objects(self) -> ROArrayWrapper:
        return ROArrayWrapper(self.__objects)

    def _get_objects(self) -> List:
        return self.__objects

    def add_object(self, obj):
        self._add_object(obj)
        self._sort_objects()
        self._update_id_to_pos()
        self._update_sequence_to_pos()
        assert self.check_sequences()

    def _add_object(self, obj):
        self.__objects.append(obj)
        if obj.sequence > self.max_sequence:
            self.max_sequence = obj.sequence

    def add_objects(self, objects: List):
        objects_copy = objects.copy()
        for obj in objects_copy:
            self._add_object(obj)
        self._sort_objects()
        self._update_id_to_pos()
        self._update_sequence_to_pos()
        assert self.check_sequences()

    def _sort_objects(self):
        self.__objects.sort(key=self.sort)

    def get_object_by_id(self, id: int):
        if id in self.id_to_pos:
            return self.__objects[self.id_to_pos[id]]
        else:
            return None

    def get_object_by_sequence(self, sequence: int):
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
        self.sequence_to_pos = {
            obj.sequence: i for i, obj in enumerate(self.__objects)
        }

    def __repr__(self):
        return f"Catalog({self.catalog_code=}, {self.max_sequence=}, count={self.get_count()})"

    def __str__(self):
        return self.__repr__()


class VirtualIDManager:
    """Manages virtual ID assignment for non-DB catalog objects"""

    virtual_id_lock = threading.Lock()
    virtual_id_low = 0

    @staticmethod
    def assign_virtual_object_ids(catalog, low_id: int) -> int:
        """
        Assigns virtual object_ids for non-DB objects. Return new low.
        """
        for obj in catalog.get_objects():
            low_id -= 1
            obj.object_id = low_id
        return low_id


class TimerMixin:
    """Provides timer functionality via composition"""

    def __init__(self):
        self.timer: Optional[threading.Timer] = None
        self.is_running: bool = False
        self.time_delay_seconds: Union[int, Callable[[], int]] = 300  # Default 5 minutes
        self.do_timed_task: Optional[Callable] = None  # Will be bound to catalog's method
        logger.debug("TimerMixin initialized")

    def start_timer(self) -> None:
        """Start the timer if it's not already running"""
        if not self.is_running:
            self.is_running = True
            self._schedule_next_run()
            logger.debug("Timer started")

    def _schedule_next_run(self) -> None:
        """Schedule the next run of the timed task"""
        delay: int
        if callable(self.time_delay_seconds):
            delay = self.time_delay_seconds()
        else:
            delay = self.time_delay_seconds
        self.timer = threading.Timer(float(delay), self._run)
        self.timer.start()

    def _run(self) -> None:
        """Execute the timed task in a separate thread and reschedule if still running"""
        threading.Thread(target=self._execute_task).start()
        if self.is_running:
            self._schedule_next_run()

    def _execute_task(self) -> None:
        """Execute the timed task"""
        try:
            if self.do_timed_task:
                self.do_timed_task()
            else:
                logger.warning("TimerMixin: No do_timed_task method bound")
        except Exception as e:
            logger.error(f"Error in timed task: {e}", exc_info=True)

    def stop(self) -> None:
        """Stop the timer"""
        self.is_running = False
        if self.timer:
            self.timer.cancel()
            self.timer = None

    def __del__(self) -> None:
        """Ensure the timer is stopped when the object is deleted"""
        self.stop()
