"""
Steinicke NGC/IC catalog loader for PiFinder.

This module loads NGC, IC, and Messier catalogs from the Steinicke JSON data.
"""

import json
import re
import logging
import zipfile
import tempfile
import sys
from pathlib import Path
from tqdm import tqdm
from collections import defaultdict

import PiFinder.utils as utils
from PiFinder.utils import format_size_value
from PiFinder.composite_object import MagnitudeObject
from .catalog_import_utils import (
    NewCatalogObject,
    delete_catalog_from_database,
    insert_catalog,
    insert_catalog_max_sequence,
)

# Import shared database object
from .database import objects_db

logger = logging.getLogger("SteinickeLoader")

# Basic object type mappings for exact matches
BASIC_TYPE_MAPPING = {
    # Stars and asterisms
    "*": "*",
    "*2": "D*",
    "*3": "***",
    "*4": "***",
    "**": "D*",
    "*Cloud": "Nb",
    "*Grp": "Ast",
    # Basic clusters
    "OCL": "OC",
    "GCL": "Gb",
    # Nebulae
    "EN": "Nb",
    "RN": "Nb",
    "PN": "PN",
    "SNR": "Nb",
    "DN": "DN",
    # Special objects
    "Nova": "*",
    "NF": "?",
    "GxyP": "Gx",
    "PRG": "Gx",
    # Combinations
    "OCL+EN": "C+N",
    "EN+OCL": "C+N",
    "PN+OCL": "C+N",
    "RN+EN": "Nb",
    "RN+OCL": "C+N",
    "EN+RN": "Nb",
    "RN+*": "C+N",
    "EN+*": "C+N",
}


def preprocess_steinicke_type(obj_type, remarks=""):
    """
    Map Steinicke object types to PiFinder types using pattern matching
    """
    if not obj_type:
        return "?"

    # Clean the type string
    cleaned = obj_type.strip()

    # Try exact match first
    if cleaned in BASIC_TYPE_MAPPING:
        return BASIC_TYPE_MAPPING[cleaned]

    # Handle combinations with + or multiple object indicators
    if "+" in cleaned:
        # Split and check individual components
        parts = [p.strip() for p in cleaned.split("+")]
        if len(parts) == 2:
            # Check for common combinations
            if any(p in ["OCL", "EN", "RN", "PN"] for p in parts):
                return "C+N"
            # Multiple galaxies or stars
            if all(is_galaxy_type(p) for p in parts):
                return "Gx"
            if all(is_star_type(p) for p in parts):
                return "***"

    # Galaxy type patterns (most common in Steinicke)
    if is_galaxy_type(cleaned):
        return "Gx"

    # Check for globular cluster indicators in remarks before Trumpler class check
    remarks_str = ""
    if isinstance(remarks, list):
        remarks_str = " ".join(str(r) for r in remarks if r)
    elif remarks:
        remarks_str = str(remarks)

    if remarks_str and ("GCL" in remarks_str or "globular" in remarks_str.lower()):
        if is_trumpler_class(
            cleaned
        ):  # Roman numerals that could be globular concentration classes
            return "Gb"

    # Trumpler class patterns for open clusters
    if is_trumpler_class(cleaned):
        return "OC"

    # Star patterns
    if is_star_type(cleaned):
        return "*"

    # Handle special suffixes and extra whitespace
    base_type = re.sub(
        r"[\s?/]+[PRMB]*[\s]*$", "", cleaned
    )  # Remove suffixes and trailing whitespace
    if base_type != cleaned:
        return preprocess_steinicke_type(base_type, remarks)

    return "?"


def is_galaxy_type(obj_type):
    """Check if object type represents a galaxy"""
    if not obj_type:
        return False

    # Basic galaxy types
    if obj_type in ["C", "D", "E", "I", "P", "S", "Irr", "dE", "dI", "cD", "Ring"]:
        return True

    # Hubble classification patterns
    patterns = [
        r"^E[0-6]?$",  # E, E0-E6
        r"^E-S0$",  # E-S0 transition
        r"^E/S[B0]+$",  # E/S0, E/SB0 transitions
        r"^S0(-a)?$",  # S0, S0-a
        r"^S[abc]?[bcd]?[dm]?$",  # Sa, Sb, Sc, Sab, Sbc, Scd, Sd, Sdm, Sm
        r"^SB[0abc]?[bcd]?[dm]?(-a)?$",  # SB0, SBa, SBb, SBc, SBab, SBbc, SBcd, SBd, SBdm, SBm, SB0-a
        r"^I[AB]?[bm]?$",  # I, IA, IB, IBm, Im
        r"^dE[0-6]?$",  # dE, dE0-dE6 (dwarf elliptical)
        r"^Ring\s*[AB]?$",  # Ring, Ring A, Ring B
        r"^[SE].*\s+[RM]$",  # Types with R (ring) or M suffix
        r"^.*\s+R$",  # Any type with R suffix (ring)
        r"^[ESI].*\s+pec$",  # Peculiar galaxies (Sa pec, etc.)
    ]

    for pattern in patterns:
        if re.match(pattern, obj_type):
            return True

    return False


