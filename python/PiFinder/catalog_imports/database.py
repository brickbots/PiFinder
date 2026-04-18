"""
Shared database module for catalog imports.

This module provides centralized access to database objects for all catalog loaders.
"""

from typing import Optional
from .catalog_import_utils import init_databases, ObjectsDatabase, ObservationsDatabase

# Global database objects shared across all catalog loaders
objects_db: Optional[ObjectsDatabase] = None
observations_db: Optional[ObservationsDatabase] = None


def init_shared_database():
    """Initialize the shared database objects"""
    global objects_db, observations_db
    if objects_db is None:
        objects_db, observations_db = init_databases()
        # Update this module's globals as well
        globals()["objects_db"] = objects_db
        globals()["observations_db"] = observations_db
    return objects_db, observations_db
