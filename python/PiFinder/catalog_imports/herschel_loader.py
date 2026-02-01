"""
Herschel 400 catalog loader for PiFinder.

This module loads the Herschel 400 catalog which references NGC objects.
"""

import logging
from pathlib import Path
from tqdm import tqdm

import PiFinder.utils as utils
from .catalog_import_utils import (
    delete_catalog_from_database,
    insert_catalog,
    insert_catalog_max_sequence,
)

# Import shared database object
from .database import objects_db

logger = logging.getLogger("Herschel400Loader")


def load_herschel400():
    """
    Load the Herschel 400 catalog.

    This TSV is from a web scrape of the
    Saguaro Astro Club h400 list as noted in their
    master DB
    """
    logging.info("Loading Herschel 400")
    catalog = "H"
    conn, _ = objects_db.get_conn_cursor()
    delete_catalog_from_database(catalog)
    insert_catalog(catalog, Path(utils.astro_data_dir, "herschel400.desc"))

    hcat = Path(utils.astro_data_dir, "herschel400.tsv")
    sequence = 0

    # Enable bulk mode for batch processing
    objects_db.bulk_mode = True
    try:
        with open(hcat, "r") as df:
            # skip column headers
            df.readline()
            for line in tqdm(list(df), leave=False):
                dfs = line.split("\t")
                dfs = [d.strip() for d in dfs]
                NGC_sequence = dfs[0]
                h_name = dfs[7]
                h_desc = dfs[8]
                sequence += 1

                logger.debug(
                    f"---------------> Herschel 400 {sequence=} <---------------"
                )

                object_id = objects_db.get_catalog_object_by_sequence(
                    "NGC", NGC_sequence
                )["id"]
                objects_db.insert_name(object_id, h_name, catalog)
                objects_db.insert_catalog_object(object_id, catalog, sequence, h_desc)
        conn.commit()
    finally:
        objects_db.bulk_mode = False

    insert_catalog_max_sequence(catalog)
