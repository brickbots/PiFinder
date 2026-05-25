"""v2.6.0 migration: clear stale ``flop_image=true`` on the default Dobsonian.

Early builds shipped a "Generic Dobsonian" with ``flop_image=true``. A
Newtonian/Dobsonian is even parity and needs neither flip nor flop (the
object-image baseline already applies a fixed 180 deg rotation). The flags were
never read until the flip/flop wiring landed for this release, so any user who
froze the bad default into their config (by selecting active gear or editing
equipment) would now see their object image incorrectly mirrored left-right.

This corrects persisted configs. ``default_config.json`` was fixed separately
for new/unpersisted users. See docs/adr/0003-object-image-orientation.md and
docs/ax/equipment.md (section 8).

Stdlib only: invoked by absolute file path from migration_source/v2.6.0.sh, so
it must not import PiFinder or rely on the working directory.
"""

from __future__ import annotations

import json
import os
import sys

# Identifying signature of the shipped "Generic Dobsonian" default plus the
# known-bad orientation state. ``flip_image==False && flop_image==True`` only
# ever came from this bad default: flip/flop were non-functional until now, so
# no user has a deliberately-chosen flop=true in the wild. obstruction_perc and
# reverse_arrow_* are intentionally excluded from the match so a user who
# toggled those (independent concerns) but never touched flop is still fixed.
_DOB_SIGNATURE = {
    "make": "Generic",
    "name": "Dobsonian",
    "aperture_mm": 200,
    "focal_length_mm": 1000,
    "mount_type": "alt/az",
    "flip_image": False,
    "flop_image": True,
}

DEFAULT_CONFIG_PATH = os.path.expanduser("~/PiFinder_data/config.json")


def _is_bad_dob(telescope: dict) -> bool:
    """True if ``telescope`` matches the bad shipped Dobsonian signature."""
    return all(telescope.get(key) == value for key, value in _DOB_SIGNATURE.items())


def migrate_dob_flop(config_path: str) -> int:
    """Clear ``flop_image`` on any persisted copy of the bad default Dobsonian.

    Operates on the raw JSON, mutating only matching telescope records and
    leaving the rest of the file (eyepieces, indices, other config, formatting)
    intact, matching how ``config.py`` reads/writes (``json.load`` /
    ``json.dump(..., indent=4)``).

    Returns the number of records corrected. No-op (returns 0) when the file is
    missing, has no ``equipment`` dict, no ``telescopes`` list, or no match; it
    never creates the file. Idempotent: once corrected a record no longer
    matches ``flop_image==True``, so a re-run changes nothing.
    """
    if not os.path.exists(config_path):
        return 0

    with open(config_path, "r") as config_file:
        config = json.load(config_file)

    equipment = config.get("equipment")
    if not isinstance(equipment, dict):
        return 0

    telescopes = equipment.get("telescopes")
    if not isinstance(telescopes, list):
        return 0

    fixed = 0
    for telescope in telescopes:
        if isinstance(telescope, dict) and _is_bad_dob(telescope):
            telescope["flop_image"] = False
            fixed += 1

    if fixed:
        with open(config_path, "w") as config_file:
            json.dump(config, config_file, indent=4)

    return fixed


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CONFIG_PATH
    corrected = migrate_dob_flop(path)
    print(f"v2.6.0 dob-flop migration: corrected {corrected} telescope record(s)")
