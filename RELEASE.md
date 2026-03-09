# PiFinder v2.5.0 Release Notes

## New Features

### T9 Input Support
Added T9-style text input for searching object catalogs using the hardware keypad. Type object names by pressing number keys to quickly filter catalog searches, just like texting on an old phone. Includes cached digit mapping for fast performance.

### Harris Globular Cluster Catalog
New catalog loader for the Harris Globular Cluster catalog, adding 147 globular clusters to the searchable database.

### Stellarium+ Mobile Support
Added support for connecting to Stellarium+ Mobile, including the ACK command needed for reliable connections without timeouts.

### Chinese (zh) Locale
Full Chinese language translation with a custom Sarasa Mono font for proper CJK character rendering. Chinese can be selected from the language settings menu.

## Bug Fixes

- **GPSD + Cedar crash fix**: Fixed an issue where early GPS dongles that never reported sky data could stall the GPS process. Also fixed auth-related solver crashes with Cedar.
- **Stellarium J2000 epoch fix**: Corrected coordinate epoch handling when connected to Stellarium, which uses J2000 rather than JNOW.
- **Double update bug**: Fixed an issue in the update script that could cause updates to run twice.
- **Eyepiece sorting**: Eyepieces are now always sorted by focal length (magnification) in the equipment list.
- **Push-to display fix**: Fixed a display issue in the push-to screen introduced by the Chinese locale update.

## Developer Improvements

- **Fake sys_utils environment toggle**: Added `PIFINDER_USE_FAKE_SYS_UTILS` environment variable for deterministic local development and testing without hardware dependencies.
- **Solver log level**: Reduced solver log verbosity for cleaner output.

## Hardware & Documentation

- Added a `pi_mount_noinserts.stl` variant for cases without heat-set inserts.
- Removed references to the discontinued HQ camera and assembled kit version.
- Various typo and spelling fixes throughout the documentation.

---

**Full Changelog**: 19 commits from release to main
