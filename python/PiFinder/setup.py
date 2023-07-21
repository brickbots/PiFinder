"""
This module holds various utils
and importers used during setup

"""
import csv
import argparse
import logging
import datetime
from pathlib import Path
from PiFinder.obj_types import OBJ_DESCRIPTORS
import PiFinder.utils as utils
from PiFinder.db.objects_db import ObjectsDatabase
from PiFinder.db.observations_db import ObservationsDatabase

objects_db: ObjectsDatabase
observations_db: ObservationsDatabase


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


def delete_catalog_from_database(db_c, catalog):
    db_c.execute(f"delete from objects where catalog='{catalog}'")
    db_c.execute(f"delete from names where catalog='{catalog}'")


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
    count_rows_per_distinct_column(conn, db_c, "names", "catalog")


def count_empty_entries_in_tables():
    conn, db_c = objects_db.get_conn_cursor()
    count_empty_entries(
        conn, db_c, "names", ["common_name", "catalog", "sequence", "comment"]
    )
    count_empty_entries(
        conn,
        db_c,
        "objects",
        [
            "catalog",
            "sequence",
            "obj_type",
            "ra",
            "dec",
            "const",
            "l_size",
            "size",
            "mag",
            "desc",
        ],
    )


def print_database():
    logging.info(">-------------------------------------------------------")
    count_common_names_per_catalog()
    count_empty_entries_in_tables()
    logging.info("<-------------------------------------------------------")


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
    objects_db.delete_catalog_by_code(catalog)
    coll = Path(utils.astro_data_dir, "collinder.txt")
    with open(coll, "r") as df:
        df.readline()
        for l in df:
            dfs = l.split("\t")
            sequence = dfs[0].split(" ")[0]
            other_names = dfs[1]
            if other_names.isnumeric():
                other_names = "NGC" + other_names

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

            q = f"""
                insert into objects(
                    catalog,
                    sequence,
                    ra,
                    dec,
                    const,
                    size,
                    desc
                )
                values (
                    "{catalog}",
                    {sequence},
                    {ra_deg},
                    {dec_deg},
                    "{const}",
                    "{size}",
                    "{desc}"
                )
            """
            db_c.execute(q)
            conn.commit()
    type_trans = {
        "Open cluster": "OC",
        "Asterism": "Ast",
        "Globular cluster": "Gb",
    }
    coll2 = Path(utils.astro_data_dir, "collinder2.txt")
    with open(coll2, "r") as df:
        df.readline()
        for l in df:
            dfs = l.split("\t")
            sequence = dfs[0].split(" ")[1]
            obj_type = type_trans.get(dfs[4], "OC")
            mag = dfs[6].strip().split(" ")[0]
            if mag == "-":
                mag = "null"
            other_names = dfs[2]

            q = f"""
                    UPDATE objects
                    set
                        obj_type = "{obj_type}",
                        mag = {mag}
                    where
                        catalog = "{catalog}"
                        and sequence = {sequence}
                """
            db_c.execute(q)
            if other_names != "":
                db_c.execute(
                    f"""
                        insert into names(common_name, catalog, sequence)
                        values ("{other_names}", "{catalog}", {sequence})
                    """
                )
    conn.commit()
    insert_catalog(catalog, Path(utils.astro_data_dir, "collinder.desc"))


def load_sac_asterisms():
    catalog = "SaA"
    conn, db_c = get_pifinder_database()
    delete_catalog_from_database(db_c, catalog)

    saca = Path(utils.astro_data_dir, "SAC_Asterisms_Ver32_Fence.txt")
    sequence = 0
    logging.info("Loading SAC Asterisms")
    delete_catalog_from_database(db_c, catalog)
    with open(saca, "r") as df:
        df.readline()
        for l in df:
            dfs = l.split("|")
            dfs = [d.strip() for d in dfs]
            other_names = dfs[1].strip()
            if other_names == "":
                continue
            else:
                sequence += 1

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
                mag = "null"

            q = f"""
                insert into objects(
                    catalog,
                    sequence,
                    obj_type,
                    ra,
                    dec,
                    const,
                    size,
                    mag,
                    desc
                )
                values (
                    "{catalog}",
                    {sequence},
                    "Ast",
                    {ra_deg},
                    {dec_deg},
                    "{const}",
                    "{size}",
                    "{mag}",
                    "{desc}"
                )
            """
            db_c.execute(q)
            db_c.execute(
                f"""
                    insert into names(common_name, catalog, sequence)
                    values ("{other_names}", "{catalog}", {sequence})
                """
            )

    conn.commit()
    insert_catalog(catalog, Path(utils.astro_data_dir, "sac.desc"))


