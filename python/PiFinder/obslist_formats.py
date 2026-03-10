"""
Common observing list format library.

Reads and writes astronomical observing lists in multiple formats:
- SkySafari (.skylist)
- CSV (.csv)
- Plain Text (.txt)
- Stellarium (.sol)
- Autostar Tour (.txt)
- Argo Navis (.txt)
- NexTour (.hct)
- EQMOD Tour (.lst)
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
from dataclasses import dataclass, field
from typing import Optional


# ── Data model ──────────────────────────────────────────────────────────


@dataclass
class ObsListEntry:
    """Common interchange format for a single observing list object."""

    name: str
    ra: float  # RA in degrees (0-360), J2000
    dec: float  # Dec in degrees (-90 to +90), J2000
    obj_type: str = ""
    mag: Optional[float] = None
    catalog_code: str = ""
    sequence: int = 0
    description: str = ""
    catalog_names: list[str] = field(default_factory=list)


@dataclass
class ObsList:
    """An observing list with a name and list of entries."""

    name: str
    entries: list[ObsListEntry] = field(default_factory=list)


# ── Supported extensions ────────────────────────────────────────────────

SUPPORTED_EXTENSIONS = (".skylist", ".csv", ".sol", ".hct", ".lst", ".txt", ".mtf")


# ── Coordinate helpers ──────────────────────────────────────────────────


def ra_to_hms(ra_deg: float) -> tuple[int, int, float]:
    """Convert RA in degrees to (hours, minutes, seconds)."""
    hours = ra_deg / 15.0
    h = int(hours)
    rem = (hours - h) * 60
    m = int(rem)
    s = (rem - m) * 60
    return h, m, s


def dec_to_dms(dec_deg: float) -> tuple[str, int, int, float]:
    """Convert Dec in degrees to (sign, degrees, arcminutes, arcseconds)."""
    sign = "+" if dec_deg >= 0 else "-"
    abs_dec = abs(dec_deg)
    d = int(abs_dec)
    rem = (abs_dec - d) * 60
    m = int(rem)
    s = (rem - m) * 60
    return sign, d, m, s


def hms_to_ra(h: int, m: int, s: float) -> float:
    """Convert (hours, minutes, seconds) to RA in degrees."""
    return (h + m / 60.0 + s / 3600.0) * 15.0


def dms_to_dec(sign: str, d: int, m: int, s: float) -> float:
    """Convert (sign, degrees, arcminutes, arcseconds) to Dec in degrees."""
    dec = d + m / 60.0 + s / 3600.0
    if sign == "-":
        dec = -dec
    return dec


def format_ra_string(ra: float) -> str:
    h, m, s = ra_to_hms(ra)
    return f"{h}h {m}m {s:.1f}s"


def format_dec_string(dec: float) -> str:
    sign, d, m, s = dec_to_dms(dec)
    return f'{sign}{d}\u00b0 {m}\' {round(s)}"'


def _parse_ra_string(s: str) -> float:
    """Parse RA from 'Xh Xm X.Xs' format to degrees."""
    match = re.match(r"(\d+)h\s+(\d+)m\s+([\d.]+)s", s.strip())
    if match:
        return hms_to_ra(
            int(match.group(1)), int(match.group(2)), float(match.group(3))
        )
    return 0.0


def _parse_dec_string(s: str) -> float:
    """Parse Dec from '+/-X deg X' X"' format to degrees."""
    match = re.match(r"([+-]?)(\d+)[°]\s*(\d+)['']\s*(\d+)", s.strip())
    if match:
        sign = match.group(1) or "+"
        return dms_to_dec(
            sign, int(match.group(2)), int(match.group(3)), float(match.group(4))
        )
    return 0.0


_TOUR_MARKERS = {"end of tour", "end of list", "end tour"}


def _is_tour_marker(name: str) -> bool:
    return name.strip().lower() in _TOUR_MARKERS


def _parse_hms_colon(s: str) -> float:
    """Parse RA from 'HH:MM:SS' to degrees."""
    parts = s.strip().split(":")
    if len(parts) == 3:
        return hms_to_ra(int(parts[0]), int(parts[1]), float(parts[2]))
    return 0.0


def _parse_dms_colon(s: str) -> float:
    """Parse Dec from '(+/-)DD:MM:SS' to degrees."""
    s = s.strip()
    sign = "+"
    if s.startswith("-"):
        sign = "-"
        s = s[1:]
    elif s.startswith("+"):
        s = s[1:]
    parts = s.split(":")
    if len(parts) == 3:
        return dms_to_dec(sign, int(parts[0]), int(parts[1]), float(parts[2]))
    return 0.0


