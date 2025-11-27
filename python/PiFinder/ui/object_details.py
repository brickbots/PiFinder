#!/usr/bin/python
# -*- coding:utf-8 -*-
# mypy: ignore-errors
"""
This module contains all the UI code for the object details screen

"""

from PiFinder.object_images import get_display_image
from PiFinder.object_images.image_base import ImageType
from PiFinder.object_images.star_catalog import CatalogState
from PiFinder.ui.marking_menus import MarkingMenuOption, MarkingMenu
from PiFinder.obj_types import OBJ_TYPES
from PiFinder.ui.align import align_on_radec
from PiFinder.ui.base import UIModule
from PiFinder.ui.log import UILog
from PiFinder.ui.ui_utils import (
    TextLayouterScroll,
    TextLayouter,
    TextLayouterSimple,
    SpaceCalculatorFixed,
    name_deduplicate,
)
from PiFinder import calc_utils
import functools

from PiFinder.db.observations_db import ObservationsDatabase
from PIL import Image, ImageDraw, ImageChops
import logging
import numpy as np
import time

logger = logging.getLogger("PiFinder.UIObjectDetails")

# Constants for display modes
DM_DESC = 0  # Display mode for description
DM_LOCATE = 1  # Display mode for LOCATE
DM_IMAGE = 2  # Display mode for images (POSS or Gaia chart)


class EyepieceInput:
    """
    Handles custom eyepiece focal length input (1-99mm)
    """

    def __init__(self):
        self.focal_length_mm = 0
        self.digits = []
        self.last_input_time = 0

    def append_digit(self, digit: int) -> bool:
        """
        Append a digit to the input.
        Returns True if input is complete (2 digits or auto-timeout)
        """
        import time

        self.digits.append(digit)
        self.last_input_time = time.time()

        # Update focal length
        if len(self.digits) == 1:
            self.focal_length_mm = digit
        else:
            self.focal_length_mm = self.digits[0] * 10 + self.digits[1]

        # Auto-complete after 2 digits
        return len(self.digits) >= 2

    def is_complete(self) -> bool:
        """Check if input has timed out (1.5 seconds)"""
        import time
        if len(self.digits) == 0:
            return False
        if len(self.digits) >= 2:
            return True
        return time.time() - self.last_input_time > 1.5

    def reset(self):
        """Clear the input"""
        self.digits = []
        self.focal_length_mm = 0
        self.last_input_time = 0

    def has_input(self) -> bool:
        """Check if any digits have been entered"""
        return len(self.digits) > 0

    def __str__(self):
        """Return display string for popup"""
        if len(self.digits) == 0:
            return "__"
        elif len(self.digits) == 1:
            return f"{self.digits[0]}_"
        else:
            return f"{self.digits[0]}{self.digits[1]}"


