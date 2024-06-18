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
from typing import Dict, List

# from PiFinder.obj_types import OBJ_DESCRIPTORS
import PiFinder.utils as utils
from PiFinder.ui.ui_utils import normalize
from PiFinder.calc_utils import (
    ra_to_deg,
    dec_to_deg,
    sf_utils,
    b1950_to_j2000,
    epoch_to_epoch,
)
from PiFinder.db.objects_db import ObjectsDatabase
from PiFinder.db.observations_db import ObservationsDatabase
from collections import namedtuple, defaultdict

objects_db: ObjectsDatabase
observations_db: ObservationsDatabase


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
        return result


def insert_akas(
    objects_db, current_object: str, catalog: str, akas: List[str], new_object_id
) -> List[int]:
    """
    Eg. SH2-005 is NGC6357
    First we insert NGC6357 as an aka for SH2-005
    Then we insert SH2-005 as an aka for NGC6357
    """
    object_finder = ObjectFinder()
    found = []
    for aka in akas:
        found_object_id = object_finder.get_object_id(aka)
        if found_object_id:
            found.append(found_object_id)

    print(f"Found {found}")
    for aka in akas:
        objects_db.insert_name(new_object_id, aka, catalog)
        print(f"Inserted {aka} for {new_object_id} in catalog {catalog}")
    for found_id in found:
        objects_db.insert_name(found_id, current_object, catalog)
        print(f"Inserted {current_object} for {found_id} in catalog {catalog}")
    return found


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
    conn, db_c = objects_db.get_conn_cursor()
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
        field_index = 0
        for l in deepmap:
            obj_rec = {}
            l = l.strip()
            ll = l.split("\t")
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
    conn, db_c = objects_db.get_conn_cursor()
    delete_catalog_from_database(catalog)

    insert_catalog(catalog, Path(utils.astro_data_dir, "EGC.desc"))
    object_finder = ObjectFinder()
    egc = Path(utils.astro_data_dir, "egc.tsv")
    with open(egc, "r") as df:
        # skip title line
        df.readline()
        for l in tqdm(list(df)):
            dfs = l.split("\t")
            sequence = dfs[0]
            other_names = dfs[1].split(",")

            const = dfs[6]
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
            mag = dfs[4]
            desc = dfs[7]

            object_id = None
            for name in other_names:
                if name.startswith("NGC"):
                    object_id = object_finder.get_object_id(name)

            # Assuming all the parsing logic is done and all variables are available...
            if object_id == None:
                obj_type = "Gb"
                object_id = objects_db.insert_object(
                    obj_type, ra_deg, dec_deg, const, size, mag
                )

            for other_name in other_names:
                objects_db.insert_name(object_id, other_name, catalog)

            objects_db.insert_catalog_object(object_id, catalog, sequence, desc)

    insert_catalog_max_sequence(catalog)
    conn.commit()