def is_trumpler_class(obj_type):
    """Check if object type represents a Trumpler open cluster classification"""
    if not obj_type:
        return False

    # Trumpler classes: I, II, III, IV followed by 1-3, then p/m/r, then n
    # Examples: II1p, III2m, IV3pn, I2r, etc.
    pattern = r"^[IVX]+[1-3]?[pmr]?n?$"
    return bool(re.match(pattern, obj_type))


def is_star_type(obj_type):
    """Check if object type represents a star"""
    if not obj_type:
        return False

    # Various star type patterns
    star_patterns = [
        r"^\*[2-9]?$",  # *, *2, *3, etc.
        r"^\d+S$",  # 3S, 4S, 5S (small star groups)
        r"^[NWDC]\*?$",  # N*, W*, D*, C*
        r"^Nova$",  # Nova
    ]

    for pattern in star_patterns:
        if re.match(pattern, obj_type):
            return True

    return False


def _check_required_files() -> bool:
    """
    Check if the required processed JSON files exist.

    Returns:
        bool: True if both required JSON files exist, False otherwise
    """
    steinicke_json = utils.astro_data_dir / "ngc_ic_m/steinicke/steinicke_catalog.json"
    descriptions_json = (
        utils.astro_data_dir / "ngc_ic_m/steinicke/ngc2000_descriptions.json"
    )

    return steinicke_json.exists() and descriptions_json.exists()


def _extract_and_process_data():
    """
    Extract ZIP file and process XLS to generate required JSON files.

    This function:
    1. Extracts the steinicke_catalog_source.zip to get the XLS file
    2. Processes the XLS file to generate steinicke_catalog.json
    3. Processes NGC2000 data to generate ngc2000_descriptions.json
    4. Cleans up temporary files
    """
    steinicke_dir = utils.astro_data_dir / "ngc_ic_m/steinicke"
    source_zip = steinicke_dir / "steinicke_catalog_source.zip"

    if not source_zip.exists():
        raise FileNotFoundError(f"Source ZIP file not found: {source_zip}")

    logging.info("Extracting and processing Steinicke catalog data...")

    # Create temporary directory for extraction
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # Step 1: Extract ZIP file
        logging.info(f"Extracting {source_zip}")
        with zipfile.ZipFile(source_zip, "r") as zip_ref:
            zip_ref.extractall(temp_path)

        # Find the extracted XLS file
        xls_files = list(temp_path.glob("*.xls"))
        if not xls_files:
            raise FileNotFoundError("No XLS file found in extracted ZIP")

        if len(xls_files) > 1:
            logging.warning(f"Multiple XLS files found, using: {xls_files[0]}")

        xls_file = xls_files[0]
        logging.info(f"Found XLS file: {xls_file}")

        # Step 2: Process XLS to JSON
        logging.info("Processing XLS file to extract catalog data...")
        output_json = steinicke_dir / "steinicke_catalog.json"

        # Import and use the actual extractor
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "steinicke_extractor", steinicke_dir / "steinicke_extractor.py"
        )
        steinicke_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(steinicke_module)

        num_objects = steinicke_module.process_xls_to_json(
            str(xls_file), str(output_json)
        )
        logging.info(f"Extracted Excel data with {num_objects} rows to {output_json}")

        # Step 3: Process NGC2000 descriptions
        _process_ngc2000_descriptions()

    logging.info("Data extraction and processing complete")


def _process_ngc2000_descriptions():
    """
    Process NGC2000 data to generate descriptions JSON file.
    """
    steinicke_dir = utils.astro_data_dir / "ngc_ic_m/steinicke"
    ngc2000_dir = utils.astro_data_dir / "ngc_ic_m/ngc2000"
    ngc2000_file = ngc2000_dir / "ngc2000.dat"

    if not ngc2000_file.exists():
        logging.warning(f"NGC2000 data file not found: {ngc2000_file}")
        # Create empty descriptions file
        empty_descriptions = {"ngc": {}, "ic": {}}
        descriptions_json = steinicke_dir / "ngc2000_descriptions.json"
        with open(descriptions_json, "w", encoding="utf-8") as f:
            json.dump(empty_descriptions, f, indent=2)
        return

    sys.path.insert(0, str(steinicke_dir))
    try:
        from description_extractor import process_ngc2000_to_json  # type: ignore

        logging.info("Processing NGC2000 descriptions...")
        descriptions_json = steinicke_dir / "ngc2000_descriptions.json"
        ngc_count, ic_count = process_ngc2000_to_json(
            str(ngc2000_file), str(descriptions_json)
        )
        logging.info(
            f"Processed {ngc_count} NGC and {ic_count} IC descriptions, saved to {descriptions_json}"
        )

    except ImportError as e:
        raise ImportError(f"Failed to import description_extractor: {e}")
    finally:
        sys.path.remove(str(steinicke_dir))


