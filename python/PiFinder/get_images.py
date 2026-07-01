#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Thin CLI to download curated object images from the CDN (ADR 0018).

For most users this is replaced by the on-device flow at
Tools ▸ Download Images.  It is kept as a headless fallback for the two
scopes that are pure DB queries — **All** (every object minus the excluded
catalogs) and **single catalog** — which need no running app.  The filter /
observing-list scopes need the live app and are device-only.

All the real work (layout, worklist, sourceless download) lives in the shared
``object_image_store`` core; this module is just argument parsing and a progress
bar.

Usage:
    python -m PiFinder.get_images                 # all objects (minus WDS)
    python -m PiFinder.get_images --catalog NGC   # one catalog
    python -m PiFinder.get_images --workers 8     # more concurrency
    python -m PiFinder.get_images --overwrite     # re-fetch existing files
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

from tqdm import tqdm

from PiFinder import object_image_store as store
from PiFinder.db.objects_db import ObjectsDatabase


def main():
    parser = argparse.ArgumentParser(
        description="Download PiFinder object images from the CDN"
    )
    parser.add_argument(
        "--catalog",
        help="Limit to a single catalog code (e.g. NGC, M, IC). Default: all.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=store.DEFAULT_DOWNLOAD_WORKERS,
        help=f"Concurrent downloads (default: {store.DEFAULT_DOWNLOAD_WORKERS})",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Re-download images that already exist",
    )
    args = parser.parse_args()

    store.create_catalog_image_dirs()

    objects_db = ObjectsDatabase()
    _, cursor = objects_db.get_conn_cursor()
    if args.catalog:
        names = store.worklist_for_scope(
            store.SCOPE_CATALOG, cursor, catalog_code=args.catalog
        )
    else:
        names = store.worklist_for_scope(store.SCOPE_ALL, cursor)

    targets = names if args.overwrite else store.missing_image_names(names)
    print(f"{len(names)} images in scope; {len(targets)} to download")
    if not targets:
        print("Nothing to download.")
        return

    session = store.new_session()
    counts = {
        store.RESULT_DOWNLOADED: 0,
        store.RESULT_SKIPPED: 0,
        store.RESULT_MISSING: 0,
        store.RESULT_ERROR: 0,
    }
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = [
                executor.submit(
                    store.download_object_image,
                    session,
                    name,
                    overwrite=args.overwrite,
                )
                for name in targets
            ]
            for future in tqdm(
                as_completed(futures), total=len(futures), desc="Downloading"
            ):
                counts[future.result()] += 1
    finally:
        session.close()

    print(
        f"Done: {counts[store.RESULT_DOWNLOADED]} downloaded, "
        f"{counts[store.RESULT_SKIPPED]} skipped, "
        f"{counts[store.RESULT_MISSING]} missing (404), "
        f"{counts[store.RESULT_ERROR]} errors"
    )


if __name__ == "__main__":
    main()
