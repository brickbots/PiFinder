from typing import Tuple, List
import textwrap
import re
import math


class SpaceCalculatorFixed:
    """Calculates spaces for fixed-width fonts"""

    def __init__(self, nr_chars, truncate_string=""):
        self.width = nr_chars
        self.truncate_string = truncate_string

    def _calc_string(self, left, right, spaces) -> str:
        return f"{left}{'': <{spaces}}{right}"

    def _truncate(self, left, right, trunc_left) -> str:
        if trunc_left:
            left_left = self.width - len(right) - 2
            return f"{left[:left_left]}{self.truncate_string}{right}"
        else:
            right_left = self.width - len(left) - 2
            return f"{left} {right[:right_left]}{self.truncate_string}"

    def calculate_spaces(
        self, left: str, right: str, empty_if_exceeds=True, trunc_left=False
    ) -> Tuple[int, str]:
        """
        returns number of spaces
        """
        lenleft = len(str(left))
        lenright = len(str(right))
        spaces = max(0, self.width - (lenleft + lenright))
        if spaces <= 0:
            if empty_if_exceeds:
                return -1, ""
            else:
                return 1, self._truncate(left, right, trunc_left)

        result = self._calc_string(left, right, spaces)
        return spaces, result


class TextLayouterSimple:
    def __init__(
        self,
        text: str,
        draw,
        color,
        font,
        embedded_color=False,
    ):
        self.text = text
        self.font = font
        self.color = color
        self.embedded_color = embedded_color
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
            self.object_text = [self.text]
            self.updated = False

    def after_draw(self, pos):
        """draw stuff on top of the text"""
        pass

    def draw(self, pos: Tuple[int, int] = (0, 0)):
        self.layout(pos)
        self.drawobj.multiline_text(
            pos,
            "\n".join(self.object_text),
            font=self.font.font,
            fill=self.color,
            embedded_color=self.embedded_color,
            spacing=0,
        )
        self.after_draw(pos)

    def __repr__(self):
        return f"TextLayouterSimple({self.text=}, {self.color=}, {self.font=}, {self.font.line_length=})"


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
        font,
        scrollspeed=MEDIUM,
    ):
        self.pointer = 0
        self.textlen = len(text)
        self.updated = True

        if self.textlen >= font.line_length:
            self.dtext = text + " " * 6 + text
            self.dtextlen = len(self.dtext)
            self.counter = 0
            self.counter_max = 3000
            self.set_scrollspeed(scrollspeed)
        super().__init__(text, draw, color, font)

    def set_scrollspeed(self, scrollspeed: float):
        self.scrollspeed = float(scrollspeed)
        self.counter = 0

    def layout(self, pos: Tuple[int, int] = (0, 0)):
        if self.textlen > self.font.line_length and self.scrollspeed > 0:
            if self.counter == 0:
                self.object_text: List[str] = [
                    self.dtext[self.pointer : self.pointer + self.font.line_length]
                ]
                self.pointer = (self.pointer + 1) % (self.textlen + 6)
            # start goes slower
            if self.pointer == 1:
                self.counter = (self.counter + 100) % self.counter_max
            # regular scrolling
            else:
                self.counter = int((self.counter + self.scrollspeed) % self.counter_max)
        elif self.updated:
            self.object_text = [self.text]
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
        font,
        available_lines=3,
    ):
        super().__init__(text, draw, color, font)
        self.nr_lines = 0
        self.colors = colors
        self.start_line = 0
        self.available_lines = available_lines
        self.pointer = 0
        self.updated = True

    def next(self, direction=1):
        if self.nr_lines <= self.available_lines:
            return
        self.pointer = (self.pointer + direction) % (
            self.nr_lines - self.available_lines + 1
        )
        self.updated = True

    def previous(self):
        self.next(-1)

    def set_text(self, text, reset_pointer=True):
        super().set_text(text)
        self.nr_lines = len(text)
        if reset_pointer:
            self.pointer = 0

    def set_available_lines(self, available_lines: int):
        self.available_lines = available_lines
        self.updated = True

    def _draw_pos(self, pos):
        xpos = 127
        starty = pos[1] + 1
        endy = 127
        therange = endy - starty
        blockextent = math.floor((self.available_lines / self.nr_lines) * therange)
        blockstart = ((self.pointer) / self.nr_lines) * therange
        start = [xpos, starty, xpos, endy]
        end = [
            xpos,
            math.floor(starty + blockstart),
            xpos,
            math.floor(starty + blockstart + blockextent),
        ]
        self.drawobj.line(start, fill=self.colors.get(64), width=1)
        self.drawobj.line(end, fill=self.colors.get(128), width=1)

    def layout(self, pos: Tuple[int, int] = (0, 0)):
        if self.updated:
            split_lines = re.split(r"\n|\n\n", self.text)
            self.object_text = []
            for line in split_lines:
                self.object_text.extend(
                    textwrap.wrap(line, width=self.font.line_length)
                )
            self.nr_lines = len(self.object_text)
            self.object_text = self.object_text[
                self.pointer : self.pointer + self.available_lines
            ]
        self.updated = False

    def after_draw(self, pos):
        if self.nr_lines > self.available_lines:
            self._draw_pos(pos)


def shadow_outline_text(
    ri_draw, xy, text, align, font, fill, shadow_color, shadow=None, outline=None
):
    """draw shadowed and outlined text"""
    x, y = xy
    if shadow:
        ri_draw.text(
            (x + shadow[0], y + shadow[1]),
            text,
            align=align,
            font=font.font,
            fill=shadow_color,
        )

    if outline:
        outline_text(
            ri_draw,
            xy,
            text,
            align=align,
            font=font,
            fill=fill,
            shadow_color=shadow_color,
            stroke=2,
        )


def outline_text(ri_draw, xy, text, align, font, fill, shadow_color, stroke=4):
    """draw outline text"""
    ri_draw.text(
        xy,
        text,
        align=align,
        font=font.font,
        fill=fill,
        stroke_width=stroke,
        stroke_fill=shadow_color,
    )


def shadow(ri_draw, xy, text, align, font, fill, shadowcolor):
    """draw shadowed text"""
    x, y = xy
    # thin border
    ri_draw.text((x - 1, y), text, align=align, font=font.font, fill=shadowcolor)
    ri_draw.text((x + 1, y), text, align=align, font=font.font, fill=shadowcolor)
    ri_draw.text((x, y - 1), text, align=align, font=font.font, fill=shadowcolor)
    ri_draw.text((x, y + 1), text, align=align, font=font.font, fill=shadowcolor)
    ri_draw.text((x, y), text, align=align, font=font.font, fill=fill)


def normalize(name):
    """Helper function to normalize names"""
    return name.lower().replace(" ", "").replace("the ", "", 1).replace("-", "")


def name_deduplicate(names: List[str], exclude: List[str]):
    """From a list of object names (NGC 5000, NGC5000), remove duplicates"""
    # Use a set for quick membership testing to remember names we've seen
    seen = set()
    result = []
    norm_excludes = [normalize(x) for x in exclude]
    for name in names:
        # Normalize name for comparison
        norm_name = normalize(name)
        if norm_name not in seen and norm_name not in norm_excludes:
            seen.add(norm_name)
            result.append(name)  # Add the original name to the result
    return result
