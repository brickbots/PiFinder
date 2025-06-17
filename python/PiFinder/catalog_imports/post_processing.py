"""
Post-processing utilities for catalog data cleanup and fixes.

This module contains functions that run after catalog loading to fix
data issues and normalize object types across different catalogs.
"""

import logging

# Import shared database object
from .database import objects_db


def fix_object_types():
    """
    Runs some global queries to normalize object types from various catalogs
    """
    logging.info("FIX: Object Types")
    conn, db_c = objects_db.get_conn_cursor()

    type_mappings = {
        "Dark Nebula": "DN",
        "* ": "*",
        "*?": "?",
        "-": "?",
        "": "?",
        "Bright Nebula": "Nb",
        "D*?": "D*",
        "Open Cluster": "OC",
        "Pl": "PN",
        "PD": "PN",
        "Supernova Remnant": "Nb",
    }

    for k, v in type_mappings.items():
        db_c.execute(f"update objects set obj_type = '{v}' where obj_type='{k}'")

    conn.commit()


def fix_m45():
    """
    m45 coordinates are wrong in our NGC source
    """
    logging.info("FIX: m45 location")
    conn, db_c = objects_db.get_conn_cursor()

    db_c.execute(
        "update objects set ra=56.85, dec=24.1167 where "
        "id = (select object_id from catalog_objects "
        "where catalog_code='M' and sequence=45)"
    )

    conn.commit()