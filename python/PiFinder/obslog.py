#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module contains
the main observation log
class

"""
import datetime
import pytz
import time
import os
import sqlite3
import json

from PiFinder.obj_types import OBJ_TYPES
from PiFinder.setup import create_logging_tables, get_observations_database


class Observation_session:
    """
    Represents a single
    session of observations
    in a specific location
    with multiple objects observed
    """

    def __init__(self, shared_state, session_uuid):
        # make sure observation db exists
        create_logging_tables()
        conn, db_c = get_observations_database()

        self.db_connection = conn
        self.db_connection.row_factory = sqlite3.Row
        self.db_cursor = db_c

        self.__session_init = False
        self.__session_uuid = session_uuid
        self.__shared_state = shared_state

    def session_uuid(self):
        """
        Returns the current session uid
        Creates a new observing session
        if none yet exists
        """
        if self.__session_init:
            # already initialized, abort
            return self.__session_uuid

        location = self.__shared_state.location()
        if not location:
            return None

        local_time = self.__shared_state.local_datetime()
        if not local_time:
            return None

        q = """
            INSERT INTO obs_sessions(
                start_time_local,
                lat,
                lon,
                timezone,
                uid
            )
            VALUES
            (
                :start_time,
                :lat,
                :lon,
                :timezone,
                :uuid
            )
        """

        self.db_cursor.execute(
            q,
            {
                "start_time": local_time.timestamp(),
                "lat": location["lat"],
                "lon": location["lon"],
                "timezone": location["timezone"],
                "uuid": self.__session_uuid,
            },
        )

        self.db_connection.commit()

        return self.__session_uuid

    def log_object(self, catalog, sequence, solution, notes):
        session_uuid = self.session_uuid()
        if not session_uuid:
            print("Could not create session")
            return None, None

        q = """
            INSERT INTO obs_objects(
                session_uid,
                obs_time_local,
                catalog,
                sequence,
                solution,
                notes
            )
            VALUES
            (
                :session_uuid,
                :obs_time,
                :catalog,
                :sequence,
                :solution,
                :notes
            )
        """

        self.db_cursor.execute(
            q,
            {
                "session_uuid": session_uuid,
                "obs_time": self.__shared_state.local_datetime(),
                "catalog": catalog,
                "sequence": sequence,
                "solution": json.dumps(solution),
                "notes": json.dumps(notes),
            },
        )
        self.db_connection.commit()

        observation_id = self.db_cursor.execute(
            "select last_insert_rowid() as id"
        ).fetchone()["id"]

        return session_uuid, observation_id


def get_logs_for_object(obj_record):
    """
    Returns a list of observations for a particular object
    """
    create_logging_tables()
    conn, db_c = get_observations_database()

    logs = db_c.execute(
        f"""
            select * from obs_objects
            where
                catalog="{obj_record['catalog']}"
                and sequence={obj_record['sequence']}
            """
    ).fetchall()

    return logs


def get_observed_objects():
    """
    Returns a list of all observed objects
    """
    create_logging_tables()
    conn, db_c = get_observations_database()

    logs = db_c.execute(
        f"""
            select distinct catalog, sequence from obs_objects
            """
    ).fetchall()

    return [(x["catalog"], x["sequence"]) for x in logs]