def load_sac_multistars():
    catalog = "SaM"
    conn, db_c = get_pifinder_database()
    delete_catalog_from_database(db_c, catalog)

    saca = Path(utils.astro_data_dir, "SAC_Multistars_Ver40", "SAC_DBL40_Fence.txt")
    sequence = 0
    logging.info("Loading SAC Multistars")
    delete_catalog_from_database(db_c, catalog)
    with open(saca, "r") as df:
        df.readline()
        for l in df:
            dfs = l.split("|")
            dfs = [d.strip() for d in dfs]
            name = [dfs[2].strip()]
            other_names = dfs[6].strip().split(";")
            name.extend(other_names)
            name = [x for x in name if x != ""]
            print(name)
            other_names = ", ".join(name)
            if other_names == "":
                continue
            else:
                sequence += 1

            const = dfs[1].strip()
            ra = dfs[3].strip()
            dec = dfs[4].strip()
            components = dfs[5].strip()
            mag = dfs[7].strip()
            mag2 = dfs[8].strip()
            sep = dfs[9].strip()
            pa = dfs[10].strip()
            desc = dfs[11].strip()
            print(f"'{desc=}'")
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
                mag = "null"

            q = f"""
                insert into objects(
                    catalog,
                    sequence,
                    obj_type,
                    ra,
                    dec,
                    const,
                    size,
                    mag,
                    desc
                )
                values (
                    "{catalog}",
                    {sequence},
                    "D*",
                    {ra_deg},
                    {dec_deg},
                    "{const}",
                    '{sep}"',
                    "{mag}/{mag2}",
                    "{desc}"
                )
            """
            db_c.execute(q)
            db_c.execute(
                f"""
                    insert into names(common_name, catalog, sequence)
                    values ("{other_names}", "{catalog}", {sequence})
                """
            )

    conn.commit()
    insert_catalog(
        catalog, Path(utils.astro_data_dir, "SAC_Multistars_Ver40", "sacm.desc")
    )


def load_taas200():
    conn, db_c = get_pifinder_database()
    data = Path(utils.astro_data_dir, "TAAS_200.csv")
    sequence = 0
    catalog = "Ta2"
    delete_catalog_from_database(db_c, catalog)
    logging.info("Loading Taas 200")

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
            sequence = int(row["Nr"])
            ngc = row["NGC/IC"]
            other_catalog = []
            if ngc:
                if ngc.startswith("IC") or ngc.startswith("B") or ngc.startswith("Col"):
                    other_catalog.append(ngc)
                else:
                    split = ngc.split(";")
                    for s in split:
                        other_catalog.append(f"NGC {s}")

            other_names = row["Name"]
            const = row["Const"]
            type = typedict[row["Type"]]
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

            q = f"""
                insert into objects(
                    catalog,
                    sequence,
                    obj_type,
                    ra,
                    dec,
                    const,
                    size,
                    mag,
                    desc
                )
                values (
                    "{catalog}",
                    {sequence},
                    "{type}",
                    {ra},
                    {dec},
                    "{const}",
                    "{size}",
                    "{mag}",
                    "{desc}"
                )
            """
            db_c.execute(q)

            # insert the other names
            insert_names(db_c, catalog, sequence, other_names)
            for name in other_catalog:
                insert_names(db_c, catalog, sequence, name)

    conn.commit()
    insert_catalog("Ta2", Path(utils.astro_data_dir, "taas200.desc"))


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

    conn, db_c = get_pifinder_database()
    max_sequence = get_catalog_sizes(catalog_name)[catalog_name]

    catalogq = f"""
            insert into catalogs(catalog, max_sequence, desc)
            values ("{catalog_name}", "{max_sequence}", "{description}")
        """
    logging.info(catalogq)
    db_c.execute(catalogq)
    conn.commit()


def get_catalog_sizes(catalog_name):
    conn, db_c = get_pifinder_database()
    query = f"SELECT catalog, MAX(sequence) FROM objects where catalog = '{catalog_name}' GROUP BY catalog"
    db_c.execute(query)
    result = db_c.fetchall()
    return {row["catalog"]: row["MAX(sequence)"] for row in result}


def load_caldwell():
    catalog = "C"
    conn, db_c = objects_db.get_conn_cursor()
    delete_catalog_from_database(db_c, catalog)

    cal = Path(utils.astro_data_dir, "caldwell.dat")
    with open(cal, "r") as df:
        df.readline()
        for l in df:
            dfs = l.split("\t")
            sequence = dfs[0].strip()
            other_names = dfs[1]
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

            q = f"""
                insert into objects(
                    catalog,
                    sequence,
                    obj_type,
                    mag,
                    ra,
                    dec,
                    const,
                    size,
                    desc
                )
                values (
                    "{catalog}",
                    {sequence},
                    "{obj_type}",
                    {mag},
                    {ra_deg},
                    {dec_deg},
                    "{const}",
                    "{size}",
                    ""
                )
            """
            db_c.execute(q)
            if other_names != "":
                db_c.execute(
                    f"""
                        insert into names(common_name, catalog, sequence)
                        values ("{other_names}", "C", {sequence})
                    """
                )

    conn.commit()
    insert_catalog("C", Path(utils.astro_data_dir, "caldwell.desc"))


