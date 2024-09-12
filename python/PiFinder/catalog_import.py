"""
This module holds various utils
and importers used during setup

"""

import csv
import json
import argparse
import logging
import datetime
import re
from tqdm import tqdm
from pathlib import Path
from typing import Dict
from dataclasses import dataclass, field
from PiFinder.composite_object import MagnitudeObject

# from PiFinder.obj_types import OBJ_DESCRIPTORS
import PiFinder.utils as utils
from PiFinder.ui.ui_utils import normalize
from PiFinder.calc_utils import (
    ra_to_deg,
    dec_to_deg,
    b1950_to_j2000,
)
from PiFinder import calc_utils
from PiFinder.db.objects_db import ObjectsDatabase
from PiFinder.db.observations_db import ObservationsDatabase
from collections import namedtuple, defaultdict
import sqlite3

objects_db: ObjectsDatabase
observations_db: ObservationsDatabase


@dataclass
class NewCatalogObject:
    object_type: str
    catalog_code: str
    sequence: int
    ra: float
    dec: float
    mag: MagnitudeObject
    object_id: int = 0
    size: str = ""
    description: str = ""
    aka_names: list[str] = field(default_factory=list)

    def insert(self):
        """
        Inserts object into DB
        """
        # sanity checks
        if type(self.aka_names) is not list:
            raise TypeError("Aka names not list")

        # Check to see if this object matches one in the DB already
        self.find_object_id()

        if self.object_id == 0:
            # Did not find a match, first insert object info
            self.find_constellation()
            assert isinstance(self.mag, MagnitudeObject)

            self.object_id = objects_db.insert_object(
                self.object_type,
                self.ra,
                self.dec,
                self.constellation,
                self.size,
                self.mag.to_json(),
            )

        # By the time we get here, we have an object_id
        objects_db.insert_catalog_object(
            self.object_id, self.catalog_code, self.sequence, self.description
        )

        # now the names
        # First, catalog name
        objects_db.insert_name(
            self.object_id, f"{self.catalog_code} {self.sequence}", self.catalog_code
        )
        for aka in self.aka_names:
            objects_db.insert_name(self.object_id, aka, self.catalog_code)

    def find_constellation(self):
        """
        Uses RA/DEC to figure out what constellation this object is in
        """
        self.constellation = calc_utils.sf_utils.radec_to_constellation(
            self.ra, self.dec
        )
        if self.constellation is None:
            raise ValueError("Constellation not set")

    def find_object_id(self):
        """
        Finds an object id if one exists using AKAs
        """
        finder = ObjectFinder()
        for aka in self.aka_names:
            _id = finder.get_object_id(aka)
            if _id is not None:
                self.object_id = _id
                break


def dedup_names():
    """
    Goes through the names table and makes sure there is only one
    of each name

    CURRENTLY only prints duplicates for inspection
    """

    _conn, db_c = ObjectsDatabase().get_conn_cursor()
    # get all names
    names = db_c.execute("select object_id, common_name from names").fetchall()

    name_dict = {}
    for name_rec in names:
        if name_rec["common_name"] not in name_dict.keys():
            name_dict[name_rec["common_name"]] = name_rec["object_id"]
        else:
            if name_rec["object_id"] != name_dict[name_rec["common_name"]]:
                print("FAIL")
                print(name_rec["common_name"], name_rec["object_id"])


# Convert to float, filtering out non-numeric values
def safe_convert_to_float(x):
    try:
        return float(x)
    except ValueError:
        return None


class ObjectFinder:
    """
    Finds object id for a given catalog code and sequence number.
    Should be reinited for every catalog as the database changes.
    """

    mappings: Dict[str, str]

    def __init__(self):
        self.objects_db = ObjectsDatabase()
        self.catalog_objects = self.objects_db.get_catalog_objects()
        self.mappings = {
            f"{row['catalog_code'].lower()}{row['sequence']}": row["object_id"]
            for row in self.catalog_objects
        }

    def get_object_id(self, object_name: str):
        logging.debug(f"Looking up object id for {object}")
        result = self.mappings.get(object_name.lower())
        if not result:
            result = self.mappings.get(normalize(object_name))
        if result:
            logging.debug(f"Found object id {result} for {object_name}")
        else:
            logging.debug(f"DID NOT Find object id {result} for {object_name}")
        return result


def add_space_after_prefix(s):
    """
    Convert a string like 'NGC1234' to 'NGC 1234'
    """
    # Use regex to match prefixes and numbers, and then join them with a space
    match = re.match(r"([a-zA-Z\-]+)(\d+)", s)
    if match:
        return " ".join(match.groups())
    return s


def delete_catalog_from_database(catalog_code: str):
    conn, db_c = objects_db.get_conn_cursor()
    # 1. Delete related records from the `catalog_objects` table
    db_c.execute("DELETE FROM catalog_objects WHERE catalog_code = ?", (catalog_code,))
    # 2. Delete the catalog record from the `catalogs` table
    db_c.execute("DELETE FROM catalogs WHERE catalog_code = ?", (catalog_code,))
    conn.commit()


def count_rows_per_distinct_column(conn, db_c, table, column):
    db_c.execute(f"SELECT {column}, COUNT(*) FROM {table} GROUP BY {column}")
    result = db_c.fetchall()
    for row in result:
        logging.info(f"{row[0]}: {row[1]} entries")


def get_catalog_counts():
    _conn, db_c = objects_db.get_conn_cursor()
    db_c.execute(
        "SELECT catalog_code, count(*) from catalog_objects group by catalog_code"
    )
    result = list(db_c.fetchall())
    for row in result:
        logging.info(f"{row[0]}: {row[1]} entries")
    return result


def count_empty_entries(conn, db_c, table, columns):
    db_c = conn.cursor()
    for column in columns:
        db_c.execute(
            f"""
                SELECT COUNT(*) FROM {table}
                WHERE {column} IS NULL OR {column} = ''
            """
        )
        result = db_c.fetchone()
        logging.info(f"{column}: {result[0]} empty entries")


