#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is used at runtime
to handle catalog image loading
"""
import requests
import sqlite3
import os
from PIL import Image, ImageOps, ImageDraw, ImageFont
from PiFinder import image_util, cat_images

BASE_IMAGE_PATH = "/Users/rich/Projects/Astronomy/PiFinder/astro_data/catalog_images"

CATALOG_PATH = "/Users/rich/Projects/Astronomy/PiFinder/astro_data/pifinder_objects.db"


def get_ngc_aka(catalog_object):
    """
    returns the NGC aka for this object
    if available
    """
    conn = sqlite3.connect(CATALOG_PATH)
    conn.row_factory = sqlite3.Row
    db_c = conn.cursor()

    aka_rec = conn.execute(
        f"""
        SELECT common_name from names
        where catalog = "{catalog_object.catalog_code}"
        and sequence = "{catalog_object.sequence}"
        and common_name like "NGC%"
    """
    ).fetchone()
    if not aka_rec:
        return None

    try:
        aka_sequence = int(aka_rec["common_name"][3:].strip())
    except ValueError:
        return None

    aka_rec = conn.execute(
        f"""
        SELECT *
        from objects
        where catalog = "NGC"
        and sequence = "{aka_sequence}"
    """
    ).fetchone()
    return aka_rec


def resolve_image_name(catalog_object, source):
    """
    returns the image path for this objects
    """
    return f"{BASE_IMAGE_PATH}/{str(catalog_object.sequence)[-1]}/{catalog_object.catalog_code}{catalog_object.sequence}_{source}.jpg"


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


def fetch_object_image(catalog_object, low_cut=10):
    """
    Check if image exists
    or fetch it.

    Returns image path
    """
    print(f"Fetching image for {catalog_object.catalog_code}{catalog_object.sequence}")
    ra = catalog_object["RA"]
    dec = catalog_object["Dec"]

    object_image_path = resolve_image_name(catalog_object, "POSS")
    if not os.path.exists(object_image_path):
        # look for any NGC aka
        aka_rec = get_ngc_aka(catalog_object)
        if aka_rec:
            return fetch_object_image(aka_rec, low_cut)
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


def fetch_catalog(catalog):
    conn = sqlite3.connect(CATALOG_PATH)
    conn.row_factory = sqlite3.Row
    db_c = conn.cursor()
    cat_objects = conn.execute(
        f"""
        SELECT * from objects
        where catalog='{catalog}'
        order by sequence
    """
    ).fetchall()
    return cat_objects


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


def get_catalog_images(catalog):
    create_catalog_image_dirs()
    cat = fetch_catalog(catalog)
    for catalog_object in cat:
        fetch_object_image(catalog_object)
