from PIL import Image, ImageDraw
from PiFinder.ui.base import UIModule
from PiFinder import calc_utils
from PiFinder import i18n  # This installs the global _() function
import time
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:

    def _(a) -> Any:
        return a


class BlinkingCursor:
    """Reusable blinking cursor component for input fields"""

    def __init__(self, blink_interval=0.5):
        self.start_time = time.time()
        self.blink_interval = blink_interval

    def is_visible(self):
        """Check if cursor should be visible based on blink timing"""
        elapsed = time.time() - self.start_time
        return (elapsed % (self.blink_interval * 2)) < self.blink_interval

    def draw(self, screen, x, y, width, height):
        """Draw semi-transparent cursor at specified position"""
        if not self.is_visible():
            return

        cursor_width = 2
        cursor_height = height - 4

        # Create a simple blended cursor by drawing with half_red color
        for cy in range(cursor_height):
            for cx in range(cursor_width):
                pixel_x, pixel_y = x + cx, y + 2 + cy
                if 0 <= pixel_x < screen.width and 0 <= pixel_y < screen.height:
                    # Get current pixel and blend with red
                    current_pixel = screen.getpixel((pixel_x, pixel_y))
                    if isinstance(current_pixel, tuple) and len(current_pixel) >= 3:
                        blended_pixel = (
                            min(255, (current_pixel[0] + 255) // 2),  # Blend red
                            current_pixel[1] // 2,                   # Dim green
                            current_pixel[2] // 2                    # Dim blue
                        )
                        screen.putpixel((pixel_x, pixel_y), blended_pixel)


class CoordinateConverter:
    """Handles coordinate format conversion and epoch transformations"""

    @staticmethod
    def hms_dms_to_degrees(fields, dec_sign):
        """Convert HMS/DMS format to decimal degrees"""
        # Convert RA from HMS to degrees
        ra_h = int(fields[0]) if fields[0] else 0
        ra_m = int(fields[1]) if fields[1] else 0
        ra_s = int(fields[2]) if fields[2] else 0
        ra_deg = calc_utils.ra_to_deg(ra_h, ra_m, ra_s)

        # Convert DEC from DMS to degrees
        dec_d = int(fields[3]) if fields[3] else 0
        dec_m = int(fields[4]) if fields[4] else 0
        dec_s = int(fields[5]) if fields[5] else 0
        dec_deg = calc_utils.dec_to_deg(dec_d, dec_m, dec_s)
        if dec_sign == "-":
            dec_deg = -dec_deg

        return ra_deg, dec_deg

    @staticmethod
    def mixed_to_degrees(fields, dec_sign):
        """Convert Mixed format (hours/degrees) to decimal degrees"""
        # RA in hours, convert to degrees
        ra_hours = float(fields[0]) if fields[0] else 0
        ra_deg = ra_hours * 15
        # DEC already in degrees
        dec_deg = float(fields[1]) if fields[1] else 0
        if dec_sign == "-":
            dec_deg = -dec_deg

        return ra_deg, dec_deg

    @staticmethod
    def decimal_to_degrees(fields, dec_sign):
        """Convert Decimal format to decimal degrees"""
        # Both already in degrees
        ra_deg = float(fields[0]) if fields[0] else 0
        dec_deg = float(fields[1]) if fields[1] else 0
        if dec_sign == "-":
            dec_deg = -dec_deg

        return ra_deg, dec_deg

    @staticmethod
    def convert_epoch(ra_deg, dec_deg, current_epoch):
        """Convert coordinates from current epoch to J2000"""
        if current_epoch == 0:  # Already J2000
            return ra_deg, dec_deg

        from skyfield.constants import T0 as J2000, B1950

        if current_epoch == 1:  # JNOW
            # Convert from current epoch to J2000
            from datetime import datetime
            import pytz

            # Get current Julian Date
            now = datetime.now(pytz.UTC)
            jd_now = calc_utils.sf_utils.ts.from_datetime(now).tt

            # Convert JNOW coordinates to J2000
            ra_hours = ra_deg / 15.0
            ra_h_j2000, dec_deg_j2000 = calc_utils.epoch_to_epoch(
                jd_now, J2000, ra_hours, dec_deg
            )
            return ra_h_j2000._degrees, dec_deg_j2000._degrees

        elif current_epoch == 2:  # B1950
            # Convert from B1950 to J2000
            ra_hours = ra_deg / 15.0
            ra_h_j2000, dec_deg_j2000 = calc_utils.b1950_to_j2000(ra_hours, dec_deg)
            return ra_h_j2000._degrees, dec_deg_j2000._degrees

        return ra_deg, dec_deg

    @classmethod
    def convert_coordinates(cls, coord_format, fields, dec_sign, current_epoch):
        """Convert coordinates based on format and epoch"""
        try:
            if coord_format == 0:  # HMS/DMS
                ra_deg, dec_deg = cls.hms_dms_to_degrees(fields, dec_sign)
            elif coord_format == 1:  # Mixed
                ra_deg, dec_deg = cls.mixed_to_degrees(fields, dec_sign)
            else:  # Decimal
                ra_deg, dec_deg = cls.decimal_to_degrees(fields, dec_sign)

            # Convert to J2000 if needed
            ra_deg, dec_deg = cls.convert_epoch(ra_deg, dec_deg, current_epoch)

            return ra_deg, dec_deg
        except ValueError:
            return None, None


class FormatConfig:
    """Configuration for coordinate input formats"""

    def __init__(self, name, field_labels, placeholders, coord_field_count, validators):
        self.name = name
        self.field_labels = field_labels
        self.placeholders = placeholders
        self.coord_field_count = coord_field_count
        self.field_count = coord_field_count + 1  # +1 for epoch
        self.validators = validators

    def validate_field(self, field_index, value):
        """Validate field value according to format rules"""
        if not value or field_index >= self.coord_field_count:
            return True

        try:
            validator = self.validators.get(field_index)
            if validator:
                num = validator['type'](value)
                return validator['min'] <= num <= validator['max']
        except ValueError:
            return False
        return True


class CoordinateFormats:
    """Central configuration for all coordinate formats"""

    @staticmethod
    def get_formats():
        return {
            0: FormatConfig(  # HMS/DMS
                name=_("Full"),
                field_labels=["RA_H", "RA_M", "RA_S", "DEC_D", "DEC_M", "DEC_S", "EPOCH"],
                placeholders=["hh", "mm", "ss", "dd", "mm", "ss", "epoch"],
                coord_field_count=6,
                validators={
                    0: {'type': int, 'min': 0, 'max': 23},    # RA hours
                    1: {'type': int, 'min': 0, 'max': 59},    # RA minutes
                    2: {'type': int, 'min': 0, 'max': 59},    # RA seconds
                    3: {'type': int, 'min': -90, 'max': 90},  # DEC degrees
                    4: {'type': int, 'min': 0, 'max': 59},    # DEC minutes
                    5: {'type': int, 'min': 0, 'max': 59},    # DEC seconds
                }
            ),
            1: FormatConfig(  # Mixed
                name=_("H/D"),
                field_labels=["RA_H", "DEC_D", "EPOCH"],
                placeholders=["00.00", "00.00", "epoch"],
                coord_field_count=2,
                validators={
                    0: {'type': float, 'min': 0, 'max': 24},   # RA hours
                    1: {'type': float, 'min': -90, 'max': 90}, # DEC degrees
                }
            ),
            2: FormatConfig(  # Decimal
                name=_("D/D"),
                field_labels=["RA_D", "DEC_D", "EPOCH"],
                placeholders=["000.00", "00.00", "epoch"],
                coord_field_count=2,
                validators={
                    0: {'type': float, 'min': 0, 'max': 360},  # RA degrees
                    1: {'type': float, 'min': -90, 'max': 90}, # DEC degrees
                }
            )
        }

    @staticmethod
    def get_default_fields(coord_format):
        """Get default field values for a format"""
        if coord_format == 0:  # HMS/DMS
            return ["", "", "", "", "", ""]
        else:  # Mixed or Decimal
            formats = CoordinateFormats.get_formats()
            return list(formats[coord_format].placeholders[:-1])  # Exclude epoch


class LayoutConfig:
    """Layout configuration constants for the coordinate entry UI"""

    # Field dimensions
    FIELD_HEIGHT = 16
    FIELD_WIDTH = 24
    FIELD_GAP = 30

    # Positioning
    LABEL_X = 5
    FIELD_START_X = 32
    RA_LABEL_Y = 18
    RA_Y = 28
    DEC_LABEL_Y = 46
    DEC_Y = 56
    EPOCH_LABEL_Y = 74
    EPOCH_Y = 84

    # UI elements
    BOTTOM_BAR_HEIGHT = 24
    CURSOR_WIDTH = 2

    # Mixed/Decimal field width
    MIXED_DECIMAL_FIELD_WIDTH = 50
    FORMAT_INDICATOR_OFFSET = 52


class UIRADecEntry(UIModule):
    __title__ = _("RA/DEC Entry")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.callback = self.item_definition.get("callback")
        self.custom_callback = self.item_definition.get("custom_callback")

        # Coordinate formats and configuration
        self.coord_format = 0
        self.formats = CoordinateFormats.get_formats()
        self.current_format_config = self.formats[self.coord_format]

        # Epoch support: 0=J2000, 1=JNOW, 2=B1950
        self.current_epoch = 0
        self.epoch_names = ["J2000", "JNOW", "B1950"]

        # Cursor for blinking effect
        self.cursor = BlinkingCursor()
        self.cursor_positions = {
            0: [0, 0, 0, 0, 0, 0],  # HMS/DMS cursor positions per field
            1: [0, 0],              # Mixed cursor positions
            2: [0, 0]               # Decimal cursor positions
        }

        # State memory for each format - preserve entries when switching
        self.format_states = {}
        for fmt_id, fmt_config in self.formats.items():
            self.format_states[fmt_id] = {
                "fields": CoordinateFormats.get_default_fields(fmt_id),
                "current_field": 0,
                "epoch": 0
            }

        # Initialize input fields based on format
        self.load_format_state()

        # Current field index
        self.current_field = 0

        # Screen setup - use inherited properties from base class
        self.width = self.display_class.resX
        self.height = self.display_class.resY
        self.red = self.colors.get(255)
        self.black = self.colors.get(0)
        self.half_red = self.colors.get(128)
        self.dim_red = self.colors.get(180)
        # self.screen and self.draw are already created by base class
        self.bold = self.fonts.bold
        self.base = self.fonts.base

        # Layout configuration
        self.layout = LayoutConfig()
        self.field_height = self.layout.FIELD_HEIGHT
        self.label_x = self.layout.LABEL_X
        self.field_start_x = self.layout.FIELD_START_X
        self.ra_label_y = self.layout.RA_LABEL_Y
        self.ra_y = self.layout.RA_Y
        self.dec_label_y = self.layout.DEC_LABEL_Y
        self.dec_y = self.layout.DEC_Y
        self.epoch_label_y = self.layout.EPOCH_LABEL_Y
        self.epoch_y = self.layout.EPOCH_Y
        self.field_width = self.layout.FIELD_WIDTH
        self.field_gap = self.layout.FIELD_GAP

        # Track DEC sign separately to avoid conflict with minus key
        self.dec_sign = "+"


    def load_format_state(self):
        """Load the saved state for current coordinate format"""
        state = self.format_states[self.coord_format]
        self.fields = state["fields"][:]  # Copy the list
        self.current_field = state["current_field"]
        self.current_epoch = state["epoch"]
        # Load cursor positions for this format
        if "cursor_positions" in state:
            self.cursor_positions[self.coord_format] = state["cursor_positions"][:]
        else:
            # Initialize cursor positions for this format
            if self.coord_format == 0:
                self.cursor_positions[self.coord_format] = [0, 0, 0, 0, 0, 0]
            else:
                self.cursor_positions[self.coord_format] = [0, 0]

        # Set field configuration based on current format
        self.current_format_config = self.formats[self.coord_format]
        self.field_labels = self.current_format_config.field_labels
        self.placeholders = self.current_format_config.placeholders
        self.coord_field_count = self.current_format_config.coord_field_count
        self.field_count = self.current_format_config.field_count

    def save_format_state(self):
        """Save the current state before switching formats"""
        self.format_states[self.coord_format] = {
            "fields": self.fields[:],  # Copy the list
            "current_field": self.current_field,
            "epoch": self.current_epoch,
            "cursor_positions": self.cursor_positions[self.coord_format][:]
        }

    def get_field_positions(self):
        """Get screen positions for input fields based on current format"""
        if self.coord_format == 0:  # HMS/DMS
            return self._get_hms_dms_positions()
        else:  # Mixed or Decimal
            return self._get_mixed_decimal_positions()

    def _get_hms_dms_positions(self):
        """Get field positions for HMS/DMS format (6 coordinate fields + epoch)"""
        positions = []
        # RA fields - all aligned and same width
        positions.append((self.field_start_x, self.ra_y, self.field_width))  # RA_H
        positions.append((self.field_start_x + self.field_gap, self.ra_y, self.field_width))  # RA_M
        positions.append((self.field_start_x + self.field_gap * 2, self.ra_y, self.field_width))  # RA_S

        # DEC fields - aligned with RA fields
        positions.append((self.field_start_x, self.dec_y, self.field_width))  # DEC_D
        positions.append((self.field_start_x + self.field_gap, self.dec_y, self.field_width))  # DEC_M
        positions.append((self.field_start_x + self.field_gap * 2, self.dec_y, self.field_width))  # DEC_S

        # Epoch field - spans from field2 to field3 position
        epoch_x = self.field_start_x + self.field_gap
        epoch_width = self.field_start_x + self.field_gap * 2 + self.field_width - epoch_x
        positions.append((epoch_x, self.epoch_y, epoch_width))

        return positions

    def _get_mixed_decimal_positions(self):
        """Get field positions for Mixed/Decimal formats (2 coordinate fields + epoch)"""
        positions = []
        field_width = self.layout.MIXED_DECIMAL_FIELD_WIDTH

        # RA and DEC fields
        positions.append((self.field_start_x, self.ra_y, field_width))
        positions.append((self.field_start_x, self.dec_y, field_width))

        # Epoch field - positioned to align with HMS/DMS layout
        epoch_x = self.field_start_x + self.field_gap
        epoch_width = self.field_start_x + self.field_gap * 2 + self.field_width - epoch_x
        positions.append((epoch_x, self.epoch_y, epoch_width))

        return positions

    def get_cursor_position(self, field_index):
        """Get cursor position within a field"""
        if field_index >= self.coord_field_count:  # Epoch field has no cursor
            return -1

        if self.coord_format == 0:  # HMS/DMS
            # Simple cursor at end of field content
            return len(self.fields[field_index])
        else:  # Mixed/Decimal
            # Use tracked cursor position, but cap at field length
            cursor_pos = self.cursor_positions[self.coord_format][field_index]
            field_value = self.fields[field_index]
            # Don't let cursor go past decimal point or end of field
            max_pos = len(field_value) - 1
            if '.' in field_value:
                decimal_pos = field_value.index('.')
                if cursor_pos == decimal_pos:
                    cursor_pos += 1  # Skip over decimal point
            return min(cursor_pos, max_pos)

    def draw_coordinate_fields(self):
        """Draw the coordinate input fields"""
        positions = self.get_field_positions()

        # Draw all field outlines and content
        for i in range(self.field_count):
            self._draw_single_field(i, positions[i])

        # Draw labels and format-specific elements
        self._draw_field_labels()
        self._draw_format_separators()
        self._draw_format_indicators()

    def _draw_single_field(self, field_index, position):
        """Draw a single input field with outline, text, and cursor"""
        x, y, width = position

        # Draw field outline
        self._draw_field_outline(x, y, width, field_index == self.current_field)

        # Get field text and color
        text, color = self._get_field_text_and_color(field_index)

        # Draw text centered in field
        text_width = self._draw_field_text(x, y, width, text, color)

        # Draw cursor if this is the current field (not for epoch field)
        if field_index == self.current_field and field_index != self.field_count - 1:
            self._draw_field_cursor(x, y, width, text, text_width, field_index)

    def _draw_field_outline(self, x, y, width, is_current):
        """Draw the outline rectangle for a field"""
        outline_color = self.red if is_current else self.half_red
        outline_width = 2 if is_current else 1

        self.draw.rectangle(
            [x, y, x + width, y + self.field_height],
            outline=outline_color,
            width=outline_width,
        )

    def _get_field_text_and_color(self, field_index):
        """Get the display text and color for a field"""
        if field_index == self.field_count - 1:  # Epoch field
            return self.epoch_names[self.current_epoch], self.red

        # Regular coordinate field
        text = self.fields[field_index]

        # Handle DEC sign for HMS/DMS format
        if field_index == 3 and self.coord_format == 0:  # DEC degrees in HMS/DMS
            if text:
                text = f"{self.dec_sign}{text}"
            else:
                text = f"{self.dec_sign}dd" if field_index != self.current_field else ""

        # Determine color based on content
        if not text and field_index != self.current_field:
            # Show placeholder if field is empty and not selected
            text = self.placeholders[field_index]
            color = self.dim_red
        else:
            color = self.red

        return text, color

    def _draw_field_text(self, x, y, width, text, color):
        """Draw text centered in field and return text width"""
        text_width = 0
        if text:
            text_bbox = self.base.font.getbbox(text)
            text_width = text_bbox[2] - text_bbox[0]
            text_x = x + (width - text_width) // 2
            text_y = y + (self.field_height - 12) // 2
            self.draw.text((text_x, text_y), text, font=self.base.font, fill=color)
        return text_width

    def _draw_field_cursor(self, x, y, width, text, text_width, field_index):
        """Draw the blinking cursor for the current field"""
        cursor_pos = self.get_cursor_position(field_index)
        if cursor_pos >= 0:
            # Calculate cursor x position based on character position
            if text and cursor_pos < len(text):
                text_before_cursor = text[:cursor_pos]
                if text_before_cursor:
                    cursor_text_width = self.base.font.getbbox(text_before_cursor)[2]
                    cursor_x = x + (width - text_width) // 2 + cursor_text_width
                else:
                    cursor_x = x + (width - text_width) // 2
            else:
                # Cursor at end of text
                cursor_x = x + (width - text_width) // 2 + text_width

            # Draw the cursor using the extracted component
            self.cursor.draw(self.screen, cursor_x, y, self.layout.CURSOR_WIDTH, self.field_height)

    def _draw_field_labels(self):
        """Draw coordinate labels (RA:, DEC:, EPOCH:)"""
        label_offset = (self.field_height - 12) // 2
        self.draw.text((self.label_x, self.ra_y + label_offset), _("RA:"), font=self.base.font, fill=self.red)
        self.draw.text((self.label_x, self.dec_y + label_offset), _("DEC:"), font=self.base.font, fill=self.red)
        self.draw.text((self.label_x, self.epoch_y + label_offset), _("EPOCH:"), font=self.base.font, fill=self.red)

    def _draw_format_separators(self):
        """Draw colons for HMS/DMS format"""
        if self.coord_format == 0:  # HMS/DMS format
            gap_center1 = self.field_start_x + self.field_width
            gap_center2 = gap_center1 + self.field_gap

            # Draw colons for RA
            self.draw.text((gap_center1, self.ra_y), ":", font=self.base.font, fill=self.red)
            self.draw.text((gap_center2, self.ra_y), ":", font=self.base.font, fill=self.red)

            # Draw colons for DEC
            self.draw.text((gap_center1, self.dec_y), ":", font=self.base.font, fill=self.red)
            self.draw.text((gap_center2, self.dec_y), ":", font=self.base.font, fill=self.red)

    def _draw_format_indicators(self):
        """Draw unit indicators (h, °) for Mixed and Decimal formats"""
        if self.coord_format in [1, 2]:  # Mixed or Decimal
            indicator_x = self.field_start_x + self.layout.FORMAT_INDICATOR_OFFSET

            if self.coord_format == 1:  # Mixed format
                self.draw.text((indicator_x, self.ra_y + 4), "h", font=self.base.font, fill=self.half_red)
                self.draw.text((indicator_x, self.dec_y + 4), "°", font=self.base.font, fill=self.half_red)
            else:  # Decimal format
                self.draw.text((indicator_x, self.ra_y + 4), "°", font=self.base.font, fill=self.half_red)
                self.draw.text((indicator_x, self.dec_y + 4), "°", font=self.base.font, fill=self.half_red)


    def draw_bottom_bar(self):
        """Draw bottom bar with navigation instructions"""
        bar_y = self.height - self.layout.BOTTOM_BAR_HEIGHT

        # Draw separator line
        self.draw.line([(2, bar_y), (self.width - 2, bar_y)], fill=self.half_red, width=1)

        # Icons separated from translatable text
        square_icon = "󰝤"
        arrow_icons = "󰹺"
        enter_icon = ""
        exit_icon = ""

        # Build more readable instruction lines by grouping logically
        line1_translated = f"{square_icon}{_('Format')} {arrow_icons}{_('Nav')} +{_('Switch')}"
        line2_translated = f"{enter_icon}{_('Enter')} {exit_icon}{_('Exit')} -{_('Del')}"
        self.draw.text((2, bar_y + 2), line1_translated, font=self.base.font, fill=self.red)
        self.draw.text((2, bar_y + 12), line2_translated, font=self.base.font, fill=self.red)

    def validate_field(self, field_index, value):
        """Validate the entered value for the given field"""
        return self.current_format_config.validate_field(field_index, value)

    def key_number(self, number):
        """Handle numeric input"""
        # Don't allow numeric input on epoch field
        if self.current_field == self.field_count - 1:
            return

        if self.coord_format == 0:  # HMS/DMS format
            self._handle_hms_dms_input(number)
        else:  # Mixed/Decimal formats
            self._handle_decimal_input(number)

    def _handle_hms_dms_input(self, number):
        """Handle numeric input for HMS/DMS format (simple append)"""
        current = self.fields[self.current_field]
        new_value = current + str(number)

        # Limit field length
        if len(new_value) > 2:
            return

        # Validate and set
        if self.validate_field(self.current_field, new_value):
            self.fields[self.current_field] = new_value

            # Auto-advance when field is full
            if len(new_value) == 2:
                next_field = (self.current_field + 1) % self.field_count
                if next_field != self.field_count - 1:  # Not epoch field
                    self.current_field = next_field

    def _handle_decimal_input(self, number):
        """Handle numeric input for Mixed/Decimal formats (cursor-based)"""
        current = self.fields[self.current_field]
        cursor_pos = self.cursor_positions[self.coord_format][self.current_field]
        new_value = list(current)

        # Skip over decimal point if cursor is at that position
        if cursor_pos < len(new_value) and new_value[cursor_pos] == '.':
            cursor_pos += 1

        # Replace character at cursor position
        if cursor_pos < len(new_value):
            new_value[cursor_pos] = str(number)
            new_value = ''.join(new_value)

            # Validate and set
            if self.validate_field(self.current_field, new_value):
                self.fields[self.current_field] = new_value
                # Advance cursor position
                self.cursor_positions[self.coord_format][self.current_field] = cursor_pos + 1

    def key_minus(self):
        """Delete last digit in current field or move to previous field"""
        # Don't allow deletion on epoch field - just move to previous field
        if self.current_field == self.field_count - 1:
            self.current_field = (self.current_field - 1) % self.field_count
            return

        if self.coord_format == 0:  # HMS/DMS format
            self._handle_hms_dms_deletion()
        else:  # Mixed/Decimal formats
            self._handle_decimal_deletion()

    def _handle_hms_dms_deletion(self):
        """Handle deletion for HMS/DMS format (simple backspace)"""
        if self.fields[self.current_field]:
            # Delete the last digit
            self.fields[self.current_field] = self.fields[self.current_field][:-1]
        else:
            # Move to previous field if current is empty
            self.current_field = (self.current_field - 1) % self.field_count

    def _handle_decimal_deletion(self):
        """Handle deletion for Mixed/Decimal formats (cursor-based)"""
        cursor_pos = self.cursor_positions[self.coord_format][self.current_field]
        if cursor_pos > 0:
            current = self.fields[self.current_field]
            new_value = list(current)

            # Move cursor back (skip over decimal point)
            cursor_pos -= 1
            if cursor_pos >= 0 and new_value[cursor_pos] == '.':
                cursor_pos -= 1

            # Replace character at cursor position with zero
            if cursor_pos >= 0:
                new_value[cursor_pos] = '0'
                self.fields[self.current_field] = ''.join(new_value)
                self.cursor_positions[self.coord_format][self.current_field] = cursor_pos

    def key_plus(self):
        """Toggle DEC sign when on DEC degree field, or cycle epoch when on epoch field"""
        # Check if we're on DEC degree field
        if (self.coord_format == 0 and self.current_field == 3) or \
           (self.coord_format > 0 and self.current_field == 1):
            # Toggle DEC sign
            self.dec_sign = "-" if self.dec_sign == "+" else "+"
        elif self.current_field == self.field_count - 1:  # On epoch field
            # Cycle through epochs: J2000 -> JNOW -> B1950 -> J2000
            self.current_epoch = (self.current_epoch + 1) % 3

    def key_up(self):
        """Move to previous field"""
        self.current_field = (self.current_field - 1) % self.field_count

    def key_down(self):
        """Move to next field"""
        self.current_field = (self.current_field + 1) % self.field_count

    def key_right(self):
        """Confirm entry and exit"""
        # Validate and save coordinates
        ra_deg, dec_deg = self.get_coordinates()
        if ra_deg is not None and dec_deg is not None:
            # Valid coordinates entered - execute callback if available
            if self.custom_callback:
                self.custom_callback(self, ra_deg, dec_deg)
            elif self.callback:
                self.callback(self, ra_deg, dec_deg)
            return True  # Exit screen after successful entry
        return False  # Stay on screen if coordinates are invalid

    def key_left(self):
        """Exit screen"""
        return True

    def key_square(self):
        """Switch coordinate format"""
        # Save current state before switching
        self.save_format_state()

        # Switch to next format
        self.coord_format = (self.coord_format + 1) % len(self.formats)
        self.current_format_config = self.formats[self.coord_format]

        # Load the saved state for the new format
        self.load_format_state()

    def get_coordinates(self):
        """Convert current input to decimal degrees"""
        return CoordinateConverter.convert_coordinates(
            self.coord_format, self.fields, self.dec_sign, self.current_epoch
        )

    def inactive(self):
        """Called when the module is no longer active"""
        # Don't call callback in inactive - callbacks should only be called
        # when user explicitly confirms coordinates (right key)
        pass

    def update(self, force=False):
        """Update the screen display"""
        # Clear only below title bar (title bar is ~15 pixels high)
        self.draw.rectangle((0, self.display_class.titlebar_height, self.width, self.height), fill=self.black)

        # Update title to show current format
        self.title = _("RA/DEC") + f" {self.current_format_config.name}"

        self.draw_coordinate_fields()
        self.draw_bottom_bar()

        if self.shared_state:
            self.shared_state.set_screen(self.screen)
        return self.screen_update()
