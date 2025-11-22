#!/usr/bin/python
# -*- coding:utf-8 -*-
# mypy: ignore-errors
"""
This module contains all the UI code for the object details screen

"""

from PiFinder import cat_images
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
import logging
import numpy as np
import time

logger = logging.getLogger("PiFinder.UIObjectDetails")

# Constants for display modes
DM_DESC = 0  # Display mode for description
DM_LOCATE = 1  # Display mode for LOCATE
DM_POSS = 2  # Display mode for POSS
DM_SDSS = 3  # Display mode for SDSS


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
        self._is_showing_loading_chart = False  # Track if showing "Loading..." for deep chart
        self._force_deep_chart = False  # Toggle: force deep chart even if POSS image exists
        self._is_deep_chart = False  # Track if currently showing a deep chart (auto or forced)

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
        self._deep_chart_marking_menu = MarkingMenu(
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
        if self._is_deep_chart:
            return self._deep_chart_marking_menu
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
        logger.info(f">>> update_object_info() called for {self.object.display_name if self.object else 'None'}")
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

        magnification = self.config_object.equipment.calc_magnification()
        prev_object_image = self.object_image

        # Get or create chart generator (owned by UI layer, not cat_images)
        logger.info(">>> Getting chart generator...")
        chart_gen = self._get_chart_generator()
        logger.info(f">>> Chart generator obtained, state: {chart_gen.get_catalog_state() if chart_gen else 'None'}")

        logger.info(f">>> Calling cat_images.get_display_image with force_deep_chart={self._force_deep_chart}")

        # get_display_image returns either an image directly (POSS) or a generator (deep chart)
        result = cat_images.get_display_image(
            self.object,
            str(self.config_object.equipment.active_eyepiece),
            self.config_object.equipment.calc_tfov(),
            roll,
            self.display_class,
            burn_in=self.object_display_mode in [DM_POSS, DM_SDSS],
            magnification=magnification,
            config_object=self.config_object,
            shared_state=self.shared_state,
            chart_generator=chart_gen,  # Pass our chart generator to cat_images
            force_deep_chart=self._force_deep_chart,  # Toggle state
        )

        # Check if it's a generator (progressive deep chart) or direct image (POSS)
        if hasattr(result, '__iter__') and hasattr(result, '__next__'):
            # It's a generator - consume yields and update display for each one
            logger.info(">>> get_display_image returned GENERATOR, consuming yields progressively...")
            for yield_num, image in enumerate(result, 1):
                logger.info(f">>> Received yield #{yield_num} from generator: {type(image)}")
                self.object_image = image
                # Force immediate screen update to show this progressive result
                self.update(force=True)
                logger.info(f">>> Display updated with yield #{yield_num}")
            logger.info(f">>> Generator exhausted, final image: {type(self.object_image)}")
        else:
            # Direct image (POSS)
            logger.info(f">>> get_display_image returned direct image: {type(result)}")
            self.object_image = result

        logger.info(f">>> update_object_info() complete, self.object_image is now: {type(self.object_image)}")

        # Track if we're showing a "Loading..." placeholder for deep chart
        # Check if image has the special "is_loading_placeholder" attribute
        self._is_showing_loading_chart = (
            self.object_image is not None
            and hasattr(self.object_image, 'is_loading_placeholder')
            and self.object_image.is_loading_placeholder
            and self.object_display_mode in [DM_POSS, DM_SDSS]
        )

        # Detect if we're showing a deep chart (forced or automatic due to no POSS image)
        # Deep charts are identified by the is_loading_placeholder attribute (loading or False)
        self._is_deep_chart = (
            self.object_image is not None
            and hasattr(self.object_image, 'is_loading_placeholder')
            and self.object_display_mode in [DM_POSS, DM_SDSS]
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

        # Pulsate: full cycle every 2 seconds
        pulse_period = 2.0  # seconds
        t = time.time() % pulse_period
        # Sine wave for smooth pulsation (0.0 to 1.0 range)
        pulse_factor = 0.5 + 0.5 * np.sin(2 * np.pi * t / pulse_period)

        # Size multiplier: 0.6 to 1.0 (smaller range, smoother looking)
        size_multiplier = 0.6 + 0.4 * pulse_factor

        # Color intensity: 48 to 128 (brighter and more visible)
        color_intensity = int(48 + 80 * pulse_factor)

        return pulse_factor, size_multiplier, color_intensity

    def _draw_crosshair_simple(self, pulse=False):
        """
        Draw simple crosshair with 4 lines and center gap

        Args:
            pulse: If True, apply pulsation effect
        """
        width, height = self.display_class.resolution
        cx, cy = width / 2.0, height / 2.0

        if pulse:
            _, size_mult, color_intensity = self._get_pulse_factor()
            # Size pulsates from 6 down to 3 pixels (inverted - more steps)
            outer = 6.0 - (3.0 * size_mult)  # 6.0 down to 3.0 (more visible integer steps)
            marker_color = self.colors.get(color_intensity)
        else:
            # Fixed size and brightness
            outer = 4
            marker_color = self.colors.get(64)

        inner = 2  # Fixed gap (small center)

        # Crosshair outline (4 short lines with gap in middle)
        self.draw.line([cx - outer, cy, cx - inner, cy], fill=marker_color, width=1)  # Left
        self.draw.line([cx + inner, cy, cx + outer, cy], fill=marker_color, width=1)  # Right
        self.draw.line([cx, cy - outer, cx, cy - inner], fill=marker_color, width=1)  # Top
        self.draw.line([cx, cy + inner, cx, cy + outer], fill=marker_color, width=1)  # Bottom

    def _draw_crosshair_circle(self, pulse=False):
        """
        Draw circle reticle

        Args:
            pulse: If True, apply pulsation effect
        """
        width, height = self.display_class.resolution
        cx, cy = width / 2.0, height / 2.0

        if pulse:
            _, size_mult, color_intensity = self._get_pulse_factor()
            radius = 8.0 - (4.0 * size_mult)  # 8.0 down to 4.0 (more steps)
            marker_color = self.colors.get(color_intensity)
        else:
            radius = 4  # Smaller fixed size
            marker_color = self.colors.get(64)

        # Draw circle
        bbox = [cx - radius, cy - radius, cx + radius, cy + radius]
        self.draw.ellipse(bbox, outline=marker_color, width=1)

        # Small center dot
        self.draw.ellipse([cx - 1, cy - 1, cx + 1, cy + 1], fill=marker_color)

    def _draw_crosshair_bullseye(self, pulse=False):
        """
        Draw concentric circles (bullseye)

        Args:
            pulse: If True, apply pulsation effect
        """
        width, height = self.display_class.resolution
        cx, cy = width / 2.0, height / 2.0

        if pulse:
            _, size_mult, color_intensity = self._get_pulse_factor()
            marker_color = self.colors.get(color_intensity)
            # Pulsate from larger to smaller (more visible steps)
            radii = [4.0 - (2.0 * size_mult), 8.0 - (4.0 * size_mult), 12.0 - (6.0 * size_mult)]  # 4→2, 8→4, 12→6
        else:
            marker_color = self.colors.get(64)
            radii = [2, 4, 6]  # Smaller fixed radii

        # Draw concentric circles
        for radius in radii:
            bbox = [cx - radius, cy - radius, cx + radius, cy + radius]
            self.draw.ellipse(bbox, outline=marker_color, width=1)

    def _draw_crosshair_brackets(self, pulse=False):
        """
        Draw corner brackets (frame corners)

        Args:
            pulse: If True, apply pulsation effect
        """
        width, height = self.display_class.resolution
        cx, cy = width / 2.0, height / 2.0

        if pulse:
            _, size_mult, color_intensity = self._get_pulse_factor()
            size = 8.0 - (4.0 * size_mult)  # 8.0 down to 4.0 (more steps)
            length = 5.0 - (2.0 * size_mult)  # 5.0 down to 3.0 (more steps)
            marker_color = self.colors.get(color_intensity)
        else:
            size = 4  # Smaller distance from center to bracket corner
            length = 3  # Shorter bracket arms
            marker_color = self.colors.get(64)

        # Top-left bracket
        self.draw.line([cx - size, cy - size, cx - size + length, cy - size], fill=marker_color, width=1)
        self.draw.line([cx - size, cy - size, cx - size, cy - size + length], fill=marker_color, width=1)

        # Top-right bracket
        self.draw.line([cx + size, cy - size, cx + size - length, cy - size], fill=marker_color, width=1)
        self.draw.line([cx + size, cy - size, cx + size, cy - size + length], fill=marker_color, width=1)

        # Bottom-left bracket
        self.draw.line([cx - size, cy + size, cx - size + length, cy + size], fill=marker_color, width=1)
        self.draw.line([cx - size, cy + size, cx - size, cy + size - length], fill=marker_color, width=1)

        # Bottom-right bracket
        self.draw.line([cx + size, cy + size, cx + size - length, cy + size], fill=marker_color, width=1)
        self.draw.line([cx + size, cy + size, cx + size, cy + size - length], fill=marker_color, width=1)

    def _draw_crosshair_dots(self, pulse=False):
        """
        Draw four corner dots

        Args:
            pulse: If True, apply pulsation effect
        """
        width, height = self.display_class.resolution
        cx, cy = width / 2.0, height / 2.0

        if pulse:
            _, size_mult, color_intensity = self._get_pulse_factor()
            distance = 8.0 - (4.0 * size_mult)  # 8.0 down to 4.0 (more steps)
            dot_size = 3.0 - (1.5 * size_mult)  # 3.0 down to 1.5 (more steps)
            marker_color = self.colors.get(color_intensity)
        else:
            distance = 4  # Smaller distance from center to dots
            dot_size = 1  # Smaller dot radius
            marker_color = self.colors.get(64)

        # Four corner dots
        positions = [
            (cx - distance, cy - distance),  # Top-left
            (cx + distance, cy - distance),  # Top-right
            (cx - distance, cy + distance),  # Bottom-left
            (cx + distance, cy + distance),  # Bottom-right
        ]

        for x, y in positions:
            bbox = [x - dot_size, y - dot_size, x + dot_size, y + dot_size]
            self.draw.ellipse(bbox, fill=marker_color)

    def _draw_crosshair_cross(self, pulse=False):
        """
        Draw full cross (lines extend across entire screen)

        Args:
            pulse: If True, apply pulsation effect
        """
        width, height = self.display_class.resolution
        cx, cy = width / 2.0, height / 2.0

        if pulse:
            _, size_mult, color_intensity = self._get_pulse_factor()
            marker_color = self.colors.get(color_intensity)
        else:
            marker_color = self.colors.get(64)

        # Horizontal line
        self.draw.line([0, cy, width, cy], fill=marker_color, width=1)
        # Vertical line
        self.draw.line([cx, 0, cx, height], fill=marker_color, width=1)

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

    def _get_chart_generator(self):
        """Get the global chart generator singleton"""
        from PiFinder.deep_chart import get_chart_generator
        import logging
        logger = logging.getLogger("ObjectDetails")

        chart_gen = get_chart_generator(self.config_object, self.shared_state)
        logger.info(f">>> _get_chart_generator returning: {chart_gen}")
        return chart_gen

    def update(self, force=True):
        import logging
        logger = logging.getLogger("ObjectDetails")

        # Check if we're showing "Loading..." for a deep chart
        # and if catalog is now ready, regenerate the image
        if self._is_showing_loading_chart:
            try:
                from PiFinder.star_catalog import CatalogState

                # Use cached chart generator to preserve catalog state
                chart_gen = self._get_chart_generator()
                state = chart_gen.get_catalog_state()
                logger.info(f">>> Update check: catalog state = {state}")

                if state == CatalogState.READY:
                    # Catalog ready! Regenerate display
                    logger.info(">>> Catalog READY! Regenerating image...")
                    self._is_showing_loading_chart = False
                    self.update_object_info()
                    force = True  # Force screen update
            except Exception as e:
                logger.error(f">>> Update check failed: {e}", exc_info=True)
                pass
        # Clear Screen
        self.clear_screen()

        # paste image
        if self.object_display_mode in [DM_POSS, DM_SDSS]:
            self.screen.paste(self.object_image)

            # If showing deep chart, draw crosshair based on config
            if self._force_deep_chart and self.object_image is not None:
                crosshair_mode = self.config_object.get_option("obj_chart_crosshair")
                crosshair_style = self.config_object.get_option("obj_chart_crosshair_style")

                if crosshair_mode != "off":
                    # Determine if we should pulse
                    pulse = (crosshair_mode == "pulse")

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
                    draw_method(pulse=pulse)

        if self.object_display_mode == DM_DESC or self.object_display_mode == DM_LOCATE:
            # catalog and entry field i.e. NGC-311
            self.refresh_designator()
            desc_available_lines = 4
            desig = self.texts["designator"]
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

        return self.screen_update()

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
        When right is pressed, move to
        logging screen
        """
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
        self.config_object.equipment.cycle_eyepieces(direction)
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
        0: Toggle between POSS image and deep chart (when both are available)
        """
        logger.info(f">>> key_number({number}) called")
        if number == 0:
            logger.info(f">>> Toggling _force_deep_chart (was: {self._force_deep_chart})")
            # Toggle the flag
            self._force_deep_chart = not self._force_deep_chart
            logger.info(f">>> _force_deep_chart now: {self._force_deep_chart}")
            # Reload image with new setting
            logger.info(">>> Calling update_object_info()...")
            self.update_object_info()
            logger.info(f">>> After update_object_info(), self.object_image type: {type(self.object_image)}, size: {self.object_image.size if self.object_image else None}")
            logger.info(">>> Calling update()...")
            update_result = self.update()
            logger.info(f">>> update() returned: {type(update_result)}")
            logger.info(">>> key_number(0) complete")
            return True
