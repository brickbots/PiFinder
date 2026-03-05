"""
Caldwell catalog loader for PiFinder.

This module loads the Caldwell catalog of deep-sky objects.
"""

import logging
from pathlib import Path
from tqdm import tqdm

import PiFinder.utils as utils
from PiFinder.composite_object import MagnitudeObject, SizeObject
from PiFinder.calc_utils import ra_to_deg, dec_to_deg
from .catalog_import_utils import (
    NewCatalogObject,
    delete_catalog_from_database,
    insert_catalog,
    insert_catalog_max_sequence,
    add_space_after_prefix,
)

# Import shared database object
from .database import objects_db


def _parse_caldwell_size(raw: str) -> SizeObject:
    """Parse Caldwell size like '14', '0.6', '19 x 7' — all arcminutes."""
    if not raw:
        return SizeObject([])
    parts = raw.lower().replace("x", " ").split()
    values = []
    for p in parts:
        try:
            values.append(float(p))
        except ValueError:
            pass
    if not values:
        return SizeObject([])
    return SizeObject.from_arcmin(*values)


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
            other_names = add_space_after_prefix(dfs[1])
            obj_type = dfs[2]
            mag = dfs[4]
            if mag == "--":
                mag = MagnitudeObject([])
            else:
                mag = MagnitudeObject([float(mag)])
            size = _parse_caldwell_size(dfs[5][5:].strip())
            ra_h = int(dfs[6])
            ra_m = float(dfs[7])
            ra_deg = ra_to_deg(ra_h, ra_m, 0)

            dec_sign = dfs[8]
            dec_deg = int(dfs[9])
            dec_m = float(dfs[10])
            if dec_sign == "-":
                dec_deg *= -1

            dec_deg = dec_to_deg(dec_deg, dec_m, 0)
            new_object = NewCatalogObject(
                object_type=obj_type,
                catalog_code=catalog,
                sequence=int(sequence),
                ra=ra_deg,
                dec=dec_deg,
                mag=mag,
                size=size,
                description="",
                aka_names=[other_names],
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