def _parse_catalog_name(name: str) -> tuple[str, int]:
    """Extract catalog code and sequence from 'NGC 224' or 'NGC224' or 'Sh2 155'."""
    name = name.strip()
    # With space: "NGC 7640", "Sh2 155", "Messier 31"
    match = re.match(r"([A-Za-z]+\d*[A-Za-z]*)\s+(\d+)$", name)
    if match:
        return match.group(1), int(match.group(2))
    # No space: "NGC7640", "M31" — split at letter/digit boundary
    match = re.match(r"([A-Za-z]+)(\d+)$", name)
    if match:
        return match.group(1), int(match.group(2))
    return "", 0


# ── Type mapping tables ─────────────────────────────────────────────────

ARGO_TYPE_MAP: dict[str, str] = {
    "Gx": "GALAXY",
    "OC": "OPEN",
    "Gb": "GLOBULAR",
    "PN": "PLANETARY",
    "Nb": "NEBULA",
    "DN": "DARK",
    "*": "STAR",
    "D*": "DOUBLE",
    "***": "TRIPLE",
    "C+N": "NEBULA",
    "Kt": "NEBULA",
    "Ast": "ASTERISM",
    "Pla": "STAR",
    "CM": "COMET",
    "?": "USER",
}
ARGO_TYPE_MAP_INV: dict[str, str] = {}
for _k, _v in ARGO_TYPE_MAP.items():
    if _v not in ARGO_TYPE_MAP_INV:
        ARGO_TYPE_MAP_INV[_v] = _k

CELESTRON_TYPE_MAP: dict[str, str] = {
    "Gx": "Galaxy",
    "OC": "Open Cluster",
    "Gb": "Globular Cluster",
    "PN": "Planetary Nebula",
    "Nb": "Nebula",
    "DN": "Nebula",
    "*": "Star",
    "D*": "Double Star",
    "***": "Triple Star",
    "C+N": "Nebula",
    "Kt": "Nebula",
    "Ast": "Asterism",
    "Pla": "Star",
    "CM": "Star",
    "?": "Star",
}
CELESTRON_TYPE_MAP_INV: dict[str, str] = {}
for _k, _v in CELESTRON_TYPE_MAP.items():
    if _v not in CELESTRON_TYPE_MAP_INV:
        CELESTRON_TYPE_MAP_INV[_v] = _k

SKYSAFARI_CATALOG_NAMES: dict[str, str] = {
    "CAL": "C",
    "COL": "Cr",
}
SKYSAFARI_CATALOG_NAMES_INV: dict[str, str] = {
    v: k for k, v in SKYSAFARI_CATALOG_NAMES.items()
}


def _skylist_object_id(obj_type: str) -> str:
    if obj_type in ("*", "D*", "***"):
        return "2,-1,-1"
    if obj_type == "Pla":
        return "1,-1,-1"
    return "4,-1,-1"


# ── SkySafari (.skylist) ────────────────────────────────────────────────


def write_skylist(obs_list: ObsList) -> str:
    lines = ["SkySafariObservingListVersion=3.0"]
    for i, entry in enumerate(obs_list.entries):
        cat = SKYSAFARI_CATALOG_NAMES.get(entry.catalog_code, entry.catalog_code)
        catalog_num = (
            f"{cat} {entry.sequence}" if cat and entry.sequence else entry.name
        )
        lines.extend(
            [
                "SkyObject=BeginObject",
                f"  ObjectID={_skylist_object_id(entry.obj_type)}",
                f"  CatalogNumber={catalog_num}",
                f"  DefaultIndex={i}",
            ]
        )
        if entry.ra or entry.dec:
            lines.append(f"  EndObjectRA={entry.ra / 15.0}")
            lines.append(f"  EndObjectDec={entry.dec}")
        if entry.description:
            lines.append(f"  Comment={entry.description}")
        lines.append("EndObject=SkyObject")
    return "\n".join(lines) + "\n"


