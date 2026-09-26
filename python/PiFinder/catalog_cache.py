"""Pickle-based cache for the output of CatalogBuilder._build_composite.

Cache layout under ~/PiFinder_data/cache/catalogs/:
    composite_objects.pkl          — pickled {composite_objects, catalogs_info}
                                     for the priority catalogs (M, NGC, IC)
    composite_objects.deferred.pkl — the other catalogs, as a sequence of
                                     pickled lists of DEFERRED_CHUNK objects
    composite_objects.meta.json    — fingerprint for invalidation

Startup loads the priority file only. The deferred file loads in the
background. pickle.load holds the GIL until it returns, so the deferred file
is in chunks: the loader yields to the UI thread between two chunks.

The `logged` flag on each CompositeObject is user state; it is reset to False
before pickling and re-applied from the observations DB after load.
"""

from __future__ import annotations

import json
import logging
import pickle
import sys
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

from PiFinder.composite_object import CompositeObject
from PiFinder.utils import data_dir, pifinder_db

logger = logging.getLogger("Catalog.Cache")

# Bump when CompositeObject shape, _create_full_composite_object output, or
# the pickled payload structure changes.
# v2: CompositeObject gained `list_descriptions` (external observing lists).
#     Caches pickled at v1 restore objects without that attribute, crashing
#     composed_sections() on the object details screen.
# v3: the deferred catalogs moved to a separate, chunked file.
CACHE_VERSION = 3

# Catalogs that load before the UI starts. The others load in the background.
PRIORITY_CATALOGS = {"NGC", "IC", "M"}

# Objects per pickled chunk in the deferred file. One chunk holds the GIL for
# about 50 ms on a Pi 4.
DEFERRED_CHUNK = 1000

CACHE_DIR = data_dir / "cache" / "catalogs"
PICKLE_PATH = CACHE_DIR / "composite_objects.pkl"
META_PATH = CACHE_DIR / "composite_objects.meta.json"


def _deferred_path() -> Path:
    return PICKLE_PATH.with_suffix(".deferred.pkl")


def _fingerprint() -> Dict:
    st = pifinder_db.stat()
    return {
        "cache_version": CACHE_VERSION,
        "db_path": str(pifinder_db.resolve()),
        "db_mtime_ns": st.st_mtime_ns,
        "db_size": st.st_size,
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
        "pickle_protocol": pickle.HIGHEST_PROTOCOL,
    }


def load_priority() -> Optional[Tuple[List[CompositeObject], Dict[str, Dict]]]:
    """Return (priority_objects, catalogs_info) if cache is valid, else None.

    Returns None on any failure (missing files, stale fingerprint, corrupt pickle).
    Resets `logged=False` on returned objects — caller must re-apply from obs_db.
    """
    if (
        not PICKLE_PATH.exists()
        or not _deferred_path().exists()
        or not META_PATH.exists()
    ):
        return None
    try:
        with META_PATH.open() as f:
            stored_meta = json.load(f)
    except Exception as e:
        logger.warning("Cache meta unreadable, ignoring cache: %s", e)
        return None

    current_meta = _fingerprint()
    if stored_meta != current_meta:
        logger.info(
            "Catalog cache fingerprint mismatch; will rebuild. stored=%s current=%s",
            stored_meta,
            current_meta,
        )
        return None

    try:
        with PICKLE_PATH.open("rb") as f:
            data = pickle.load(f)
        composite_objects = data["composite_objects"]
        catalogs_info = data["catalogs_info"]
    except Exception as e:
        logger.warning("Cache pickle unreadable, ignoring cache: %s", e)
        return None

    for obj in composite_objects:
        obj.logged = False

    logger.info(
        "Loaded catalog cache: %d priority objects from %s",
        len(composite_objects),
        PICKLE_PATH,
    )
    return composite_objects, catalogs_info


def iter_deferred() -> Iterator[List[CompositeObject]]:
    """Yield the deferred objects one chunk at a time.

    Raises on a missing or corrupt file. Resets `logged=False` on the objects.
    """
    with _deferred_path().open("rb") as f:
        while True:
            try:
                chunk = pickle.load(f)
            except EOFError:
                return
            for obj in chunk:
                obj.logged = False
            yield chunk


def load() -> Optional[Tuple[List[CompositeObject], Dict[str, Dict]]]:
    """Return (all composite_objects, catalogs_info) if cache is valid, else None."""
    cached = load_priority()
    if cached is None:
        return None
    composite_objects, catalogs_info = cached
    try:
        for chunk in iter_deferred():
            composite_objects.extend(chunk)
    except Exception as e:
        logger.warning("Deferred cache unreadable, ignoring cache: %s", e)
        return None
    return composite_objects, catalogs_info


def save(
    composite_objects: List[CompositeObject], catalogs_info: Dict[str, Dict]
) -> None:
    """Write the cache. Never raises — logs errors instead.

    Strips `logged` to False so the cache is stable across sessions.
    Writes each pickle atomically via tmp + rename to avoid torn writes.
    The meta file is written last, so a torn save leaves no valid cache.
    """
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        META_PATH.unlink(missing_ok=True)

        priority: List[CompositeObject] = []
        deferred: List[CompositeObject] = []
        for obj in composite_objects:
            obj.logged = False
            if obj.catalog_code in PRIORITY_CATALOGS:
                priority.append(obj)
            else:
                deferred.append(obj)

        payload = {
            "composite_objects": priority,
            "catalogs_info": catalogs_info,
        }

        tmp_pkl = PICKLE_PATH.with_suffix(".pkl.tmp")
        with tmp_pkl.open("wb") as f:
            pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
        tmp_pkl.replace(PICKLE_PATH)

        deferred_path = _deferred_path()
        tmp_deferred = deferred_path.with_suffix(".tmp")
        with tmp_deferred.open("wb") as f:
            for start in range(0, len(deferred), DEFERRED_CHUNK):
                pickle.dump(
                    deferred[start : start + DEFERRED_CHUNK],
                    f,
                    protocol=pickle.HIGHEST_PROTOCOL,
                )
        tmp_deferred.replace(deferred_path)

        with META_PATH.open("w") as f:
            json.dump(_fingerprint(), f, indent=2)

        logger.info(
            "Catalog cache written: %d priority and %d deferred objects -> %s",
            len(priority),
            len(deferred),
            CACHE_DIR,
        )
    except Exception as e:
        logger.error("Failed to write catalog cache: %s", e, exc_info=True)


def clear() -> None:
    """Remove cache files. Used by tests and for manual invalidation."""
    for p in (PICKLE_PATH, _deferred_path(), META_PATH):
        try:
            p.unlink()
        except FileNotFoundError:
            pass
