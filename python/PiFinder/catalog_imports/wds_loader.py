"""
WDS double star catalog.

TODO:
    - use real WDS names instead of sequence
    - incorporate cross references to BDS, ADS, IDS, Struve, ...:
      https://www.astro.gsu.edu/wds/wdstext.html#bdsadswds
      https://www.astro.gsu.edu/wds/misc/wdsidsadsbds.txt

"""

import logging
from pathlib import Path
from tqdm import tqdm
from collections import defaultdict

import PiFinder.utils as utils
from PiFinder.composite_object import MagnitudeObject, SizeObject
from PiFinder.calc_utils import ra_to_deg, dms_to_dec
from .catalog_import_utils import (
    STAND_IN_POSITIONS,
    delete_catalog_from_database,
    insert_catalog,
    insert_catalog_max_sequence,
    NewCatalogObject,
    trim_string,
)

# Import shared database object
from .database import objects_db
import numpy as np


def read_wds_catalog(file_path):
    # wds_precise.txt is not laid out like the standard WDS file: it gives one
    # position angle and separation, the last measured, at columns 38-44 and
    # 45-53 with more decimals, and nothing at the standard columns' places.
    # "-1" stands for a measure WDS lacks, and "." for a magnitude it lacks.
    col_specs = [
        (0, 10),  # coords
        (10, 17),  # discoverer
        (17, 22),  # components
        (23, 27),  # date_first
        (28, 32),  # date_last
        (33, 37),  # num_obs
        (37, 44),  # pa (last)
        (44, 53),  # sep (last)
        (58, 63),  # mag_first
        (64, 69),  # mag_second
        (70, 79),  # spectral_type
        (80, 84),  # pm_ra_primary
        (84, 88),  # pm_dec_primary
        (89, 93),  # pm_ra_secondary
        (93, 97),  # pm_dec_secondary
        (98, 106),  # dm_number
        (107, 111),  # notes
        (112, 130),  # coords_arc
    ]

    # Define dtype for structured array
    dtype = [
        ("Coordinates_2000", "U10"),
        ("Discoverer_Number", "U7"),
        ("Components", "U5"),
        ("Date_First", "i4"),
        ("Date_Last", "i4"),
        ("Num_Observations", "i4"),
        ("PA", "f8"),
        ("Sep", "f8"),
        ("Mag_First", "f8"),
        ("Mag_Second", "f8"),
        ("Spectral_Type", "U9"),
        ("PM_RA_Primary", "i4"),
        ("PM_Dec_Primary", "i4"),
        ("PM_RA_Secondary", "i4"),
        ("PM_Dec_Secondary", "i4"),
        ("DM_Number", "U8"),
        ("Notes", "U4"),
        ("Coordinates_Arcsec", "U18"),
    ]

    def parse_line(line):
        return tuple(
            parse_field(line[start:end].strip(), dtype)
            for (start, end), (_, dtype) in zip(col_specs, dtype)
        )

    def parse_field(value, dtype):
        value = value.strip()
        if dtype.startswith("U"):
            return value
        elif dtype == "i4":
            return int(value) if value and value != "." else 0
        elif dtype == "f8":
            # A missing value is NaN, never 0.0, which reads as a 0 mag star.
            try:
                return float(value) if value and value != "." else np.nan
            except ValueError:
                return np.nan

    data = []
    with open(file_path, "r") as file:
        for line in file:
            data.append(parse_line(line))

    data = np.array(data, dtype=dtype)
    for measure in ("PA", "Sep"):
        data[measure][data[measure] < 0] = np.nan
    return data


def wds_magnitudes(mag1: float, mag2: float) -> MagnitudeObject:
    """A pair's [primary, companion] magnitudes, leaving out what WDS lacks.

    Without the primary's magnitude there is none for the star, so the
    companion's stays off it, as in the SAC loader.
    """
    if np.isnan(mag1):
        return MagnitudeObject([])
    mags = [round(float(mag1), 2)]
    if not np.isnan(mag2):
        mags.append(round(float(mag2), 2))
    return MagnitudeObject(mags)


# The D* rule's WDS clause (docs/ax/catalog.md §9.3): WDS lists every pair
# ever measured, so a pair makes a double star only if WDS flags it neither
# optical (S, U, Y, L) nor dubious (X), it includes the primary, and its
# companion is one an observer would look for: within this separation and
# magnitude difference of the primary, and wide enough to split (Capella's
# and Algol's interferometric pairs are not). Vega's companions fail,
# Propus's BU 1008 (6.2 at 1.9") passes. The limits are Rich's choice
# (2026-10), his to tune.
OPTICAL_OR_DUBIOUS = frozenset("SUYLX")
DOUBLE_MIN_SEPARATION_ARCSEC = 0.5
DOUBLE_MAX_SEPARATION_ARCSEC = 60.0
DOUBLE_MAX_DELTA_MAG = 5.0


