#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This script runs to fetch
images from AWS
"""
import requests, os
import sqlite3

from PiFinder import cat_images


def get_catalog_objects():
    conn = sqlite3.connect(cat_images.CATALOG_PATH)
    conn.row_factory = sqlite3.Row
    db_c = conn.cursor()
    cat_objects = conn.execute(
        f"""
        SELECT * from objects
        order by catalog desc ,sequence
    """
    ).fetchall()
    return cat_objects


def fetch_object_image(catalog_object):
    """
    Check if image exists
    or fetch it.

    Returns image path
    """
    if catalog_object["catalog"] not in ["NGC", "IC"]:
        # look for any NGC aka
        conn = sqlite3.connect(cat_images.CATALOG_PATH)
        conn.row_factory = sqlite3.Row
        db_c = conn.cursor()

        aka_rec = conn.execute(
            f"""
            SELECT common_name from names
            where catalog = "{catalog_object['catalog']}"
            and sequence = "{catalog_object['sequence']}"
            and common_name like "NGC%"
        """
        ).fetchone()
        if aka_rec:
            try:
                aka_sequence = int(aka_rec["common_name"][3:].strip())
            except ValueError:
                aka_sequence = None
                pass

            if aka_sequence:
                catalog_object = {"catalog": "NGC", "sequence": aka_sequence}

    object_image_path = cat_images.resolve_image_name(catalog_object, "POSS")
    if not os.path.exists(object_image_path):
        # POSS
        image_name = object_image_path.split("/")[-1]
        seq_ones = image_name.split("_")[0][-1]
        s3_url = f"https://ddbeeedxfpnp0.cloudfront.net/catalog_images/{seq_ones}/{image_name}"
        r = requests.get(s3_url)
        if r.status_code == 200:
            with open(object_image_path, "wb") as f:
                f.write(r.content)
        elif r.status_code == 403:
            print("\tNot available")
            return False
        else:
            print(s3_url, r.status_code)
            return False

        object_image_path = cat_images.resolve_image_name(catalog_object, "SDSS")
        image_name = object_image_path.split("/")[-1]
        seq_ones = image_name.split("_")[0][-1]
        s3_url = f"https://ddbeeedxfpnp0.cloudfront.net/catalog_images/{seq_ones}/{image_name}"
        r = requests.get(s3_url)
        if r.status_code == 200:
            with open(object_image_path, "wb") as f:
                f.write(r.content)
        elif r.status_code == 403:
            return False
            pass
        else:
            print(s3_url, r.status_code)
            return False
    else:
        print("\tAleady fetched")
        return True

    print("\tDone!")
    return True


def main():
    cat_images.create_catalog_image_dirs()
    all_objects = get_catalog_objects()
    all_objects_count = len(all_objects)
    i = 0
    for catalog_object in all_objects:
        i += 1
        print(
            f"{i: >5}/{all_objects_count} - {i/all_objects_count*100.0:2.2f}% -  {catalog_object['catalog']}{catalog_object['sequence']}"
        )
        fetch_object_image(catalog_object)


if __name__ == "__main__":
    main()
