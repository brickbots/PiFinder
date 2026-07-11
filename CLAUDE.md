# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Branch Model

- **`main`** is the integration / development branch. **All PRs target `main`.**
- **`release`** is the production branch — code is promoted from `main` to `release` as part of a release cut. Do not open PRs directly against `release`.
- Feature branches: branch off `main` and PR back to `main`.

Note: the auto-detected "Main branch" shown in the Claude Code env block may currently read `release` (because the GitHub default branch points there). Disregard that — the rule above is authoritative for this repo.

### Agent worktrees

Worktrees must be rooted on **`main`**. The harness's `fresh` base resolves to this clone's `origin/HEAD`, which may point at `release` (the GitHub default) — in which case `EnterWorktree` lands on `release`, not `main`. CLAUDE.md cannot change this; it is decided by the harness before any instruction here is read.

After `EnterWorktree`, **verify the base before making changes**: if `git merge-base HEAD origin/main` does not equal `origin/main`'s tip, the worktree is on the wrong branch — run `git reset --hard origin/main` and proceed from there.

Maintainers can make `fresh` root on `main` automatically per clone (without changing GitHub's default branch) by repointing the local default-branch pointer:

```bash
git remote set-head origin main
```

**No tetra3 submodule on this branch.** Unlike upstream `main`, the solver
(`cedar-solve`/Tetra3) is an ordinary uv dependency (pinned git rev in
`python/pyproject.toml`), so worktrees need no `git submodule` step.

## Development Commands

**This branch uses uv (pyproject.toml + uv.lock), not nox/requirements*.txt.**
All Python tooling runs through uv from `python/`:

```bash
cd python/
uv sync --frozen                                  # create/refresh .venv from uv.lock
uvx ruff@0.4.8 check --config "builtins=['_']" .  # lint (same pin as CI / upstream noxfile)
uvx ruff@0.4.8 format .                           # format
uv run mypy PiFinder                              # type checking
uv run pytest -m smoke                            # smoke tests
uv run pytest -m unit                             # unit tests
uv run pytest -m integration tests/test_ui_modules.py  # UI module harness
```

CI (`.github/workflows/nox.yml` — keeps the upstream "nox" check name) runs
exactly these commands.

NixOS dev-box note: manylinux wheels (numpy etc.) need `libstdc++`; if imports
fail with `libstdc++.so.6: cannot open shared object file`, run tests with
`LD_LIBRARY_PATH=$(nix build --print-out-paths nixpkgs#stdenv.cc.cc.lib)/lib`.

**Running the application:**

First start the `cedar-detect-server` which is in `bin` (you need to use `-p 50551`, when invoking it).
Use the correct architecture suffix for cedar-detect-server according to the platform you're running on.

```bash
cd python/
uv run python -m PiFinder.main [options]
```
Usual startup:

```bash
uv run python -m PiFinder.main -fh --camera debug --keyboard local -x
```

## Reference Documentation

Before working in an area of the codebase, check whether it has reference docs:

- **`CONTEXT-MAP.md`** (repo root) — index of bounded contexts and how they relate. Start here for any cross-context question.
- **`docs/ax/<area>/CONTEXT.md`** — canonical glossary for each context (Catalog, Positioning, SQM…). These define the project's vocabulary: what each domain term means, which words to avoid, and how related concepts compose. **Use these terms when reading, writing, and discussing code.**
- **`docs/ax/<area>.md`** — architecture deep-dives (data flow, lifecycle, gotchas) alongside each CONTEXT.md.
- **`docs/adr/NNNN-*.md`** — short architecture-decision records capturing the *why* behind non-obvious or hard-to-reverse choices.

When a `CONTEXT.md` defines a term, prefer that term over synonyms in code comments, commit messages, and PR descriptions. If you encounter language in code or chat that conflicts with a CONTEXT.md, flag it.

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
- Selenium Grid server at localhost:4444 (configurable via SELENIUM_GRID_URL environment variable). 
  This server is started outside of the test code, for maximum flexibility
- Chrome browser in headless mode for test execution
- Tests automatically skip if Selenium Grid is unavailable

**Test Coverage Areas:**
- **Web Interface** (`test_web_interface.py`): Basic page loading, image display, status table elements (Mode, coordinates, software version)
- **Location Management** (`test_web_locations.py`): Location CRUD operations, DMS coordinate entry, default switching, GPS integration via remote interface
- **Network Configuration** (`test_web_network.py`): WiFi settings form validation, network management, restart flows, modal dialogs
- **Remote Control** (`test_web_remote.py`): Authentication, virtual keypad, menu navigation, marking menus, API endpoint validation
- **Equipment Management** (`test_web_equipment.py`): Telescope and eyepiece CRUD operations, active equipment selection, form validation
- **Observation Tracking** (`test_web_observations.py`): Session list display, observation counters, detail pages, TSV export functionality

**Authentication:** All protected pages use default password "solveit"

**Responsive Testing:** Tests run on both desktop (1920x1080) and mobile (375x667) viewports

**API Integration:** Extensive use of `/api/current-selection` endpoint to validate UI state changes and ensure web interface accurately reflects PiFinder's internal state

**Helper Utilities:** Shared utilities in `web_test_utils.py` for login flows, key simulation, and state validation with recursive dictionary comparison

## Code Quality

- **Linting:** Ruff with Python 3.9 target, Black-compatible formatting
- **Type Checking:** MyPy with gradual typing adoption
- **Code Style:** 88-character line length, double quotes, space indentation
- **Comments:** describe what the code does now, not how it changed. No "previously / no longer / used to / moved from" — history lives in git/jj, not in comments.
- **I18n Support:** Babel integration for multi-language UI

The codebase follows modern Python practices with type hints, comprehensive testing, and automated code quality checks integrated into the development workflow.

## NixOS Development

**CRITICAL: Never run `nix build` or `nix eval` on Pi 4 targets.** The Pi 4 lacks sufficient resources and will hang/crash. Always build on pi5.local (GitHub Actions runner), push to Attic, then trigger the upgrade service:
```bash
# Build on pi5
ssh pi5.local 'nix build --no-link --print-out-paths github:mrosseel/PiFinder/nixos#nixosConfigurations.pifinder.config.system.build.toplevel'
# Push to Attic (so Pi can download signed paths)
ssh pi5.local 'attic push pifinder:pifinder <store-path>'
# Trigger upgrade on target Pi (downloads from Attic, activates, reboots)
ssh pifinder@<target-ip> 'echo "<store-path>" > /run/pifinder/upgrade-ref && sudo systemctl start --no-block pifinder-upgrade.service'
# Monitor progress
ssh pifinder@<target-ip> 'cat /run/pifinder/upgrade-status'
```

**Netboot deployment (dev Pi on proxnix NFS):**
```bash
./deploy-image-to-nfs.sh    # Build and deploy to NFS
```

**Power control (Shelly plug via Home Assistant):**
```bash
~/.local/bin/pifinder-power-off.sh   # Turn off PiFinder
~/.local/bin/pifinder-power-on.sh    # Turn on PiFinder
```

**Check Pi status:**
```bash
ssh pifinder@192.168.5.146           # SSH to netboot Pi
systemctl status pifinder            # Check service status
journalctl -u pifinder -f            # Follow service logs
```
