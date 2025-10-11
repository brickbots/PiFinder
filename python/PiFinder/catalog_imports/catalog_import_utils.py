"""
Shared utilities for catalog import operations.

This module contains common classes and functions used by all catalog loaders.
"""

import logging
import re
from typing import Dict, Optional
from dataclasses import dataclass, field
from tqdm import tqdm

from PiFinder.composite_object import MagnitudeObject
from PiFinder.ui.ui_utils import normalize
from PiFinder import calc_utils
from PiFinder.db.objects_db import ObjectsDatabase
from PiFinder.db.observations_db import ObservationsDatabase

# Global database objects (will be initialized by the main import script)
objects_db: Optional[ObjectsDatabase] = None
observations_db: Optional[ObservationsDatabase] = None


@dataclass
class NewCatalogObject:
    object_type: str
    catalog_code: str
    sequence: int
    ra: float
    dec: float
    mag: MagnitudeObject
    object_id: int = 0
    size: str = ""
    description: str = ""
    aka_names: list[str] = field(default_factory=list)
    surface_brightness: float = 0.0

    # Class-level shared finder for performance optimization
    _shared_finder: Optional["ObjectFinder"] = None

    @classmethod
    def set_shared_finder(cls, finder: "ObjectFinder") -> None:
        """Set a shared ObjectFinder instance for all objects to use during bulk operations"""
        cls._shared_finder = finder

    @classmethod
    def clear_shared_finder(cls) -> None:
        """Clear the shared ObjectFinder instance"""
        cls._shared_finder = None

    def insert(self, find_object_id=True):
        """
        Inserts object into DB
        """
        # sanity checks
        if type(self.aka_names) is not list:
            raise TypeError("Aka names not list")

        # Check to see if this object matches one in the DB already
        # This is a costly operation, so disabled for 'source' catalogs like WDS
        if find_object_id:
            self.find_object_id()

        try:
            # Enable bulk mode to prevent individual commits
            objects_db.bulk_mode = True
            objects_db.conn.execute("BEGIN TRANSACTION")

            if self.object_id == 0:
                # Did not find a match, first insert object info
                self.find_constellation()
                assert isinstance(self.mag, MagnitudeObject)

                self.object_id = objects_db.insert_object(
                    self.object_type,
                    self.ra,
                    self.dec,
                    self.constellation,
                    self.size,
                    self.mag.to_json(),
                    self.surface_brightness,
                )

            # By the time we get here, we have an object_id
            objects_db.insert_catalog_object(
                self.object_id, self.catalog_code, self.sequence, self.description
            )

            # now the names
            # First, catalog name
            objects_db.insert_name(
                self.object_id,
                f"{self.catalog_code} {self.sequence}",
                self.catalog_code,
            )
            for aka in self.aka_names:
                objects_db.insert_name(self.object_id, aka, self.catalog_code)

            # Commit the transaction
            objects_db.conn.commit()

        except Exception as e:
            objects_db.conn.rollback()
            logging.error(f"Database error inserting object: {e}")
            raise
        finally:
            # Restore bulk mode to False
            objects_db.bulk_mode = False

    def find_constellation(self):
        """
        Uses RA/DEC to figure out what constellation this object is in
        """
        self.constellation = calc_utils.sf_utils.radec_to_constellation(
            self.ra, self.dec
        )
        if self.constellation is None:
            raise ValueError("Constellation not set")

    def find_object_id(self):
        """
        Finds an object id if one exists using AKAs
        """
        # Use class-level shared finder if available, otherwise create new one
        finder = self.__class__._shared_finder or ObjectFinder()
        for aka in self.aka_names:
            _id = finder.get_object_id(aka)
            if _id is not None:
                self.object_id = _id
                break


class ObjectFinder:
    """
    Finds object id for a given catalog code and sequence number.
    Should be reinited for every catalog as the database changes.
    """

    mappings: Dict[str, str]

    def __init__(self):
        self.objects_db = ObjectsDatabase()
        self.catalog_objects = self.objects_db.get_catalog_objects()
        self.mappings = {
            f"{row['catalog_code'].lower()}{row['sequence']}": row["object_id"]
            for row in self.catalog_objects
        }

    def get_object_id(self, object_name: str):
        logging.debug(f"Looking up object id for {object_name}")
        result = self.mappings.get(object_name.lower())
        if not result:
            result = self.mappings.get(normalize(object_name))
        if result:
            logging.debug(f"Found object id {result} for {object_name}")
        else:
            logging.debug(f"DID NOT Find object id {result} for {object_name}")
        return result


