"""
Reusable numeric entry components for PiFinder UI

Provides standardized components for entering numeric values with consistent
legends, cursor behavior, and validation across different UI screens.
"""

import time
from typing import List, Optional, Tuple, Any, TYPE_CHECKING
from dataclasses import dataclass
from PIL import ImageDraw

if TYPE_CHECKING:

    def _(a) -> Any:
        return a


class BlinkingCursor:
    """Blinking cursor for entry fields"""

    def __init__(self, blink_interval=0.5):
        self.start_time = time.time()
        self.blink_interval = blink_interval

    def is_visible(self):
        elapsed = time.time() - self.start_time
        return (elapsed % (self.blink_interval * 2)) < self.blink_interval

    def draw(self, screen, x, y, width, height):
        if not self.is_visible():
            return

        cursor_width = 2
        cursor_height = height - 2

        # Create a simple blended cursor by drawing with half_red color
        # Start cursor lower to align with underscore baseline
        cursor_y_offset = 4
        for cy in range(cursor_height):
            for cx in range(cursor_width):
                pixel_x, pixel_y = x + cx, y + cursor_y_offset + cy
                if 0 <= pixel_x < screen.width and 0 <= pixel_y < screen.height:
                    # Get current pixel and blend with red
                    current_pixel = screen.getpixel((pixel_x, pixel_y))
                    if isinstance(current_pixel, tuple) and len(current_pixel) >= 3:
                        blended_pixel = (
                            min(255, (current_pixel[0] + 255) // 2),  # Blend red
                            current_pixel[1] // 2,  # Dim green
                            current_pixel[2] // 2,  # Dim blue
                        )
                        screen.putpixel((pixel_x, pixel_y), blended_pixel)


@dataclass
class LegendItem:
    """A single item in the bottom legend bar"""

    icon: str  # Nerd Font glyph (e.g., "󰝤", "󰹺")
    label: str  # Translated label text
    key_hint: Optional[str] = None  # Optional key hint (e.g., "Left", "0-9")


class NumericEntryField:
    """
    Single numeric field with configurable format and validation.

    Supports formats like:
    - "XX.X" - two digits, decimal, one digit (e.g., "14.5")
    - "XX.XX" - two digits, decimal, two digits (e.g., "18.25")
    - "XXX" - three digits (e.g., "123")
    - "XX" - two digits (e.g., "45")

    Features:
    - Fixed-width display with cursor highlighting
    - Automatic decimal point handling
    - Range validation
    - Underscore placeholder for empty digits
    """

    def __init__(
        self,
        format_pattern: str = "XX.X",
        validation_range: Optional[Tuple[float, float]] = None,
        placeholder_char: str = "_",
        initial_value: Optional[str] = None,
    ):
        """
        Initialize numeric entry field.

        Args:
            format_pattern: Format string using 'X' for digits, '.' for decimal
            validation_range: Optional (min, max) tuple for value validation
            placeholder_char: Character to show for empty positions
            initial_value: Optional initial value to populate field
        """
        self.format_pattern = format_pattern
        self.validation_range = validation_range
        self.placeholder_char = placeholder_char

        # Parse format pattern to create digit array
        self.positions = list(format_pattern)
        self.num_positions = len(self.positions)

        # Initialize value array with empty spaces
        self.value = [" " if c == "X" else c for c in self.positions]

        # Set initial value if provided
        if initial_value:
            self._set_initial_value(initial_value)

        # Cursor starts at first editable position
        self.cursor_pos = self._first_editable_position()

    def _first_editable_position(self) -> int:
        """Find first editable position (not a decimal point)"""
        for i, pos in enumerate(self.positions):
            if pos == "X":
                return i
        return 0

    def _next_editable_position(self, current: int) -> int:
        """Find next editable position after current"""
        for i in range(current + 1, self.num_positions):
            if self.positions[i] == "X":
                return i
        return current

    def _prev_editable_position(self, current: int) -> int:
        """Find previous editable position before current"""
        for i in range(current - 1, -1, -1):
            if self.positions[i] == "X":
                return i
        return current

    def _set_initial_value(self, value_str: str):
        """Set initial value from string"""
        # Remove any whitespace
        value_str = value_str.strip()

        # Map string characters to value array
        value_idx = 0
        for i, pattern_char in enumerate(self.positions):
            if value_idx < len(value_str):
                if pattern_char == "X":
                    if value_str[value_idx].isdigit():
                        self.value[i] = value_str[value_idx]
                        value_idx += 1
                elif pattern_char == "." and value_str[value_idx] == ".":
                    value_idx += 1

    def insert_digit(self, digit: int) -> bool:
        """
        Insert digit at current cursor position.

        Returns:
            True if digit was inserted and cursor advanced
        """
        if not (0 <= digit <= 9):
            return False

        # Check if current position is editable
        if self.positions[self.cursor_pos] != "X":
            return False

        # Insert digit
        self.value[self.cursor_pos] = str(digit)

        # Move cursor to next editable position
        next_pos = self._next_editable_position(self.cursor_pos)
        if next_pos != self.cursor_pos:
            self.cursor_pos = next_pos
            return True

        return True

    def delete_digit(self) -> bool:
        """
        Delete digit at current cursor position and move cursor back (backspace behavior).

        Returns:
            True if digit was deleted
        """
        # If current position is empty, move back and delete previous
        if self.value[self.cursor_pos] == " ":
            prev_pos = self._prev_editable_position(self.cursor_pos)
            if prev_pos != self.cursor_pos:
                self.cursor_pos = prev_pos
                if self.positions[self.cursor_pos] == "X":
                    self.value[self.cursor_pos] = " "
                    return True
            return False

        # Current position has a digit, delete it
        if self.positions[self.cursor_pos] == "X":
            self.value[self.cursor_pos] = " "
            return True

        return False

    def move_cursor_left(self) -> bool:
        """Move cursor to previous editable position"""
        prev_pos = self._prev_editable_position(self.cursor_pos)
        if prev_pos != self.cursor_pos:
            self.cursor_pos = prev_pos
            return True
        return False

    def move_cursor_right(self) -> bool:
        """Move cursor to next editable position"""
        next_pos = self._next_editable_position(self.cursor_pos)
        if next_pos != self.cursor_pos:
            self.cursor_pos = next_pos
            return True
        return False

    def get_value_string(self) -> str:
        """Get current value as string"""
        return "".join(self.value)

    def get_display_string(self) -> str:
        """Get display string with placeholders for empty positions"""
        result = []
        for i, char in enumerate(self.value):
            if char == " ":
                result.append(self.placeholder_char)
            else:
                result.append(char)
        return "".join(result)

    def validate(self) -> Tuple[bool, Optional[float]]:
        """
        Validate current value.

        Returns:
            Tuple of (is_valid, parsed_value)
        """
        value_str = self.get_value_string().strip()

        # Check if empty
        if not value_str or value_str.replace(".", "").replace(" ", "") == "":
            return False, None

        # Replace remaining spaces with zeros
        value_str = value_str.replace(" ", "0")

        try:
            parsed_value = float(value_str)
        except ValueError:
            return False, None

        # Check range if specified
        if self.validation_range:
            min_val, max_val = self.validation_range
            if not (min_val <= parsed_value <= max_val):
                return False, parsed_value

        return True, parsed_value

    def draw(
        self,
        draw: ImageDraw.ImageDraw,
        screen,
        x: int,
        y: int,
        font,
        char_width: int,
        char_height: int,
        normal_color: tuple,
        blinking_cursor: Optional[BlinkingCursor] = None,
    ):
        """
        Draw the numeric entry field.

        Args:
            draw: PIL ImageDraw object
            screen: PIL Image (for blinking cursor pixel manipulation)
            x: Starting X position
            y: Starting Y position
            font: Font to use for drawing
            char_width: Width of each character
            char_height: Height of characters
            normal_color: Color for normal text
            blinking_cursor: Optional BlinkingCursor instance for animated cursor
        """
        display_str = self.get_display_string()

        for i, char in enumerate(display_str):
            char_x = x + (i * char_width)
            draw.text((char_x, y), char, font=font, fill=normal_color)

        # Draw blinking cursor at current position if provided
        # Only show cursor if current position is empty (not filled)
        if blinking_cursor and self.positions[self.cursor_pos] == "X":
            # Don't show cursor if the current position is already filled
            if self.value[self.cursor_pos] == " ":
                cursor_x = x + (self.cursor_pos * char_width)
                blinking_cursor.draw(screen, cursor_x, y, char_width, char_height)


class EntryLegend:
    """
    Standardized bottom legend for entry screens.

    Provides consistent layout with separator line and proper icon rendering.
    """

    def __init__(
        self,
        items: List[LegendItem],
        show_separator: bool = True,
        layout: str = "two_line",
    ):
        """
        Initialize legend.

        Args:
            items: List of legend items to display
            show_separator: Whether to draw separator line above legend
            layout: Layout mode - "two_line", "single_line", or "compact"
        """
        self.items = items
        self.show_separator = show_separator
        self.layout = layout

    def draw(
        self,
        draw: ImageDraw.ImageDraw,
        screen_width: int,
        screen_height: int,
        font,
        font_height: int,
        separator_color: tuple,
        text_color: tuple,
        margin: int = 2,
    ):
        """
        Draw the legend at bottom of screen.

        Args:
            draw: PIL ImageDraw object
            screen_width: Width of screen
            screen_height: Height of screen
            font: Font to use
            font_height: Height of font
            separator_color: Color for separator line
            text_color: Color for legend text
            margin: Margin from screen edges
        """
        if self.layout == "two_line":
            self._draw_two_line(
                draw,
                screen_width,
                screen_height,
                font,
                font_height,
                separator_color,
                text_color,
                margin,
            )
        elif self.layout == "single_line":
            self._draw_single_line(
                draw,
                screen_width,
                screen_height,
                font,
                font_height,
                separator_color,
                text_color,
                margin,
            )
        else:  # compact
            self._draw_compact(
                draw,
                screen_width,
                screen_height,
                font,
                font_height,
                separator_color,
                text_color,
                margin,
            )

    def _draw_two_line(
        self,
        draw: ImageDraw.ImageDraw,
        screen_width: int,
        screen_height: int,
        font,
        font_height: int,
        separator_color: tuple,
        text_color: tuple,
        margin: int,
    ):
        """Draw legend in two-line format (like RA/Dec and LM entry)"""
        # Calculate starting Y position for legend
        bar_y = screen_height - (font_height * 2) - 6

        # Draw separator line if requested
        if self.show_separator:
            draw.line(
                [(margin, bar_y), (screen_width - margin, bar_y)],
                fill=separator_color,
                width=1,
            )

        # Split items into two lines
        mid_point = (len(self.items) + 1) // 2
        line1_items = self.items[:mid_point]
        line2_items = self.items[mid_point:]

        # Draw first line (no space between icon and label, matches radec/lm)
        y_pos = bar_y + 2
        line1_text = " ".join([f"{item.icon}{item.label}" for item in line1_items])
        draw.text((margin, y_pos), line1_text, font=font, fill=text_color)

        # Draw second line if there are items
        if line2_items:
            y_pos += font_height + 2
            line2_text = " ".join([f"{item.icon}{item.label}" for item in line2_items])
            draw.text((margin, y_pos), line2_text, font=font, fill=text_color)

    def _draw_single_line(
        self,
        draw: ImageDraw.ImageDraw,
        screen_width: int,
        screen_height: int,
        font,
        font_height: int,
        separator_color: tuple,
        text_color: tuple,
        margin: int,
    ):
        """Draw legend in single line format"""
        bar_y = screen_height - font_height - 4

        if self.show_separator:
            draw.line(
                [(margin, bar_y - 2), (screen_width - margin, bar_y - 2)],
                fill=separator_color,
                width=1,
            )

        legend_text = " ".join([f"{item.icon}{item.label}" for item in self.items])
        draw.text((margin, bar_y), legend_text, font=font, fill=text_color)

    def _draw_compact(
        self,
        draw: ImageDraw.ImageDraw,
        screen_width: int,
        screen_height: int,
        font,
        font_height: int,
        separator_color: tuple,
        text_color: tuple,
        margin: int,
    ):
        """Draw legend in compact format with minimal spacing"""
        bar_y = screen_height - font_height - 2

        if self.show_separator:
            draw.line(
                [(margin, bar_y - 1), (screen_width - margin, bar_y - 1)],
                fill=separator_color,
                width=1,
            )

        legend_text = " ".join([f"{item.icon}{item.label}" for item in self.items])
        draw.text((margin, bar_y), legend_text, font=font, fill=text_color)
