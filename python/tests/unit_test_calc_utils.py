""" 
Unit tests for: PiFinder.calc_utils: Coordinate transformations, etc.

Run from PiFinder/python:
`> python -m tests.unit_test_calc_utils`
"""

import unittest
from PiFinder.calc_utils import hadec_to_pa

class UnitTestCalcUtils(unittest.TestCase):
    """
    Unit tests for calc_utils.py which does coordinate transformations.
    """

    def test_hadec_to_pa0(self):
        """ Test hadec_to_pa() for the special case when HA = 0 """
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
    
"""
    def test_hadec_to_pa(self):
        # Define the inputs:        
        ha_deg = 60.0
        lat_deg = 51.0  # Approximately Greenwich Observatory
        dec_degs = [90, 60, 51, 30, 0, -30]
        # Expected values
        exp_pa_degs = []
        
        expected_pa_degs = []  # For HA=+60 deg
        for dec, expected in zip(dec_degs, expected_pa_degs):
            # +ve HA case:
            pa_deg = hadec_to_pa(ha_deg, dec, lat_deg)
            self.assertAlmostEqual(pa_deg, expected, places=3, 
                                   message='HA = {:.2f}, dec = {:.2f}'.format(ha_deg, dec))
            # -ve HA case (expect -ve values):
            pa_deg = hadec_to_pa(-ha_deg, dec, lat_deg)
            self.assertAlmostEqual(pa_deg, -expected, places=3, 
                                   message='HA = {:.2f}, dec = {:.2f}'.format(-ha_deg, dec))
"""

if __name__ == '__main__':
    unittest.main()