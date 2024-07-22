# CompositeObject class
from dataclasses import dataclass, field
import numpy as np
import json
from PiFinder.utils import is_number
from typing import List


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
            self.filter_mag = np.mean(np.array(self._filter_floats()))
        else:
            self.filter_mag = self.UNKNOWN_MAG

    def _filter_floats(self):
        return [float(x) for x in self.mags if is_number(x)]

    def calc_two_mag_representation(self):
        """reduce the mags to a string with max 2 values"""
        if len(self.mags) == 0 or self.filter_mag == self.UNKNOWN_MAG:
            return "-"
        elif len(self.mags) == 1:
            return self.mags[0]
        else:
            filtered = self._filter_floats()
            return f"{np.min(filtered)}/{np.max(filtered)}"

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
    image_name: str = field(default="")
    logged: bool = field(default=False)
    last_filtered_time: float = 0
    last_filtered_result: bool = True

    @classmethod
    def from_dict(cls, d):
        return cls(**d)

    @property
    def display_name(self):
        """
        Returns the display name for this object
        """
        return f"{self.catalog_code} {self.sequence}"
