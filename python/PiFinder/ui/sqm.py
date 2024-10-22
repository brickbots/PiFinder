import time

from luma.core.device import sleep

from PiFinder.ui.base import UIModule
from PiFinder import utils
from PiFinder.state_utils import sleep_for_framerate
from PiFinder.ui.ui_utils import TextLayouter, SpaceCalculatorFixed
sys_utils = utils.get_sys_utils()


class UISQM(UIModule):
    """
    Displays various status information
    """

    __title__ = "SQM"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def update(self, force=False):
        sleep_for_framerate(self.shared_state)
        self.clear_screen()

        if (self.shared_state.solve_state is None or self.shared_state.solution() is None or self.shared_state.solution()["SQM"] is None):
            self.draw.text(
                (10, 30),
                "NO SQM DATA",
                font=self.fonts.bold.font,
                fill=self.colors.get(128),
            )
        else:
            sqm = self.shared_state.solution()["SQM"][0]
            self.draw.text(
                (10, 30),
                f"{sqm:.2f}",
                font=self.fonts.huge.font,
                fill=self.colors.get(128),
            )
            details = self.get_sky_details(sqm)
            self.draw.text(
                (10, 80),
                f"{details['title']}",
                font=self.fonts.base.font,
                fill=self.colors.get(128),
            )
            self.draw.text(
                (10, 90),
                f"Bortle {details['bortle_class']}",
                font=self.fonts.bold.font,
                fill=self.colors.get(128),
            )

        return self.screen_update()

    # def key_up(self):
    #     self.text_layout.previous()
    #
    # def key_down(self):
    #     self.text_layout.next()

    def active(self):
        """
        Called when a module becomes active
        i.e. foreground controlling display
        """

    def get_sky_details(self, mag_arcsec):
        """
        Takes a mag/arcsec² value and returns corresponding Bortle scale details.

        Source: https://www.juliandarkskynetwork.com/sky-quality.html

        Args:
            mag_arcsec (float): The magnitude per square arcsecond value

        Returns:
            dict: Dictionary containing all Bortle scale properties for the given magnitude
        """
        scale = [
            {
                'bortle_class': 1,
                'title': 'Excellent Dark Sky Site',
                'nelm_range': (7.6, 8.0),
                'mag_arcsec_range': (21.99, 22.00),
                'description': [
                    'Zodiacal light visible; M33 direct vision naked eye object;',
                    'Regions of the Milky Way cast obvious shadows on the ground;',
                    'surroundings basically invisible.'
                ]
            },
            {
                'bortle_class': 2,
                'title': 'Typical True Dark Sky Site',
                'nelm_range': (7.1, 7.5),
                'mag_arcsec_range': (21.89, 21.99),
                'description': [
                    'Highly structured summer Milky Way;',
                    'distinctly yellowish zodiacal light bright enough to cast shadows',
                    'at dusk and dawn.'
                ]
            },
            {
                'bortle_class': 3,
                'title': 'Rural Sky',
                'nelm_range': (6.6, 7.0),
                'mag_arcsec_range': (21.69, 21.89),
                'description': [
                    'Low light domes (10 to 15 degrees) on horizon.',
                    'M33 easy with averted vision.',
                    'Milky way shows bulge.'
                ]
            },
            {
                'bortle_class': 4,
                'title': 'Rural / Suburban Transition',
                'nelm_range': (6.2, 6.5),
                'mag_arcsec_range': (21.25, 21.69),
                'description': [
                    'Zodiacal light seen on best nights.',
                    'Milky way shows much dark lane structure with beginnings of faint bulge.',
                    'M33 difficult even when above 50 degrees.'
                ]
            },
            {
                'bortle_class': 4.5,
                'title': 'Suburban Sky',
                'nelm_range': (5.9, 6.2),
                'mag_arcsec_range': (20.49, 21.25),
                'description': [
                    'Some dark lanes in Milky Way but no bulge.',
                    'Washed out Milky Way visible near horizon.',
                    'Zodiacal light very rare. Light domes up to 45 degrees.'
                ]
            },
            {
                'bortle_class': 5,
                'title': 'Bright Suburban Sky',
                'nelm_range': (5.6, 5.9),
                'mag_arcsec_range': (19.50, 20.49),
                'description': [
                    'Milky Way washed out at zenith and invisible at horizon.',
                    'Many light domes. Clouds are brighter than sky.'
                ]
            },
            {
                'bortle_class': (6, 7),
                'title': 'Suburban / Urban Transition or Full Moon',
                'nelm_range': (5.0, 5.5),
                'mag_arcsec_range': (18.38, 19.50),
                'description': [
                    'Milky Way at best very faint at zenith. M31 difficult and indistinct.',
                    'Sky is grey up to 35 degrees.'
                ]
            },
            {
                'bortle_class': (8, 9),
                'title': 'City Sky',
                'nelm_range': (3.0, 4.0),
                'mag_arcsec_range': (0, 18.38),
                'description': [
                    'Entire sky is grayish or brighter.',
                    'Familiar constellations are missing stars.',
                    'Most people don\'t look up.'
                ]
            }
        ]

        # Find matching range
        for props in scale:
            min_mag_arcsec, max_mag_arcsec = props['mag_arcsec_range']
            if min_mag_arcsec <= mag_arcsec <= max_mag_arcsec:
                return {
                    'bortle_class': props['bortle_class'],
                    'title': props['title'],
                    'nelm_range': f"{props['nelm_range'][0]} - {props['nelm_range'][1]}",
                    'mag_arcsec_range': f"{min_mag_arcsec} - {max_mag_arcsec}",
                    'description': props['description']
                }

        return None
