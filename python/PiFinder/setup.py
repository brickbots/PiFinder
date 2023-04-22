#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module holds various utils
and importers used during setup

"""
import sqlite3
import os
from PiFinder.obj_types import OBJ_DESCRIPTORS
from PiFinder import config
from pprint import pprint


def create_logging_tables():
    """
    Creates the base logging tables
    """

    root_dir = "/home/pifinder/PiFinder_data"
    db_path = os.path.join(root_dir, "observations.db")
    if os.path.exists(db_path):
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


def load_deepmap_600():
    """
    loads the deepmap 600 file to add
    better descriptions and flag items
    on the list
    """
    root_dir = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))
    data_path = os.path.join(root_dir, "astro_data", "deepmap_600.txt")
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


def init_catalog_tables():
    """
    Creates blank catalog tables

    """
    root_dir = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))
    db_path = os.path.join(root_dir, "astro_data", "pifinder_objects.db")

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


def load_collinder():
    root_dir = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))
    db_path = os.path.join(root_dir, "astro_data", "pifinder_objects.db")
    if not os.path.exists(db_path):
        print("DB does not exists")
        return False

    # open the DB
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    db_c = conn.cursor()

    coll = os.path.join(root_dir, "astro_data", "collinder.txt")
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
            ra_deg = ra_to_dec(ra_h, ra_m, ra_s)

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
                    "Col",
                    {sequence},
                    {ra_deg},
                    {dec_deg},
                    "{const}",
                    "{size}",
                    "{desc}"
                )
            """
            db_c.execute(q)
            if other_names != "":
                db_c.execute(
                    f"""
                        insert into names(common_name, catalog, sequence)
                        values ("{other_names}", "Col", {sequence})
                    """
                )

    conn.commit()
    type_trans = {
        "Open cluster": "OC",
        "Asterism": "Ast",
        "Globular cluster": "Gb",
    }
    coll2 = os.path.join(root_dir, "astro_data", "collinder2.txt")
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
                        catalog = "Col"
                        and sequence = {sequence}
                """
            db_c.execute(q)
            if other_names != "":
                db_c.execute(
                    f"""
                        insert into names(common_name, catalog, sequence)
                        values ("{other_names}", "Col", {sequence})
                    """
                )
    conn.commit()


def load_caldwell():
    root_dir = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))
    db_path = os.path.join(root_dir, "astro_data", "pifinder_objects.db")
    if not os.path.exists(db_path):
        print("DB does not exists")
        return False

    # open the DB
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    db_c = conn.cursor()

    cal = os.path.join(root_dir, "astro_data", "caldwell.dat")
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
            ra_deg = ra_to_dec(ra_h, ra_m, 0)

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
    root_dir = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))
    db_path = os.path.join(root_dir, "astro_data", "pifinder_objects.db")
    if not os.path.exists(db_path):
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
        os.path.join(root_dir, "astro_data", "ngc2000", "ngc2000.dat"),
        os.path.join(root_dir, "astro_data", "messier_objects.dat"),
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
        os.path.join(root_dir, "astro_data", "ngc2000", "names.dat"),
        os.path.join(root_dir, "astro_data", "extra_names.dat"),
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
    name_dat = os.path.join(root_dir, "astro_data", "messier_names.dat")
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
