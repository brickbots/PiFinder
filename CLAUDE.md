# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

**Development workflow uses Nox for task automation:**
```bash
nox -s lint          # Code linting with Ruff (auto-fixes issues)
nox -s format        # Code formatting with Ruff
nox -s type_hints    # Type checking with MyPy
nox -s smoke_tests   # Quick functionality validation
nox -s unit_tests    # Full unit test suite
nox -s babel         # I18n message extraction and compilation
```

**Direct testing with pytest:**
```bash
pytest -m smoke      # Smoke tests for core functionality
pytest -m unit       # Unit tests for isolated components
pytest -m integration # End-to-end integration tests
```

**Development setup:**
```bash
cd python/
pip install -r requirements.txt
pip install -r requirements_dev.txt
```

Watch out for .venv directories containing virtual environments, that you need to activate first. 

**Running the application:**
```bash
cd python/
python -m PiFinder.main [options]
```

## Architecture Overview

**Multi-Process Design:** PiFinder uses a process-based architecture where each major subsystem runs in its own process, communicating via queues and shared state objects:

- **Main Process** (`main.py`) - UI event loop, menu system, user interaction
- **Camera Process** - Image capture from various camera types (Pi, ASI, debug)
- **Solver Process** - Plate solving using Tetra3/Cedar libraries for star pattern recognition
- **GPS Process** - Location/time via GPSD or UBlox direct interface
- **IMU Process** - Motion tracking with BNO055 sensor
- **Integrator Process** - Combines solver + IMU data for real-time positioning
- **Web Server Process** - Web interface and SkySafari integration as a telescope 
- **Position Server Process** - External protocol support

**State Management:** 
- `SharedStateObj` - Process-shared state using multiprocessing managers
- `UIState` - UI-specific state management

**Database Layer:**
- SQLite backend (`astro_data/pifinder_objects.db`)
- `ObjectsDatabase` - Astronomical catalog management (NGC, Messier, etc.)
- `ObservationsDatabase` - Session logging and observation tracking
- Modular catalog import system supporting multiple astronomical databases

**Hardware Abstraction:**
- Camera interface supporting IMX296 (global shutter), IMX290/462, HQ cameras
- Display system for SSD1351 OLED and ST7789 LCD with night vision preservation using red channel only
- Hardware keypad with PWM brightness control
- GPS integration via GPSD or direct UBlox protocol
- IMU sensor integration for motion detection and telescope orientation

## Key Directories

- `python/PiFinder/` - Core application modules
- `python/PiFinder/ui/` - User interface components (menus, screens, charts)
- `python/PiFinder/db/` - Database abstraction layer
- `astro_data/` - Astronomical catalogs and object databases
- `python/tests/` - Test suite (smoke, unit, integration markers)
- `case/` - 3D printable enclosure files
- `docs/` - Documentation and build guides

## Configuration

**Config Files:**
- `default_config.json` - System defaults
- `~/PiFinder_data/config.json` - User settings
- Equipment profiles for telescopes and eyepieces
- Display, camera, GPS, and solver parameters

**Hardware Configuration:**
- Camera selection: Pi Camera, ASI cameras, debug mode
- Display type: OLED vs LCD with brightness/orientation settings  
- Input method: hardware keypad, local keyboard, web interface
- GPS receiver: GPSD daemon vs direct UBlox protocol

## Testing Strategy

Tests use pytest with custom markers for different test types. The smoke tests provide quick validation while unit tests cover isolated functionality. Integration tests validate end-to-end workflows including the multi-process architecture.

**Key test areas:**
- Calculation utilities and coordinate transformations
- Catalog data validation and import processes
- Menu structure and navigation logic
- Multi-process logging and communication
- Hardware interface abstractions
- Website testing

### Website testing setup

**Testing Framework:** Uses Selenium WebDriver with Pytest for automated browser testing of the web interface

**Infrastructure Requirements:**
- Selenium Grid server at localhost:4444 (configurable via SELENIUM_GRID_URL environment variable)
- Chrome browser in headless mode for test execution
- Tests automatically skip if Selenium Grid is unavailable

**Test Coverage Areas:**
- **Web Interface** (`test_web_interface.py`): Basic page loading, image display, status table elements (Mode, coordinates, software version)
- **Location Management** (`test_web_locations.py`): Location CRUD operations, DMS coordinate entry, default switching, GPS integration via remote interface
- **Network Configuration** (`test_web_network.py`): WiFi settings form validation, network management, restart flows, modal dialogs
- **Remote Control** (`test_web_remote.py`): Authentication, virtual keypad, menu navigation, marking menus, API endpoint validation

**Authentication:** All protected pages use default password "solveit"

**Responsive Testing:** Tests run on both desktop (1920x1080) and mobile (375x667) viewports

**API Integration:** Extensive use of `/api/current-selection` endpoint to validate UI state changes and ensure web interface accurately reflects PiFinder's internal state

**Helper Utilities:** Shared utilities in `web_test_utils.py` for login flows, key simulation, and state validation with recursive dictionary comparison

## Code Quality

- **Linting:** Ruff with Python 3.9 target, Black-compatible formatting
- **Type Checking:** MyPy with gradual typing adoption
- **Code Style:** 88-character line length, double quotes, space indentation
- **I18n Support:** Babel integration for multi-language UI

The codebase follows modern Python practices with type hints, comprehensive testing, and automated code quality checks integrated into the development workflow.