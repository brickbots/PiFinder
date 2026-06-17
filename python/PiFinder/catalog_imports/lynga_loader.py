"""
Lynga Open Cluster catalog load script.

Source: VII/92A - Catalogue of Open Cluster Data 5th Edition (Lynga 1987)
        https://cdsarc.cds.unistra.fr/ftp/VII/92A/

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
from PiFinder.composite_object import MagnitudeObject, SizeObject
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

# Cluster Sequence Code mapping (Note 1 in ReadMe)
CLUSTER_SEQUENCE = {
    1: "NGC",
    2: "IC",
    3: "Berkeley",
    4: "Czernik",
    5: "Dolidze",
    6: "Collinder",
    7: "Upgren",
    8: "Tombaugh",
    9: "Ruprecht",
    10: "King",
    11: "Stock",
    13: "Trumpler",
    14: "Markarian",
    16: "Haffner",
    17: "Hogg",
    18: "Sher",
    19: "Feinstein",
    20: "Harvard",
    21: "Lynga",
    22: "Westerlund",
    23: "Basel",
    24: "Blanco",
    25: "Baractova",
    26: "Biurakan",
    27: "Melotte",
    28: "Pismis",
    30: "Trapezium",
    32: "Pleiades",
    33: "Graff",
    34: "Iskudarian",
    35: "Stephenson",
    36: "Roslund",
    37: "Hyades",
    41: "vdB-Hagen",
    42: "Bochum",
    43: "Dolidze-Dzimselejsvili",
    45: "Antalova",
    46: "Moffat",
    47: "Havlen-Moffat",
    48: "Frolov",
    50: "vdB",
    51: "Mayer",
    52: "Latysev",
    53: "Sigma Ori",
    54: "Graham",
    55: "Aveni-Hunter",
    56: "Loden",
    57: "Grasdalen",
    58: "Waterloo",
    59: "Auner",
    61: "Schuster",
    62: "Danks",
    63: "Muzzio",
    64: "Pfleiderer",
}


def read_lynga_catalog(file_path: Path) -> npt.NDArray:
    """
    Read Lynga Open Cluster catalog from fixed-width format file.

    Format per ReadMe (1-based bytes, converted to 0-based slices):
    - Bytes  1-  2: ClSeq  - Cluster Sequence code (I2)
    - Bytes  3-  6: ClNum  - Number inside Cluster Sequence (I4)
    - Bytes  8-  9: RA2000h - RA 2000 hours (I2)
    - Bytes 10- 13: RA2000m - RA 2000 minutes (F4.1)
    - Byte  14:     DE2000- - Dec 2000 sign (A1)
    - Bytes 15- 16: DE2000d - Dec 2000 degrees (I2)
    - Bytes 17- 18: DE2000m - Dec 2000 minutes (I2)
    - Bytes 59- 64: Diam    - Selected angular diameter (F6.1 arcmin)
    - Bytes 65- 68: r_Diam  - Reference for diameter (I4)
    - Bytes 69- 72: Dist    - Distance (I4 pc)
    - Bytes 74- 76: r_Dist  - Reference for distance (I3)
    - Bytes 77- 81: log.Age - log(age) years (F5.2)
    - Bytes 82- 84: r_log.Age - Reference for log age (I3)
    - Bytes 85- 89: [Fe/H]  - Metallicity (F5.2)
    - Bytes 90- 92: r_[Fe/H] - Reference for metallicity (I3)
    - Bytes 93- 98: E(B-V)  - Reddening (F6.2 mag)
    - Bytes 101-102: ClTyp  - "DO" doubtful cluster flag (A2)
    - Bytes 195-196: TrConc - Trumpler concentration class (I2)
    - Bytes 197-198: TrRange - Trumpler range class (I2)
    - Bytes 199-200: TrRich - Trumpler richness class (A2)
    - Byte  202:     TrNeb  - Trumpler nebulosity (A1)
    - Bytes 215-218: maxBr.50  - Brightest star magnitude from ref.50 (F4.1)
    - Bytes 225-228: totMag.50 - Total magnitude from ref.50 (F4.1)
    - Bytes 235-238: totMag.422 - Total magnitude from Skiff (F4.1)
    - Bytes 239-242: i(B-V).422 - Integrated B-V from Skiff (F4.2)
    - Bytes 243-246: N.422   - Number of stars (Skiff) (I4)
    - Bytes 322-324: w_RVel  - Weight for radial velocity (F3.1)
    - Bytes 325-328: RVel    - Radial velocity (I4 km/s)
    - Bytes 430-438: Cname   - "C" designation (A9)
    - Bytes 464-468: Dist.jdl - jdl distance (I5 pc)
    - Bytes 471-475: turn.jdl - jdl turn-off colour (F5.2)
    - Bytes 476-481: Age.jdl  - jdl derived age (F6.0 Myr)
    - Bytes 484-488: E(B-V).jdl - jdl reddening (F5.2)
    - Bytes 492-496: [Fe/H].jdl - jdl abundance (F5.2)
    """
    # Define the column specifications (0-based, end-exclusive)
    col_specs = [
        (0, 2),  # ClSeq
        (2, 6),  # ClNum
        (7, 9),  # RA2000h
        (9, 13),  # RA2000m
        (13, 14),  # DE2000-
        (14, 16),  # DE2000d
        (16, 18),  # DE2000m
        (58, 64),  # Diam (arcmin)
        (68, 72),  # Dist (pc)
        (76, 81),  # log.Age
        (84, 89),  # [Fe/H]
        (92, 98),  # E(B-V)
        (100, 102),  # ClTyp
        (194, 196),  # TrConc
        (196, 198),  # TrRange
        (198, 200),  # TrRich
        (201, 202),  # TrNeb
        (214, 218),  # maxBr.50 (brightest star, ref.50)
        (224, 228),  # totMag.50 (total magnitude, ref.50)
        (234, 238),  # totMag.422 (Skiff total mag)
        (238, 242),  # i(B-V).422 (Skiff B-V)
        (242, 246),  # N.422 (Skiff star count)
        (321, 324),  # w_RVel
        (324, 328),  # RVel (km/s)
        (429, 438),  # Cname
        (463, 468),  # Dist.jdl (pc)
        (470, 475),  # turn.jdl
        (475, 481),  # Age.jdl (Myr)
        (483, 488),  # E(B-V).jdl
        (491, 496),  # [Fe/H].jdl
    ]

    # Define dtype for structured array
    dtype = [
        ("ClSeq", "i4"),  # Cluster Sequence code
        ("ClNum", "i4"),  # Number inside sequence
        ("RA2000h", "i4"),  # RA 2000 hours
        ("RA2000m", "f4"),  # RA 2000 minutes
        ("DE2000s", "U1"),  # Dec 2000 sign
        ("DE2000d", "i4"),  # Dec 2000 degrees
        ("DE2000m", "i4"),  # Dec 2000 minutes
        ("Diam", "f4"),  # Angular diameter (arcmin)
        ("Dist", "i4"),  # Distance (pc)
        ("logAge", "f4"),  # log(age) years
        ("FeH", "f4"),  # Metallicity [Fe/H]
        ("EBV", "f4"),  # Reddening E(B-V)
        ("ClTyp", "U2"),  # Doubtful cluster flag
        ("TrConc", "i4"),  # Trumpler concentration class
        ("TrRange", "i4"),  # Trumpler range class
        ("TrRich", "U2"),  # Trumpler richness class
        ("TrNeb", "U1"),  # Trumpler nebulosity
        ("maxBr50", "f4"),  # Brightest star magnitude (ref.50)
        ("totMag50", "f4"),  # Total magnitude (ref.50)
        ("totMag422", "f4"),  # Total magnitude (Skiff ref.422)
        ("iBV422", "f4"),  # Integrated B-V (Skiff)
        ("N422", "i4"),  # Number of stars (Skiff)
        ("wRVel", "f4"),  # Radial velocity weight
        ("RVel", "i4"),  # Radial velocity (km/s)
        ("Cname", "U9"),  # "C" designation
        ("DistJDL", "i4"),  # jdl distance (pc)
        ("turnJDL", "f4"),  # jdl turn-off colour
        ("AgeJDL", "f4"),  # jdl age (Myr)
        ("EBVJDL", "f4"),  # jdl reddening
        ("FeHJDL", "f4"),  # jdl abundance
    ]

    def parse_field(value: str, field_dtype: str) -> Any:
        value = value.strip()
        if field_dtype.startswith("U"):
            return value
        elif field_dtype == "i4":
            return int(value) if value and value not in (".", "-") else 0
        elif field_dtype == "f4":
            try:
                return float(value) if value and value not in (".", "-") else np.nan
            except ValueError:
                return np.nan

    def parse_line(line: str) -> tuple:
        # Pad line to at least 496 chars to avoid index errors
        line = line.rstrip("\n").rstrip("\r")
        line = line.ljust(514)
        return tuple(
            parse_field(line[start:end].strip(), field_dtype)
            for (start, end), (_, field_dtype) in zip(col_specs, dtype)
        )

    data = []
    with open(file_path, "r") as file:
        for line_num, line in enumerate(file, start=1):
            parsed = parse_line(line)
            data.append(parsed)

            if VERBOSE and line_num <= 3:
                logging.info(f"Line {line_num} parsed:")
                logging.info(f"  ClSeq: {parsed[0]}, ClNum: {parsed[1]}")
                logging.info(f"  RA2000: {parsed[2]}h {parsed[3]}m")
                logging.info(f"  Dec2000: {parsed[4]}{parsed[5]}° {parsed[6]}'")
                logging.info(f"  Cname: '{parsed[24]}'")

    logging.info(f"Read {len(data)} lines from Lynga catalog")
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


def build_cluster_designation(cl_seq: int, cl_num: int) -> Tuple[str, bool]:
    """
    Build the cluster designation string from ClSeq and ClNum codes.

    Args:
        cl_seq: Cluster Sequence code
        cl_num: Number within that sequence

    Returns:
        tuple: (designation_string, is_official_catalog)
            is_official_catalog is True for NGC, IC, Collinder, Melotte, Trumpler, etc.
    """
    prefix = CLUSTER_SEQUENCE.get(cl_seq, f"Seq{cl_seq}")
    designation = f"{prefix} {cl_num}" if cl_num > 0 else prefix

    # Official catalog prefixes that are recognized in the PiFinder database
    official_prefixes = {
        "NGC",
        "IC",
        "Collinder",
        "Col",
        "Melotte",
        "Trumpler",
        "Tr",
        "Berkeley",
        "Stock",
        "King",
        "Ruprecht",
        "Harvard",
        "Hogg",
        "Markarian",
        "Lynga",
        "Bochum",
        "Basel",
        "Westerlund",
    }

    is_official = prefix in official_prefixes
    return designation, is_official


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

    for catalog in official_catalogs:
        if name.startswith(catalog + " ") or name == catalog:
            normalized = name.replace(" ", "")
            return True, normalized

    return False, name


def create_cluster_object(entry: npt.NDArray, seq: int) -> Dict[str, Any]:
    """
    Create a single open cluster object from catalog entry.

    Args:
        entry: numpy structured array row with cluster data
        seq: sequence number (row number in catalog, used as designation)

    Returns:
        dict with ra, dec, mag, size, catalog_names, common_names,
              description, primary_name
    """
    result: Dict[str, Any] = {}

    cl_seq = entry["ClSeq"].item()
    cl_num = entry["ClNum"].item()
    cname = entry["Cname"].item().strip()

    if VERBOSE:
        logging.info(
            f"Processing Lynga {seq}: ClSeq={cl_seq}, ClNum={cl_num}, Cname='{cname}'"
        )

    # --- Coordinates (J2000) ---
    ra_h = entry["RA2000h"].item()
    ra_m = entry["RA2000m"].item()
    result["ra"] = ra_to_deg(ra_h, ra_m, 0.0)

    dec_d = entry["DE2000d"].item()
    if entry["DE2000s"] == "-":
        dec_d = -dec_d
    dec_m = entry["DE2000m"].item()
    result["dec"] = dec_to_deg(dec_d, dec_m, 0)

    if VERBOSE:
        logging.debug(
            f"  Coordinates: RA={result['ra']:.4f}°, Dec={result['dec']:.4f}°"
        )

    # --- Magnitude ---
    # Priority: totMag.422 (Skiff integrated V) → totMag.50 (ref.50 integrated)
    #           → maxBr.50 (brightest member star, last resort)
    mag_value = entry["totMag422"].item()
    if not is_valid_mag(mag_value):
        mag_value = entry["totMag50"].item()
    if not is_valid_mag(mag_value):
        mag_value = entry["maxBr50"].item()

    if is_valid_mag(mag_value):
        result["mag"] = MagnitudeObject([mag_value])
        if VERBOSE:
            logging.debug(f"  Magnitude: {mag_value:.1f}")
    else:
        result["mag"] = MagnitudeObject([])
        if VERBOSE:
            logging.debug("  Magnitude: None")

    # --- Size ---
    # Angular diameter in arcminutes
    diam = entry["Diam"].item()
    if is_valid_value(diam):
        result["size"] = SizeObject.from_arcmin(float(diam))
        if VERBOSE:
            logging.debug(f"  Size: {result['size']}")
    else:
        result["size"] = SizeObject([])

    # --- Description ---
    description_parts: List[str] = []

    # Distance
    dist = entry["Dist"].item()
    dist_jdl = entry["DistJDL"].item()
    if dist_jdl and dist_jdl > 0:
        description_parts.append(f"Distance: {dist_jdl} pc (jdl)")
    elif dist and dist > 0:
        description_parts.append(f"Distance: {dist} pc")

    # Age
    log_age = entry["logAge"].item()
    age_jdl = entry["AgeJDL"].item()
    if is_valid_value(age_jdl):
        description_parts.append(f"Age: {age_jdl:.0f} Myr (jdl)")
    elif is_valid_value(log_age):
        description_parts.append(f"log(age): {log_age:.2f} yr")

    # Reddening
    ebv_jdl = entry["EBVJDL"].item()
    ebv = entry["EBV"].item()
    if is_valid_value(ebv_jdl):
        description_parts.append(f"E(B-V): {ebv_jdl:.2f} (jdl)")
    elif is_valid_value(ebv):
        description_parts.append(f"E(B-V): {ebv:.2f}")

    # Metallicity
    feh_jdl = entry["FeHJDL"].item()
    feh = entry["FeH"].item()
    if is_valid_value(feh_jdl):
        description_parts.append(f"[Fe/H]: {feh_jdl:.2f} (jdl)")
    elif is_valid_value(feh):
        description_parts.append(f"[Fe/H]: {feh:.2f}")

    # Trumpler classification
    tr_conc = entry["TrConc"].item()
    tr_range = entry["TrRange"].item()
    tr_rich = entry["TrRich"].item().strip()
    tr_neb = entry["TrNeb"].item().strip()
    if tr_conc or tr_range or tr_rich:
        tr_class = ""
        if tr_conc:
            tr_class += str(tr_conc)
        if tr_range:
            tr_class += str(tr_range)
        if tr_rich:
            tr_class += tr_rich
        if tr_neb:
            tr_class += "n"
        if tr_class:
            description_parts.append(f"Trumpler class: {tr_class}")

    # Integrated B-V colour
    ibv = entry["iBV422"].item()
    if is_valid_value(ibv):
        description_parts.append(f"Integrated B-V: {ibv:.2f}")

    # Radial velocity
    rvel = entry["RVel"].item()
    w_rvel = entry["wRVel"].item()
    if rvel != 0 and is_valid_value(w_rvel):
        description_parts.append(f"Radial velocity: {rvel} km/s")

    # Doubtful cluster flag
    cl_typ = entry["ClTyp"].item().strip()
    if cl_typ == "DO":
        description_parts.append("Note: Classified as doubtful cluster")

    result["description"] = "\n".join(description_parts) if description_parts else ""

    if VERBOSE and description_parts:
        logging.debug(f"  Description: {len(description_parts)} features")

    # --- Names ---
    result["catalog_names"] = []  # Official catalog designations for aka_names
    result["common_names"] = []  # Everything else
    result["primary_name"] = f"Lyn {seq}"

    # Build designation from ClSeq + ClNum
    designation, is_official = build_cluster_designation(cl_seq, cl_num)

    if designation:
        if is_official:
            # Check further against the PiFinder official catalog list
            is_pf_catalog, normalized = identify_catalog_type(designation)
            if is_pf_catalog:
                result["catalog_names"].append(normalized)
                if VERBOSE:
                    logging.info(f"  Catalog name: '{designation}' → '{normalized}'")
            else:
                # Official astronomy catalog but not in PiFinder system - use as common name
                result["common_names"].append(designation)
                if VERBOSE:
                    logging.info(f"  Common name (non-PF official): '{designation}'")
        else:
            result["common_names"].append(designation)
            if VERBOSE:
                logging.info(f"  Common name: '{designation}'")

    # Note: Cname (e.g. C2357+606) is a positional identifier only, not stored

    if VERBOSE:
        logging.info(
            f"  Primary: {result['primary_name']}, "
            f"Catalog names: {len(result['catalog_names'])}, "
            f"Common names: {len(result['common_names'])}"
        )

    return result


def load_lynga() -> None:
    assert objects_db is not None, "Database not initialized before load_lynga()"
    logging.info("Loading Lynga Open Cluster catalog")
    catalog: str = "Lyn"
    obj_type: str = "OC"  # Open Cluster
    conn, _ = objects_db.get_conn_cursor()

    # Enable bulk mode to prevent commits during insert operations
    objects_db.bulk_mode = True

    # Optimize SQLite for bulk import
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA cache_size = 10000")
    conn.commit()

    # Path to file that contains the catalog's data
    data_path = Path(utils.astro_data_dir, "lynga/catalog")
    delete_catalog_from_database(catalog)

    # Path to file that describes the catalog
    insert_catalog(catalog, Path(utils.astro_data_dir) / "lynga/ReadMe")

    # Read the catalog data
    data = read_lynga_catalog(data_path)

    logging.info(f"Read {len(data)} Lynga open clusters")

    # Create shared ObjectFinder to avoid recreating for each object
    from .catalog_import_utils import ObjectFinder

    shared_finder = ObjectFinder()
    NewCatalogObject.set_shared_finder(shared_finder)

    try:
        seq: int = 1
        for entry in tqdm(data, total=len(data)):
            if VERBOSE:
                logging.info(f"\n{'=' * 60}")
                logging.info(f"Processing sequence {seq}/{len(data)}")

            cluster_result: Dict[str, Any] = create_cluster_object(entry, seq)

            # Validate RA/DEC
            if (
                cluster_result["ra"] is None
                or cluster_result["dec"] is None
                or np.isnan(cluster_result["ra"])
                or np.isnan(cluster_result["dec"])
            ):
                cl_seq = entry["ClSeq"].item()
                cl_num = entry["ClNum"].item()
                logging.error(
                    f"Invalid RA/DEC for Lynga cluster ClSeq={cl_seq} ClNum={cl_num} "
                    f"at sequence {seq}"
                )
                logging.error(
                    f"  RA: {cluster_result['ra']}, DEC: {cluster_result['dec']}"
                )
                raise ValueError(
                    f"Invalid RA/DEC coordinates for Lynga cluster ClSeq={cl_seq} "
                    f"ClNum={cl_num}: RA={cluster_result['ra']}, "
                    f"DEC={cluster_result['dec']}"
                )

            primary_name: str = cluster_result["primary_name"]

            # Build aka_names list with official catalog designations ONLY
            # Do NOT include primary_name - insert() adds "catalog_code sequence" automatically
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
                    f"  RA/Dec: {cluster_result['ra']:.4f}°, "
                    f"{cluster_result['dec']:.4f}°"
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

            if VERBOSE:
                logging.info("Inserting into database (find_object_id=True)...")

            original_aka_names: List[str] = aka_names.copy()
            new_object.insert(find_object_id=True)

            object_id: Optional[int] = new_object.object_id
            if VERBOSE and object_id and original_aka_names:
                conn, cursor = objects_db.get_conn_cursor()
                cursor.execute(
                    "SELECT catalog_code FROM catalog_objects "
                    "WHERE object_id = ? ORDER BY id LIMIT 1",
                    (object_id,),
                )
                first_catalog = cursor.fetchone()
                if first_catalog and first_catalog["catalog_code"] != catalog:
                    logging.info(
                        f"  Matched existing {first_catalog['catalog_code']} object "
                        f"(object_id: {object_id})"
                    )
                else:
                    logging.info(f"  Created new object (object_id: {object_id})")
            else:
                if VERBOSE:
                    logging.info(f"  Inserted/Updated object_id: {object_id}")

            # Add common names (Berkeley 58, Waterloo 1, Czernik 4, etc.)
            # These are NOT official PiFinder catalog designations but still useful names
            if VERBOSE and cluster_result["common_names"]:
                logging.info(
                    f"Adding {len(cluster_result['common_names'])} common name(s):"
                )
            for common_name in cluster_result["common_names"]:
                if VERBOSE:
                    logging.info(f"  - '{common_name}' → names table")
                objects_db.insert_name(object_id, common_name, origin="Lyn")

            seq += 1

        logging.info(f"\n{'=' * 60}")
        logging.info(f"Completed processing {seq - 1} Lynga open clusters")

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

    logging.info(f"Successfully loaded Lynga catalog with {seq - 1} clusters")
    logging.info(f"{'=' * 60}")
