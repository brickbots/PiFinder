#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module holds various utils
and importers used during setup

"""
import sqlite3
import os


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
    db_c = conn.cursor()

    # initialize tables
    db_c.execute(
        """
           CREATE TABLE ngc(
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

    # load em up!
    # ngc2000.dat
    ngc_dat = os.path.join(root_dir, "astro_data", "ngc2000", "ngc2000.dat")
    with open(ngc_dat, "r") as ngc:
        for l in ngc:
            catalog = l[0:1]
            if catalog == " ":
                catalog = "N"
            designation = int(l[1:5])
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
            desc = l[46:]

            # convert ra/dec here....
            dec = ded + (dem / 60)
            if des == "-":
                dec = dec * -1
            ra = rah + (ram / 60) * 15

            q = f"""
                    INSERT INTO ngc
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

    name_dat = os.path.join(root_dir, "astro_data", "ngc2000", "names.dat")
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
