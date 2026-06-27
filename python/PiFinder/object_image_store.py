#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Shared core for object images — ADR 0018: one sourceless image per object.

Centralizes the on-disk layout, sourceless name resolution, per-scope worklist
building, and single-image CDN download shared by:

  * the runtime **Display** path (``cat_images.get_display_image``),
  * the on-device **Download** feature (``object_image_download`` controller),
  * the thin ``get_images`` CLI.

An object image is stored sourceless as ``<base>/<last-digit>/<image_name>.jpg``
and served from the CDN at the matching path.  Survey provenance ("source") is a
recorded-but-not-runtime-branched curation directive (``object_images.source``),
read only by the dev-side **Generate** step (``gen_images``); nothing in this
module branches on it.  See ``docs/ax/catalog/CONTEXT.md`` → "Object images" and
``docs/adr/0018-one-object-image-per-object.md``.

Deliberately lightweight (no PIL / no UI imports) so the CLI and the catalog
import tooling can use it without pulling in the display stack.
"""

import logging
import os
from typing import List, Optional

import requests

from PiFinder import utils

logger = logging.getLogger("Catalog.ImageStore")

# Local, on-device root for downloaded object images.
BASE_IMAGE_PATH = f"{utils.data_dir}/catalog_images"

# CloudFront host serving the curated, sourceless object images.  Kept as a
# single module constant (not user config) — see the ADR consequences.
CDN_BASE_URL = "https://ddbeeedxfpnp0.cloudfront.net/catalog_images"

# Catalogs with no meaningful survey image; excluded from the "All" scope and
# from the CDN.  Matches ``gen_images`` (the publisher).
EXCLUDED_CATALOGS = {"WDS"}

# Conservative, fixed concurrency for the on-device download worker.  Downloads
# are I/O-bound (network + SD-card writes), so a small pool overlaps latency
# while keeping the Pi responsive.  Not user-configurable in v1.
DEFAULT_DOWNLOAD_WORKERS = 4

# Per-image size estimate for the pre-flight ("~N MB to download").  The curated
# survey JPEGs vary; this is a deliberately rough average for a human-facing
# estimate only, never a hard limit.
ESTIMATED_IMAGE_BYTES = 120_000

REQUEST_TIMEOUT = 30
_USER_AGENT = "PiFinder-ImageDownloader/2.0"

# Download scopes (v1).  All / single-catalog are pure DB queries and work from
# the thin CLI; filter / observing-list need the running app to supply the live
# objects (mapped via object_id to the canonical CDN ``image_name``).
SCOPE_ALL = "all"
SCOPE_CATALOG = "catalog"
SCOPE_FILTER = "filter"
SCOPE_LIST = "list"

# Per-image download outcomes.
RESULT_DOWNLOADED = "downloaded"  # fetched and written
RESULT_SKIPPED = "skipped"  # already present locally (idempotent skip)
RESULT_MISSING = "missing"  # 403/404 — not on the CDN (tolerated)
RESULT_ERROR = "error"  # network/HTTP error


# --------------------------------------------------------------------------- #
# On-disk / CDN layout
# --------------------------------------------------------------------------- #
def image_bucket(image_name: str) -> str:
    """Bucket sub-directory for an ``image_name`` (its last character)."""
    return str(image_name)[-1]


def local_image_path(image_name: str) -> str:
    """Absolute on-disk path for a sourceless object image."""
    return f"{BASE_IMAGE_PATH}/{image_bucket(image_name)}/{image_name}.jpg"


def cdn_image_url(image_name: str) -> str:
    """CDN URL for a sourceless object image."""
    return f"{CDN_BASE_URL}/{image_bucket(image_name)}/{image_name}.jpg"


def create_catalog_image_dirs() -> None:
    """Create the base image dir and its ten (0-9) bucket sub-directories."""
    if not os.path.exists(BASE_IMAGE_PATH):
        os.makedirs(BASE_IMAGE_PATH)
    for i in range(0, 10):
        bucket = f"{BASE_IMAGE_PATH}/{i}"
        if not os.path.exists(bucket):
            os.makedirs(bucket)


def resolve_image_name(catalog_object) -> str:
    """Local path of the displayable object image, or ``""`` if none on disk.

    Sourceless (ADR 0018): a single ``<digit>/<stem>.jpg`` per object.  Tries
    the viewed listing's ``catalog_code``+``sequence`` stem first, then falls
    back to each whitespace-stripped common **Name** (this is what resolves an
    object whose canonical image was published under another catalog's
    designator — e.g. M 31 is stored as ``NGC224`` and matched via its
    ``"NGC 224"`` name).
    """

    def _path_if_exists(stem: str):
        path = local_image_path(stem)
        return os.path.exists(path), path

    stem = f"{catalog_object.catalog_code}{catalog_object.sequence}"
    ok, path = _path_if_exists(stem)
    if ok:
        return path

    for name in catalog_object.names:
        ok, path = _path_if_exists("".join(name.split()))
        if ok:
            return path

    return ""


# --------------------------------------------------------------------------- #
# Worklists (which image_names a scope needs)
# --------------------------------------------------------------------------- #
def all_image_names(cursor) -> List[str]:
    """Every CDN-eligible ``image_name`` (all catalogs minus the excluded set)."""
    placeholders = ",".join("?" for _ in EXCLUDED_CATALOGS)
    rows = cursor.execute(
        f"""
        SELECT DISTINCT oi.image_name
        FROM object_images oi
        JOIN catalog_objects co ON co.object_id = oi.object_id
        WHERE co.catalog_code NOT IN ({placeholders})
          AND oi.image_name != ''
        """,
        list(EXCLUDED_CATALOGS),
    ).fetchall()
    return [row["image_name"] for row in rows]


def catalog_image_names(cursor, catalog_code: str) -> List[str]:
    """Every ``image_name`` reachable through a single catalog's listings."""
    rows = cursor.execute(
        """
        SELECT DISTINCT oi.image_name
        FROM object_images oi
        JOIN catalog_objects co ON co.object_id = oi.object_id
        WHERE co.catalog_code = ?
          AND oi.image_name != ''
        """,
        (catalog_code,),
    ).fetchall()
    return [row["image_name"] for row in rows]


