"""v2.7.0 migration: one sourceless object image per object.

ADR 0018 moves object images from two source-suffixed files per object
(``<name>_POSS.jpg`` / ``<name>_SDSS.jpg``) to a single sourceless image
(``<name>.jpg``), matching the re-laid-out CDN.  This renames any legacy
suffixed files already on the device:

  * POSS wins when both a POSS and an SDSS file exist (the runtime only ever
    displayed POSS); the redundant SDSS file is removed.
  * If a sourceless ``<name>.jpg`` already exists, the suffixed copies are just
    removed as redundant.

Walks ``<base>/<digit>/`` buckets under the catalog-images dir.  Idempotent:
once converted there are no ``_POSS``/``_SDSS`` files left, so a re-run is a
no-op.  Version-gated and run once by ``pifinder_post_update.sh``.

Stdlib only: invoked by absolute file path from migration_source/v2.7.0.sh, so
it must not import PiFinder or rely on the working directory.
"""

import os
import sys

POSS_SUFFIX = "_POSS.jpg"
SDSS_SUFFIX = "_SDSS.jpg"

DEFAULT_BASE_PATH = "/home/pifinder/PiFinder_data/catalog_images"


def _legacy_stems(file_names):
    """Base stems in a bucket that have a legacy ``_POSS``/``_SDSS`` file."""
    stems = set()
    for name in file_names:
        if name.endswith(POSS_SUFFIX):
            stems.add(name[: -len(POSS_SUFFIX)])
        elif name.endswith(SDSS_SUFFIX):
            stems.add(name[: -len(SDSS_SUFFIX)])
    return stems


def migrate_images(base_path):
    """Rename legacy suffixed images under ``base_path`` to sourceless names.

    Returns ``(renamed, removed)`` counts.  No-op (returns ``(0, 0)``) when the
    directory is missing; never creates it.
    """
    renamed = 0
    removed = 0
    if not os.path.isdir(base_path):
        return renamed, removed

    for bucket in os.listdir(base_path):
        bucket_path = os.path.join(base_path, bucket)
        if not os.path.isdir(bucket_path):
            continue

        for stem in _legacy_stems(os.listdir(bucket_path)):
            poss = os.path.join(bucket_path, stem + POSS_SUFFIX)
            sdss = os.path.join(bucket_path, stem + SDSS_SUFFIX)
            target = os.path.join(bucket_path, stem + ".jpg")

            if os.path.exists(poss):
                chosen, other = poss, sdss
            elif os.path.exists(sdss):
                chosen, other = sdss, None
            else:
                continue

            if os.path.exists(target):
                # Sourceless image already present; suffixed copies are redundant.
                for path in (poss, sdss):
                    if os.path.exists(path):
                        os.remove(path)
                        removed += 1
                continue

            os.replace(chosen, target)
            renamed += 1
            if other is not None and os.path.exists(other):
                os.remove(other)
                removed += 1

    return renamed, removed


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_BASE_PATH
    renamed_count, removed_count = migrate_images(path)
    print(
        "v2.7.0 sourceless-images migration: "
        f"renamed {renamed_count}, removed {removed_count} redundant"
    )
