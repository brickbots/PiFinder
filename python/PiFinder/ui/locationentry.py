from typing import Any, TYPE_CHECKING

from PIL import Image, ImageDraw

import PiFinder.ui.callbacks as callbacks
from PiFinder.ui.base import UIModule

if TYPE_CHECKING:

    def _(a) -> Any:
        return a


class UILocationEntry(UIModule):
    """Entry screen for latitude, longitude, or altitude.

    Three-step flow: lat → lon → alt.
    The 'coordinate' item_definition key controls the mode.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.coordinate = self.item_definition.get("coordinate", "lat")
        self._skip_callback = False
        self._confirmed = False
        self.custom_callback = self.item_definition.get("custom_callback")

        if self.coordinate == "lat":
            self.label = _("Enter Latitude")
            self.max_degrees = 90
            self.deg_digits = 2
            self.placeholders = [_("DD"), _("dd")]
            self.has_sign = True
            self.num_boxes = 2
        elif self.coordinate == "lon":
            self.label = _("Enter Longitude")
            self.max_degrees = 180
            self.deg_digits = 3
            self.placeholders = [_("DDD"), _("dd")]
            self.has_sign = True
            self.num_boxes = 2
        else:  # alt
            self.label = _("Altitude (m)")
            self.placeholders = [_("meters")]
            self.has_sign = False
            self.num_boxes = 1

        # Sign: + = N/E, - = S/W
        self.sign = "+"

        self.boxes = [""] * self.num_boxes
        self.current_box = 0

        # Pre-fill from shared state if available
        location = self.shared_state.location() if self.shared_state else None
        if location and location.lock:
            if self.coordinate == "lat":
                val = location.lat
                if val < 0:
                    self.sign = "-"
                    val = abs(val)
                self.boxes[0] = str(int(val))
                self.boxes[1] = f"{int(round((val - int(val)) * 100)):02d}"
            elif self.coordinate == "lon":
                val = location.lon
                if val < 0:
                    self.sign = "-"
                    val = abs(val)
                self.boxes[0] = str(int(val))
                self.boxes[1] = f"{int(round((val - int(val)) * 100)):02d}"
            else:  # alt
                self.boxes[0] = str(int(location.altitude))

        # Screen setup
        self.width = 128
        self.height = 128
        self.red = self.colors.get(255)
        self.black = self.colors.get(0)
        self.half_red = self.colors.get(128)
        self.screen = Image.new("RGB", (self.width, self.height), "black")
        self.draw = ImageDraw.Draw(self.screen)
        self.bold = self.fonts.bold

        # Layout
        self.text_y = 25
        self.box_height = 20
        self.box_spacing = 12
        if self.coordinate == "alt":
            self.box_widths = [50]
        elif self.coordinate == "lon":
            self.box_widths = [32, 28]
        else:
            self.box_widths = [28, 28]

    def _sign_label(self):
        if self.coordinate == "lat":
            return "N" if self.sign == "+" else "S"
        return "E" if self.sign == "+" else "W"

    def draw_boxes(self):
        total_width = sum(self.box_widths) + (self.num_boxes - 1) * self.box_spacing
        start_x = (self.width - total_width) // 2

        # Draw sign indicator for lat/lon
        if self.has_sign:
            sign_x = start_x - 14
            self.draw.text(
                (sign_x, self.text_y + 2),
                self._sign_label(),
                font=self.bold.font,
                fill=self.red,
            )

        x_pos = start_x
        for i in range(self.num_boxes):
            w = self.box_widths[i]
            outline_color = self.red if i == self.current_box else self.half_red
            outline_width = 2 if i == self.current_box else 1

            self.draw.rectangle(
                [x_pos, self.text_y, x_pos + w, self.text_y + self.box_height],
                outline=outline_color,
                width=outline_width,
            )

            text = self.boxes[i]
            if not text and i != self.current_box:
                text = self.placeholders[i]
                color = self.colors.get(180)
            else:
                color = self.red

            if self.coordinate == "alt":
                placeholder = "0000"
            else:
                placeholder = "0" * (self.deg_digits if i == 0 else 2)
            text_width = self.bold.font.getbbox(text if text else placeholder)[2]
            text_x = x_pos + (w - text_width) // 2
            text_y = self.text_y + 2

            self.draw.text((text_x, text_y), text, font=self.bold.font, fill=color)

            # Draw decimal point between lat/lon boxes
            if self.num_boxes == 2 and i == 0:
                dot_x = x_pos + w + self.box_spacing // 2 - 2
                self.draw.text(
                    (dot_x, self.text_y + 2),
                    ".",
                    font=self.bold.font,
                    fill=self.red,
                )

            # Draw cursor in current box if empty
            if i == self.current_box and not self.boxes[i]:
                self.draw.rectangle(
                    [
                        x_pos + 2,
                        self.text_y + 2,
                        x_pos + 10,
                        self.text_y + self.box_height - 2,
                    ],
                    fill=self.red,
                )

            x_pos += w + self.box_spacing

        # Draw unit suffix
        if self.coordinate == "alt":
            self.draw.text(
                (x_pos - self.box_spacing + 4, self.text_y + 2),
                "m",
                font=self.bold.font,
                fill=self.red,
            )
        else:
            self.draw.text(
                (x_pos - self.box_spacing + 4, self.text_y + 2),
                "\u00b0",
                font=self.bold.font,
                fill=self.red,
            )

    def draw_label(self):
        note_y = self.text_y + self.box_height + 10
        self.draw.text(
            (10, note_y),
            self.label,
            font=self.fonts.base.font,
            fill=self.red,
        )
        return note_y + 15

    def draw_separator(self, start_y):
        self.draw.line(
            [(10, start_y), (self.width - 10, start_y)], fill=self.half_red, width=1
        )
        return start_y + 5

    def draw_legend(self, start_y):
        legend_y = start_y
        legend_color = self.red

        self.draw.text(
            (10, legend_y),
            _("\uf054 Next/Done"),
            font=self.fonts.base.font,
            fill=legend_color,
        )
        legend_y += 12
        self.draw.text(
            (10, legend_y),
            _("\uf053 Cancel"),
            font=self.fonts.base.font,
            fill=legend_color,
        )
        legend_y += 12
        if self.coordinate == "lat":
            hint = _("\U000f0374 Delete  \U000f0415 N/S")
        elif self.coordinate == "lon":
            hint = _("\U000f0374 Delete  \U000f0415 E/W")
        else:
            hint = _("\U000f0374 Delete/Previous")
        self.draw.text(
            (10, legend_y),
            hint,
            font=self.fonts.base.font,
            fill=legend_color,
        )

    def validate_box(self, box_index, value):
        if not value:
            return True
        try:
            num = int(value)
            if self.coordinate == "alt":
                if len(value) > 5:
                    return False
                return 0 <= num <= 99999
            if box_index == 0:
                max_digits = self.deg_digits
                if len(value) > max_digits:
                    return False
                if len(value) == max_digits:
                    return 0 <= num <= self.max_degrees
                return True
            else:
                if len(value) > 2:
                    return False
                return 0 <= num <= 99
        except ValueError:
            return False

    def key_number(self, number):
        current = self.boxes[self.current_box]
        new_value = current + str(number)

        if self.coordinate == "alt":
            max_d = 5
        else:
            max_d = self.deg_digits if self.current_box == 0 else 2

        if len(new_value) > max_d:
            return

        if self.validate_box(self.current_box, new_value):
            self.boxes[self.current_box] = new_value
            if len(new_value) == max_d and self.current_box < self.num_boxes - 1:
                self.current_box += 1

    def key_minus(self):
        if self.boxes[self.current_box]:
            self.boxes[self.current_box] = self.boxes[self.current_box][:-1]
        elif self.num_boxes > 1:
            self.current_box = (self.current_box - 1) % self.num_boxes

    def key_plus(self):
        if self.has_sign:
            self.sign = "-" if self.sign == "+" else "+"

    def _parse_value(self):
        """Parse the current boxes into a numeric value."""
        if self.coordinate == "alt":
            return int(self.boxes[0]) if self.boxes[0] else 0
        deg = int(self.boxes[0]) if self.boxes[0] else 0
        dec = int(self.boxes[1]) if self.boxes[1] else 0
        val = deg + dec / 100.0
        if self.sign == "-":
            val = -val
        return val

    def _last_box(self):
        return self.num_boxes - 1

    def key_right(self):
        if all(self.boxes) and self.current_box == self._last_box():
            val = self._parse_value()
            if self.coordinate == "lat":
                self._skip_callback = True
                self.remove_from_stack()
                self.add_to_stack(
                    {
                        "name": _("Enter Coords"),
                        "class": UILocationEntry,
                        "coordinate": "lon",
                        "lat": val,
                        "custom_callback": callbacks.set_location,
                    }
                )
            elif self.coordinate == "lon":
                self._skip_callback = True
                self.remove_from_stack()
                self.add_to_stack(
                    {
                        "name": _("Enter Coords"),
                        "class": UILocationEntry,
                        "coordinate": "alt",
                        "lat": self.item_definition.get("lat", 0.0),
                        "lon": val,
                        "custom_callback": callbacks.set_location,
                    }
                )
            else:  # alt
                self.item_definition["alt"] = val
                self._confirmed = True
                self.remove_from_stack()
            return False
        if self.current_box < self.num_boxes - 1:
            self.current_box += 1
        return False

    def key_left(self) -> bool:
        if self.current_box > 0:
            self.current_box -= 1
            return False
        self._skip_callback = True
        self.message(_("Cancelled"), 1)
        return True

    def inactive(self):
        if not self._confirmed or self._skip_callback:
            return
        if self.coordinate == "alt" and self.custom_callback:
            self.custom_callback(self)

    def update(self, force=False):
        self.draw.rectangle((0, 0, 128, 128), fill=self.black)
        self.draw_boxes()
        note_y = self.draw_label()
        separator_y = self.draw_separator(note_y + 15)
        self.draw_legend(separator_y)

        if self.shared_state:
            self.shared_state.set_screen(self.screen)
        return self.screen_update()
