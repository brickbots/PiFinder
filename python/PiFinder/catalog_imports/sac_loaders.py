"""
Saguaro Astronomy Club (SAC) catalog loaders for PiFinder.

This module loads various SAC catalogs including asterisms, multistars, and red stars.
"""

import logging
import re
from pathlib import Path
from typing import List, Optional, Tuple
from tqdm import tqdm

import PiFinder.utils as utils
from PiFinder.composite_object import MagnitudeObject, SizeObject
from PiFinder.calc_utils import ra_to_deg, dms_to_dec
from .catalog_import_utils import (
    NewCatalogObject,
    delete_catalog_from_database,
    insert_catalog,
    insert_catalog_max_sequence,
    trim_string,
)

# Import shared database object
from .database import objects_db


def parse_sac_dec(raw: str) -> float:
    """SAC's "+42 06" or "-00 18" to degrees.

    The sign is read on its own, so a declination between -1° and 0° (Mintaka,
    δ Ori at "-00 18") stays south, which int("-00") cannot represent.
    """
    degrees, minutes = raw.split()
    sign = "-" if degrees.startswith("-") else "+"
    return dms_to_dec(sign, int(degrees.lstrip("+-")), int(minutes), 0)


# A variable's magnitude as SAC writes it: "2 v" is Mira at its maximum.
_VARIABLE_MAG_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*v")
# The range a note gives for a primary SAC lists only as "var.":
# "Primary is carbon star; mag var 8.0-8.5".
_NOTE_RANGE_RE = re.compile(r"mag var (\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)")


def parse_sac_magnitude(raw: str, notes: str = "") -> Optional[float]:
    """One magnitude field of the SAC double-star file, or None if it gives none.

    A number reads as itself. A variable reads as its maximum: "2 v" is 2.0,
    and "var." takes the brighter end of the range the row's note gives
    ("mag var 8.0-8.5" is 8.0). "var." without a range, "Var" and a blank
    field give no magnitude.
    """
    raw = raw.strip()
    if utils.is_number(raw):
        return float(raw)
    variable = _VARIABLE_MAG_RE.fullmatch(raw)
    if variable:
        return float(variable.group(1))
    if raw.lower() == "var.":
        note_range = _NOTE_RANGE_RE.search(notes)
        if note_range:
            return float(note_range.group(1))
    return None


def sac_pair_magnitudes(
    mag1: str, mag2: str, notes: str = ""
) -> Tuple[List[float], Optional[float]]:
    """A SAC pair's [primary, companion] magnitudes, and a companion left over.

    A row that leaves the primary's magnitude blank (ν Sco's AC and CD rows
    follow its AB row) gives no magnitude for the star, so the companion's
    stays off it: it is returned on its own, for the description.
    """
    primary = parse_sac_magnitude(mag1, notes)
    companion = parse_sac_magnitude(mag2)
    if primary is None:
        return [], companion
    return [primary] + ([companion] if companion is not None else []), None


def is_rejected_pair(name: str, notes: str) -> bool:
    """Whether SAC marks a row's pair as rejected ("STT 56 rej.", σ Per)."""
    return "rej." in name or "rej." in notes


def _parse_sac_asterism_size(raw: str) -> SizeObject:
    """Parse SAC asterism size strings like '3d X 2.4d', '10x5', '20deg x 15deg'.

    Values with 'd', 'deg', or '°' are degrees; plain numbers are arcminutes.
    """
    cleaned = raw.strip().replace(" ", "").replace("X", "x")
    if not cleaned:
        return SizeObject([])
    parts = cleaned.split("x")
    values = []
    is_degrees = False
    for p in parts:
        p = p.strip()
        if "deg" in p or "°" in p or p.endswith("d"):
            is_degrees = True
            p = p.replace("deg", "").replace("°", "").rstrip("d")
        try:
            values.append(float(p))
        except ValueError:
            return SizeObject([])
    if not values:
        return SizeObject([])
    if is_degrees:
        return SizeObject.from_degrees(*values)
    return SizeObject.from_arcmin(*values)


