"""
Named Stars catalog loader for PiFinder.

One listing for each star the IAU Catalog of Star Names (the WGSN's) gives a
Hipparcos number for, numbered by that number: Vega is Nam 91262. The number
stays the star's as the WGSN adopts new names, and it identifies the star:
the star-identity stage joins the listing to the star other catalogs list by
that number, never by position (docs/ax/catalog.md §9.3).

The listing carries no names of its own. The WGSN supplementary source
(add_wgsn_names) gives each identified star its IAU name, so a star never
gets its name twice.
"""

import logging
import math
from pathlib import Path
from typing import List, Optional

import PiFinder.utils as utils
from PiFinder.composite_object import MagnitudeObject, SizeObject
from .catalog_import_utils import (
    NewCatalogObject,
    delete_catalog_from_database,
    insert_catalog,
    insert_catalog_max_sequence,
)
from .database import objects_db
from .star_identity import HIP_NUMBERED_CATALOGS, Hipparcos, load_hipparcos
from .supplementary_sources import WGSN_PATH, read_wgsn

CATALOG_CODE = "Nam"
assert CATALOG_CODE in HIP_NUMBERED_CATALOGS
DESCRIPTION_PATH = Path(utils.astro_data_dir, "named_stars.desc")


def named_star_listings(
    hipparcos: Hipparcos, path: Path = WGSN_PATH
) -> List[NewCatalogObject]:
    """One listing per HIP number the WGSN names, in HIP order.

    The position is Hipparcos's, carried to J2000 by its proper motion. The V
    is Hipparcos's: the star's own where Hipparcos says so (Hipparcos.own_vmag),
    otherwise the light of the whole system it measured, which is what a
    finder shows of a star its catalog lists alone. A name without a HIP
    number has no listing.
    """
    hips = sorted({name.hip for name in read_wgsn(path) if name.hip is not None})
    listings = []
    for hip in hips:
        index = hipparcos.index_of(hip)
        if index is None:
            raise ValueError(f"WGSN names HIP {hip}, which Hipparcos lacks")
        vmag = float(hipparcos.vmag[index])
        listings.append(
            NewCatalogObject(
                object_type="*",
                catalog_code=CATALOG_CODE,
                sequence=hip,
                ra=float(hipparcos.ra[index]),
                dec=float(hipparcos.dec[index]),
                mag=MagnitudeObject([] if math.isnan(vmag) else [vmag]),
                size=SizeObject([]),
            )
        )
    return listings


def load_named_stars(
    hipparcos: Optional[Hipparcos] = None, path: Path = WGSN_PATH
) -> None:
    """Load the Named Stars catalog: every IAU-named Hipparcos star."""
    logging.info("Loading Named Stars")
    assert objects_db is not None, "init_shared_database() runs first"
    hipparcos = hipparcos if hipparcos is not None else load_hipparcos()
    conn, _ = objects_db.get_conn_cursor()
    delete_catalog_from_database(CATALOG_CODE)
    insert_catalog(CATALOG_CODE, DESCRIPTION_PATH)
    listings = named_star_listings(hipparcos, path)
    objects_db.bulk_mode = True
    try:
        for listing in listings:
            # The listing names nothing to join: the star-identity stage joins
            # it to its star by HIP number.
            listing.insert(find_object_id=False)
        conn.commit()
    finally:
        objects_db.bulk_mode = False
    insert_catalog_max_sequence(CATALOG_CODE)
    logging.info("Named Stars: %d stars", len(listings))