def count_common_names_per_catalog():
    conn, db_c = objects_db.get_conn_cursor()
    count_rows_per_distinct_column(conn, db_c, "names", "origin")


def count_empty_entries_in_tables():
    conn, db_c = objects_db.get_conn_cursor()
    count_empty_entries(conn, db_c, "names", ["object_id", "common_name", "origin"])
    count_empty_entries(
        conn,
        db_c,
        "objects",
        [
            "obj_type",
            "ra",
            "dec",
            "const",
            "size",
            "mag",
        ],
    )


def print_database():
    logging.info(">-------------------------------------------------------")
    count_common_names_per_catalog()
    count_empty_entries_in_tables()
    logging.info("<-------------------------------------------------------")


def insert_catalog(catalog_name, description_path):
    with open(description_path, "r") as desc:
        description = "".join(desc.readlines())
    objects_db.insert_catalog(catalog_name, -1, description)


def insert_catalog_max_sequence(catalog_name):
    conn, db_c = objects_db.get_conn_cursor()
    query = f"""
            SELECT MAX(sequence) FROM catalog_objects
            where catalog_code = '{catalog_name}' GROUP BY catalog_code
        """
    db_c.execute(query)
    result = db_c.fetchone()
    # print(dict(result))
    query = f"""
        update catalogs set max_sequence = {
        dict(result)['MAX(sequence)']} where catalog_code = '{catalog_name}'
        """
    # print(query)
    db_c.execute(query)
    conn.commit()


def resolve_object_images():
    # This is the list of catalogs to search for
    # objects to match against image names
    _conn, db_c = objects_db.get_conn_cursor()
    resolution_priority = db_c.execute(
        """
            SELECT catalog_code
            FROM catalogs
            ORDER BY rowid
        """
    ).fetchall()

    # load all objects in objects table
    all_objects = objects_db.get_objects()

    for obj_record in tqdm(all_objects):
        resolved_name = None
        for entry in resolution_priority:
            catalog_code = entry["catalog_code"]
            catalog_check = db_c.execute(
                f"""
                    SELECT sequence
                    FROM catalog_objects
                    WHERE catalog_code = '{catalog_code}'
                    AND object_id = {obj_record['id']}
                """
            ).fetchone()
            if catalog_check:
                # Found a match!
                resolved_name = f"{catalog_code}{catalog_check['sequence']}"
                break

        if not resolved_name:
            logging.warning(f"No catalog entries for object: { obj_record['id']}")
        else:
            objects_db.insert_image_object(obj_record["id"], resolved_name)


# not used atm
def _load_deepmap_600():
    """
    loads the deepmap 600 file to add
    better descriptions and flag items
    on the list
    """
    data_path = Path(utils.astro_data_dir, "deepmap_600.txt")
    field_list = [
        "ID",
        "Catalog",
        "Name",
        "App Mag",
        "Type",
        "RA",
        "Dec",
        "Con",
        "Diff",
        "Mag1",
        "Mag2",
        "Sf Br",
        "Size",
        "CatNotes",
        "UserNotes",
    ]
    obj_list = []
    with open(data_path, "r") as deepmap:
        for line in deepmap:
            obj_rec = {}
            line = line.strip()
            ll = line.split("\t")
            for i, v in enumerate(ll):
                obj_rec[field_list[i]] = v
            obj_list.append(obj_rec)
    return obj_list


def load_egc():
    """
    Loads the PiFinder specific catalog of
    extragalactic globulars.  Brightest
    of M31 + extras
    """
    logging.info("Loading EGC")
    catalog = "EGC"
    conn, _db_c = objects_db.get_conn_cursor()
    delete_catalog_from_database(catalog)

    insert_catalog(catalog, Path(utils.astro_data_dir, "EGC.desc"))
    egc = Path(utils.astro_data_dir, "egc.tsv")
    with open(egc, "r") as df:
        # skip title line
        df.readline()
        for line in tqdm(list(df)):
            dfs = line.split("\t")
            sequence = dfs[0]
            other_names = dfs[1].split(",")

            ra = dfs[2].split()
            ra_h = int(ra[0])
            ra_m = int(ra[1])
            ra_s = float(ra[2])
            ra_deg = ra_to_deg(ra_h, ra_m, ra_s)

            dec = dfs[3].split()
            dec_deg = int(dec[0])
            dec_m = int(dec[1])
            dec_s = int(dec[2])
            dec_deg = dec_to_deg(dec_deg, dec_m, dec_s)

            size = dfs[5]
            mag = MagnitudeObject([float(dfs[4])])
            desc = dfs[7]

            new_object = NewCatalogObject(
                object_type="Gb",
                catalog_code=catalog,
                sequence=int(sequence),
                ra=ra_deg,
                dec=dec_deg,
                mag=mag,
                size=size,
                description=desc,
                aka_names=other_names,
            )
            new_object.insert()

    insert_catalog_max_sequence(catalog)
    conn.commit()


