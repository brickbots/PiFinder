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
        width=-1,
        scrollspeed=MEDIUM,
    ):
        self.pointer = 0
        self.textlen = len(text)
        self.updated = True
        self.scrollspeed = scrollspeed
        if width == -1:
            self.width = font.line_length
        else:
            self.width = width

        if self.textlen >= width:
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
        # Derive the scrollbar extent from the display resolution. TextLayouter
        # isn't handed a display_class, but its ``colors`` carries a red_image
        # sized to the display resolution, so read the size from there.
        resX, resY = self.colors.red_image.size
        xpos = resX - 1
        starty = pos[1] + 1
        endy = resY - 1
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


class SectionedTextLayouter(TextLayouter):
    """
    Multi-line description where some lines are section-header *rules*: a bright,
    edge-to-edge box-drawing line (Nerd Font U+2501 ``━``) with an optional left
    label, drawn at a different brightness than the body text.

    Rule lines are tagged with ``RULE_MARK`` so wrapping/scrolling work exactly
    as in TextLayouter; the full-width glyph run is built at draw time, when the
    line width is known. A label too long to fit inline is split onto its own
    line under a label-less full rule.
    """

    RULE_MARK = "\x00"
    RULE_GLYPH = "━"
    LEAD = 2  # leading glyphs before the label

    def set_sections(self, sections, reset_pointer=True):
        """``sections``: list of ``(label_or_None, text)``; None = no rule."""
        width = self.font.line_length
        lines: List[str] = []
        for label, text in sections:
            if label is None:
                pass
            elif self.LEAD + len(label) + 2 <= width:
                lines.append(self.RULE_MARK + label)  # inline rule
            else:
                lines.append(self.RULE_MARK)  # full rule, no label
                lines.append(label)  # name wraps on its own line(s)
            if text:
                lines.append(text)
        self.set_text("\n".join(lines), reset_pointer=reset_pointer)

    def _rule_text(self, label: str) -> str:
        width = self.font.line_length
        if not label:
            return self.RULE_GLYPH * width
        fill = max(0, width - self.LEAD - len(label) - 2)
        return f"{self.RULE_GLYPH * self.LEAD} {label} {self.RULE_GLYPH * fill}"

    def draw(self, pos: Tuple[int, int] = (0, 0)):
        self.layout(pos)
        x, y = pos
        rule_color = self.colors.get(255)
        for line in self.object_text:
            if line.startswith(self.RULE_MARK):
                self.drawobj.text(
                    (x, y),
                    self._rule_text(line[len(self.RULE_MARK) :]),
                    font=self.font.font,
                    fill=rule_color,
                )
            else:
                self.drawobj.text((x, y), line, font=self.font.font, fill=self.color)
            y += self.font.height
        self.after_draw(pos)


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


def outline_text(
    ri_draw, xy, text, align, font, fill, shadow_color, stroke=4, anchor=None
):
    """draw outline text"""
    ri_draw.text(
        xy,
        text,
        align=align,
        font=font.font,
        fill=fill,
        stroke_width=stroke,
        stroke_fill=shadow_color,
        anchor=anchor,
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
    return (
        name.lower().replace(" ", "").replace("the ", "", 1).replace("-", "")
    )  # TODO I18N If we get local names, we need to change this, too.


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


def format_number(num: float, width=5):
    """
    Format a number with K (thousands) or M (millions) suffix.
    """
    if num < 1000:
        return f"{num:{width}d}"
    elif num < 1000000:
        decimal_places = max(0, width - 3)  # 'K' and at least one digit
        return f"{num / 1000:{width}.{decimal_places}f}K"
    else:
        decimal_places = max(0, width - 3)  # 'M' and at least one digit
        return f"{num / 1000000:{width}.{decimal_places}f}M"


def pointing_arrows(ui, point_az, point_alt, mount_type=None):
    """
    Resolve the push-to direction indicators for a (point_az, point_alt)
    movement, honoring the mount_type and pushto_az_arrows config
    options: directional arrows for Alt/Az mounts, +/- signs for EQ
    mounts (where the values are RA/Dec offsets).

    Returns (az_indicator, point_az, alt_indicator, point_alt) with the
    point values made positive.

    mount_type must match the one the point values were computed with
    (e.g. the value passed to aim_degrees); when None, the current
    config option is used. Callers whose values are intrinsically Alt/Az
    regardless of the configured mount (e.g. polar alignment, where you
    drive the mount's alt/az polar adjusters) pass mount_type="Alt/Az"
    explicitly.
    """
    if mount_type is None:
        mount_type = ui.config_object.get_option("mount_type")
    mount_altaz = mount_type == "Alt/Az"

    if point_az < 0:
        point_az *= -1
        az_arrow = ui._LEFT_ARROW if mount_altaz else "-"
    else:
        az_arrow = ui._RIGHT_ARROW if mount_altaz else "+"

    if (
        mount_altaz
        and ui.config_object.get_option("pushto_az_arrows", "Default") == "Reverse"
    ):
        if az_arrow is ui._LEFT_ARROW:
            az_arrow = ui._RIGHT_ARROW
        else:
            az_arrow = ui._LEFT_ARROW

    if point_alt < 0:
        point_alt *= -1
        alt_arrow = ui._DOWN_ARROW if mount_altaz else "-"
    else:
        alt_arrow = ui._UP_ARROW if mount_altaz else "+"

    return az_arrow, point_az, alt_arrow, point_alt


def draw_pointing_instructions(
    ui, point_az, point_alt, brightness=255, mount_type=None
):
    """
    Draw the standard push-to display: the az and alt movements as two
    huge-font lines with direction indicators anchored at the bottom of
    the screen, as on the object locate screen.
    """
    az_arrow, point_az, alt_arrow, point_alt = pointing_arrows(
        ui, point_az, point_alt, mount_type
    )

    az_anchor = (0, ui.display_class.resY - (ui.fonts.huge.height * 2.2))
    alt_anchor = (0, ui.display_class.resY - (ui.fonts.huge.height * 1.2))
    for anchor, arrow, value in (
        (az_anchor, az_arrow, point_az),
        (alt_anchor, alt_arrow, point_alt),
    ):
        # Change decimal points when within 1 degree
        decimals = 2 if value < 1 else 1
        ui.draw.text(
            anchor,
            f"{arrow}{value: >5.{decimals}f}",
            font=ui.fonts.huge.font,
            fill=ui.colors.get(brightness),
        )
