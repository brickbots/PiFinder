#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Limiting Magnitude Entry UI

Allows user to enter a fixed limiting magnitude value (e.g., 14.5)
with one decimal place precision.
"""

from PIL import Image, ImageDraw
from PiFinder.ui.base import UIModule


class UILMEntry(UIModule):
    """
    UI for entering limiting magnitude value

    Controls:
    - 0-9: Enter digits
    - Up/Down: Move cursor left/right between digits
    - -: Delete digit (backspace)
    - Right: Accept (save and return)
    - Left: Cancel (discard and return)
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.config_option = self.item_definition.get("config_option", "obj_chart_lm_fixed")

        # Start with placeholder/blank value for user to fill in
        # Store as string for editing: format is "  .  " (spaces for digits)
        self.digits = [' ', ' ', '.', ' ']  # Two digits, decimal, one digit

        # Cursor position (0-3 for "XX.X" format)
        # Position 2 is the decimal point (not editable)
        self.cursor_pos = 0

        self.width = 128
        self.height = 128
        self.screen = Image.new("RGB", (self.width, self.height), "black")

    def update(self, force=False):
        """Render the LM entry screen"""
        self.screen = Image.new("RGB", (self.width, self.height), "black")
        draw = ImageDraw.Draw(self.screen)

        # Title
        title = "Set Limiting Mag"
        title_bbox = draw.textbbox((0, 0), title, font=self.fonts.base.font)
        title_width = title_bbox[2] - title_bbox[0]
        title_x = (self.width - title_width) // 2
        draw.text(
            (title_x, 5),
            title,
            font=self.fonts.base.font,
            fill=self.colors.get(128)
        )

        # Display current value with cursor
        value_y = (self.height - self.fonts.large.height) // 2 - 10

        # Use fixed-width spacing for consistent alignment
        char_width = self.fonts.large.width  # Fixed character width
        total_width = char_width * len(self.digits)

        # Center the entire value
        start_x = (self.width - total_width) // 2

        # Draw each character
        for i, char in enumerate(self.digits):
            x_pos = start_x + (i * char_width)

            # Display character or underscore for empty
            display_char = char if char != ' ' else '_'

            # Highlight cursor position (but not the decimal point)
            if i == self.cursor_pos and char != '.':
                # Draw filled rectangle background
                draw.rectangle(
                    [x_pos - 2, value_y - 2, x_pos + char_width + 2, value_y + self.fonts.large.height + 2],
                    fill=self.colors.get(255),
                    outline=self.colors.get(255),
                    width=2
                )
                # Draw text in inverse color
                text_color = self.colors.get(0)
            else:
                text_color = self.colors.get(255)

            draw.text(
                (x_pos, value_y),
                display_char,
                font=self.fonts.large.font,
                fill=text_color
            )

        # Icons (matching radec_entry style)
        arrow_icons = "󰹺"
        back_icon = ""
        go_icon = ""

        # Legends at bottom (two lines)
        bar_y = self.height - (self.fonts.base.height * 2) - 4

        # Draw separator line
        draw.line(
            [(2, bar_y), (self.width - 2, bar_y)],
            fill=self.colors.get(128),
            width=1
        )

        # Line 1: Navigation
        line1 = f"{arrow_icons}Nav"
        draw.text((2, bar_y + 2), line1, font=self.fonts.base.font, fill=self.colors.get(128))

        # Line 2: Actions
        line2 = f"{back_icon}Cancel {go_icon}Accept -Del"
        draw.text((2, bar_y + 12), line2, font=self.fonts.base.font, fill=self.colors.get(128))

        return self.screen, None

    def key_up(self):
        """Move cursor left"""
        if self.cursor_pos > 0:
            self.cursor_pos -= 1
            # Skip over decimal point
            if self.cursor_pos == 2:
                self.cursor_pos = 1
        return True

    def key_down(self):
        """Move cursor right"""
        if self.cursor_pos < 3:
            self.cursor_pos += 1
            # Skip over decimal point
            if self.cursor_pos == 2:
                self.cursor_pos = 3
        return True

    def key_number(self, number):
        """Enter digit 0-9 at cursor position"""
        if 0 <= number <= 9:
            # Don't allow editing the decimal point
            if self.cursor_pos == 2:
                return False

            # Replace digit at cursor position
            self.digits[self.cursor_pos] = str(number)

            # Move cursor to next position after entering digit
            if self.cursor_pos < 3:
                self.cursor_pos += 1
                # Skip over decimal point
                if self.cursor_pos == 2:
                    self.cursor_pos = 3

            return True
        return False

    def key_minus(self):
        """Delete digit at cursor position (replace with space)"""
        if self.cursor_pos == 2:
            # Can't delete decimal point
            return False

        # Replace with space (blank)
        self.digits[self.cursor_pos] = ' '
        return True

    def key_left(self):
        """Cancel - return without saving"""
        return True

    def key_right(self):
        """Accept - save value and return"""
        import logging
        logger = logging.getLogger("UILMEntry")
        logger.info(">>> key_right() called!")

        try:
            # Convert digits to string, replacing spaces with nothing won't work
            # We need at least one digit before decimal and one after
            value_str = "".join(self.digits).strip()
            logger.info(f"LM entry: digits={self.digits}, value_str='{value_str}'")

            # Check if we have any actual digits (not just spaces and decimal)
            if value_str.replace('.', '').replace(' ', '') == '':
                # No digits entered, reject
                logger.info("LM entry rejected: no digits")
                return False

            # Replace remaining spaces with 0 for parsing
            value_str = value_str.replace(' ', '0')
            final_value = float(value_str)
            logger.info(f"LM entry: parsed value={final_value}")

            # Validate range
            if final_value < 5.0 or final_value > 20.0:
                # Out of range, reject
                logger.info(f"LM entry rejected: out of range (5.0-20.0)")
                return False

            logger.info(f"LM entry accepted: {final_value}")
            self.config_object.set_option(self.config_option, final_value)

            # Also set the mode to "fixed" since user entered a value
            self.config_object.set_option("obj_chart_lm_mode", "fixed")

            # No need to invalidate cache - cache key includes LM so different
            # LM values will automatically get separate cache entries

            logger.info("Returning True to exit LM entry screen")
            return True
        except ValueError as e:
            # Invalid value, don't accept
            logger.error(f"LM entry ValueError: {e}")
            return False

    def active(self):
        """Called when screen becomes active"""
        return False
