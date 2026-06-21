import PiFinder.utils as utils
from sqlite3 import Connection, Cursor, OperationalError
from typing import Tuple, DefaultDict, List, Dict
from PiFinder.db.db import Database
from collections import defaultdict
import logging
import time

# Readable display names per catalog code, used both by the import loaders
# (fresh build) and by the startup migration that backfills the `name` column
# on already-shipped, pre-built databases. Keep these two paths in agreement.
CATALOG_DISPLAY_NAMES: Dict[str, str] = {
    "NGC": "NGC",
    "IC": "IC",
    "M": "Messier",
    "C": "Caldwell",
    "H": "Herschel",
    "Col": "Collinder",
    "Ta2": "TAAS 200",
    "SaA": "SAC Asterisms",
    "SaM": "SAC Doubles",
    "SaR": "SAC Red Stars",
    "Str": "Bright Stars",
    "EGC": "Extragalactic Globular Clusters",
    "RDS": "RASC Double Stars",
    "B": "Barnard",
    "Sh2": "Sharpless",
    "Abl": "Abell",
    "Arp": "Arp",
    "TLK": "TLK Variable Stars",
    "WDS": "Washington Double Star",
    "Har": "Harris",
    "Lyn": "Lynga",
}


class ObjectsDatabase(Database):
    def __init__(self, db_path=utils.pifinder_db):
        conn, cursor = self.get_database(db_path)
        super().__init__(conn, cursor, db_path)

        # Performance optimizations for Pi/SD card environments
        logging.info("Applying database performance optimizations...")
        self.cursor.execute("PRAGMA foreign_keys = ON;")
        self.cursor.execute("PRAGMA mmap_size = 268435456;")  # 256MB memory mapping
        self.cursor.execute("PRAGMA cache_size = -64000;")  # 64MB cache (negative = KB)
        self.cursor.execute("PRAGMA temp_store = MEMORY;")  # Keep temporary data in RAM
        self.cursor.execute(
            "PRAGMA synchronous = NORMAL;"
        )  # Balanced safety/performance
        logging.info("Database optimizations applied")

        self.conn.commit()
        self.bulk_mode = False  # Flag to disable commits during bulk operations

        # One-time, idempotent backfill of the catalogs.name column for
        # pre-built databases shipped without it.
        self._migrate_catalog_names()

    def create_tables(self):
        # Create objects table
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS objects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                obj_type TEXT,
                ra NUMERIC,
                dec NUMERIC,
                const TEXT,
                size TEXT,
                mag TEXT,
                surface_brightness NUMERIC
            );
        """
        )

        # Create names table
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS names (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                object_id INTEGER,
                common_name TEXT,
                origin TEXT,
                FOREIGN KEY (object_id) REFERENCES objects(id)
            );
        """
        )

        # Create indexes on names table for faster lookups
        self.cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_names_object_id
            ON names(object_id);
            """
        )
        self.cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_names_common_name
            ON names(common_name);
            """
        )

        # Create catalogs table
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS catalogs (
                catalog_code TEXT PRIMARY KEY,
                max_sequence INT,
                desc TEXT,
                name TEXT
            );
        """
        )

        # Create catalog_objects table
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS catalog_objects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                object_id INTEGER,
                catalog_code TEXT,
                sequence INTEGER,
                description TEXT,
                FOREIGN KEY (object_id) REFERENCES objects(id),
                FOREIGN KEY (catalog_code) REFERENCES catalogs(catalog_code)
            );
        """
        )

        # Create images_objects table
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS object_images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                object_id INTEGER,
                image_name TEXT,
                FOREIGN KEY (object_id) REFERENCES objects(id)
            );
        """
        )

        # Commit changes to the database
        self.conn.commit()

    def _migrate_catalog_names(self) -> None:
        """Add and backfill the catalogs.name column on legacy databases.

        The shipped pifinder_objects.db is a pre-built binary that predates the
        name column, so a full re-import is not normally run on the device. This
        adds the column if missing and populates it by catalog_code, leaving any
        unmapped catalogs with a NULL name (the UI falls back to the code).
        Safe to run on every startup: it is a no-op once the column exists.
        """
        # The catalogs table may not exist yet during a fresh import build.
        self.cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='catalogs'"
        )
        if self.cursor.fetchone() is None:
            return

        self.cursor.execute("PRAGMA table_info(catalogs)")
        columns = [row["name"] for row in self.cursor.fetchall()]
        if "name" in columns:
            return

        logging.info("Migrating catalogs table: adding and backfilling 'name'")
        try:
            self.cursor.execute("ALTER TABLE catalogs ADD COLUMN name TEXT")
        except OperationalError as e:
            # Another process won the race and already added the column.
            if "duplicate column" in str(e).lower():
                return
            raise

        for catalog_code, display_name in CATALOG_DISPLAY_NAMES.items():
            self.cursor.execute(
                "UPDATE catalogs SET name = ? WHERE catalog_code = ?;",
                (display_name, catalog_code),
            )
        self.conn.commit()

    def get_pifinder_database(self) -> Tuple[Connection, Cursor]:
        return self.get_database(utils.pifinder_db)

    def destroy_tables(self):
        tables = ["catalog_objects", "names", "object_images", "objects", "catalogs"]
        for table in tables:
            self.cursor.execute(f"DROP TABLE IF EXISTS {table};")
        self.conn.commit()

    # ---- OBJECTS methods ----

    def insert_object(
        self, obj_type, ra, dec, const, size, mag, surface_brightness=None
    ):
        logging.debug(
            f"Inserting object {obj_type}, {ra}, {dec}, {const}, {size}, {mag}, {surface_brightness}"
        )
        self.cursor.execute(
            """
            INSERT INTO objects (obj_type, ra, dec, const, size, mag, surface_brightness)
            VALUES (?, ?, ?, ?, ?, ?, ?);
        """,
            (obj_type, ra, dec, const, size, mag, surface_brightness),
        )
        if not self.bulk_mode:
            self.conn.commit()
        return self.cursor.lastrowid

    def get_objects(self):
        """Combines objects and object_images tables"""
        self.cursor.execute(
            """
                SELECT objects.*,image_name FROM objects
                LEFT JOIN object_images on object_id=objects.id;
            """
        )
        return self.cursor.fetchall()

    def get_object_by_id(self, object_id):
        self.cursor.execute("SELECT * FROM objects WHERE id = ?;", (object_id,))
        return self.cursor.fetchone()

    def update_object_by_id(self, object_id, **kwargs):
        columns = ", ".join([f"{key} = ?" for key in kwargs])
        values = list(kwargs.values())
        values.append(object_id)
        self.cursor.execute(f"UPDATE objects SET {columns} WHERE id = ?;", values)
        self.conn.commit()

    # ---- NAMES methods ----

    def insert_name(self, object_id, common_name, origin=""):
        common_name = common_name.strip()
        if common_name == "":
            logging.debug(f"Skipping empty name for {object_id}")
            return
        logging.debug(f"Inserting name {common_name} into {object_id}")
        self.cursor.execute(
            """
            INSERT INTO names (object_id, common_name, origin)
            VALUES (?, ?, ?);
        """,
            (object_id, common_name, origin),
        )
        if not self.bulk_mode:
            self.conn.commit()

    def get_name_by_object_id(self, object_id):
        self.cursor.execute("SELECT * FROM names WHERE object_id = ?;", (object_id,))
        return self.cursor.fetchone()

    def get_object_id_to_names(self) -> DefaultDict[int, List[str]]:
        """
        Returns a dictionary of object_id: [common_name, common_name, ...]
        duplicates are removed.
        """
        start_time = time.time()
        logging.info("Starting get_object_id_to_names query...")

        query_start = time.time()
        self.cursor.execute("SELECT object_id, common_name FROM names ORDER BY rowid;")
        results = self.cursor.fetchall()
        query_time = time.time() - query_start
        logging.info(
            f"Database query took {query_time:.2f}s, returned {len(results)} rows"
        )

        process_start = time.time()
        name_dict = defaultdict(list)
        for object_id, common_name in results:
            name_dict[object_id].append(common_name.strip())
        for object_id in name_dict:
            name_dict[object_id] = list(dict.fromkeys(name_dict[object_id]))
        process_time = time.time() - process_start
        logging.info(
            f"Processing took {process_time:.2f}s, created {len(name_dict)} object entries"
        )

        total_time = time.time() - start_time
        logging.info(f"get_object_id_to_names total time: {total_time:.2f}s")
        return name_dict

    def search_common_names(self, search_term):
        self.cursor.execute(
            "SELECT * FROM names WHERE common_name LIKE ?;", (f"%{search_term}%",)
        )
        return self.cursor.fetchall()

    def get_name_to_object_id(self, id_to_names_dict=None) -> Dict[str, int]:
        """
        Returns a dictionary of common_name: object_id
        """
        if id_to_names_dict is None:
            other_dict = self.get_object_id_to_names()
        else:
            other_dict = id_to_names_dict
        result_dict = defaultdict(int)
        for k, v in other_dict.items():
            for name in v:
                result_dict[name] = k
        return result_dict

    # ---- CATALOGS methods ----

    def insert_catalog(self, catalog_code, max_sequence, desc, name=None):
        self.cursor.execute(
            """
            INSERT INTO catalogs (catalog_code, max_sequence, desc, name)
            VALUES (?, ?, ?, ?);
        """,
            (catalog_code, max_sequence, desc, name),
        )
        self.conn.commit()

    def get_catalog_by_code(self, catalog_code):
        self.cursor.execute(
            "SELECT * FROM catalogs WHERE catalog_code = ?;", (catalog_code,)
        )
        return self.cursor.fetchone()

    def get_catalogs(self):
        self.cursor.execute("SELECT * FROM catalogs;")
        return self.cursor.fetchall()

    def get_catalogs_dict(self) -> Dict[str, Dict]:
        rows = self.get_catalogs()
        result = {}

        for row in rows:
            catalog_code = row[
                "catalog_code"
            ]  # Assuming 'catalog_code' is a column in your rows
            row_dict = dict(row)
            result[catalog_code] = row_dict
        return result

    # ---- CATALOG_OBJECTS methods ----

    def insert_catalog_object(self, object_id, catalog_code, sequence, description):
        logging.debug(
            f"Inserting catalog object '{object_id=}' into '{catalog_code=}-{sequence=}', {description=}"
        )
        self.cursor.execute(
            """
            INSERT INTO catalog_objects (object_id, catalog_code, sequence, description)
            VALUES (?, ?, ?, ?);
        """,
            (object_id, catalog_code, sequence, description),
        )
        if not self.bulk_mode:
            self.conn.commit()

    def get_catalog_objects_by_object_id(self, object_id):
        self.cursor.execute(
            "SELECT * FROM catalog_objects WHERE object_id = ?;", (object_id,)
        )
        return self.cursor.fetchall()

    def get_catalog_object_by_sequence(self, catalog_code, sequence):
        self.cursor.execute(
            "SELECT * FROM catalog_objects WHERE catalog_code = ? and sequence = ?;",
            (catalog_code, sequence),
        )
        return self.cursor.fetchone()

    def get_catalog_objects_by_catalog_code(self, catalog_code):
        self.cursor.execute(
            "SELECT * FROM catalog_objects WHERE catalog_code = ?;", (catalog_code,)
        )
        return self.cursor.fetchall()

    def get_catalog_objects(self):
        start_time = time.time()
        logging.info("Starting get_catalog_objects query...")

        self.cursor.execute("SELECT * FROM catalog_objects;")
        results = self.cursor.fetchall()

        total_time = time.time() - start_time
        logging.info(
            f"get_catalog_objects took {total_time:.2f}s, returned {len(results)} rows"
        )
        return results

    # ---- IMAGES_OBJECTS methods ----
    def insert_image_object(self, object_id, image_name):
        self.cursor.execute(
            """
            INSERT INTO object_images(object_id, image_name)
            VALUES (?, ?);
        """,
            (object_id, image_name),
        )
        self.conn.commit()

    # Generic delete method for all tables
    def delete_by_id(self, table, record_id):
        self.cursor.execute(f"DELETE FROM {table} WHERE id = ?;", (record_id,))
        self.conn.commit()

    def delete_catalog_by_code(self, catalog_code):
        # First, delete related entries in catalog_objects to maintain foreign key integrity
        self.cursor.execute(
            "DELETE FROM catalog_objects WHERE catalog_code = ?;", (catalog_code,)
        )
        # Now, delete the catalog
        self.cursor.execute(
            "DELETE FROM catalogs WHERE catalog_code = ?;", (catalog_code,)
        )
        self.conn.commit()

    def close(self):
        self.conn.close()
