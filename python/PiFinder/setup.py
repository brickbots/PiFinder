#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module holds various utils
and importers used during setup

"""
import sqlite3
import os
from PiFinder.obj_types import OBJ_DESCRIPTORS
from pprint import pprint


def create_logging_tables():
    """
    Creates the base logging tables
    """

    root_dir = os.path.realpath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..")
    )
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
                designation INTEGER,
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


def load_ngc_catalog():
    """
    checks for presense of sqllite db
    If found, exits
    if not, tries to load ngc2000 data from
    ../../astro_data/ngc2000
    """
    root_dir = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))
    db_path = os.path.join(root_dir, "astro_data", "pifinder_objects.db")
    if os.path.exists(db_path):
        print("DB Exists")
        return False

    # open the DB
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    db_c = conn.cursor()

    # initialize tables
    db_c.execute(
        """
           CREATE TABLE objects(
                catalog TEXT,
                designation INTEGER,
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

    db_c.execute(
        """
           CREATE TABLE names(
                common_name TEXT,
                catalog TEXT,
                designation INTEGER,
                comment TEXT
           )
        """
    )

    # Track M objects to avoid double adding some with
    # multiple NGC designations
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
                if catalog == " ":
                    catalog = "N"
                designation = int(l[1:5])
                if catalog == "M":
                    if designation not in m_objects:
                        m_objects.append(designation)
                    else:
                        add = False
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
                                {designation},
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
                    m_designation = int(common_name[2:].strip())
                    if m_designation not in m_objects:
                        catalog = l[36:37]
                        if catalog == " ":
                            catalog = "N"
                        designation = l[37:41].strip()

                        q = f"""
                            SELECT * from objects
                            where catalog="{catalog}"
                            and designation="{designation}"
                        """
                        tmp_row = conn.execute(q).fetchone()
                        if tmp_row:
                            m_objects.append(m_designation)
                            q = f"""
                                INSERT INTO objects
                                VALUES(
                                    "M",
                                    {m_designation},
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
                designation = l[37:41].strip()
                comment = l[42:]

                if designation != "":
                    q = f"""
                            INSERT INTO names
                            values(
                                "{common_name}",
                                "{catalog}",
                                {designation},
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
            designation = ls[0][1:]

            if designation != "":
                q = f"""
                        INSERT INTO names
                        values(
                            "{common_name}",
                            "{catalog}",
                            {designation},
                            "{comment.replace('"','""')}"
                        )
                    """

                db_c.execute(q)
        conn.commit()
