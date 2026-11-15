#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module contains
the main observation log
class

"""

import logging
from typing import Optional

from PiFinder.db.observations_db import (
    ObservationsDatabase,
)

logger = logging.getLogger("Observation.Log")

# Fields lifted out of shared_state.sqm_details() into an observation's
# notes, as note_key -> details_key. The details dict also carries whole
# rolling-window dumps (window_radiometer and friends); those belong to
# telemetry, which already records the per-frame stream timestamped, and
# would otherwise be duplicated in near-identical form on every log entry.
SQM_NOTE_DETAIL_KEYS = {
    "samples": "radiometer_samples",
    "scatter": "radiometer_frame_scatter",
    "pedestal_source": "pedestal_source",
}


def sqm_note(sqm, sqm_details: Optional[dict]) -> Optional[dict]:
    """The sky brightness behind an observation, or None if unmeasured.

    ``SQM.value`` holds a plausible dark-sky default (20.15) from the
    moment the state object exists, so a value only counts as a reading
    when its ``source`` says one was actually taken. ``samples`` and
    ``scatter`` are the radiometer's own figures for the window the value
    came from, which is what makes the reading's stability judgeable later.
    """
    if sqm is None:
        return None

    source = getattr(sqm, "source", None)
    if not source or source == "None":
        return None

    note = {"value": round(float(sqm.value), 2), "source": source}
    details = sqm_details or {}
    for note_key, details_key in SQM_NOTE_DETAIL_KEYS.items():
        value = details.get(details_key)
        if value is None:
            continue
        # numpy scalars reach here from the radiometer; json can't take them.
        note[note_key] = round(float(value), 3) if note_key == "scatter" else value

    return note


class Observation_session:
    """
    Represents a single
    session of observations
    in a specific location
    with multiple objects observed
    """

    def __init__(self, shared_state, session_uuid):
        self.db = ObservationsDatabase()
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
        local_time = self.__shared_state.local_datetime()

        # handle missing location or time
        if not location:
            logger.error(
                "Session uuid could not be created, as location is not set (yet)."
            )
            return None
        if not local_time:
            logger.error(
                "Session uuid could not be created, as local time is not set (yet)."
            )
            return None

        self.db.create_obs_session(
            local_time.timestamp(),
            location.lat,
            location.lon,
            location.timezone,
            self.__session_uuid,
        )

        self.__session_init = True
        return self.__session_uuid

    def log_object(self, catalog, sequence, solution, notes):
        session_uuid = self.session_uuid()
        if not session_uuid:
            logger.error("Could not create session, so object could not be logged.")
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