def safe_convert_to_float(x):
    """Convert to float, filtering out non-numeric values"""
    try:
        return float(x)
    except ValueError:
        return None


def add_space_after_prefix(s):
    """
    Convert a string like 'NGC1234' to 'NGC 1234'
    """
    # Use regex to match prefixes and numbers, and then join them with a space
    match = re.match(r"([a-zA-Z\-]+)(\d+)", s)
    if match:
        return " ".join(match.groups())
    return s


def trim_string(s):
    """Remove extra whitespace from string"""
    return " ".join(s.split())


def delete_catalog_from_database(catalog_code: str):
    """Delete a catalog and all its related records from the database"""
    if objects_db is None:
        raise RuntimeError("objects_db not initialized")
    conn, db_c = objects_db.get_conn_cursor()
    # 1. Delete related records from the `catalog_objects` table
    db_c.execute("DELETE FROM catalog_objects WHERE catalog_code = ?", (catalog_code,))
    # 2. Delete the catalog record from the `catalogs` table
    db_c.execute("DELETE FROM catalogs WHERE catalog_code = ?", (catalog_code,))
    conn.commit()


def insert_catalog(catalog_name, description_path):
    """Insert a catalog description into the database"""
    with open(description_path, "r") as desc:
        description = "".join(desc.readlines())
    objects_db.insert_catalog(catalog_name, -1, description)


def insert_catalog_max_sequence(catalog_name):
    """Update the max_sequence for a catalog based on actual data"""
    conn, db_c = objects_db.get_conn_cursor()
    query = f"""
            SELECT MAX(sequence) FROM catalog_objects
            where catalog_code = '{catalog_name}' GROUP BY catalog_code
        """
    db_c.execute(query)
    result = db_c.fetchone()
    if result:
        query = f"""
            update catalogs set max_sequence = {
            dict(result)['MAX(sequence)']} where catalog_code = '{catalog_name}'
            """
        db_c.execute(query)
        conn.commit()


def count_rows_per_distinct_column(conn, db_c, table, column):
    """Count rows per distinct value in a column"""
    db_c.execute(f"SELECT {column}, COUNT(*) FROM {table} GROUP BY {column}")
    result = db_c.fetchall()
    for row in result:
        logging.info(f"{row[0]}: {row[1]} entries")


def get_catalog_counts():
    """Get count of objects per catalog"""
    _conn, db_c = objects_db.get_conn_cursor()
    db_c.execute(
        "SELECT catalog_code, count(*) from catalog_objects group by catalog_code"
    )
    result = list(db_c.fetchall())
    for row in result:
        logging.info(f"{row[0]}: {row[1]} entries")
    return result


def count_empty_entries(conn, db_c, table, columns):
    """Count empty entries in specified columns"""
    db_c = conn.cursor()
    for column in columns:
        db_c.execute(
            f"""
                SELECT COUNT(*) FROM {table}
                WHERE {column} IS NULL OR {column} = ''
            """
        )
        result = db_c.fetchone()
        logging.info(f"{column}: {result[0]} empty entries")


def count_common_names_per_catalog():
    """Count common names per catalog"""
    conn, db_c = objects_db.get_conn_cursor()
    count_rows_per_distinct_column(conn, db_c, "names", "origin")


def count_empty_entries_in_tables():
    """Count empty entries across important tables"""
    conn, db_c = objects_db.get_conn_cursor()
    count_empty_entries(conn, db_c, "names", ["object_id", "common_name", "origin"])
    count_empty_entries(
        conn,
        db_c,
        "objects",
        [
            "obj_type",
            "ra",
            "dec",
            "const",
            "size",
            "mag",
        ],
    )


def print_database():
    """Print database statistics"""
    logging.info(">-------------------------------------------------------")
    count_common_names_per_catalog()
    count_empty_entries_in_tables()
    logging.info("<-------------------------------------------------------")


