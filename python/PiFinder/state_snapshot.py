"""
Shared-memory snapshot of the shared state, for fast reads.

``SharedStateObj`` lives in the multiprocessing manager process, so every read
through its proxy is a socket round trip. During the wait the calling thread
releases the GIL, and a busy thread in the same process can then keep the GIL
for up to the switch interval. The UI makes many such reads per frame.

This module keeps a copy of the frequently read values in one shared-memory
block:

- The manager process is the only writer. After a ``SharedStateObj`` setter
  changes a value, it publishes the value into its **slot**
  (``SnapshotWriter.publish``). The setters and their rules do not change.
- Any process reads all slots with ``StateReader.read()``, which returns a
  ``StateSnapshot``. A read is a memory copy: there is no round trip and the
  GIL is not released.

Each slot has its own ``multiprocessing.Lock``. The values in different slots
are independent, but one value is many fields (a solution holds RA, Dec, roll
and times), so a reader must never copy a slot while it is half written. A
lock that nobody holds is taken with ``sem_trywait`` and keeps the GIL.

Slot layout in the block::

    | version: u64 | length: u32 | payload: pickle bytes |

The writer adds 1 to the version on each write. A reader keeps the last
decoded value per slot and decodes again only when the version changed.

A thread in the manager process writes a heartbeat once a second. A reader
that finds the heartbeat older than ``HEARTBEAT_TIMEOUT`` raises
``SharedStateLost``, the same error that a dead manager gives through the
proxy (see ``state_utils``).
"""

import datetime
import logging
import multiprocessing
import pickle
import struct
import threading
import time
from dataclasses import dataclass, field
from multiprocessing import shared_memory
from typing import Any, Dict, Optional, Protocol, Tuple

import pytz

from PiFinder.state_utils import SharedStateLost

logger = logging.getLogger("SharedState.Snapshot")

BLOCK_NAME = "pifinder_state"

# Maximum pickle size per slot, in bytes. A solution with 30 matched stars
# pickles to about 2.4 KB; SQM details are a dict with tens of keys.
SLOT_SIZES: Dict[str, int] = {
    "heartbeat": 64,
    "power_state": 256,
    "solution": 16384,
    "imu": 4096,
    "location": 4096,
    "datetime": 1024,
    "sqm": 4096,
    "sqm_details": 16384,
    "battery": 4096,
    "hardware": 4096,
    "sats": 1024,
    "gps_comms": 1024,
    "last_image_metadata": 4096,
    "camera_type": 256,
    "camera_lens": 256,
    "optical_train_known": 256,
    "test_mode": 256,
}

_HEADER = struct.Struct("<QI")  # version, payload length

# What a reader gets for a slot that was never written (version 0).
_UNSET = object()
HEARTBEAT_PERIOD = 1.0
HEARTBEAT_TIMEOUT = 5.0


def _layout() -> Dict[str, Tuple[int, int]]:
    """Slot name -> (offset, payload capacity)."""
    layout = {}
    offset = 0
    for slot, size in SLOT_SIZES.items():
        layout[slot] = (offset, size)
        offset += _HEADER.size + size
    return layout


LAYOUT = _layout()
BLOCK_SIZE = sum(_HEADER.size + size for size in SLOT_SIZES.values())


@dataclass
class SnapshotSpec:
    """
    What a process needs to open the block: its name and the slot locks.

    The locks are ``multiprocessing`` locks, so a spec can go to another
    process only as an argument when that process starts (``Process`` args,
    or the manager's ``initargs``).
    """

    name: str
    locks: Dict[str, Any] = field(default_factory=dict)


def _buffer(shm: shared_memory.SharedMemory) -> memoryview:
    buf = shm.buf
    assert buf is not None
    return buf


class ReadableState(Protocol):
    """The read side of the shared state that the catalog filter uses:
    ``SharedStateObj``, ``StateSnapshot`` and ``ui.base.CurrentSnapshot``."""

    def location(self) -> Any: ...

    def datetime(self) -> Any: ...

    def altaz_ready(self) -> bool: ...


