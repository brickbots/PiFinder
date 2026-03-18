# CompositeObject class
from dataclasses import dataclass, field
import numpy as np
import json
import math
from typing import List, Union
from PiFinder.utils import is_number


class SizeObject:
    """Structured angular size for astronomical objects.

    All extents are stored internally in arcseconds.
    - []           -> unknown / point source
    - [d]          -> circular, diameter d
    - [major, minor] -> elliptical (major x minor axes)
    - [v1, v2, ...] -> polygon radial distances at equal angular intervals
    - [[ra,dec], ...] -> RA/Dec polyline vertices (degrees)
    - [[[ra,dec],[ra,dec]], ...] -> disconnected line segments (degrees)

    The geometry field disambiguates: "polyline" or "segments".
    """

    def __init__(
        self,
        extents: Union[List[float], List[List[float]]],
        position_angle: float = 0.0,
        geometry: str = "",
    ):
        self.extents: Union[List[float], List[List[float]]] = extents
        self.position_angle: float = position_angle
        self.geometry: str = geometry

    # --- mode detection ---

    @property
    def is_vertices(self) -> bool:
        """True for polyline vertices: [[ra,dec], ...]"""
        if not self.extents:
            return False
        if self.geometry == "segments":
            return False
        if self.geometry == "polyline":
            return True
        return isinstance(self.extents[0], (list, tuple))

    @property
    def is_segments(self) -> bool:
        """True for disconnected segments: [[[ra,dec],[ra,dec]], ...]"""
        if self.geometry == "segments":
            return True
        return False

    def _all_vertices(self) -> List[List[float]]:
        """Collect all RA/Dec vertices regardless of geometry type."""
        if self.is_segments:
            verts = []
            for seg in self.extents:
                verts.extend(seg)
            return verts
        if self.is_vertices:
            return self.extents
        return []

    @property
    def max_extent_arcsec(self) -> float:
        if not self.extents:
            return 0.0
        verts = self._all_vertices()
        if verts:
            max_sep = 0.0
            for i in range(len(verts)):
                for j in range(i + 1, len(verts)):
                    ra1, dec1 = math.radians(verts[i][0]), math.radians(verts[i][1])
                    ra2, dec2 = math.radians(verts[j][0]), math.radians(verts[j][1])
                    dra = ra2 - ra1
                    ddec = dec2 - dec1
                    cos_dec = math.cos((dec1 + dec2) / 2)
                    sep = math.sqrt((dra * cos_dec) ** 2 + ddec**2)
                    max_sep = max(max_sep, sep)
            return math.degrees(max_sep) * 3600.0
        return max(self.extents)

    # --- constructors ---

    @classmethod
    def from_arcmin(cls, *values: float, position_angle: float = 0.0) -> "SizeObject":
        return cls([v * 60.0 for v in values], position_angle=position_angle)

    @classmethod
    def from_arcsec(cls, *values: float, position_angle: float = 0.0) -> "SizeObject":
        return cls(list(values), position_angle=position_angle)

    @classmethod
    def from_degrees(cls, *values: float, position_angle: float = 0.0) -> "SizeObject":
        return cls([v * 3600.0 for v in values], position_angle=position_angle)

    @classmethod
    def from_vertices(cls, vertices: List[List[float]]) -> "SizeObject":
        return cls(vertices, position_angle=0.0)

    # --- serialization ---

    def to_json(self) -> str:
        return json.dumps({"e": self.extents, "p": self.position_angle})

    @classmethod
    def from_json(cls, json_str: str) -> "SizeObject":
        if not json_str:
            return cls([])
        parsed = json.loads(json_str)
        return cls(parsed["e"], position_angle=parsed.get("p", 0.0))

    # --- display ---

    def _format_value(self, arcsec: float, unit_suffix: str) -> str:
        """Format a single value, dropping .0 for whole numbers."""
        if unit_suffix == '"':
            val = arcsec
        elif unit_suffix == "'":
            val = arcsec / 60.0
        else:
            val = arcsec / 3600.0
        if val == int(val):
            return f"{int(val)}{unit_suffix}"
        return f"{val:.1f}{unit_suffix}"

    def _pick_unit(self, arcsec: float) -> str:
        """Choose display unit for a value in arcseconds."""
        if arcsec >= 3600.0:
            return "°"
        if arcsec >= 60.0:
            return "'"
        return '"'

    def to_display_string(self) -> str:
        if not self.extents:
            return ""
        if self.is_vertices or self.is_segments:
            extent = self.max_extent_arcsec
            return f"~{self._format_value(extent, self._pick_unit(extent))}"
        unit = self._pick_unit(max(self.extents))
        if len(self.extents) == 1:
            return self._format_value(self.extents[0], unit)
        if len(self.extents) == 2:
            a = self._format_value(self.extents[0], unit)
            b = self._format_value(self.extents[1], unit)
            # strip repeated unit suffix for compact display: 17'x8'
            return f"{a}x{b}"
        # 3+ extents: show max extent only with polygon marker
        return f"~{self._format_value(max(self.extents), unit)}"

    def __repr__(self) -> str:
        return f"SizeObject({self.extents})"

    def __str__(self) -> str:
        return self.to_display_string()


