"""One-time, version-gated data migrations for persisted user config.

Each module here corrects a specific bad value in
``~/PiFinder_data/config.json``. Modules are invoked by absolute file path
from ``migration_source/<version>.sh`` (driven by ``pifinder_post_update.sh``)
and must depend only on the standard library so they run regardless of the
working directory at update time.
"""
