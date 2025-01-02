from dataclasses import dataclass
from dataclasses_json import dataclass_json
from typing import Union


@dataclass
class Eyepiece:
    make: str
    name: str
    focal_length_mm: float
    afov: int
    field_stop: float = 0

    def __str__(self):
        return f"{self.focal_length_mm}mm {self.name}"


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
    active_telescope_index: int = -1
    active_eyepiece_index: int = -1

    def set_active_telescope(self, telescope: Telescope):
        self.active_telescope_index = self.telescopes.index(telescope)

    def set_active_eyepiece(self, eyepiece: Eyepiece):
        self.active_eyepiece_index = self.eyepieces.index(eyepiece)

    @property
    def active_telescope(self):
        try:
            return self.telescopes[self.active_telescope_index]
        except (IndexError, TypeError):
            return None

    @property
    def active_eyepiece(self):
        try:
            return self.eyepieces[self.active_eyepiece_index]
        except (IndexError, TypeError):
            return None

    def cycle_eyepieces(self, direction: int) -> Eyepiece:
        self.active_eyepiece_index += direction
        if self.active_eyepiece_index >= len(self.eyepieces):
            self.active_eyepiece_index = 0

        if self.active_eyepiece_index < 0:
            self.active_eyepiece_index = len(self.eyepieces) - 1

        return self.active_eyepiece

    def calc_magnification(
        self,
        telescope: Union[None, Telescope] = None,
        eyepiece: Union[None, Eyepiece] = None,
    ) -> float:
        """
        Returns calculated magnification for a specific telescope/eyepiece combination
        If no telescope or eyepiece are provided, use the current active selections

        returns -1 if unable to calculate
        """
        if telescope is None:
            telescope = self.active_telescope

        if eyepiece is None:
            eyepiece = self.active_eyepiece

        if eyepiece is None or telescope is None:
            return -1

        return telescope.focal_length_mm / eyepiece.focal_length_mm

    def calc_tfov(
        self,
        telescope: Union[None, Telescope] = None,
        eyepiece: Union[None, Eyepiece] = None,
    ) -> float:
        """
        Returns calculated true field of view for a specific telescope/eyepiece combination
        If no telescope or eyepiece are provided, use the current active selections

        returns -1 if unable to calculate
        """
        if telescope is None:
            telescope = self.active_telescope

        if eyepiece is None:
            eyepiece = self.active_eyepiece

        if eyepiece is None or telescope is None:
            return -1

        if eyepiece.field_stop == 0:
            return eyepiece.afov / self.calc_magnification(telescope, eyepiece)
        else:
            return eyepiece.field_stop / telescope.focal_length_mm * 57.2958