class MagnitudeObject:
    UNKNOWN_MAG: float = 99
    mags: List = []
    filter_mag: float = UNKNOWN_MAG

    def __init__(self, mags: list):
        self.mags = mags
        self.calc_filter_mag()

    def add(self, mag):
        self.mags.append(mag)
        self.calc_filter_mag()

    def calc_filter_mag(self):
        filtered = self._filter_floats()
        if len(filtered) > 0:
            self.filter_mag = float(np.mean(np.array(self._filter_floats())))
        else:
            self.filter_mag = self.UNKNOWN_MAG

    def _filter_floats(self) -> List[float]:
        """only used valid floats for magnitude"""
        return [float(x) for x in self.mags if is_number(x)]

    def calc_two_mag_representation(self):
        """reduce the mags to a string with max 2 values"""
        filtered = self._filter_floats()
        if len(filtered) == 0 or self.filter_mag == self.UNKNOWN_MAG:
            return "-"
        if len(filtered) == 1:
            return f"{filtered[0]:.1f}"
        else:
            return f"{np.min(filtered):.1f}/{np.max(filtered):.1f}"

    def to_json(self):
        return json.dumps({"mags": self.mags, "filter_mag": self.filter_mag})

    def __repr__(self):
        return f"MagnitudeObject({self.mags}, {self.filter_mag})"

    @classmethod
    def from_json(cls, json_str):
        data = json.loads(json_str)
        obj = cls(data["mags"])
        return obj


@dataclass
class CompositeObject:
    """A catalog object, augmented with related DB data"""

    # id is the primary key of the catalog_objects table
    id: int = field(default=-1)
    # object_id is the primary key of the objects table
    object_id: int = field(default=-1)
    obj_type: str = field(default="")
    # ra in degrees, J2000
    ra: float = field(default=0.0)
    # dec in degrees, J2000
    dec: float = field(default=0.0)
    const: str = field(default="")
    size: "SizeObject" = field(default_factory=lambda: SizeObject([]))
    mag: MagnitudeObject = field(default=MagnitudeObject([]))
    mag_str: str = field(default="")
    catalog_code: str = field(default="")
    # we want catalogs of M and NGC etc, so sequence should be a name like M 31
    # deduplicated from names. Catalog code stays, because this collection of
    # things has a name
    sequence: int = field(default=0)
    description: str = field(default="")
    names: list = field(default_factory=list)
    # Background loading support
    _details_loaded: bool = field(default=False)
    image_name: str = field(default="")
    surface_brightness: float = field(default=0.0)
    logged: bool = field(default=False)
    last_filtered_time: float = 0
    last_filtered_result: bool = True

    def __eq__(self, other):
        if not isinstance(other, CompositeObject):
            return NotImplemented
        return self.object_id == other.object_id

    def __hash__(self):
        return hash(self.object_id)

    @classmethod
    def from_dict(cls, d):
        return cls(**d)

    @property
    def display_name(self):
        """
        Returns the display name for this object
        """
        return f"{self.catalog_code} {self.sequence}"