def load_collinder():
    logging.info("Loading Collinder")
    catalog = "Col"
    conn, db_c = objects_db.get_conn_cursor()
    delete_catalog_from_database(catalog)
    insert_catalog(catalog, Path(utils.astro_data_dir, "collinder.desc"))
    object_finder = ObjectFinder()
    coll = Path(utils.astro_data_dir, "collinder.txt")
    Collinder = namedtuple(
        "Collinder",
        [
            "sequence",
            "other_names",
            "const",
            "ra_deg",
            "dec_deg",
            "size",
            "desc",
            "object_id",
        ],
    )
    c_dict = {}
    with open(coll, "r") as df:
        df.readline()
        for l in tqdm(list(df)):
            dfs = l.split("\t")
            sequence = dfs[0].split(" ")[0]
            other_names = dfs[1]
            if other_names.isnumeric():
                other_names = "NGC " + other_names

            const = dfs[2]
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

            object_id = object_finder.get_object_id(other_names)
            # Assuming all the parsing logic is done and all variables are available...

            collinder = Collinder(
                sequence=sequence,
                other_names=other_names,
                const=const,
                ra_deg=ra_deg,
                dec_deg=dec_deg,
                size=size,
                desc=desc,
                object_id=object_id,
            )
            c_dict[sequence] = collinder

    type_trans = {
        "Open cluster": "OC",
        "Asterism": "Ast",
        "Globular cluster": "Gb",
    }
    coll2 = Path(utils.astro_data_dir, "collinder2.txt")
    with open(coll2, "r") as df:
        duplicate_names = set()
        df.readline()
        for l in tqdm(list(df)):
            dfs = l.split("\t")
            sequence = dfs[0].split(" ")[1]
            obj_type = type_trans.get(dfs[4], "OC")
            mag = dfs[6].strip().split(" ")[0]
            if mag == "-":
                mag = ""
            other_names = dfs[2].strip()
            c_tuple = c_dict[sequence]
            object_id = c_tuple.object_id
            if object_id is None:
                object_id = objects_db.insert_object(
                    obj_type,
                    c_tuple.ra_deg,
                    c_tuple.dec_deg,
                    c_tuple.const,
                    c_tuple.size,
                    mag,
                )
            objects_db.insert_catalog_object(object_id, catalog, sequence, c_tuple.desc)
            first_other_names = c_tuple.other_names.strip()
            if (
                first_other_names
                and not first_other_names in duplicate_names
                and not first_other_names.startswith(("[note", "Tr.", "Harv.", "Mel."))
            ):
                logging.debug(f"{first_other_names=}")
                objects_db.insert_name(object_id, first_other_names, catalog + "1")
                duplicate_names.add(first_other_names)
            if (
                other_names
                and not other_names == first_other_names
                and not other_names in duplicate_names
                and not other_names.startswith(("[note"))
            ):
                logging.debug(f"{other_names=}")
                objects_db.insert_name(object_id, other_names, catalog + "2")
                duplicate_names.add(first_other_names)

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
        for l in tqdm(list(df)):
            dfs = l.split(",")
            dfs = [d.strip() for d in dfs]
            other_names = dfs[1:3]
            sequence = int(dfs[0]) + 1

            logging.debug(f"---------------> Bright Stars {sequence=} <---------------")
            size = ""
            const = dfs[2].strip()
            desc = ""

            ra_h = int(dfs[3])
            ra_m = float(dfs[4])
            ra_deg = ra_to_deg(ra_h, ra_m, 0)

            dec_d = int(dfs[5])
            dec_m = float(dfs[6])
            dec_deg = dec_to_deg(dec_d, dec_m, 0)

            mag = dfs[7].strip()
            const = dfs[8].strip()

            object_id = objects_db.insert_object(
                obj_type, ra_deg, dec_deg, const, size, mag
            )

            for other_name in other_names:
                objects_db.insert_name(object_id, other_name, catalog)

            objects_db.insert_catalog_object(object_id, catalog, sequence, desc)
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
        for l in tqdm(list(df)):
            dfs = l.split("\t")
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
        for l in tqdm(list(df)):
            dfs = l.split("|")
            dfs = [d.strip() for d in dfs]
            other_names = dfs[1].strip()
            if other_names == "":
                continue
            else:
                sequence += 1

            logging.debug(
                f"---------------> SAC Asterisms {sequence=} <---------------"
            )
            const = dfs[2].strip()
            ra = dfs[3].strip()
            dec = dfs[4].strip()
            mag = dfs[5].strip()
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

            if mag == "none":
                mag = ""

            object_id = objects_db.insert_object(
                obj_type, ra_deg, dec_deg, const, size, mag
            )
            objects_db.insert_name(object_id, other_names, catalog)
            objects_db.insert_catalog_object(object_id, catalog, sequence, desc)
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
        for l in tqdm(list(df)):
            dfs = l.split("|")
            dfs = [d.strip() for d in dfs]
            name = [dfs[2].strip()]
            other_names = dfs[6].strip().split(";")
            name.extend(other_names)
            name = [trim_string(x.strip()) for x in name if x != ""]
            other_names = ", ".join(name)
            if other_names == "":
                continue
            else:
                sequence += 1

            logging.debug(
                f"---------------> SAC Multistars {sequence=} <---------------"
            )
            const = dfs[1].strip()
            ra = dfs[3].strip()
            dec = dfs[4].strip()
            components = dfs[5].strip()
            mag = dfs[7].strip()
            mag2 = dfs[8].strip()
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

            if mag == "none":
                mag = ""

            object_id = objects_db.insert_object(
                obj_type, ra_deg, dec_deg, const, sep, f"{mag}/{mag2}"
            )
            objects_db.insert_name(object_id, other_names, catalog)
            objects_db.insert_catalog_object(object_id, catalog, sequence, desc)

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
        for l in tqdm(list(df)):
            dfs = l.split("|")
            dfs = [d.strip() for d in dfs]
            name = [dfs[1].strip()]
            other_names = dfs[2].strip().split(";")
            name.extend(other_names)
            name = [trim_string(x.strip()) for x in name if x != ""]
            other_names = ", ".join(name)
            if other_names == "":
                continue
            else:
                sequence += 1

            logging.debug(
                f"---------------> SAC Red Stars {sequence=} <---------------"
            )
            const = dfs[3].strip()
            ra = dfs[4].strip()
            dec = dfs[5].strip()
            size = ""
            mag = dfs[6].strip()
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

            if mag == "none":
                mag = ""

            object_id = objects_db.insert_object(
                obj_type, ra_deg, dec_deg, const, size, mag
            )
            objects_db.insert_name(object_id, other_names, catalog)
            objects_db.insert_catalog_object(object_id, catalog, sequence, desc)

    insert_catalog_max_sequence(catalog)
    conn.commit()