def load_collinder():
    logging.info("Loading Collinder")
    catalog = "Col"
    conn, _db_c = objects_db.get_conn_cursor()
    delete_catalog_from_database(catalog)
    insert_catalog(catalog, Path(utils.astro_data_dir, "collinder.desc"))
    coll = Path(utils.astro_data_dir, "collinder.txt")
    Collinder = namedtuple(
        "Collinder",
        [
            "sequence",
            "other_names",
            "ra_deg",
            "dec_deg",
            "size",
            "desc",
        ],
    )
    c_dict = {}
    with open(coll, "r") as df:
        df.readline()
        for line in df:
            dfs = line.split("\t")
            sequence = dfs[0].split(" ")[0]
            other_names = dfs[1]
            if other_names.isnumeric():
                other_names = "NGC " + other_names

            ra = dfs[3]
            ra_h = int(ra[0:2])
            ra_m = int(ra[4:6])
            ra_s = float(ra[8:12])
            ra_deg = ra_to_deg(ra_h, ra_m, ra_s)

            dec = dfs[4]
            dec_sign = dec[0]
            dec_deg = int(dec[1:3])
            if dec_sign == "-":
                dec_deg *= -1
            dec_m = int(dec[5:7])
            dec_s = int(dec[9:11])
            dec_deg = dec_to_deg(dec_deg, dec_m, dec_s)

            size = dfs[7]
            desc = f"{dfs[6]} stars, like {dfs[8]}"

            # Assuming all the parsing logic is done and all variables are available...

            collinder = Collinder(
                sequence=sequence,
                other_names=other_names.strip(),
                ra_deg=ra_deg,
                dec_deg=dec_deg,
                size=size,
                desc=desc,
            )
            c_dict[sequence] = collinder

    type_trans = {
        "Open cluster": "OC",
        "Asterism": "Ast",
        "Globular cluster": "Gb",
    }
    coll2 = Path(utils.astro_data_dir, "collinder2.txt")
    with open(coll2, "r") as df:
        df.readline()
        for line in tqdm(list(df)):
            duplicate_names = set()
            dfs = line.split("\t")
            sequence = dfs[0].split(" ")[1]
            obj_type = type_trans.get(dfs[4], "OC")
            mag = dfs[6].strip().split(" ")[0]
            if mag == "-":
                mag = MagnitudeObject([])
            else:
                mag = MagnitudeObject([float(mag)])
            other_names = dfs[2].strip()
            c_tuple = c_dict[sequence]

            # Figurre out other names
            if c_tuple.other_names and not c_tuple.other_names.startswith(
                ("[note", "Tr.", "Harv.", "Mel.")
            ):
                duplicate_names.add(c_tuple.other_names)

            if other_names and not other_names.startswith(("[note")):
                duplicate_names.add(other_names)

            new_object = NewCatalogObject(
                object_type=obj_type,
                catalog_code=catalog,
                sequence=int(sequence),
                ra=c_tuple.ra_deg,
                dec=c_tuple.dec_deg,
                mag=mag,
                size=c_tuple.size,
                description=c_tuple.desc,
                aka_names=list(duplicate_names),
            )
            new_object.insert()

    insert_catalog_max_sequence(catalog)
    conn.commit()


def load_bright_stars():
    logging.info("Loading Bright Named Stars")
    catalog = "Str"
    conn, _ = objects_db.get_conn_cursor()
    delete_catalog_from_database(catalog)
    insert_catalog(catalog, Path(utils.astro_data_dir, "Str.desc"))

    bstr = Path(utils.astro_data_dir, "bright_stars.csv")
    with open(bstr, "r") as df:
        # skip header
        df.readline()
        obj_type = "* "
        for line in tqdm(list(df)):
            dfs = line.split(",")
            dfs = [d.strip() for d in dfs]
            other_names = dfs[1:3]
            sequence = int(dfs[0]) + 1

            logging.debug(f"---------------> Bright Stars {sequence=} <---------------")
            size = ""
            # const = dfs[2].strip()
            desc = ""

            ra_h = int(dfs[3])
            ra_m = float(dfs[4])
            ra_deg = ra_to_deg(ra_h, ra_m, 0)

            dec_d = int(dfs[5])
            dec_m = float(dfs[6])
            dec_deg = dec_to_deg(dec_d, dec_m, 0)

            mag = MagnitudeObject([float(dfs[7].strip())])
            # const = dfs[8]

            new_object = NewCatalogObject(
                object_type=obj_type,
                catalog_code=catalog,
                sequence=int(sequence),
                ra=ra_deg,
                dec=dec_deg,
                mag=mag,
                size=size,
                description=desc,
                aka_names=other_names,
            )
            new_object.insert()

    insert_catalog_max_sequence(catalog)
    conn.commit()


def load_herschel400():
    """
    This TSV is from a web scrape of the
    Saguaro Astro Club h400 list as noted in their
    master DB
    """
    logging.info("Loading Herschel 400")
    catalog = "H"
    conn, _ = objects_db.get_conn_cursor()
    delete_catalog_from_database(catalog)
    insert_catalog(catalog, Path(utils.astro_data_dir, "herschel400.desc"))

    hcat = Path(utils.astro_data_dir, "herschel400.tsv")
    sequence = 0
    with open(hcat, "r") as df:
        # skip column headers
        df.readline()
        for line in tqdm(list(df)):
            dfs = line.split("\t")
            dfs = [d.strip() for d in dfs]
            NGC_sequence = dfs[0]
            h_name = dfs[7]
            h_desc = dfs[8]
            sequence += 1

            logging.debug(f"---------------> Herschel 400 {sequence=} <---------------")

            object_id = objects_db.get_catalog_object_by_sequence("NGC", NGC_sequence)[
                "id"
            ]
            objects_db.insert_name(object_id, h_name, catalog)
            objects_db.insert_catalog_object(object_id, catalog, sequence, h_desc)
    insert_catalog_max_sequence(catalog)
    conn.commit()


