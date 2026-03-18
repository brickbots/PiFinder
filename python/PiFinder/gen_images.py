#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Fetch images from sky survey sources (NASA SkyView POSS, SDSS DR18)
and prepare them for PiFinder use.

Usage:
    python -m PiFinder.gen_images                  # Fetch missing images
    python -m PiFinder.gen_images --force           # Re-fetch ALL images
    python -m PiFinder.gen_images --force --poss    # Re-fetch POSS only
    python -m PiFinder.gen_images --force --sdss    # Re-fetch SDSS only
    python -m PiFinder.gen_images --workers 20      # More concurrency
"""

import argparse
import os
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from typing import Dict, List, Tuple

import requests
from PIL import Image, ImageOps
from tqdm import tqdm

from PiFinder import utils

BASE_IMAGE_PATH = f"{utils.data_dir}/catalog_images"

# Catalogs that are excluded from image fetching (no meaningful survey images)
EXCLUDED_CATALOGS = {"WDS"}

SKYVIEW_URL = (
    "https://skyview.gsfc.nasa.gov/current/cgi/runquery.pl"
    "?Survey=digitized+sky+survey&position={ra},{dec}"
    "&Return=JPEG&size=1&pixels=1024"
)

SDSS_URL = (
    "https://skyserver.sdss.org/dr18/SkyServerWS/ImgCutout/getjpeg"
    "?ra={ra}&dec={dec}&scale=3.515&width=1024&height=1024&opt="
)


def resolve_image_path(image_name: str, source: str) -> str:
    last_char = str(image_name)[-1]
    return f"{BASE_IMAGE_PATH}/{last_char}/{image_name}_{source}.jpg"


def check_sdss_image(image: Image.Image) -> bool:
    """Check SDSS image for defects (blank/out-of-range)."""
    blank = True
    for y in range(0, 24):
        if image.getpixel((0, y + 50)) > 0:
            blank = False
            break
    if blank:
        return False

    black_pixel_count = 0
    for pixel in image.getdata():
        if pixel == 0:
            black_pixel_count += 1
            if black_pixel_count > 120000:
                return False
    return True


def fetch_poss(
    session: requests.Session, ra: float, dec: float, image_name: str, low_cut: int = 10
) -> Tuple[bool, str]:
    """Fetch POSS image from NASA SkyView."""
    path = resolve_image_path(image_name, "POSS")
    url = SKYVIEW_URL.format(ra=ra, dec=dec)
    try:
        resp = session.get(url, timeout=60)
        if resp.status_code != 200:
            return False, f"HTTP {resp.status_code}"
        img = Image.open(BytesIO(resp.content))
        img = img.convert("L")
        img = ImageOps.autocontrast(img, cutoff=(low_cut, 0))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        img.save(path)
        return True, ""
    except Exception as e:
        return False, str(e)


def fetch_sdss(
    session: requests.Session, ra: float, dec: float, image_name: str
) -> Tuple[bool, str]:
    """Fetch SDSS DR18 image."""
    path = resolve_image_path(image_name, "SDSS")
    url = SDSS_URL.format(ra=ra, dec=dec)
    try:
        resp = session.get(url, timeout=60)
        if resp.status_code != 200:
            return False, f"HTTP {resp.status_code}"
        img = Image.open(BytesIO(resp.content))
        img = img.convert("L")
        if not check_sdss_image(img):
            return False, "out of range"
        img = ImageOps.autocontrast(img)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        img.save(path)
        return True, ""
    except Exception as e:
        return False, str(e)


def fetch_object(
    session: requests.Session,
    ra: float,
    dec: float,
    image_name: str,
    do_poss: bool,
    do_sdss: bool,
    force: bool,
) -> Tuple[str, Dict[str, Tuple[bool, str]]]:
    """Fetch survey images for one object."""
    results: Dict[str, Tuple[bool, str]] = {}

    if do_poss:
        path = resolve_image_path(image_name, "POSS")
        if force or not os.path.exists(path):
            results["POSS"] = fetch_poss(session, ra, dec, image_name)
        else:
            results["POSS"] = (True, "exists")

    if do_sdss:
        path = resolve_image_path(image_name, "SDSS")
        if force or not os.path.exists(path):
            results["SDSS"] = fetch_sdss(session, ra, dec, image_name)
        else:
            results["SDSS"] = (True, "exists")

    return image_name, results


def get_objects_to_fetch() -> List[Tuple[float, float, str]]:
    """Get all non-WDS objects with their coordinates and image names."""
    db_path = utils.pifinder_db
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    excluded_placeholders = ",".join("?" for _ in EXCLUDED_CATALOGS)
    cursor.execute(
        f"""
        SELECT DISTINCT o.ra, o.dec, oi.image_name
        FROM objects o
        JOIN object_images oi ON oi.object_id = o.id
        JOIN catalog_objects co ON co.object_id = o.id
        WHERE co.catalog_code NOT IN ({excluded_placeholders})
          AND oi.image_name != ''
        """,
        list(EXCLUDED_CATALOGS),
    )
    rows = [(r["ra"], r["dec"], r["image_name"]) for r in cursor.fetchall()]
    conn.close()
    return rows


def create_catalog_image_dirs():
    if not os.path.exists(BASE_IMAGE_PATH):
        os.makedirs(BASE_IMAGE_PATH)
    for i in range(0, 10):
        d = f"{BASE_IMAGE_PATH}/{i}"
        if not os.path.exists(d):
            os.makedirs(d)


def main():
    parser = argparse.ArgumentParser(
        description="Fetch survey images for PiFinder objects"
    )
    parser.add_argument(
        "--force", action="store_true", help="Re-fetch even if image exists"
    )
    parser.add_argument("--poss", action="store_true", help="Fetch POSS only")
    parser.add_argument("--sdss", action="store_true", help="Fetch SDSS only")
    parser.add_argument(
        "--workers", type=int, default=10, help="Concurrent workers (default: 10)"
    )
    args = parser.parse_args()

    do_poss = True
    do_sdss = True
    if args.poss and not args.sdss:
        do_sdss = False
    elif args.sdss and not args.poss:
        do_poss = False

    create_catalog_image_dirs()

    print("Querying objects from database...")
    objects = get_objects_to_fetch()
    print(f"Found {len(objects)} objects (excluding {', '.join(EXCLUDED_CATALOGS)})")

    if args.force:
        to_fetch = objects
        print(f"Force mode: will re-fetch all {len(to_fetch)} objects")
    else:
        to_fetch = []
        for ra, dec, name in objects:
            poss_missing = do_poss and not os.path.exists(
                resolve_image_path(name, "POSS")
            )
            sdss_missing = do_sdss and not os.path.exists(
                resolve_image_path(name, "SDSS")
            )
            if poss_missing or sdss_missing:
                to_fetch.append((ra, dec, name))
        print(f"Missing images: {len(to_fetch)} of {len(objects)}")

    if not to_fetch:
        print("Nothing to fetch!")
        return

    sources = []
    if do_poss:
        sources.append("POSS")
    if do_sdss:
        sources.append("SDSS")
    print(f"Fetching: {', '.join(sources)} with {args.workers} workers")

    session = requests.Session()
    session.headers.update({"User-Agent": "PiFinder-ImageGenerator/2.0"})

    failed: List[Tuple[str, str]] = []
    fetched = 0
    skipped = 0
    t_start = time.time()

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                fetch_object, session, ra, dec, name, do_poss, do_sdss, args.force
            ): name
            for ra, dec, name in to_fetch
        }

        for future in tqdm(
            as_completed(futures), total=len(futures), desc="Downloading"
        ):
            name = futures[future]
            try:
                _, results = future.result()
                for source, (ok, err) in results.items():
                    if err == "exists":
                        skipped += 1
                    elif ok:
                        fetched += 1
                    else:
                        failed.append((f"{name}_{source}", err))
            except Exception as e:
                failed.append((name, str(e)))

    elapsed = time.time() - t_start
    print(
        f"\nDone in {elapsed:.0f}s: {fetched} fetched, {skipped} skipped, {len(failed)} failed"
    )

    if failed:
        print(f"\nFailed ({len(failed)}):")
        for name, err in failed[:20]:
            print(f"  {name}: {err}")
        if len(failed) > 20:
            print(f"  ... and {len(failed) - 20} more")

    session.close()


if __name__ == "__main__":
    main()
