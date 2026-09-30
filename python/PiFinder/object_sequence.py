"""
A read-only list of catalog objects that makes objects only when asked.

The DB catalogs keep their listings as numpy columns (see catalog_arrays),
not as one ``CompositeObject`` per listing. An ``ObjectSequence`` stores only
references: for each position, a **source** (a catalog, or a plain list of
objects) and a row in that source. It builds a ``CompositeObject`` only for
the positions that code reads with ``seq[i]`` or by iteration.

Filtering, sorting and nearby ranking work on whole columns
(``seq.column("ra")``) and give a new sequence with ``take`` or ``mask``, so
a list of 150,000 listings never becomes 150,000 Python objects.

A source has ``len()``, ``row(i)`` (the object for row i) and
``column(name)`` (a numpy array with one value per row). The column names
are in ``COLUMNS``.
"""

import threading
from collections.abc import Sequence
from typing import Any, Dict, Iterable, List, Optional

import numpy as np

from PiFinder.composite_object import CompositeObject

# Columns that every source provides.
COLUMNS = (
    "ra",
    "dec",
    "filter_mag",
    "object_id",
    "sequence",
    "obj_type",
    "const",
    "logged",
    "catalog_code",
    "listing_key",
)

_code_ids: Dict[str, int] = {}
_code_ids_lock = threading.Lock()


def catalog_code_id(catalog_code: str) -> int:
    """A small integer for a catalog code, the same for the whole process."""
    with _code_ids_lock:
        return _code_ids.setdefault(catalog_code, len(_code_ids))


def listing_keys(codes: np.ndarray, sequences: np.ndarray) -> np.ndarray:
    """One int64 per catalog listing, from its catalog code and sequence:
    equal keys mean the same listing (not only the same sky object)."""
    code_ids = np.array([catalog_code_id(str(c)) for c in codes], dtype=np.int64)
    return (code_ids << 32) + sequences.astype(np.int64)


class ListSource:
    """A source over a fixed list of objects (planets, comets, observing
    lists, search results of the list catalogs)."""

    def __init__(self, objects: Iterable[CompositeObject]):
        self._objects: List[CompositeObject] = list(objects)

    def __len__(self) -> int:
        return len(self._objects)

    def row(self, i: int) -> CompositeObject:
        return self._objects[i]

    def column(self, name: str) -> np.ndarray:
        objects = self._objects
        if name in ("ra", "dec"):
            return _floats([getattr(obj, name) for obj in objects])
        if name == "filter_mag":
            return np.array([obj.mag.filter_mag for obj in objects], dtype=float)
        if name in ("object_id", "sequence"):
            return np.array([getattr(obj, name) for obj in objects], dtype=np.int64)
        if name in ("obj_type", "const", "catalog_code"):
            return np.array([getattr(obj, name) or "" for obj in objects], dtype=str)
        if name == "logged":
            return np.array([bool(obj.logged) for obj in objects], dtype=bool)
        if name == "listing_key":
            return listing_keys(self.column("catalog_code"), self.column("sequence"))
        raise KeyError(name)


def _floats(values: list) -> np.ndarray:
    """RA/Dec values as floats. None and values that are not numbers are NaN."""
    try:
        return np.array(values, dtype=float)
    except (TypeError, ValueError):
        result = np.full(len(values), np.nan)
        for i, value in enumerate(values):
            try:
                result[i] = float(value)
            except (TypeError, ValueError):
                pass
        return result


_EMPTY_ROWS = np.zeros(0, dtype=np.int64)