def load_taas200():
    logging.info("Loading Taas 200")
    catalog = "Ta2"
    conn, _ = objects_db.get_conn_cursor()
    delete_catalog_from_database(catalog)
    insert_catalog(catalog, Path(utils.astro_data_dir, "taas200.desc"))
    object_finder = ObjectFinder()
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
            duplicate_names = set()
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
            const = row["Const"]
            obj_type = typedict[row["Type"]]
            ra = ra_to_deg(float(row["RA Hr"]), float(row["RA Min"]), 0)
            dec_deg = row["Dec Deg"]
            dec_deg = (
                float(dec_deg[1:]) if dec_deg[0] == "n" else float(dec_deg[1:]) * -1
            )
            dec = dec_to_deg(dec_deg, float(row["Dec Min"]), 0)
            mag = row["Magnitude"]
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
            extra.append(f"{f'in Herschel 400' if h400 == 'Y' else ''}")
            extra = [x for x in extra if x]
            if len(extra) > 0:
                extra_desc = "\n" + "; ".join(extra)
                desc += extra_desc

            if mag == "none":
                mag = "null"

            if len(other_catalog) > 0:
                object_id = object_finder.get_object_id(other_catalog[0])
                if not object_id:
                    object_id = objects_db.insert_object(
                        obj_type, ra, dec, const, size, mag
                    )
                    logging.debug(f"inserting unknown object {object_id=}")
                logging.debug(f"TAAS inserting {object_id=}, {catalog=}, {sequence=}")
                objects_db.insert_catalog_object(object_id, catalog, sequence, desc)

                if other_names not in duplicate_names:
                    objects_db.insert_name(object_id, other_names, catalog)
                    duplicate_names.add(other_names)
                for catalog_name in other_catalog:
                    if catalog_name not in duplicate_names:
                        objects_db.insert_name(object_id, catalog_name, catalog)
                        duplicate_names.add(catalog_name)

        insert_catalog_max_sequence(catalog)
        conn.commit()


def load_caldwell():
    logging.info("Loading Caldwell")
    catalog = "C"
    conn, _ = objects_db.get_conn_cursor()
    delete_catalog_from_database(catalog)
    insert_catalog(catalog, Path(utils.astro_data_dir, "caldwell.desc"))
    object_finder = ObjectFinder()
    data = Path(utils.astro_data_dir, "caldwell.dat")
    with open(data, "r") as df:
        for l in tqdm(list(df)):
            dfs = l.split("\t")
            sequence = dfs[0].strip()
            logging.debug(f"<----------------- Caldwell {sequence=} ----------------->")
            other_names = add_space_after_prefix(dfs[1])
            obj_type = dfs[2]
            const = dfs[3]
            mag = dfs[4]
            if mag == "--":
                mag = "null"
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
            desc = ""
            object_id = object_finder.get_object_id(other_names)
            if not object_id:
                object_id = objects_db.insert_object(
                    obj_type, ra_deg, dec_deg, const, size, mag
                )
                logging.debug(f"inserting unknown object {object_id=}")
            objects_db.insert_catalog_object(object_id, catalog, sequence, desc)
            objects_db.insert_name(object_id, other_names, catalog)
    insert_catalog_max_sequence(catalog)
    conn.commit()


