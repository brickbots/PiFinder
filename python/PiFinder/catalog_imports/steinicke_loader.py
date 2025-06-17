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



# Map Steinicke object types to PiFinder types
STEINICKE_TYPE_MAPPING = {
    # Stars and asterisms
    "*": "*",  # Single star
    "*2": "D*",  # Double star
    "*3": "***",  # Triple star
    "*4": "***",  # Multiple star
    "*Cloud": "Nb",  # Star cloud
    "*Grp": "Ast",  # Star group/asterism
    # Galaxies - Basic Types
    "C": "Gx",  # Compact galaxy
    "D": "Gx",  # Dwarf galaxy
    "E": "Gx",  # Elliptical galaxy
    "I": "Gx",  # Irregular galaxy
    "P": "Gx",  # Peculiar galaxy
    "S": "Gx",  # Spiral galaxy
    # Galaxies - Detailed Types
    "E0": "Gx",  # E0 elliptical
    "E1": "Gx",  # E1 elliptical
    "E2": "Gx",  # E2 elliptical
    "E3": "Gx",  # E3 elliptical
    "E4": "Gx",  # E4 elliptical
    "E5": "Gx",  # E5 elliptical
    "E6": "Gx",  # E6 elliptical
    "E-S0": "Gx",  # E-S0 transition
    "S0": "Gx",  # S0 lenticular
    "Sa": "Gx",  # Sa spiral
    "Sab": "Gx",  # Sab spiral
    "Sb": "Gx",  # Sb spiral
    "Sbc": "Gx",  # Sbc spiral
    "Sc": "Gx",  # Sc spiral
    "Scd": "Gx",  # Scd spiral
    "Sd": "Gx",  # Sd spiral
    "Sdm": "Gx",  # Sdm spiral
    "Sm": "Gx",  # Sm spiral
    "SB": "Gx",  # Barred spiral
    "SBa": "Gx",  # SBa barred spiral
    "SBab": "Gx",  # SBab barred spiral
    "SBb": "Gx",  # SBb barred spiral
    "SBbc": "Gx",  # SBbc barred spiral
    "SBc": "Gx",  # SBc barred spiral
    "SBcd": "Gx",  # SBcd barred spiral
    "SBd": "Gx",  # SBd barred spiral
    "SBdm": "Gx",  # SBdm barred spiral
    "SBm": "Gx",  # SBm barred spiral
    "dE": "Gx",  # Dwarf elliptical
    "dI": "Gx",  # Dwarf irregular
    "cD": "Gx",  # cD galaxy
    # Special Galaxy Types
    "R": "Gx",  # Ring galaxy
    "PRG": "Gx",  # Polar ring galaxy
    "GxyP": "Gx",  # Part of galaxy (e.g. bright HII region)
    "Ring": "Gx",  # Ring galaxy
    "Ring A": "Gx",  # Ring galaxy type A
    "Ring B": "Gx",  # Ring galaxy type B
    "S R": "Gx",  # Ring spiral galaxy
    # Lenticular Galaxy Variants (Most Common Missing)
    "S0-a": "Gx",  # Lenticular galaxy subtype
    "SB0": "Gx",  # Barred lenticular galaxy
    "SB0-a": "Gx",  # Barred lenticular galaxy subtype
    "S0+": "Gx",  # Lenticular galaxy variant
    "SB0+": "Gx",  # Barred lenticular galaxy variant
    "S0?": "Gx",  # Uncertain lenticular galaxy
    "SB0?": "Gx",  # Uncertain barred lenticular galaxy
    "S0/P": "Gx",  # Peculiar lenticular galaxy
    "SB0/P": "Gx",  # Peculiar barred lenticular galaxy
    # Galaxy Types with Uncertainty Markers
    "S?": "Gx",  # Uncertain spiral galaxy
    "E?": "Gx",  # Uncertain elliptical galaxy
    "SB?": "Gx",  # Uncertain barred spiral
    "Sa?": "Gx",  # Uncertain Sa spiral
    "Sb?": "Gx",  # Uncertain Sb spiral
    "Sc?": "Gx",  # Uncertain Sc spiral
    "Sd?": "Gx",  # Uncertain Sd spiral
    "SBa?": "Gx",  # Uncertain SBa barred spiral
    "SBb?": "Gx",  # Uncertain SBb barred spiral
    "SBc?": "Gx",  # Uncertain SBc barred spiral
    "Irr?": "Gx",  # Uncertain irregular galaxy
    "I?": "Gx",  # Uncertain irregular galaxy
    # Transition Galaxy Types
    "E/SB0": "Gx",  # Transition between elliptical and barred lenticular
    "E/S0": "Gx",  # Transition between elliptical and lenticular
    "S0/Sa": "Gx",  # Transition between S0 and Sa
    "SB0/SBa": "Gx",  # Transition between SB0 and SBa
    # Irregular Galaxy Subtypes
    "IBm": "Gx",  # Irregular galaxy, Magellanic type
    "Im": "Gx",  # Irregular galaxy, Magellanic type (compact)
    "IAB": "Gx",  # Irregular galaxy type AB
    "IB": "Gx",  # Irregular galaxy type B
    "I0": "Gx",  # Irregular galaxy type 0
    # Peculiar Galaxy Designations
    "Sa/P": "Gx",  # Peculiar Sa spiral
    "Sb/P": "Gx",  # Peculiar Sb spiral
    "Sc/P": "Gx",  # Peculiar Sc spiral
    "SBa/P": "Gx",  # Peculiar SBa barred spiral
    "SBb/P": "Gx",  # Peculiar SBb barred spiral
    "SBc/P": "Gx",  # Peculiar SBc barred spiral
    "S/P": "Gx",  # Peculiar spiral galaxy
    "E/P": "Gx",  # Peculiar elliptical galaxy
    "I/P": "Gx",  # Peculiar irregular galaxy
    # Additional Galaxy Types
    "S ": "Gx",  # Spiral galaxy (with space)
    "Sc ": "Gx",  # Sc spiral (with trailing space)
    "dSph": "Gx",  # Dwarf spheroidal galaxy
    "BCD": "Gx",  # Blue compact dwarf galaxy
    "cG": "Gx",  # Compact galaxy
    "HII": "Gx",  # HII galaxy/region
    # Globular Cluster Classifications (Shapley-Sawyer)
    "II2p": "Gb",  # Globular cluster, concentration class II, pop. 2, peculiar
    "III2p": "Gb",  # Globular cluster, concentration class III, pop. 2, peculiar
    "II2m": "Gb",  # Globular cluster, concentration class II, pop. 2, metal-rich
    "III2m": "Gb",  # Globular cluster, concentration class III, pop. 2, metal-rich
    # "I": "Gb",     # Globular cluster, concentration class I
    "II": "Gb",  # Globular cluster, concentration class II
    "III": "Gb",  # Globular cluster, concentration class III
    "IV": "Gb",  # Globular cluster, concentration class IV
    "V": "Gb",  # Globular cluster, concentration class V
    "VI": "Gb",  # Globular cluster, concentration class VI
    "VII": "Gb",  # Globular cluster, concentration class VII
    "VIII": "Gb",  # Globular cluster, concentration class VIII
    "IX": "Gb",  # Globular cluster, concentration class IX
    "X": "Gb",  # Globular cluster, concentration class X
    "XI": "Gb",  # Globular cluster, concentration class XI
    "XII": "Gb",  # Globular cluster, concentration class XII
    "I2": "Gb",  # Globular cluster, concentration class I, pop. 2
    "II2": "Gb",  # Globular cluster, concentration class II, pop. 2
    "III2": "Gb",  # Globular cluster, concentration class III, pop. 2
    "IV2": "Gb",  # Globular cluster, concentration class IV, pop. 2
    "V2": "Gb",  # Globular cluster, concentration class V, pop. 2
    "VI2": "Gb",  # Globular cluster, concentration class VI, pop. 2
    # Clusters
    "OCL": "OC",  # Open cluster (no Trümpler class)
    "GCL": "Gb",  # Globular cluster (no concentration class)
    "3S": "OC",  # Small cluster
    "4S": "OC",  # Small cluster
    "5C": "OC",  # Compact cluster
    # "C": "OC",     # Cluster
    "C  M": "OC",  # Multiple cluster
    "C+*?": "OC",  # Cluster with stars
    "C+C": "OC",  # Multiple cluster
    "C+C+C": "OC",  # Multiple cluster
    "C/P": "OC",  # Cluster with nebulosity
    "CorG": "OC",  # Corona or Group
    # Nebulae
    "EN": "Nb",  # Emission nebula
    "RN": "Nb",  # Reflection nebula
    "PN": "PN",  # Planetary nebula
    "SNR": "Nb",  # Supernova remnant
    "DN": "DN",  # Dark nebula
    "HH": "Nb",  # Herbig-Haro object
    "Neb": "Nb",  # General nebula
    # Star Types
    "**": "D*",  # Double star (alternative notation)
    "WR": "*",  # Wolf-Rayet star
    "C*": "*",  # Carbon star
    "WD": "*",  # White dwarf
    "N*": "*",  # Nova
    # Combinations
    "C+N": "C+N",  # Cluster + Nebula
    "OCL+EN": "C+N",  # Open cluster + Emission nebula
    "PN+OCL": "C+N",  # Planetary nebula + Open cluster
    "RN+EN": "C+N",  # Reflection nebula + Emission nebula
    "RN+OCL": "C+N",  # Reflection nebula + Open cluster
    "EN+OCL": "C+N",  # Emission nebula + Open cluster
    "EN+RN": "C+N",  # Emission nebula + Reflection nebula
    "RN+*": "C+N",  # Reflection nebula + Star
    "EN+*": "C+N",  # Emission nebula + Star
    # Uncertain/Unknown
    "?": "?",  # Unknown object type
    "Unknown": "?",  # Unknown object type
    "NF": "?",  # Not found (301 objects)
    "P?": "?",  # Uncertain peculiar object
    "Nova": "*",  # Nova star
    "Ring/P": "Gx",  # Peculiar ring galaxy
    "D R": "Gx",  # Dwarf ring galaxy
    "RN4": "Nb",  # Reflection nebula type 4
    "RN2": "Nb",  # Reflection nebula type 2
    "*3+C": "***",  # Triple star + cluster
}


