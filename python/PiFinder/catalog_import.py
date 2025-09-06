"""
Legacy compatibility wrapper for catalog import functionality.

The main functionality has been moved to the catalog_imports package.
This file maintains backward compatibility for existing code.
"""

# Re-export main functions from the new package structure
from PiFinder.catalog_imports.main import main
from PiFinder.catalog_imports.catalog_import_utils import (
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
