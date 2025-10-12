from PiFinder.ui.base import UIModule
from PiFinder import calc_utils
import time
from typing import Any, TYPE_CHECKING, List, Dict
from dataclasses import dataclass, replace

if TYPE_CHECKING:

    def _(a) -> Any:
        return a


@dataclass(frozen=True)
class CoordinateState:
    """Immutable state representation for coordinate entry"""

    coord_format: int
    fields: List[str]
    current_field: int
    current_epoch: int
    dec_sign: str
    cursor_positions: Dict[int, List[int]]

    def with_field_updated(self, field_index: int, value: str) -> "CoordinateState":
        new_fields = self.fields.copy()
        new_fields[field_index] = value
        return replace(
            self, fields=new_fields, cursor_positions=self.cursor_positions.copy()
        )

    def with_current_field_changed(self, new_field: int) -> "CoordinateState":
        return replace(
            self,
            current_field=new_field,
            fields=self.fields.copy(),
            cursor_positions=self.cursor_positions.copy(),
        )

    def with_format_changed(
        self,
        new_format: int,
        new_fields: List[str],
        new_cursor_positions: Dict[int, List[int]],
    ) -> "CoordinateState":
        return replace(
            self,
            coord_format=new_format,
            fields=new_fields,
            current_field=0,
            cursor_positions=new_cursor_positions,
        )

    def with_epoch_changed(self, new_epoch: int) -> "CoordinateState":
        return replace(
            self,
            current_epoch=new_epoch,
            fields=self.fields.copy(),
            cursor_positions=self.cursor_positions.copy(),
        )

    def with_dec_sign_toggled(self) -> "CoordinateState":
        return replace(
            self,
            dec_sign="-" if self.dec_sign == "+" else "+",
            fields=self.fields.copy(),
            cursor_positions=self.cursor_positions.copy(),
        )

    def with_cursor_updated(
        self, field_index: int, new_position: int
    ) -> "CoordinateState":
        new_cursor_positions = {
            fmt: pos.copy() for fmt, pos in self.cursor_positions.items()
        }
        if self.coord_format in new_cursor_positions:
            new_cursor_positions[self.coord_format][field_index] = new_position
        return replace(
            self, fields=self.fields.copy(), cursor_positions=new_cursor_positions
        )


class BlinkingCursor:
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
                            current_pixel[1] // 2,  # Dim green
                            current_pixel[2] // 2,  # Dim blue
                        )
                        screen.putpixel((pixel_x, pixel_y), blended_pixel)


class CoordinateConverter:
    """Handles coordinate format conversion and epoch transformations"""

    def hms_dms_to_degrees(self, fields, dec_sign):
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

    def convert_epoch(self, ra_deg, dec_deg, current_epoch):
        """Convert coordinates from current epoch to J2000"""
        if current_epoch == 0:  # Already J2000
            return ra_deg, dec_deg

        from skyfield.constants import T0 as J2000

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

    def convert_coordinates(self, coord_format, fields, dec_sign, current_epoch):
        """Convert coordinates based on format and epoch"""
        try:
            if coord_format == 0:  # HMS/DMS
                ra_deg, dec_deg = self.hms_dms_to_degrees(fields, dec_sign)
            elif coord_format == 1:  # Mixed
                ra_deg, dec_deg = self.mixed_to_degrees(fields, dec_sign)
            else:  # Decimal
                ra_deg, dec_deg = self.decimal_to_degrees(fields, dec_sign)

            # Convert to J2000 if needed
            ra_deg, dec_deg = self.convert_epoch(ra_deg, dec_deg, current_epoch)

            return ra_deg, dec_deg
        except ValueError:
            return None, None