def load_sac_asterisms():
    """Load the SAC Asterisms catalog"""
    logging.info("Loading SAC Asterisms")
    catalog = "SaA"
    conn, _ = objects_db.get_conn_cursor()
    delete_catalog_from_database(catalog)
    insert_catalog(catalog, Path(utils.astro_data_dir, "sac.desc"))

    saca = Path(utils.astro_data_dir, "SAC_Asterisms_Ver32_Fence.txt")
    sequence = 0

    # Prepare objects for batch insertion
    objects_to_insert = []
    # Create shared ObjectFinder to avoid recreating for each object
    from .catalog_import_utils import ObjectFinder

    shared_finder = ObjectFinder()

    with open(saca, "r") as df:
        df.readline()
        obj_type = "Ast"
        for line in tqdm(list(df), leave=False):
            dfs = line.split("|")
            dfs = [d.strip() for d in dfs]
            other_names = dfs[1].strip()
            if other_names == "":
                continue
            else:
                sequence += 1

            logging.debug(
                f"---------------> SAC Asterisms {sequence=} <---------------"
            )
            ra = dfs[3].strip()
            dec = dfs[4].strip()
            mag = dfs[5].strip()
            if mag == "none":
                mag = MagnitudeObject([])
            else:
                mag = MagnitudeObject([float(mag)])
            size = _parse_sac_asterism_size(dfs[6])
            desc = dfs[9].strip()

            ra = ra.split()
            ra_h = int(ra[0])
            ra_m = float(ra[1])
            ra_deg = ra_to_deg(ra_h, ra_m, 0)

            dec_deg = parse_sac_dec(dec)

            new_object = NewCatalogObject(
                object_type=obj_type,
                catalog_code=catalog,
                sequence=sequence,
                ra=ra_deg,
                dec=dec_deg,
                mag=mag,
                size=size,
                description=desc,
                aka_names=[other_names],
            )
            objects_to_insert.append(new_object)

    # Batch insert all objects
    objects_db.bulk_mode = True
    # Set up shared finder for performance
    NewCatalogObject.set_shared_finder(shared_finder)
    try:
        for obj in tqdm(
            objects_to_insert, desc="Inserting SAC Asterisms objects", leave=False
        ):
            obj.insert()
        conn.commit()
    finally:
        objects_db.bulk_mode = False
        NewCatalogObject.clear_shared_finder()

    insert_catalog_max_sequence(catalog)


def load_sac_multistars():
    """Load the SAC Multistars catalog"""
    logging.info("Loading SAC Multistars")
    catalog = "SaM"
    conn, _ = objects_db.get_conn_cursor()
    delete_catalog_from_database(catalog)
    sam_path = Path(utils.astro_data_dir, "SAC_Multistars_Ver40")
    insert_catalog(catalog, sam_path / "sacm.desc")
    saca = sam_path / "SAC_DBL40_Fence.txt"
    sequence = 0

    # Prepare objects for batch insertion
    objects_to_insert = []
    # Create shared ObjectFinder to avoid recreating for each object
    from .catalog_import_utils import ObjectFinder

    shared_finder = ObjectFinder()

    with open(saca, "r") as df:
        df.readline()
        obj_type = "D*"
        for line in tqdm(list(df), leave=False):
            dfs = line.split("|")
            # Early skip for empty records
            if len(dfs) < 12:
                continue

            # Only process the name field we need
            name = [dfs[2].strip()]
            other_names = dfs[6].strip().split(";")
            name.extend(other_names)
            name = [trim_string(x.strip()) for x in name if x != ""]
            if not name:
                continue
            sequence += 1

            notes = dfs[11].strip()
            # A rejected pair is no double star (σ Per's "STT 56 rej."). Its
            # sequence number stays taken, so every later SaM designator
            # keeps naming the row it always has.
            if is_rejected_pair(dfs[2], notes):
                logging.debug("SaM %d is a rejected pair: skipped", sequence)
                continue

            # Removed debug logging for performance
            # Process only the fields we need (avoid full strip)
            ra = dfs[3].strip()
            dec = dfs[4].strip()
            components = dfs[5].strip()

            mag_list, companion_mag = sac_pair_magnitudes(dfs[7], dfs[8], notes)
            mag = MagnitudeObject(mag_list)

            sep = dfs[9].strip()
            pa = dfs[10].strip()
            desc = notes
            desc += f"\nComponents: {components}" if components else ""
            desc += f"\nPA: {pa}°" if pa else ""
            if companion_mag is not None:
                desc += f"\nCompanion mag {companion_mag:g}"

            ra = ra.split()
            ra_h = int(ra[0])
            ra_m = float(ra[1])
            ra_deg = ra_to_deg(ra_h, ra_m, 0)

            dec_deg = parse_sac_dec(dec)

            if sep and utils.is_number(sep):
                size = SizeObject.from_arcsec(float(sep))
            else:
                size = SizeObject([])

            new_object = NewCatalogObject(
                object_type=obj_type,
                catalog_code=catalog,
                sequence=sequence,
                ra=ra_deg,
                dec=dec_deg,
                mag=mag,
                size=size,
                description=desc,
                aka_names=name,
            )
            objects_to_insert.append(new_object)

    # Batch insert all objects
    objects_db.bulk_mode = True
    # Set up shared finder for performance
    NewCatalogObject.set_shared_finder(shared_finder)
    try:
        for obj in tqdm(
            objects_to_insert, desc="Inserting SAC Multistars objects", leave=False
        ):
            obj.insert()
        conn.commit()
    finally:
        objects_db.bulk_mode = False
        NewCatalogObject.clear_shared_finder()

    insert_catalog_max_sequence(catalog)


