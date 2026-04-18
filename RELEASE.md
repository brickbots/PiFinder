# PiFinder v2.5.0 Release Notes

## New Features

### T9 Input Support (#364)
Added T9-style text input for searching object catalogs using the hardware keypad. Type object names by pressing number keys to quickly filter catalog searches, just like texting on an old phone. Includes cached digit mapping for fast performance.

### Harris Globular Cluster Catalog (#384)
New catalog loader for the Harris Globular Cluster catalog, adding 147 globular clusters with detailed metadata (distance, metallicity, concentration, etc.) to the searchable database.

### Stellarium+ Mobile Support (#375)
Added support for connecting to Stellarium+ Mobile, including the ACK command and additional protocol responses needed for reliable connections without timeouts.

### Stellarium J2000 Epoch Handling (#376)
Corrected coordinate epoch handling when connected to Stellarium, which uses J2000 rather than JNOW. Skips unnecessary epoch conversion when J2000 is the input.

### Chinese (zh) Locale (#377)
Full Chinese language translation with a custom Sarasa Mono SC font for proper CJK character rendering. The font is conditionally loaded only when Chinese is selected, keeping memory usage low for other languages.

## Bug Fixes

- **GPSD + Cedar crash fix** (#386): Fixed an issue where early GPS dongles that never reported sky data could stall the GPS process. Also fixed auth-related solver crashes with Cedar.
- **Camera fade on non-solves**: Solver now clears RA/Dec/Matches before attempting a solve (not just when no stars are found), preventing stale position data from persisting after a failed solve. The UI fade timer was also doubled in speed (3s vs 6s ramp) for quicker visual feedback when the solver loses lock.
- **Position server TypeError**: Added defensive type coercion and error handling in `pos_server.py` for RA/Dec values, preventing crashes when solution coordinates are None or non-numeric.
- **Debug camera rotation timing**: Fixed the debug camera so it actually resets its timer when switching images, preventing images from cycling every frame after the first 10-second interval.
- **Double update bug**: Fixed an issue in the update process that could cause updates to run twice.
- **Eyepiece sorting** (#387): Eyepieces are now always sorted by focal length (magnification) in the equipment list.
- **Push-to display fix**: Fixed a display/typing issue in the push-to screen introduced by the Chinese locale update.

## Developer Improvements

- **Fake sys_utils environment toggle** (#380): Added `PIFINDER_USE_FAKE_SYS_UTILS` environment variable for deterministic local development and testing without hardware dependencies.
- **Fake GPS argument**: New `--gps fake` CLI argument to use a fake GPS module during development, complementing the existing `--camera debug` flag.
- **Solver log level**: Reduced solver log verbosity for cleaner output during normal operation.
- **T9 test suite**: Added comprehensive tests for T9 digit mapping and search filtering (`test_t9_search.py`).

## Hardware & Documentation

- Added `pi_mount_noinserts.stl` variant for cases assembled without heat-set inserts.
- Removed references to the discontinued HQ camera and assembled kit version.
- Various typo and spelling fixes throughout the documentation.

---

**Version**: 2.4.0 → 2.5.0
**Commits**: 22 (including 1 merge)
**Files changed**: 41 (+3,434 / -147 lines)