class CoordinateEntryLogic:
    """business logic for coordinate entry, separate from UI concerns"""

    def __init__(self):
        # Initialize formats
        self.formats = CoordinateFormats.get_formats()
        self.epoch_names = ["J2000", "JNOW", "B1950"]

        # Initialize state
        self._state = self._create_initial_state()

    def _create_initial_state(self) -> CoordinateState:
        """Create initial coordinate state"""
        # Initialize format states for all formats
        cursor_positions = {
            0: [0, 0, 0, 0, 0, 0],  # HMS/DMS
            1: [0, 0],  # Mixed
            2: [0, 0],  # Decimal
        }

        return CoordinateState(
            coord_format=0,
            fields=CoordinateFormats.get_default_fields(0),
            current_field=0,
            current_epoch=0,
            dec_sign="+",
            cursor_positions=cursor_positions,
        )

    def get_current_state(self) -> CoordinateState:
        """Get current immutable state"""
        return self._state

    def get_current_format_config(self) -> "FormatConfig":
        """Get configuration for current format"""
        return self.formats[self._state.coord_format]

    def validate_field(self, field_index: int, value: str) -> bool:
        """Validate field input without UI dependencies"""
        format_config = self.get_current_format_config()
        return format_config.validate_field(field_index, value)

    def handle_numeric_input(self, number: int) -> CoordinateState:
        """Process numeric input based on current format"""
        if (
            self._state.current_field
            >= self.get_current_format_config().coord_field_count
        ):
            return self._state  # Don't allow numeric input on epoch field

        if self._state.coord_format == 0:  # HMS/DMS format
            new_state = self._handle_hms_dms_input(number)
        else:  # Mixed/Decimal formats
            new_state = self._handle_decimal_input(number)

        self._state = new_state
        return self._state

    def _validate_and_update(
        self, new_value: str, tentative_state: CoordinateState
    ) -> CoordinateState:
        """Common validation and update logic"""
        if not self.validate_field(self._state.current_field, new_value):
            return self._state
        if not self.get_current_format_config().validate_dms_combination(
            tentative_state.fields, tentative_state.dec_sign, self._state.current_field
        ):
            return self._state
        return tentative_state

    def _handle_hms_dms_input(self, number: int) -> CoordinateState:
        """Handle numeric input for HMS/DMS format"""
        current_value = self._state.fields[self._state.current_field]
        new_value = current_value + str(number)
        if len(new_value) > 2:
            return self._state

        tentative_state = self._state.with_field_updated(
            self._state.current_field, new_value
        )
        new_state = self._validate_and_update(new_value, tentative_state)
        if new_state == self._state:
            return self._state

        # Auto-advance when field is full
        if len(new_value) == 2:
            format_config = self.get_current_format_config()
            next_field = (self._state.current_field + 1) % format_config.field_count
            if next_field != format_config.field_count - 1:  # Not epoch field
                new_state = new_state.with_current_field_changed(next_field)
        return new_state

    def _handle_decimal_input(self, number: int) -> CoordinateState:
        """Handle numeric input for Mixed/Decimal formats"""
        current_value = self._state.fields[self._state.current_field]
        cursor_pos = self._state.cursor_positions[self._state.coord_format][
            self._state.current_field
        ]
        new_value_list = list(current_value)

        # Skip over decimal point if cursor is at that position
        if cursor_pos < len(new_value_list) and new_value_list[cursor_pos] == ".":
            cursor_pos += 1

        # Replace character at cursor position
        if cursor_pos < len(new_value_list):
            new_value_list[cursor_pos] = str(number)
            new_value = "".join(new_value_list)
            tentative_state = self._state.with_field_updated(
                self._state.current_field, new_value
            ).with_cursor_updated(self._state.current_field, cursor_pos + 1)
            return self._validate_and_update(new_value, tentative_state)
        return self._state

    def handle_deletion(self) -> CoordinateState:
        """Handle deletion logic"""
        # Don't allow deletion on epoch field - just move to previous field
        format_config = self.get_current_format_config()
        if self._state.current_field == format_config.field_count - 1:
            new_field = (self._state.current_field - 1) % format_config.field_count
            new_state = self._state.with_current_field_changed(new_field)
            self._state = new_state
            return self._state

        if self._state.coord_format == 0:  # HMS/DMS format
            new_state = self._handle_hms_dms_deletion()
        else:  # Mixed/Decimal formats
            new_state = self._handle_decimal_deletion()

        self._state = new_state
        return self._state

    def _handle_hms_dms_deletion(self) -> CoordinateState:
        """Handle deletion for HMS/DMS format"""
        if self._state.fields[self._state.current_field]:
            # Delete the last digit
            current_value = self._state.fields[self._state.current_field]
            new_value = current_value[:-1]
            return self._state.with_field_updated(self._state.current_field, new_value)
        else:
            # Move to previous field if current is empty
            format_config = self.get_current_format_config()
            new_field = (self._state.current_field - 1) % format_config.field_count
            return self._state.with_current_field_changed(new_field)

    def _handle_decimal_deletion(self) -> CoordinateState:
        """Handle deletion for Mixed/Decimal formats"""
        cursor_pos = self._state.cursor_positions[self._state.coord_format][
            self._state.current_field
        ]
        if cursor_pos > 0:
            current_value = self._state.fields[self._state.current_field]
            new_value_list = list(current_value)

            # Move cursor back (skip over decimal point)
            cursor_pos -= 1
            if cursor_pos >= 0 and new_value_list[cursor_pos] == ".":
                cursor_pos -= 1

            # Replace character at cursor position with zero
            if cursor_pos >= 0:
                new_value_list[cursor_pos] = "0"
                new_value = "".join(new_value_list)
                new_state = self._state.with_field_updated(
                    self._state.current_field, new_value
                )
                return new_state.with_cursor_updated(
                    self._state.current_field, cursor_pos
                )

        return self._state

    def toggle_dec_sign(self) -> CoordinateState:
        """Toggle DEC sign when on appropriate field"""
        # Check if we're on DEC degree field
        if (self._state.coord_format == 0 and self._state.current_field == 3) or (
            self._state.coord_format > 0 and self._state.current_field == 1
        ):
            new_state = self._state.with_dec_sign_toggled()
            self._state = new_state
            return self._state
        return self._state

    def cycle_epoch(self) -> CoordinateState:
        """Cycle through epochs when on epoch field"""
        format_config = self.get_current_format_config()
        if self._state.current_field == format_config.field_count - 1:  # On epoch field
            new_epoch = (self._state.current_epoch + 1) % 3
            new_state = self._state.with_epoch_changed(new_epoch)
            self._state = new_state
            return self._state
        return self._state

    def move_to_previous_field(self) -> CoordinateState:
        """Move to previous field"""
        format_config = self.get_current_format_config()
        new_field = (self._state.current_field - 1) % format_config.field_count
        new_state = self._state.with_current_field_changed(new_field)
        self._state = new_state
        return self._state

    def move_to_next_field(self) -> CoordinateState:
        """Move to next field"""
        format_config = self.get_current_format_config()
        new_field = (self._state.current_field + 1) % format_config.field_count
        new_state = self._state.with_current_field_changed(new_field)
        self._state = new_state
        return self._state

    def switch_format(self) -> CoordinateState:
        """Switch coordinate format and preserve appropriate state"""
        next_format = (self._state.coord_format + 1) % len(self.formats)
        new_fields = CoordinateFormats.get_default_fields(next_format)

        # Initialize cursor positions for new format
        new_cursor_positions = self._state.cursor_positions.copy()
        if next_format not in new_cursor_positions:
            if next_format == 0:
                new_cursor_positions[next_format] = [0, 0, 0, 0, 0, 0]
            else:
                new_cursor_positions[next_format] = [0, 0]

        new_state = self._state.with_format_changed(
            next_format, new_fields, new_cursor_positions
        )
        self._state = new_state
        return self._state

    def get_coordinates(self) -> tuple:
        """Convert current state to decimal degrees"""
        converter = CoordinateConverter()

        return converter.convert_coordinates(
            self._state.coord_format,
            self._state.fields,
            self._state.dec_sign,
            self._state.current_epoch,
        )


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
                num = validator["type"](value)
                return validator["min"] <= num <= validator["max"]
        except ValueError:
            return False
        return True

    def validate_dms_combination(self, fields, dec_sign, field_index):
        """Validate that combined DMS values don't exceed ±90° for declination

        Args:
            fields: List of field values
            dec_sign: "+" or "-"
            field_index: The field being updated (3=deg, 4=min, 5=sec for HMS/DMS)

        Returns:
            bool: True if the combined DMS value is valid (≤ ±90°)
        """
        # Only validate DEC fields in HMS/DMS format (check coord_field_count=6 instead of name)
        if self.coord_field_count != 6 or field_index not in [3, 4, 5]:
            return True

        try:
            # Get DEC components, using empty strings as 0
            deg_str = fields[3] if len(fields) > 3 else ""
            min_str = fields[4] if len(fields) > 4 else ""
            sec_str = fields[5] if len(fields) > 5 else ""

            deg = int(deg_str) if deg_str else 0
            minutes = int(min_str) if min_str else 0
            seconds = int(sec_str) if sec_str else 0

            # Calculate total decimal degrees
            total_deg = abs(deg) + (minutes / 60.0) + (seconds / 3600.0)

            # Must not exceed 90 degrees
            return total_deg <= 90.0

        except (ValueError, IndexError):
            # If we can't parse the values, allow the input
            # Individual field validation will catch format errors
            return True


