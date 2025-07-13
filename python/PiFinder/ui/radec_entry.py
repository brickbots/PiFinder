from PIL import Image, ImageDraw
from PiFinder.ui.base import UIModule
from PiFinder import calc_utils


class UIRADecEntry(UIModule):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.callback = self.item_definition.get("callback")
        self.custom_callback = self.item_definition.get("custom_callback")

        # Coordinate formats: 0=HMS/DMS, 1=Mixed, 2=Decimal
        self.coord_format = 0
        self.format_names = ["HMS/DMS", "Mixed", "Decimal"]

        # State memory for each format - preserve entries when switching
        self.format_states = {
            0: {"fields": ["", "", "", "", "", ""], "current_field": 0},  # HMS/DMS
            1: {"fields": ["", ""], "current_field": 0},                  # Mixed
            2: {"fields": ["", ""], "current_field": 0}                   # Decimal
        }

        # Initialize input fields based on format
        self.load_format_state()

        # Current field index
        self.current_field = 0

        # Screen setup
        self.width = 128
        self.height = 128
        self.red = self.colors.get(255)
        self.black = self.colors.get(0)
        self.half_red = self.colors.get(128)
        self.dim_red = self.colors.get(180)
        self.screen = Image.new("RGB", (self.width, self.height), "black")
        self.draw = ImageDraw.Draw(self.screen)
        self.bold = self.fonts.bold
        self.base = self.fonts.base

        # Layout constants - improved spacing
        self.field_height = 18
        self.field_spacing = 6
        self.ra_label_y = 20
        self.ra_y = 32
        self.dec_label_y = 56
        self.dec_y = 68
        self.field_width = 36
        self.small_field_width = 24

    def load_format_state(self):
        """Load the saved state for current coordinate format"""
        state = self.format_states[self.coord_format]
        self.fields = state["fields"][:]  # Copy the list
        self.current_field = state["current_field"]

        # Set field count and placeholders based on format
        if self.coord_format == 0:  # HMS/DMS
            self.field_labels = ["RA_H", "RA_M", "RA_S", "DEC_D", "DEC_M", "DEC_S"]
            self.placeholders = ["hh", "mm", "ss", "±dd", "mm", "ss"]
            self.field_count = 6
        elif self.coord_format == 1:  # Mixed
            self.field_labels = ["RA_H", "DEC_D"]
            self.placeholders = ["hh.hh", "±dd.dd"]
            self.field_count = 2
        else:  # Decimal
            self.field_labels = ["RA_D", "DEC_D"]
            self.placeholders = ["ddd.dd", "±dd.dd"]
            self.field_count = 2

    def save_format_state(self):
        """Save the current state before switching formats"""
        self.format_states[self.coord_format] = {
            "fields": self.fields[:],  # Copy the list
            "current_field": self.current_field
        }

    def get_field_positions(self):
        """Get screen positions for input fields based on current format"""
        positions = []
        if self.coord_format == 0:  # HMS/DMS - 6 fields
            # RA fields with better spacing
            ra_start_x = 8
            field_gap = 30
            positions.append((ra_start_x, self.ra_y, self.small_field_width))  # RA_H
            positions.append((ra_start_x + field_gap, self.ra_y, self.small_field_width))  # RA_M
            positions.append((ra_start_x + field_gap * 2, self.ra_y, self.small_field_width))  # RA_S
            # DEC fields with same spacing
            positions.append((ra_start_x, self.dec_y, self.small_field_width))  # DEC_D
            positions.append((ra_start_x + field_gap, self.dec_y, self.small_field_width))  # DEC_M
            positions.append((ra_start_x + field_gap * 2, self.dec_y, self.small_field_width))  # DEC_S
        else:  # Mixed or Decimal - 2 fields
            positions.append((8, self.ra_y, 55))  # RA field - wider
            positions.append((8, self.dec_y, 55))  # DEC field - wider
        return positions

    def draw_coordinate_fields(self):
        """Draw the coordinate input fields"""
        positions = self.get_field_positions()

        for i in range(self.field_count):
            x, y, width = positions[i]

            # Draw field outline - highlight current field
            outline_color = self.red if i == self.current_field else self.half_red
            outline_width = 2 if i == self.current_field else 1

            self.draw.rectangle(
                [x, y, x + width, y + self.field_height],
                outline=outline_color,
                width=outline_width,
            )

            # Draw text or placeholder
            text = self.fields[i]
            if not text and i != self.current_field:
                # Show placeholder if field is empty and not selected
                text = self.placeholders[i]
                color = self.dim_red
            else:
                color = self.red

            # Center text in field with better padding
            if text:
                text_bbox = self.base.font.getbbox(text)
                text_width = text_bbox[2] - text_bbox[0]
                text_x = x + (width - text_width) // 2
                text_y = y + (self.field_height - 12) // 2  # Better vertical centering
                self.draw.text((text_x, text_y), text, font=self.base.font, fill=color)

            # Draw cursor in current field if empty
            if i == self.current_field and not self.fields[i]:
                cursor_x = x + 2
                self.draw.rectangle(
                    [cursor_x, y + 2, cursor_x + 8, y + self.field_height - 2],
                    fill=self.red,
                )

        # Draw coordinate labels on separate rows
        self.draw.text((10, self.ra_label_y), "RA:", font=self.base.font, fill=self.red)
        self.draw.text((10, self.dec_label_y), "DEC:", font=self.base.font, fill=self.red)

        # Draw separators and format indicators for HMS/DMS format
        if self.coord_format == 0:
            # Draw colons for RA with proper spacing
            self.draw.text((33, self.ra_y + 4), ":", font=self.base.font, fill=self.red)
            self.draw.text((63, self.ra_y + 4), ":", font=self.base.font, fill=self.red)
            # Draw colons for DEC with proper spacing
            self.draw.text((33, self.dec_y + 4), ":", font=self.base.font, fill=self.red)
            self.draw.text((63, self.dec_y + 4), ":", font=self.base.font, fill=self.red)

        # Draw format indicators
        if self.coord_format == 1:
            self.draw.text((68, self.ra_y + 4), "h", font=self.base.font, fill=self.half_red)
            self.draw.text((68, self.dec_y + 4), "°", font=self.base.font, fill=self.half_red)
        elif self.coord_format == 2:
            self.draw.text((68, self.ra_y + 4), "°", font=self.base.font, fill=self.half_red)
            self.draw.text((68, self.dec_y + 4), "°", font=self.base.font, fill=self.half_red)

    def draw_format_indicator(self):
        """Draw current coordinate format at top of screen"""
        format_text = f"Format: {self.format_names[self.coord_format]}"
        self.draw.text((10, 5), format_text, font=self.base.font, fill=self.red)

    def draw_bottom_bar(self):
        """Draw bottom bar with navigation instructions"""
        bar_y = self.height - 28

        # Draw separator line
        self.draw.line([(5, bar_y), (self.width - 5, bar_y)], fill=self.half_red, width=1)

        # Format switch instruction with nerd font icon
        format_text = f" {self.format_names[self.coord_format]}"
        self.draw.text((5, bar_y + 3), format_text, font=self.base.font, fill=self.red)

        # Navigation instructions with nerd font icons
        nav_text = " Navigate"
        self.draw.text((5, bar_y + 13), nav_text, font=self.base.font, fill=self.red)

        # Enter/Exit instructions with nerd font icons
        action_text = " Enter   Exit"
        self.draw.text((65, bar_y + 13), action_text, font=self.base.font, fill=self.red)

    def validate_field(self, field_index, value):
        """Validate the entered value for the given field"""
        if not value:
            return True

        try:
            if self.coord_format == 0:  # HMS/DMS
                num = int(value)
                if field_index == 0:  # RA hours
                    return 0 <= num <= 23
                elif field_index in [1, 2]:  # RA minutes/seconds
                    return 0 <= num <= 59
                elif field_index == 3:  # DEC degrees
                    return -90 <= num <= 90
                elif field_index in [4, 5]:  # DEC minutes/seconds
                    return 0 <= num <= 59
            else:  # Mixed or Decimal
                num = float(value)
                if field_index == 0:  # RA
                    if self.coord_format == 1:  # Mixed - hours
                        return 0 <= num <= 24
                    else:  # Decimal - degrees
                        return 0 <= num <= 360
                elif field_index == 1:  # DEC - degrees
                    return -90 <= num <= 90
        except ValueError:
            return False
        return True

    def key_number(self, number):
        """Handle numeric input"""
        # Add digit to current field
        current = self.fields[self.current_field]
        new_value = current + str(number)

        # Limit field length based on format
        max_len = 6 if self.coord_format > 0 else 2  # Decimal fields longer
        if len(new_value) > max_len:
            return

        # Validate the new value
        if self.validate_field(self.current_field, new_value):
            self.fields[self.current_field] = new_value

            # Auto-advance for HMS/DMS format when field is full
            if self.coord_format == 0 and len(new_value) == 2:
                self.current_field = (self.current_field + 1) % self.field_count

    def key_minus(self):
        """Delete last digit in current field or move to previous field"""
        if self.fields[self.current_field]:
            # Delete the last digit
            self.fields[self.current_field] = self.fields[self.current_field][:-1]
        else:
            # Move to previous field if current is empty
            self.current_field = (self.current_field - 1) % self.field_count

    def key_up(self):
        """Move to previous field"""
        self.current_field = (self.current_field - 1) % self.field_count

    def key_down(self):
        """Move to next field"""
        self.current_field = (self.current_field + 1) % self.field_count

    def key_right(self):
        """Confirm entry and exit"""
        # Could trigger coordinate confirmation here
        return False

    def key_left(self):
        """Exit screen"""
        return True

    def key_square(self):
        """Switch coordinate format"""
        # Save current state before switching
        self.save_format_state()

        # Switch to next format
        self.coord_format = (self.coord_format + 1) % 3

        # Load the saved state for the new format
        self.load_format_state()

    def get_coordinates(self):
        """Convert current input to decimal degrees"""
        try:
            if self.coord_format == 0:  # HMS/DMS
                # Convert RA from HMS to degrees
                ra_h = int(self.fields[0]) if self.fields[0] else 0
                ra_m = int(self.fields[1]) if self.fields[1] else 0
                ra_s = int(self.fields[2]) if self.fields[2] else 0
                ra_deg = calc_utils.ra_to_deg(ra_h, ra_m, ra_s)

                # Convert DEC from DMS to degrees
                dec_d = int(self.fields[3]) if self.fields[3] else 0
                dec_m = int(self.fields[4]) if self.fields[4] else 0
                dec_s = int(self.fields[5]) if self.fields[5] else 0
                dec_deg = calc_utils.dec_to_deg(dec_d, dec_m, dec_s)

            elif self.coord_format == 1:  # Mixed
                # RA in hours, convert to degrees
                ra_hours = float(self.fields[0]) if self.fields[0] else 0
                ra_deg = ra_hours * 15
                # DEC already in degrees
                dec_deg = float(self.fields[1]) if self.fields[1] else 0

            else:  # Decimal
                # Both already in degrees
                ra_deg = float(self.fields[0]) if self.fields[0] else 0
                dec_deg = float(self.fields[1]) if self.fields[1] else 0

            return ra_deg, dec_deg
        except ValueError:
            return None, None

    def inactive(self):
        """Called when the module is no longer active"""
        if self.custom_callback:
            ra_deg, dec_deg = self.get_coordinates()
            if ra_deg is not None and dec_deg is not None:
                self.custom_callback(self, ra_deg, dec_deg)

    def update(self, force=False):
        """Update the screen display"""
        self.draw.rectangle((0, 0, self.width, self.height), fill=self.black)

        self.draw_format_indicator()
        self.draw_coordinate_fields()
        self.draw_bottom_bar()

        if self.shared_state:
            self.shared_state.set_screen(self.screen)
        return self.screen_update()