class ObjectSequence(Sequence):
    """
    A read-only list of CompositeObjects over one or more sources.

    It behaves like a list for reading: ``len``, ``seq[i]``, ``seq[a:b]``,
    iteration, ``in``, ``index(obj)`` (first object with the same
    ``object_id``, as ``list.index`` with ``CompositeObject.__eq__``) and
    ``==`` against another sequence or a list.
    """

    __slots__ = ("_sources", "_src", "_rows")

    def __init__(
        self,
        sources: tuple = (),
        src: Optional[np.ndarray] = None,
        rows: Optional[np.ndarray] = None,
    ):
        self._sources = tuple(sources)
        self._rows = _EMPTY_ROWS if rows is None else np.asarray(rows, dtype=np.int64)
        self._src = (
            np.zeros(len(self._rows), dtype=np.int16)
            if src is None
            else np.asarray(src, dtype=np.int16)
        )

    # --- construction -----------------------------------------------------

    @classmethod
    def of(cls, items: Any) -> "ObjectSequence":
        """``items`` as an ObjectSequence: returned as-is when it is one."""
        if isinstance(items, ObjectSequence):
            return items
        return cls.from_objects(items if items is not None else [])

    @classmethod
    def from_objects(cls, objects: Iterable[CompositeObject]) -> "ObjectSequence":
        source = ListSource(objects)
        return cls((source,), None, np.arange(len(source), dtype=np.int64))

    @classmethod
    def from_rows(cls, source: Any, rows: np.ndarray) -> "ObjectSequence":
        return cls((source,), None, rows)

    @classmethod
    def concat(cls, parts: Iterable["ObjectSequence"]) -> "ObjectSequence":
        sources: List[Any] = []
        srcs = []
        rows = []
        for part in parts:
            if not len(part):
                continue
            mapping = np.empty(len(part._sources), dtype=np.int16)
            for k, source in enumerate(part._sources):
                for j, known in enumerate(sources):
                    if known is source:
                        mapping[k] = j
                        break
                else:
                    sources.append(source)
                    mapping[k] = len(sources) - 1
            srcs.append(mapping[part._src])
            rows.append(part._rows)
        if not rows:
            return cls()
        return cls(tuple(sources), np.concatenate(srcs), np.concatenate(rows))

    # --- reading ----------------------------------------------------------

    def __len__(self) -> int:
        return len(self._rows)

    def __getitem__(self, key):
        if isinstance(key, slice):
            return self.take(np.arange(len(self))[key])
        position = int(key)
        if position < 0:
            position += len(self)
        if not 0 <= position < len(self):
            raise IndexError("ObjectSequence index out of range")
        source = self._sources[self._src[position]]
        return source.row(int(self._rows[position]))

    def __iter__(self):
        for position in range(len(self)):
            yield self[position]

    def __contains__(self, obj) -> bool:
        return self._first(obj) is not None

    def index(self, obj, start: int = 0, stop: Optional[int] = None) -> int:
        position = self._first(obj, start, stop)
        if position is None:
            raise ValueError(f"{obj!r} is not in the sequence")
        return position

    def _first(self, obj, start: int = 0, stop: Optional[int] = None):
        object_id = getattr(obj, "object_id", None)
        if object_id is None or not len(self):
            return None
        hits = np.flatnonzero(self.column("object_id")[start:stop] == object_id)
        return int(hits[0]) + start if len(hits) else None

    def copy(self) -> "ObjectSequence":
        """The sequence is read-only, so a copy is the sequence itself."""
        return self

    def __eq__(self, other) -> bool:
        if isinstance(other, (ObjectSequence, list, tuple)):
            return len(self) == len(other) and all(a == b for a, b in zip(self, other))
        return NotImplemented

    def __ne__(self, other) -> bool:
        result = self.__eq__(other)
        return result if result is NotImplemented else not result

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        return f"ObjectSequence(len={len(self)}, sources={len(self._sources)})"

    # --- columns and selection -------------------------------------------

    def column(self, name: str) -> np.ndarray:
        """The column ``name`` for every position, in sequence order."""
        if not self._sources:
            return np.zeros(0)
        if len(self._sources) == 1:
            return self._sources[0].column(name)[self._rows]
        parts = []
        for k, source in enumerate(self._sources):
            positions = np.flatnonzero(self._src == k)
            parts.append((positions, source.column(name)[self._rows[positions]]))
        result = np.empty(len(self), dtype=_common_dtype([v for _, v in parts]))
        for positions, values in parts:
            result[positions] = values
        return result

    def take(self, positions) -> "ObjectSequence":
        """The objects at ``positions``, in that order."""
        positions = np.asarray(positions, dtype=np.int64)
        return ObjectSequence(
            self._sources, self._src[positions], self._rows[positions]
        )

    def mask(self, keep: np.ndarray) -> "ObjectSequence":
        """The objects where ``keep`` is True, in sequence order."""
        return self.take(np.flatnonzero(keep))


def _common_dtype(arrays: List[np.ndarray]) -> np.dtype:
    """One dtype that holds every array: the longest string type for text
    columns, else numpy's common type."""
    text = [a.dtype.itemsize // 4 for a in arrays if a.dtype.kind == "U"]
    if text:
        return np.dtype(f"<U{max(text)}")
    return np.result_type(*[a.dtype for a in arrays])