class CoordinateFormats:
    @staticmethod
    def get_formats():
        return {
            0: FormatConfig(
                _("Full"),
                ["RA_H", "RA_M", "RA_S", "DEC_D", "DEC_M", "DEC_S", "EPOCH"],
                ["hh", "mm", "ss", "dd", "mm", "ss", "epoch"],
                6,
                {
                    0: {"type": int, "min": 0, "max": 23},
                    1: {"type": int, "min": 0, "max": 59},
                    2: {"type": int, "min": 0, "max": 59},
                    3: {"type": int, "min": -90, "max": 90},
                    4: {"type": int, "min": 0, "max": 59},
                    5: {"type": int, "min": 0, "max": 59},
                },
            ),
            1: FormatConfig(
                _("H/D"),
                ["RA_H", "DEC_D", "EPOCH"],
                ["00.00", "00.00", "epoch"],
                2,
                {
                    0: {"type": float, "min": 0, "max": 24},
                    1: {"type": float, "min": -90, "max": 90},
                },
            ),
            2: FormatConfig(
                _("D/D"),
                ["RA_D", "DEC_D", "EPOCH"],
                ["000.00", "00.00", "epoch"],
                2,
                {
                    0: {"type": float, "min": 0, "max": 360},
                    1: {"type": float, "min": -90, "max": 90},
                },
            ),
        }

    @staticmethod
    def get_default_fields(coord_format):
        return (
            ["", "", "", "", "", ""]
            if coord_format == 0
            else list(CoordinateFormats.get_formats()[coord_format].placeholders[:-1])
        )


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

        # Create business logic instance
        self.logic = CoordinateEntryLogic()

        # Create cursor for blinking effect
        self.cursor = BlinkingCursor()

        # set up class data elements
        self.coord_format: int = 0

        # Get initial state from logic
        self._sync_from_logic()

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

    def _sync_from_logic(self):
        state = self.logic.get_current_state()
        format_config = self.logic.get_current_format_config()
        # Bulk update UI state
        self.__dict__.update(
            {
                "coord_format": state.coord_format,
                "fields": state.fields,
                "current_field": state.current_field,
                "current_epoch": state.current_epoch,
                "dec_sign": state.dec_sign,
                "cursor_positions": state.cursor_positions,
                "current_format_config": format_config,
                "field_labels": format_config.field_labels,
                "placeholders": format_config.placeholders,
                "coord_field_count": format_config.coord_field_count,
                "field_count": format_config.field_count,
                "epoch_names": self.logic.epoch_names,
            }
        )

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
        positions.append(
            (self.field_start_x + self.field_gap, self.ra_y, self.field_width)
        )  # RA_M
        positions.append(
            (self.field_start_x + self.field_gap * 2, self.ra_y, self.field_width)
        )  # RA_S

        # DEC fields - aligned with RA fields
        positions.append((self.field_start_x, self.dec_y, self.field_width))  # DEC_D
        positions.append(
            (self.field_start_x + self.field_gap, self.dec_y, self.field_width)
        )  # DEC_M
        positions.append(
            (self.field_start_x + self.field_gap * 2, self.dec_y, self.field_width)
        )  # DEC_S

        # Epoch field - spans from field2 to field3 position
        epoch_x = self.field_start_x + self.field_gap
        epoch_width = (
            self.field_start_x + self.field_gap * 2 + self.field_width - epoch_x
        )
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
        epoch_width = (
            self.field_start_x + self.field_gap * 2 + self.field_width - epoch_x
        )
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
            if "." in field_value:
                decimal_pos = field_value.index(".")
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
        self._draw_format_decorations()

    def _draw_single_field(self, field_index, position):
        """Draw a single input field with outline, text, and cursor"""
        x, y, width = position

        # Draw field outline
        self._draw_field_outline(x, y, width, field_index == self.current_field)

        # Get field text and color
        text, color = self._get_field_text_and_color(field_index)

        self._draw_field_complete(x, y, width, text, color, field_index)

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

        # Determine color based on content
        if not text and field_index != self.current_field:
            # Show placeholder if field is empty and not selected
            text = self.placeholders[field_index]
            color = self.dim_red
        else:
            color = self.red

        return text, color

    def _draw_field_complete(self, x, y, width, text, color, field_index):
        """Draw field text and cursor in one method"""
        text_width = 0
        text_y = y + (self.field_height - 12) // 2
        base_text_x = x

        # draw DEC sign if dec field
        if self._is_dec_field(field_index):
            self.draw.text(
                (base_text_x + 3, text_y),
                self.dec_sign,
                font=self.base.font,
                fill=color,
            )
            base_text_x += 2  # offset text position for sign
        if text:
            text_bbox = self.base.font.getbbox(text)
            text_width = text_bbox[2] - text_bbox[0]
            text_x = base_text_x + (width - text_width) // 2
            self.draw.text((text_x, text_y), text, font=self.base.font, fill=color)

        # Draw cursor if this is the current field
        cursor_pos = self.get_cursor_position(field_index)
        if cursor_pos >= 0 and field_index == self.current_field:
            if text and cursor_pos < len(text):
                text_before_cursor = text[:cursor_pos]
                cursor_text_width = (
                    self.base.font.getbbox(text_before_cursor)[2]
                    if text_before_cursor
                    else 0
                )
                cursor_x = base_text_x + (width - text_width) // 2 + cursor_text_width
            else:
                cursor_x = base_text_x + (width - text_width) // 2 + text_width
            self.cursor.draw(
                self.screen, cursor_x, y, self.layout.CURSOR_WIDTH, self.field_height
            )

    def _draw_field_labels(self):
        """Draw coordinate labels (RA:, DEC:, EPOCH:)"""
        label_offset = (self.field_height - 12) // 2
        self.draw.text(
            (self.label_x, self.ra_y + label_offset),
            _("RA:"),
            font=self.base.font,
            fill=self.red,
        )
        self.draw.text(
            (self.label_x, self.dec_y + label_offset),
            _("DEC:"),
            font=self.base.font,
            fill=self.red,
        )
        self.draw.text(
            (self.label_x, self.epoch_y + label_offset),
            _("EPOCH:"),
            font=self.base.font,
            fill=self.red,
        )

    def _draw_format_decorations(self):
        """Draw format-specific separators and indicators"""
        if self.coord_format == 0:  # HMS/DMS format - draw colons
            gap_center1, gap_center2 = (
                self.field_start_x + self.field_width,
                self.field_start_x + self.field_width + self.field_gap,
            )
            for y in [self.ra_y, self.dec_y]:
                self.draw.text(
                    (gap_center1, y), ":", font=self.base.font, fill=self.red
                )
                self.draw.text(
                    (gap_center2, y), ":", font=self.base.font, fill=self.red
                )
        elif self.coord_format in [1, 2]:  # Mixed/Decimal - draw unit indicators
            indicator_x = self.field_start_x + self.layout.FORMAT_INDICATOR_OFFSET
            ra_unit, dec_unit = ("h", "°") if self.coord_format == 1 else ("°", "°")
            self.draw.text(
                (indicator_x, self.ra_y + 4),
                ra_unit,
                font=self.base.font,
                fill=self.half_red,
            )
            self.draw.text(
                (indicator_x, self.dec_y + 4),
                dec_unit,
                font=self.base.font,
                fill=self.half_red,
            )

    def _is_dec_field(self, field_index: int) -> bool:
        """Returns True if the provided field index is
        referring to a DEC entry field"""
        if (field_index == 3 and self.coord_format == 0) or (
            field_index == 1 and self.coord_format > 0
        ):
            return True
        return False

    def draw_bottom_bar(self):
        """Draw bottom bar with navigation instructions"""
        bar_y = self.height - self.layout.BOTTOM_BAR_HEIGHT

        # Draw separator line
        self.draw.line(
            [(2, bar_y), (self.width - 2, bar_y)], fill=self.half_red, width=1
        )

        # Icons separated from translatable text
        square_icon = "󰝤"
        arrow_icons = "󰹺"
        back_icon = ""
        go_icon = ""

        # Build more readable instruction lines by grouping logically

        # Line 1 changes based on field selected
        if self._is_dec_field(self.current_field):
            line1 = f"{square_icon}{_('Format')} {arrow_icons}{_('Nav')} +{_('Sign')}"
        elif self.current_field == self.field_count - 1:  # epoch
            line1 = f"{square_icon}{_('Format')} {arrow_icons}{_('Nav')} +{_('Toggle')}"
        else:
            line1 = f"{square_icon}{_('Format')} {arrow_icons}{_('Nav')}"
        line2 = f"{back_icon}{_('Cancel')} {go_icon}{_('Go ')} -{_('Del')}"
        self.draw.text((2, bar_y + 2), line1, font=self.base.font, fill=self.red)
        self.draw.text((2, bar_y + 12), line2, font=self.base.font, fill=self.red)

    def validate_field(self, field_index, value):
        """Validate the entered value for the given field"""
        return self.current_format_config.validate_field(field_index, value)

    def key_number(self, number):
        """Handle numeric input"""
        self.logic.handle_numeric_input(number)
        self._sync_from_logic()

    def key_minus(self):
        """Delete last digit in current field or move to previous field"""
        self.logic.handle_deletion()
        self._sync_from_logic()

    def key_plus(self):
        """Toggle DEC sign when on DEC degree field, or cycle epoch when on epoch field"""
        # Try both operations - only one will actually modify state
        self.logic.toggle_dec_sign()
        self.logic.cycle_epoch()
        self._sync_from_logic()

    def key_up(self):
        """Move to previous field"""
        self.logic.move_to_previous_field()
        self._sync_from_logic()

    def key_down(self):
        """Move to next field"""
        self.logic.move_to_next_field()
        self._sync_from_logic()

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
        self.logic.switch_format()
        self._sync_from_logic()

    def get_coordinates(self):
        """Convert current input to decimal degrees"""
        return self.logic.get_coordinates()

    def inactive(self):
        """Called when the module is no longer active"""
        # Don't call callback in inactive - callbacks should only be called
        # when user explicitly confirms coordinates (right key)
        pass

    def update(self, force=False):
        """Update the screen display"""
        # Clear only below title bar (title bar is ~15 pixels high)
        self.draw.rectangle(
            (0, self.display_class.titlebar_height, self.width, self.height),
            fill=self.black,
        )

        # Update title to show current format
        self.title = _("RA/DEC") + f" {self.current_format_config.name}"

        self.draw_coordinate_fields()
        self.draw_bottom_bar()

        if self.shared_state:
            self.shared_state.set_screen(self.screen)
        return self.screen_update()
