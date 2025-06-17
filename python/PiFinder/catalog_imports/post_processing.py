"""
Post-processing utilities for catalog data cleanup and fixes.

This module contains functions that run after catalog loading to fix
data issues and normalize object types across different catalogs.
"""

import logging

# Import shared database object
from .database import objects_db
from .catalog_import_utils import NewCatalogObject
from PiFinder.composite_object import MagnitudeObject


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


def add_missing_messier_objects():
    """
    Add M40 and M45 which are missing from the Steinicke catalog
    """
    logging.info("ADDING: Missing Messier objects M40 and M45")
    
    # M40 - Winnecke 4 (Double star in Ursa Major)
    # RA: 12h 22m 12.5272s = 185.552°, Dec: +58° 4′ 58.549″ = +58.083°
    m40 = NewCatalogObject(
        object_type="D*",
        catalog_code="M", 
        sequence=40,
        ra=185.552,  # 12h 22m 12.5272s in degrees
        dec=58.083,  # +58° 4′ 58.549″ in degrees
        mag=MagnitudeObject([9.9]),  # Average of components A (9.64) and B (10.11)
        size="0.1'",
        description="Winnecke 4 double star",
        aka_names=["Winnecke 4", "WNC 4"]
    )
    m40.insert()
    
    # M45 - Pleiades (Open cluster in Taurus)
    # RA: 03h 47m 24s = 56.85°, Dec: +24° 07′ 00″ = +24.117°
    m45 = NewCatalogObject(
        object_type="OC",
        catalog_code="M",
        sequence=45, 
        ra=56.85,   # 03h 47m 24s in degrees
        dec=24.117, # +24° 07′ 00″ in degrees
        mag=MagnitudeObject([1.6]),
        size="120'",  # 2° = 120 arcminutes
        description="Pleiades open cluster",
        aka_names=["Pleiades", "Seven Sisters", "Cr 42", "Mel 22"]
    )
    m45.insert()
    
    logging.info("ADDED: M40 (Winnecke 4) and M45 (Pleiades)")


