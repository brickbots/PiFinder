"""
This module holds various utils
and importers used during setup

"""
import sqlite3
from PiFinder.obj_types import OBJ_DESCRIPTORS
from pathlib import Path
import PiFinder.utils as utils
import csv


def create_logging_tables():
    """
    Creates the base logging tables
    """

    db_path = Path(utils.home_dir, "observations.db")
    if db_path.exists():
        return db_path

    # open the DB
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    db_c = conn.cursor()

    # initialize tables
    db_c.execute(
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

    db_c.execute(
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
    return db_path


# TODO not used atm + do we really want to auto-expand the ngc descriptions?
def decode_description(description):
    """
    decodes comma seperated descriptors
    """
    result = []
    codes = description.split(",")
    for code in codes:
        code = code.strip()
        decode = OBJ_DESCRIPTORS.get(code, code)
        if decode == code:
            sub_result = []
            # try splitting on spaces..
            for sub_code in code.split(" "):
                decode = OBJ_DESCRIPTORS.get(sub_code, sub_code)
                sub_result.append(decode)

            decode = " ".join(sub_result)

        result.append(decode)

    return ", ".join(result)


def init_catalog_tables():
    """
    Creates blank catalog tables

    """
    db_path = Path(utils.astro_data_dir, "pifinder_objects.db")

    # open the DB
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    db_c = conn.cursor()

    # initialize tables
    db_c.execute("drop table if exists objects")
    db_c.execute(
        """
           CREATE TABLE objects(
                catalog TEXT,
                sequence INTEGER,
                obj_type TEXT,
                ra NUMERIC,
                dec NUMERIC,
                const TEXT,
                l_size TEXT,
                size NUMERIC,
                mag NUMERIC,
                desc TEXT
           )
        """
    )

    db_c.execute("drop table if exists names")
    db_c.execute(
        """
           CREATE TABLE names(
                common_name TEXT,
                catalog TEXT,
                sequence INTEGER,
                comment TEXT
           )
        """
    )


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


def get_database(db_path):
    if not db_path.exists():
        print("DB does not exists")
        return False

    # open the DB
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    db_c = conn.cursor()
    return conn, db_c


def get_pifinder_database():
    return get_database(Path(utils.astro_data_dir, "pifinder_objects.db"))


def delete_catalog_from_database(db_c, catalog):
    db_c.execute(f"delete from objects where catalog='{catalog}'")
    db_c.execute(f"delete from names where catalog='{catalog}'")


def count_rows_per_distinct_column(conn, db_c, table, column):
    db_c.execute(f"SELECT {column}, COUNT(*) FROM {table} GROUP BY {column}")
    result = db_c.fetchall()
    for row in result:
        print(f"{row[0]}: {row[1]} entries")
    conn.close()


def count_empty_entries(conn, db_c, table, columns):
    db_c = conn.cursor()
    for column in columns:
        db_c.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {column} IS NULL OR {column} = ''"
        )
        result = db_c.fetchone()
        print(f"{column}: {result[0]} empty entries")
    conn.close()


def count_common_names_per_catalog():
    conn, db_c = get_pifinder_database()
    count_rows_per_distinct_column(conn, db_c, "names", "catalog")


def count_empty_entries_in_tables():
    conn, db_c = get_pifinder_database()
    count_empty_entries(
        conn, db_c, "names", ["common_name", "catalog", "sequence", "comment"]
    )
    conn, db_c = get_pifinder_database()
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


def print_database(conn, db_c):
    conn, db_c = get_pifinder_database()
    print(">-------------------------------------------------------")
    count_common_names_per_catalog()
    count_empty_entries_in_tables()
    print("<-------------------------------------------------------")


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
    conn, db_c = get_pifinder_database()
    delete_catalog_from_database(db_c, catalog)
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


def load_sac_asterisms():
    catalog = "SaA"
    conn, db_c = get_pifinder_database()
    delete_catalog_from_database(db_c, catalog)

    saca = Path(utils.astro_data_dir, "SAC_Asterisms_Ver32_Fence.txt")
    sequence = 0
    print("Loading SAC Asterisms")
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


def load_taas200():
    conn, db_c = get_pifinder_database()
    data = Path(utils.astro_data_dir, "TAAS_200.csv")
    sequence = 0
    catalog = "Ta2"
    delete_catalog_from_database(db_c, catalog)
    print("Loading Taas 200")

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


def insert_names(db_c, catalog, sequence, name):
    if name == "":
        return
    nameq = f"""
            insert into names(common_name, catalog, sequence)
            values ("{name}", "{catalog}", {sequence})
        """
    db_c.execute(nameq)


def load_caldwell():
    db_path = Path(utils.astro_data_dir, "pifinder_objects.db")
    if not db_path.exists():
        print("DB does not exists")
        return False

    # open the DB
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    db_c = conn.cursor()

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
                    "C",
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


def load_ngc_catalog():
    """
    checks for presense of sqllite db
    If found, exits
    if not, tries to load ngc2000 data from
    ../../astro_data/ngc2000
    """
    db_path = Path(utils.astro_data_dir, "pifinder_objects.db")
    if not db_path.exists():
        print("DB does not exists")
        return False

    # open the DB
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    db_c = conn.cursor()

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


if __name__ == "__main__":
    print("Starting")
    # execute all functions
    print("Creating DB")
    create_logging_tables()
    print("creating catalog tables")
    init_catalog_tables()
    print("loading catalogs")
    load_collinder()
    load_taas200()
    load_sac_asterisms()
    load_caldwell()
    load_ngc_catalog()
    conn, db_c = get_pifinder_database()
    print_database(conn, db_c)