def load_sac_asterisms():
    logging.info("Loading SAC Asterisms")
    catalog = "SaA"
    conn, _ = objects_db.get_conn_cursor()
    delete_catalog_from_database(catalog)
    insert_catalog(catalog, Path(utils.astro_data_dir, "sac.desc"))

    saca = Path(utils.astro_data_dir, "SAC_Asterisms_Ver32_Fence.txt")
    sequence = 0
    with open(saca, "r") as df:
        df.readline()
        obj_type = "Ast"
        for line in tqdm(list(df)):
            dfs = line.split("|")
            dfs = [d.strip() for d in dfs]
            other_names = dfs[1].strip()
            if other_names == "":
                continue
            else:
                sequence += 1

            logging.debug(
                f"---------------> SAC Asterisms {sequence=} <---------------"
            )
            # const = dfs[2].strip()
            ra = dfs[3].strip()
            dec = dfs[4].strip()
            mag = dfs[5].strip()
            if mag == "none":
                mag = MagnitudeObject([])
            else:
                mag = MagnitudeObject([float(mag)])
            size = (
                dfs[6]
                .replace(" ", "")
                .replace("X", "x")
                .replace("deg", "°")
                .replace("d", "°")
            )
            desc = dfs[9].strip()

            ra = ra.split()
            ra_h = int(ra[0])
            ra_m = float(ra[1])
            ra_deg = ra_to_deg(ra_h, ra_m, 0)

            dec = dec.split(" ")
            dec_d = int(dec[0])
            dec_m = float(dec[1])
            dec_deg = dec_to_deg(dec_d, dec_m, 0)

            new_object = NewCatalogObject(
                object_type=obj_type,
                catalog_code=catalog,
                sequence=sequence,
                ra=ra_deg,
                dec=dec_deg,
                mag=mag,
                size=size,
                description=desc,
                aka_names=[other_names],
            )
            new_object.insert()

    insert_catalog_max_sequence(catalog)
    conn.commit()


def load_sac_multistars():
    logging.info("Loading SAC Multistars")
    catalog = "SaM"
    conn, _ = objects_db.get_conn_cursor()
    delete_catalog_from_database(catalog)
    sam_path = Path(utils.astro_data_dir, "SAC_Multistars_Ver40")
    insert_catalog(catalog, sam_path / "sacm.desc")
    saca = sam_path / "SAC_DBL40_Fence.txt"
    sequence = 0
    with open(saca, "r") as df:
        df.readline()
        obj_type = "D*"
        for line in tqdm(list(df)):
            dfs = line.split("|")
            dfs = [d.strip() for d in dfs]
            name = [dfs[2].strip()]
            other_names = dfs[6].strip().split(";")
            name.extend(other_names)
            name = [trim_string(x.strip()) for x in name if x != ""]
            if not name:
                continue
            else:
                sequence += 1

            logging.debug(
                f"---------------> SAC Multistars {sequence=} <---------------"
            )
            # const = dfs[1].strip()
            ra = dfs[3].strip()
            dec = dfs[4].strip()
            components = dfs[5].strip()
            mag = [dfs[7].strip(), dfs[8].strip()]
            mag = [x for x in mag if x != "none" and x != ""]
            mag = [float(x) if utils.is_number(x) else x for x in mag]
            mag = MagnitudeObject(mag)

            sep = dfs[9].strip()
            pa = dfs[10].strip()
            desc = dfs[11].strip()
            desc += f"\nComponents: {components}" if components else ""
            desc += f"\nPA: {pa}°" if pa else ""

            ra = ra.split()
            ra_h = int(ra[0])
            ra_m = float(ra[1])
            ra_deg = ra_to_deg(ra_h, ra_m, 0)

            dec = dec.split(" ")
            dec_d = int(dec[0])
            dec_m = float(dec[1])
            dec_deg = dec_to_deg(dec_d, dec_m, 0)

            new_object = NewCatalogObject(
                object_type=obj_type,
                catalog_code=catalog,
                sequence=sequence,
                ra=ra_deg,
                dec=dec_deg,
                mag=mag,
                size=sep,
                description=desc,
                aka_names=name,
            )
            new_object.insert()

    insert_catalog_max_sequence(catalog)
    conn.commit()


def trim_string(s):
    return " ".join(s.split())


def load_sac_redstars():
    logging.info("Loading SAC Redstars")
    catalog = "SaR"
    conn, _ = objects_db.get_conn_cursor()
    delete_catalog_from_database(catalog)

    sam_path = Path(utils.astro_data_dir, "SAC_RedStars_Ver20")
    insert_catalog(catalog, sam_path / "sacr.desc")
    sac = sam_path / "SAC_RedStars_ver20_FENCE.TXT"
    sequence = 0
    with open(sac, "r") as df:
        df.readline()
        obj_type = "D*"
        for line in tqdm(list(df)):
            dfs = line.split("|")
            dfs = [d.strip() for d in dfs]
            name = [dfs[1].strip()]
            other_names = dfs[2].strip().split(";")
            name.extend(other_names)
            name = [trim_string(x.strip()) for x in name if x != ""]
            if not name:
                continue
            else:
                sequence += 1

            logging.debug(
                f"---------------> SAC Red Stars {sequence=} <---------------"
            )
            # const = dfs[3].strip()
            ra = dfs[4].strip()
            dec = dfs[5].strip()
            size = ""
            mag = dfs[6].strip()
            if mag == "none":
                mag = MagnitudeObject([])
            else:
                mag = MagnitudeObject([float(mag)])
            bv = dfs[7].strip()
            spec = dfs[8].strip()
            notes = dfs[9].strip()
            desc = notes
            desc += f"\nB-V: {bv}"
            desc += f", Spec: {spec}"

            ra = ra.split(" ")
            ra_h = int(ra[0])
            ra_m = float(ra[1])
            ra_deg = ra_to_deg(ra_h, ra_m, 0)

            dec = dec.split(" ")
            dec_d = int(dec[0])
            dec_m = float(dec[1])
            dec_deg = dec_to_deg(dec_d, dec_m, 0)

            new_object = NewCatalogObject(
                object_type=obj_type,
                catalog_code=catalog,
                sequence=sequence,
                ra=ra_deg,
                dec=dec_deg,
                mag=mag,
                size=size,
                description=desc,
                aka_names=name,
            )
            new_object.insert()

    insert_catalog_max_sequence(catalog)
    conn.commit()


