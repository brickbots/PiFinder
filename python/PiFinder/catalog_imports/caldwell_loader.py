"""
Caldwell catalog loader for PiFinder.

This module loads the Caldwell catalog of deep-sky objects.
"""

import logging
import re
from pathlib import Path
from typing import List

from tqdm import tqdm

import PiFinder.utils as utils
from PiFinder.composite_object import MagnitudeObject
from PiFinder.calc_utils import ra_to_deg, dms_to_dec
from .catalog_import_utils import (
    NewCatalogObject,
    delete_catalog_from_database,
    insert_catalog,
    insert_catalog_max_sequence,
    parse_arcmin_size,
    parse_designation,
)

# Import shared database object
from .database import objects_db

# Two numbers in one other-name: "NGC 869/884", "NGC 6992/5", "NGC 2237-9".
_TWO_NUMBERS_RE = re.compile(r"(.*?)(\d+)\s*[/-]\s*(\d+)")


def caldwell_akas(other_name: str) -> List[str]:
    """The designations in caldwell.dat's other-name field.

    "none" names nothing. A designation parse_designation reads stays whole,
    so "Sh2-155" is Sh2 155. Two numbers are split, the second replacing the
    first's trailing digits: "NGC 6992/5" is NGC 6992 and NGC 6995, and
    "NGC 2237-9" is NGC 2237 and NGC 2239.
    """
    name = other_name.strip()
    if not name or name.lower() == "none":
        return []
    if parse_designation(name) is not None:
        return [name]
    match = _TWO_NUMBERS_RE.fullmatch(name)
    if match is None:
        return [name]
    prefix, first, second = match.groups()
    second = first[: max(len(first) - len(second), 0)] + second
    return [f"{prefix}{first}", f"{prefix}{second}"]


def load_caldwell():
    """Load the Caldwell catalog"""
    logging.info("Loading Caldwell")
    catalog = "C"
    conn, _ = objects_db.get_conn_cursor()
    delete_catalog_from_database(catalog)
    insert_catalog(catalog, Path(utils.astro_data_dir, "caldwell.desc"))
    data = Path(utils.astro_data_dir, "caldwell.dat")

    # Prepare objects for batch insertion
    objects_to_insert = []
    with open(data, "r") as df:
        for line in tqdm(list(df), leave=False):
            dfs = line.split("\t")
            sequence = dfs[0].strip()
            logging.debug(f"<----------------- Caldwell {sequence=} ----------------->")
            aka_names = caldwell_akas(dfs[1])
            obj_type = dfs[2]
            mag = dfs[4]
            if mag == "--":
                mag = MagnitudeObject([])
            else:
                mag = MagnitudeObject([float(mag)])
            size = parse_arcmin_size(dfs[5][5:].strip())
            ra_h = int(dfs[6])
            ra_m = float(dfs[7])
            ra_deg = ra_to_deg(ra_h, ra_m, 0)

            # The sign is a column of its own, so a declination between -1°
            # and 0° would stay south (caldwell.dat has none today).
            dec_deg = dms_to_dec(dfs[8], int(dfs[9]), float(dfs[10]), 0)
            new_object = NewCatalogObject(
                object_type=obj_type,
                catalog_code=catalog,
                sequence=int(sequence),
                ra=ra_deg,
                dec=dec_deg,
                mag=mag,
                size=size,
                description="",
                aka_names=aka_names,
            )
            objects_to_insert.append(new_object)

    # Batch insert all objects with shared finder
    objects_db.bulk_mode = True

    # Create shared ObjectFinder to avoid recreating for each object
    from .catalog_import_utils import ObjectFinder

    shared_finder = ObjectFinder()
    NewCatalogObject.set_shared_finder(shared_finder)

    try:
        for obj in tqdm(
            objects_to_insert, desc="Inserting Caldwell objects", leave=False
        ):
            obj.insert()
        conn.commit()
    finally:
        objects_db.bulk_mode = False
        NewCatalogObject.clear_shared_finder()

    insert_catalog_max_sequence(catalog)
