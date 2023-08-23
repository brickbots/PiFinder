#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module has functions
for reading / writing
observing lists in skylist
format used by SkySafari
but supported by other
tools
"""
import os
import sqlite3
from textwrap import dedent
from PiFinder import utils
import logging
from PiFinder.db.objects_db import ObjectsDatabase

OBSLIST_DIR = f"{utils.data_dir}/obslists/"

SKYSAFARI_CATALOG_NAMES = {
    "CAL": "C",
    "COL": "Cr",
}

SKYSAFARI_CATALOG_NAMES_INV = {v: k for k, v in SKYSAFARI_CATALOG_NAMES.items()}


def write_list(catalog, name):
    """
    Writes the catalog (list of object records)
    to a file.
    """
    index_num = 0
    with open(OBSLIST_DIR + name + ".skylist", "w") as skylist:
        skylist.write("SkySafariObservingListVersion=3.0\n")
        for obj in catalog:
            catalog_name = SKYSAFARI_CATALOG_NAMES.get(obj.catalog, obj.catalog)
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


def resolve_object(catalog_numbers, db):
    """
    Takes a list of SkySafari catalog
    numbers and tries to find an object
    in our DB which matches
    """
    for catalog_number in catalog_numbers:
        try:
            logging.debug(f"trying to resolve {catalog_number}")
            catalog = catalog_number.split(" ")[0]
            catalog = SKYSAFARI_CATALOG_NAMES_INV.get(catalog, catalog)
            sequence = catalog_number.split(" ")[1].strip()
            sequence = int(sequence)
        except:
            return None

        _object = db.get_catalog_object_by_sequence(catalog, sequence)
        if _object:
            return dict(_object)
    return None


def read_list(name):
    """
    Reads a skylist style observing
    list.  Matches against catalogs
    and returns a catalog list
    """
    db = ObjectsDatabase()

    list_catalog = []
    objects_parsed = 0
    in_object = False
    with open(OBSLIST_DIR + name + ".skylist", "r") as skylist:
        for l in skylist:
            l = l.strip()
            if l == "SkyObject=BeginObject":
                if in_object:
                    print("Encountered object start while in object.  File is corrupt")
                    return {
                        "result": "error",
                        "objects_parsed": objects_parsed,
                        "message": "Bad start tag",
                        "catalog": list_catalog,
                    }

                catalog_numbers = []
                in_object = True

            elif l == "EndObject=SkyObject":
                if not in_object:
                    print(
                        "Encountered object end while not in object.  File is corrupt"
                    )
                    return {
                        "result": "error",
                        "objects_parsed": objects_parsed,
                        "message": "Bad end tag",
                        "catalog": list_catalog,
                    }

                # see if we can resolve an object
                _object = resolve_object(catalog_numbers, db)

                if _object:
                    list_catalog.append(_object)

                objects_parsed += 1
                in_object = False

            elif l.startswith("CatalogNumber"):
                if not in_object:
                    print(
                        "Encountered catalog number while not in object.  File is corrupt"
                    )
                    return {
                        "result": "error",
                        "objects_parsed": objects_parsed,
                        "message": "Bad catalog tag",
                        "catalog": list_catalog,
                    }
                catalog_numbers.append(l.split("=")[1])

            else:
                pass

    db.close()
    return {
        "result": "success",
        "objects_parsed": objects_parsed,
        "message": "Complete",
        "catalog": list_catalog,
    }

def get_lists():
    """
    Returns a list of list names on disk
    """
    obs_files = []
    for filename in os.listdir(OBSLIST_DIR):
        if not filename.startswith(".") and filename.endswith(".skylist"):
            obs_files.append(filename[:-8])

    return obs_files