def read_skylist(text: str) -> ObsList:
    entries: list[ObsListEntry] = []
    catalog_numbers: list[str] = []
    comment = ""
    end_ra: Optional[float] = None
    end_dec: Optional[float] = None
    in_object = False

    for line in text.splitlines():
        line = line.strip()
        if line == "SkyObject=BeginObject":
            catalog_numbers = []
            comment = ""
            end_ra = None
            end_dec = None
            in_object = True
        elif line == "EndObject=SkyObject" and in_object:
            name = (
                catalog_numbers[0].strip()
                if catalog_numbers
                else f"OBJ {len(entries) + 1}"
            )
            catalog_code, sequence = _parse_catalog_name(name)
            ra = end_ra * 15.0 if end_ra is not None else 0.0
            dec = end_dec if end_dec is not None else 0.0
            entries.append(
                ObsListEntry(
                    name=name,
                    ra=ra,
                    dec=dec,
                    catalog_code=catalog_code,
                    sequence=sequence,
                    description=comment,
                    catalog_names=list(catalog_numbers),
                )
            )
            in_object = False
        elif line.startswith("CatalogNumber=") and in_object:
            catalog_numbers.append(line.split("=", 1)[1])
        elif line.startswith("Comment=") and in_object:
            comment = line.split("=", 1)[1].strip()
        elif line.startswith("EndObjectRA=") and in_object:
            try:
                end_ra = float(line.split("=", 1)[1])
            except ValueError:
                pass
        elif line.startswith("EndObjectDec=") and in_object:
            try:
                end_dec = float(line.split("=", 1)[1])
            except ValueError:
                pass

    return ObsList(name="", entries=entries)


# ── CSV (.csv) ──────────────────────────────────────────────────────────

_CSV_HEADER = "Name,RA,Dec,Magnitude,Type,CatalogCode,Sequence"


def write_csv(obs_list: ObsList) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Name", "RA", "Dec", "Magnitude", "Type", "CatalogCode", "Sequence"])
    for entry in obs_list.entries:
        mag_str = f"{entry.mag:.1f}" if entry.mag is not None else ""
        writer.writerow(
            [
                entry.name,
                format_ra_string(entry.ra),
                format_dec_string(entry.dec),
                mag_str,
                entry.obj_type,
                entry.catalog_code,
                entry.sequence,
            ]
        )
    return buf.getvalue()


def read_csv(text: str) -> ObsList:
    entries: list[ObsListEntry] = []
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        name = row.get("Name", "")
        ra_str = row.get("RA", "")
        dec_str = row.get("Dec", "")
        mag_str = row.get("Magnitude", "")
        obj_type = row.get("Type", "")
        catalog_code = row.get("CatalogCode", "")
        seq_str = row.get("Sequence", "0")

        ra = _parse_ra_string(ra_str) if ra_str else 0.0
        dec = _parse_dec_string(dec_str) if dec_str else 0.0
        mag: Optional[float] = None
        if mag_str:
            try:
                mag = float(mag_str)
            except ValueError:
                pass
        try:
            sequence = int(seq_str)
        except ValueError:
            sequence = 0

        entries.append(
            ObsListEntry(
                name=name,
                ra=ra,
                dec=dec,
                obj_type=obj_type,
                mag=mag,
                catalog_code=catalog_code,
                sequence=sequence,
            )
        )
    return ObsList(name="", entries=entries)


# ── Plain Text (.txt) ──────────────────────────────────────────────────


def write_text(obs_list: ObsList) -> str:
    return "\n".join(entry.name for entry in obs_list.entries) + "\n"


def read_text(text: str) -> ObsList:
    entries: list[ObsListEntry] = []
    for line in text.splitlines():
        name = line.strip()
        if not name:
            continue
        catalog_code, sequence = _parse_catalog_name(name)
        entries.append(
            ObsListEntry(
                name=name,
                ra=0.0,
                dec=0.0,
                catalog_code=catalog_code,
                sequence=sequence,
            )
        )
    return ObsList(name="", entries=entries)


# ── Stellarium (.sol) ──────────────────────────────────────────────────


def write_stellarium(obs_list: ObsList) -> str:
    data = {
        "version": "1.0",
        "shortName": obs_list.name,
        "description": "Exported from PiFinder",
        "objects": [
            {
                "designation": entry.name,
                "objtype": entry.obj_type,
                "ra": format_ra_string(entry.ra),
                "dec": format_dec_string(entry.dec),
                "magnitude": f"{entry.mag:.2f}" if entry.mag is not None else "",
            }
            for entry in obs_list.entries
        ],
    }
    return json.dumps(data, indent=2)