class UIObjectDetails(UIModule):
    """
    Shows details about an object
    """

    __help_name__ = "object_details"
    __title__ = "OBJECT"
    __ACTIVATION_TIMEOUT = 10

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.screen_direction = self.config_object.get_option("screen_direction")
        self.mount_type = self.config_object.get_option("mount_type")
        self._chart_gen = None  # Cached chart generator instance
        self.object = self.item_definition["object"]
        self.object_list = self.item_definition["object_list"]
        self.object_display_mode = DM_LOCATE
        self.object_image = None
        self._chart_generator = None  # Active generator for progressive chart updates
        self._is_showing_loading_chart = False  # Track if showing "Loading..." for deep chart
        self._force_gaia_chart = False  # Toggle: force deep chart even if POSS image exists
        self.eyepiece_input = EyepieceInput()  # Custom eyepiece input handler
        self.eyepiece_input_display = False  # Show eyepiece input popup
        self._custom_eyepiece = None  # Reference to custom eyepiece object in equipment list (None = not active)

        # Default Marking Menu
        self._default_marking_menu = MarkingMenu(
            left=MarkingMenuOption(),
            right=MarkingMenuOption(),
            down=MarkingMenuOption(
                label=_("ALIGN"),
                callback=MarkingMenu(
                    up=MarkingMenuOption(),
                    left=MarkingMenuOption(label=_("CANCEL"), callback=self.mm_cancel),
                    down=MarkingMenuOption(),
                    right=MarkingMenuOption(label=_("ALIGN"), callback=self.mm_align),
                ),
            ),
        )

        # Deep Chart Marking Menu - Settings access
        self._gaia_chart_marking_menu = MarkingMenu(
            up=MarkingMenuOption(label=_("SETTINGS"), menu_jump="obj_chart_settings"),
            right=MarkingMenuOption(label=_("CROSS"), menu_jump="obj_chart_crosshair"),
            down=MarkingMenuOption(label=_("STYLE"), menu_jump="obj_chart_style"),
            left=MarkingMenuOption(label=_("LM"), menu_jump="obj_chart_lm"),
        )

        # Used for displaying obsevation counts
        self.observations_db = ObservationsDatabase()

        self.simpleTextLayout = functools.partial(
            TextLayouterSimple,
            draw=self.draw,
            color=self.colors.get(255),
            font=self.fonts.base,
        )
        self.descTextLayout: TextLayouter = TextLayouter(
            "",
            draw=self.draw,
            color=self.colors.get(255),
            colors=self.colors,
            font=self.fonts.base,
        )
        self.ScrollTextLayout = functools.partial(
            TextLayouterScroll,
            draw=self.draw,
            color=self.colors.get(255),
            font=self.fonts.base,
        )
        self.space_calculator = SpaceCalculatorFixed(18)
        self.texts = {
            "type-const": self.simpleTextLayout(
                _("No Object Found"),
                font=self.fonts.bold,
                color=self.colors.get(255),
            ),
        }

        # cache some display stuff for locate
        self.az_anchor = (0, self.display_class.resY - (self.fonts.huge.height * 2.2))
        self.alt_anchor = (0, self.display_class.resY - (self.fonts.huge.height * 1.2))
        self._elipsis_count = 0

        self.active()  # fill in activation time
        self.update_object_info()

    @property
    def marking_menu(self):
        """
        Return appropriate marking menu based on current view mode
        """
        if self._is_gaia_chart:
            return self._gaia_chart_marking_menu
        return self._default_marking_menu

    def _layout_designator(self):
        """
        Generates designator layout object
        If there is a selected object which
        is in the catalog, but not in the filtered
        catalog, dim the designator out
        """
        designator_color = 255
        if not self.object.last_filtered_result:
            designator_color = 128
        return self.simpleTextLayout(
            self.object.display_name,
            font=self.fonts.large,
            color=self.colors.get(designator_color),
        )

    def refresh_designator(self):
        self.texts["designator"] = self._layout_designator()

    def _get_scrollspeed_config(self):
        scroll_dict = {
            "Off": 0,
            "Fast": TextLayouterScroll.FAST,
            "Med": TextLayouterScroll.MEDIUM,
            "Slow": TextLayouterScroll.SLOW,
        }
        scrollspeed = self.config_object.get_option("text_scroll_speed", "Med")
        return scroll_dict[scrollspeed]

    def update_config(self):
        if self.texts.get("aka"):
            self.texts["aka"].set_scrollspeed(self._get_scrollspeed_config())

    def update_object_info(self):
        """
        Generates object text and loads object images
        """
        # logger.info(f">>> update_object_info() called for {self.object.display_name if self.object else 'None'}")

        # CRITICAL: Clear loading flag at START to prevent recursive update() calls
        # during generator consumption. If we don't do this, calling self.update()
        # while consuming yields will trigger update() -> update_object_info() recursion.
        self._is_showing_loading_chart = False

        # Title...
        self.title = self.object.display_name

        # text stuff....

        self.texts = {}
        # Type / Constellation
        object_type = OBJ_TYPES.get(self.object.obj_type, self.object.obj_type)

        # layout the type - constellation line
        discarded, typeconst = self.space_calculator.calculate_spaces(  # noqa: F841
            object_type, self.object.const
        )
        self.texts["type-const"] = self.simpleTextLayout(
            _(typeconst),
            font=self.fonts.bold,
            color=self.colors.get(255),
        )
        # Magnitude / Size
        # try to get object mag to float
        obj_mag = self.object.mag_str

        size = str(self.object.size).strip()
        size = "-" if size == "" else size
        # Only construct mag/size if at least one is present
        magsize = ""
        if size != "-" or obj_mag != "-":
            spaces, magsize = self.space_calculator.calculate_spaces(
                _("Mag:{obj_mag}").format(
                    obj_mag=obj_mag
                ),  # TRANSLATORS: object info magnitude
                _("Sz:{size}").format(size=size),  # TRANSLATORS: object info size
            )
            if spaces == -1:
                spaces, magsize = self.space_calculator.calculate_spaces(
                    _("Mag:{obj_mag}").format(obj_mag=obj_mag), size
                )
            if spaces == -1:
                spaces, magsize = self.space_calculator.calculate_spaces(obj_mag, size)

        self.texts["magsize"] = self.simpleTextLayout(
            magsize, font=self.fonts.bold, color=self.colors.get(255)
        )

        if self.object.names:
            # first deduplicate the aka's
            dedups = name_deduplicate(self.object.names, [self.object.display_name])
            self.texts["aka"] = self.ScrollTextLayout(
                ", ".join(dedups),
                font=self.fonts.base,
                scrollspeed=self._get_scrollspeed_config(),
            )

        # NGC description....
        logs = self.observations_db.get_logs_for_object(self.object)
        desc = ""
        if self.object.description:
            desc = (
                self.object.description.replace("\t", " ") + "\n"
            )  # I18N: Descriptions are not translated
        if len(logs) == 0:
            desc = desc + _("  Not Logged")
        else:
            desc = desc + _("  {logs} Logs").format(logs=len(logs))

        self.descTextLayout.set_text(desc)
        self.texts["desc"] = self.descTextLayout

        solution = self.shared_state.solution()
        roll = 0
        if solution:
            roll = solution["Roll"]

        # Calculate magnification and TFOV using current active eyepiece (custom or configured)
        magnification = self.config_object.equipment.calc_magnification()
        tfov = self.config_object.equipment.calc_tfov()
        eyepiece_text = str(self.config_object.equipment.active_eyepiece)

        if self._custom_eyepiece is not None:
            logger.info(f">>> Using custom eyepiece: {eyepiece_text}, tfov={tfov}, mag={magnification}")
        else:
            logger.info(f">>> Using configured eyepiece: {eyepiece_text}, tfov={tfov}, mag={magnification}")

        prev_object_image = self.object_image

        # Get or create chart generator (owned by UI layer)
        logger.info(">>> Getting chart generator...")
        chart_gen = self._get_gaia_chart_generator()
        logger.info(f">>> Chart generator obtained, state: {chart_gen.get_catalog_state() if chart_gen else 'None'}")

        logger.info(f">>> Calling get_display_image with force_gaia_chart={self._force_gaia_chart}")

        # get_display_image returns either an image directly (POSS) or a generator (deep chart)
        result = get_display_image(
            self.object,
            eyepiece_text,
            tfov,
            roll,
            self.display_class,
            burn_in=self.object_display_mode == DM_IMAGE,
            magnification=magnification,
            config_object=self.config_object,
            shared_state=self.shared_state,
            chart_generator=chart_gen,  # Pass our chart generator to object_images
            force_chart=self._force_gaia_chart,  # Toggle state
        )

        # Check if it's a generator (progressive deep chart) or direct image (POSS)
        if hasattr(result, '__iter__') and hasattr(result, '__next__'):
            # It's a generator - store it for progressive consumption by update()
            logger.info(">>> get_display_image returned GENERATOR, storing for progressive updates...")
            self._chart_generator = result
            self.object_image = None  # Will be set by first yield
        else:
            # Direct image (POSS)
            logger.info(f">>> get_display_image returned direct image: {type(result)}")
            self._chart_generator = None
            self.object_image = result

        logger.info(f">>> update_object_info() complete, self.object_image is now: {type(self.object_image)}")

        # Track if we're showing a "Loading..." placeholder for chart
        self._is_showing_loading_chart = (
            self.object_image is not None
            and hasattr(self.object_image, 'image_type')
            and self.object_image.image_type == ImageType.LOADING
        )


    @property
    def _is_gaia_chart(self):
        """Check if currently displaying a Gaia chart"""
        return (
            self.object_image is not None
            and hasattr(self.object_image, 'image_type')
            and self.object_image.image_type == ImageType.GAIA_CHART
        )

    def active(self):
        self.activation_time = time.time()
        # Regenerate object info when returning to this screen
        # This ensures config changes (like LM) are applied
        self.update_object_info()

    def _check_catalog_initialized(self):
        code = self.object.catalog_code
        if code in ["PUSH", "USER"]:
            # Special codes for objects pushed from sky-safari or created by user
            return True
        catalog = self.catalogs.get_catalog_by_code(code)
        return catalog and catalog.initialized

    def _get_pulse_factor(self):
        """
        Calculate current pulse factor for animations
        Returns tuple: (pulse_factor, size_multiplier, color_intensity)
        - pulse_factor: 0.0 to 1.0 sine wave
        - size_multiplier: factor to multiply sizes by (0.6 to 1.0 for smoother animation)
        - color_intensity: brightness value (48 to 128 for more visible change)
        """
        import time
        import numpy as np

        # Get pulse period from config (default 2.0 seconds)
        pulse_period = float(self.config_object.get_option("obj_chart_crosshair_speed", "2.0"))

        t = time.time() % pulse_period
        # Sine wave for smooth pulsation (0.0 to 1.0 range)
        pulse_factor = 0.5 + 0.5 * np.sin(2 * np.pi * t / pulse_period)

        # Size multiplier: 0.6 to 1.0 (smaller range, smoother looking)
        size_multiplier = 0.6 + 0.4 * pulse_factor

        # Color intensity: 48 to 128 (brighter and more visible)
        color_intensity = int(48 + 80 * pulse_factor)

        return pulse_factor, size_multiplier, color_intensity

    def _get_fade_factor(self):
        """
        Calculate current fade factor for animations
        Returns color_intensity that fades from 0 to 128
        - Crosshair stays at minimum size
        - Only brightness changes
        """
        import time
        import numpy as np

        # Get fade period from config (default 2.0 seconds)
        fade_period = float(self.config_object.get_option("obj_chart_crosshair_speed", "2.0"))

        t = time.time() % fade_period
        # Sine wave for smooth fading (0.0 to 1.0 range)
        fade_factor = 0.5 + 0.5 * np.sin(2 * np.pi * t / fade_period)

        # Color intensity: 0 to 128 (fade from invisible to half brightness)
        # Use round instead of int for better distribution
        color_intensity = round(128 * fade_factor)

        return color_intensity

    def _draw_crosshair_simple(self, mode="off"):
        """
        Draw simple crosshair with 4 lines and center gap using inverted pixels

        Args:
            mode: Animation mode - "off", "pulse", or "fade" (fade not supported for inverted pixels)
        """
        import numpy as np

        width, height = self.display_class.resolution
        cx, cy = int(width / 2.0), int(height / 2.0)

        if mode == "pulse":
            pulse_factor, _, _ = self._get_pulse_factor()
            # Size pulsates from 7 down to 4 pixels (inverted - more steps)
            outer = int(7.0 - (3.0 * pulse_factor))  # 7.0 down to 4.0 (smooth animation)
        else:
            # Fixed size (fade mode not supported for inverted pixels)
            outer = 5

        inner = 3  # Fixed gap (slightly larger center hole)

        # Get screen buffer as numpy array for pixel manipulation
        pixels = np.array(self.screen)

        # Invert crosshair pixels (red channel only) for visibility
        # Horizontal lines (left and right of center)
        for x in range(max(0, cx - outer), max(0, cx - inner)):
            if 0 <= x < width and 0 <= cy < height:
                pixels[cy, x, 0] = 255 - pixels[cy, x, 0]
        for x in range(min(width, cx + inner), min(width, cx + outer)):
            if 0 <= x < width and 0 <= cy < height:
                pixels[cy, x, 0] = 255 - pixels[cy, x, 0]

        # Vertical lines (top and bottom of center)
        for y in range(max(0, cy - outer), max(0, cy - inner)):
            if 0 <= y < height and 0 <= cx < width:
                pixels[y, cx, 0] = 255 - pixels[y, cx, 0]
        for y in range(min(height, cy + inner), min(height, cy + outer)):
            if 0 <= y < height and 0 <= cx < width:
                pixels[y, cx, 0] = 255 - pixels[y, cx, 0]

        # Update screen buffer with inverted pixels
        self.screen = Image.fromarray(pixels, mode="RGB")
        # Re-create draw object since we replaced the image
        self.draw = ImageDraw.Draw(self.screen)

    def _draw_crosshair_circle(self, mode="off"):
        """
        Draw circle reticle

        Args:
            mode: Animation mode - "off", "pulse", or "fade"
        """
        width, height = self.display_class.resolution
        cx, cy = width / 2.0, height / 2.0

        if mode == "pulse":
            pulse_factor, _, color_intensity = self._get_pulse_factor()
            radius = 8.0 - (4.0 * pulse_factor)  # 8.0 down to 4.0 (smooth animation)
        elif mode == "fade":
            color_intensity = self._get_fade_factor()
            radius = 4  # Fixed minimum size
        else:
            color_intensity = 64
            radius = 4  # Smaller fixed size

        # Create a separate layer for the crosshair
        crosshair_layer = Image.new("RGB", (width, height), (0, 0, 0))
        crosshair_draw = ImageDraw.Draw(crosshair_layer)

        # Draw circle on the layer
        marker_color = (color_intensity, 0, 0)
        bbox = [cx - radius, cy - radius, cx + radius, cy + radius]
        crosshair_draw.ellipse(bbox, outline=marker_color, width=1)

        # Use lighten blend: take the lighter of the two values for each pixel
        self.screen = ImageChops.lighter(self.screen, crosshair_layer)
        self.draw = ImageDraw.Draw(self.screen)

    def _draw_crosshair_bullseye(self, mode="off"):
        """
        Draw concentric circles (bullseye)

        Args:
            mode: Animation mode - "off", "pulse", or "fade"
        """
        width, height = self.display_class.resolution
        cx, cy = width / 2.0, height / 2.0

        if mode == "pulse":
            pulse_factor, _, color_intensity = self._get_pulse_factor()
            # Pulsate from larger to smaller (smooth animation)
            radii = [4.0 - (2.0 * pulse_factor), 8.0 - (4.0 * pulse_factor), 12.0 - (6.0 * pulse_factor)]  # 4→2, 8→4, 12→6
        elif mode == "fade":
            color_intensity = self._get_fade_factor()
            radii = [2, 4, 6]  # Fixed minimum radii
        else:
            color_intensity = 64
            radii = [2, 4, 6]  # Smaller fixed radii

        # Create a separate layer for the crosshair
        crosshair_layer = Image.new("RGB", (width, height), (0, 0, 0))
        crosshair_draw = ImageDraw.Draw(crosshair_layer)

        # Draw concentric circles on the layer
        marker_color = (color_intensity, 0, 0)
        for radius in radii:
            bbox = [cx - radius, cy - radius, cx + radius, cy + radius]
            crosshair_draw.ellipse(bbox, outline=marker_color, width=1)

        # Use lighten blend
        self.screen = ImageChops.lighter(self.screen, crosshair_layer)
        self.draw = ImageDraw.Draw(self.screen)

    def _draw_crosshair_brackets(self, mode="off"):
        """
        Draw corner brackets (frame corners)

        Args:
            mode: Animation mode - "off", "pulse", or "fade"
        """
        width, height = self.display_class.resolution
        cx, cy = int(width / 2.0), int(height / 2.0)

        if mode == "pulse":
            pulse_factor, _, color_intensity = self._get_pulse_factor()
            size = int(8.0 - (4.0 * pulse_factor))  # 8.0 down to 4.0 (smooth animation)
            length = int(5.0 - (2.0 * pulse_factor))  # 5.0 down to 3.0 (smooth animation)
        elif mode == "fade":
            color_intensity = self._get_fade_factor()
            size = 4  # Fixed minimum size
            length = 3  # Fixed minimum length
        else:
            color_intensity = 64
            size = 4  # Smaller distance from center to bracket corner
            length = 3  # Shorter bracket arms

        # Create a separate layer for the crosshair
        crosshair_layer = Image.new("RGB", (width, height), (0, 0, 0))
        crosshair_draw = ImageDraw.Draw(crosshair_layer)

        marker_color = (color_intensity, 0, 0)

        # Draw brackets on the layer
        # Top-left bracket
        crosshair_draw.line([cx - size, cy - size, cx - size + length, cy - size], fill=marker_color, width=1)
        crosshair_draw.line([cx - size, cy - size, cx - size, cy - size + length], fill=marker_color, width=1)

        # Top-right bracket
        crosshair_draw.line([cx + size - length, cy - size, cx + size, cy - size], fill=marker_color, width=1)
        crosshair_draw.line([cx + size, cy - size, cx + size, cy - size + length], fill=marker_color, width=1)

        # Bottom-left bracket
        crosshair_draw.line([cx - size, cy + size, cx - size + length, cy + size], fill=marker_color, width=1)
        crosshair_draw.line([cx - size, cy + size - length, cx - size, cy + size], fill=marker_color, width=1)

        # Bottom-right bracket
        crosshair_draw.line([cx + size - length, cy + size, cx + size, cy + size], fill=marker_color, width=1)
        crosshair_draw.line([cx + size, cy + size - length, cx + size, cy + size], fill=marker_color, width=1)

        # Use lighten blend
        self.screen = ImageChops.lighter(self.screen, crosshair_layer)
        self.draw = ImageDraw.Draw(self.screen)

    def _draw_crosshair_dots(self, mode="off"):
        """
        Draw four corner dots

        Args:
            mode: Animation mode - "off", "pulse", or "fade"
        """
        width, height = self.display_class.resolution
        cx, cy = width / 2.0, height / 2.0

        if mode == "pulse":
            pulse_factor, _, color_intensity = self._get_pulse_factor()
            distance = 8.0 - (4.0 * pulse_factor)  # 8 down to 4 (smooth animation)
            dot_size = 3.0 - (1.5 * pulse_factor)  # 3 down to 1 (smooth animation)
        elif mode == "fade":
            color_intensity = self._get_fade_factor()
            distance = 4  # Fixed minimum distance
            dot_size = 1  # Fixed minimum size
        else:
            color_intensity = 64
            distance = 4  # Smaller distance from center to dots
            dot_size = 1  # Smaller dot radius

        # Create a separate layer for the crosshair
        crosshair_layer = Image.new("RGB", (width, height), (0, 0, 0))
        crosshair_draw = ImageDraw.Draw(crosshair_layer)

        marker_color = (color_intensity, 0, 0)

        # Four corner dots
        positions = [
            (cx - distance, cy - distance),  # Top-left
            (cx + distance, cy - distance),  # Top-right
            (cx - distance, cy + distance),  # Bottom-left
            (cx + distance, cy + distance),  # Bottom-right
        ]

        for x, y in positions:
            bbox = [x - dot_size, y - dot_size, x + dot_size, y + dot_size]
            crosshair_draw.ellipse(bbox, fill=marker_color)

        # Use lighten blend
        self.screen = ImageChops.lighter(self.screen, crosshair_layer)
        self.draw = ImageDraw.Draw(self.screen)

    def _draw_crosshair_cross(self, mode="off"):
        """
        Draw full cross (lines extend across entire screen)

        Args:
            mode: Animation mode - "off", "pulse", or "fade"
        """
        width, height = self.display_class.resolution
        cx, cy = width / 2.0, height / 2.0

        if mode == "pulse":
            pulse_factor, _, color_intensity = self._get_pulse_factor()
        elif mode == "fade":
            color_intensity = self._get_fade_factor()
        else:
            color_intensity = 64

        # Create a separate layer for the crosshair
        crosshair_layer = Image.new("RGB", (width, height), (0, 0, 0))
        crosshair_draw = ImageDraw.Draw(crosshair_layer)

        marker_color = (color_intensity, 0, 0)

        # Horizontal line
        crosshair_draw.line([0, cy, width, cy], fill=marker_color, width=1)
        # Vertical line
        crosshair_draw.line([cx, 0, cx, height], fill=marker_color, width=1)

        # Use lighten blend
        self.screen = ImageChops.lighter(self.screen, crosshair_layer)
        self.draw = ImageDraw.Draw(self.screen)

    def _draw_fov_circle(self):
        """
        Draw FOV circle to show eyepiece field of view boundary
        Matches the POSS view circular crop
        """
        width, height = self.display_class.resolution
        cx, cy = width / 2.0, height / 2.0

        # Use slightly smaller than screen to show the boundary
        # Screen is typically 128x128, so use radius that fits within screen
        radius = min(width, height) / 2.0 - 2  # Leave 2 pixel margin

        # Draw subtle circle
        marker_color = self.colors.get(32)  # Very dim, just to show boundary
        bbox = [cx - radius, cy - radius, cx + radius, cy + radius]
        self.draw.ellipse(bbox, outline=marker_color, width=1)

    def _render_pointing_instructions(self):
        # Pointing Instructions
        if self.shared_state.solution() is None:
            self.draw.text(
                (10, 70),
                _("No solve"),  # TRANSLATORS: No solve yet... (Part 1/2)
                font=self.fonts.large.font,
                fill=self.colors.get(255),
            )
            self.draw.text(
                (10, 90),
                _("yet{elipsis}").format(
                    elipsis="." * int(self._elipsis_count / 10)
                ),  # TRANSLATORS: No solve yet... (Part 2/2)
                font=self.fonts.large.font,
                fill=self.colors.get(255),
            )
            self._elipsis_count += 1
            if self._elipsis_count > 39:
                self._elipsis_count = 0
            return

        if not self.shared_state.altaz_ready():
            self.draw.text(
                (10, 70),
                _("Searching"),  # TRANSLATORS: Searching for GPS (Part 1/2)
                font=self.fonts.large.font,
                fill=self.colors.get(255),
            )
            self.draw.text(
                (10, 90),
                _("for GPS{elipsis}").format(
                    elipsis="." * int(self._elipsis_count / 10)
                ),  # TRANSLATORS: Searching for GPS (Part 2/2)
                font=self.fonts.large.font,
                fill=self.colors.get(255),
            )
            self._elipsis_count += 1
            if self._elipsis_count > 39:
                self._elipsis_count = 0
            return

        if not self._check_catalog_initialized():
            self.draw.text(
                (10, 70),
                _("Calculating"),
                font=self.fonts.large.font,
                fill=self.colors.get(255),
            )
            self.draw.text(
                (10, 90),
                _(f"positions{'.' * int(self._elipsis_count / 10)}"),
                font=self.fonts.large.font,
                fill=self.colors.get(255),
            )
            self._elipsis_count += 1
            if self._elipsis_count > 39:
                self._elipsis_count = 0
            return

        indicator_color = 255 if self._unmoved else 128
        point_az, point_alt = calc_utils.aim_degrees(
            self.shared_state,
            self.mount_type,
            self.screen_direction,
            self.object,
        )

        # Check if aim_degrees returned valid values
        if point_az is None or point_alt is None:
            # No valid pointing data available
            self.draw.text(
                (10, 70),
                _("Calculating"),
                font=self.fonts.large.font,
                fill=self.colors.get(255),
            )
            self.draw.text(
                (10, 90),
                _(f"position{'.' * int(self._elipsis_count / 10)}"),
                font=self.fonts.large.font,
                fill=self.colors.get(255),
            )
            self._elipsis_count += 1
            if self._elipsis_count > 39:
                self._elipsis_count = 0
            return

        if point_az < 0:
            point_az *= -1
            az_arrow = self._LEFT_ARROW
        else:
            az_arrow = self._RIGHT_ARROW

        # Check az arrow config
        if self.config_object.get_option("pushto_az_arrows", "Default") == "Reverse":
            if az_arrow is self._LEFT_ARROW:
                az_arrow = self._RIGHT_ARROW
            else:
                az_arrow = self._LEFT_ARROW

        # Change decimal points when within 1 degree
        if point_az < 1:
            self.draw.text(
                self.az_anchor,
                f"{az_arrow}{point_az : >5.2f}",
                font=self.fonts.huge.font,
                fill=self.colors.get(indicator_color),
            )
        else:
            self.draw.text(
                self.az_anchor,
                f"{az_arrow}{point_az : >5.1f}",
                font=self.fonts.huge.font,
                fill=self.colors.get(indicator_color),
            )

        if point_alt < 0:
            point_alt *= -1
            alt_arrow = self._DOWN_ARROW
        else:
            alt_arrow = self._UP_ARROW

        # Change decimal points when within 1 degree
        if point_alt < 1:
            self.draw.text(
                self.alt_anchor,
                f"{alt_arrow}{point_alt : >5.2f}",
                font=self.fonts.huge.font,
                fill=self.colors.get(indicator_color),
            )
        else:
            self.draw.text(
                self.alt_anchor,
                f"{alt_arrow}{point_alt : >5.1f}",
                font=self.fonts.huge.font,
                fill=self.colors.get(indicator_color),
            )

    def _get_gaia_chart_generator(self):
        """Get the global chart generator singleton"""
        from PiFinder.object_images.gaia_chart import get_gaia_chart_generator
        import logging
        logger = logging.getLogger("ObjectDetails")

        chart_gen = get_gaia_chart_generator(self.config_object, self.shared_state)
        logger.info(f">>> _get_gaia_chart_generator returning: {chart_gen}")
        return chart_gen

    def _apply_custom_eyepiece(self):
        """Apply the custom eyepiece focal length and update display"""
        from PiFinder.equipment import Eyepiece

        # Capture the focal length before resetting
        focal_length = self.eyepiece_input.focal_length_mm

        # Reset input state FIRST to prevent recursion in update()
        self.eyepiece_input.reset()
        self.eyepiece_input_display = False

        # Apply the custom eyepiece
        if focal_length > 0:
            logger.info(f">>> Applying custom eyepiece: {focal_length}mm")

            # Remove old custom eyepiece if it exists
            if self._custom_eyepiece is not None and self._custom_eyepiece in self.config_object.equipment.eyepieces:
                logger.info(f">>> Removing old custom eyepiece: {self._custom_eyepiece}")
                self.config_object.equipment.eyepieces.remove(self._custom_eyepiece)

            # Create and add new custom eyepiece
            self._custom_eyepiece = Eyepiece(
                make="Custom",
                name=f"{focal_length}mm",
                focal_length_mm=focal_length,
                afov=50,  # Default AFOV for custom eyepiece
                field_stop=0
            )
            self.config_object.equipment.eyepieces.append(self._custom_eyepiece)
            self.config_object.equipment.active_eyepiece_index = len(self.config_object.equipment.eyepieces) - 1
            logger.info(f">>> Added custom eyepiece to equipment list: {self._custom_eyepiece}")

            self.update_object_info()
            self.update()
        else:
            logger.warning(f">>> Invalid focal length: {focal_length}mm, not applying")

    def update(self, force=True):
        import logging
        import time
        logger = logging.getLogger("ObjectDetails")

        # Check for eyepiece input timeout
        if self.eyepiece_input_display and self.eyepiece_input.is_complete():
            # Auto-complete the input
            self._apply_custom_eyepiece()

        # If we have a chart generator, consume one yield to get the next progressive update
        if hasattr(self, '_chart_generator') and self._chart_generator is not None:
            try:
                next_image = next(self._chart_generator)
                # logger.debug(f">>> update(): Consumed next chart yield: {type(next_image)}")
                self.object_image = next_image

                force = True  # Force screen update for progressive chart
            except StopIteration:
                logger.info(">>> update(): Chart generator exhausted")
                self._chart_generator = None  # Generator exhausted
        
        # Update loading flag based on current image
        if self.object_image is not None:
            self._is_showing_loading_chart = (
                hasattr(self.object_image, 'image_type')
                and self.object_image.image_type == ImageType.LOADING
            )

        # Check if we're showing "Loading..." for a deep chart
        # and if catalog is now ready, regenerate the image
        if self._is_showing_loading_chart:
            try:
                # Use cached chart generator to preserve catalog state
                chart_gen = self._get_gaia_chart_generator()
                state = chart_gen.get_catalog_state()
                # logger.debug(f">>> Update check: catalog state = {state}")

                if state == CatalogState.READY:
                    # Catalog ready! Regenerate display
                    # logger.info(">>> Catalog READY! Regenerating image...")
                    self._is_showing_loading_chart = False
                    self.update_object_info()
                    force = True  # Force screen update
            except Exception as e:
                logger.error(f">>> Update check failed: {e}", exc_info=True)
                pass
        # Clear Screen
        self.clear_screen()

        # paste image
        # paste image
        # logger.debug(f">>> update(): object_display_mode={self.object_display_mode}...")
        # logger.debug(f">>> update(): object_image type={type(self.object_image)}...")


        if self.object_display_mode == DM_IMAGE:
            # DEBUG: Check if image has any non-black pixels
            if self.object_image and self._force_gaia_chart:
                import numpy as np
                img_array = np.array(self.object_image)
                non_zero = np.count_nonzero(img_array)
                max_val = np.max(img_array)
                # logger.debug(f">>> CHART IMAGE DEBUG: non-zero pixels={non_zero}, max_value={max_val}, shape={img_array.shape}")

            self.screen.paste(self.object_image)
            # Recreate draw object to ensure it's in sync with screen after paste
            self.draw = ImageDraw.Draw(self.screen, mode="RGBA")
            # logger.debug(f">>> Image pasted to screen")

            # DEBUG: Save screen buffer to file for inspection
            # (Removed per user request)

            # If showing Gaia chart, draw crosshair based on config
            is_chart = (
                self.object_image is not None
                and hasattr(self.object_image, 'image_type')
                and self.object_image.image_type == ImageType.GAIA_CHART
            )
            if is_chart:
                crosshair_mode = self.config_object.get_option("obj_chart_crosshair")
                crosshair_style = self.config_object.get_option("obj_chart_crosshair_style")

                if crosshair_mode != "off":
                    # Call the appropriate drawing method based on style
                    style_methods = {
                        "simple": self._draw_crosshair_simple,
                        "circle": self._draw_crosshair_circle,
                        "bullseye": self._draw_crosshair_bullseye,
                        "brackets": self._draw_crosshair_brackets,
                        "dots": self._draw_crosshair_dots,
                        "cross": self._draw_crosshair_cross,
                    }

                    draw_method = style_methods.get(crosshair_style, self._draw_crosshair_simple)
                    draw_method(mode=crosshair_mode)

                    # Force continuous updates for animated crosshairs
                    if crosshair_mode in ["pulse", "fade"]:
                        force = True
        # Note: We do NOT create a new screen/draw here because text layouts
        # hold references to self.draw from __init__. The screen was already
        # cleared by self.clear_screen() at line 940.

        if self.object_display_mode == DM_DESC or self.object_display_mode == DM_LOCATE:
            # catalog and entry field i.e. NGC-311
            self.refresh_designator()
            desc_available_lines = 4
            desig = self.texts.get("designator")
            if desig:
                desig.draw((0, 20))

            # Object TYPE and Constellation i.e. 'Galaxy    PER'
            typeconst = self.texts.get("type-const")
            if typeconst:
                typeconst.draw((0, 36))

        if self.object_display_mode == DM_LOCATE:
            self._render_pointing_instructions()

        elif self.object_display_mode == DM_DESC:
            # Object Magnitude and size i.e. 'Mag:4.0   Sz:7"'
            magsize = self.texts.get("magsize")
            posy = 52
            if magsize and magsize.text.strip():
                if self.object:
                    # check for visibility and adjust mag/size text color
                    obj_altitude = calc_utils.calc_object_altitude(
                        self.shared_state, self.object
                    )

                    if obj_altitude:
                        if obj_altitude < 10:
                            # Not really visible
                            magsize.set_color = self.colors.get(128)
                magsize.draw((0, posy))
                posy += 17
            else:
                posy += 3
                desc_available_lines += 1  # extra lines for description

            # Common names for this object, i.e. M13 -> Hercules cluster
            aka = self.texts.get("aka")
            if aka and aka.text.strip():
                aka.draw((0, posy))
                posy += 11
            else:
                desc_available_lines += 1  # extra lines for description

            # Remaining lines with object description
            desc = self.texts.get("desc")
            if desc:
                desc.set_available_lines(desc_available_lines)
                desc.draw((0, posy))

        # Display eyepiece input popup if active
        if self.eyepiece_input_display:
            self.message(
                f"{str(self.eyepiece_input)}mm",
                0.1,
                [30, 10, 93, 40],
            )

        result = self.screen_update()
        return result

    def cycle_display_mode(self):
        """
        Cycle through available display modes
        for a module.  Invoked when the square
        key is pressed
        """
        self.object_display_mode = (
            self.object_display_mode + 1 if self.object_display_mode < 2 else 0
        )
        self.update_object_info()
        self.update()

    def maybe_add_to_recents(self):
        if self.activation_time < time.time() - self.__ACTIVATION_TIMEOUT:
            self.ui_state.add_recent(self.object)
            self.active()  # reset activation time

    def scroll_object(self, direction: int) -> None:
        if isinstance(self.object_list, np.ndarray):
            # For NumPy array
            current_index = np.where(self.object_list == self.object)[0][0]
        else:
            # For regular Python list
            current_index = self.object_list.index(self.object)
        current_index += direction
        if current_index < 0:
            current_index = 0
        if current_index >= len(self.object_list):
            current_index = len(self.object_list) - 1

        self.object = self.object_list[current_index]
        self.update_object_info()
        self.update()

    def mm_cancel(self, _marking_menu, _menu_item) -> bool:
        """
        Do nothing....
        """
        return True

    def mm_toggle_crosshair(self, _marking_menu, _menu_item) -> bool:
        """
        Cycle through crosshair modes: off -> on -> pulse -> off
        """
        current_mode = self.config_object.get_option("obj_chart_crosshair")
        modes = ["off", "on", "pulse"]
        current_index = modes.index(current_mode) if current_mode in modes else 0
        next_index = (current_index + 1) % len(modes)
        self.config_object.set_option("obj_chart_crosshair", modes[next_index])
        return False  # Don't exit, just update

    def mm_cycle_style(self, _marking_menu, _menu_item) -> bool:
        """
        Cycle through crosshair styles
        """
        current_style = self.config_object.get_option("obj_chart_crosshair_style")
        styles = ["simple", "circle", "bullseye", "brackets", "dots", "cross"]
        current_index = styles.index(current_style) if current_style in styles else 0
        next_index = (current_index + 1) % len(styles)
        self.config_object.set_option("obj_chart_crosshair_style", styles[next_index])
        return False  # Don't exit, just update

    def mm_toggle_lm_mode(self, _marking_menu, _menu_item) -> bool:
        """
        Toggle between auto and fixed LM mode
        """
        current_mode = self.config_object.get_option("obj_chart_lm_mode")
        new_mode = "fixed" if current_mode == "auto" else "auto"
        self.config_object.set_option("obj_chart_lm_mode", new_mode)
        # If switching to auto, regenerate the chart with new calculation
        if new_mode == "auto":
            self.update_object_info()
        return False  # Don't exit, just update

    def mm_align(self, _marking_menu, _menu_item) -> bool:
        """
        Called from marking menu to align on curent object
        """
        self.message(_("Aligning..."), 0.1)
        if align_on_radec(
            self.object.ra,
            self.object.dec,
            self.command_queues,
            self.config_object,
            self.shared_state,
        ):
            self.message(_("Aligned!"), 1)
        else:
            self.message(_("Too Far"), 2)

        return True

    def key_down(self):
        self.maybe_add_to_recents()
        self.scroll_object(1)

    def key_up(self):
        self.maybe_add_to_recents()
        self.scroll_object(-1)

    def key_left(self):
        self.maybe_add_to_recents()
        return True

    def key_right(self):
        """
        When right is pressed, move to logging screen
        Or, if eyepiece input is active, complete the input
        """
        # If eyepiece input is active, complete it
        if self.eyepiece_input_display:
            self._apply_custom_eyepiece()
            return True

        self.maybe_add_to_recents()
        if self.shared_state.solution() is None:
            return
        object_item_definition = {
            "name": _("LOG"),
            "class": UILog,
            "object": self.object,
        }
        self.add_to_stack(object_item_definition)

    def change_fov(self, direction):
        """
        Change field of view by cycling eyepieces.
        If a custom eyepiece is active, jump to the nearest configured eyepiece and remove custom.
        """
        if self._custom_eyepiece is not None:
            # Custom eyepiece is active - remove it and find nearest configured eyepiece
            logger.info(f">>> Custom eyepiece active, switching to configured eyepieces")
            custom_focal_length = self._custom_eyepiece.focal_length_mm

            # Remove custom eyepiece from equipment list
            if self._custom_eyepiece in self.config_object.equipment.eyepieces:
                self.config_object.equipment.eyepieces.remove(self._custom_eyepiece)
            self._custom_eyepiece = None

            # Get configured eyepieces (now that custom is removed)
            eyepieces = self.config_object.equipment.eyepieces
            if not eyepieces:
                return

            # Sort eyepieces by focal length
            sorted_eyepieces = sorted(eyepieces, key=lambda e: e.focal_length_mm)

            if direction > 0:
                # Find next larger eyepiece (smaller magnification)
                for ep in sorted_eyepieces:
                    if ep.focal_length_mm > custom_focal_length:
                        self.config_object.equipment.active_eyepiece_index = eyepieces.index(ep)
                        logger.info(f">>> Jumped to next larger: {ep}")
                        break
                else:
                    # No larger eyepiece found, wrap to smallest
                    self.config_object.equipment.active_eyepiece_index = eyepieces.index(sorted_eyepieces[0])
                    logger.info(f">>> Wrapped to smallest: {sorted_eyepieces[0]}")
            else:
                # Find next smaller eyepiece (larger magnification)
                for i in range(len(sorted_eyepieces) - 1, -1, -1):
                    ep = sorted_eyepieces[i]
                    if ep.focal_length_mm < custom_focal_length:
                        self.config_object.equipment.active_eyepiece_index = eyepieces.index(ep)
                        logger.info(f">>> Jumped to next smaller: {ep}")
                        break
                else:
                    # No smaller eyepiece found, wrap to largest
                    self.config_object.equipment.active_eyepiece_index = eyepieces.index(sorted_eyepieces[-1])
                    logger.info(f">>> Wrapped to largest: {sorted_eyepieces[-1]}")
        else:
            # Normal eyepiece cycling
            self.config_object.equipment.cycle_eyepieces(direction)
            logger.info(f">>> Normal cycle to: {self.config_object.equipment.active_eyepiece}")

        self.update_object_info()
        self.update()

    def key_plus(self):
        if self.object_display_mode == DM_DESC:
            self.descTextLayout.next()
            typeconst = self.texts.get("type-const")
            if typeconst and isinstance(typeconst, TextLayouter):
                typeconst.next()
        else:
            self.change_fov(1)

    def key_minus(self):
        if self.object_display_mode == DM_DESC:
            self.descTextLayout.next()
            typeconst = self.texts.get("type-const")
            if typeconst and isinstance(typeconst, TextLayouter):
                typeconst.next()
        else:
            self.change_fov(-1)

    def key_number(self, number):
        """
        Handle number key presses
        When viewing image (DM_IMAGE):
        - 0: Toggle between POSS image and Gaia chart (only if no input active)
        - 1-9: Start custom eyepiece input
        - After first digit, 0-9 adds second digit or completes input
        """
        logger.info(f">>> key_number({number}) called")

        # Only handle custom eyepiece input in image display modes
        if self.object_display_mode != DM_IMAGE:
            return

        # Special case: 0 when no input is active toggles POSS/chart
        if number == 0 and not self.eyepiece_input_display:
            logger.info(f">>> Toggling _force_gaia_chart (was: {self._force_gaia_chart})")
            # Toggle the flag
            self._force_gaia_chart = not self._force_gaia_chart
            logger.info(f">>> _force_gaia_chart now: {self._force_gaia_chart}")

            # Reload image with new setting
            logger.info(">>> Calling update_object_info()...")
            self.update_object_info()
            logger.info(f">>> After update_object_info(), self.object_image type: {type(self.object_image)}, size: {self.object_image.size if self.object_image else None}")
            logger.info(">>> Calling update()...")
            update_result = self.update()
            logger.info(f">>> update() returned: {type(update_result)}")
            logger.info(">>> key_number(0) complete")
            return True

        # Handle custom eyepiece input (1-9 to start, 0-9 for second digit)
        if number >= 1 or (number == 0 and self.eyepiece_input_display):
            logger.info(f">>> Adding digit {number} to eyepiece input")
            is_complete = self.eyepiece_input.append_digit(number)
            self.eyepiece_input_display = True
            logger.info(f">>> After adding digit: focal_length={self.eyepiece_input.focal_length_mm}mm, complete={is_complete}, display='{self.eyepiece_input}'")

            if is_complete:
                # Two digits entered, apply immediately
                logger.info(f">>> Input complete, applying {self.eyepiece_input.focal_length_mm}mm")
                self._apply_custom_eyepiece()
            else:
                # Show popup with current input
                logger.info(f">>> Input incomplete, showing popup")
                self.update()

            return True
