import pytest
from PiFinder.ui import menu_structure


@pytest.mark.smoke
def test_menu_valid():
    assert type(menu_structure.pifinder_menu) is dict
