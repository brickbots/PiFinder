import json
import logging
from dataclasses import dataclass
from pathlib import Path
from sqlite3 import Connection, Cursor
from threading import RLock
from typing import List, Optional, Tuple

from PiFinder.composite_object import CompositeObject
from PiFinder.db.db import Database
from PiFinder.db.objects_db import ObjectsDatabase
from PiFinder.observing_nights import (
    coerce_epoch,
    group_into_nights,
    local_datetime,
    night_key as night_key_for,
)
import PiFinder.utils as utils

logger = logging.getLogger("Observations_DB")

TSV_HEADERS = [
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
TSV_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


@dataclass
class _ObservedIdentityCache:
    fingerprint: tuple[tuple[int, int], tuple[int, int]]
    listings: set[tuple[str, int]]
    object_ids: set[int]


_observed_identity_caches: dict[tuple[Path, Path], _ObservedIdentityCache] = {}
_observed_identity_cache_lock = RLock()


def _database_fingerprint(path: Path) -> tuple[int, int]:
    try:
        stat = path.stat()
    except OSError:
        return 0, 0
    return stat.st_mtime_ns, stat.st_size


class ObservationsDatabase(Database):
    def __init__(self, db_path: Optional[Path] = None):
        # Resolved at call time, not as a default argument: an import-time
        # default captures utils.observations_db before the test sandbox
        # patches it, sending writes to the real ~/PiFinder_data.
        if db_path is None:
            db_path = utils.observations_db
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
            self._objects_db = ObjectsDatabase()
        return self._objects_db

    def _identity_cache_key(self) -> tuple[Path, Path]:
        return self.db_path.resolve(), Path(utils.pifinder_db).resolve()

    def _identity_cache_fingerprint(self) -> tuple[tuple[int, int], tuple[int, int]]:
        observations_path, objects_path = self._identity_cache_key()
        return (
            _database_fingerprint(observations_path),
            _database_fingerprint(objects_path),
        )

    def _query_observed_identities(
        self,
    ) -> tuple[set[tuple[str, int]], set[int]]:
        """Load listing and sky-object identities with one indexed query."""
        alias = "catalog_identity"
        self.cursor.execute(
            f"ATTACH DATABASE ? AS {alias}", (str(Path(utils.pifinder_db)),)
        )
        try:
            rows = self.cursor.execute(
                f"""
                SELECT DISTINCT observed.catalog, observed.sequence,
                                catalog_object.object_id
                FROM obs_objects AS observed
                LEFT JOIN {alias}.catalog_objects AS catalog_object
                  ON catalog_object.catalog_code = observed.catalog
                 AND catalog_object.sequence = observed.sequence
                """
            ).fetchall()
        finally:
            self.cursor.execute(f"DETACH DATABASE {alias}")

        listings = {(row["catalog"], row["sequence"]) for row in rows}
        object_ids = {
            row["object_id"]
            for row in rows
            if row["object_id"] is not None and row["object_id"] >= 0
        }
        return listings, object_ids

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

        # Update the process-wide cache so every existing view reflects the
        # new observation immediately.
        with _observed_identity_cache_lock:
            self.observed_objects_cache.add((catalog, sequence))
            object_id = self._resolve_object_id(catalog, sequence)
            if object_id is not None and object_id >= 0:
                self.observed_object_ids.add(object_id)

            cache = _observed_identity_caches.get(self._identity_cache_key())
            if cache is not None:
                cache.fingerprint = self._identity_cache_fingerprint()

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
        with _observed_identity_cache_lock:
            key = self._identity_cache_key()
            fingerprint = self._identity_cache_fingerprint()
            cache = _observed_identity_caches.get(key)
            if cache is None or cache.fingerprint != fingerprint:
                try:
                    listings, object_ids = self._query_observed_identities()
                except Exception:
                    logger.warning(
                        "Could not resolve observed object identities; "
                        "observed status stays per listing",
                        exc_info=True,
                    )
                    listings = {
                        (row["catalog"], row["sequence"])
                        for row in self.get_observed_objects()
                    }
                    object_ids = set()

                if cache is None:
                    cache = _ObservedIdentityCache(fingerprint, listings, object_ids)
                    _observed_identity_caches[key] = cache
                else:
                    # Existing database instances retain these set objects, so
                    # refresh them in place rather than stranding stale readers.
                    cache.listings.clear()
                    cache.listings.update(listings)
                    cache.object_ids.clear()
                    cache.object_ids.update(object_ids)
                    cache.fingerprint = fingerprint

            self.observed_objects_cache = cache.listings
            self.observed_object_ids = cache.object_ids

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

        Times come back as the raw stored value; rendering them needs the
        session's timezone, which sqlite has no database for.
        """
        objects = self.cursor.execute(
            """
                Select
                    session_uid,
                    obs_time_local,
                    catalog,
                    sequence,
                    notes
                from obs_objects
                where session_uid= :session_uid
            """,
            {"session_uid": session_uid},
        ).fetchall()

        return objects

    def get_observations_with_session(self):
        """
        Every observation with the session context needed to place it in a
        night: the timezone its clock ran in, and where it was made.

        Times come back as raw epochs. Rendering them needs the timezone,
        which sqlite has no database for, so formatting happens in Python
        (see PiFinder.observing_nights).

        A historical bug wrote duplicate obs_sessions rows for one run --
        the same sanitizing get_sessions() does -- so the session context
        is aggregated rather than joined row-for-row, which would multiply
        each observation by the number of duplicates.
        """
        return self.cursor.execute(
            """
                select
                    o.session_uid,
                    o.obs_time_local,
                    o.catalog,
                    o.sequence,
                    o.notes,
                    s.timezone,
                    s.lat,
                    s.lon
                from obs_objects o
                left join (
                    select
                        uid,
                        max(timezone) as timezone,
                        avg(lat) as lat,
                        avg(lon) as lon
                    from obs_sessions
                    group by uid
                ) s on s.uid = o.session_uid
                order by o.obs_time_local
            """
        ).fetchall()

    def get_nights(self):
        """
        Observing nights, most recent first. See PiFinder.observing_nights
        for what counts as a night and why it isn't a session.
        """
        return group_into_nights(self.get_observations_with_session())

    def get_logs_by_night(self, night_key):
        """
        Observations belonging to one night, in the order they were made.

        Includes the stored solution, which carries the constellation and
        the object's Alt/Az at the moment it was logged.
        """
        rows = self.cursor.execute(
            """
                select
                    o.session_uid,
                    o.obs_time_local,
                    o.catalog,
                    o.sequence,
                    o.solution,
                    o.notes,
                    s.timezone,
                    s.lat,
                    s.lon
                from obs_objects o
                left join (
                    select
                        uid,
                        max(timezone) as timezone,
                        avg(lat) as lat,
                        avg(lon) as lon
                    from obs_sessions
                    group by uid
                ) s on s.uid = o.session_uid
                order by o.obs_time_local
            """
        ).fetchall()

        logs = []
        for row in rows:
            record = dict(row)
            epoch = coerce_epoch(record["obs_time_local"])
            if epoch is None or night_key_for(epoch, record["timezone"]) != night_key:
                continue
            record["epoch"] = epoch
            record["local_time"] = local_datetime(epoch, record["timezone"])
            logs.append(record)

        return logs

    def get_session_timezones(self):
        """
        Each session's timezone, keyed by session uid.

        Aggregated for the same reason the night join is: a historical bug
        wrote a session's row more than once.
        """
        rows = self.cursor.execute(
            """
                select uid, max(timezone) as timezone
                from obs_sessions
                group by uid
            """
        ).fetchall()
        return {row["UID"]: row["timezone"] for row in rows}

    def night_key_for_session(self, session_uid):
        """
        The night a software run belongs to, from its first observation.

        A run that produced nothing has no night to point at.
        """
        row = self.cursor.execute(
            """
                select min(obs_time_local) as first_observation
                from obs_objects
                where session_uid = :session_uid
            """,
            {"session_uid": session_uid},
        ).fetchone()

        epoch = coerce_epoch(row["first_observation"]) if row else None
        if epoch is None:
            return None
        timezone = self.get_session_timezones().get(session_uid)
        return night_key_for(epoch, timezone)

    def get_object_history(self, obj_record: CompositeObject):
        """
        Every observation of one sky object, most recent first.

        Built on get_logs_for_object, so an object logged under one of its
        designations shows that entry under all of them (M 31 / NGC 224),
        with each entry placed in the night it belongs to.
        """
        timezones = self.get_session_timezones()

        history = []
        for row in self.get_logs_for_object(obj_record):
            record = dict(row)
            epoch = coerce_epoch(record["obs_time_local"])
            if epoch is None:
                continue
            timezone = timezones.get(record["session_uid"])
            record["epoch"] = epoch
            record["timezone"] = timezone
            record["local_time"] = local_datetime(epoch, timezone)
            record["night_key"] = night_key_for(epoch, timezone)
            history.append(record)

        return sorted(history, key=lambda record: record["epoch"], reverse=True)

    def observations_as_tsv(self, session_uid=None, night_key=None):
        """
        Returns all observations for a session, a night, or everything.

        Observation times are written in the timezone the session ran in,
        the same as the night-scoped export -- both describe the same
        instants and must not disagree about what the clock read.
        """
        if night_key is not None:
            return self._night_as_tsv(night_key)
        rows_list = ["\t".join(TSV_HEADERS)]

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
                    self._local_time_string(obj["obs_time_local"], session["timezone"]),
                    obj["catalog"],
                    str(obj["sequence"]),
                    obj["notes"],
                ]
                rows_list.append("\t".join(object_row))

        return "\n".join(rows_list)

    @staticmethod
    def _local_time_string(value, timezone):
        """
        A stored observation time as the observer's wall clock, falling
        back to the raw value when it can't be read as an instant.
        """
        epoch = coerce_epoch(value)
        if epoch is None:
            return str(value)
        return local_datetime(epoch, timezone).strftime(TSV_TIME_FORMAT)

    def _night_as_tsv(self, night_key):
        """
        One night's observations, in the same column shape as the
        session-scoped export so both downloads parse identically.
        """
        rows_list = ["\t".join(TSV_HEADERS)]

        for log in self.get_logs_by_night(night_key):
            rows_list.append(
                "\t".join(
                    [
                        str(log["session_uid"]),
                        night_key,
                        str(log["timezone"] or ""),
                        str(log["lat"]),
                        str(log["lon"]),
                        log["local_time"].strftime(TSV_TIME_FORMAT),
                        log["catalog"],
                        str(log["sequence"]),
                        log["notes"],
                    ]
                )
            )

        return "\n".join(rows_list)
