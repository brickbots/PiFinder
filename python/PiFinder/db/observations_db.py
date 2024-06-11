import json
from pathlib import Path
from typing import Tuple
from sqlite3 import Connection, Cursor
from PiFinder.db.db import Database
import PiFinder.utils as utils
from PiFinder.composite_object import CompositeObject


class ObservationsDatabase(Database):
    def __init__(self, db_path: Path = utils.observations_db):
        new_db = False
        if not db_path.exists():
            new_db = True
        conn, cursor = self.get_database(db_path)
        super().__init__(conn, cursor, db_path)
        if new_db:
            self.create_tables()

        self.observed_objects_cache = None

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
        self.conn.commit()

    def get_observations_database(self) -> Tuple[Connection, Cursor]:
        return self.get_database(utils.observations_db)

    def create_obs_session(self, start_time, lat, lon, timezone, uuid):
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

        self.cursor.execute(
            q,
            {
                "start_time": start_time,
                "lat": lat,
                "lon": lon,
                "timezone": timezone,
                "uuid": uuid,
            },
        )
        self.conn.commit()

    def log_object(self, session_uuid, obs_time, catalog, sequence, solution, notes):
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

        self.cursor.execute(
            q,
            {
                "session_uuid": session_uuid,
                "obs_time": obs_time,
                "catalog": catalog,
                "sequence": sequence,
                "solution": json.dumps(solution),
                "notes": json.dumps(notes),
            },
        )
        self.conn.commit()

        observation_id = self.cursor.execute(
            "select last_insert_rowid() as id"
        ).fetchone()["id"]
        return observation_id

    def get_observed_objects(self):
        """
        Returns a list of all observed objects
        """
        logs = self.cursor.execute(
            """
                select distinct catalog, sequence from obs_objects
            """
        ).fetchall()

        return logs

    def load_observed_objects_cache(self):
        """
        (re)Loads the logged object cache
        """
        self.observed_objects_cache = [
            (x["catalog"], x["sequence"]) for x in self.get_observed_objects()
        ]

    def check_logged(self, obj_record: CompositeObject):
        """
        Returns true/false if this object has been observed
        """
        # safety check
        if self.observed_objects_cache is None:
            self.load_observed_objects_cache()

        if (
            obj_record.catalog_code,
            obj_record.sequence,
        ) in self.observed_objects_cache:
            return True

        return False

    def get_logs_for_object(self, obj_record: CompositeObject):
        """
        Returns a list of observations for a particular object
        """
        logs = self.cursor.execute(
            """
                select * from obs_objects
                where catalog = :catalog
                and sequence = :sequence
            """,
            {"catalog": obj_record.catalog_code, "sequence": obj_record.sequence},
        ).fetchall()

        return logs

    def close(self):
        self.conn.close()

    def get_sessions(self, session_uid=None):
        """
        returns a list of observing session dictionaries

        There was a bug that would double up session
        entries for the same PiFinder software run
        so this does some sanitizing of the data

        """
        q = """
                Select
                    uid,
                    timezone,
                    datetime(min(start_time_local), "unixepoch") as start_time_local,
                    avg(lat) as lat,
                    avg(lon) as lon
                from obs_sessions
            """
        if session_uid is not None:
            # add in a where clause
            q += """
                where uid= :sess_uid
            """

        q += """
                group by 1,2
                order by start_time_local
            """

        sessions = self.cursor.execute(q, {"sess_uid": session_uid}).fetchall()

        # now enrich them....
        ret_sessions = []
        for sess in sessions:
            sess = dict(sess)
            _sess_info = self.cursor.execute(
                """
                    select
                        count(*) as observations,
                        (max(obs_time_local) - min(obs_time_local)) / 60 /60 as duration
                    from obs_objects
                    where session_uid= :sess_uid
                """,
                {"sess_uid": sess["UID"]},
            ).fetchone()
            sess = sess | dict(_sess_info)
            if sess["observations"] > 0:
                ret_sessions.append(sess)

        return ret_sessions

    def get_session(self, session_uid):
        """
        returns a record for a specific session
        applies the same enrichment
        """
        return self.get_sessions(session_uid=session_uid)[0]

    def get_logs_by_session(self, session_uid):
        """
        returns a list of observed objects for session
        """
        objects = self.cursor.execute(
            """
                Select
                    session_uid,
                    ifnull(datetime(obs_time_local, "unixepoch"), datetime(obs_time_local)) as obs_time_local,
                    catalog,
                    sequence,
                    notes
                from obs_objects
                where session_uid= :session_uid
            """,
            {"session_uid": session_uid},
        ).fetchall()

        return objects

    def observations_as_tsv(self, session_uid=None):
        """
        Returns all observations for a session
        or all sessions
        """
        rows_list = []
        headers_list = [
            "Session_ID",
            "Session_Start_Time",
            "Session_Time_Zone",
            "Session_Lat",
            "Session_Lon",
            "Observation_Time",
            "Catalog",
            "Sequence",
            "Notes",
        ]
        rows_list.append("\t".join(headers_list))

        sessions = self.get_sessions(session_uid=session_uid)
        for session in sessions:
            base_row = [
                session["UID"],
                session["start_time_local"],
                session["timezone"],
                str(session["lat"]),
                str(session["lon"]),
            ]
            objects = self.get_logs_by_session(session["UID"])
            for obj in objects:
                object_row = base_row + [
                    obj["obs_time_local"],
                    obj["catalog"],
                    str(obj["sequence"]),
                    obj["notes"],
                ]
                rows_list.append("\t".join(object_row))

        return "\n".join(rows_list)
