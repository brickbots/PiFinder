# CompositeObject class
from dataclasses import dataclass, field
import numpy as np
import json
from typing import List
from PiFinder.utils import is_number


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
    size: str = field(default="")
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
