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
from PiFinder.calc_utils import sf_utils
from PiFinder.catalog_base import VirtualIDManager
from PiFinder.catalogs import Catalogs
from PiFinder.composite_object import CompositeObject
from PiFinder.ui.ui_utils import normalize
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
    return ObsListEntry(
        name=obj.display_name,
        ra=obj.ra,
        dec=obj.dec,
        obj_type=obj.obj_type,
        mag=obj.mag,
        size=obj.size,
        catalog_code=obj.catalog_code,
        sequence=obj.sequence,
        description=obj.description,
    )


CATALOG_ALIASES: dict = {
    "Messier": "M",
    "Caldwell": "C",
    "Collinder": "Cr",
}


def resolve_object(catalog_numbers, catalogs: Catalogs):
    """
    Takes a list of catalog number strings
    (e.g. ["M 31", "NGC 224"]) and tries to
    find a matching object in the PiFinder DB.

    Pure lookup: returns the shared catalog object (or None). Callers must not
    mutate its catalog description; per-list text goes in `list_descriptions`.
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
                return _object
    return None


def _coordinate_object(entry: ObsListEntry, index: int) -> CompositeObject:
    """
    Creates a CompositeObject from an ObsListEntry's coordinates
    when catalog resolution fails.
    """
    const = ""
    if entry.ra is not None and entry.dec is not None:
        try:
            const = sf_utils.radec_to_constellation(entry.ra, entry.dec)
        except Exception:
            pass
    virtual_id = VirtualIDManager.mint_id()
    return CompositeObject(
        id=virtual_id,
        object_id=virtual_id,
        ra=entry.ra,
        dec=entry.dec,
        obj_type=entry.obj_type or "?",
        const=const,
        size=entry.size,
        # Coordinate objects always carry catalog code OBS (see Catalog
        # CONTEXT.md). A name like "CGCS135" parses to a bogus catalog code that
        # resolves to nothing, so don't let it leak onto the object -- it breaks
        # display and the OBS whitelist. The original designation lives in names.
        catalog_code="OBS",
        sequence=index + 1,
        # No description fallback to the name: that just duplicates the name
        # (shown as the title) in the description area.
        description=entry.description,
        names=[entry.name],
        mag=entry.mag,
    )


# Latin genitive constellation names (as used in variable/Bayer designations
# like "VY Andromedae") -> IAU 3-letter abbreviation. PiFinder stores the short
# form ("VY And"), so a name is normalized to this before matching.
CONSTELLATION_GENITIVE_ABBR: dict = {
    "andromedae": "And",
    "antliae": "Ant",
    "apodis": "Aps",
    "aquarii": "Aqr",
    "aquilae": "Aql",
    "arae": "Ara",
    "arietis": "Ari",
    "aurigae": "Aur",
    "bootis": "Boo",
    "caeli": "Cae",
    "camelopardalis": "Cam",
    "cancri": "Cnc",
    "canum venaticorum": "CVn",
    "canis majoris": "CMa",
    "canis minoris": "CMi",
    "capricorni": "Cap",
    "carinae": "Car",
    "cassiopeiae": "Cas",
    "centauri": "Cen",
    "cephei": "Cep",
    "ceti": "Cet",
    "chamaeleontis": "Cha",
    "circini": "Cir",
    "columbae": "Col",
    "comae berenices": "Com",
    "coronae australis": "CrA",
    "coronae borealis": "CrB",
    "corvi": "Crv",
    "crateris": "Crt",
    "crucis": "Cru",
    "cygni": "Cyg",
    "delphini": "Del",
    "doradus": "Dor",
    "draconis": "Dra",
    "equulei": "Equ",
    "eridani": "Eri",
    "fornacis": "For",
    "geminorum": "Gem",
    "gruis": "Gru",
    "herculis": "Her",
    "horologii": "Hor",
    "hydrae": "Hya",
    "hydri": "Hyi",
    "indi": "Ind",
    "lacertae": "Lac",
    "leonis": "Leo",
    "leonis minoris": "LMi",
    "leporis": "Lep",
    "librae": "Lib",
    "lupi": "Lup",
    "lyncis": "Lyn",
    "lyrae": "Lyr",
    "mensae": "Men",
    "microscopii": "Mic",
    "monocerotis": "Mon",
    "muscae": "Mus",
    "normae": "Nor",
    "octantis": "Oct",
    "ophiuchi": "Oph",
    "orionis": "Ori",
    "pavonis": "Pav",
    "pegasi": "Peg",
    "persei": "Per",
    "phoenicis": "Phe",
    "pictoris": "Pic",
    "piscium": "Psc",
    "piscis austrini": "PsA",
    "puppis": "Pup",
    "pyxidis": "Pyx",
    "reticuli": "Ret",
    "sagittae": "Sge",
    "sagittarii": "Sgr",
    "scorpii": "Sco",
    "sculptoris": "Scl",
    "scuti": "Sct",
    "serpentis": "Ser",
    "sextantis": "Sex",
    "tauri": "Tau",
    "telescopii": "Tel",
    "trianguli": "Tri",
    "trianguli australis": "TrA",
    "tucanae": "Tuc",
    "ursae majoris": "UMa",
    "ursae minoris": "UMi",
    "velorum": "Vel",
    "virginis": "Vir",
    "volantis": "Vol",
    "vulpeculae": "Vul",
}


def _normalize_designation(name: str):
    """
    If `name` ends in a Latin genitive constellation ("VY Andromedae"),
    return it with the IAU abbreviation ("VY And"); otherwise None.
    """
    parts = name.strip().split()
    if len(parts) < 2:
        return None
    # Match the longest trailing genitive first ("Canum Venaticorum").
    for take in (2, 1):
        if len(parts) > take:
            genitive = " ".join(parts[-take:]).lower()
            abbr = CONSTELLATION_GENITIVE_ABBR.get(genitive)
            if abbr:
                return " ".join(parts[:-take] + [abbr])
    return None


def _build_name_index(catalogs: Catalogs) -> dict:
    """
    Map every catalog object's names to the object, for name-based resolution.
    Names are normalized (ui_utils.normalize) so spacing/case variants like
    "NGC 6205" and "NGC6205" collapse together. First writer wins, so a name
    resolves to one stable object.
    """
    index: dict = {}
    for obj in catalogs.get_objects(only_selected=False, filtered=False):
        for nm in obj.names:
            key = normalize(nm)
            if key and key not in index:
                index[key] = obj
    return index


def resolve_by_name(name: str, name_index: dict):
    """
    Resolve an entry to a catalog object by normalized name (ui_utils.normalize:
    case-, space- and hyphen-insensitive), also trying a constellation-normalized
    variant ("VY Andromedae" -> "VY And"). Returns the shared catalog object or
    None.
    """
    if not name:
        return None
    keys = [normalize(name)]
    designation = _normalize_designation(name)
    if designation:
        keys.append(normalize(designation))
    for key in keys:
        obj = name_index.get(key)
        if obj:
            return obj
    return None


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
    name_index = None  # built lazily, only if an entry needs name resolution
    errors = 0
    last_error: Exception | None = None
    try:
        for i, entry in enumerate(obs_list.entries):
            try:
                _object = None

                # Try catalog resolution with catalog_names (skylist multi-name)
                if entry.catalog_names:
                    _object = resolve_object(entry.catalog_names, catalogs)
                elif entry.catalog_code and entry.sequence:
                    _object = resolve_object(
                        [f"{entry.catalog_code} {entry.sequence}"], catalogs
                    )

                # No catalog match: try resolving by object name (handles lists
                # that identify objects only by name, e.g. "VY Andromedae").
                if not _object and entry.name:
                    if name_index is None:
                        name_index = _build_name_index(catalogs)
                    _object = resolve_by_name(entry.name, name_index)

                # Resolved objects are shared catalog instances: record this
                # list's description under the list name rather than clobbering
                # the catalog one.
                if _object and entry.description:
                    _object.list_descriptions[obs_list.name] = entry.description

                # Fall back to coordinate-based object
                if not _object and (entry.ra or entry.dec):
                    _object = _coordinate_object(entry, i)

                if _object:
                    list_catalog.append(_object)
            except Exception as e:
                # One malformed entry (bad coords, a lookup that errors) must not
                # sink the whole list: log it, skip it, keep resolving the rest.
                errors += 1
                last_error = e
                logger.warning(
                    "Skipping observing list entry %d (%r): %s",
                    i,
                    getattr(entry, "name", "?"),
                    e,
                )
    except Exception as e:
        # Safety net for a failure outside the per-entry guard (e.g. the entries
        # iterable itself raises). Mirror the file-read error-dict contract so
        # UIObsList.key_right shows its message instead of crashing the UI. Use
        # len(list_catalog), not len(obs_list.entries): if entries was the thing
        # that raised, touching it again here would re-raise and defeat the net.
        logger.critical("Failed to resolve observing list %s: %s", name, e)
        return {
            "result": "error",
            "objects_parsed": len(list_catalog),
            "message": str(e),
            "catalog_objects": list_catalog,
        }

    # Every entry raised: this is systemic (e.g. the catalog DB is unavailable),
    # not a few bad rows. Report it as an error rather than a silent "0 objects".
    if obs_list.entries and errors == len(obs_list.entries):
        logger.critical(
            "Failed to resolve any entries in observing list %s: %s",
            name,
            last_error,
        )
        return {
            "result": "error",
            "objects_parsed": len(obs_list.entries),
            "message": str(last_error),
            "catalog_objects": list_catalog,
        }

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

    When multiple files share the same stem (e.g. Messier.skylist and
    Messier.csv), an extension tag is appended to the display name:
    "Messier [skylist]".
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
            display = f"{f['stem']} [{f['tag']}]"
        entries.append({"name": display, "type": "file", "path": f["path"]})
    return entries
