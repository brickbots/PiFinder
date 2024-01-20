#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This script runs to fetch
images from AWS
"""
import requests, os
import sqlite3
from tqdm import tqdm

from PiFinder import cat_images
from PiFinder.db.objects_db import ObjectsDatabase
from PiFinder.catalogs import CompositeObject


def check_catalog_objects(objects):
    """
    Checks through catalog objects
    to deterine which need to be
    fetched.

    Returns the list of just objects
    to fetch
    """
    return_list = []
    for _obj in tqdm(objects):
        catalog_object = CompositeObject.from_dict(dict(_obj))
        object_image_path = cat_images.resolve_image_name(catalog_object, "POSS")
        if not os.path.exists(object_image_path):
            return_list.append(catalog_object)

    return return_list


def fetch_object_image(catalog_object):
    """
    Check if image exists
    or fetch it.

    Returns image path
    """

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
            print(f"\t{image_name} Not available")
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
        return True

    return True


def main():
    cat_images.create_catalog_image_dirs()
    objects_db = ObjectsDatabase()
    print("Checking for missing images")
    objects_to_fetch = check_catalog_objects(objects_db.get_objects())
    if len(objects_to_fetch) > 0:
        print(f"Fetching {len(objects_to_fetch)} images....")
        for catalog_object in tqdm(objects_to_fetch):
            fetch_object_image(catalog_object)
        print("Done!")
    else:
        print("All images downloaded")


if __name__ == "__main__":
    main()