def load_ngc_catalog():
    """
    checks for presense of sqllite db
    If found, exits
    if not, tries to load ngc2000 data from
    ../../astro_data/ngc2000
    """
    conn, db_c = objects_db.get_conn_cursor()

    # Track M objects to avoid double adding some with
    # multiple NGC sequences
    m_objects = []
    # load em up!
    # ngc2000.dat + messier.dat
    ngc_dat_files = [
        Path(utils.astro_data_dir, "ngc2000", "ngc2000.dat"),
        Path(utils.astro_data_dir, "messier_objects.dat"),
    ]
    for ngc_dat in ngc_dat_files:
        with open(ngc_dat, "r") as ngc:
            for l in ngc:
                add = True
                catalog = l[0:1]
                if catalog == " " or catalog == "N":
                    catalog = "NGC"
                if catalog == "I":
                    catalog = "IC"
                if catalog == "M":
                    if sequence not in m_objects:
                        m_objects.append(sequence)
                    else:
                        add = False

                sequence = int(l[1:5])
                if add:
                    obj_type = l[6:9].strip()
                    rah = int(l[10:12])
                    ram = float(l[13:17])
                    des = l[19:20]
                    ded = int(l[20:22])
                    dem = int(l[23:25])
                    const = l[29:32]
                    l_size = l[32:33]
                    size = l[33:38]
                    mag = l[40:44]
                    # desc = decode_description(l[46:])
                    desc = l[46:]

                    # convert ra/dec here....
                    dec = ded + (dem / 60)
                    if des == "-":
                        dec = dec * -1
                    ra = (rah + (ram / 60)) * 15

                    q = f"""
                            INSERT INTO objects
                            VALUES(
                                "{catalog}",
                                {sequence},
                                "{obj_type}",
                                {ra},
                                {dec},
                                "{const}",
                                "{l_size}",
                                "{size}",
                                "{mag}",
                                "{desc.replace('"','""')}"
                            )
                        """
                    db_c.execute(q)
            conn.commit()

    # add records for M objects into objects....
    name_dat_files = [
        Path(utils.astro_data_dir, "ngc2000", "names.dat"),
        Path(utils.astro_data_dir, "extra_names.dat"),
    ]
    for name_dat in name_dat_files:
        with open(name_dat, "r") as names:
            for l in names:
                common_name = l[0:35]
                if common_name.startswith("M "):
                    m_sequence = int(common_name[2:].strip())
                    if m_sequence not in m_objects:
                        catalog = l[36:37]
                        if catalog == " " or catalog == "N":
                            catalog = "NGC"
                        if catalog == "I":
                            catalog = "IC"
                        sequence = l[37:41].strip()

                        q = f"""
                            SELECT * from objects
                            where catalog="{catalog}"
                            and sequence="{sequence}"
                        """
                        tmp_row = conn.execute(q).fetchone()
                        if tmp_row:
                            m_objects.append(m_sequence)
                            q = f"""
                                INSERT INTO objects
                                VALUES(
                                    "M",
                                    {m_sequence},
                                    "{tmp_row['obj_type']}",
                                    {tmp_row['ra']},
                                    {tmp_row['dec']},
                                    "{tmp_row['const']}",
                                    "{tmp_row['l_size']}",
                                    "{tmp_row['size']}",
                                    "{tmp_row['mag']}",
                                    "{tmp_row['desc'].replace('"','""')}"
                                )
                                """
                            db_c.execute(q)
            conn.commit()

        # Now add the names
        with open(name_dat, "r") as names:
            for l in names:
                common_name = l[0:35]
                if common_name.startswith("M "):
                    common_name = "M" + common_name[2:].strip()
                catalog = l[36:37]
                if catalog == " ":
                    catalog = "N"
                if catalog == "N":
                    catalog = "NGC"
                if catalog == "I":
                    catalog = "IC"

                sequence = l[37:41].strip()
                comment = l[42:]

                if sequence != "":
                    q = f"""
                            INSERT INTO names
                            values(
                                "{common_name}",
                                "{catalog}",
                                {sequence},
                                "{comment.replace('"','""')}"
                            )
                        """

                    db_c.execute(q)
            conn.commit()

    # Now add the messier names
    name_dat = Path(utils.astro_data_dir, "messier_names.dat")
    with open(name_dat, "r") as names:
        for i, l in enumerate(names):
            ls = l.split("\t")
            common_name = ls[1][:-1]
            catalog = "M"
            sequence = ls[0][1:]

            if sequence != "":
                q = f"""
                        INSERT INTO names
                        values(
                            "{common_name}",
                            "{catalog}",
                            {sequence},
                            "{comment.replace('"','""')}"
                        )
                    """

                db_c.execute(q)
        conn.commit()

    # insert catalog descriptions
    insert_catalog("NGC", Path(utils.astro_data_dir, "ngc2000", "ngc.desc"))
    insert_catalog("M", Path(utils.astro_data_dir, "messier.desc"))
    insert_catalog("IC", Path(utils.astro_data_dir, "ic.desc"))


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
    if not observations_db.exists():
        observations_db.create_tables()
    logging.info("loading catalogs")
    load_ngc_catalog()
    load_collinder()
    load_taas200()
    load_sac_asterisms()
    load_sac_multistars()
    load_caldwell()
    print_database()
