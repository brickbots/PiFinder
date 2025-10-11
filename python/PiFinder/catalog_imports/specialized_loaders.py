"""
Specialized catalog loaders for PiFinder.

This module loads various specialized astronomical catalogs including
EGC, Collinder, TAAS200, RASC double stars, Barnard, Sharpless, Arp,
TLK variables, and Abell catalogs.
"""

import csv
import json
import logging
import sqlite3
from pathlib import Path
from tqdm import tqdm
from collections import namedtuple, defaultdict

import PiFinder.utils as utils
from PiFinder.composite_object import MagnitudeObject
from PiFinder.calc_utils import ra_to_deg, dec_to_deg, b1950_to_j2000
from .catalog_import_utils import (
    NewCatalogObject,
    delete_catalog_from_database,
    insert_catalog,
    insert_catalog_max_sequence,
    add_space_after_prefix,
)

# Import shared database object
from .database import objects_db

logger = logging.getLogger("SpecializedLoaders")


def load_egc():
    """
    Load the EGC (Extragalactic Globular Clusters) catalog.

    Loads the PiFinder specific catalog of
    extragalactic globulars. Brightest
    of M31 + extras
    """
    logging.info("Loading EGC")
    catalog = "EGC"
    conn, _db_c = objects_db.get_conn_cursor()
    delete_catalog_from_database(catalog)

    insert_catalog(catalog, Path(utils.astro_data_dir, "EGC.desc"))
    egc = Path(utils.astro_data_dir, "egc.tsv")

    # Create shared ObjectFinder to avoid recreating for each object
    from .catalog_import_utils import ObjectFinder

    shared_finder = ObjectFinder()
    NewCatalogObject.set_shared_finder(shared_finder)

    try:
        with open(egc, "r") as df:
            # skip title line
            df.readline()
            for line in tqdm(list(df), leave=False):
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
    finally:
        NewCatalogObject.clear_shared_finder()

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
    # Prepare objects for batch insertion
    objects_to_insert = []
    coll2 = Path(utils.astro_data_dir, "collinder2.txt")
    with open(coll2, "r") as df:
        df.readline()
        for line in tqdm(list(df), desc="Processing Collinder data", leave=False):
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

            # Collect all valid names more efficiently
            aka_names = []
            if c_tuple.other_names and not c_tuple.other_names.startswith(
                ("[note", "Tr.", "Harv.", "Mel.")
            ):
                aka_names.append(c_tuple.other_names)

            if other_names and not other_names.startswith("[note"):
                aka_names.append(other_names)

            new_object = NewCatalogObject(
                object_type=obj_type,
                catalog_code=catalog,
                sequence=int(sequence),
                ra=c_tuple.ra_deg,
                dec=c_tuple.dec_deg,
                mag=mag,
                size=c_tuple.size,
                description=c_tuple.desc,
                aka_names=aka_names,
            )
            objects_to_insert.append(new_object)

    # Batch insert all objects with shared finder
    objects_db.bulk_mode = True

    # Create shared ObjectFinder to avoid recreating for each object
    from .catalog_import_utils import ObjectFinder

    shared_finder = ObjectFinder()
    NewCatalogObject.set_shared_finder(shared_finder)

    try:
        for obj in tqdm(
            objects_to_insert, desc="Inserting Collinder objects", leave=False
        ):
            obj.insert()
        conn.commit()
    finally:
        objects_db.bulk_mode = False
        NewCatalogObject.clear_shared_finder()

    insert_catalog_max_sequence(catalog)
    conn.commit()


def load_taas200():
    """Load the TAAS 200 catalog"""
    logging.info("Loading Taas 200")
    catalog = "Ta2"
    conn, _ = objects_db.get_conn_cursor()
    delete_catalog_from_database(catalog)
    insert_catalog(catalog, Path(utils.astro_data_dir, "taas200.desc"))
    data = Path(utils.astro_data_dir, "TAAS_200.csv")
    sequence = 0

    # Prepare objects for batch insertion
    objects_to_insert = []
    # Create shared ObjectFinder to avoid recreating for each object
    from .catalog_import_utils import ObjectFinder

    shared_finder = ObjectFinder()

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
        for row in tqdm(list(reader), leave=False):
            sequence = int(row["Nr"])
            logger.debug(f"<----------------- TAAS {sequence=} ----------------->")
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
            logger.debug(f"TAAS catalog {other_catalog=} {other_names=}")
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
            objects_to_insert.append(new_object)

        # Batch insert all objects
        objects_db.bulk_mode = True
        # Set up shared finder for performance
        NewCatalogObject.set_shared_finder(shared_finder)
        try:
            for obj in tqdm(
                objects_to_insert, desc="Inserting TAAS200 objects", leave=False
            ):
                obj.insert()
            conn.commit()
        finally:
            objects_db.bulk_mode = False
            NewCatalogObject.clear_shared_finder()

        insert_catalog_max_sequence(catalog)


