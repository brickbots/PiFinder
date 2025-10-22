from PiFinder.ui.base import UIModule
from PiFinder import utils
from PiFinder.state_utils import sleep_for_framerate
from PiFinder.ui.ui_utils import TextLayouter
import time
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:

    def _(a) -> Any:
        return a


sys_utils = utils.get_sys_utils()


class UISQM(UIModule):
    """
    Displays various status information
    """

    __title__ = _("SQM")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.show_description = False
        self.text_layout = TextLayouter(
            "",
            draw=self.draw,
            color=self.colors.get(255),
            colors=self.colors,
            font=self.fonts.base,
        )

    def update(self, force=False):
        sleep_for_framerate(self.shared_state)
        self.clear_screen()

        if (
            self.shared_state.solve_state is None
            or self.shared_state.solution() is None
            or "SQM" not in self.shared_state.solution()
            or self.shared_state.solution()["SQM"] is None
        ):
            self.draw.text(
                (10, 30),
                _("NO SQM DATA"),
                font=self.fonts.bold.font,
                fill=self.colors.get(128),
            )
        else:
            sqm_data = self.shared_state.solution()["SQM"]
            sqm = sqm_data[0]
            sqm_timestamp = sqm_data[2] if len(sqm_data) > 2 else None
            details = self.get_sky_details(sqm)

            # If no details found, show SQM value only
            if details is None:
                self.draw.text(
                    (10, 30),
                    f"{sqm:.2f}",
                    font=self.fonts.huge.font,
                    fill=self.colors.get(128),
                )
                self.draw.text(
                    (10, 80),
                    _("mag/arcsec²"),
                    font=self.fonts.base.font,
                    fill=self.colors.get(128),
                )
                return self.screen_update()

            if self.show_description and details:
                # Show scrollable description with bullet points
                desc_lines = [f"• {line}" for line in details["description"]]
                desc_lines.append("─" * self.fonts.base.line_length)  # End marker
                desc_text = "\n".join(desc_lines)
                self.text_layout.set_text(desc_text, reset_pointer=False)
                self.text_layout.set_available_lines(7)

                # Title
                self.draw.text(
                    (0, 20),
                    _("Bortle {bc}").format(bc=details["bortle_class"]),
                    font=self.fonts.bold.font,
                    fill=self.colors.get(255),
                )

                # Scrollable description
                self.text_layout.draw((0, 38))

                # Legend
                back_text = _("BACK")
                scroll_text = _("SCROLL")
                self.draw.text(
                    (0, 115),
                    f"{self._SQUARE_} {back_text}  {self._PLUSMINUS_} {scroll_text}",
                    font=self.fonts.base.font,
                    fill=self.colors.get(128),
                )
            else:
                # Main SQM view
                # Last calculation time
                if sqm_timestamp:
                    elapsed = int(time.time() - sqm_timestamp)
                    if elapsed < 60:
                        time_str = _("{s}s ago").format(s=elapsed)
                    else:
                        time_str = _("{m}m ago").format(m=elapsed // 60)
                    self.draw.text(
                        (10, 20),
                        time_str,
                        font=self.fonts.base.font,
                        fill=self.colors.get(64),
                    )

                self.draw.text(
                    (10, 30),
                    f"{sqm:.2f}",
                    font=self.fonts.huge.font,
                    fill=self.colors.get(128),
                )
                self.draw.text(
                    (10, 80),
                    f"{details['title']}",
                    font=self.fonts.base.font,
                    fill=self.colors.get(128),
                )
                self.draw.text(
                    (10, 90),
                    _("Bortle {bc}").format(bc=details["bortle_class"]),
                    font=self.fonts.bold.font,
                    fill=self.colors.get(128),
                )

                # Legend
                details_text = _("DETAILS")
                self.draw.text(
                    (10, 110),
                    f"{self._SQUARE_} {details_text}",
                    font=self.fonts.base.font,
                    fill=self.colors.get(64),
                )

        return self.screen_update()

    def key_square(self):
        """Toggle between main view and description view"""
        self.show_description = not self.show_description
        if self.show_description:
            self.text_layout.pointer = 0

    def key_plus(self):
        """Scroll description down"""
        if self.show_description:
            self.text_layout.next()

    def key_minus(self):
        """Scroll description up"""
        if self.show_description:
            self.text_layout.previous()

    def active(self):
        """
        Called when a module becomes active
        i.e. foreground controlling display
        """

    def get_sky_details(self, mag_arcsec):
        """
        Takes a mag/arcsec² value and returns corresponding Bortle scale details.

        Source: https://en.wikipedia.org/wiki/Bortle_scale

        Args:
            mag_arcsec (float): The magnitude per square arcsecond value

        Returns:
            dict: Dictionary containing all Bortle scale properties for the given magnitude
        """
        scale = [
            {
                "bortle_class": 1,
                "title": _("Excellent Dark-Sky Site"),
                "nelm_range": (7.6, 8.0),
                "mag_arcsec_range": (21.76, 22.00),
                "description": [
                    _("The zodiacal light is visible and colorful. Gegenschein readily visible."),
                    _("The Scorpius and Sagittarius regions of the Milky Way cast obvious shadows."),
                    _("M33 is a direct naked-eye object. Airglow readily visible."),
                    _("Abundant stars make faint constellations hard to distinguish."),
                ],
            },
            {
                "bortle_class": 2,
                "title": _("Typical Truly Dark Site"),
                "nelm_range": (7.1, 7.5),
                "mag_arcsec_range": (21.60, 21.76),
                "description": [
                    _("The zodiacal light is distinctly yellowish and bright enough to cast shadows at dusk and dawn."),
                    _("Clouds appear as dark silhouettes against the sky."),
                    _("The summer Milky Way is highly structured. M33 easily visible."),
                ],
            },
            {
                "bortle_class": 3,
                "title": _("Rural Sky"),
                "nelm_range": (6.6, 7.0),
                "mag_arcsec_range": (21.30, 21.60),
                "description": [
                    _("The zodiacal light is striking in spring and autumn, color still visible."),
                    _("Some light pollution at horizon. Clouds illuminated near horizon, dark overhead."),
                    _("The summer Milky Way still appears complex."),
                    _("Several Messier objects remain naked-eye visible."),
                ],
            },
            {
                "bortle_class": 4,
                "title": _("Brighter Rural"),
                "nelm_range": (6.3, 6.5),
                "mag_arcsec_range": (20.80, 21.30),
                "description": [
                    _("Zodiacal light still visible but doesn't extend halfway to zenith."),
                    _("Light pollution domes apparent in multiple directions."),
                    _("The Milky Way well above the horizon is still impressive, but lacks detail."),
                    _("M33 difficult to see."),
                ],
            },
            {
                "bortle_class": 4.5,
                "title": _("Semi-Suburban/Transition Sky"),
                "nelm_range": (6.1, 6.3),
                "mag_arcsec_range": (20.30, 20.80),
                "description": [
                    _("Clouds have a grayish glow at zenith and appear bright toward city domes."),
                    _("Milky Way only vaguely visible 10-15° above horizon."),
                    _("Great Rift observable overhead."),
                ],
            },
            {
                "bortle_class": 5,
                "title": _("Suburban Sky"),
                "nelm_range": (5.6, 6.0),
                "mag_arcsec_range": (19.25, 20.30),
                "description": [
                    _("Only hints of zodiacal light seen on best nights in autumn and spring."),
                    _("Light pollution visible in most, if not all, directions."),
                    _("Clouds noticeably brighter than the sky."),
                    _("Milky Way invisible near horizon, looks washed out overhead."),
                ],
            },
            {
                "bortle_class": 6,
                "title": _("Bright Suburban Sky"),
                "nelm_range": (5.1, 5.5),
                "mag_arcsec_range": (18.50, 19.25),
                "description": [
                    _("The zodiacal light is invisible."),
                    _("Light pollution makes sky within 35° of horizon glow grayish white."),
                    _("The Milky Way is only visible near the zenith. M33 undetectable."),
                    _("M31 modestly apparent. Surroundings easily visible."),
                ],
            },
            {
                "bortle_class": 7,
                "title": _("Suburban/Urban Transition"),
                "nelm_range": (4.6, 5.0),
                "mag_arcsec_range": (18.00, 18.50),
                "description": [
                    _("Light pollution makes the entire sky light gray."),
                    _("Strong light sources evident in all directions."),
                    _("The Milky Way is nearly or totally invisible."),
                    _("M31 and M44 may be glimpsed, but with no detail."),
                ],
            },
            {
                "bortle_class": 8,
                "title": _("City Sky"),
                "nelm_range": (4.1, 4.5),
                "mag_arcsec_range": (17.00, 18.00),
                "description": [
                    _("The sky is light gray or orange—one can easily read."),
                    _("Stars forming recognizable patterns may vanish entirely."),
                    _("Only bright Messier objects can be detected with telescopes."),
                ],
            },
            {
                "bortle_class": 9,
                "title": _("Inner-City Sky"),
                "nelm_range": (0.0, 4.0),
                "mag_arcsec_range": (0.00, 17.00),
                "description": [
                    _("The sky is brilliantly lit."),
                    _("Many stars forming constellations invisible."),
                    _("Only the Moon, planets, bright satellites, and a few of the brightest star clusters observable."),
                ],
            },
        ]

        # Find matching range
        for props in scale:
            min_mag_arcsec, max_mag_arcsec = props["mag_arcsec_range"]
            if min_mag_arcsec <= mag_arcsec <= max_mag_arcsec:
                return {
                    "bortle_class": props["bortle_class"],
                    "title": props["title"],
                    "nelm_range": f"{props['nelm_range'][0]} - {props['nelm_range'][1]}",
                    "mag_arcsec_range": f"{min_mag_arcsec} - {max_mag_arcsec}",
                    "description": props["description"],
                }

        return None