def is_double_star_pair(value) -> bool:
    """Whether one WDS pair makes its primary a double star (D*)."""
    if set(value["Notes"]) & OPTICAL_OR_DUBIOUS:
        return False
    components = value["Components"].strip()
    if components and not components.startswith("A"):
        return False
    sep = value["Sep"].item()
    if np.isnan(sep) or not (
        DOUBLE_MIN_SEPARATION_ARCSEC <= sep <= DOUBLE_MAX_SEPARATION_ARCSEC
    ):
        return False
    mag1, mag2 = value["Mag_First"].item(), value["Mag_Second"].item()
    if np.isnan(mag2):
        return False
    return bool(np.isnan(mag1) or mag2 - mag1 <= DOUBLE_MAX_DELTA_MAG)


def describe_pair(value) -> str:
    """One pair's line of a WDS listing's description, without what WDS lacks."""
    components = value["Components"].strip()
    parts = [] if not components else [f"{components}:"]
    mags = [value["Mag_First"].item(), value["Mag_Second"].item()]
    parts.append(
        "Mag=" + "/".join("?" if np.isnan(m) else f"{round(m, 2)}" for m in mags)
    )
    pa = value["PA"].item()
    if not np.isnan(pa):
        parts[-1] += ","
        parts.append(f"PA={round(pa, 1)} ({value['Date_Last']})")
    sep = value["Sep"].item()
    if not np.isnan(sep):
        parts[-1] += ","
        parts.append(f"Sep={round(sep, 3)}")
    notes = value["Notes"].strip()
    if notes:
        parts.append(f"Notes: {notes}")
    return " ".join(parts)


