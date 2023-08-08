import PiFinder.utils as utils
from sqlite3 import Connection, Cursor, Error
from typing import Tuple, DefaultDict, List
from PiFinder.db.db import Database
from collections import defaultdict
import logging


class ObjectsDatabase(Database):
    def __init__(self, db_path=utils.pifinder_db):
        conn, cursor = self.get_database(db_path)
        super().__init__(conn, cursor, db_path)
        self.cursor.execute("PRAGMA foreign_keys = ON;")
        self.conn.commit()

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
                mag NUMERIC
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

        # Create catalogs table
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS catalogs (
                catalog_code TEXT PRIMARY KEY,
                max_sequence INT,
                desc TEXT
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
            CREATE TABLE IF NOT EXISTS images_objects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                object_id INTEGER,
                image_path TEXT,
                FOREIGN KEY (object_id) REFERENCES objects(id)
            );
        """
        )

        # Commit changes to the database
        self.conn.commit()

    def get_pifinder_database(self) -> Tuple[Connection, Cursor]:
        return self.get_database(utils.pifinder_db)

    def destroy_tables(self):
        tables = ["catalog_objects", "names", "objects", "catalogs"]
        for table in tables:
            self.cursor.execute(f"DROP TABLE IF EXISTS {table};")
        self.conn.commit()

    # ---- OBJECTS methods ----

    def insert_object(self, obj_type, ra, dec, const, size, mag):
        logging.debug(
            f"Inserting object {obj_type}, {ra}, {dec}, {const}, {size}, {mag}"
        )
        self.cursor.execute(
            """
            INSERT INTO objects (obj_type, ra, dec, const, size, mag)
            VALUES (?, ?, ?, ?, ?, ?);
        """,
            (obj_type, ra, dec, const, size, mag),
        )
        self.conn.commit()
        return self.cursor.lastrowid

    def get_objects(self):
        self.cursor.execute("SELECT * FROM objects;")
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
        self.conn.commit()

    def get_name_by_object_id(self, object_id):
        self.cursor.execute("SELECT * FROM names WHERE object_id = ?;", (object_id,))
        return self.cursor.fetchone()

    def get_names(self) -> DefaultDict[int, List[str]]:
        """
        Returns a dictionary of object_id: [common_name, common_name, ...]
        duplicates are removed.
        """
        self.cursor.execute("SELECT object_id, common_name FROM names;")
        results = self.cursor.fetchall()
        name_dict = defaultdict(list)
        for object_id, common_name in results:
            name_dict[object_id].append(common_name.strip())
        for object_id in name_dict:
            name_dict[object_id] = list(set(name_dict[object_id]))
        return name_dict

    # ---- CATALOGS methods ----

    def insert_catalog(self, catalog_code, max_sequence, desc):
        self.cursor.execute(
            """
            INSERT INTO catalogs (catalog_code, max_sequence, desc)
            VALUES (?, ?, ?);
        """,
            (catalog_code, max_sequence, desc),
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

    # ---- CATALOG_OBJECTS methods ----

    def insert_catalog_object(self, object_id, catalog_code, sequence, description):
        logging.debug(
            f"Inserting catalog object '{object_id}' into '{catalog_code}-{sequence}', {description=}"
        )
        self.cursor.execute(
            """
            INSERT INTO catalog_objects (object_id, catalog_code, sequence, description)
            VALUES (?, ?, ?, ?);
        """,
            (object_id, catalog_code, sequence, description),
        )
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
        self.cursor.execute("SELECT * FROM catalog_objects;")
        return self.cursor.fetchall()

    # ---- IMAGES_OBJECTS methods ----
    def insert_image_object(self, image_id, object_id):
        self.cursor.execute(
            """
            INSERT INTO images_objects (object_id, image_path)
            VALUES (?, ?);
        """,
            (object_id, image_path),
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
