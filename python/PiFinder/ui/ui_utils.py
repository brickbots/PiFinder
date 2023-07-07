import PiFinder.utils as utils
from PiFinder.ui.fonts import Fonts as fonts
from typing import Tuple, List, Dict, Optional
import textwrap
import logging
import re


class SpaceCalculator:
    """Calculates spaces for proportional fonts, obsolete"""

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
        # logging.debug(f"returning {spaces=}, {result=}")
        return spaces, result


class SpaceCalculatorFixed:
    """Calculates spaces for fixed-width fonts"""

    def __init__(self, nr_chars):
        self.width = nr_chars

    def _calc_string(self, left, right, spaces) -> str:
        return f"{left}{'': <{spaces}}{right}"

    def calculate_spaces(self, left: str, right: str) -> Tuple[int, str]:
        """
        returns number of spaces
        """
        spaces = 1
        lenleft = len(str(left))
        lenright = len(str(right))

        if lenleft + lenright + 1 > self.width:
            return -1, ""

        spaces = self.width - (lenleft + lenright)
        result = self._calc_string(left, right, spaces)
        return spaces, result


class TextLayouterSimple:
    def __init__(
        self,
        text: str,
        draw,
        color,
        font=fonts.base,
        width=fonts.base_width,
    ):
        self.text = text
        self.font = font
        self.color = color
        self.width = width
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
        # logging.debug(f"Drawing {self.object_text=}")
        self.drawobj.multiline_text(
            pos, "\n".join(self.object_text), font=self.font, fill=self.color, spacing=0
        )

    def __repr__(self):
        return f"TextLayouterSimple({self.text=}, {self.color=}, {self.font=}, {self.width=})"


class TextLayouterScroll(TextLayouterSimple):
    """To be used as a one-line scrolling text"""

    FAST = 750
    MEDIUM = 500
    SLOW = 200

    def __init__(
        self,
        text: str,
        draw,
        color,
        font=fonts.base,
        width=fonts.base_width,
        scrollspeed=MEDIUM,
    ):
        self.pointer = 0
        self.textlen = len(text)
        self.updated = True

        if self.textlen >= width:
            self.dtext = text + " " * 6 + text
            self.dtextlen = len(self.dtext)
            self.counter = 0
            self.counter_max = 3000
            self.set_scrollspeed(scrollspeed)
        super().__init__(text, draw, color, font, width)

    def set_scrollspeed(self, scrollspeed: float):
        self.scrollspeed = float(scrollspeed)
        self.counter = 0

    def layout(self, pos: Tuple[int, int] = (0, 0)):
        if self.textlen > self.width and self.scrollspeed > 0:
            if self.counter == 0:
                self.object_text: List[str] = [
                    self.dtext[self.pointer : self.pointer + self.width]
                ]
                self.pointer = (self.pointer + 1) % (self.textlen + 6)
            # start goes slower
            if self.pointer == 1:
                self.counter = (self.counter + 100) % self.counter_max
            # regular scrolling
            else:
                self.counter = (self.counter + self.scrollspeed) % self.counter_max
        elif self.updated:
            self.object_text: List[str] = [self.text]
            self.updated = False


class TextLayouter(TextLayouterSimple):
    """To be used as a multi-line text with down scrolling"""

    shorttop = [48, 125, 80, 125]
    shortbottom = [48, 126, 80, 126]
    longtop = [32, 125, 96, 125]
    longbottom = [32, 126, 96, 126]
    downarrow = (longtop, shortbottom)
    uparrow = (shorttop, longbottom)

    def __init__(
        self,
        text: str,
        draw,
        color,
        colors,
        font=fonts.base,
        width=fonts.base_width,
        available_lines=3,
    ):
        super().__init__(text, draw, color, font, width)
        self.nr_lines = 0
        self.colors = colors
        self.start_line = 0
        self.available_lines = available_lines
        self.scrolled = False
        self.pointer = 0
        self.updated = True

    def next(self):
        if self.nr_lines <= self.available_lines:
            return
        self.pointer = (self.pointer + 1) % (self.nr_lines - self.available_lines + 1)
        self.scrolled = True

    def set_text(self, text):
        super().set_text(text)
        self.pointer = 0
        self.nr_lines = len(text)

    def draw_arrow(self, down):
        if self.nr_lines > self.available_lines:
            if down:
                self._draw_arrow(*self.downarrow)
            else:
                self._draw_arrow(*self.uparrow)

    def _draw_arrow(self, top, bottom):
        self.drawobj.rectangle([0, 126, 128, 128], fill=self.colors.get(0))
        self.drawobj.rectangle(top, fill=self.colors.get(128))
        self.drawobj.rectangle(bottom, fill=self.colors.get(128))

    def layout(self, pos: Tuple[int, int] = (0, 0)):
        if self.updated:
            # logging.debug(f"Updating {self.text=}")
            split_lines = re.split(r"\n|\n\n", self.text)
            self.object_text = []
            for line in split_lines:
                self.object_text.extend(textwrap.wrap(line, width=self.width))
            self.orig_object_text = self.object_text
            self.object_text = self.object_text[0 : self.available_lines]
            self.nr_lines = len(self.orig_object_text)
        if self.scrolled:
            self.object_text = self.orig_object_text[
                self.pointer : self.pointer + self.available_lines
            ]
        up = self.pointer + self.available_lines == self.nr_lines
        self.draw_arrow(not up)
        self.updated = False
        self.scrolled = False
