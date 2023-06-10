import PiFinder.image_util as utils
from PiFinder.ui.fonts import Fonts as fonts
from typing import Tuple, List
import logging


class Catalog:
    def __init__(self):
        pass


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


class TextLayouter:
    def __init__(
        self, text: List[str], draw, color, font=fonts.base, width=128, max_lines=3
    ):
        self.text = text
        self.font = font
        self.color = color
        self.width = width
        self.max_lines = max_lines
        self.drawobj = draw
        self.object_text = []

    def set_text(self, text):
        if not isinstance(text, list):
            text = [text]
        self.text = text

    def set_color(self, color):
        self.color = color

    def layout(self, pos: Tuple[int, int] = (0, 0)):
        # TODO take pos into account when calculating width
        self.object_text = []
        line = ""
        last_line = line
        line_nr = 1
        line_max = self.max_lines
        # desc = self.cat_object["desc"].replace('\t', ' ').replace('\n', '')
        desc_tokens = self.text.split(" ")
        try:
            for token in desc_tokens:
                last_line = line
                line = line + " " + token
                if self.drawobj.textlength(line) > self.width:
                    if line_nr == line_max:
                        self.object_text.append(last_line[:-3] + "...")
                    else:
                        self.object_text.append(last_line)
                    line = ""
                    last_line = ""
                    line_nr += 1
            self.object_text.append(line)
        except Exception as e:
            print(f"{e}, {line=}, {self=}")

    def draw(self, pos: Tuple[int, int] = (0, 0)):
        self.layout(pos)
        # print(f"{self.object_text=}")
        # print(f"{self.font=}")
        # print(f"{self.color=}")
        # print(f"{pos=}")
        self.drawobj.multiline_text(
            pos, "\n".join(self.object_text), font=self.font, fill=self.color
        )
