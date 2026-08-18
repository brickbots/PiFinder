"""Pickle-based cache for the output of CatalogBuilder._build_composite.

Cache layout under ~/PiFinder_data/cache/catalogs/:
    composite_objects.pkl       — pickled {composite_objects, catalogs_info}
    composite_objects.meta.json — fingerprint for invalidation

The `logged` flag on each CompositeObject is user state; it is reset to False
before pickling and re-applied from the observations DB after load.
"""

from __future__ import annotations

import json
import logging
import pickle
import sys
from typing import Dict, List, Optional, Tuple

from PiFinder.composite_object import CompositeObject
from PiFinder.utils import data_dir, pifinder_db

logger = logging.getLogger("Catalog.Cache")

# Bump when CompositeObject shape, _create_full_composite_object output, or
# the pickled payload structure changes.
# v2: CompositeObject gained `list_descriptions` (external observing lists).
#     Caches pickled at v1 restore objects without that attribute, crashing
#     composed_sections() on the object details screen.
CACHE_VERSION = 2

CACHE_DIR = data_dir / "cache" / "catalogs"
PICKLE_PATH = CACHE_DIR / "composite_objects.pkl"
META_PATH = CACHE_DIR / "composite_objects.meta.json"


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


def load() -> Optional[Tuple[List[CompositeObject], Dict[str, Dict]]]:
    """Return (composite_objects, catalogs_info) if cache is valid, else None.

    Returns None on any failure (missing files, stale fingerprint, corrupt pickle).
    Resets `logged=False` on returned objects — caller must re-apply from obs_db.
    """
    if not PICKLE_PATH.exists() or not META_PATH.exists():
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
        "Loaded catalog cache: %d composite objects from %s",
        len(composite_objects),
        PICKLE_PATH,
    )
    return composite_objects, catalogs_info


def save(
    composite_objects: List[CompositeObject], catalogs_info: Dict[str, Dict]
) -> None:
    """Write the cache. Never raises — logs errors instead.

    Strips `logged` to False so the cache is stable across sessions.
    Writes the pickle atomically via tmp + rename to avoid torn writes.
    """
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

        for obj in composite_objects:
            obj.logged = False

        payload = {
            "composite_objects": composite_objects,
            "catalogs_info": catalogs_info,
        }

        tmp_pkl = PICKLE_PATH.with_suffix(".pkl.tmp")
        with tmp_pkl.open("wb") as f:
            pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
        tmp_pkl.replace(PICKLE_PATH)

        with META_PATH.open("w") as f:
            json.dump(_fingerprint(), f, indent=2)

        logger.info(
            "Catalog cache written: %d composite objects -> %s",
            len(composite_objects),
            PICKLE_PATH,
        )
    except Exception as e:
        logger.error("Failed to write catalog cache: %s", e, exc_info=True)


def clear() -> None:
    """Remove cache files. Used by tests and for manual invalidation."""
    for p in (PICKLE_PATH, META_PATH):
        try:
            p.unlink()
        except FileNotFoundError:
            pass
