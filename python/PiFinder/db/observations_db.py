import PiFinder.utils as utils
from sqlite3 import Connection, Cursor, Error
from typing import Tuple
from PiFinder.db.db import Database


class ObservationsDatabase(Database):
    def __init__(self, db_path=utils.observations_db):
        conn, cursor = self.get_database(db_path)
        super().__init__(conn, cursor, db_path)

    def create_tables(self, force_delete: bool = False):
        """
        Creates the base logging tables
        """

        # initialize tables
        self.cursor.execute(
            """
               CREATE TABLE obs_sessions(
                    id INTEGER PRIMARY KEY,
                    start_time_local INTEGER,
                    lat NUMERIC,
                    lon NUMERIC,
                    timezone TEXT,
                    UID TEXT
               )
            """
        )

        self.cursor.execute(
            """
               CREATE TABLE obs_objects(
                    id INTEGER PRIMARY KEY,
                    session_uid TEXT,
                    obs_time_local INTEGER,
                    catalog TEXT,
                    sequence INTEGER,
                    solution TEXT,
                    notes TEXT
               )
            """
        )
        self.obs_conn.close()

    def get_observations_database(self) -> Tuple[Connection, Cursor]:
        return self.get_database(utils.observations_db)

    # ---- OBJECTS methods ----

    def insert_object(self, obj_type, ra, dec, const, l_size, size, mag):
        self.cursor.execute(
            """
            INSERT INTO objects (obj_type, ra, dec, const, l_size, size, mag)
            VALUES (?, ?, ?, ?, ?, ?, ?);
        """,
            (obj_type, ra, dec, const, l_size, size, mag),
        )
        self.self.obs_conn.commit()

    def get_all_objects(self):
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
        self.self.obs_conn.commit()

    # ---- NAMES methods ----

    def insert_name(self, object_id, common_name, description):
        self.cursor.execute(
            """
            INSERT INTO names (object_id, common_name, description)
            VALUES (?, ?);
        """,
            (object_id, common_name),
        )
        self.self.obs_conn.commit()

    def get_name_by_object_id(self, object_id):
        self.cursor.execute("SELECT * FROM names WHERE object_id = ?;", (object_id,))
        return self.cursor.fetchone()

    # ---- CATALOGS methods ----

    def insert_catalog(self, catalog_code, max_sequence, desc):
        self.cursor.execute(
            """
            INSERT INTO catalogs (catalog_code, max_sequence, desc)
            VALUES (?, ?, ?);
        """,
            (catalog_code, max_sequence, desc),
        )
        self.self.obs_conn.commit()

    def get_catalog_by_code(self, catalog_code):
        self.cursor.execute(
            "SELECT * FROM catalogs WHERE catalog_code = ?;", (catalog_code,)
        )
        return self.cursor.fetchone()

    # ---- CATALOG_OBJECTS methods ----

    def insert_catalog_object(self, object_id, catalog_code, sequence, description):
        self.cursor.execute(
            """
            INSERT INTO catalog_objects (object_id, catalog_code, sequence, description)
            VALUES (?, ?, ?, ?);
        """,
            (object_id, catalog_code, sequence, description),
        )
        self.self.obs_conn.commit()

    def get_catalog_objects_by_object_id(self, object_id):
        self.cursor.execute(
            "SELECT * FROM catalog_objects WHERE object_id = ?;", (object_id,)
        )
        return self.cursor.fetchall()

    # Generic delete method for all tables
    def delete_by_id(self, table, record_id):
        self.cursor.execute(f"DELETE FROM {table} WHERE id = ?;", (record_id,))
        self.self.obs_conn.commit()

    def close(self):
        self.self.obs_conn.close()