def read_stellarium(text: str) -> ObsList:
    data = json.loads(text)
    name = data.get("shortName", "")
    entries: list[ObsListEntry] = []
    for obj in data.get("objects", []):
        designation = obj.get("designation", "")
        obj_type = obj.get("objtype", "")
        ra = _parse_ra_string(obj.get("ra", ""))
        dec = _parse_dec_string(obj.get("dec", ""))
        mag: Optional[float] = None
        mag_str = obj.get("magnitude", "")
        if mag_str:
            try:
                mag = float(mag_str)
            except ValueError:
                pass
        catalog_code, sequence = _parse_catalog_name(designation)
        entries.append(
            ObsListEntry(
                name=designation,
                ra=ra,
                dec=dec,
                obj_type=obj_type,
                mag=mag,
                catalog_code=catalog_code,
                sequence=sequence,
            )
        )
    return ObsList(name=name, entries=entries)


# ── Autostar Tour (.txt) ───────────────────────────────────────────────


def write_autostar(obs_list: ObsList) -> str:
    title = obs_list.name[:15]
    lines = ["/ PiFinder export", f'TITLE "{title}"']
    for entry in obs_list.entries:
        h, m, s = ra_to_hms(entry.ra)
        ra_str = f"{h:02d}:{m:02d}:{round(s):02d}"
        sign, d, dm, ds = dec_to_dms(entry.dec)
        sign_char = "-" if sign == "-" else ""
        dec_str = f"{sign_char}{d:02d}d{dm:02d}m{round(ds):02d}s"
        obj_title = entry.name[:16]
        mag_str = f" mag {entry.mag:.1f}" if entry.mag is not None else ""
        lines.append(f'USER {ra_str} {dec_str} "{obj_title}" "{entry.obj_type}{mag_str}"')
    return "\n".join(lines) + "\n"


def read_autostar(text: str) -> ObsList:
    entries: list[ObsListEntry] = []
    name = ""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("TITLE "):
            match = re.match(r'TITLE\s+"([^"]*)"', line)
            if match:
                name = match.group(1)
            continue
        if not line.startswith("USER "):
            continue
        # USER HH:MM:SS ±DDdMMmSSs "name" "type mag"
        match = re.match(
            r'USER\s+(\d{2}:\d{2}:\d{2})\s+([+-]?\d{1,2}d\d{2}m\d{2}s)\s+"([^"]*)"\s+"([^"]*)"',
            line,
        )
        if not match:
            continue
        ra = _parse_hms_colon(match.group(1))
        dec_str = match.group(2)
        dec_match = re.match(r"([+-]?)(\d+)d(\d+)m(\d+)s", dec_str)
        dec = 0.0
        if dec_match:
            dec_sign = "-" if dec_match.group(1) == "-" else "+"
            dec = dms_to_dec(
                dec_sign,
                int(dec_match.group(2)),
                int(dec_match.group(3)),
                float(dec_match.group(4)),
            )
        obj_name = match.group(3)
        type_mag = match.group(4)
        obj_type = ""
        mag: Optional[float] = None
        mag_match = re.match(r"(\S+)\s+mag\s+([\d.]+)", type_mag)
        if mag_match:
            obj_type = mag_match.group(1)
            try:
                mag = float(mag_match.group(2))
            except ValueError:
                pass
        else:
            obj_type = type_mag.strip()

        catalog_code, sequence = _parse_catalog_name(obj_name)
        entries.append(
            ObsListEntry(
                name=obj_name,
                ra=ra,
                dec=dec,
                obj_type=obj_type,
                mag=mag,
                catalog_code=catalog_code,
                sequence=sequence,
            )
        )
    return ObsList(name=name, entries=entries)


# ── Argo Navis (.txt) ──────────────────────────────────────────────────


def write_argo(obs_list: ObsList) -> str:
    lines: list[str] = []
    for entry in obs_list.entries:
        h, m, s = ra_to_hms(entry.ra)
        ra_str = f"{h:02d}:{m:02d}:{round(s):02d}"
        sign, d, dm, ds = dec_to_dms(entry.dec)
        dec_str = f"{sign}{d:02d}:{dm:02d}:{round(ds):02d}"
        atype = ARGO_TYPE_MAP.get(entry.obj_type, "USER")
        mag_str = f"{entry.mag:.1f}" if entry.mag is not None else "ANY"
        lines.append(f"{entry.name}|{ra_str}|{dec_str}|{atype}|{mag_str}|")
    return "\r\n".join(lines) + "\r\n"


