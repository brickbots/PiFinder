"""
Catalog import package for PiFinder.

This package contains all the catalog loading and import functionality,
organized by catalog type for better maintainability.
"""

# Import catalog loaders (but not main to avoid module conflicts)
from .steinicke_loader import load_ngc_catalog
from .caldwell_loader import load_caldwell
from .post_processing import fix_object_types, add_missing_messier_objects

__version__ = "1.0.0"
__all__ = ["load_ngc_catalog", "load_caldwell", "fix_object_types", "add_missing_messier_objects"]