def image_names_for_object_ids(cursor, object_ids) -> List[str]:
    """Canonical ``image_name``s for a set of sky-object ids.

    Used by the filter / observing-list scopes: the live ``CompositeObject``s
    carry an ``object_id`` but their ``image_name`` attribute is unset until
    display, so the canonical CDN stem is looked up here (one row per imaged
    sky object), independent of which catalog listing the user is viewing.
    """
    ids = sorted({int(oid) for oid in object_ids})
    if not ids:
        return []
    # Chunk the IN list so a large filter / observing list stays under SQLite's
    # bound-variable limit (999 on older builds).
    chunk_size = 900
    names: List[str] = []
    seen = set()
    for start in range(0, len(ids), chunk_size):
        chunk = ids[start : start + chunk_size]
        placeholders = ",".join("?" for _ in chunk)
        rows = cursor.execute(
            f"""
            SELECT DISTINCT image_name
            FROM object_images
            WHERE object_id IN ({placeholders})
              AND image_name != ''
            """,
            chunk,
        ).fetchall()
        for row in rows:
            name = row["image_name"]
            if name not in seen:
                seen.add(name)
                names.append(name)
    return names


def worklist_for_scope(
    scope: str,
    cursor,
    *,
    catalog_code: Optional[str] = None,
    objects: Optional[list] = None,
) -> List[str]:
    """Return the distinct ``image_name``s a download *scope* covers.

    * ``SCOPE_ALL`` / ``SCOPE_CATALOG`` — pure DB queries (also usable headless).
    * ``SCOPE_FILTER`` / ``SCOPE_LIST`` — derived from caller-supplied live
      ``objects`` (their ``object_id``s), mapped to canonical ``image_name``s.
    """
    if scope == SCOPE_ALL:
        return all_image_names(cursor)
    if scope == SCOPE_CATALOG:
        if not catalog_code:
            raise ValueError("SCOPE_CATALOG requires catalog_code")
        return catalog_image_names(cursor, catalog_code)
    if scope in (SCOPE_FILTER, SCOPE_LIST):
        object_ids = [getattr(obj, "object_id") for obj in (objects or [])]
        return image_names_for_object_ids(cursor, object_ids)
    raise ValueError(f"unknown download scope: {scope!r}")


def missing_image_names(image_names) -> List[str]:
    """Subset of ``image_names`` not yet present on local disk (download targets)."""
    return [name for name in image_names if not os.path.exists(local_image_path(name))]


def estimated_download_bytes(missing_count: int) -> int:
    """Rough total size estimate for the pre-flight, in bytes."""
    return missing_count * ESTIMATED_IMAGE_BYTES


# --------------------------------------------------------------------------- #
# Download (one curated, sourceless image)
# --------------------------------------------------------------------------- #
def new_session() -> requests.Session:
    """A pooled ``requests`` session with the PiFinder user-agent."""
    session = requests.Session()
    session.headers.update({"User-Agent": _USER_AGENT})
    return session


def cdn_reachable(session: Optional[requests.Session] = None, timeout: int = 8) -> bool:
    """Quick reachability probe of the CDN host for the pre-flight.

    A reachable CloudFront may answer the bare host path with 403/404; anything
    short of a transport failure (or 5xx) counts as reachable.
    """
    own = session is None
    session = session or new_session()
    try:
        resp = session.head(f"{CDN_BASE_URL}/", timeout=timeout)
        return resp.status_code < 500
    except requests.RequestException:
        return False
    finally:
        if own:
            session.close()


def download_object_image(
    session: requests.Session,
    image_name: str,
    *,
    overwrite: bool = False,
    timeout: int = REQUEST_TIMEOUT,
) -> str:
    """Download one sourceless object image to local disk.

    Idempotent: an already-present file is left untouched (``RESULT_SKIPPED``)
    unless ``overwrite`` is set.  404/403 means the CDN has no image for this
    name and is tolerated (``RESULT_MISSING``).  Writes atomically via a
    ``.part`` temp file so a cancel / power-loss never leaves a truncated JPEG.
    """
    dest = local_image_path(image_name)
    if not overwrite and os.path.exists(dest):
        return RESULT_SKIPPED

    try:
        resp = session.get(cdn_image_url(image_name), timeout=timeout)
    except requests.RequestException as exc:
        logger.debug("download error for %s: %s", image_name, exc)
        return RESULT_ERROR

    if resp.status_code == 200:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        tmp = f"{dest}.part"
        with open(tmp, "wb") as out:
            out.write(resp.content)
        os.replace(tmp, dest)
        return RESULT_DOWNLOADED
    if resp.status_code in (403, 404):
        return RESULT_MISSING
    logger.debug("download for %s returned HTTP %s", image_name, resp.status_code)
    return RESULT_ERROR
