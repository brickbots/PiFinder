import pytest
from PiFinder import calc_utils


@pytest.mark.unit
def test_converters():
    assert round(calc_utils.ra_to_deg(10, 10, 50), 5) == 152.70833
    assert round(calc_utils.dec_to_deg(10, 10, 50), 5) == 10.18056
    assert calc_utils.dec_to_dms(80.55) == (80, 32, 59)
    assert calc_utils.ra_to_hms(81.55) == (5, 26, 12)