def load_taas200():
    logging.info("Loading Taas 200")
    catalog = "Ta2"
    conn, _ = objects_db.get_conn_cursor()
    delete_catalog_from_database(catalog)
    insert_catalog(catalog, Path(utils.astro_data_dir, "taas200.desc"))
    data = Path(utils.astro_data_dir, "TAAS_200.csv")
    sequence = 0

    typedict = {
        "oc": "Open Cluster",
        "gc": "Glob. Cluster",
        "gn": "Gaseous Neb.",
        "?gn": "?Gaseous Neb.",
        "pn": "Planeta. Neb.",
        "?pn": "?Planet. Neb.",
        "dn": "Dark Nebula",
        "snr": "SN Remnant",
        "eg": "Galaxy",
        "gn + oc": "Gas. Neb.+OC",
        "oc + oc": "OC + OC",
        "oc + gn": "OC+Gas. Neb.",
    }

    with open(data, "r") as f:
        reader = csv.DictReader(f)

        # Iterate over each row in the file
        for row in tqdm(list(reader)):
            sequence = int(row["Nr"])
            logging.debug(f"<----------------- TAAS {sequence=} ----------------->")
            ngc = row["NGC/IC"]
            other_catalog = []
            if ngc:
                if ngc.startswith("IC") or ngc.startswith("B") or ngc.startswith("Col"):
                    other_catalog.append(add_space_after_prefix(ngc))
                else:
                    split = ngc.split(";")
                    for s in split:
                        other_catalog.append(f"NGC {s}")

            other_names = row["Name"]
            logging.debug(f"TAAS catalog {other_catalog=} {other_names=}")
            obj_type = typedict[row["Type"]]
            ra = ra_to_deg(float(row["RA Hr"]), float(row["RA Min"]), 0)
            dec_deg = row["Dec Deg"]
            dec_deg = (
                float(dec_deg[1:]) if dec_deg[0] == "n" else float(dec_deg[1:]) * -1
            )
            dec = dec_to_deg(dec_deg, float(row["Dec Min"]), 0)
            mag = row["Magnitude"]
            if mag == "none" or mag == "":
                mag = MagnitudeObject([])
            else:
                mag = MagnitudeObject([float(mag)])
            size = row["Size"]
            desc = row["Description"]
            nr_stars = row["# Stars"]
            gc = row["GC Conc or Class"]
            h400 = row["Herschel 400"]
            min_ap = row["Min Aperture"]
            extra = []
            extra.append(f"{f'Min apert: {min_ap}' if min_ap != '' else ''}")
            extra.append(f"{f'Nr *:{nr_stars}' if nr_stars != '' else ''}")
            extra.append(f"{f'GC:{gc}' if gc != '' else ''}")
            extra.append(f"{'in Herschel 400' if h400 == 'Y' else ''}")
            extra = [x for x in extra if x]
            if len(extra) > 0:
                extra_desc = "\n" + "; ".join(extra)
                desc += extra_desc

            duplicate_names = set(other_catalog)
            duplicate_names.add(other_names)
            new_object = NewCatalogObject(
                object_type=obj_type,
                catalog_code=catalog,
                sequence=sequence,
                ra=ra,
                dec=dec,
                mag=mag,
                size=size,
                description=desc,
                aka_names=list(duplicate_names),
            )
            new_object.insert()

        insert_catalog_max_sequence(catalog)
        conn.commit()


def load_caldwell():
    logging.info("Loading Caldwell")
    catalog = "C"
    conn, _ = objects_db.get_conn_cursor()
    delete_catalog_from_database(catalog)
    insert_catalog(catalog, Path(utils.astro_data_dir, "caldwell.desc"))
    data = Path(utils.astro_data_dir, "caldwell.dat")
    with open(data, "r") as df:
        for line in tqdm(list(df)):
            dfs = line.split("\t")
            sequence = dfs[0].strip()
            logging.debug(f"<----------------- Caldwell {sequence=} ----------------->")
            other_names = add_space_after_prefix(dfs[1])
            obj_type = dfs[2]
            mag = dfs[4]
            if mag == "--":
                mag = MagnitudeObject([])
            else:
                mag = MagnitudeObject([float(mag)])
            size = dfs[5][5:].strip()
            ra_h = int(dfs[6])
            ra_m = float(dfs[7])
            ra_deg = ra_to_deg(ra_h, ra_m, 0)

            dec_sign = dfs[8]
            dec_deg = int(dfs[9])
            dec_m = float(dfs[10])
            if dec_sign == "-":
                dec_deg *= -1

            dec_deg = dec_to_deg(dec_deg, dec_m, 0)
            new_object = NewCatalogObject(
                object_type=obj_type,
                catalog_code=catalog,
                sequence=int(sequence),
                ra=ra_deg,
                dec=dec_deg,
                mag=mag,
                size=size,
                description="",
                aka_names=[other_names],
            )
            new_object.insert()

    insert_catalog_max_sequence(catalog)
    conn.commit()


def load_rasc_double_Stars():
    logging.info("Loading RASC Double Stars")
    catalog = "RDS"
    conn, _ = objects_db.get_conn_cursor()
    path = Path(utils.astro_data_dir, "RASC_DoubleStars")
    delete_catalog_from_database(catalog)
    insert_catalog(catalog, path / "rasc_ds.desc")
    data = path / "rasc_double_stars.csv"
    # Sequence Target	AlternateID	WDS	Con	RA2000	Dec2000	Mag MaxSep Notes
    with open(data, "r") as df:
        # skip title line
        df.readline()
        for row in tqdm(list(df)):
            dfs = row.split("\t")
            sequence = dfs[0].strip()
            logging.debug(f"<----------------- Rasc DS {sequence=} ----------------->")
            target = dfs[1]
            alternate_ids = dfs[2].split(",")
            wds = dfs[3]
            obj_type = "D*"
            # const = dfs[4]
            mags = json.loads(dfs[7])
            mag = MagnitudeObject(mags)
            size = dfs[8]
            # 03 31.1	+27 44
            ra = dfs[5].split()
            ra_h = int(ra[0])
            ra_m = float(ra[1])
            ra_deg = ra_to_deg(ra_h, ra_m, 0)

            dec = dfs[6].split()
            dec_deg = int(dec[0])
            dec_m = float(dec[1])
            dec_deg = dec_to_deg(dec_deg, dec_m, 0)
            desc = dfs[9].strip().replace("<NEWLINE>", "\n").replace("<SECS>", '"')
            aka_names = [target, wds] + alternate_ids

            new_object = NewCatalogObject(
                object_type=obj_type,
                catalog_code=catalog,
                sequence=int(sequence),
                ra=ra_deg,
                dec=dec_deg,
                mag=mag,
                size=size,
                description=desc,
                aka_names=aka_names,
            )
            new_object.insert()

    insert_catalog_max_sequence(catalog)
    conn.commit()


