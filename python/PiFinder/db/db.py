from typing import Tuple
from sqlite3 import Connection, Cursor, Error
import logging
import sqlite3
from pathlib import Path


class Database:
    conn: Connection
    cursor: Cursor
    db_path: Path

    def __init__(self, conn, cursor, db_path: Path):
        self.conn = conn
        self.cursor = cursor
        self.db_path = db_path

    def get_conn_cursor(self) -> Tuple[Connection, Cursor]:
        return self.conn, self.cursor

    def get_database(self, db_path) -> Tuple[Connection, Cursor]:
        try:
            # open the DB
            logging.debug(f"Opening DB {db_path}")
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            db_c = conn.cursor()
        except Error as e:
            logging.error(e)
            raise e

        return conn, db_c
