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
import numpy as np


def read_wds_catalog(file_path):
    # Define the column specifications
    col_specs = [
        (0, 10),  # coords
        (10, 17),  # discoverer
        (17, 22),  # components
        (23, 27),  # date_first
        (28, 32),  # date_last
        (33, 37),  # num_obs
        (38, 41),  # pa_first
        (42, 45),  # pa_last
        (46, 51),  # sep_first
        (52, 57),  # sep_last
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
        ("PA_First", "f4"),
        ("PA_Last", "f4"),
        ("Sep_First", "f4"),
        ("Sep_Last", "f4"),
        ("Mag_First", "f4"),
        ("Mag_Second", "f4"),
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
        elif dtype == "f4":
            try:
                return float(value) if value and value != "." else 0.0
            except ValueError:
                return 0.0

    data = []
    with open(file_path, "r") as file:
        for line in file:
            data.append(parse_line(line))

    return np.array(data, dtype=dtype)


def load_wds():
    logging.info("Loading WDS")
    catalog = "WDS"
    obj_type = "D*"
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
            dec_sign = 1 if coord[5] == "+" else -1
            dec_deg = float(coord[6:8]) * dec_sign
            dec_m = float(coord[8:10])
            return ra_to_deg(ra_h, ra_m, ra_s), dec_to_deg(dec_deg, dec_m, 0)
        except (ValueError, IndexError):
            return None, None

    def parse_coordinates_arcsec(coord):
        try:
            # Handle empty, missing, or '.' coordinates
            coord_clean = coord.strip()
            if not coord_clean or coord_clean == '.':
                return None, None

            # Find the sign position (+ or -)
            sign_pos = -1
            for i, char in enumerate(coord_clean):
                if char in ['+', '-']:
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
            dec_sign = 1 if dec_part[0] == '+' else -1
            dec_coords = dec_part[1:].strip()  # Remove sign

            dec_deg = float(dec_coords[:2]) * dec_sign
            dec_m = float(dec_coords[2:4])
            dec_s = float(dec_coords[4:]) if len(dec_coords) > 4 else 0.0

        except (ValueError, IndexError):
            return None, None
        return ra_to_deg(ra_h, ra_m, ra_s), dec_to_deg(dec_deg, dec_m, dec_s)

    def handle_multiples(key, values) -> dict:
        discoverers = set()
        components = {}
        result = {}
        descriptions = []
        for i, value in enumerate(values):
            mag1 = round(value["Mag_First"].item(), 2)
            mag2 = round(value["Mag_Second"].item(), 2)
            if i == 0:
                # Validate RA/DEC in the first (primary) object
                if value['ra'] is None or value['dec'] is None or np.isnan(value['ra']) or np.isnan(value['dec']):
                    logging.error(f"Empty or invalid RA/DEC in handle_multiples for WDS object '{key}'")
                    logging.error(f"  Primary object RA: {value['ra']}, DEC: {value['dec']}")
                    logging.error(f"  Coordinates_2000: '{value['Coordinates_2000']}'")
                    logging.error(f"  Coordinates_Arcsec: '{value['Coordinates_Arcsec']}'")
                    raise ValueError(f"Invalid RA/DEC coordinates for primary WDS object '{key}': RA={value['ra']}, DEC={value['dec']}")
                result["ra"] = value["ra"]
                result["dec"] = value["dec"]
                result["mag"] = MagnitudeObject([mag1, mag2])
                sizemax = np.max([value["Sep_First"], value["Sep_Last"]])
                result["size"] = str(round(sizemax, 1))
            discoverers.add(value["Discoverer_Number"])
            notes = value["Notes"].strip()
            notes_str = "" if len(notes) == 0 else f" Notes: {notes}"
            components = value["Components"].strip()
            components_str = "" if len(components) == 0 else f"{components}: "
            pa = value["PA_Last"]
            pa_str = f", PA={pa} ({value['Date_Last']})"
            sep = value["Sep_Last"].item()
            sep_str = f", Sep={sep}"
            mag_str = f"Mag={mag1}/{mag2}"

            descriptions.append(
                f"{components_str}{mag_str}{pa_str}{sep_str}{notes_str}"
            )

        result["discoverers"] = list(discoverers)
        result["name"] = key
        result["description"] = "\n".join(descriptions)
        return result

    # Add coordinate columns to the numpy array
    new_dtype = data.dtype.descr + [("ra", "f8"), ("dec", "f8")]
    new_data = np.empty(data.shape, dtype=new_dtype)

    # Copy existing data
    for name in data.dtype.names:
        new_data[name] = data[name]

    # Replace the old data with the new data
    data = new_data

    # Parse coordinates on demand and assign final values
    for i, entry in enumerate(data):
        # Try arcsecond coordinates first
        ra_arcsec, dec_arcsec = parse_coordinates_arcsec(entry["Coordinates_Arcsec"])

        if ra_arcsec is not None and dec_arcsec is not None:
            entry["ra"] = ra_arcsec
            entry["dec"] = dec_arcsec
        else:
            # Fall back to 2000 coordinates
            ra_2000, dec_2000 = parse_coordinates_2000(entry["Coordinates_2000"])
            entry["ra"] = ra_2000
            entry["dec"] = dec_2000

        # Validate RA/DEC values are not empty/invalid
        if entry['ra'] is None or entry['dec'] is None or np.isnan(entry['ra']) or np.isnan(entry['dec']):
            coord_2000 = entry['Coordinates_2000']
            coord_arcsec = entry['Coordinates_Arcsec']
            logging.error(f"Empty or invalid RA/DEC detected for WDS object at line {i+1}")
            logging.error(f"  Coordinates_2000: '{coord_2000}'")
            logging.error(f"  Coordinates_Arcsec: '{coord_arcsec}'")
            logging.error(f"  Parsed RA_2000: {ra_2000[i]}, DEC_2000: {dec_2000[i]}")
            logging.error(f"  Parsed RA_arcsec: {ra_arcsec[i]}, DEC_arcsec: {dec_arcsec[i]}")
            logging.error(f"  Final RA: {entry['ra']}, DEC: {entry['dec']}")
            raise ValueError(f"Invalid RA/DEC coordinates for WDS object at line {i+1}: RA={entry['ra']}, DEC={entry['dec']}")

    # make a dictionary of WDS objects to group duplicates
    wds_dict = defaultdict(list)

    for line, entry in enumerate(tqdm(data, total=len(data))):
        wds_dict[entry["Coordinates_2000"]].append(entry)

    seq = 1
    for key, value in tqdm(wds_dict.items(), total=len(wds_dict.items())):
        current_result = handle_multiples(key, value)
        wds_name = f"WDS J{current_result['name']}"
        clean_discoverers = [
            trim_string(name) for name in current_result["discoverers"]
        ]
        new_object = NewCatalogObject(
            object_type=obj_type,
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
        seq += 1

    insert_catalog_max_sequence(catalog)

    # Restore SQLite settings
    conn.execute("PRAGMA synchronous = FULL")
    conn.execute("PRAGMA journal_mode = DELETE")

    conn.commit()
