#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module reads and writes observing
lists in the .skylist format used by
SkySafari.

Supported skylist fields per SkyObject:
  - CatalogNumber  (one or more): resolved against PiFinder catalogs
  - EndObjectRA    (optional): RA in decimal hours (J2000)
  - EndObjectDec   (optional): Dec in decimal degrees (J2000)
  - Comment        (optional): stored as the object description

Objects can be specified by catalog reference (CatalogNumber) or by
coordinates (EndObjectRA/EndObjectDec).  When both are present, catalog
resolution is attempted first.  Objects with neither are skipped.
"""

from __future__ import annotations

import os
import logging
from textwrap import dedent
from PiFinder import utils
from PiFinder.catalogs import Catalogs
from PiFinder.composite_object import CompositeObject, MagnitudeObject

logger = logging.getLogger("Observation.List")

OBSLIST_DIR = f"{utils.data_dir}/obslists/"

SKYSAFARI_CATALOG_NAMES = {
    "CAL": "C",
    "COL": "Cr",
}

SKYSAFARI_CATALOG_NAMES_INV = {v: k for k, v in SKYSAFARI_CATALOG_NAMES.items()}


def write_list(catalog_objects, name):
    """
    Writes the list of catalog objects
    to a file.
    """
    index_num = 0
    with open(OBSLIST_DIR + name + ".skylist", "w") as skylist:
        skylist.write("SkySafariObservingListVersion=3.0\n")
        for obj in catalog_objects:
            catalog_name = SKYSAFARI_CATALOG_NAMES.get(
                obj.catalog_code, obj.catalog_code
            )
            catalog_number = f"{catalog_name} {obj.sequence}"
            entry_text = dedent(
                f"""
                SkyObject=BeginObject
                    ObjectID=4,-1,-1
                    CatalogNumber={catalog_number}
                    DefaultIndex={index_num}
                EndObject=SkyObject
                """
            ).strip()
            skylist.write(entry_text + "\n")
            index_num += 1


def resolve_object(catalog_numbers, catalogs: Catalogs, comment: str = ""):
    """
    Takes a list of SkySafari catalog
    numbers and tries to find an object
    in our DB which matches.
    If comment is provided and the object
    has no description, use it.
    """
    for catalog_number in catalog_numbers:
        parts = catalog_number.strip().split(" ", 1)
        catalog = SKYSAFARI_CATALOG_NAMES_INV.get(parts[0], parts[0])
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


def _make_coordinate_object(
    ra_hours: float,
    dec_degrees: float,
    catalog_numbers: list,
    comment: str,
    index: int,
) -> CompositeObject:
    """
    Creates a CompositeObject from EndObjectRA/EndObjectDec
    when catalog resolution fails.  EndObjectRA is in decimal
    hours, so we convert to degrees for CompositeObject.
    """
    display_name = catalog_numbers[0].strip() if catalog_numbers else f"OBJ {index + 1}"
    return CompositeObject(
        id=-(index + 1),
        object_id=-(index + 1),
        ra=ra_hours * 15.0,
        dec=dec_degrees,
        catalog_code="OBS",
        sequence=index + 1,
        description=comment or display_name,
        names=[display_name],
        mag=MagnitudeObject([]),
    )


def read_list(catalogs: Catalogs, name):
    """
    Reads a skylist style observing
    list.  Matches against catalogs
    and returns a catalog list
    """

    list_catalog: list = []
    catalog_numbers: list = []
    comment: str = ""
    end_ra: float | None = None
    end_dec: float | None = None
    objects_parsed = 0
    in_object = False
    with open(OBSLIST_DIR + name + ".skylist", "r") as skylist:
        for line in skylist:
            line = line.strip()
            if line == "SkyObject=BeginObject":
                if in_object:
                    logger.critical(
                        "Encountered object start while in object.  File is corrupt"
                    )
                    return {
                        "result": "error",
                        "objects_parsed": objects_parsed,
                        "message": "Bad start tag",
                        "catalog_objects": list_catalog,
                    }

                catalog_numbers = []
                comment = ""
                end_ra = None
                end_dec = None
                in_object = True

            elif line == "EndObject=SkyObject":
                if not in_object:
                    logger.critical(
                        "Encountered object end while not in object.  File is corrupt"
                    )
                    return {
                        "result": "error",
                        "objects_parsed": objects_parsed,
                        "message": "Bad end tag",
                        "catalog_objects": list_catalog,
                    }

                _object = resolve_object(catalog_numbers, catalogs, comment)

                if not _object and end_ra is not None and end_dec is not None:
                    _object = _make_coordinate_object(
                        end_ra, end_dec, catalog_numbers, comment, objects_parsed
                    )

                if _object:
                    list_catalog.append(_object)

                objects_parsed += 1
                in_object = False

            elif line.startswith("CatalogNumber="):
                if not in_object:
                    logger.critical(
                        "Encountered catalog number while not in object.  File is corrupt"
                    )
                    return {
                        "result": "error",
                        "objects_parsed": objects_parsed,
                        "message": "Bad catalog tag",
                        "catalog_objects": list_catalog,
                    }
                catalog_numbers.append(line.split("=", 1)[1])

            elif line.startswith("Comment="):
                if in_object:
                    comment = line.split("=", 1)[1].strip()

            elif line.startswith("EndObjectRA="):
                if in_object:
                    try:
                        end_ra = float(line.split("=", 1)[1])
                    except ValueError:
                        pass

            elif line.startswith("EndObjectDec="):
                if in_object:
                    try:
                        end_dec = float(line.split("=", 1)[1])
                    except ValueError:
                        pass

    return {
        "result": "success",
        "objects_parsed": objects_parsed,
        "message": "Complete",
        "catalog_objects": list_catalog,
    }


def get_lists():
    """
    Returns a list of list names on disk
    """
    if not os.path.isdir(OBSLIST_DIR):
        return []
    obs_files = []
    for filename in os.listdir(OBSLIST_DIR):
        if not filename.startswith(".") and filename.endswith(".skylist"):
            obs_files.append(filename[:-8])

    return obs_files