def read_argo(text: str) -> ObsList:
    entries: list[ObsListEntry] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("|")
        if len(parts) < 5:
            continue
        obj_name = parts[0].strip()
        ra = _parse_hms_colon(parts[1])
        dec = _parse_dms_colon(parts[2])
        obj_type = ARGO_TYPE_MAP_INV.get(parts[3].strip(), "")
        mag: Optional[float] = None
        mag_str = parts[4].strip()
        if mag_str and mag_str != "ANY":
            try:
                mag = float(mag_str)
            except ValueError:
                pass
        catalog_code, sequence = _parse_catalog_name(obj_name)
        entries.append(
            ObsListEntry(
                name=obj_name,
                ra=ra,
                dec=dec,
                obj_type=obj_type,
                mag=mag,
                catalog_code=catalog_code,
                sequence=sequence,
            )
        )
    return ObsList(name="", entries=entries)


# ── NexTour (.hct) ─────────────────────────────────────────────────────


def write_nextour(obs_list: ObsList) -> str:
    lines: list[str] = []
    for entry in obs_list.entries:
        ra_hours = entry.ra / 15.0
        ra_h = int(ra_hours)
        ra_m = (ra_hours - ra_h) * 60
        dec_sign = "+" if entry.dec >= 0 else "-"
        dec_abs = abs(entry.dec)
        dec_d = int(dec_abs)
        dec_m = (dec_abs - dec_d) * 60
        category = entry.catalog_code or "User"
        obj_num = str(entry.sequence) if entry.sequence else ""
        ctype = CELESTRON_TYPE_MAP.get(entry.obj_type, "Star")
        mag_str = f"{entry.mag:.1f}" if entry.mag is not None else ""
        lines.append(
            f"{category}#{obj_num}#{entry.name}#{ctype}#{mag_str}#"
            f"#{ra_h}#{ra_m:.1f}#{dec_sign}#{dec_d}#{dec_m:.1f}#"
        )
    return "\r\n".join(lines) + "\r\n"


def _detect_nextour_variant(text: str) -> str:
    """Detect which NexTour variant: 'coord_first' or 'catalog_first'."""
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # CSOG variant starts with HH:MM:SS
        if re.match(r"\d{2}:\d{2}:\d{2}", line):
            return "coord_first"
        return "catalog_first"
    return "catalog_first"


def _read_nextour_coord_first(text: str) -> ObsList:
    """Parse CSOG-style NexTour: RA#±Dec#Name#..."""
    entries: list[ObsListEntry] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("#")
        if len(parts) < 3:
            continue
        ra_str = parts[0].strip()
        dec_str = parts[1].strip()
        obj_name = parts[2].strip()
        if not obj_name or not re.match(r"\d{2}:\d{2}:", ra_str):
            continue
        ra = _parse_hms_colon(ra_str)
        dec = _parse_dms_colon(dec_str)
        if _is_tour_marker(obj_name):
            continue
        catalog_code, sequence = _parse_catalog_name(obj_name)
        entries.append(
            ObsListEntry(
                name=obj_name,
                ra=ra,
                dec=dec,
                catalog_code=catalog_code,
                sequence=sequence,
            )
        )
    return ObsList(name="", entries=entries)


def _read_nextour_catalog_first(text: str) -> ObsList:
    """Parse web-export NexTour: category#objNum#name#type#mag##raH#raM#sign#decD#decM#"""
    entries: list[ObsListEntry] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("#")
        if len(parts) < 12:
            continue
        category = parts[0].strip()
        obj_num_str = parts[1].strip()
        obj_name = parts[2].strip()
        ctype = parts[3].strip()
        mag_str = parts[4].strip()
        # parts[5] is empty (double hash)
        ra_h_str = parts[6].strip()
        ra_m_str = parts[7].strip()
        dec_sign = parts[8].strip()
        dec_d_str = parts[9].strip()
        dec_m_str = parts[10].strip()

        try:
            ra_h = int(ra_h_str)
            ra_m = float(ra_m_str)
            ra = (ra_h + ra_m / 60.0) * 15.0
        except ValueError:
            ra = 0.0
        try:
            dec_d = int(dec_d_str)
            dec_m = float(dec_m_str)
            dec = dec_d + dec_m / 60.0
            if dec_sign == "-":
                dec = -dec
        except ValueError:
            dec = 0.0

        obj_type = CELESTRON_TYPE_MAP_INV.get(ctype, "")
        mag: Optional[float] = None
        if mag_str:
            try:
                mag = float(mag_str)
            except ValueError:
                pass
        try:
            obj_num = int(obj_num_str)
        except ValueError:
            obj_num = 0

        catalog_code = category if category != "User" else ""
        entries.append(
            ObsListEntry(
                name=obj_name,
                ra=ra,
                dec=dec,
                obj_type=obj_type,
                mag=mag,
                catalog_code=catalog_code,
                sequence=obj_num,
            )
        )
    return ObsList(name="", entries=entries)


