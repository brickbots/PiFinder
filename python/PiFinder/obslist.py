#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Observing list management for PiFinder.

Reads observing lists in any supported format (via obslist_formats),
resolves entries against the PiFinder catalog database, and provides
the list as CompositeObject instances for the UI.

Writing always produces SkySafari .skylist format.
"""

from __future__ import annotations

import os
import logging
from PiFinder import utils
from PiFinder.catalogs import Catalogs
from PiFinder.composite_object import CompositeObject, MagnitudeObject
from PiFinder.obslist_formats import (
    ObsList,
    ObsListEntry,
    SKYSAFARI_CATALOG_NAMES_INV,
    SUPPORTED_EXTENSIONS,
    read_file as formats_read_file,
    write_skylist,
)

logger = logging.getLogger("Observation.List")

OBSLIST_DIR = f"{utils.data_dir}/obslists/"


def write_list(catalog_objects, name):
    """
    Writes the list of catalog objects
    to a .skylist file.
    """
    entries = [_entry_from_composite(obj) for obj in catalog_objects]
    obs_list = ObsList(name=name, entries=entries)
    content = write_skylist(obs_list)
    with open(OBSLIST_DIR + name + ".skylist", "w") as f:
        f.write(content)


def _entry_from_composite(obj: CompositeObject) -> ObsListEntry:
    """Convert a CompositeObject to an ObsListEntry."""
    mag_val = obj.mag.filter_mag if obj.mag.filter_mag != MagnitudeObject.UNKNOWN_MAG else None
    return ObsListEntry(
        name=obj.display_name,
        ra=obj.ra,
        dec=obj.dec,
        obj_type=obj.obj_type,
        mag=mag_val,
        catalog_code=obj.catalog_code,
        sequence=obj.sequence,
        description=obj.description,
    )


CATALOG_ALIASES: dict = {
    "Messier": "M",
    "Caldwell": "C",
    "Collinder": "Cr",
}


def resolve_object(catalog_numbers, catalogs: Catalogs, comment: str = ""):
    """
    Takes a list of catalog number strings
    (e.g. ["M 31", "NGC 224"]) and tries to
    find a matching object in the PiFinder DB.
    """
    for catalog_number in catalog_numbers:
        parts = catalog_number.strip().split(" ", 1)
        catalog = SKYSAFARI_CATALOG_NAMES_INV.get(parts[0], parts[0])
        catalog = CATALOG_ALIASES.get(catalog, catalog)
        try:
            sequence = int(parts[1].strip())
        except (ValueError, IndexError):
            sequence = None

        if sequence is not None:
            _object = catalogs.get_object(catalog, sequence)
            if _object:
                if comment and not _object.description:
                    _object.description = comment
                return _object
    return None


def _coordinate_object(entry: ObsListEntry, index: int) -> CompositeObject:
    """
    Creates a CompositeObject from an ObsListEntry's coordinates
    when catalog resolution fails.
    """
    return CompositeObject(
        id=-(index + 1),
        object_id=-(index + 1),
        ra=entry.ra,
        dec=entry.dec,
        catalog_code=entry.catalog_code or "OBS",
        sequence=entry.sequence or (index + 1),
        description=entry.description or entry.name,
        names=[entry.name],
        mag=MagnitudeObject([entry.mag] if entry.mag is not None else []),
    )


def read_list(catalogs: Catalogs, name):
    """
    Reads an observing list file in any supported format.
    Resolves entries against catalogs and returns a catalog list.
    """
    filepath = os.path.join(OBSLIST_DIR, name)

    try:
        obs_list = formats_read_file(filepath)
    except Exception as e:
        logger.critical("Failed to read observing list %s: %s", name, e)
        return {
            "result": "error",
            "objects_parsed": 0,
            "message": str(e),
            "catalog_objects": [],
        }

    list_catalog: list = []
    for i, entry in enumerate(obs_list.entries):
        _object = None

        # Try catalog resolution with catalog_names (skylist multi-name support)
        if entry.catalog_names:
            _object = resolve_object(entry.catalog_names, catalogs, entry.description)
        elif entry.catalog_code and entry.sequence:
            _object = resolve_object(
                [f"{entry.catalog_code} {entry.sequence}"],
                catalogs,
                entry.description,
            )

        # Fall back to coordinate-based object
        if not _object and (entry.ra or entry.dec):
            _object = _coordinate_object(entry, i)

        if _object:
            list_catalog.append(_object)

    return {
        "result": "success",
        "objects_parsed": len(obs_list.entries),
        "message": "Complete",
        "catalog_objects": list_catalog,
    }


def get_lists(subdir=""):
    """
    Returns entries (folders and observing list files) under OBSLIST_DIR/subdir.
    Each entry is a dict with 'name', 'type' ('folder' or 'file'),
    and either 'subdir' (for folders) or 'path' (for files).

    When multiple files share the same stem (e.g. CSOG.skylist and CSOG.csv),
    an extension tag is appended to the display name: "CSOG [skylist]".
    """
    target = os.path.join(OBSLIST_DIR, subdir)
    if not os.path.isdir(target):
        return []

    folders = []
    files = []
    stem_counts: dict = {}
    for name in sorted(os.listdir(target)):
        if name.startswith("."):
            continue
        full = os.path.join(target, name)
        if os.path.isdir(full):
            folders.append(
                {"name": name, "type": "folder", "subdir": os.path.join(subdir, name)}
            )
        else:
            for ext in SUPPORTED_EXTENSIONS:
                if name.endswith(ext):
                    stem = name[: -len(ext)]
                    tag = ext[1:]  # strip the dot
                    files.append(
                        {
                            "stem": stem,
                            "tag": tag,
                            "type": "file",
                            "path": os.path.join(subdir, name),
                        }
                    )
                    stem_counts[stem] = stem_counts.get(stem, 0) + 1
                    break

    entries = list(folders)
    for f in files:
        display = f["stem"]
        if stem_counts.get(f["stem"], 1) > 1:
            display = f'{f["stem"]} [{f["tag"]}]'
        entries.append({"name": display, "type": "file", "path": f["path"]})
    return entries
