"""
Saguaro Astronomy Club (SAC) catalog loaders for PiFinder.

This module loads various SAC catalogs including asterisms, multistars, and red stars.
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
    trim_string,
)

# Import shared database object
from .database import objects_db

logger = logging.getLogger("SACLoaders")


def load_sac_asterisms():
    """Load the SAC Asterisms catalog"""
    logging.info("Loading SAC Asterisms")
    catalog = "SaA"
    conn, _ = objects_db.get_conn_cursor()
    delete_catalog_from_database(catalog)
    insert_catalog(catalog, Path(utils.astro_data_dir, "sac.desc"))

    saca = Path(utils.astro_data_dir, "SAC_Asterisms_Ver32_Fence.txt")
    sequence = 0

    # Prepare objects for batch insertion
    objects_to_insert = []
    # Create shared ObjectFinder to avoid recreating for each object
    from .catalog_import_utils import ObjectFinder

    shared_finder = ObjectFinder()

    with open(saca, "r") as df:
        df.readline()
        obj_type = "Ast"
        for line in tqdm(list(df), leave=False):
            dfs = line.split("|")
            dfs = [d.strip() for d in dfs]
            other_names = dfs[1].strip()
            if other_names == "":
                continue
            else:
                sequence += 1

            logger.debug(f"---------------> SAC Asterisms {sequence=} <---------------")
            # const = dfs[2].strip()
            ra = dfs[3].strip()
            dec = dfs[4].strip()
            mag = dfs[5].strip()
            if mag == "none":
                mag = MagnitudeObject([])
            else:
                mag = MagnitudeObject([float(mag)])
            size = (
                dfs[6]
                .replace(" ", "")
                .replace("X", "x")
                .replace("deg", "°")
                .replace("d", "°")
            )
            desc = dfs[9].strip()

            ra = ra.split()
            ra_h = int(ra[0])
            ra_m = float(ra[1])
            ra_deg = ra_to_deg(ra_h, ra_m, 0)

            dec = dec.split(" ")
            dec_d = int(dec[0])
            dec_m = float(dec[1])
            dec_deg = dec_to_deg(dec_d, dec_m, 0)

            new_object = NewCatalogObject(
                object_type=obj_type,
                catalog_code=catalog,
                sequence=sequence,
                ra=ra_deg,
                dec=dec_deg,
                mag=mag,
                size=size,
                description=desc,
                aka_names=[other_names],
            )
            objects_to_insert.append(new_object)

    # Batch insert all objects
    objects_db.bulk_mode = True
    # Set up shared finder for performance
    NewCatalogObject.set_shared_finder(shared_finder)
    try:
        for obj in tqdm(
            objects_to_insert, desc="Inserting SAC Asterisms objects", leave=False
        ):
            obj.insert()
        conn.commit()
    finally:
        objects_db.bulk_mode = False
        NewCatalogObject.clear_shared_finder()

    insert_catalog_max_sequence(catalog)


def load_sac_multistars():
    """Load the SAC Multistars catalog"""
    logging.info("Loading SAC Multistars")
    catalog = "SaM"
    conn, _ = objects_db.get_conn_cursor()
    delete_catalog_from_database(catalog)
    sam_path = Path(utils.astro_data_dir, "SAC_Multistars_Ver40")
    insert_catalog(catalog, sam_path / "sacm.desc")
    saca = sam_path / "SAC_DBL40_Fence.txt"
    sequence = 0

    # Prepare objects for batch insertion
    objects_to_insert = []
    # Create shared ObjectFinder to avoid recreating for each object
    from .catalog_import_utils import ObjectFinder

    shared_finder = ObjectFinder()

    with open(saca, "r") as df:
        df.readline()
        obj_type = "D*"
        for line in tqdm(list(df), leave=False):
            dfs = line.split("|")
            # Early skip for empty records
            if len(dfs) < 12:
                continue

            # Only process the name field we need
            name = [dfs[2].strip()]
            other_names = dfs[6].strip().split(";")
            name.extend(other_names)
            name = [trim_string(x.strip()) for x in name if x != ""]
            if not name:
                continue
            sequence += 1

            # Removed debug logging for performance
            # Process only the fields we need (avoid full strip)
            ra = dfs[3].strip()
            dec = dfs[4].strip()
            components = dfs[5].strip()

            # Optimize magnitude processing
            mag1, mag2 = dfs[7].strip(), dfs[8].strip()
            mag_list = []
            for m in [mag1, mag2]:
                if m and m != "none":
                    if utils.is_number(m):
                        mag_list.append(float(m))
                    else:
                        mag_list.append(m)
            mag = MagnitudeObject(mag_list)

            sep = dfs[9].strip()
            pa = dfs[10].strip()
            desc = dfs[11].strip()
            desc += f"\nComponents: {components}" if components else ""
            desc += f"\nPA: {pa}°" if pa else ""

            ra = ra.split()
            ra_h = int(ra[0])
            ra_m = float(ra[1])
            ra_deg = ra_to_deg(ra_h, ra_m, 0)

            dec = dec.split(" ")
            dec_d = int(dec[0])
            dec_m = float(dec[1])
            dec_deg = dec_to_deg(dec_d, dec_m, 0)

            new_object = NewCatalogObject(
                object_type=obj_type,
                catalog_code=catalog,
                sequence=sequence,
                ra=ra_deg,
                dec=dec_deg,
                mag=mag,
                size=sep,
                description=desc,
                aka_names=name,
            )
            objects_to_insert.append(new_object)

    # Batch insert all objects
    objects_db.bulk_mode = True
    # Set up shared finder for performance
    NewCatalogObject.set_shared_finder(shared_finder)
    try:
        for obj in tqdm(
            objects_to_insert, desc="Inserting SAC Multistars objects", leave=False
        ):
            obj.insert()
        conn.commit()
    finally:
        objects_db.bulk_mode = False
        NewCatalogObject.clear_shared_finder()

    insert_catalog_max_sequence(catalog)


def load_sac_redstars():
    """Load the SAC Red Stars catalog"""
    logging.info("Loading SAC Redstars")
    catalog = "SaR"
    conn, _ = objects_db.get_conn_cursor()
    delete_catalog_from_database(catalog)

    sam_path = Path(utils.astro_data_dir, "SAC_RedStars_Ver20")
    insert_catalog(catalog, sam_path / "sacr.desc")
    sac = sam_path / "SAC_RedStars_ver20_FENCE.TXT"
    sequence = 0

    # Prepare objects for batch insertion
    objects_to_insert = []
    # Create shared ObjectFinder to avoid recreating for each object
    from .catalog_import_utils import ObjectFinder

    shared_finder = ObjectFinder()

    with open(sac, "r") as df:
        df.readline()
        obj_type = "D*"
        for line in tqdm(list(df), leave=False):
            dfs = line.split("|")
            dfs = [d.strip() for d in dfs]
            name = [dfs[1].strip()]
            other_names = dfs[2].strip().split(";")
            name.extend(other_names)
            name = [trim_string(x.strip()) for x in name if x != ""]
            if not name:
                continue
            else:
                sequence += 1

            logger.debug(f"---------------> SAC Red Stars {sequence=} <---------------")
            # const = dfs[3].strip()
            ra = dfs[4].strip()
            dec = dfs[5].strip()
            size = ""
            mag = dfs[6].strip()
            if mag == "none":
                mag = MagnitudeObject([])
            else:
                mag = MagnitudeObject([float(mag)])
            bv = dfs[7].strip()
            spec = dfs[8].strip()
            notes = dfs[9].strip()
            desc = notes
            desc += f"\nB-V: {bv}"
            desc += f", Spec: {spec}"

            ra = ra.split(" ")
            ra_h = int(ra[0])
            ra_m = float(ra[1])
            ra_deg = ra_to_deg(ra_h, ra_m, 0)

            dec = dec.split(" ")
            dec_d = int(dec[0])
            dec_m = float(dec[1])
            dec_deg = dec_to_deg(dec_d, dec_m, 0)

            new_object = NewCatalogObject(
                object_type=obj_type,
                catalog_code=catalog,
                sequence=sequence,
                ra=ra_deg,
                dec=dec_deg,
                mag=mag,
                size=size,
                description=desc,
                aka_names=name,
            )
            objects_to_insert.append(new_object)

    # Batch insert all objects
    objects_db.bulk_mode = True
    # Set up shared finder for performance
    NewCatalogObject.set_shared_finder(shared_finder)
    try:
        for obj in tqdm(
            objects_to_insert, desc="Inserting SAC RedStars objects", leave=False
        ):
            obj.insert()
        conn.commit()
    finally:
        objects_db.bulk_mode = False
        NewCatalogObject.clear_shared_finder()

    insert_catalog_max_sequence(catalog)
