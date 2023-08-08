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
from PiFinder.db.observations_db import (
    ObservationsDatabase,
)


class Observation_session:
    """
    Represents a single
    session of observations
    in a specific location
    with multiple objects observed
    """

    def __init__(self, shared_state, session_uuid):
        self.db = ObservationsDatabase()
        if not self.db.exists():
            self.db.create_tables()

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
        self.db.create_obs_session(
            local_time.timestamp(),
            location["lat"],
            location["lon"],
            location["timezone"],
            self.__session_uuid,
        )

        return self.__session_uuid

    def log_object(self, catalog, sequence, solution, notes):
        session_uuid = self.session_uuid()
        if not session_uuid:
            print("Could not create session")
            return False

        observation_id = self.db.log_object(
            session_uuid,
            self.__shared_state.local_datetime().timestamp(),
            catalog,
            sequence,
            solution,
            notes,
        )

        return session_uuid, observation_id

    def get_logs_for_object(self, obj_record):
        """
        Returns a list of observations for a particular object
        """
        return self.db.get_logs_for_object(obj_record)

    def get_observed_objects(self):
        """
        Returns a list of all observed objects
        """
        logs = self.db.get_observed_objects()

        return [(x.catalog_code, x.sequence) for x in logs]