def load_barnard():
    logging.info("Loading Barnard Dark Objects")
    catalog = "B"
    conn, _ = objects_db.get_conn_cursor()
    path = Path(utils.astro_data_dir, "barnard")
    delete_catalog_from_database(catalog)
    insert_catalog(catalog, path / "barnard.desc")
    # object_finder = ObjectFinder()
    data = path / "barnard.dat"
    data_notes = path / "notes.dat"
    barn_dict = defaultdict(str)
    # build dictionary with notes
    with open(data_notes, "r") as notes:
        for line in notes:
            # Extract the Barnard number and text note from the line
            barn = line[1:5].strip()  # Bytes 2-5
            text = line[6:80].strip()  # Bytes 7-80
            barn_dict[barn] += f" {text}"

    # build catalog
    with open(data, "r") as df:
        for row in tqdm(list(df)):
            Barn = row[1:5].strip()
            if Barn[-1] == "a":
                print(f"Skipping {Barn=}")
                continue
            RA2000h = int(row[22:24])
            RA2000m = int(row[25:27])
            RA2000s = int(row[28:30]) if row[28:30].strip() else 0
            DE2000_sign = row[32]
            DE2000d = int(row[33:35])
            DE2000m = int(row[36:38])
            Diam = float(row[39:44]) if row[39:44].strip() else ""
            sequence = Barn
            logging.debug(f"<------------- Barnard {sequence=} ------------->")
            obj_type = "Nb"
            ra_h = RA2000h
            ra_m = RA2000m
            ra_s = RA2000s
            ra_deg = ra_to_deg(ra_h, ra_m, ra_s)

            dec_deg = DE2000d * -1 if DE2000_sign == "-" else DE2000d
            dec_m = DE2000m
            dec_deg = dec_to_deg(dec_deg, dec_m, 0)
            desc = barn_dict[Barn].strip()

            new_object = NewCatalogObject(
                object_type=obj_type,
                catalog_code=catalog,
                sequence=int(Barn),
                ra=ra_deg,
                dec=dec_deg,
                mag=MagnitudeObject([]),
                size=str(Diam),
                description=desc,
                aka_names=[],
            )
            new_object.insert()

    insert_catalog_max_sequence(catalog)
    conn.commit()


def load_sharpless():
    logging.info("Loading Sharpless")
    catalog = "Sh2"
    obj_type = "Nb"
    conn, _ = objects_db.get_conn_cursor()
    path = Path(utils.astro_data_dir, "sharpless")
    delete_catalog_from_database(catalog)
    insert_catalog(catalog, path / "sharpless.desc")
    data = path / "catalog.dat"
    akas = path / "akas.csv"
    descriptions = path / "galaxymap_descriptions.csv"
    form = {1: "circular", 2: "elliptical", 3: "irregular"}
    struct = {1: "amorphous", 2: "semi-amorphous", 3: "filamentary"}
    bright = {1: "dim", 2: "medium", 3: "bright"}

    # Define a list to hold all the extracted records
    records = []

    # read description dictionary
    descriptions_dict = {}
    with open(akas, mode="r", newline="", encoding="utf-8") as file:
        reader = csv.reader(open(descriptions, "r"))
        for row in reader:
            if len(row) == 2:
                k, v = row
                descriptions_dict[k] = v

    # read akas dictionary
    akas_dict = {}
    with open(akas, mode="r", newline="", encoding="utf-8") as file:
        reader = csv.reader(file, delimiter=";")
        for row in reader:
            if row:  # Ensure the row is not empty
                key = int(row[0])  # Convert the first column to an integer
                # Split second column on ',' and strip spaces
                values = [value.strip() for value in row[1].split(",")]
                akas_dict[key] = values

    # Open the file for reading
    with open(data, "r") as file:
        # Iterate over each line in the file
        for line in file:
            # Extract the relevant parts of each line based on byte positions
            record = {
                "Sh2": int(line[0:4].strip()),
                "RA1950": {
                    "h": int(line[34:36].strip()),
                    "m": int(line[36:38].strip()),
                    "ds": int(line[38:41].strip()),
                },
                "DE1950": {
                    "sign": line[41],
                    "d": int(line[42:44].strip()),
                    "m": int(line[44:46].strip()),
                    "s": int(line[46:48].strip()),
                },
                "Diam": int(line[48:52].strip()),
                "Form": int(line[52:53].strip()),
                "Struct": int(line[53:54].strip()),
                "Bright": int(line[54:55].strip()),
                "Stars": int(line[55:57].strip()),
            }
            # Append the extracted record to the list of records
            records.append(record)
    for record in tqdm(records):
        sh2 = int(record["Sh2"])
        ra_hours = (
            record["RA1950"]["h"]
            + record["RA1950"]["m"] / 60
            + record["RA1950"]["ds"] / 36000
        )
        dec_sign = -1 if record["DE1950"]["sign"] == "-" else 1
        dec_deg = dec_sign * (
            record["DE1950"]["d"]
            + record["DE1950"]["m"] / 60
            + record["DE1950"]["s"] / 3600
        )
        j_ra_h, j_dec_deg = b1950_to_j2000(ra_hours, dec_deg)
        j_ra_deg = j_ra_h._degrees
        j_dec_deg = j_dec_deg._degrees
        desc = f"{form[record['Form']]}, {struct[record['Struct']]}, {bright[record['Bright']]}, {record['Stars']}\n"

        desc += descriptions_dict[str(sh2)]
        current_akas = akas_dict[sh2] if sh2 in akas_dict else []

        new_object = NewCatalogObject(
            object_type=obj_type,
            catalog_code=catalog,
            sequence=record["Sh2"],
            ra=j_ra_deg,
            dec=dec_deg,
            size=str(record["Diam"]),
            mag=MagnitudeObject([]),
            description=desc,
            aka_names=current_akas,
        )
        new_object.insert()
    insert_catalog_max_sequence(catalog)
    conn.commit()


