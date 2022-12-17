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
import uuid
import sqlite3
import json

from PiFinder.obj_types import OBJ_TYPES
from PiFinder.setup import create_logging_tables


class Observation_session:
    """
    Represents a single
    session of observations
    in a specific location
    with multiple objects observed
    """

    def __init__(self, shared_state):
        # make sure observation db exists
        db_path = create_logging_tables()

        self.db_connection = sqlite3.connect(db_path)
        self.db_connection.row_factory = sqlite3.Row
        self.db_cursor = self.db_connection.cursor()

        self.__session_uid = None
        self.__shared_state = shared_state

    def session_uid(self):
        """
        Returns the current session uid
        Creates a new observing session
        if none yet exists
        """
        if self.__session_uid:
            # already initialized, abort
            return self.__session_uid

        location = self.__shared_state.location()
        if not location:
            return None

        local_time = self.__shared_state.local_datetime()
        self.__session_uid = str(uuid.uuid1()).split("-")[0]

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
                :uid
            )
        """

        self.db_cursor.execute(
            q,
            {
                "start_time": local_time.timestamp(),
                "lat": location["lat"],
                "lon": location["lon"],
                "timezone": location["timezone"],
                "uid": self.__session_uid,
            },
        )

        return self.__session_uid

    def log_object(self, catalog, designation, solution, notes):

        session_uid = self.session_uid()
        if not session_uid:
            print("Could not create session")
            return False

        q = """
            INSERT INTO obs_objects(
                session_uid,
                obs_time_local,
                catalog,
                designation,
                solution,
                notes
            )
            VALUES
            (
                :session_uid,
                :obs_time,
                :catalog,
                :designation,
                :solution,
                :notes
            )
        """

        self.db_cursor.execute(
            q,
            {
                "session_uid": session_uid,
                "obs_time": self.__shared_state.local_datetime(),
                "catalog": catalog,
                "designation": designation,
                "solution": json.dumps(solution),
                "notes": json.dumps(notes),
            },
        )

        return True
