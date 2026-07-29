#!/usr/bin/python
# -*- coding:utf-8 -*-
# mypy: ignore-errors
"""
This script runs to fetch
images from AWS
"""

import sqlite3

import requests
from tqdm import tqdm

from PiFinder.object_images.poss_provider import POSSImageProvider


def get_catalog_objects():
    conn = sqlite3.connect(
        "/Users/rich/Projects/Astronomy/PiFinder/astro_data/pifinder_objects.db"
    )
    conn.row_factory = sqlite3.Row
    cat_objects = conn.execute(
        """
        SELECT * from objects
        order by catalog desc ,sequence
    """
    ).fetchall()
    return cat_objects


def check_object_image(catalog_object):
    """
    Check if image exists
    or fetch it.

    Returns image path
    """
    if catalog_object["catalog"] not in ["NGC", "IC"]:
        # look for any NGC aka
        conn = sqlite3.connect(
            "/Users/rich/Projects/Astronomy/PiFinder/astro_data/pifinder_objects.db"
        )
        conn.row_factory = sqlite3.Row

        aka_rec = conn.execute(
            f"""
            SELECT common_name from names
            where catalog = "{catalog_object["catalog"]}"
            and sequence = "{catalog_object["sequence"]}"
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

    object_image_path = POSSImageProvider()._resolve_image_name(catalog_object, "POSS")
    # POSS
    image_name = object_image_path.split("/")[-1]
    seq_ones = image_name.split("_")[0][-1]
    s3_url = (
        f"https://ddbeeedxfpnp0.cloudfront.net/catalog_images/{seq_ones}/{image_name}"
    )
    r = requests.head(s3_url)
    if r.status_code == 200:
        return True
    elif r.status_code == 403:
        return False
    else:
        print(s3_url, r.status_code)
        return False


def main():
    all_objects = get_catalog_objects()
    print("Checking for missing images")
    print(f"Checking {len(all_objects)} images....")
    for catalog_object in tqdm(all_objects):
        if not check_object_image(catalog_object):
            print(
                "Missing: "
                + catalog_object["catalog"]
                + str(catalog_object["sequence"])
            )


if __name__ == "__main__":
    main()