def load_arp():
    logging.info("Loading Arp")
    catalog = "Arp"
    path = Path(utils.astro_data_dir, "arp")
    delete_catalog_from_database(catalog)
    insert_catalog(catalog, path / "arp.desc")
    comments = path / "arp_comments.csv"

    def expand(name):
        expanded_list = []
        if "+" in name:
            parts = name.split("+")
            # Extract the base part and the rest
            base_part = parts[0]
            # Add the base part first
            expanded_list.append(base_part)
            # Process all subsequent parts
            for additional in parts[1:]:
                if additional.isdigit():
                    # If the additional part is a number, add it directly
                    expanded_list.append(f"{base_part[:-len(additional)]}{additional}")
                else:
                    expanded_list.append(additional)
        else:
            # Append the name directly if there is no '+'
            expanded_list.append(name)
        return expanded_list

    # read all comments for each Arp object
    with open(comments, "r") as f:
        arp_comments = {}
        reader = csv.DictReader(f)
        # Iterate over each row in the file
        for row in reader:
            arp = int(row["arp_number"])
            comment = row["comment"]
            arp_comments[arp] = comment

    # open arp sqlite db
    arp_conn = sqlite3.connect(path / "arp.sqlite")
    arp_conn.row_factory = sqlite3.Row
    arp_cur = arp_conn.cursor()

    arp_cur.execute(
        "select ra,dec,magnitude,name, catalog_identifier from cat order by catalog_identifier"
    )
    """
    There are multiple rows per object if there are multiple names
    so iterate through collecting names and object info and then
    write objects when the id changes
    """
    last_id = None
    aka_names = []
    new_object = None
    for row in tqdm(arp_cur.fetchall()):
        if last_id != row["catalog_identifier"]:
            # Save the previous object and start a new one
            if new_object is not None:
                new_object.insert()

            last_id = row["catalog_identifier"]
            mag = row["magnitude"]
            if utils.is_number(mag):
                mag = MagnitudeObject([float(mag)])
            else:
                print(f"Skipping {row['name']} {row['catalog_identifier']} {mag}")
                mag = MagnitudeObject([])
            new_object = NewCatalogObject(
                object_type="Gx",
                catalog_code="Arp",
                sequence=row["catalog_identifier"],
                ra=row["ra"],
                dec=row["dec"],
                mag=mag,
                description=arp_comments.get(row["catalog_identifier"], ""),
                aka_names=[row["name"]],
            )
        else:
            aka_names.append(row["name"])

    insert_catalog_max_sequence(catalog)
    arp_conn.commit()


def load_tlk_90_vars():
    logging.info("Loading TLK 90 Vars")
    catalog = "TLK"
    obj_type = "* "
    conn, _ = objects_db.get_conn_cursor()
    path = Path(utils.astro_data_dir, "variables/TLK_90_vars")
    delete_catalog_from_database(catalog)
    insert_catalog(catalog, path / "v90.desc")
    data = path / "v90.csv"

    # Open the file for reading
    with open(data, "r") as file:
        reader = csv.DictReader(file, delimiter=";")
        for nr, row in enumerate(tqdm(list(reader))):
            # Extract the relevant parts of each line based on byte positions

            v90_id = nr + 1
            ra_h = int(row["RA2K_H"])
            ra_m = int(row["RA2K_M"])
            ra_s = float(row["RA2K_S"].replace(",", "."))
            ra_deg = ra_to_deg(ra_h, ra_m, ra_s)

            dec_sign = -1 if row["DEC2K_SIGN"] == "-" else 1
            dec_deg = dec_sign * int(row["DEC2K_D"])
            dec_m = int(row["DEC2K_M"])
            dec_s = float(row["DEC2K_S"])
            dec_deg = dec_to_deg(dec_deg, dec_m, dec_s)

            desc = str(row["DESCRIPTION"])
            mag_max = float(row["MagMax"].replace(",", "."))
            mag_min = float(row["MagMin"].replace(",", "."))
            mag_object = MagnitudeObject([mag_max, mag_min])

            current_akas = row["STAR"].split(",") if row["STAR"] else []
            if row["SAO#"]:
                current_akas.append(f"SAO {row['SAO#']}")

            new_object = NewCatalogObject(
                object_type=obj_type,
                catalog_code=catalog,
                sequence=v90_id,
                ra=ra_deg,
                dec=dec_deg,
                mag=mag_object,
                size="",
                description=desc,
                aka_names=current_akas,
            )

            new_object.insert()

    insert_catalog_max_sequence(catalog)
    conn.commit()


def load_abell():
    logging.info("Loading Abell")
    catalog = "Abl"
    obj_type = "PN"
    conn, _ = objects_db.get_conn_cursor()
    data = Path(utils.astro_data_dir, "abell.tsv")
    delete_catalog_from_database(catalog)
    insert_catalog(catalog, Path(utils.astro_data_dir) / "abell.desc")

    # Open the file for reading
    with open(data, "r") as file:
        # Iterate over each line in the file
        for line in tqdm(list(file)[1:]):
            split_line = line.split("\t")
            # Extract the relevant parts of each line based on byte positions
            aka_names = [f"Abl {split_line[0].strip()}"]
            other_name = split_line[2].strip()
            if other_name != "":
                aka_names.append(other_name)

            new_object = NewCatalogObject(
                object_type=obj_type,
                catalog_code=catalog,
                sequence=int(split_line[0].strip()),
                ra=float(split_line[3].strip()),
                dec=float(split_line[4].strip()),
                mag=MagnitudeObject([float(split_line[5].strip())]),
                size=split_line[6].strip(),
                aka_names=aka_names,
            )

            new_object.insert()

    insert_catalog_max_sequence(catalog)
    conn.commit()


