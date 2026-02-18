"""
Harris Globular Cluster catalog load script.

TODO:
    - Nothing yet

"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional
from tqdm import tqdm

import numpy as np
import numpy.typing as npt
import PiFinder.utils as utils
from PiFinder.composite_object import MagnitudeObject
from PiFinder.calc_utils import ra_to_deg, dec_to_deg
from .catalog_import_utils import (
    delete_catalog_from_database,
    insert_catalog,
    insert_catalog_max_sequence,
    NewCatalogObject,
    trim_string,
)

# Import shared database object
from .database import objects_db

# Set to True for verbose debug logging during development
# When False, only essential progress messages are logged
VERBOSE = False


def read_harris_catalog(file_path: Path) -> npt.NDArray:
    """
    Read Harris Globular Cluster catalog from fixed-width format file.

    Format per ReadMe:
    - Bytes 2-10: Cluster ID (NGC, Pal, AM, E, etc.)
    - Bytes 12-22: Common name (47 Tuc, omega Cen, M 3, etc.)
    - Bytes 24-25: RA hours
    - Bytes 27-28: RA minutes
    - Bytes 30-33: RA seconds (F4.1)
    - Byte 36: Dec sign
    - Bytes 37-38: Dec degrees
    - Bytes 40-41: Dec minutes
    - Bytes 43-44: Dec seconds
    - Bytes 47-52: Galactic longitude (F6.2)
    - Bytes 54-59: Galactic latitude (F6.2)
    - Bytes 61-65: Distance from Sun in kpc (F5.1)
    - Bytes 67-71: Distance from Galactic center in kpc (F5.1)
    - Bytes 73-77: X component in kpc (F5.1)
    - Bytes 79-83: Y component in kpc (F5.1)
    - Bytes 85-89: Z component in kpc (F5.1)
    - Bytes 110-114: Integrated V magnitude (F5.2)
    - Bytes 116-121: Absolute magnitude (F6.2)
    """
    # Define the column specifications (using 0-based indexing)
    col_specs = [
        (1, 10),  # ID (cluster identification)
        (11, 22),  # Name (common name)
        (23, 25),  # RA Hours
        (26, 28),  # RA Minutes
        (29, 33),  # RA Seconds (F4.1)
        (35, 36),  # Dec sign
        (36, 38),  # Dec Degrees
        (39, 41),  # Dec Minutes
        (42, 44),  # Dec Seconds
        (46, 52),  # Galactic Longitude (F6.2)
        (53, 59),  # Galactic Latitude (F6.2)
        (60, 65),  # Distance from Sun (kpc) (F5.1)
        (66, 71),  # Distance from Galactic Center (kpc) (F5.1)
        (72, 77),  # X Distance (kpc) (F5.1)
        (78, 83),  # Y Distance (kpc) (F5.1)
        (84, 89),  # Z Distance (kpc) (F5.1)
        (109, 114),  # Integrated V magnitude (Vt) (F5.2)
        (115, 121),  # Absolute visual magnitude (MVt) (F6.2)
        (201, 205),  # Core radius (Rc) (F4.2 arcmin)
        (206, 210),  # Half-mass radius (Rh) (F4.2 arcmin)
    ]

    # Define dtype for structured array
    dtype = [
        ("ID", "U10"),  # Cluster ID
        ("Name", "U12"),  # Common name
        ("RAh", "i4"),  # RA hours
        ("RAm", "i4"),  # RA minutes
        ("RAs", "f4"),  # RA seconds
        ("DE_sign", "U1"),  # Dec sign
        ("DEd", "i4"),  # Dec degrees
        ("DEm", "i4"),  # Dec minutes
        ("DEs", "i4"),  # Dec seconds
        ("GLON", "f4"),  # Galactic longitude
        ("GLAT", "f4"),  # Galactic latitude
        ("Rsun", "f4"),  # Distance from Sun
        ("Rgc", "f4"),  # Distance from Galactic center
        ("X", "f4"),  # X component
        ("Y", "f4"),  # Y component
        ("Z", "f4"),  # Z component
        ("Vt", "f4"),  # Integrated V magnitude
        ("MVt", "f4"),  # Absolute magnitude
        ("Rc", "f4"),  # Core radius (arcmin)
        ("Rh", "f4"),  # Half-mass radius (arcmin)
    ]

    def parse_line(line: str) -> tuple:
        return tuple(
            parse_field(line[start:end].strip(), field_dtype)
            for (start, end), (_, field_dtype) in zip(col_specs, dtype)
        )

    def parse_field(value: str, field_dtype: str) -> Any:
        value = value.strip()
        if field_dtype.startswith("U"):
            return value
        elif field_dtype == "i4":
            return int(value) if value and value != "." else 0
        elif field_dtype == "f4":
            try:
                return float(value) if value and value != "." else np.nan
            except ValueError:
                return np.nan

    data = []
    with open(file_path, "r") as file:
        for line_num, line in enumerate(file, start=1):
            parsed = parse_line(line)
            data.append(parsed)

            # Log first 3 entries in detail for verification
            if VERBOSE and line_num <= 3:
                logging.info(f"Line {line_num} parsed:")
                logging.info(f"  ID: '{parsed[0]}', Name: '{parsed[1]}'")
                logging.info(f"  RA: {parsed[2]}h {parsed[3]}m {parsed[4]}s")
                logging.info(
                    f"  Dec: {parsed[5]}{parsed[6]}° {parsed[7]}' {parsed[8]}\""
                )
                logging.info(f"  Vt mag: {parsed[16]}, MVt: {parsed[17]}")

    logging.info(f"Read {len(data)} lines from Harris catalog")
    return np.array(data, dtype=dtype)


def is_valid_value(val: Any) -> bool:
    """Check if a numeric value is valid (not NaN, not empty)"""
    if val is None:
        return False
    if isinstance(val, str) and val.strip() == "":
        return False
    try:
        float_val = float(val)
        return not np.isnan(float_val) and float_val != 0.0
    except (ValueError, TypeError):
        return False


def is_valid_mag(mag: Any) -> bool:
    """Check if magnitude is valid and in reasonable range"""
    if not is_valid_value(mag):
        return False
    try:
        mag_float = float(mag)
        return 0 < mag_float < 99
    except (ValueError, TypeError):
        return False


def normalize_catalog_name(name: str) -> str:
    """
    Normalize catalog designations by removing spaces for major catalogs.

    Harris catalog has names like "NGC 104", "M 79", "Arp 2" with spaces,
    but the database has them as "NGC104", "M79", "Arp2" without spaces.

    Other catalog prefixes (Pal, AM, Terzan, etc.) are NOT in the official
    catalog system and should be treated as common names with spaces intact.

    Args:
        name: Catalog designation with potential spaces

    Returns:
        Normalized name (spaces removed for NGC, IC, M, Arp)
    """
    name = name.strip()

    # Normalize major catalogs by removing spaces
    # NGC, IC, M (Messier), Arp all need space removal
    if (
        name.startswith("NGC ")
        or name.startswith("IC ")
        or name.startswith("M ")
        or name.startswith("Arp ")
    ):
        return name.replace(" ", "")

    # All other names keep their spaces
    return name


def identify_catalog_type(name: str) -> Tuple[bool, str]:
    """
    Identify if a name is an official catalog designation or a common name.

    Official catalogs in the system: NGC, IC, M, C, Col, Ta2, H, SaA, SaM,
    SaR, Str, EGC, RDS, B, Sh2, Abl, Arp, TLK, WDS

    Args:
        name: Name to check

    Returns:
        tuple: (is_official_catalog, normalized_name)
    """
    # List of official catalog prefixes
    official_catalogs = {
        "NGC",
        "IC",
        "M",
        "C",
        "Col",
        "Ta2",
        "H",
        "SaA",
        "SaM",
        "SaR",
        "Str",
        "EGC",
        "RDS",
        "B",
        "Sh2",
        "Abl",
        "Arp",
        "TLK",
        "WDS",
    }

    name = name.strip()

    # Check if the name starts with any official catalog prefix
    for catalog in official_catalogs:
        if name.startswith(catalog + " ") or name == catalog:
            # Normalize NGC and IC by removing spaces
            normalized = normalize_catalog_name(name)
            return True, normalized

    # Not an official catalog - treat as common name
    return False, name


def create_cluster_object(entry: npt.NDArray, seq: int) -> Dict[str, Any]:
    """
    Create a single cluster object from catalog entry.

    Args:
        entry: numpy structured array row with cluster data
        seq: sequence number (line number in catalog)

    Returns:
        dict with ra, dec, mag, size, catalog_names, common_names, description, primary_name
    """
    result: Dict[str, Any] = {}

    # Log what we're processing
    cluster_id: str = entry["ID"].item().strip()
    common_name: str = entry["Name"].item().strip()
    if VERBOSE:
        logging.info(
            f"Processing Harris {seq}: ID='{cluster_id}', Name='{common_name}'"
        )

    # Parse RA/Dec from standard columns
    ra_h = entry["RAh"].item()
    ra_m = entry["RAm"].item()
    ra_s = entry["RAs"].item()
    result["ra"] = ra_to_deg(ra_h, ra_m, ra_s)

    # Handle declination sign
    dec_d = entry["DEd"].item()
    if entry["DE_sign"] == "-":
        dec_d = -dec_d
    dec_m = entry["DEm"].item()
    dec_s = entry["DEs"].item()
    result["dec"] = dec_to_deg(dec_d, dec_m, dec_s)

    if VERBOSE:
        logging.debug(
            f"  Coordinates: RA={result['ra']:.4f}°, Dec={result['dec']:.4f}°"
        )

    # Magnitude - use integrated V magnitude
    mag_value = entry["Vt"].item()
    if is_valid_mag(mag_value):
        result["mag"] = MagnitudeObject([mag_value])
        if VERBOSE:
            logging.debug(f"  Magnitude: {mag_value:.2f}")
    else:
        result["mag"] = MagnitudeObject([])
        if VERBOSE:
            logging.debug(f"  Magnitude: None (invalid value: {mag_value})")

    # Size - use half-mass radius (Rh) in arcminutes
    # Format using utils.format_size_value to match other catalogs
    rh = entry["Rh"].item()
    if is_valid_value(rh):
        # Convert to string, removing unnecessary decimals
        result["size"] = utils.format_size_value(rh)
        if VERBOSE:
            logging.debug(f"  Size (half-mass radius): {result['size']} arcmin")
    else:
        result["size"] = ""
        if VERBOSE:
            logging.debug(f"  Size: None (invalid Rh value: {rh})")

    # Build description with interesting features
    description_parts: List[str] = []

    # Distance from Sun
    rsun = entry["Rsun"].item()
    if is_valid_value(rsun):
        description_parts.append(f"Distance from Sun: {rsun:.1f} kpc")

    # Distance from Galactic center
    rgc = entry["Rgc"].item()
    if is_valid_value(rgc):
        description_parts.append(f"Distance from Galactic center: {rgc:.1f} kpc")

    # Galactic coordinates
    glon = entry["GLON"].item()
    glat = entry["GLAT"].item()
    if is_valid_value(glon) and is_valid_value(glat):
        description_parts.append(f"Galactic coords: l={glon:.2f}°, b={glat:.2f}°")

    # 3D position (Sun-centered coordinate system)
    x = entry["X"].item()
    y = entry["Y"].item()
    z = entry["Z"].item()
    if is_valid_value(x) and is_valid_value(y) and is_valid_value(z):
        description_parts.append(f"3D position (kpc): X={x:.1f}, Y={y:.1f}, Z={z:.1f}")

    # Absolute magnitude (cluster luminosity)
    mvt = entry["MVt"].item()
    if is_valid_value(mvt):
        description_parts.append(f"Absolute magnitude: {mvt:.2f}")

    result["description"] = "\n".join(description_parts) if description_parts else ""

    if VERBOSE and description_parts:
        logging.debug(f"  Description: {len(description_parts)} features")

    # Separate catalog names from common names
    # Official catalogs: NGC, IC, M, C, Col, Ta2, H, SaA, SaM, SaR, Str, EGC, RDS, B, Sh2, Abl, Arp, TLK, WDS
    # Everything else (Pal, AM, Terzan, etc.) becomes a common name
    result["catalog_names"] = []  # For aka_names (catalog designations)
    result["common_names"] = []  # For insert_name (common names)
    result["primary_name"] = f"Har {seq}"

    # Process catalog ID (first field)
    cluster_id = entry["ID"].item().strip()
    if cluster_id:
        is_catalog, normalized = identify_catalog_type(cluster_id)
        if is_catalog:
            result["catalog_names"].append(normalized)
            if VERBOSE:
                logging.info(f"  Catalog name: '{cluster_id}' → '{normalized}'")
        else:
            # Not an official catalog - add as common name
            result["common_names"].append(cluster_id)
            if VERBOSE:
                logging.info(f"  Common name: '{cluster_id}'")

    # Process common name field (second field)
    # These are always common names (47 Tuc, omega Cen, etc.)
    common_name = entry["Name"].item().strip()
    if common_name:
        # Check if it might be a Messier designation
        is_catalog, normalized = identify_catalog_type(common_name)
        if is_catalog:
            result["catalog_names"].append(normalized)
            if VERBOSE:
                logging.info(f"  Catalog name: '{common_name}' → '{normalized}'")
        else:
            result["common_names"].append(common_name)
            if VERBOSE:
                logging.info(f"  Common name: '{common_name}'")

    # Log summary
    if VERBOSE:
        logging.info(
            f"  Primary: {result['primary_name']}, "
            f"Catalog names: {len(result['catalog_names'])}, "
            f"Common names: {len(result['common_names'])}"
        )

    return result


def load_harris():
    logging.info("Loading Harris Globular Cluster catalog")
    catalog: str = "Har"
    obj_type: str = "Gb"  # Globular Cluster
    conn, _ = objects_db.get_conn_cursor()

    # Enable bulk mode to prevent commits during insert operations
    objects_db.bulk_mode = True

    # Optimize SQLite for bulk import
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA cache_size = 10000")
    conn.commit()  # Commit the PRAGMA changes

    # Path to file that contains the catalog's data
    data_path = Path(utils.astro_data_dir, "harris/catalog")
    delete_catalog_from_database(catalog)

    # Path to file that describes the catalog
    insert_catalog(catalog, Path(utils.astro_data_dir) / "harris/ReadMe")

    # Read the catalog data
    data = read_harris_catalog(data_path)

    logging.info(f"Read {len(data)} Harris globular clusters")

    # Create shared ObjectFinder to avoid recreating for each object
    from .catalog_import_utils import ObjectFinder

    shared_finder = ObjectFinder()
    NewCatalogObject.set_shared_finder(shared_finder)

    try:
        # Process each cluster entry
        seq: int = 1
        for entry in tqdm(data, total=len(data)):
            if VERBOSE:
                logging.info(f"\n{'=' * 60}")
                logging.info(f"Processing sequence {seq}/{len(data)}")

            # Create cluster object
            cluster_result: Dict[str, Any] = create_cluster_object(entry, seq)

            # Validate RA/DEC
            if (
                cluster_result["ra"] is None
                or cluster_result["dec"] is None
                or np.isnan(cluster_result["ra"])
                or np.isnan(cluster_result["dec"])
            ):
                cluster_id: str = entry["ID"].item().strip()
                logging.error(
                    f"Invalid RA/DEC for Harris cluster {cluster_id} at sequence {seq}"
                )
                logging.error(
                    f"  RA: {cluster_result['ra']}, DEC: {cluster_result['dec']}"
                )
                raise ValueError(
                    f"Invalid RA/DEC coordinates for Harris cluster {cluster_id}: "
                    f"RA={cluster_result['ra']}, DEC={cluster_result['dec']}"
                )

            # Primary catalog name is "Har ###"
            primary_name: str = cluster_result["primary_name"]

            # Build aka_names list with official catalog designations ONLY
            # Do NOT include primary_name - insert() adds "catalog_code sequence" automatically
            # Official catalogs (NGC, IC, M, etc.) go in aka_names for object matching
            # Other names (Pal, AM, Terzan, etc.) become common names added separately
            aka_names: List[str] = [
                trim_string(name) for name in cluster_result["catalog_names"]
            ]

            if VERBOSE:
                logging.info("Building catalog object:")
                logging.info(
                    f"  Primary: {primary_name} (added automatically by insert)"
                )
                logging.info(f"  aka_names: {aka_names}")
                logging.info(f"  common_names: {cluster_result['common_names']}")
                logging.info(
                    f"  RA/Dec: {cluster_result['ra']:.4f}°, {cluster_result['dec']:.4f}°"
                )

            # Create new catalog object
            # IMPORTANT: find_object_id=True to match existing objects by aka_names
            new_object = NewCatalogObject(
                object_type=obj_type,
                catalog_code=catalog,
                sequence=seq,
                ra=cluster_result["ra"],
                dec=cluster_result["dec"],
                mag=cluster_result["mag"],
                size=cluster_result["size"],
                aka_names=aka_names,
                description=cluster_result["description"],
            )

            # Insert with find_object_id=True to match existing objects
            if VERBOSE:
                logging.info("Inserting into database (find_object_id=True)...")

            # Check if we're linking to an existing object
            # We need aka_names for finding, but if found, clear them to prevent duplicates
            original_aka_names: List[str] = aka_names.copy()
            new_object.insert(find_object_id=True)

            # If we matched an existing object, aka_names would have added duplicate names
            # So we need to check if a match was found and log it
            object_id: Optional[int] = new_object.object_id
            if VERBOSE and object_id and original_aka_names:
                # Check if this is a new Harris object or if we matched existing
                # If the first catalog_object entry for this object_id is NOT Harris,
                # then we matched an existing object
                conn, cursor = objects_db.get_conn_cursor()
                cursor.execute(
                    "SELECT catalog_code FROM catalog_objects WHERE object_id = ? ORDER BY id LIMIT 1",
                    (object_id,),
                )
                first_catalog = cursor.fetchone()
                if first_catalog and first_catalog["catalog_code"] != catalog:
                    if VERBOSE:
                        logging.info(
                            f"  Matched existing {first_catalog['catalog_code']} object (object_id: {object_id})"
                        )
                        logging.info(
                            f"  Note: aka_names {original_aka_names} may already exist for this object"
                        )
                else:
                    if VERBOSE:
                        logging.info(f"  Created new object (object_id: {object_id})")
            else:
                if VERBOSE:
                    logging.info(f"  Inserted/Updated object_id: {object_id}")

            # Add common names (Pal 1, Terzan 7, 47 Tuc, omega Cen, etc.)
            # These are NOT official catalog designations but descriptive names
            if VERBOSE and cluster_result["common_names"]:
                logging.info(
                    f"Adding {len(cluster_result['common_names'])} common name(s):"
                )
            for common_name in cluster_result["common_names"]:
                if VERBOSE:
                    logging.info(f"  - '{common_name}' → names table")
                objects_db.insert_name(object_id, common_name, origin="Harris")

            seq += 1

        logging.info(f"\n{'=' * 60}")
        logging.info(f"Completed processing {seq - 1} Harris globular clusters")

    finally:
        # Clear shared finder
        NewCatalogObject.clear_shared_finder()

    # Disable bulk mode before final operations
    objects_db.bulk_mode = False

    insert_catalog_max_sequence(catalog)
    logging.info(f"Inserted catalog max sequence for {catalog}")

    # Commit all changes
    conn.commit()
    logging.info("Committed all changes")

    logging.info(f"Successfully loaded Harris catalog with {seq - 1} clusters")
    logging.info(f"{'=' * 60}")
