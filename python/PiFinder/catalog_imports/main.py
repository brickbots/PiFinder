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

# Loader registry - import functions dynamically to reduce coupling
CATALOG_LOADERS = [
    # Core catalogs (order matters for referencing)
    ("steinicke_loader", "load_ngc_catalog"),
    # Additional catalogs
    ("caldwell_loader", "load_caldwell"),
    ("specialized_loaders", "load_collinder"),
    ("specialized_loaders", "load_taas200"),
    ("herschel_loader", "load_herschel400"),
    ("sac_loaders", "load_sac_asterisms"),
    ("sac_loaders", "load_sac_multistars"),
    ("sac_loaders", "load_sac_redstars"),
    ("bright_stars_loader", "load_bright_stars"),
    ("specialized_loaders", "load_egc"),
    ("specialized_loaders", "load_rasc_double_Stars"),
    ("specialized_loaders", "load_barnard"),
    ("specialized_loaders", "load_sharpless"),
    ("specialized_loaders", "load_abell"),
    ("specialized_loaders", "load_arp"),
    ("specialized_loaders", "load_tlk_90_vars"),
    ("wds_loader", "load_wds"),
]

POST_PROCESSING_FUNCTIONS = [
    ("post_processing", "fix_object_types"),
    ("post_processing", "add_missing_messier_objects"),
]


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
    objects_db, _ = init_shared_database()

    logging.info("creating catalog tables")
    objects_db.destroy_tables()
    objects_db.create_tables()

    logging.info("loading catalogs")

    # Load catalogs using registry (order is preserved for referencing)
    for module_name, function_name in CATALOG_LOADERS:
        try:
            module = __import__(
                f"PiFinder.catalog_imports.{module_name}", fromlist=[function_name]
            )
            loader_func = getattr(module, function_name)
            logging.info(f"Loading catalog: {function_name}")
            loader_func()
        except Exception as e:
            logging.error(f"Failed to load {function_name} from {module_name}: {e}")
            raise

    # Run post-processing functions
    for module_name, function_name in POST_PROCESSING_FUNCTIONS:
        try:
            module = __import__(
                f"PiFinder.catalog_imports.{module_name}", fromlist=[function_name]
            )
            process_func = getattr(module, function_name)
            logging.info(f"Running post-processing: {function_name}")
            process_func()
        except Exception as e:
            logging.error(f"Failed to run {function_name} from {module_name}: {e}")
            raise

    # Populate the images table
    logging.info("Resolving object images...")
    resolve_object_images()
    print_database()


if __name__ == "__main__":
    main()
