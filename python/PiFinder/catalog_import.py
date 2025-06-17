"""
Legacy compatibility wrapper for catalog import functionality.

The main functionality has been moved to the catalog_imports package.
This file maintains backward compatibility for existing code.
"""

# Re-export main functions from the new package structure
from PiFinder.catalog_imports.main import main
from PiFinder.catalog_imports.steinicke_loader import load_ngc_catalog
from PiFinder.catalog_imports.caldwell_loader import load_caldwell
from PiFinder.catalog_imports.bright_stars_loader import load_bright_stars
from PiFinder.catalog_imports.herschel_loader import load_herschel400
from PiFinder.catalog_imports.sac_loaders import (
    load_sac_asterisms,
    load_sac_multistars,
    load_sac_redstars,
)
from PiFinder.catalog_imports.specialized_loaders import (
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
from PiFinder.catalog_imports.post_processing import fix_object_types, fix_m45
from PiFinder.catalog_imports.catalog_import_utils import (
    NewCatalogObject,
    ObjectFinder,
    safe_convert_to_float,
    add_space_after_prefix,
    trim_string,
    delete_catalog_from_database,
    insert_catalog,
    insert_catalog_max_sequence,
    get_catalog_counts,
    print_database,
    resolve_object_images,
    dedup_names,
    init_databases,
)

# Initialize global database objects for backward compatibility
objects_db = None
observations_db = None

def _init_globals():
    """Initialize global database objects"""
    global objects_db, observations_db
    if objects_db is None:
        objects_db, observations_db = init_databases()

# Ensure globals are initialized when module is imported
_init_globals()

if __name__ == "__main__":
    main()