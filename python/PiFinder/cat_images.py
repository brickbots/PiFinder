#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module holds various utils
and importers used during setup

"""
import requests
import sqlite3
import os
from PIL import Image, ImageOps, ImageDraw, ImageFont
from PiFinder import image_util

BASE_IMAGE_PATH = "/home/pifinder/PiFinder_data/catalog_images"


def get_display_image(catalog_object, source, fov):
    """
    Returns a 128x128 image buffer for
    the catalog object/source
    Resizing/cropping as needed to achieve FOV
    in degrees
        fov: 1-.125
    """
    font_base = ImageFont.truetype(
        "/home/pifinder/PiFinder/fonts/RobotoMono-Regular.ttf", 10
    )
    font_large = ImageFont.truetype(
        "/home/pifinder/PiFinder/fonts/RobotoMono-Regular.ttf", 15
    )

    object_image_path = resolve_image_name(catalog_object, source)
    if not os.path.exists(object_image_path):
        if catalog_object["catalog"] != "NGC":
            # look for any NGC aka
            conn = sqlite3.connect(
                "/home/pifinder/PiFinder/astro_data/pifinder_objects.db"
            )
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
                    return get_display_image(
                        {"catalog": "NGC", "sequence": aka_sequence}, source, fov
                    )
        return_image = Image.new("RGB", (128, 128))
        ri_draw = ImageDraw.Draw(return_image)
        ri_draw.text((30, 50), "No Image", font=font_large, fill=(0, 0, 128))
    else:
        return_image = Image.open(object_image_path)

        # FOV
        fov_size = int(1024 * fov / 2)
        return_image = return_image.crop(
            (
                512 - fov_size,
                512 - fov_size,
                512 + fov_size,
                512 + fov_size,
            )
        )
        return_image = return_image.resize((128, 128), Image.LANCZOS)

        # RED
        return_image = return_image.convert("RGB")
        return_image = image_util.make_red(return_image)
        ri_draw = ImageDraw.Draw(return_image)

    # Burn In
    ri_draw.rectangle([0, 108, 30, 128], fill=(0, 0, 0))
    ri_draw.text((1, 110), source, font=font_base, fill=(0, 0, 128))

    ri_draw.rectangle([98, 108, 128, 128], fill=(0, 0, 0))
    ri_draw.text((100, 110), f"{fov:0.2f}", font=font_base, fill=(0, 0, 128))

    return return_image


def resolve_image_name(catalog_object, source):
    """
    returns the image path for this objects
    """
    return f"{BASE_IMAGE_PATH}/{str(catalog_object['sequence'])[-1]}/{catalog_object['catalog']}{catalog_object['sequence']}_{source}.png"


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
    print(f"Fetching image for {catalog_object['catalog']}{catalog_object['sequence']}")
    ra = catalog_object["RA"]
    dec = catalog_object["Dec"]

    object_image_path = resolve_image_name(catalog_object, "POSS")
    if not os.path.exists(object_image_path):
        # POSS
        # this url has less contrast and requires a low-cut on the autoconstrast
        fetch_url = f"https://skyview.gsfc.nasa.gov/current/cgi/runquery.pl?Survey=digitized+sky+survey&position={ra},{dec}&Return=JPEG&size=1&pixels=1024"

        # this url produces nicer (but larger image size) results, but is sloooow
        # should not have low_cut
        # fetch_url = f"https://archive.stsci.edu/cgi-bin/dss_search?v=poss2ukstu_red&r={ra}&d={dec}&e=J2000&H=60&w=60&f=gif&c=none&fov=NONE&v3="
        fetched_image = Image.open(requests.get(fetch_url, stream=True).raw)
        fetched_image = fetched_image.convert("L")
        # fetched_image = fetched_image.resize((512,512), Image.LANCZOS)
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

    return True


def fetch_catalog(catalog):
    conn = sqlite3.connect("/home/pifinder/PiFinder/astro_data/pifinder_objects.db")
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
