import pytest

from PiFinder.equipment import Equipment, Telescope


def make_telescope(flip_image: bool, flop_image: bool) -> Telescope:
    return Telescope(
        make="Test",
        name="Scope",
        aperture_mm=200,
        focal_length_mm=1000,
        obstruction_perc=17.0,
        mount_type="alt/az",
        flip_image=flip_image,
        flop_image=flop_image,
        reverse_arrow_a=False,
        reverse_arrow_b=False,
    )


@pytest.mark.unit
class TestActiveTelescopeOrientation:
    """Equipment.active_telescope_image_orientation() flag resolution."""

    def test_no_active_telescope_returns_no_mirror(self):
        equipment = Equipment(telescopes=[], eyepieces=[])
        assert equipment.active_telescope_image_orientation() == (False, False)

    def test_active_telescope_flags_are_returned(self):
        equipment = Equipment(
            telescopes=[make_telescope(flip_image=True, flop_image=False)],
            eyepieces=[],
            active_telescope_index=0,
        )
        assert equipment.active_telescope_image_orientation() == (True, False)

    def test_flop_only(self):
        equipment = Equipment(
            telescopes=[make_telescope(flip_image=False, flop_image=True)],
            eyepieces=[],
            active_telescope_index=0,
        )
        assert equipment.active_telescope_image_orientation() == (False, True)
