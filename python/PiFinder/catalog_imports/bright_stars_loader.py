"""
Bright stars catalog loader for PiFinder.

This module loads the catalog of bright named stars.
"""

import logging
from pathlib import Path
from tqdm import tqdm

import PiFinder.utils as utils
from PiFinder.composite_object import MagnitudeObject
from PiFinder.calc_utils import ra_to_deg, dec_to_deg
from .catalog_import_utils import (
    NewCatalogObject,
    delete_catalog_from_database,
    insert_catalog,
    insert_catalog_max_sequence,
)

# Import shared database object
from .database import objects_db

logger = logging.getLogger("BrightStarsLoader")


def load_bright_stars():
    """Load the catalog of bright named stars"""
    logging.info("Loading Bright Named Stars")
    catalog = "Str"
    conn, _ = objects_db.get_conn_cursor()
    delete_catalog_from_database(catalog)
    insert_catalog(catalog, Path(utils.astro_data_dir, "Str.desc"))

    bstr = Path(utils.astro_data_dir, "bright_stars.csv")

    # Prepare objects for batch insertion
    objects_to_insert = []
    with open(bstr, "r") as df:
        # skip header
        df.readline()
        obj_type = "* "
        for line in tqdm(list(df), leave=False):
            dfs = line.split(",")
            dfs = [d.strip() for d in dfs]
            other_names = dfs[1:3]
            sequence = int(dfs[0])

            logger.debug(f"---------------> Bright Stars {sequence=} <---------------")
            size = ""
            # const = dfs[2].strip()
            desc = ""

            ra_h = int(dfs[3])
            ra_m = float(dfs[4])
            ra_deg = ra_to_deg(ra_h, ra_m, 0)

            dec_d = int(dfs[5])
            dec_m = float(dfs[6])
            dec_deg = dec_to_deg(dec_d, dec_m, 0)

            mag = MagnitudeObject([float(dfs[7].strip())])
            # const = dfs[8]

            new_object = NewCatalogObject(
                object_type=obj_type,
                catalog_code=catalog,
                sequence=int(sequence),
                ra=ra_deg,
                dec=dec_deg,
                mag=mag,
                size=size,
                description=desc,
                aka_names=other_names,
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
            objects_to_insert, desc="Inserting Bright Stars objects", leave=False
        ):
            obj.insert()
        conn.commit()
    finally:
        objects_db.bulk_mode = False
        NewCatalogObject.clear_shared_finder()

    insert_catalog_max_sequence(catalog)
