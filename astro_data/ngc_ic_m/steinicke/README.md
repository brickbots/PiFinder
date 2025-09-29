# Steinicke Catalog Processing Tools

This directory contains Python utilities for processing the Steinicke catalog data into formats usable by PiFinder's catalog import system.

## Processing Scripts

### `steinicke_extractor.py`
Processes the main Steinicke Excel file into structured JSON format.

**Features:**
- Reads `NI2023.xls` and converts to `AstronomicalObject` dataclass instances
- Handles all catalog fields: coordinates, magnitudes, object types, distances, cross-references
- Exports to JSON for database import via `python/PiFinder/catalog_imports/`
- Includes data validation and error handling for malformed entries

**Usage:**
```bash
python steinicke_extractor.py
# Processes NI2023.xls → steinicke_catalog.json
```

### `description_extractor.py`
Extracts Dreyer's original object descriptions from NGC2000 format files.

**Purpose:**
- Supplements Steinicke data with historical object descriptions
- Processes fixed-width format catalog files with descriptions starting at column 47
- Creates lookup dictionaries for NGC/IC numbers to description text
- Supports multiple export formats (Python, JSON, CSV)

**Input Sources:**
- `../ngc2000/ngc2000.dat` - Main data with embedded descriptions
- Uses Dreyer's original 1880s notation (abbreviations defined in `../ngc2000/ngc.desc`)

**Usage:**
```bash
python description_extractor.py ../ngc2000/ngc2000.dat --format json
python description_extractor.py ../ngc2000/ngc2000.dat --output descriptions.py
```

## Data Processing Pipeline

1. **Steinicke Processing**: `steinicke_extractor.py` creates the primary object database
2. **Description Enhancement**: `description_extractor.py` extracts supplemental descriptions
3. **Database Integration**: Output files are consumed by `python/PiFinder/catalog_imports/steinicke_loader.py`

## Technical Implementation

Both scripts use robust error handling to process incomplete catalog entries and provide detailed logging of processing statistics. The `AstronomicalObject` dataclass provides a clean interface for astronomical data with proper type hints and validation.

**Key Classes:**
- `AstronomicalObject` - Structured representation of catalog entries
- `AstronomyCatalog` - Collection management with filtering capabilities