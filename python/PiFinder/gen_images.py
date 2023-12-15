#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module fetchs images from sky survey sources on the internet
and prepares them for PiFinder use.
"""
import requests
import sqlite3
import os
from tqdm import tqdm
from PIL import Image, ImageOps, ImageDraw, ImageFont
from PiFinder import image_util, cat_images
from PiFinder.db.objects_db import ObjectsDatabase
from PiFinder.catalogs import CompositeObject

BASE_IMAGE_PATH = "/Users/rich/Projects/Astronomy/PiFinder/astro_data/catalog_images"

CATALOG_PATH = "/Users/rich/Projects/Astronomy/PiFinder/astro_data/pifinder_objects.db"


def resolve_image_name(catalog_object, source):
    """
    returns the image path for this objects
    """
    return f"{BASE_IMAGE_PATH}/{str(catalog_object.image_name)[-1]}/{catalog_object.image_name}_{source}.jpg"


def check_image(image):
    """
    Checks for defects....
    """
    # out of range message
    blank = True
    for y in range(0, 24):
        if image.getpixel((0, y + 50)) > 0:
            blank = False
            break
    if blank:
        print("\tSDSS Out of range")
        return False

    black_pixel_count = 0
    for pixel in image.getdata():
        if pixel == 0:
            black_pixel_count += 1
            if black_pixel_count > 120000:
                print("\tToo many black pixels")
                return False

    return True


def fetch_object_image(_obj, low_cut=10):
    """
    Check if image exists
    or fetch it.

    Returns image path
    """
    catalog_object = CompositeObject.from_dict(dict(_obj))
    ra = catalog_object.ra
    dec = catalog_object.dec

    object_image_path = resolve_image_name(catalog_object, "POSS")
    if not os.path.exists(object_image_path):
        print(f"Fetching {object_image_path}")
        # POSS
        # this url has less contrast and requires a low-cut on the autoconstrast
        fetch_url = f"https://skyview.gsfc.nasa.gov/current/cgi/runquery.pl?Survey=digitized+sky+survey&position={ra},{dec}&Return=JPEG&size=1&pixels=1024"

        fetched_image = Image.open(requests.get(fetch_url, stream=True).raw)
        fetched_image = fetched_image.convert("L")
        fetched_image = ImageOps.autocontrast(fetched_image, cutoff=(low_cut, 0))
        fetched_image.save(object_image_path)
        print("\tPOSS Good!")

        # SDSS DR18
        object_image_path = resolve_image_name(catalog_object, "SDSS")
        fetch_url = f"https://skyserver.sdss.org/dr18/SkyServerWS/ImgCutout/getjpeg?ra={ra}&dec={dec}&scale=3.515&width=1024&height=1024&opt="
        fetched_image = Image.open(requests.get(fetch_url, stream=True).raw)
        fetched_image = fetched_image.convert("L")

        # check to see if it's black (i.e. out of SDSS coverage area)
        if check_image(fetched_image):
            print("\tSDSS Good!")
            fetched_image = ImageOps.autocontrast(fetched_image)
            fetched_image.save(object_image_path)
        else:
            print("\tSDSS BAD!")
            return False

    return True


def create_catalog_image_dirs():
    """
    Checks for and creates catalog_image dirs
    """
    if not os.path.exists(BASE_IMAGE_PATH):
        os.makedirs(BASE_IMAGE_PATH)

    for i in range(0, 10):
        _image_dir = f"{BASE_IMAGE_PATH}/{i}"
        if not os.path.exists(_image_dir):
            os.makedirs(_image_dir)


def main():
    objects_db = ObjectsDatabase()
    create_catalog_image_dirs()
    all_objects = objects_db.get_objects()
    for catalog_object in tqdm(all_objects):
        fetch_object_image(catalog_object)


if __name__ == "__main__":
    main()
