from dataclasses import dataclass
from dataclasses_json import dataclass_json
from typing import Union


@dataclass
class Eyepiece:
    make: str
    name: str
    focal_length: int
    afov: int
    field_stop: float


@dataclass
class Telescope:
    make: str
    name: str
    aperture_mm: int
    focal_length_mm: int
    obstruction_perc: float
    mount_type: str
    flip_image: bool
    flop_image: bool
    reverse_arrow_a: bool
    reverse_arrow_b: bool


@dataclass_json
@dataclass
class Equipment:
    telescopes: list[Telescope]
    eyepieces: list[Eyepiece]
    active_telescope: Union[None, Telescope] = None
    active_eyepiece: Union[None, Eyepiece] = None
