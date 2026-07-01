#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
**Generate** object images (ADR 0018) — the dev-side, off-device step.

Fetches a cutout from a sky survey (NASA SkyView POSS, SDSS DR18) and writes one
**sourceless** image per object (``<digit>/<image_name>.jpg``) ready to publish
to the CDN.  Which survey to (re)generate from is read per object from
``object_images.source`` — the recorded curation directive — with ``NULL`` ("not
yet curated") falling back to POSS.  This is the *only* place an image source is
read or acted on; resolution, display and the on-device download never branch on
it.

Multi-source candidate staging and the discriminator (which would *write*
``source``) are out of v1 scope: this tool produces the single canonical image
for the recorded (or default) source.

Usage:
    python -m PiFinder.gen_images                  # fetch missing images
    python -m PiFinder.gen_images --force          # re-fetch ALL images
    python -m PiFinder.gen_images --workers 20     # more concurrency
"""

import argparse
import os
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from typing import List, Tuple, cast

import requests
from PIL import Image, ImageOps
from tqdm import tqdm

from PiFinder import object_image_store as store
from PiFinder import utils

# Default survey for an uncurated (NULL/empty) ``object_images.source``.
DEFAULT_SOURCE = "POSS"

SKYVIEW_URL = (
    "https://skyview.gsfc.nasa.gov/current/cgi/runquery.pl"
    "?Survey=digitized+sky+survey&position={ra},{dec}"
    "&Return=JPEG&size=1&pixels=1024"
)

SDSS_URL = (
    "https://skyserver.sdss.org/dr18/SkyServerWS/ImgCutout/getjpeg"
    "?ra={ra}&dec={dec}&scale=3.515&width=1024&height=1024&opt="
)


def survey_for(source) -> str:
    """Survey to (re)generate this object's image from.

    Reads the recorded curation directive; ``NULL``/empty/unknown falls back to
    the default (POSS).  See ADR 0018.
    """
    normalized = (source or "").strip().upper()
    return normalized if normalized in ("POSS", "SDSS") else DEFAULT_SOURCE


def check_sdss_image(image: Image.Image) -> bool:
    """Check SDSS image for defects (blank/out-of-range)."""
    blank = True
    for y in range(0, 24):
        if cast(int, image.getpixel((0, y + 50))) > 0:
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
    session: requests.Session, ra: float, dec: float, path: str, low_cut: int = 10
) -> Tuple[bool, str]:
    """Fetch a POSS image from NASA SkyView and save it (sourceless) to ``path``."""
    url = SKYVIEW_URL.format(ra=ra, dec=dec)
    try:
        resp = session.get(url, timeout=60)
        if resp.status_code != 200:
            return False, f"HTTP {resp.status_code}"
        img: Image.Image = Image.open(BytesIO(resp.content))
        img = img.convert("L")
        img = ImageOps.autocontrast(img, cutoff=(low_cut, 0))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        img.save(path)
        return True, ""
    except Exception as e:
        return False, str(e)


def fetch_sdss(
    session: requests.Session, ra: float, dec: float, path: str
) -> Tuple[bool, str]:
    """Fetch an SDSS DR18 image and save it (sourceless) to ``path``."""
    url = SDSS_URL.format(ra=ra, dec=dec)
    try:
        resp = session.get(url, timeout=60)
        if resp.status_code != 200:
            return False, f"HTTP {resp.status_code}"
        img: Image.Image = Image.open(BytesIO(resp.content))
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
    source,
    force: bool,
) -> Tuple[str, str, Tuple[bool, str]]:
    """Generate the one sourceless image for an object from its recorded source."""
    survey = survey_for(source)
    path = store.local_image_path(image_name)
    if not force and os.path.exists(path):
        return image_name, survey, (True, "exists")
    if survey == "SDSS":
        result = fetch_sdss(session, ra, dec, path)
    else:
        result = fetch_poss(session, ra, dec, path)
    return image_name, survey, result


def get_objects_to_fetch() -> List[Tuple[float, float, str, object]]:
    """All CDN-eligible objects with coordinates, image name and recorded source."""
    conn = sqlite3.connect(str(utils.pifinder_db))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    excluded = ",".join("?" for _ in store.EXCLUDED_CATALOGS)
    cursor.execute(
        f"""
        SELECT DISTINCT o.ra, o.dec, oi.image_name, oi.source
        FROM objects o
        JOIN object_images oi ON oi.object_id = o.id
        JOIN catalog_objects co ON co.object_id = o.id
        WHERE co.catalog_code NOT IN ({excluded})
          AND oi.image_name != ''
        """,
        list(store.EXCLUDED_CATALOGS),
    )
    rows = [
        (r["ra"], r["dec"], r["image_name"], r["source"]) for r in cursor.fetchall()
    ]
    conn.close()
    return rows


def main():
    parser = argparse.ArgumentParser(
        description="Generate (survey-fetch) sourceless PiFinder object images"
    )
    parser.add_argument(
        "--force", action="store_true", help="Re-fetch even if image exists"
    )
    parser.add_argument(
        "--workers", type=int, default=10, help="Concurrent workers (default: 10)"
    )
    args = parser.parse_args()

    store.create_catalog_image_dirs()

    print("Querying objects from database...")
    objects = get_objects_to_fetch()
    print(
        f"Found {len(objects)} objects "
        f"(excluding {', '.join(sorted(store.EXCLUDED_CATALOGS))})"
    )

    if args.force:
        to_fetch = objects
        print(f"Force mode: will re-fetch all {len(to_fetch)} objects")
    else:
        to_fetch = [
            obj for obj in objects if not os.path.exists(store.local_image_path(obj[2]))
        ]
        print(f"Missing images: {len(to_fetch)} of {len(objects)}")

    if not to_fetch:
        print("Nothing to fetch!")
        return

    session = requests.Session()
    session.headers.update({"User-Agent": "PiFinder-ImageGenerator/3.0"})

    failed: List[Tuple[str, str]] = []
    fetched = 0
    skipped = 0
    t_start = time.time()

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                fetch_object, session, ra, dec, name, source, args.force
            ): name
            for ra, dec, name, source in to_fetch
        }

        for future in tqdm(
            as_completed(futures), total=len(futures), desc="Generating"
        ):
            name = futures[future]
            try:
                _, survey, (ok, err) = future.result()
                if err == "exists":
                    skipped += 1
                elif ok:
                    fetched += 1
                else:
                    failed.append((f"{name} ({survey})", err))
            except Exception as e:
                failed.append((name, str(e)))

    elapsed = time.time() - t_start
    print(
        f"\nDone in {elapsed:.0f}s: {fetched} fetched, {skipped} skipped, "
        f"{len(failed)} failed"
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
