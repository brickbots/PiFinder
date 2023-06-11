import PiFinder.image_util as utils
from PiFinder.ui.fonts import Fonts as fonts
from typing import Tuple, List
import textwrap
import logging


class Catalog:
    def __init__(self):
        pass


class SpaceCalculator:
    def __init__(self, draw, width):
        self.draw = draw
        self.width = width
        pass

    def _calc_string(self, left, right, spaces) -> str:
        return f"{left}{'':.<{spaces}}{right}"

    def calculate_spaces(self, left, right) -> Tuple[int, str]:
        """
        returns number of spaces
        """
        spaces = 1
        if self.draw.textlength(self._calc_string(left, right, spaces)) > self.width:
            return -1, ""

        while self.draw.textlength(self._calc_string(left, right, spaces)) < self.width:
            spaces += 1

        spaces = spaces - 1

        result = self._calc_string(left, right, spaces)
        logging.debug(f"returning {spaces=}, {result=}")
        return spaces, result


class SpaceCalculatorFixed:
    def __init__(self, nr_chars):
        self.width = nr_chars

    def _calc_string(self, left, right, spaces) -> str:
        return f"{left}{'': <{spaces}}{right}"

    def calculate_spaces(self, left: str, right: str) -> Tuple[int, str]:
        """
        returns number of spaces
        """
        logging.debug(f"calculating spaces for {left=} {right=}")
        spaces = 1
        lenleft = len(str(left))
        lenright = len(str(right))

        if lenleft + lenright + 1 > self.width:
            return -1, ""

        spaces = self.width - (lenleft + lenright)
        result = self._calc_string(left, right, spaces)
        logging.debug(f"returning {spaces=}, {result=}")
        return spaces, result


class CatalogDesignator:
    """Holds the string that represents the catalog input/search field.
    Usually looks like 'NGC----' or 'M-13'"""

    # TODO this can be queried from the DB, get the max sequence for each catalog
    CAT_DASHES = {"NGC": 4, "M": 3, "IC": 3, "C": 3, "Col": 3, "SaA": 3}

    def __init__(self, catalog_names, catalog_index):
        self.catalog_names = catalog_names
        self.catalog_index = catalog_index
        self.object_number = 0
        self.field = self.get_designator()

    def set_target(self, catalog_index, number=0):
        self.catalog_index = catalog_index
        self.object_number = number
        self.field = self.get_designator()

    def append_number(self, number):
        number_str = str(self.object_number) + str(number)
        if len(number_str) > self.get_catalog_width():
            number_str = number_str[1:]
        self.object_number = int(number_str)
        self.field = self.get_designator()

    def set_number(self, number):
        self.object_number = number
        self.field = self.get_designator()

    def reset_number(self):
        self.object_number = 0
        self.field = self.get_designator()

    def increment_number(self):
        self.object_number += 1
        self.field = self.get_designator()

    def decrement_number(self):
        self.object_number -= 1
        self.field = self.get_designator()

    def next_catalog(self):
        self.catalog_index = (self.catalog_index + 1) % len(self.catalog_names)
        self.object_number = 0
        self.field = self.get_designator()
        return self.catalog_index

    def get_catalog_name(self):
        print("get_catalog_name", self.catalog_names, self.catalog_index)
        return self.catalog_names[self.catalog_index]

    def get_catalog_width(self):
        print(self.get_catalog_name())
        return self.CAT_DASHES[self.get_catalog_name()]

    def get_designator(self):
        number_str = str(self.object_number) if self.object_number > 0 else ""
        return f"{self.get_catalog_name(): >3}{number_str:->{self.get_catalog_width()}}"

    def __str__(self):
        return self.field


class TextLayouterSimple:
    def __init__(self, text: str, draw, color, font=fonts.base, width=fonts.base_width, max_lines=3):
        self.text = text
        self.font = font
        self.color = color
        self.width = width
        self.max_lines = max_lines
        self.drawobj = draw
        self.object_text: List[str] = []
        self.updated = True

    def set_text(self, text):
        self.text = text
        self.updated = True

    def set_color(self, color):
        self.color = color
        self.updated = True

    def layout(self, pos: Tuple[int, int] = (0, 0)):
        if self.updated:
            self.object_text: List[str] = [self.text]
            self.updated = False

    def draw(self, pos: Tuple[int, int] = (0, 0)):
        self.layout(pos)
        logging.debug(f"Drawing {self.object_text=}")
        self.drawobj.multiline_text(
            pos, "\n".join(self.object_text), font=self.font, fill=self.color, spacing=0
        )


class TextLayouterScroll(TextLayouterSimple):
    def __init__(self, text: str, draw, color, font=fonts.base, width=fonts.base_width, max_lines=3):
        super().__init__(text, draw, color, font, width, max_lines)
        self.pointer = 0
        self.textlen = len(text)
        self.counter = 0

    def layout(self, pos: Tuple[int, int] = (0, 0)):
        if self.textlen > self.width:
            if self.counter % 30 == 0:
                self.object_text: List[str] = [self.text[self.pointer:self.pointer+self.width]]
                self.pointer = (self.pointer + 1) % (self.textlen-self.width+1)
            if self.pointer < 5:
                self.counter += 1
            else:
                self.counter += 10
        else:
            self.object_text: List[str] = [self.text]


class TextLayouter(TextLayouterSimple):
    def __init__(self, text: str, draw, color, font=fonts.base, width=fonts.base_width, max_lines=3):
        super().__init__(text, draw, color, font, width, max_lines)
        self.updated = True

    def layout(self, pos: Tuple[int, int] = (0, 0)):
        if self.updated:
            self.object_text = textwrap.wrap(self.text, width=self.width)
            self.updated = False