def load_rasc_double_Stars():
    logging.info("Loading RASC Double Stars")
    catalog = "RDS"
    conn, _ = objects_db.get_conn_cursor()
    path = Path(utils.astro_data_dir, "RASC_DoubleStars")
    delete_catalog_from_database(catalog)
    insert_catalog(catalog, path / "rasc_ds.desc")
    object_finder = ObjectFinder()
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
            const = dfs[4]
            mags = json.loads(dfs[7])
            mag = mags[0]
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
            object_id = object_finder.get_object_id(wds)
            if not object_id:
                object_id = objects_db.insert_object(
                    obj_type, ra_deg, dec_deg, const, size, mag
                )
                logging.debug(f"inserting unknown object {object_id=}")
            objects_db.insert_catalog_object(object_id, catalog, sequence, desc)
            for name in alternate_ids:
                objects_db.insert_name(object_id, name, catalog)
            objects_db.insert_name(object_id, wds, catalog)
            objects_db.insert_name(object_id, target, catalog)
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
            const = sf_utils.radec_to_constellation(ra_deg, dec_deg)
            # object_id = object_finder.get_object_id(wds)
            # if not object_id:
            object_id = objects_db.insert_object(
                obj_type, ra_deg, dec_deg, const, Diam, ""
            )
            logging.debug(f"inserting unknown object {object_id=}")
            objects_db.insert_catalog_object(object_id, catalog, sequence, desc)
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
    for record in records:
        sh2 = int(record["Sh2"])
        ra_hours = (
            record["RA1950"]["h"]
            + record["RA1950"]["m"] / 60
            + record["RA1950"]["ds"] / 36000
        )
        # print(f'{record["RA1950"]} {record["DE1950"]}')
        dec_sign = -1 if record["DE1950"]["sign"] == "-" else 1
        dec_deg = dec_sign * (
            record["DE1950"]["d"]
            + record["DE1950"]["m"] / 60
            + record["DE1950"]["s"] / 3600
        )
        # print(f"RA: {ra_hours}, Dec: {dec_deg}")
        j_ra_h, j_dec_deg = b1950_to_j2000(ra_hours, dec_deg)
        j_ra_deg = j_ra_h._degrees
        j_dec_deg = j_dec_deg._degrees
        const = sf_utils.radec_to_constellation(j_ra_deg, j_dec_deg)
        desc = f"{form[record['Form']]}, {struct[record['Struct']]}, {bright[record['Bright']]}, {record['Stars']}\n"

        desc += descriptions_dict[str(sh2)]
        current_object = f"Sh2-{sh2}"
        current_akas = akas_dict[sh2] if sh2 in akas_dict else []
        object_id = objects_db.insert_object(
            obj_type, j_ra_deg, dec_deg, const, str(record["Diam"]), desc
        )
        insert_akas(objects_db, current_object, catalog, current_akas, object_id)
        objects_db.insert_catalog_object(object_id, catalog, record["Sh2"], desc)

    insert_catalog_max_sequence(catalog)
    conn.commit()


def load_arp():
    logging.info("Loading Arp")
    catalog = "Arp"
    obj_type = "Gx"
    conn, _ = objects_db.get_conn_cursor()
    path = Path(utils.astro_data_dir, "arp")
    delete_catalog_from_database(catalog)
    insert_catalog(catalog, path / "arp.desc")
    data = path / "table2.txt"
    records = []

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

    with open(data, "r") as file:
        for line in file:
            if line.strip():  # Ensure the line is not empty
                # Extract fields based on fixed widths
                RAh = int(line[0:2].strip())
                RAm = float(line[3:7].strip())
                pPos = line[7].strip()
                DE_sign = line[11].strip()
                DEd = int(line[12:14].strip())
                DEm = int(line[15:17].strip())
                APG = int(line[20:23].strip())
                Name = line[27:43].strip()
                Redshifts = line[45:90].strip()

                # Use the Arp's number (APG) as the key
                record = {
                    "APG": APG,
                    "RAh": RAh,
                    "RAm": RAm,
                    "pPos": pPos,
                    "DE_sign": DE_sign,
                    "DEd": DEd,
                    "DEm": DEm,
                    "Name": expand(Name),
                    "Redshifts": Redshifts,
                }
            records.append(record)

    for record in records:
        arp = int(record["APG"])
        ra_hours = record["RAh"] + record["RAm"] / 60
        dec_sign = -1 if record["pPos"] == "-" else 1
        dec_deg = dec_sign * (record["DEd"] + record["DEd"] / 60)
        # print(f"RA: {ra_hours}, Dec: {dec_deg}")
        j_ra_h, j_dec_deg = epoch_to_epoch(1970, 2000, ra_hours, dec_deg)
        j_ra_deg = j_ra_h._degrees
        j_dec_deg = j_dec_deg._degrees
        const = sf_utils.radec_to_constellation(j_ra_deg, j_dec_deg)
        desc = f"Redshifts: {record['Redshifts']}\n" if record["Redshifts"] else ""

        current_akas = record["Name"]
        current_object = f"Arp-{arp}"
        object_id = objects_db.insert_object(obj_type, j_ra_deg, dec_deg, const, "", "")
        insert_akas(objects_db, current_object, catalog, current_akas, object_id)
        objects_db.insert_catalog_object(object_id, catalog, arp, desc)

    insert_catalog_max_sequence(catalog)
    conn.commit()