def load_sac_redstars():
    """Load the SAC Red Stars catalog"""
    logging.info("Loading SAC Redstars")
    catalog = "SaR"
    conn, _ = objects_db.get_conn_cursor()
    delete_catalog_from_database(catalog)

    sam_path = Path(utils.astro_data_dir, "SAC_RedStars_Ver20")
    insert_catalog(catalog, sam_path / "sacr.desc")
    sac = sam_path / "SAC_RedStars_ver20_FENCE.TXT"
    sequence = 0

    # Prepare objects for batch insertion
    objects_to_insert = []
    # Create shared ObjectFinder to avoid recreating for each object
    from .catalog_import_utils import ObjectFinder

    shared_finder = ObjectFinder()

    with open(sac, "r") as df:
        df.readline()
        obj_type = "D*"
        for line in tqdm(list(df), leave=False):
            dfs = line.split("|")
            dfs = [d.strip() for d in dfs]
            name = [dfs[1].strip()]
            other_names = dfs[2].strip().split(";")
            name.extend(other_names)
            name = [trim_string(x.strip()) for x in name if x != ""]
            if not name:
                continue
            else:
                sequence += 1

            logging.debug(
                f"---------------> SAC Red Stars {sequence=} <---------------"
            )
            ra = dfs[4].strip()
            dec = dfs[5].strip()
            size = SizeObject([])
            mag = dfs[6].strip()
            if mag == "none":
                mag = MagnitudeObject([])
            else:
                mag = MagnitudeObject([float(mag)])
            bv = dfs[7].strip()
            spec = dfs[8].strip()
            notes = dfs[9].strip()
            desc = notes
            desc += f"\nB-V: {bv}"
            desc += f", Spec: {spec}"

            ra = ra.split(" ")
            ra_h = int(ra[0])
            ra_m = float(ra[1])
            ra_deg = ra_to_deg(ra_h, ra_m, 0)

            dec_deg = parse_sac_dec(dec)

            new_object = NewCatalogObject(
                object_type=obj_type,
                catalog_code=catalog,
                sequence=sequence,
                ra=ra_deg,
                dec=dec_deg,
                mag=mag,
                size=size,
                description=desc,
                aka_names=name,
            )
            objects_to_insert.append(new_object)

    # Batch insert all objects
    objects_db.bulk_mode = True
    # Set up shared finder for performance
    NewCatalogObject.set_shared_finder(shared_finder)
    try:
        for obj in tqdm(
            objects_to_insert, desc="Inserting SAC RedStars objects", leave=False
        ):
            obj.insert()
        conn.commit()
    finally:
        objects_db.bulk_mode = False
        NewCatalogObject.clear_shared_finder()

    insert_catalog_max_sequence(catalog)
