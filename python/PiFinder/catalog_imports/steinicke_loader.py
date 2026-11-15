"""
Steinicke NGC/IC catalog loader for PiFinder.

This module loads NGC, IC, and Messier catalogs from the Steinicke JSON data.
"""

import json
import math
import re
import logging
import zipfile
import tempfile
import sys
from pathlib import Path
from tqdm import tqdm
from collections import defaultdict

import PiFinder.utils as utils
from PiFinder.composite_object import MagnitudeObject, SizeObject
from .catalog_import_utils import (
    NewCatalogObject,
    delete_catalog_from_database,
    insert_catalog,
    insert_catalog_max_sequence,
)

# Import shared database object
from .database import objects_db
from .post_processing import title_case


# Basic object type mappings for exact matches
BASIC_TYPE_MAPPING = {
    # Stars and asterisms
    "*": "*",
    "*2": "D*",
    "*3": "***",
    "*4": "***",
    "**": "D*",
    # A Milky Way star cloud is a rich star field, not a nebula; post_processing
    # types M 24 the same way.
    "*Cloud": "Ast",
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
    # A planetary seen inside a cluster (NGC 2818 in NGC 2818A) is the
    # planetary: Steinicke's status 3.
    "PN+OCL": "PN",
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

    # Globular-cluster disambiguation MUST run before the galaxy check.
    # For a globular, Steinicke's TYPE is the Shapley-Sawyer concentration
    # class -- a Roman numeral such as "I" -- which is_galaxy_type() would
    # otherwise read as an Irregular galaxy. A "GCL"/globular cross-ID in the
    # remarks (the ID1-ID11 fields) confirms the object really is a globular,
    # so when both hold we map to "Gb". Without this ordering, globulars like
    # NGC 7006, NGC 2808, NGC 5824, NGC 5834 and NGC 6864 (M 75) are
    # mis-typed as galaxies. The is_trumpler_class() guard keeps objects that
    # merely mention a globular in their remarks (e.g. IC 4802, a star group
    # *inside* a globular) from being reclassified.
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

    # Galaxy type patterns (most common in Steinicke)
    if is_galaxy_type(cleaned):
        return "Gx"

    # Trumpler class patterns for open clusters. A trailing "n" is the
    # Trumpler flag for nebulosity in the cluster ("III3pn": IC 1805, M 16).
    if is_trumpler_class(cleaned):
        return "C+N" if cleaned.endswith("n") else "OC"

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


# Steinicke's status field S: what the identification of an NGC/IC number
# found (NI2023, Table 2). It says what an object is more reliably than its
# TYPE, which mixes Hubble types, Trumpler classes and concentration classes.
STATUS_GALAXY = 1
STATUS_NEBULA = 2
STATUS_PLANETARY = 3
STATUS_OPEN_CLUSTER = 4
STATUS_GLOBULAR = 5
STATUS_PART_OF_GALAXY = 6
STATUS_DUPLICATE = 7  # another number in the same catalog (NGC 6 = NGC 20)
STATUS_DUPLICATE_OF_NGC = 8  # an IC number that is already an NGC object
STATUS_STARS = 9
STATUS_NOT_FOUND = 10

DUPLICATE_STATUSES = (STATUS_DUPLICATE, STATUS_DUPLICATE_OF_NGC)

# The status alone decides these types.
STATUS_TYPES = {
    STATUS_GALAXY: "Gx",
    STATUS_PLANETARY: "PN",
    STATUS_GLOBULAR: "Gb",
    STATUS_NOT_FOUND: "?",
}

# Leads the description of a not-found object, ahead of Dreyer's text.
NOT_FOUND_DESCRIPTION = "Not found: nothing at Dreyer's position (Steinicke)."

# Steinicke places a duplicate at its twin's position. A duplicate row further
# than this from its twin carries values of its own, so the source contradicts
# itself and the row stays a sky object of its own.
DUPLICATE_MAX_SEPARATION_ARCMIN = 1.0

_HII_REGION = re.compile(r"\bHII\b")
_CLUSTER_OR_ASSOCIATION = re.compile(r"\b(?:OCL|SCL)\b|\*Cloud|associat", re.IGNORECASE)
_DESIGNATION = re.compile(r"^(NGC|IC|M)\s*(\d+)\s*([A-Z]?)(?:-(\d+))?$")


def steinicke_status(obj):
    """A Steinicke row's status S as an int, or None when it has none."""
    status = obj.get("status")
    try:
        return int(status)
    except (TypeError, ValueError):
        return None


def _remark(remarks):
    """
    The remark of a Steinicke row: its last non-empty ID field, where
    Steinicke puts the remark when there is one.
    """
    if isinstance(remarks, list):
        filled = [str(r) for r in remarks if r]
        return filled[-1] if filled else ""
    return str(remarks) if remarks else ""


def part_of_galaxy_type(obj_type, remarks=""):
    """
    Type a part of another galaxy (status 6) by its remark: an HII region is a
    nebula, a cluster, star cloud or association is a cluster (PiFinder has no
    association type), and any other part of a galaxy is not a galaxy of its
    own, so it is typed unknown.
    """
    remark = _remark(remarks)
    if _HII_REGION.search(remark):
        return "Nb"
    if _CLUSTER_OR_ASSOCIATION.search(remark):
        return "OC"
    if (obj_type or "").strip() == "GxyP":
        return "?"
    return preprocess_steinicke_type(obj_type, remarks)


def steinicke_object_type(status, obj_type, remarks=""):
    """
    Map a Steinicke row to a PiFinder type by its status first, then by its
    TYPE. A duplicate (status 7 or 8) is typed by its TYPE: it only needs a
    type of its own when its twin cannot be found.
    """
    if status in STATUS_TYPES:
        return STATUS_TYPES[status]
    if status == STATUS_PART_OF_GALAXY:
        return part_of_galaxy_type(obj_type, remarks)
    if status == STATUS_OPEN_CLUSTER and (obj_type or "").strip() == "*Grp":
        # A star group Steinicke identifies as a cluster (NGC 6885)
        return "OC"
    return preprocess_steinicke_type(obj_type, remarks)


def steinicke_radec(obj):
    """A Steinicke row's J2000 position in decimal degrees (0, 0 if none)."""
    if not (obj.get("right_ascension") and obj.get("declination")):
        return 0.0, 0.0
    ra_dict = obj["right_ascension"]
    ra = (
        ra_dict.get("hours", 0)
        + ra_dict.get("minutes", 0) / 60
        + ra_dict.get("seconds", 0) / 3600
    ) * 15
    dec_dict = obj["declination"]
    dec = (
        dec_dict.get("degrees", 0)
        + dec_dict.get("minutes", 0) / 60
        + dec_dict.get("seconds", 0) / 3600
    )
    if dec_dict.get("sign", 1) < 0:
        dec = -dec
    return ra, dec


def _separation_arcmin(obj_a, obj_b):
    ra1, dec1, ra2, dec2 = map(
        math.radians, (*steinicke_radec(obj_a), *steinicke_radec(obj_b))
    )
    cos_sep = math.sin(dec1) * math.sin(dec2) + math.cos(dec1) * math.cos(
        dec2
    ) * math.cos(ra1 - ra2)
    return math.degrees(math.acos(max(-1.0, min(1.0, cos_sep)))) * 60


def _designation(key):
    prefix, number = key
    return f"{'NGC' if prefix == 'N' else 'IC'} {number}"


def _is_duplicate(obj):
    return steinicke_status(obj) in DUPLICATE_STATUSES


def resolve_duplicate_twins(selected):
    """
    Find the twin of every duplicate (status 7 or 8) among the selected rows,
    by Steinicke's own identification.

    ``selected`` maps (catalogue_prefix, catalogue_number) to the one row the
    loader keeps for that number. Steinicke names a duplicate's twin in its
    first ID field: an NGC or IC number, possibly with an extension letter or
    component ("NGC 3280A", "NGC 1040-1"), or a Messier number. A twin that is
    itself a duplicate is followed to the row it names (IC 249 -> NGC 961 ->
    NGC 1051). Duplicates that name each other (IC 5179, IC 5183) take the
    first non-duplicate any of them names (IC 5184).

    Returns ``{duplicate key: twin key}`` for each duplicate whose twin is a
    non-duplicate row within DUPLICATE_MAX_SEPARATION_ARCMIN. Every other
    duplicate is logged and left out, so it stays a sky object of its own.
    """
    # "M 76" names the one non-duplicate row that lists it (NGC 650)
    messier_rows = defaultdict(list)
    for key, obj in selected.items():
        if _is_duplicate(obj):
            continue
        for remark in obj.get("remarks") or []:
            match = re.match(r"^M\s*(\d+)$", str(remark))
            if match:
                messier_rows[int(match.group(1))].append(key)

    def named_row(identification):
        """The selected row an identification names, or None."""
        match = _DESIGNATION.match(str(identification or "").strip())
        if not match:
            return None
        catalog, number, letter, component = match.groups()
        if catalog == "M":
            rows = messier_rows.get(int(number), [])
            return rows[0] if len(rows) == 1 else None
        key = ("N" if catalog == "NGC" else "I", int(number))
        row = selected.get(key)
        if row is None:
            return None
        # A lettered twin or component is only the loader's sky object for
        # that number if it is the row the loader kept ("NGC 4676B" is not).
        if letter and row.get("extension_letter") != letter:
            return None
        if component and row.get("component") != int(component):
            return None
        return key

    def first_identification(key):
        remarks = selected[key].get("remarks") or []
        return remarks[0] if remarks else None

    def cycle_exit(cycle):
        """The first non-duplicate row any member of a cycle names."""
        for member in cycle:
            for remark in selected[member].get("remarks") or []:
                named = named_row(remark)
                if named is not None and not _is_duplicate(selected[named]):
                    return named
        return None

    twins = {}
    for key, obj in selected.items():
        if not _is_duplicate(obj):
            continue
        chain = [key]
        twin = named_row(first_identification(key))
        while twin is not None and _is_duplicate(selected[twin]):
            if twin in chain:
                twin = cycle_exit(chain)
                break
            chain.append(twin)
            twin = named_row(first_identification(twin))

        if twin is None:
            logging.warning(
                f"Steinicke duplicate {_designation(key)}: no sky object for "
                f"its twin {first_identification(key)!r}, so it stays its own"
            )
            continue
        separation = _separation_arcmin(obj, selected[twin])
        if separation > DUPLICATE_MAX_SEPARATION_ARCMIN:
            logging.warning(
                f"Steinicke duplicate {_designation(key)} is {separation:.1f}' "
                f"from its twin {_designation(twin)}, so it stays its own"
            )
            continue
        twins[key] = twin
    return twins


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


def select_listings(data):
    """
    The one Steinicke row the loader keeps for each NGC and IC number, keyed
    by (catalogue_prefix, catalogue_number): the main row, else its extension
    letter A or component 1. Other letters and components are not loaded.
    """
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
    return {
        (obj["catalogue_prefix"], obj["catalogue_number"]): obj
        for obj in selected_objects
    }


def steinicke_description(obj, dreyer_description=""):
    """
    A listing's description: Dreyer's text (from NGC 2000.0) and Steinicke's
    redshift distance and surface brightness. A not-found object's leads with
    NOT_FOUND_DESCRIPTION, so nobody hunts an empty field.
    """
    desc = dreyer_description or ""
    extra = ""
    rs = obj.get("redshift_distance")
    if rs:
        extra += f"D(z)={rs:.1f} Mpc"
    sb = obj.get("surface_brightness")
    if sb:
        extra += f"{',' if rs else ''}SB={sb} mag/arcmin²"
    if (rs or sb) and desc:
        desc += "\n" + extra
    if steinicke_status(obj) == STATUS_NOT_FOUND:
        desc = f"{NOT_FOUND_DESCRIPTION}\n{desc}" if desc else NOT_FOUND_DESCRIPTION
    return desc


def prepare_steinicke_object(obj, dreyer_description=""):
    """The NewCatalogObject for one selected Steinicke row."""
    catalog = "NGC" if obj.get("catalogue_prefix") == "N" else "IC"
    obj_type = steinicke_object_type(
        steinicke_status(obj),
        (obj.get("object_type") or "").strip(),
        obj.get("remarks") or "",
    )
    ra, dec = steinicke_radec(obj)

    mag_value = obj.get("visual_magnitude")
    if mag_value is None:
        mag = MagnitudeObject([])
    else:
        mag = MagnitudeObject([float(mag_value)])

    # Format size information (arcminutes from Steinicke)
    pa = float(obj["position_angle"]) if obj.get("position_angle") else 0.0
    if obj.get("diameter_larger"):
        larger = float(obj["diameter_larger"])
        if obj.get("diameter_smaller"):
            size = SizeObject.from_arcmin(
                larger, float(obj["diameter_smaller"]), position_angle=pa
            )
        else:
            size = SizeObject.from_arcmin(larger, position_angle=pa)
    else:
        size = SizeObject([])

    return NewCatalogObject(
        object_type=obj_type,
        catalog_code=catalog,
        sequence=obj.get("catalogue_number"),
        ra=ra,
        dec=dec,
        mag=mag,
        size=size,
        description=steinicke_description(obj, dreyer_description),
        surface_brightness=obj.get("surface_brightness"),
    )


def insert_steinicke_objects(prepared, twins):
    """
    Insert the prepared listings. Each one mints its sky object, except a
    duplicate in ``twins``, whose listing joins its twin's sky object: the
    twins go in first, so every duplicate finds its twin's object_id.
    """
    for key, new_object in prepared.items():
        if key not in twins:
            new_object.insert()
    for key, twin in twins.items():
        new_object = prepared[key]
        new_object.object_id = prepared[twin].object_id
        new_object.insert(find_object_id=False)


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

    # First pass: select the best row for each catalogue number
    selected = select_listings(data)

    # Prepare all objects for batch insertion
    logging.info("Preparing objects for batch insertion...")
    descriptions = {"N": ngc_dict, "I": ic_dict}
    prepared = {
        key: prepare_steinicke_object(obj, descriptions[key[0]].get(key[1]) or "")
        for key, obj in tqdm(selected.items(), desc="Preparing objects", leave=False)
    }
    twins = resolve_duplicate_twins(selected)
    logging.info(
        f"Attaching {len(twins)} Steinicke duplicates to their twins' sky objects"
    )

    # Batch insert all objects in single transaction
    logging.info(f"Batch inserting {len(prepared)} objects...")
    objects_db.bulk_mode = True

    # Create shared finder before bulk operations to avoid database conflicts
    from .catalog_import_utils import ObjectFinder

    shared_finder = ObjectFinder()
    NewCatalogObject.set_shared_finder(shared_finder)

    try:
        insert_steinicke_objects(prepared, twins)
        for obj in prepared.values():
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
                else:
                    # NGC 2000.0's names are mostly lower case after the first
                    # word ("Crab nebula").
                    common_name = title_case(common_name)
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