def load_ngc_catalog():
    logging.info("Loading NGC catalog")
    conn, _db_c = objects_db.get_conn_cursor()
    object_id_desc_dict = {}

    ngc_dat_files = [
        Path(utils.astro_data_dir, "ngc2000", "ngc2000.dat"),
        Path(utils.astro_data_dir, "messier_objects.dat"),
    ]
    # Add records for catalog descriptions
    delete_catalog_from_database("NGC")
    insert_catalog("NGC", Path(utils.astro_data_dir, "ngc2000", "ngc.desc"))
    delete_catalog_from_database("IC")
    insert_catalog("IC", Path(utils.astro_data_dir, "ic.desc"))
    delete_catalog_from_database("M")
    insert_catalog("M", Path(utils.astro_data_dir, "messier.desc"))

    for ngc_dat in ngc_dat_files:
        with open(ngc_dat, "r") as ngc:
            for line in tqdm(list(ngc)):
                sequence = int(line[1:5])
                # add = True
                catalog = line[0:1]
                if catalog == " " or catalog == "N":
                    catalog = "NGC"
                if catalog == "I":
                    catalog = "IC"
                obj_type = line[6:9].strip()
                rah = int(line[10:12])
                ram = float(line[13:17])
                des = line[19:20]
                ded = int(line[20:22])
                dem = int(line[23:25])
                line_size = line[32:33]
                size = line_size + line[33:38]
                mag = line[40:44].strip()
                if mag == "":
                    mag = MagnitudeObject([])
                else:
                    mag = MagnitudeObject([float(mag)])
                desc = line[46:].strip()

                dec = ded + (dem / 60)
                if des == "-":
                    dec = dec * -1
                ra = (rah + (ram / 60)) * 15
                new_object = NewCatalogObject(
                    object_type=obj_type,
                    catalog_code=catalog,
                    sequence=sequence,
                    ra=ra,
                    dec=dec,
                    mag=mag,
                    size=size,
                    description=desc,
                )
                new_object.insert()
                object_id_desc_dict[new_object.object_id] = desc

    # Additional processing for names and messier objects... (similarly transformed as above)
    # Now add the names
    # add records for M objects into objects....
    name_dat_files = [
        Path(utils.astro_data_dir, "ngc2000", "names.dat"),
        Path(utils.astro_data_dir, "extra_names.dat"),
    ]
    seen = set()
    for name_dat in tqdm(name_dat_files):
        with open(name_dat, "r") as names:
            for line in names:
                m_sequence = ""
                common_name = line[0:35]
                if common_name.startswith("M "):
                    m_sequence = common_name[2:].strip()
                    common_name = "M" + m_sequence
                catalog = line[36:37]
                if catalog == " ":
                    catalog = "N"
                if catalog == "N":
                    catalog = "NGC"
                if catalog == "I":
                    catalog = "IC"

                ngc_ic_sequence = line[37:41].strip()

                if ngc_ic_sequence != "":
                    obj = objects_db.get_catalog_object_by_sequence(
                        catalog, ngc_ic_sequence
                    )
                    if obj:
                        object_id = obj["object_id"]
                        objects_db.insert_name(object_id, common_name, catalog)
                        if m_sequence != "" and m_sequence not in seen:
                            desc = object_id_desc_dict[object_id]
                            objects_db.insert_catalog_object(
                                object_id, "M", m_sequence, desc
                            )
                            seen.add(m_sequence)
                    else:
                        logging.error(f"Can't find object id {catalog=}, {sequence=}")

    conn.commit()
    insert_catalog_max_sequence("NGC")
    insert_catalog_max_sequence("IC")
    insert_catalog_max_sequence("M")


if __name__ == "__main__":
    logging.info("starting main")
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logging.getLogger("PIL.PngImagePlugin").setLevel(logging.WARNING)
    logging.basicConfig(format="%(asctime)s %(name)s: %(levelname)s %(message)s")
    # formatter = logging.Formatter('%(asctime)s - %(name)-30s - %(levelname)-8s - %(message)s')

    parser = argparse.ArgumentParser(description="eFinder")
    parser.add_argument(
        "-f",
        "--force",
        help="DANGER: overwrite observations.db",
        default=False,
        action="store_true",
        required=False,
    )
    parser.add_argument(
        "-x", "--verbose", help="Set logging to debug mode", action="store_true"
    )
    parser.add_argument("-l", "--log", help="Log to file", action="store_true")
    args = parser.parse_args()
    # add the handlers to the logger

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    if args.log:
        datenow = datetime.datetime.now()
        filehandler = f"PiFinder-{datenow:%Y%m%d-%H_%M_%S}.log"
        fh = logging.FileHandler(filehandler)
        fh.setLevel(logger.level)
        logger.addHandler(fh)

    logging.info("Starting")
    # execute all functions
    logging.info("Creating DB")
    objects_db = ObjectsDatabase()
    observations_db = ObservationsDatabase()
    logging.info("creating catalog tables")
    objects_db.destroy_tables()
    objects_db.create_tables()
    logging.info("loading catalogs")
    # These load functions must be kept in this order
    # to keep some of the object referencing working
    # particularly starting with the NGC as the base
    load_ngc_catalog()
    load_caldwell()
    load_collinder()
    load_taas200()
    load_herschel400()
    load_sac_asterisms()
    load_sac_multistars()
    load_sac_redstars()
    load_bright_stars()
    load_egc()
    load_rasc_double_Stars()
    load_barnard()
    load_sharpless()
    load_abell()
    load_arp()
    load_tlk_90_vars()

    # Populate the images table
    logging.info("Resolving object images...")
    resolve_object_images()
    print_database()