def load_wds():
    logging.info("Loading WDS")
    catalog = "WDS"
    conn, _ = objects_db.get_conn_cursor()

    # Optimize SQLite for bulk import
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA cache_size = 10000")

    data_path = Path(utils.astro_data_dir, "WDS/wds_precise.txt")
    delete_catalog_from_database(catalog)
    insert_catalog(catalog, Path(utils.astro_data_dir) / "WDS/wds.desc")
    data = read_wds_catalog(data_path)

    def parse_coordinates_2000(coord):
        try:
            # Check for correct length (WDS identifier is always 10 chars)
            if len(coord) != 10:
                return None, None

            # Format: HHMM.t±DDMM (10 characters) - example: 00001-0122
            ra_h = float(coord[:2])
            ra_m = float(coord[2:4])
            ra_s = float(coord[4:5]) * 6  # Convert tenths of minutes to seconds
            # The sign is read on its own: -1 * 00 is -0.0, which is not < 0.
            dec_deg = dms_to_dec(coord[5], int(coord[6:8]), float(coord[8:10]), 0)
            return ra_to_deg(ra_h, ra_m, ra_s), dec_deg
        except (ValueError, IndexError):
            return None, None

    def parse_coordinates_arcsec(coord):
        try:
            # Handle empty, missing, or '.' coordinates
            coord_clean = coord.strip()
            if not coord_clean or coord_clean == ".":
                return None, None

            # Find the sign position (+ or -)
            sign_pos = -1
            for i, char in enumerate(coord_clean):
                if char in ["+", "-"]:
                    sign_pos = i
                    break

            if sign_pos == -1:
                return None, None

            # Parse RA part (before sign)
            ra_part = coord_clean[:sign_pos].strip()
            ra_h = float(ra_part[:2])
            ra_m = float(ra_part[2:4])
            ra_s = float(ra_part[4:])  # Variable length seconds

            # Parse DEC part (after sign)
            dec_part = coord_clean[sign_pos:]
            dec_coords = dec_part[1:].strip()  # Remove sign

            dec_d = int(dec_coords[:2])
            dec_m = float(dec_coords[2:4])
            dec_s = float(dec_coords[4:]) if len(dec_coords) > 4 else 0.0

        except (ValueError, IndexError):
            return None, None
        # The sign is read on its own, so a pair at -00 44 stays south.
        return ra_to_deg(ra_h, ra_m, ra_s), dms_to_dec(dec_part[0], dec_d, dec_m, dec_s)

    def handle_multiples(key, values) -> dict:
        # Ordered, so the names keep the source order in every import.
        discoverers: dict = {}
        result: dict = {}
        double = False
        descriptions = []
        for i, value in enumerate(values):
            if i == 0:
                # Validate RA/DEC in the first (primary) object
                if (
                    value["ra"] is None
                    or value["dec"] is None
                    or np.isnan(value["ra"])
                    or np.isnan(value["dec"])
                ):
                    logging.error(
                        f"Empty or invalid RA/DEC in handle_multiples for WDS object '{key}'"
                    )
                    logging.error(
                        f"  Primary object RA: {value['ra']}, DEC: {value['dec']}"
                    )
                    logging.error(f"  Coordinates_2000: '{value['Coordinates_2000']}'")
                    logging.error(
                        f"  Coordinates_Arcsec: '{value['Coordinates_Arcsec']}'"
                    )
                    raise ValueError(
                        f"Invalid RA/DEC coordinates for primary WDS object '{key}': RA={value['ra']}, DEC={value['dec']}"
                    )
                result["ra"] = value["ra"]
                result["dec"] = value["dec"]
                result["precise"] = bool(value["precise"])
                result["mag"] = wds_magnitudes(value["Mag_First"], value["Mag_Second"])
                sep = value["Sep"].item()
                result["size"] = (
                    SizeObject([])
                    if np.isnan(sep)
                    else SizeObject.from_arcsec(round(sep, 1))
                )
            discoverers[value["Discoverer_Number"]] = None
            descriptions.append(describe_pair(value))
            double = double or is_double_star_pair(value)

        # A listing none of whose pairs is a double star is a single star.
        result["obj_type"] = "D*" if double else "*"
        result["discoverers"] = list(discoverers)
        result["name"] = key
        result["description"] = "\n".join(descriptions)
        return result

    # Add coordinate columns to the numpy array
    new_dtype = data.dtype.descr + [("ra", "f8"), ("dec", "f8"), ("precise", "?")]
    new_data = np.empty(data.shape, dtype=new_dtype)

    # Copy existing data
    for name in data.dtype.names:
        new_data[name] = data[name]
    # Whether the position is the arcsecond one, not the identifier's.
    new_data["precise"] = False

    # Replace the old data with the new data
    data = new_data

    # Parse coordinates on demand and assign final values
    for i, entry in enumerate(data):
        # Try arcsecond coordinates first
        ra_arcsec, dec_arcsec = parse_coordinates_arcsec(entry["Coordinates_Arcsec"])

        if ra_arcsec is not None and dec_arcsec is not None:
            entry["ra"] = ra_arcsec
            entry["dec"] = dec_arcsec
            entry["precise"] = True
        else:
            # Fall back to 2000 coordinates
            ra_2000, dec_2000 = parse_coordinates_2000(entry["Coordinates_2000"])
            entry["ra"] = ra_2000
            entry["dec"] = dec_2000

        # Validate RA/DEC values are not empty/invalid
        if (
            entry["ra"] is None
            or entry["dec"] is None
            or np.isnan(entry["ra"])
            or np.isnan(entry["dec"])
        ):
            coord_2000 = entry["Coordinates_2000"]
            coord_arcsec = entry["Coordinates_Arcsec"]
            logging.error(
                f"Empty or invalid RA/DEC detected for WDS object at line {i+1}"
            )
            logging.error(f"  Coordinates_2000: '{coord_2000}'")
            logging.error(f"  Coordinates_Arcsec: '{coord_arcsec}'")
            logging.error(f"  Parsed RA_2000: {ra_2000[i]}, DEC_2000: {dec_2000[i]}")
            logging.error(
                f"  Parsed RA_arcsec: {ra_arcsec[i]}, DEC_arcsec: {dec_arcsec[i]}"
            )
            logging.error(f"  Final RA: {entry['ra']}, DEC: {entry['dec']}")
            raise ValueError(
                f"Invalid RA/DEC coordinates for WDS object at line {i+1}: RA={entry['ra']}, DEC={entry['dec']}"
            )

    # make a dictionary of WDS objects to group duplicates
    wds_dict = defaultdict(list)

    for line, entry in enumerate(tqdm(data, total=len(data))):
        wds_dict[entry["Coordinates_2000"]].append(entry)

    STAND_IN_POSITIONS.difference_update(
        {listing for listing in STAND_IN_POSITIONS if listing[0] == catalog}
    )
    seq = 1
    for key, value in tqdm(wds_dict.items(), total=len(wds_dict.items())):
        current_result = handle_multiples(key, value)
        wds_name = f"WDS J{current_result['name']}"
        clean_discoverers = [
            trim_string(name) for name in current_result["discoverers"]
        ]
        new_object = NewCatalogObject(
            object_type=current_result["obj_type"],
            catalog_code=catalog,
            sequence=seq,
            ra=current_result["ra"],
            dec=current_result["dec"],
            mag=current_result["mag"],
            size=current_result["size"],
            aka_names=[wds_name] + clean_discoverers,
            description=current_result["description"],
        )
        new_object.insert(find_object_id=False)
        if not current_result["precise"]:
            STAND_IN_POSITIONS.add((catalog, seq))
        seq += 1

    insert_catalog_max_sequence(catalog)

    # Restore SQLite settings
    conn.execute("PRAGMA synchronous = FULL")
    conn.execute("PRAGMA journal_mode = DELETE")

    conn.commit()
