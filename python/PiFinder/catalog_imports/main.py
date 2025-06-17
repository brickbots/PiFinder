"""
Main orchestration module for catalog imports.

This module contains the main entry point and orchestration logic
for loading all astronomical catalogs into the PiFinder database.
"""

import argparse
import logging
import datetime

from .catalog_import_utils import print_database, resolve_object_images
from .database import init_shared_database
from .steinicke_loader import load_ngc_catalog
from .caldwell_loader import load_caldwell
from .bright_stars_loader import load_bright_stars
from .herschel_loader import load_herschel400
from .sac_loaders import load_sac_asterisms, load_sac_multistars, load_sac_redstars
from .specialized_loaders import (
    load_egc,
    load_collinder,
    load_taas200,
    load_rasc_double_Stars,
    load_barnard,
    load_sharpless,
    load_arp,
    load_tlk_90_vars,
    load_abell,
)
from .post_processing import fix_object_types, fix_m45


def main():
    """
    Main entry point for catalog import functionality.
    Handles command-line arguments and orchestrates all catalog loading.
    """
    logging.info("starting main")
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logging.getLogger("PIL.PngImagePlugin").setLevel(logging.WARNING)
    logging.basicConfig(format="%(asctime)s %(name)s: %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="eFinder")
    parser.add_argument(
        "-f",
        "--force",
        help="DANGER: overwrite observations.db",
        default=False,
        action="store_true",
        required=False,
    )
    parser.add_argument(
        "-x", "--verbose", help="Set logging to debug mode", action="store_true"
    )
    parser.add_argument("-l", "--log", help="Log to file", action="store_true")
    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    if args.log:
        datenow = datetime.datetime.now()
        filehandler = f"PiFinder-{datenow:%Y%m%d-%H_%M_%S}.log"
        fh = logging.FileHandler(filehandler)
        fh.setLevel(logger.level)
        logger.addHandler(fh)

    logging.info("Starting")
    
    # Initialize shared databases
    logging.info("Creating DB")
    objects_db, observations_db = init_shared_database()
    
    logging.info("creating catalog tables")
    objects_db.destroy_tables()
    objects_db.create_tables()
    
    logging.info("loading catalogs")
    
    # These load functions must be kept in this order
    # to keep some of the object referencing working
    # particularly starting with the NGC as the base
    load_ngc_catalog()
    
    # Load additional catalogs
    load_caldwell()
    load_collinder()
    load_taas200()
    load_herschel400()
    load_sac_asterisms()
    load_sac_multistars()
    load_sac_redstars()
    load_bright_stars()
    load_egc()
    load_rasc_double_Stars()
    load_barnard()
    load_sharpless()
    load_abell()
    load_arp()
    load_tlk_90_vars()

    # Fix data issues
    fix_object_types()
    fix_m45()

    # Populate the images table
    logging.info("Resolving object images...")
    resolve_object_images()
    print_database()


if __name__ == "__main__":
    main()