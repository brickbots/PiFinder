from PIL import Image, ImageDraw
from PiFinder.ui.base import UIModule
import time

class UITimeEntry(UIModule):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        self.callback = self.item_definition.get('callback')
        self.custom_callback = self.item_definition.get('custom_callback')
        # Initialize three empty boxes for hours, minutes, seconds
        self.boxes = ["", "", ""]
        self.current_box = 0  # Start with hours
        self.placeholders = ["hh", "mm", "ss"]
        
        # Screen setup
        self.width = 128
        self.height = 128
        self.red = self.colors.get(255)
        self.black = self.colors.get(0)
        self.half_red = self.colors.get(128)
        self.screen = Image.new("RGB", (self.width, self.height), "black")
        self.draw = ImageDraw.Draw(self.screen)
        self.bold = self.fonts.bold
        
        # Layout constants
        self.text_y = 25
        self.box_width = 25
        self.box_height = 20
        self.box_spacing = 15
        self.start_x = 20

    def draw_time_boxes(self):
        # Draw the three boxes with colons between them
        for i in range(3):
            x = self.start_x + i * (self.box_width + self.box_spacing)
            
            # Draw box outline
            self.draw.rectangle(
                [x, self.text_y, x + self.box_width, self.text_y + self.box_height],
                outline=self.half_red,
                width=1
            )
            
            # Draw text or placeholder
            text = self.boxes[i]
            if not text and i != self.current_box:
                # Show placeholder if box is empty and not selected
                text = self.placeholders[i]
                color = self.colors.get(64)  # Dimmer color for placeholder
            else:
                color = self.red
            
            # Center text in box
            text_width = self.bold.font.getbbox(text if text else "00")[2]
            text_x = x + (self.box_width - text_width) // 2
            text_y = self.text_y + 2
            
            self.draw.text(
                (text_x, text_y),
                text,
                font=self.bold.font,
                fill=color
            )
            
            # Draw colon after first two boxes
            if i < 2:
                colon_x = x + self.box_width + self.box_spacing // 2 - 2
                self.draw.text(
                    (colon_x, self.text_y + 2),
                    ":",
                    font=self.bold.font,
                    fill=self.red
                )
        
        # Draw cursor in current box if empty
        if not self.boxes[self.current_box]:
            x = self.start_x + self.current_box * (self.box_width + self.box_spacing)
            cursor_x = x + 2
            self.draw.rectangle(
                [cursor_x, self.text_y + 2, cursor_x + 8, self.text_y + self.box_height - 2],
                fill=self.red
            )

    def draw_legend(self):
        legend_y = self.text_y + self.box_height + 15
        self.draw.text(
            (10, legend_y),
            "Right: Next box",
            font=self.fonts.base.font,
            fill=self.half_red
        )
        legend_y += 12
        self.draw.text(
            (10, legend_y),
            "Left/Square: Done",
            font=self.fonts.base.font,
            fill=self.half_red
        )
        legend_y += 12
        self.draw.text(
            (10, legend_y),
            "-: Delete",
            font=self.fonts.base.font,
            fill=self.half_red
        )

    def validate_box(self, box_index, value):
        """Validate the entered value for the given box"""
        if not value:
            return True
        try:
            num = int(value)
            if box_index == 0:  # Hours
                return 0 <= num <= 23
            else:  # Minutes or seconds
                return 0 <= num <= 59
        except ValueError:
            return False

    def key_number(self, number):
        current = self.boxes[self.current_box]
        new_value = current + str(number)
        
        # Only allow 2 digits per box
        if len(new_value) > 2:
            return
            
        # Validate the new value
        if self.validate_box(self.current_box, new_value):
            self.boxes[self.current_box] = new_value
            # Auto-advance to next box if we have 2 digits
            if len(new_value) == 2:
                self.current_box = (self.current_box + 1) % 3

    def key_minus(self):
        """Delete last digit in current box"""
        if self.boxes[self.current_box]:
            self.boxes[self.current_box] = self.boxes[self.current_box][:-1]

    def key_right(self):
        """Move to next box"""
        self.current_box = (self.current_box + 1) % 3
        return False

    def key_square(self):
        """Alternative way to finish time entry"""
        return self.key_left()

    def inactive(self):
        """Called when the module is no longer the active module"""
        if self.custom_callback:
            time_str = f"{self.boxes[0] or '00'}:{self.boxes[1] or '00'}:{self.boxes[2] or '00'}"
            self.custom_callback(self, time_str)

    def update(self, force=False):
        self.draw.rectangle((0, 0, 128, 128), fill=self.black)
        
        # Draw title
        self.draw.text(
            (7, 5),
            "Enter Time:",
            font=self.fonts.base.font,
            fill=self.half_red,
        )
        
        self.draw_time_boxes()
        self.draw_legend()
        
        if self.shared_state:
            self.shared_state.set_screen(self.screen)
        return self.screen_update() 