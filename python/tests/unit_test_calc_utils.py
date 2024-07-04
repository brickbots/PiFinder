""" 
Unit tests for: PiFinder.calc_utils: Coordinate transformations, etc.

Run from PiFinder/python:
`> python -m tests.unit_test_calc_utils`
"""

import unittest
from PiFinder.calc_utils import hadec_to_pa, hadec_to_roll
import numpy as np


class UnitTestCalcUtils(unittest.TestCase):
    """
    Unit tests for calc_utils.py which does coordinate transformations.
    """

    def test_hadec_to_pa0(self):
        """ Unit Test: hadec_to_pa(): For the special case when HA = 0 """
        # Define the inputs:
        ha_deg = 0.0
        lat_deg = 51.0  # Approximately Greenwich Observatory
        dec_degs = [90, 60, 51, 30, 0, -30]
        
        # At HA = 0, expect pa = 0 or 180 deg
        for dec in dec_degs:
            pa_deg = hadec_to_pa(ha_deg, dec, lat_deg)
            if dec >= lat_deg:
                self.assertAlmostEqual(pa_deg, 180.0, places=3, 
                                       msg='HA = 0: dec={:.1f}'.format(dec))
            else:
                self.assertAlmostEqual(pa_deg, 0.0, places=3, 
                                       msg='HA = 0: dec={:.1f}'.format(dec))
    

    def test_hadec_to_pa(self):
        """ Unit Test: haddec_to_pa(): For when HA != 0 """
        # Define the inputs:        
        ha_deg = 60.0
        lat_deg = 51.0  # Approximately Greenwich Observatory
        dec_degs = [90, 60, 51, 30, 0, -30]
        # Expected values for +ve HA (exp. values for -ve HA are the -ves)
        expected_pa_degs = [120.00000, 77.9774, 65.8349, 46.5827, 35.0417, 33.2789]

        for dec, expected in zip(dec_degs, expected_pa_degs):
            # +ve HA case:
            pa_deg = hadec_to_pa(ha_deg, dec, lat_deg)
            self.assertAlmostEqual(pa_deg, expected, places=3, 
                                   msg='HA = {:.2f}, dec = {:.2f}'.format(ha_deg, dec))
            # -ve HA case (expect -ve values):
            pa_deg = hadec_to_pa(-ha_deg, dec, lat_deg)
            self.assertAlmostEqual(pa_deg, -expected, places=3, 
                                   msg='HA = {:.2f}, dec = {:.2f}'.format(-ha_deg, dec))


    def test_hadec_to_roll(self):
            """ Unit Test: haddec_to_roll() """
            # Define the inputs:        
            lat_deg = 51.0  # Approximately Greenwich Observatory
            ha_degs = [60.0, 60.0, 60.0, 60.0, 60.0, 60.0,
                    -60.0, -60.0, -60.0, -60.0, -60.0, -60.0] 
            dec_degs = [90, 60, 51, 30, 0, -30,
                        90, 60, 51, 30, 0, -30]
            # Expected values
            expected_roll_degs = [124.0807, 74.1037, -79.9949, -98.92265, -60.2643, -131.5124, 
                                -124.0807, -74.1037, 79.9949, 98.92265, 60.2643, 131.5124]

            for ha, dec, expected in zip(ha_degs, dec_degs, expected_roll_degs):
                roll = hadec_to_roll(ha, dec, lat_deg)
                self.assertAlmostEqual(roll, expected, places=3, 
                                    msg='HA = {:.2f}, dec = {:.2f}'.format(ha, dec))


    def test_hadec_to_roll2(self):
            """ Unit Test against observed roll data: haddec_to_roll() """
            # Define the inputs:        
            lat_deg = 35.819676052
            ha_hrs = [4.1309, -3.6298, 0.3378] 
            dec_degs = [74.0515, 22.2856, 30.3246]
            # Observed values
            observed_roll_degs = [72.0398, 62.6766, 328.6188]

            for ha_hr, dec, observed in zip(ha_hrs, dec_degs, observed_roll_degs):
                ha = ha_hr / 12 * 180  # Convert from hr to deg
                roll = hadec_to_roll(ha, dec, lat_deg)
                # Roll must be within 2 degrees
                self.assertLess(np.abs(roll - observed), 2, 
                                    msg='HA = {:.2f} hr, dec = {:.2f}, roll = {:.1f}, observed = {:.1f}'.format(ha_hr, dec, roll, observed))
                

if __name__ == '__main__':
    unittest.main(verbosity=2)