def load_rasc_double_Stars():
    """Load the RASC Double Stars catalog"""
    logging.info("Loading RASC Double Stars")
    catalog = "RDS"
    conn, _ = objects_db.get_conn_cursor()
    path = Path(utils.astro_data_dir, "RASC_DoubleStars")
    delete_catalog_from_database(catalog)
    insert_catalog(catalog, path / "rasc_ds.desc")
    data = path / "rasc_double_stars.csv"

    # Create shared ObjectFinder to avoid recreating for each object
    from .catalog_import_utils import ObjectFinder

    shared_finder = ObjectFinder()
    NewCatalogObject.set_shared_finder(shared_finder)

    try:
        # Sequence Target	AlternateID	WDS	Con	RA2000	Dec2000	Mag MaxSep Notes
        with open(data, "r") as df:
            # skip title line
            df.readline()
            for row in tqdm(list(df), leave=False):
                dfs = row.split("\t")
                sequence = dfs[0].strip()
                logger.debug(
                    f"<----------------- Rasc DS {sequence=} ----------------->"
                )
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
    finally:
        NewCatalogObject.clear_shared_finder()

    insert_catalog_max_sequence(catalog)
    conn.commit()


def load_barnard():
    logging.info("Loading Barnard Dark Objects")
    catalog = "B"
    conn, _ = objects_db.get_conn_cursor()
    path = Path(utils.astro_data_dir, "barnard")
    delete_catalog_from_database(catalog)
    insert_catalog(catalog, path / "barnard.desc")
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

    # Create shared ObjectFinder to avoid recreating for each object
    from .catalog_import_utils import ObjectFinder

    shared_finder = ObjectFinder()
    NewCatalogObject.set_shared_finder(shared_finder)

    try:
        # build catalog
        with open(data, "r") as df:
            for row in tqdm(list(df), leave=False):
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
                logger.debug(f"<------------- Barnard {sequence=} ------------->")
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
    finally:
        NewCatalogObject.clear_shared_finder()

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

    # Create shared ObjectFinder to avoid recreating for each object
    from .catalog_import_utils import ObjectFinder

    shared_finder = ObjectFinder()
    NewCatalogObject.set_shared_finder(shared_finder)

    try:
        for record in tqdm(records, leave=False):
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
            desc = f"{form[record['Form']]}, {struct[record['Struct']]}, {bright[record['Bright']]}, {record['Stars']}\n"

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
    finally:
        NewCatalogObject.clear_shared_finder()

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
    conn, _ = objects_db.get_conn_cursor()

    # Create shared ObjectFinder to avoid recreating for each object
    from .catalog_import_utils import ObjectFinder

    shared_finder = ObjectFinder()
    NewCatalogObject.set_shared_finder(shared_finder)

    try:
        for row in tqdm(arp_cur.fetchall()):
            if last_id != row["catalog_identifier"]:
                # Save the previous object and start a new one
                if new_object is not None:
                    new_object.aka_names = aka_names
                    new_object.insert()

                last_id = row["catalog_identifier"]
                aka_names = [row["name"]]  # Start with the first name
                mag = row["magnitude"]
                if utils.is_number(mag):
                    mag = MagnitudeObject([float(mag)])
                else:
                    logging.warning(
                        f"Invalid magnitude for Arp {row['catalog_identifier']}"
                    )
                    mag = MagnitudeObject([])
                new_object = NewCatalogObject(
                    object_type="Gx",
                    catalog_code="Arp",
                    sequence=row["catalog_identifier"],
                    ra=row["ra"],
                    dec=row["dec"],
                    mag=mag,
                    description=arp_comments.get(row["catalog_identifier"], ""),
                )
            else:
                # Collect additional names for the same object
                aka_names.append(row["name"])

        # Don't forget to save the last object
        if new_object is not None:
            new_object.aka_names = aka_names
            new_object.insert()
    finally:
        NewCatalogObject.clear_shared_finder()

    insert_catalog_max_sequence(catalog)
    conn.commit()
    arp_conn.close()


def load_tlk_90_vars():
    logging.info("Loading TLK 90 Vars")
    catalog = "TLK"
    obj_type = "* "
    conn, _ = objects_db.get_conn_cursor()
    path = Path(utils.astro_data_dir, "variables/TLK_90_vars")
    delete_catalog_from_database(catalog)
    insert_catalog(catalog, path / "v90.desc")
    data = path / "v90.csv"

    # Create shared ObjectFinder to avoid recreating for each object
    from .catalog_import_utils import ObjectFinder

    shared_finder = ObjectFinder()
    NewCatalogObject.set_shared_finder(shared_finder)

    try:
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
    finally:
        NewCatalogObject.clear_shared_finder()

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

    # Create shared ObjectFinder to avoid recreating for each object
    from .catalog_import_utils import ObjectFinder

    shared_finder = ObjectFinder()
    NewCatalogObject.set_shared_finder(shared_finder)

    try:
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
    finally:
        NewCatalogObject.clear_shared_finder()

    insert_catalog_max_sequence(catalog)
    conn.commit()