def preprocess_steinicke_type(obj_type):
    """
    Preprocess object type with regex to handle common patterns
    """
    if not obj_type:
        return "?"

    # Try exact match first
    if obj_type in STEINICKE_TYPE_MAPPING:
        return STEINICKE_TYPE_MAPPING[obj_type]

    # Only strip trailing spaces and + for unmapped types
    cleaned = re.sub(r"[+\s]+$", "", obj_type)  # Remove +, trailing spaces

    if cleaned in STEINICKE_TYPE_MAPPING:
        return STEINICKE_TYPE_MAPPING[cleaned]

    # For galaxy-like patterns not in mapping, default to Gx
    if re.match(r"^(S|E|I|dE|cD|BCD)", cleaned) and cleaned not in ["*", "SNR", "EN"]:
        return "Gx"

    return "?"


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

        # Step 2: Process XLS to JSON using steinicke_extractor
        sys.path.insert(0, str(steinicke_dir))
        try:
            from steinicke_extractor import process_xls_to_json  # type: ignore

            logging.info("Processing XLS file to extract catalog data...")
            output_json = steinicke_dir / "steinicke_catalog.json"
            num_objects = process_xls_to_json(str(xls_file), str(output_json))
            logging.info(f"Processed {num_objects} objects and saved to {output_json}")

        except ImportError as e:
            raise ImportError(f"Failed to import steinicke_extractor: {e}")
        finally:
            sys.path.remove(str(steinicke_dir))

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
                    logging.debug(
                        f"Selected {prefix}{number}{best_object.get('extension_letter') or best_object.get('component') or ''}, "
                        f"skipped {len(skipped)} other variants"
                    )

    logging.debug(f"Selected {len(selected_objects)} objects after deduplication")

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
        obj_type = preprocess_steinicke_type(steinicke_type)

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
            size = format_size_value(obj['diameter_larger'])
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
                            desc = object_id_desc_dict.get(f"{catalog}{ngc_ic_sequence}", "")
                            # logging.info(f"DEBUG: M{m_sequence} ({catalog}{ngc_ic_sequence}) description: '{desc[:50]}{'...' if len(desc) > 50 else ''}'")
                            objects_db.insert_catalog_object(
                                object_id, "M", m_sequence, desc
                            )
                            seen.add(m_sequence)
                    else:
                        logging.error(f"Can't find object id {catalog=}, {ngc_ic_sequence=}")

    # Commit changes and update sequence counters
    conn.commit()
    insert_catalog_max_sequence("NGC")
    insert_catalog_max_sequence("IC")
    insert_catalog_max_sequence("M")

    logging.info("Catalog loading complete")
