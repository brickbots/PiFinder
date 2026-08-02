from typing import Any, TYPE_CHECKING

from PIL import Image, ImageDraw

from PiFinder.ui.base import UIModule
from PiFinder.ui.layout import center_box_row

if TYPE_CHECKING:

    def _(a) -> Any:
        return a


class UIDateEntry(UIModule):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.callback = self.item_definition.get("callback")
        self.custom_callback = self.item_definition.get("custom_callback")
        self._confirmed = False

        # Initialize three boxes for year, month, day - pre-filled from shared state
        self.boxes = ["", "", ""]
        self.current_box = 0
        self.placeholders = [
            _("yyyy"),
            _("mm"),
            _("dd"),
        ]  # TRANSLATORS: Place holders for year, month, day in date entry
        self.max_digits = [4, 2, 2]

        # Pre-fill from best-known date
        local_dt = self.shared_state.local_datetime() if self.shared_state else None
        if local_dt is not None:
            self.boxes[0] = str(local_dt.year)
            self.boxes[1] = f"{local_dt.month:02d}"
            self.boxes[2] = f"{local_dt.day:02d}"

        # Screen setup
        self.width = self.display_class.resX
        self.height = self.display_class.resY
        self.red = self.colors.get(255)
        self.black = self.colors.get(0)
        self.half_red = self.colors.get(128)
        self.screen = Image.new("RGB", (self.width, self.height), "black")
        self.draw = ImageDraw.Draw(self.screen)
        self.bold = self.fonts.bold

        # Layout constants - box widths derive from the bold font so the
        # YYYY-MM-DD boxes scale with the display (38 / 25 / 20 on the 128 panel).
        self.text_y = self.display_class.titlebar_height + 8
        self.year_box_width = self.bold.width * 4 + 10
        self.md_box_width = self.bold.width * 2 + 11
        self.box_height = self.bold.height + 7
        self.box_spacing = round(self.display_class.resX * 10 / 128)

        # Center year + month + day boxes on the actual screen width
        box_row = center_box_row(
            self.display_class,
            [self.year_box_width, self.md_box_width, self.md_box_width],
            self.box_spacing,
            self.text_y,
            self.box_height,
        )
        self.box_xs = box_row.xs
        self.start_x = box_row.xs[0]

    def _box_x(self, i):
        """Get the x position for box i."""
        return self.box_xs[i]

    def _box_width(self, i):
        """Get the width for box i."""
        return self.year_box_width if i == 0 else self.md_box_width

    def draw_date_boxes(self):
        for i in range(3):
            x = self._box_x(i)
            w = self._box_width(i)

            outline_color = self.red if i == self.current_box else self.half_red
            outline_width = 2 if i == self.current_box else 1

            self.draw.rectangle(
                [x, self.text_y, x + w, self.text_y + self.box_height],
                outline=outline_color,
                width=outline_width,
            )

            text = self.boxes[i]
            if not text and i != self.current_box:
                text = self.placeholders[i]
                color = self.colors.get(180)
            else:
                color = self.red

            placeholder = "0" * self.max_digits[i]
            text_width = self.bold.font.getbbox(text if text else placeholder)[2]
            text_x = x + (w - text_width) // 2
            text_y = self.text_y + 2

            self.draw.text((text_x, text_y), text, font=self.bold.font, fill=color)

            # Draw dash separator after first two boxes
            if i < 2:
                next_x = self._box_x(i + 1)
                dash_x = x + w + (next_x - x - w) // 2 - 2
                self.draw.text(
                    (dash_x, self.text_y + 2), "-", font=self.bold.font, fill=self.red
                )

        # Draw cursor in current box if empty
        if not self.boxes[self.current_box]:
            x = self._box_x(self.current_box)
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

    def _location_locked(self) -> bool:
        """True when a location fix exists, so the date has a real local zone.

        ``set_datetime`` localises the entered date+time in the observer's zone,
        which we only derive from a location fix. This screen is reached only
        through the (equally gated) time screen today, but it self-gates on the
        same precondition so it stays correct if it is ever surfaced directly
        (see ADR 0019). The check is live, mirroring UITimeEntry.
        """
        return bool(self.shared_state and self.shared_state.location().lock)

    def draw_local_date_note(self):
        note_y = self.text_y + self.box_height + 10
        self.draw.text(
            (10, note_y),
            _("Enter Local Date"),
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
            _("\uf054 Done"),
            font=self.fonts.base.font,
            fill=legend_color,
        )
        legend_y += self.fonts.base.height + 1
        self.draw.text(
            (10, legend_y),
            _("\uf053 Cancel"),
            font=self.fonts.base.font,
            fill=legend_color,
        )
        legend_y += self.fonts.base.height + 1
        self.draw.text(
            (10, legend_y),
            _("\U000f0374 Delete/Previous"),
            font=self.fonts.base.font,
            fill=legend_color,
        )

    def validate_box(self, box_index, value):
        """Validate the entered value for the given box."""
        if not value:
            return True
        try:
            num = int(value)
            if box_index == 0:  # Year
                # Allow partial entry (e.g. "2", "20", "202") and full 2020-2099
                if len(value) < 4:
                    return True
                return 2020 <= num <= 2099
            elif box_index == 1:  # Month
                return 1 <= num <= 12
            else:  # Day
                return 1 <= num <= 31
        except ValueError:
            return False

    def key_number(self, number):
        if not self._location_locked():
            return  # gated: no location fix, so ignore digit entry
        current = self.boxes[self.current_box]
        new_value = current + str(number)

        max_d = self.max_digits[self.current_box]
        if len(new_value) > max_d:
            return

        if self.validate_box(self.current_box, new_value):
            self.boxes[self.current_box] = new_value
            if len(new_value) == max_d and self.current_box < 2:
                self.current_box += 1

    def key_minus(self):
        """Delete last digit in current box or move to previous box if empty."""
        if not self._location_locked():
            return  # gated: nothing to edit until a location fix exists
        if self.boxes[self.current_box]:
            self.boxes[self.current_box] = self.boxes[self.current_box][:-1]
        else:
            self.current_box = (self.current_box - 1) % 3

    def key_right(self):
        """Confirm if all boxes filled, otherwise cycle to next box."""
        if not self._location_locked():
            return False  # gated: don't confirm the date
        if all(self.boxes) and self.current_box == 2:
            self._confirmed = True
            self.remove_from_stack()
            return False
        if self.current_box < 2:
            self.current_box += 1
        return False

    def key_left(self) -> bool:
        if self.current_box > 0:
            self.current_box -= 1
            return False
        self.message(_("Cancelled"), 1)
        return True

    def inactive(self):
        """Called when the module is no longer active."""
        if not self._location_locked():
            return  # gated: never fire set_datetime against a bogus (UTC) zone
        if self._confirmed and self.custom_callback:
            date_str = f"{self.boxes[0]}-{self.boxes[1]}-{self.boxes[2]}"
            self.custom_callback(self, date_str)

    def update(self, force=False):
        if not self._location_locked():
            # Self-gate on a location fix, mirroring UITimeEntry (see ADR 0019).
            self.draw_gate_message(_("Set location\nfirst"))
        else:
            self.draw.rectangle((0, 0, self.width, self.height), fill=self.black)
            self.draw_date_boxes()
            note_y = self.draw_local_date_note()
            separator_y = self.draw_separator(note_y + 15)
            self.draw_legend(separator_y)

        if self.shared_state:
            self.shared_state.set_screen(self.screen)
        return self.screen_update()
