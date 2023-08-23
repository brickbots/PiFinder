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

OBSLIST_DIR = f"{utils.data_dir}/obslists/"
DB_PATH = f"{utils.pifinder_dir}/astro_data/pifinder_objects.db"

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


def resolve_object(catalog_numbers, connection):
    """
    Takes a list of SkySafari catalog
    numbers and tries to find an object
    in our DB which matches
    """
    for catalog_number in catalog_numbers:
        catalog = catalog_number.split(" ")[0]
        catalog = SKYSAFARI_CATALOG_NAMES_INV.get(catalog, catalog)
        sequence = catalog_number.split(" ")[1].strip()
        try:
            sequence = int(sequence)
        except ValueError:
            return None

        _object = connection.execute(
            f"""
                    select * from
                    objects
                    where catalog='{catalog}'
                    and sequence={sequence}

                """
        ).fetchone()
        if _object:
            return dict(_object)
    print("Failed")
    return None


def read_list(name):
    """
    Reads a skylist style observing
    list.  Matches against catalogs
    and returns a catalog list
    """

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

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
                _object = resolve_object(catalog_numbers, conn)

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

    return {
        "result": "success",
        "objects_parsed": objects_parsed,
        "message": "Complete",
        "catalog": list_catalog,
    }

    cat_objects = self.conn.execute(
        f"""
        SELECT * from objects
        where catalog='{catalog_name}'
        order by sequence
    """
    ).fetchall()


def get_lists():
    """
    Returns a list of list names on disk
    """
    obs_files = []
    for filename in os.listdir(OBSLIST_DIR):
        if not filename.startswith(".") and filename.endswith(".skylist"):
            obs_files.append(filename[:-8])

    return obs_files