def resolve_object_images():
    """Resolve object images based on catalog priority - Optimized version"""
    conn, db_c = objects_db.get_conn_cursor()

    # Get catalog priority order
    resolution_priority = db_c.execute(
        """
            SELECT catalog_code
            FROM catalogs
            ORDER BY rowid
        """
    ).fetchall()

    # Build priority order list for easier processing
    catalog_priority = [entry["catalog_code"] for entry in resolution_priority]

    # Use a single complex query to get all catalog mappings at once
    # This creates a priority-ordered result set
    priority_cases = []
    for i, catalog_code in enumerate(catalog_priority):
        priority_cases.append(f"WHEN catalog_code = '{catalog_code}' THEN {i}")

    priority_case_sql = "CASE " + " ".join(priority_cases) + " ELSE 999 END"

    # Single query to get the highest priority catalog entry for each object
    query = f"""
        WITH ranked_catalogs AS (
            SELECT 
                co.object_id,
                co.catalog_code,
                co.sequence,
                ROW_NUMBER() OVER (
                    PARTITION BY co.object_id 
                    ORDER BY {priority_case_sql}
                ) as priority_rank
            FROM catalog_objects co
            WHERE co.catalog_code IN ({','.join(['?'] * len(catalog_priority))})
        )
        SELECT 
            o.id as object_id,
            rc.catalog_code,
            rc.sequence
        FROM objects o
        LEFT JOIN ranked_catalogs rc ON o.id = rc.object_id AND rc.priority_rank = 1
        ORDER BY o.id
    """

    # Execute with catalog codes as parameters
    results = db_c.execute(query, catalog_priority).fetchall()

    # Prepare bulk insert data
    image_objects_to_insert = []
    unresolved_objects = []

    for row in tqdm(results, desc="Resolving object images"):
        object_id = row["object_id"]
        catalog_code = row["catalog_code"]
        sequence = row["sequence"]

        if catalog_code and sequence is not None:
            resolved_name = f"{catalog_code}{sequence}"
            image_objects_to_insert.append((object_id, resolved_name))
        else:
            unresolved_objects.append(object_id)

    # Bulk insert image objects
    if image_objects_to_insert:
        # Use executemany for bulk insert into the correct table
        db_c.executemany(
            "INSERT INTO object_images (object_id, image_name) VALUES (?, ?)",
            image_objects_to_insert,
        )
        conn.commit()
        logging.info(f"Resolved {len(image_objects_to_insert)} object images")

    # Log unresolved objects
    if unresolved_objects:
        logging.warning(
            f"No catalog entries for {len(unresolved_objects)} objects: {unresolved_objects[:10]}{'...' if len(unresolved_objects) > 10 else ''}"
        )


def dedup_names():
    """
    Goes through the names table and makes sure there is only one
    of each name

    CURRENTLY only prints duplicates for inspection
    """

    _conn, db_c = ObjectsDatabase().get_conn_cursor()
    # get all names
    names = db_c.execute("select object_id, common_name from names").fetchall()

    name_dict = {}
    for name_rec in names:
        if name_rec["common_name"] not in name_dict.keys():
            name_dict[name_rec["common_name"]] = name_rec["object_id"]
        else:
            if name_rec["object_id"] != name_dict[name_rec["common_name"]]:
                print("FAIL")
                print(name_rec["common_name"], name_rec["object_id"])


def init_databases():
    """Initialize global database objects"""
    global objects_db, observations_db
    objects_db = ObjectsDatabase()
    observations_db = ObservationsDatabase()

    # Also initialize the module-level globals in all loader modules
    import PiFinder.catalog_imports.steinicke_loader as steinicke_mod
    import PiFinder.catalog_imports.caldwell_loader as caldwell_mod
    import PiFinder.catalog_imports.post_processing as postproc_mod
    import PiFinder.catalog_imports.specialized_loaders as specialized_mod
    import PiFinder.catalog_imports.bright_stars_loader as bright_stars_mod
    import PiFinder.catalog_imports.herschel_loader as herschel_mod
    import PiFinder.catalog_imports.sac_loaders as sac_mod

    steinicke_mod.objects_db = objects_db
    caldwell_mod.objects_db = objects_db
    postproc_mod.objects_db = objects_db
    specialized_mod.objects_db = objects_db
    bright_stars_mod.objects_db = objects_db
    herschel_mod.objects_db = objects_db
    sac_mod.objects_db = objects_db

    return objects_db, observations_db