def load_ngc_catalog():
    """
    Load NGC, IC, and Messier catalogs with automated data extraction.

    This function first checks if the required JSON files exist. If not, it automatically
    extracts the ZIP file and processes the data to generate the required files.
    Then it loads the catalog data using existing infrastructure methods.
    """
    # Check if required files exist, extract and process if not
    if not _check_required_files():
        logging.info("Required JSON files not found, extracting and processing data...")
        _extract_and_process_data()

    # Load JSON data
    data_path = Path(utils.astro_data_dir, "ngc_ic_m/steinicke/steinicke_catalog.json")
    logging.info(f"Loading catalog data from {data_path}")

    with open(data_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Load descriptions
    with open(
        utils.astro_data_dir / "ngc_ic_m/steinicke/ngc2000_descriptions.json", "r"
    ) as f:
        catalog_data = json.load(f)
    ngc_dict, ic_dict = (
        {int(k): v for k, v in catalog_data["ngc"].items()},
        {int(k): v for k, v in catalog_data["ic"].items()},
    )

    # Create dictionary to map between object IDs and descriptions
    object_id_desc_dict = {}

    # Delete existing catalog data
    delete_catalog_from_database("NGC")
    delete_catalog_from_database("IC")
    delete_catalog_from_database("M")

    # Insert catalog descriptions
    insert_catalog("NGC", Path(utils.astro_data_dir, "ngc_ic_m/ngc2000", "ngc.desc"))
    insert_catalog("IC", Path(utils.astro_data_dir, "ngc_ic_m/", "ic.desc"))
    insert_catalog("M", Path(utils.astro_data_dir, "ngc_ic_m/messier", "messier.desc"))

    conn, _db_c = objects_db.get_conn_cursor()

    # First pass: Group objects by catalogue number and select the best one from each group
    logging.info("Grouping objects by catalogue number...")
    object_groups = defaultdict(list)

    # Group all objects by (catalogue_prefix, catalogue_number) - filter early for performance
    for obj in data:
        prefix = obj.get("catalogue_prefix")
        number = obj.get("catalogue_number")
        if not prefix or not number or prefix not in ["N", "I"]:  # Early filtering
            continue

        key = (prefix, number)
        object_groups[key].append(obj)

    # Select the best object from each group
    selected_objects = []
    for key, objects in object_groups.items():
        prefix, number = key

        # Define priority for object selection:
        # 1. No extension_letter and no component (main object)
        # 2. extension_letter = 'A' or component = 1
        # 3. Skip everything else

        def get_priority(obj):
            letter = obj.get("extension_letter")
            component = obj.get("component")

            if letter is None and component is None:
                return 1  # Highest priority: main object
            elif letter == "A" or component == 1:
                return 2  # Second priority: A or 1 variants
            else:
                return 999  # Low priority: skip B/C/2/3/etc.

        # Sort objects by priority and select the best one
        objects.sort(key=get_priority)
        best_object = objects[0]

        # Only select if it's not a low-priority object
        if get_priority(best_object) < 999:
            selected_objects.append(best_object)
            if len(objects) > 1:
                skipped = [obj for obj in objects[1:] if get_priority(obj) < 999]
                if skipped:
                    logger.debug(
                        f"Selected {prefix}{number}{best_object.get('extension_letter') or best_object.get('component') or ''}, "
                        f"skipped {len(skipped)} other variants"
                    )

    logger.debug(f"Selected {len(selected_objects)} objects after deduplication")

    # Prepare all objects for batch insertion
    logging.info("Preparing objects for batch insertion...")
    prepared_objects = []
    object_id_desc_dict = {}

    for obj in tqdm(selected_objects, desc="Preparing objects", leave=False):
        # Get basic object properties
        prefix = obj.get("catalogue_prefix")
        sequence = obj.get("catalogue_number")

        # Determine catalog code
        if prefix == "N":
            catalog = "NGC"
        elif prefix == "I":
            catalog = "IC"
        else:
            continue

        # Extract object type and preprocess for mapping
        steinicke_type = obj.get("object_type", "").strip()
        remarks = obj.get("remarks", "")
        obj_type = preprocess_steinicke_type(steinicke_type, remarks)

        # Convert coordinates to decimal degrees
        ra, dec = 0.0, 0.0
        if obj.get("right_ascension") and obj.get("declination"):
            # Extract RA components
            ra_dict = obj["right_ascension"]
            rah = ra_dict.get("hours", 0)
            ram = ra_dict.get("minutes", 0)
            ras = ra_dict.get("seconds", 0)

            # Extract Dec components
            dec_dict = obj["declination"]
            des = "+" if dec_dict.get("sign", 1) > 0 else "-"
            ded = dec_dict.get("degrees", 0)
            dem = dec_dict.get("minutes", 0)
            des_sec = dec_dict.get("seconds", 0)

            # Convert to decimal degrees
            dec = ded + (dem / 60) + (des_sec / 3600)
            if des == "-":
                dec = dec * -1
            ra = (rah + (ram / 60) + (ras / 3600)) * 15

        # Get magnitude
        mag_value = obj.get("visual_magnitude")
        if mag_value is None:
            mag = MagnitudeObject([])
        else:
            mag = MagnitudeObject([float(mag_value)])

        # Get surface brightness
        surface_brightness = obj.get("surface_brightness")

        # Format size information
        size = ""
        if obj.get("diameter_larger"):
            size = format_size_value(obj["diameter_larger"])
            if obj.get("diameter_smaller"):
                size += f"x{format_size_value(obj['diameter_smaller'])}"

        desc = ""
        extra = ""
        # Get description from remarks
        if catalog == "NGC":
            desc = ngc_dict.get(sequence) or ""
        elif catalog == "IC":
            desc = ic_dict.get(sequence) or ""
        rs = obj.get("redshift_distance")
        if rs:
            extra += f"D(z)={rs:.1f} Mpc"
        sb = obj.get("surface_brightness")
        if sb:
            extra += f"{',' if rs else ''}SB={sb} mag/arcmin²"
        if (rs or sb) and desc:
            desc += "\n" + extra

        # Prepare object for batch insertion
        new_object = NewCatalogObject(
            object_type=obj_type,
            catalog_code=catalog,
            sequence=sequence,
            ra=ra,
            dec=dec,
            mag=mag,
            size=size,
            description=desc,
            surface_brightness=surface_brightness,
        )
        prepared_objects.append(new_object)

    # Batch insert all objects in single transaction
    logging.info(f"Batch inserting {len(prepared_objects)} objects...")
    objects_db.bulk_mode = True

    # Create shared finder before bulk operations to avoid database conflicts
    from .catalog_import_utils import ObjectFinder

    shared_finder = ObjectFinder()
    NewCatalogObject.set_shared_finder(shared_finder)

    try:
        for obj in tqdm(prepared_objects, desc="Inserting objects", leave=False):
            obj.insert()
            # Create mapping using catalog+sequence format for Messier lookup
            catalog_sequence_key = f"{obj.catalog_code}{obj.sequence}"
            object_id_desc_dict[catalog_sequence_key] = obj.description
        conn.commit()  # Single commit for all operations
    finally:
        objects_db.bulk_mode = False
        NewCatalogObject.clear_shared_finder()

    # Second pass: Process common names and Messier objects from names.dat
    logging.info("Processing common names and Messier objects from names.dat...")

    name_dat_files = [
        Path(utils.astro_data_dir, "ngc_ic_m", "ngc2000", "names.dat"),
    ]
    seen = set()
    for name_dat in tqdm(name_dat_files, desc="Processing name files"):
        with open(name_dat, "r") as names:
            for line in names:
                m_sequence = ""
                common_name = line[0:35].strip()
                if common_name.startswith("M "):
                    m_sequence = common_name[2:].strip()
                    common_name = "M" + m_sequence
                catalog = line[36:37]
                if catalog == " ":
                    catalog = "N"
                if catalog == "N":
                    catalog = "NGC"
                if catalog == "I":
                    catalog = "IC"

                ngc_ic_sequence = line[37:41].strip()

                if ngc_ic_sequence != "":
                    obj = objects_db.get_catalog_object_by_sequence(
                        catalog, ngc_ic_sequence
                    )
                    if obj:
                        object_id = obj["object_id"]
                        objects_db.insert_name(object_id, common_name, catalog)
                        if m_sequence != "" and m_sequence not in seen:
                            desc = object_id_desc_dict.get(
                                f"{catalog}{ngc_ic_sequence}", ""
                            )
                            # logging.info(f"DEBUG: M{m_sequence} ({catalog}{ngc_ic_sequence}) description: '{desc[:50]}{'...' if len(desc) > 50 else ''}'")
                            objects_db.insert_catalog_object(
                                object_id, "M", m_sequence, desc
                            )
                            seen.add(m_sequence)
                    else:
                        logging.error(
                            f"Can't find object id {catalog=}, {ngc_ic_sequence=}"
                        )

    # Commit changes and update sequence counters
    conn.commit()
    insert_catalog_max_sequence("NGC")
    insert_catalog_max_sequence("IC")
    insert_catalog_max_sequence("M")

    logging.info("Catalog loading complete")