class PowerStateSource(Protocol):
    """What ``state_utils.sleep_for_framerate`` reads."""

    def power_state(self) -> Any: ...


class SnapshotBlock:
    """Creates and removes the shared-memory block. Owned by main."""

    def __init__(self, name: str = BLOCK_NAME):
        self.name = name
        self._remove_stale(name)
        self.shm = shared_memory.SharedMemory(name=name, create=True, size=BLOCK_SIZE)
        self.spec = SnapshotSpec(
            name=name, locks={slot: multiprocessing.Lock() for slot in SLOT_SIZES}
        )

    @staticmethod
    def _remove_stale(name: str) -> None:
        """Removes a block that a killed run left behind."""
        try:
            stale = shared_memory.SharedMemory(name=name, track=False)
        except FileNotFoundError:
            return
        logger.warning("Removing a stale state snapshot block %s", name)
        stale.close()
        stale.unlink()

    def close(self) -> None:
        self.shm.close()
        try:
            self.shm.unlink()
        except FileNotFoundError:
            pass


class SnapshotWriter:
    """Writes slots. Used only in the manager process."""

    def __init__(self, spec: SnapshotSpec):
        self._spec = spec
        self._shm = shared_memory.SharedMemory(name=spec.name, track=False)
        self._buf = _buffer(self._shm)

    def publish(self, slot: str, value: Any) -> None:
        payload = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
        offset, capacity = LAYOUT[slot]
        if len(payload) > capacity:
            logger.error(
                "State snapshot slot %s: %d bytes do not fit in %d; slot not changed",
                slot,
                len(payload),
                capacity,
            )
            return
        start = offset + _HEADER.size
        with self._spec.locks[slot]:
            version, _ = _HEADER.unpack_from(self._buf, offset)
            self._buf[start : start + len(payload)] = payload
            _HEADER.pack_into(self._buf, offset, version + 1, len(payload))

    def start_heartbeat(self) -> None:
        def beat():
            while True:
                self.publish("heartbeat", time.monotonic())
                time.sleep(HEARTBEAT_PERIOD)

        threading.Thread(target=beat, name="SnapshotHeartbeat", daemon=True).start()


# The writer of this process, set by attach_writer in the manager process.
_writer: Optional[SnapshotWriter] = None


def attach_writer(spec: SnapshotSpec) -> None:
    """Manager initializer: open the block for writing and start the heartbeat."""
    global _writer
    _writer = SnapshotWriter(spec)
    _writer.start_heartbeat()


def publish(slot: str, value: Any) -> None:
    """Publishes a value when this process is the writer; else does nothing."""
    if _writer is not None:
        _writer.publish(slot, value)


class StateReader:
    """Reads the block. One reader per process; safe to share between threads."""

    def __init__(self, spec: SnapshotSpec):
        self._spec = spec
        self._shm = shared_memory.SharedMemory(name=spec.name, track=False)
        self._buf = _buffer(self._shm)
        self._cache: Dict[str, Tuple[int, Any]] = {}

    def _read_slot(self, slot: str) -> Any:
        offset, _ = LAYOUT[slot]
        start = offset + _HEADER.size
        cached_version, cached_value = self._cache.get(slot, (0, _UNSET))
        with self._spec.locks[slot]:
            version, length = _HEADER.unpack_from(self._buf, offset)
            if version == cached_version:
                return cached_value
            payload = bytes(self._buf[start : start + length])
        value = pickle.loads(payload)
        self._cache[slot] = (version, value)
        return value

    def read(self) -> "StateSnapshot":
        heartbeat = self._read_slot("heartbeat")
        if heartbeat is not _UNSET and time.monotonic() - heartbeat > HEARTBEAT_TIMEOUT:
            raise SharedStateLost("the shared-state manager stopped its heartbeat")
        values = {}
        for slot in SLOT_SIZES:
            if slot == "heartbeat":
                continue
            value = self._read_slot(slot)
            if value is not _UNSET:
                values[slot] = value
        # The solution slot holds (solution, solve_state), so the two always
        # agree.
        if "solution" in values:
            values["solution"], values["solve_state"] = values["solution"]
        return StateSnapshot(values)

    def close(self) -> None:
        self._buf.release()
        self._shm.close()