def load_abell():
    logging.info("Loading Abell")
    object_finder = ObjectFinder()
    catalog = "Abl"
    obj_type = "PN"
    conn, _ = objects_db.get_conn_cursor()
    data = Path(utils.astro_data_dir, "abell.tsv")
    delete_catalog_from_database(catalog)
    insert_catalog(catalog, Path(utils.astro_data_dir) / "abell.desc")

    # Define a list to hold all the extracted records
    records = []

    # Open the file for reading
    with open(data, "r") as file:
        # Iterate over each line in the file
        for line in list(file)[1:]:
            split_line = line.split("\t")
            # Extract the relevant parts of each line based on byte positions
            record = {
                "id": int(split_line[0].strip()),
                "AKA": split_line[2].strip(),
                "RA": float(split_line[3].strip()),
                "Dec": float(split_line[4].strip()),
                "Mag": float(split_line[5].strip()),
                "Size": float(split_line[6].strip()),
                "const": split_line[7].strip(),
                "desc": "",
            }
            # Append the extracted record to the list of records
            records.append(record)
    for record in tqdm(records):
        object_id = object_finder.get_object_id(record["AKA"])
        if not object_id:
            # obj_type, ra, dec, const, size, mag
            object_id = objects_db.insert_object(
                obj_type,
                record["RA"],
                record["Dec"],
                record["const"],
                record["Size"],
                record["Mag"],
            )
        else:
            objects_db.insert_name(object_id, f"Abell {record['id']}", catalog)

        objects_db.insert_catalog_object(
            object_id, catalog, record["id"], record["desc"]
        )

    insert_catalog_max_sequence(catalog)
    conn.commit()


def load_ngc_catalog():
    logging.info("Loading NGC catalog")
    conn, db_c = objects_db.get_conn_cursor()
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
            for l in tqdm(list(ngc)):
                sequence = int(l[1:5])
                # add = True
                catalog = l[0:1]
                if catalog == " " or catalog == "N":
                    catalog = "NGC"
                if catalog == "I":
                    catalog = "IC"
                obj_type = l[6:9].strip()
                rah = int(l[10:12])
                ram = float(l[13:17])
                des = l[19:20]
                ded = int(l[20:22])
                dem = int(l[23:25])
                const = l[29:32]
                l_size = l[32:33]
                size = l_size + l[33:38]
                mag = l[40:44]
                desc = l[46:].strip()

                dec = ded + (dem / 60)
                if des == "-":
                    dec = dec * -1
                ra = (rah + (ram / 60)) * 15
                object_id = objects_db.insert_object(
                    obj_type, ra, dec, const, size, mag
                )
                objects_db.insert_catalog_object(object_id, catalog, sequence, desc)
                object_id_desc_dict[object_id] = desc

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
            for l in names:
                m_sequence = ""
                common_name = l[0:35]
                if common_name.startswith("M "):
                    m_sequence = common_name[2:].strip()
                    common_name = "M" + m_sequence
                catalog = l[36:37]
                if catalog == " ":
                    catalog = "N"
                if catalog == "N":
                    catalog = "NGC"
                if catalog == "I":
                    catalog = "IC"

                ngc_ic_sequence = l[37:41].strip()
                comment = l[42:]

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
                        logging.debug(f"Can't find object id {catalog=}, {sequence=}")

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
        datenow = datetime.now()
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
    load_arp()
    load_abell()

    # Populate the images table
    logging.info("Resolving object images...")
    resolve_object_images()
    print_database()
