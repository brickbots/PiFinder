"""
Post-processing utilities for catalog data cleanup and fixes.

This module contains functions that run after catalog loading to fix
data issues and normalize object types across different catalogs.
"""

import logging
from pathlib import Path

# Import shared database object
from .database import objects_db
from .catalog_import_utils import NewCatalogObject
from PiFinder.composite_object import MagnitudeObject
import PiFinder.utils as utils

logger = logging.getLogger("PostProcessing")


def _load_messier_names():
    """
    Load Messier common names from messier_names.dat file.

    Returns:
        dict: Mapping of {messier_number: [list_of_common_names]}
    """
    messier_names = {}
    messier_names_file = (
        Path(utils.astro_data_dir) / "ngc_ic_m/messier/messier_names.dat"
    )

    if not messier_names_file.exists():
        logging.warning(f"Messier names file not found: {messier_names_file}")
        return messier_names

    try:
        with open(messier_names_file, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue

                parts = line.split("\t")
                if len(parts) < 2:
                    continue

                # Extract M number (e.g., "M1" -> 1)
                m_designation = parts[0].strip()
                if not m_designation.startswith("M"):
                    continue

                try:
                    m_number = int(m_designation[1:])
                except ValueError:
                    continue

                # Extract common names (everything after NGC reference)
                common_names = []
                if len(parts) >= 3:
                    names_part = parts[2].strip()
                    if names_part:
                        # Split on commas and clean up each name
                        for name in names_part.split(","):
                            name = name.strip()
                            if name:
                                common_names.append(name)

                messier_names[m_number] = common_names

        logger.debug(f"Loaded {len(messier_names)} Messier objects with common names")

    except Exception as e:
        logging.error(f"Error reading messier_names.dat: {e}")

    return messier_names


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
    Add M24, M40, M45, and M102 which are missing from the main catalog loading
    """
    logging.info("ADDING: Missing Messier objects M24, M40, M45, and M102")

    # Load Messier common names mapping
    messier_names_map = _load_messier_names()

    # M40 - Winnecke 4 (Double star in Ursa Major)
    # RA: 12h 22m 12.5272s = 185.552°, Dec: +58° 4′ 58.549″ = +58.083°
    m40_aka_names = ["Winnecke 4", "WNC 4"]
    # Add common names from messier_names.dat if available
    if 40 in messier_names_map:
        m40_aka_names.extend(messier_names_map[40])

    m40 = NewCatalogObject(
        object_type="D*",
        catalog_code="M",
        sequence=40,
        ra=185.552,  # 12h 22m 12.5272s in degrees
        dec=58.083,  # +58° 4′ 58.549″ in degrees
        mag=MagnitudeObject([9.9]),  # Average of components A (9.64) and B (10.11)
        size="0.1'",
        description="Winnecke 4 double star",
        aka_names=m40_aka_names,
    )
    m40.insert()

    # M45 - Pleiades (Open cluster in Taurus)
    # RA: 03h 47m 24s = 56.85°, Dec: +24° 07′ 00″ = +24.117°
    m45_aka_names = ["Cr 42", "Mel 22"]  # Keep catalog designations
    # Add common names from messier_names.dat if available
    if 45 in messier_names_map:
        m45_aka_names.extend(messier_names_map[45])

    m45 = NewCatalogObject(
        object_type="OC",
        catalog_code="M",
        sequence=45,
        ra=56.85,  # 03h 47m 24s in degrees
        dec=24.117,  # +24° 07′ 00″ in degrees
        mag=MagnitudeObject([1.6]),
        size="120'",  # 2° = 120 arcminutes
        description="Pleiades open cluster",
        aka_names=m45_aka_names,
    )
    m45.insert()

    # M24 - Sagittarius Star Cloud (no NGC equivalent, it's a dense star field)
    # RA: 18h 18m 24s = 274.6°, Dec: -18° 24′ 00″ = -18.4°
    m24_aka_names = ["Sagittarius Star Cloud"]
    # Add common names from messier_names.dat if available
    if 24 in messier_names_map:
        m24_aka_names.extend(messier_names_map[24])

    m24 = NewCatalogObject(
        object_type="Ast",  # Asterism/Star cloud
        catalog_code="M",
        sequence=24,
        ra=274.6,  # 18h 18m 24s in degrees
        dec=-18.4,  # -18° 24′ 00″ in degrees
        mag=MagnitudeObject([4.6]),  # Visual magnitude of the brightest part
        size="90'",  # About 1.5 degrees
        description="Sagittarius Star Cloud",
        aka_names=m24_aka_names,
    )
    m24.insert()

    # M102 - Usually identified with NGC 5866 (Spindle Galaxy)
    # RA: 15h 06m 29.5s = 226.623°, Dec: +55° 45′ 48″ = +55.763°
    m102_aka_names = ["NGC 5866", "Spindle Galaxy"]
    # Add common names from messier_names.dat if available
    if 102 in messier_names_map:
        m102_aka_names.extend(messier_names_map[102])

    m102 = NewCatalogObject(
        object_type="Gx",  # Galaxy
        catalog_code="M",
        sequence=102,
        ra=226.623,  # 15h 06m 29.5s in degrees
        dec=55.763,  # +55° 45′ 48″ in degrees
        mag=MagnitudeObject([10.7]),
        size="5.2'x2.3'",
        description="Spindle Galaxy (controversial Messier object)",
        aka_names=m102_aka_names,
    )
    m102.insert()

    logging.info(
        "ADDED: M24 (Sagittarius Star Cloud), M40 (Winnecke 4), M45 (Pleiades), and M102 (NGC 5866)"
    )
