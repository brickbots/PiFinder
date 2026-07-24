import json
import logging
from pathlib import Path
from typing import List, Optional, Tuple
from sqlite3 import Connection, Cursor
from PiFinder.db.db import Database
import PiFinder.utils as utils
from PiFinder.composite_object import CompositeObject

logger = logging.getLogger("Observations_DB")


class ObservationsDatabase(Database):
    def __init__(self, db_path: Path = utils.observations_db):
        self._objects_db = None
        new_db = False
        if not db_path.exists():
            new_db = True
        conn, cursor = self.get_database(db_path)
        super().__init__(conn, cursor, db_path)
        if new_db:
            self.create_tables()

        self.load_observed_objects_cache()

    def _get_objects_db(self):
        """
        The catalog objects DB — a separate sqlite file from this one.
        Observed status is a property of the underlying sky object, so
        listing keys (catalog, sequence) are mapped to object ids through
        it. Opened lazily and kept for the life of this instance.
        """
        if self._objects_db is None:
            from PiFinder.db.objects_db import ObjectsDatabase

            self._objects_db = ObjectsDatabase()
        return self._objects_db

    def _resolve_object_id(self, catalog: str, sequence: int) -> Optional[int]:
        """
        Maps a listing to its objects-table id; None when the listing
        doesn't resolve (virtual objects like planets, or log entries from
        catalogs no longer installed).
        """
        try:
            row = self._get_objects_db().get_catalog_object_by_sequence(
                catalog, sequence
            )
        except Exception:
            logger.warning(
                "Objects DB unavailable; observed status stays per listing",
                exc_info=True,
            )
            return None
        return None if row is None else row["object_id"]

    def _resolve_listings(self, object_id: int) -> List[Tuple[str, int]]:
        """
        Maps an objects-table id to all of its catalog listings (the
        sibling designations of one sky object, e.g. M 31 / NGC 224).
        """
        try:
            rows = self._get_objects_db().get_catalog_objects_by_object_id(object_id)
        except Exception:
            logger.warning(
                "Objects DB unavailable; log entries stay per listing",
                exc_info=True,
            )
            return []
        return [(row["catalog_code"], row["sequence"]) for row in rows]

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
                "solution": utils.serialize_solution(solution),
                "notes": json.dumps(notes),
            },
        )
        self.conn.commit()

        # Update caches so filters reflect the new observation immediately
        self.observed_objects_cache.add((catalog, sequence))
        object_id = self._resolve_object_id(catalog, sequence)
        if object_id is not None and object_id >= 0:
            self.observed_object_ids.add(object_id)

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

    def load_observed_objects_cache(self) -> None:
        """
        (re)Loads the logged object cache.

        Log entries are stored per listing (catalog, sequence), but
        observed status is a property of the underlying sky object, so
        each logged listing is also mapped to its object id — logging
        M 31 marks NGC 224 observed too, retroactively for existing log
        entries. Listings that don't resolve to an object id (virtual
        objects, removed catalogs) stay listing-keyed only.
        """
        self.observed_objects_cache: set[tuple[str, int]] = {
            (x["catalog"], x["sequence"]) for x in self.get_observed_objects()
        }
        self.observed_object_ids: set[int] = set()
        for catalog, sequence in self.observed_objects_cache:
            object_id = self._resolve_object_id(catalog, sequence)
            if object_id is not None and object_id >= 0:
                self.observed_object_ids.add(object_id)

    def check_logged(self, obj_record: CompositeObject):
        """
        Returns true/false if this object has been observed.

        A DB-backed object (object_id >= 0) tests as logged when any of
        its listings has a log entry. Virtual objects key on their own
        (catalog, sequence) listing only: their negative object_ids are
        minted per session, so id-keyed status would cross-mark
        unrelated objects or vanish on restart.
        """
        # safety check
        if self.observed_objects_cache is None:
            self.load_observed_objects_cache()

        if (
            obj_record.catalog_code,
            obj_record.sequence,
        ) in self.observed_objects_cache:
            return True

        object_id = obj_record.object_id
        return (
            object_id is not None
            and object_id >= 0
            and object_id in self.observed_object_ids
        )

    def get_logs_for_object(self, obj_record: CompositeObject):
        """
        Returns a list of log entries for the underlying sky object: for
        a DB-backed object, entries recorded under any of its listings
        (M 31's logs show on NGC 224's details too); virtual objects stay
        per listing.
        """
        listings: List[Tuple[str, int]] = []
        object_id = obj_record.object_id
        if object_id is not None and object_id >= 0:
            listings = self._resolve_listings(object_id)
        home = (obj_record.catalog_code, obj_record.sequence)
        if home not in listings:
            listings.append(home)

        predicate = " or ".join(["(catalog = ? and sequence = ?)"] * len(listings))
        params = [value for listing in listings for value in listing]
        logs = self.cursor.execute(
            f"select * from obs_objects where {predicate}", params
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
