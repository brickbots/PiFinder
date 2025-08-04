from PIL import Image, ImageDraw

from PiFinder.state import SQM
from PiFinder.ui.base import UIModule
import math

class UISqmEntry(UIModule):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Initialize two empty boxes
        self.boxes = ["", ""]
        self.current_box = 0  # Start with decimals
        if self.shared_state:
            # Get the current sky brightness from shared state
            decimal_part, integer_part = math.modf(self.shared_state.get_sky_brightness())
            # Convert to string with 2 decimal places
            decimal_part = f"{int(decimal_part * 100):02d}"  # Convert
            integer_part = f"{int(integer_part):02d}"  # Convert to string with leading zeros
        else:
            # Default to 0.00 if no shared state is available
            decimal_part, integer_part = "", ""
        self.placeholders = [
            integer_part,
            decimal_part,
        ]

        # Screen setup
        self.width = 128
        self.height = 128
        self.red = self.colors.get(255)
        self.black = self.colors.get(0)
        self.half_red = self.colors.get(128)
        self.screen = Image.new("RGB", (self.width, self.height), "black")
        self.draw = ImageDraw.Draw(self.screen)
        self.bold = self.fonts.bold

        # Layout constants - updated to center the boxes
        self.text_y = 25
        self.box_width = 25
        self.box_height = 20
        self.box_spacing = 15

        # Calculate start_x to center the boxes on screen
        total_width = (2 * self.box_width) + self.box_spacing
        self.start_x = (self.width - total_width) // 2

    def draw_boxes(self):
        # Draw the two boxes with a decimal point between them
        for i in range(2):
            x = self.start_x + i * (self.box_width + self.box_spacing)

            # Draw box outline - highlight current box with a brighter outline
            outline_color = self.red if i == self.current_box else self.half_red
            outline_width = 2 if i == self.current_box else 1

            self.draw.rectangle(
                [x, self.text_y, x + self.box_width, self.text_y + self.box_height],
                outline=outline_color,
                width=outline_width,
            )

            # Draw text or placeholder
            text = self.boxes[i]
            if not text and i != self.current_box:
                # Show placeholder if box is empty and not selected
                text = self.placeholders[i]
                color = self.colors.get(180)  # Brighter color for placeholder
            else:
                color = self.red

            # Center text in box
            text_width = self.bold.font.getbbox(text if text else "00")[2]
            text_x = x + (self.box_width - text_width) // 2
            text_y = self.text_y + 2

            self.draw.text((text_x, text_y), text, font=self.bold.font, fill=color)

            # Draw colon after first two boxes
            if i < 1:
                colon_x = x + self.box_width + self.box_spacing // 2 - 2
                self.draw.text(
                    (colon_x, self.text_y + 2), ".", font=self.bold.font, fill=self.red
                )

        # Draw cursor in current box if empty
        if not self.boxes[self.current_box]:
            x = self.start_x + self.current_box * (self.box_width + self.box_spacing)
            cursor_x = x + 2
            self.draw.rectangle(
                [
                    cursor_x,
                    self.text_y + 2,
                    cursor_x + 8,
                    self.text_y + self.box_height - 2,
                ],
                fill=self.red,
            )

    def draw_separator(self, start_y):
        # Draw a separator line before the legend
        self.draw.line(
            [(10, start_y), (self.width - 10, start_y)], fill=self.half_red, width=1
        )
        return start_y + 5  # Return the Y position after the separator

    def draw_legend(self, start_y):
        legend_y = start_y
        # Still using full red for better visibility but smaller font
        legend_color = self.red

        self.draw.text(
            (10, legend_y),
            _("  Next box"),  # Right
            font=self.fonts.base.font,  # Using base font
            fill=legend_color,
        )
        legend_y += 12  # Standard spacing
        self.draw.text(
            (10, legend_y),
            _("  Done"),  # Left
            font=self.fonts.base.font,
            fill=legend_color,
        )
        legend_y += 12  # Standard spacing
        self.draw.text(
            (10, legend_y),
            _("󰍴  Delete/Previous"),  # minus
            font=self.fonts.base.font,
            fill=legend_color,
        )

    def validate_box(self, box_index, value):
        """Validate the entered value for the given box"""
        if not value:
            return True
        try:
            num = int(value)
            if box_index == 0:
                return 14 <= num <= 22
            else:
                return 0 <= num <= 99
        except ValueError:
            return False

    def key_number(self, number):
        current = self.boxes[self.current_box]
        new_value = current + str(number)

        # Only allow 2 digits per box
        if len(new_value) > 2:
            return

        # Validate the new value
        self.boxes[self.current_box] = new_value
        # Auto-advance to next box if we have 2 digits
        if len(new_value) == 2:
            self.current_box = (self.current_box + 1) % 2

    def key_minus(self):
        """Delete last digit in current box or move to previous box if empty"""
        if self.boxes[self.current_box]:
            # Delete the last digit
            self.boxes[self.current_box] = self.boxes[self.current_box][:-1]
        else:
            # If current box is empty, move to previous box
            self.current_box = (self.current_box - 1) % 2

    def key_right(self):
        """Move to next box"""
        self.current_box = (self.current_box + 1) % 2
        return False

    def inactive(self):
        """Called when the module is no longer the active module"""
        if not self.validate_box(0, self.boxes[0]) or not self.validate_box(1, self.boxes[1]):
            # If any box has invalid value, do nothing
            return

        if not self.boxes[0] or not self.boxes[1]:
            # If both boxes are empty, do nothing
            return

        # Create the SQM value from the boxes
        sqm = float(self.boxes[1]) / 100.0 + float(self.boxes[0])

        # Put the sqm value in a SQM object
        sqm = SQM(sqm, "Manual")
        self.shared_state.set_sqm(sqm)

    def update(self, force=False):
        self.draw.rectangle((0, 0, 128, 128), fill=self.black)

        self.draw_boxes()

        # Draw additional elements with proper positioning
        separator_y = self.draw_separator(65 + 15)
        self.draw_legend(separator_y)
        self.draw_legend(separator_y)

        if self.shared_state:
            self.shared_state.set_screen(self.screen)
        return self.screen_update()