# Value of each slot before its first write.
DEFAULTS: Dict[str, Any] = {
    "power_state": 1,
    "solution": None,
    "solve_state": None,
    "imu": None,
    "location": None,
    "datetime": None,
    "sqm": None,
    "sqm_details": {},
    "battery": None,
    "hardware": None,
    "sats": None,
    "gps_comms": None,
    "last_image_metadata": None,
    "camera_type": None,
    "camera_lens": None,
    "optical_train_known": True,
    "test_mode": False,
}


class StateSnapshot:
    """
    One view of the shared state. The getters have the same names and return
    the same values as the getters of ``SharedStateObj``, so code that only
    reads state works with either one.

    The values are shared by every user of the same snapshot. Treat them as
    read-only; change state only through the ``SharedStateObj`` setters.

    Tests build one directly: ``StateSnapshot({"solution": solution})``.
    """

    @classmethod
    def from_state(cls, state) -> "StateSnapshot":
        """
        A snapshot of an object with the SharedStateObj getters (the object
        itself or its proxy), read one getter at a time. For tests and tools;
        the app reads the shared-memory block with StateReader.
        """
        values = {
            name: getattr(state, name)() for name in DEFAULTS if name != "datetime"
        }
        now = state.datetime()
        values["datetime"] = None if now is None else (now, time.time())
        return cls(values)

    def __init__(self, values: Optional[Dict[str, Any]] = None):
        self._values = dict(DEFAULTS)
        if values:
            unknown = set(values) - set(DEFAULTS)
            if unknown:
                raise KeyError(f"not snapshot values: {sorted(unknown)}")
            self._values.update(values)

    def power_state(self):
        return self._values["power_state"]

    def solution(self):
        return self._values["solution"]

    def solve_state(self):
        return self._values["solve_state"]

    def imu(self):
        return self._values["imu"]

    def location(self):
        return self._values["location"]

    def sqm(self):
        return self._values["sqm"]

    def sqm_details(self):
        return self._values["sqm_details"]

    def get_sky_brightness(self):
        sqm = self.sqm()
        return sqm.value if sqm is not None else None

    def battery(self):
        return self._values["battery"]

    def hardware(self):
        return self._values["hardware"]

    def sats(self):
        return self._values["sats"]

    def gps_comms(self):
        return self._values["gps_comms"]

    def last_image_metadata(self):
        return self._values["last_image_metadata"]

    def camera_type(self):
        return self._values["camera_type"]

    def camera_lens(self):
        return self._values["camera_lens"]

    def optical_train_known(self):
        return self._values["optical_train_known"]

    def test_mode(self):
        return self._values["test_mode"]

    def datetime(self):
        """The civil datetime, UTC-aware, as ``SharedStateObj.datetime()``:
        the stored time plus the time passed since it was stored."""
        stored = self._values["datetime"]
        if stored is None:
            return None
        dt, stored_at = stored
        return dt + datetime.timedelta(seconds=time.time() - stored_at)

    def utc_datetime(self):
        dt = self.datetime()
        return None if dt is None else dt.astimezone(pytz.utc)

    def local_datetime(self):
        """The datetime in the location's timezone, UTC when unknown."""
        dt = self.datetime()
        if dt is None:
            return None
        location = self.location()
        if location and location.timezone:
            try:
                return dt.astimezone(pytz.timezone(location.timezone))
            except (pytz.exceptions.UnknownTimeZoneError, AttributeError):
                return dt.astimezone(pytz.utc)
        return dt.astimezone(pytz.utc)

    def altaz_ready(self):
        location = self.location()
        return bool(location and location.lock and self.datetime())
