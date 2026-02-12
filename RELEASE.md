# PiFinder v2.4.0 Release Notes

## Major New Features

### Sky Quality Meter (SQM) - Experimental
A new Sky Quality Meter feature measures sky brightness and displays the corresponding Bortle scale classification. This helps observers assess observing conditions at their location.
- Real-time SQM measurement with Bortle class display
- Calibration UI for accurate readings across different camera configurations
- Camera profiles for IMX296 and other supported sensors
- Rotating constellation/SQM display in title bar

### Camera Auto Exposure
Automatic exposure control using a PID-based algorithm that adapts to changing sky conditions.
- Asymmetric tuning for responsive exposure adjustments
- Exposure sweep functionality for calibration
- SNR-based thresholds derived from camera profiles
- Visual exposure overlay in preview mode

### Cedar-Detect System Service
Cedar-Detect now runs as a dedicated system service rather than a subprocess, improving stability and resource management. This change is transparent to users but provides better crash recovery and memory handling.

## Improvements

### GPS
- **Configurable baud rate**: GPS baud rate can now be configured via the Advanced settings menu (#345)
- **Reorganized GPS settings**: GPS options now grouped under Settings > Advanced > GPS Settings
- **GPSD improvements**: Fixed lock_type handling for GPSD-based GPS messages (#358)
- **Early dongle fix**: Fixed issue where some GPS dongles never reported sky data (#373)

### Catalogs
- **WDS catalog**: Improved loading speed with background loading for better UI responsiveness (#352, #355)
- **Async search**: Search is now asynchronous for improved responsiveness
- **Comet catalog**: Better refresh and download handling with non-blocking updates (#353)
- **Bright stars**: Fixed off-by-one error in bright stars catalog

### User Interface
- **EQ mode**: Push-to now uses +/- buttons rather than arrows for clearer directional guidance
- **Settings reorganization**: Advanced settings (PiFinder Type, Camera Type, GPS Settings) now grouped under an "Advanced" submenu
- **Preview cleanup**: Removed background subtraction and gamma functions from preview
- **Experimental menu**: Moved higher in menu structure for easier access

## Bug Fixes

- Fixed preview crash when marking menu items are missing
- Fixed crash when screenshot title contains a slash
- Fixed OSX logging levels by applying log config in each subprocess
- Fixed various solver stability issues with improved error handling
- Fixed typo in SkySafari documentation
- Fixed typo in menu

## Hardware & Documentation

- Adjusted GPS antenna holder sizing
- Improved case tolerances and new dovetail design
- Updated shroud with tighter tolerance
- Added instructions to build guide for testing LEDs and buttons
- Clarified DIY vs Assembled parts in case documentation

## Migration Notes

This release includes a migration script (`migration_source/v2.4.0.sh`) that sets up the Cedar-Detect system service. The migration will run automatically during the update process.

---

**Full Changelog**: 40 commits from release to main
