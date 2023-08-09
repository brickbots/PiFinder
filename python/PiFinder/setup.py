"""
This module holds various utils
and importers used during setup

"""
import csv
import argparse
import logging
import datetime
import re
from pathlib import Path
from typing import Dict
from PiFinder.obj_types import OBJ_DESCRIPTORS
import PiFinder.utils as utils
from PiFinder.db.objects_db import ObjectsDatabase
from PiFinder.db.observations_db import ObservationsDatabase
from collections import namedtuple

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
            f"{row['catalog_code']} {row['sequence']}": row["object_id"]
            for row in self.catalog_objects
        }

    def get_object_id(self, object: str):
        logging.debug(f"Looking up object id for {object}")
        return self.mappings.get(object)

    def get_object_id_by_parts(self, catalog_code: str, sequence: int):
        return self.mappings.get(f"{catalog_code} {sequence}")


def ra_to_deg(ra_h, ra_m, ra_s):
    ra_deg = ra_h
    if ra_m > 0:
        ra_deg += ra_m / 60
    if ra_s > 0:
        ra_deg += ra_s / 60 / 60
    ra_deg *= 15

    return ra_deg


def dec_to_deg(dec, dec_m, dec_s):
    dec_deg = abs(dec)

    if dec_m > 0:
        dec_deg += dec_m / 60
    if dec_s > 0:
        dec_deg += dec_s / 60 / 60
    if dec < 0:
        dec_deg *= -1

    return dec_deg


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
            f"SELECT COUNT(*) FROM {table} WHERE {column} IS NULL OR {column} = ''"
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


def insert_names(db_c, catalog, sequence, name):
    if name == "":
        return
    nameq = f"""
            insert into names(common_name, catalog, sequence)
            values ("{name}", "{catalog}", {sequence})
        """
    db_c.execute(nameq)


def insert_catalog(catalog_name, description_path):
    with open(description_path, "r") as desc:
        description = "".join(desc.readlines())
    objects_db.insert_catalog(catalog_name, -1, description)


def insert_catalog_max_sequence(catalog_name):
    conn, db_c = objects_db.get_conn_cursor()
    query = f"SELECT MAX(sequence) FROM catalog_objects where catalog_code = '{catalog_name}' GROUP BY catalog_code"
    db_c.execute(query)
    result = db_c.fetchone()
    print(dict(result))
    query = f"update catalogs set max_sequence = {dict(result)['MAX(sequence)']} where catalog_code = '{catalog_name}'"
    print(query)
    db_c.execute(query)
    conn.commit()


# not used atm
def load_deepmap_600():
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


def load_collinder():
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
        for l in df:
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
        for l in df:
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


def load_sac_asterisms():
    logging.info("Loading SAC Asterisms")
    catalog = "SaA"
    conn, _ = objects_db.get_conn_cursor()
    delete_catalog_from_database(catalog)
    insert_catalog(catalog, Path(utils.astro_data_dir, "sac.desc"))

    saca = Path(utils.astro_data_dir, "SAC_Asterisms_Ver32_Fence.txt")
    sequence = 0
    logging.info("Loading SAC Asterisms")
    with open(saca, "r") as df:
        df.readline()
        obj_type = "Ast"
        for l in df:
            dfs = l.split("|")
            dfs = [d.strip() for d in dfs]
            other_names = dfs[1].strip()
            if other_names == "":
                continue
            else:
                sequence += 1

            logging.debug(
                f"-----------------> SAC Asterisms {sequence=} <-----------------"
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
        for l in df:
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
                f"-----------------> SAC Multistars {sequence=} <-----------------"
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
        for l in df:
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
                f"-----------------> SAC Red Stars {sequence=} <-----------------"
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
        for row in reader:
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
        for l in df:
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
    delete_catalog_from_database("M")
    insert_catalog("M", Path(utils.astro_data_dir, "messier.desc"))
    delete_catalog_from_database("IC")
    insert_catalog("IC", Path(utils.astro_data_dir, "ic.desc"))

    for ngc_dat in ngc_dat_files:
        with open(ngc_dat, "r") as ngc:
            for l in ngc:
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
    for name_dat in name_dat_files:
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
                        if m_sequence != "":
                            desc = object_id_desc_dict[object_id]
                            objects_db.insert_catalog_object(
                                object_id, "M", m_sequence, desc
                            )
                    else:
                        logging.debug(f"Can't find object id {catalog=}, {sequence=}")

    conn.commit()
    insert_catalog_max_sequence("NGC")
    insert_catalog_max_sequence("IC")
    insert_catalog_max_sequence("M")
    logging.info("NGC catalog loaded.")


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
    # objects_db.destroy_tables()
    objects_db.create_tables()
    if not observations_db.exists():
        observations_db.create_tables()
    logging.info("loading catalogs")
    load_ngc_catalog()
    load_collinder()
    load_taas200()
    load_sac_asterisms()
    load_sac_multistars()
    load_sac_redstars()
    load_caldwell()
    print_database()