def read_nextour(text: str) -> ObsList:
    variant = _detect_nextour_variant(text)
    if variant == "coord_first":
        return _read_nextour_coord_first(text)
    return _read_nextour_catalog_first(text)


# ── EQMOD Tour (.lst) ──────────────────────────────────────────────────


def write_eqmod(obs_list: ObsList) -> str:
    lines = ["!J2000", f"# {obs_list.name} - exported from PiFinder"]
    for entry in obs_list.entries:
        ra_hours = entry.ra / 15.0
        lines.append(f"{ra_hours:.4f}; {entry.dec:.4f}; {entry.name}")
    return "\n".join(lines) + "\n"


def read_eqmod(text: str) -> ObsList:
    entries: list[ObsListEntry] = []
    name = ""
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("!"):
            continue
        if line.startswith("#"):
            if not name:
                name = line.lstrip("# ").split(" - ")[0].strip()
            continue
        parts = line.split(";")
        if len(parts) < 3:
            continue
        try:
            ra_hours = float(parts[0].strip())
            ra = ra_hours * 15.0
        except ValueError:
            continue
        try:
            dec = float(parts[1].strip())
        except ValueError:
            continue
        obj_name = parts[2].strip()
        if _is_tour_marker(obj_name):
            continue
        catalog_code, sequence = _parse_catalog_name(obj_name)
        entries.append(
            ObsListEntry(
                name=obj_name,
                ra=ra,
                dec=dec,
                catalog_code=catalog_code,
                sequence=sequence,
            )
        )
    return ObsList(name=name, entries=entries)


# ── Format detection ───────────────────────────────────────────────────

_FORMAT_BY_EXT: dict[str, str] = {
    ".skylist": "skylist",
    ".sol": "stellarium",
    ".hct": "nextour",
    ".lst": "eqmod",
    ".csv": "csv",
    ".mtf": "autostar",
}

_READERS: dict[str, object] = {
    "skylist": read_skylist,
    "csv": read_csv,
    "text": read_text,
    "stellarium": read_stellarium,
    "autostar": read_autostar,
    "argo": read_argo,
    "nextour": read_nextour,
    "eqmod": read_eqmod,
}

_WRITERS: dict[str, object] = {
    "skylist": write_skylist,
    "csv": write_csv,
    "text": write_text,
    "stellarium": write_stellarium,
    "autostar": write_autostar,
    "argo": write_argo,
    "nextour": write_nextour,
    "eqmod": write_eqmod,
}


def detect_format(text: str, filename: str = "") -> str:
    """Auto-detect observing list format by extension or content sniffing."""
    if filename:
        _, ext = os.path.splitext(filename.lower())
        fmt = _FORMAT_BY_EXT.get(ext)
        if fmt:
            return fmt

    stripped = text.lstrip()
    if "SkySafariObservingListVersion" in text:
        return "skylist"
    if stripped.startswith("{"):
        return "stellarium"
    if stripped.startswith("!J2000"):
        return "eqmod"
    # Check for pipe-delimited lines (Argo Navis)
    for line in text.splitlines()[:10]:
        line = line.strip()
        if line and not line.startswith("#") and line.count("|") >= 4:
            return "argo"
    # Check for USER lines (Autostar)
    for line in text.splitlines()[:20]:
        if line.strip().startswith("USER "):
            return "autostar"
    # Check for CSV header
    if stripped.startswith("Name,") or stripped.startswith('"Name"'):
        return "csv"

    return "text"


def read_file(path: str) -> ObsList:
    """Read an observing list file, auto-detecting the format."""
    with open(path, "r") as f:
        text = f.read()
    fmt = detect_format(text, os.path.basename(path))
    reader = _READERS.get(fmt, read_text)
    obs_list = reader(text)
    if not obs_list.name:
        obs_list.name = os.path.splitext(os.path.basename(path))[0]
    return obs_list


def write_file(obs_list: ObsList, path: str, fmt: str) -> None:
    """Write an observing list to a file in the specified format."""
    writer = _WRITERS.get(fmt)
    if not writer:
        raise ValueError(f"Unknown format: {fmt}")
    content = writer(obs_list)
    with open(path, "w") as f:
        f.write(content)
