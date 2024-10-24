import numpy as np
import logging
from typing import Tuple

logger = logging.getLogger("Solver")


class SQM():
    """
    SQM class to calculate SQM value from centroids and image.
    Procedure:
        - measure the background adu
        - measure the adu of the centroids
        - calculate real background by subtracting both the area and the adus
        of all centroids
        - calculate sqm by using the known adu and the known magnitude of the matched stars
    """

    def __init__(self):
        super()

    def _calc_degrees(self, degrees):
        self.degrees = degrees
        self.field_in_arcseconds = (degrees * 3600)**2
        self.pixel_arcseconds = self.field_in_arcseconds / 512**2

    def calculate(self, bias_image, centroids, solution, image, radius=4) -> Tuple[float, list]:
        """
        Calculate SQM value from centroids and image
        """
        fov_estimate = solution['FOV']
        self._calc_degrees(fov_estimate)
        self.radius = radius
        centroids = np.array(centroids)[:, ::-1]
        matched_centroids = np.array(solution["matched_centroids"])[:, ::-1]  # reverses the last dimension
        matched_stars = solution["matched_stars"]
        assert len(matched_centroids) == len(matched_stars)
        # image = image - bias_image

        bias_ADU = self._calculate_background(bias_image)
        print("bias adu is:", bias_ADU)
        background_ADU = self._calculate_background(image)
        print("background adu is:", bias_ADU)
        all_stars_ADU = self._star_flux(image, centroids, self.radius)
        matched_stars_ADU = self._star_flux(image, matched_centroids, self.radius)
        background_ADU_corrected = background_ADU - np.sum(all_stars_ADU)
        field_corrected = self.field_in_arcseconds - self.pixel_arcseconds * len(all_stars_ADU) * np.pi * self.radius**2
        background = background_ADU_corrected / field_corrected  # background ADU per arcsecond squared
        sqm, sqms, adu_stars = self._calculate_sqm(background, matched_stars_ADU, matched_stars)
        logger.debug(f"{background=}, {sqm=}, {sqms=}, {adu_stars=}")
        return sqm, sqms

    def _calculate_background(self, np_image) -> float:
        """
        Calculate background from image
        """
        total_area_ADU = np.sum(np_image)
        return total_area_ADU

    def _draw_annulus(self, image, x, y, cx, cy, radius):
        # Draw the annulus on the image copy
        circle = (x - cx)**2 + (y - cy)**2
        annulus = (circle >= (radius-1)**2) & (circle <= (radius+1)**2)
        image[annulus] = np.max(image)  # Set annulus pix4ls to max value for visibility
        return image

    def _star_flux(self, image, centroids, radius):
        height, width = image.shape
        y, x = np.ogrid[:height, :width]
        results = []

        for cx, cy in centroids:
            # Create a mask for the circular region
            mask = (x - cx)**2 + (y - cy)**2 <= radius**2

            # Calculate the sum of pixel values in the circular region
            annulus_sum = np.sum(image[mask])

            results.append(annulus_sum)
        return results

    def _calculate_sqm(self, background, matched_stars_ADU, matched_stars) -> Tuple[float, list, list]:
        """
        Calculate SQM value from background
        """
        sqms = []
        adu_stars = zip(matched_stars_ADU, [x[2] for x in matched_stars])
        # take the ADU of the centroids and the mag of the matched stars
        for adu, star in adu_stars:
            ratio = adu / background
            if ratio == 0:
                continue
            mag = -2.5 * np.log10(1/ratio)
            sqm = star + mag
            sqms.append(sqm)
        logger.debug(f"{sqms=}")
        return float(np.median(sqms)), sqms, list(adu_stars)

