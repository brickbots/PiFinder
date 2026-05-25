import pytest
from PIL import Image

from PiFinder import cat_images
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


def _marker_image() -> Image.Image:
    """A small asymmetric image so every mirror actually moves a pixel."""
    img = Image.new("RGB", (4, 4), (0, 0, 0))
    img.putpixel((0, 0), (255, 255, 255))
    return img


def _data(img: Image.Image):
    return list(img.getdata())


@pytest.mark.unit
class TestOrientImage:
    """cat_images._orient_image applies flip/flop after the baseline rotate."""

    def test_flags_apply_the_right_transposes_after_baseline(self):
        src = _marker_image()
        # Baseline: 180 rotate only (no roll, no mirrors)
        base = cat_images._orient_image(src, 0, False, False)

        flipped = cat_images._orient_image(src, 0, True, False)
        flopped = cat_images._orient_image(src, 0, False, True)
        both = cat_images._orient_image(src, 0, True, True)

        # flip == top-to-bottom mirror of the baseline
        assert _data(flipped) == _data(base.transpose(Image.FLIP_TOP_BOTTOM))
        # flop == left-to-right mirror of the baseline
        assert _data(flopped) == _data(base.transpose(Image.FLIP_LEFT_RIGHT))
        # both == flip + flop of the baseline
        assert _data(both) == _data(
            base.transpose(Image.FLIP_TOP_BOTTOM).transpose(Image.FLIP_LEFT_RIGHT)
        )

    def test_each_combo_is_distinct(self):
        src = _marker_image()
        results = [
            _data(cat_images._orient_image(src, 0, flip, flop))
            for flip in (False, True)
            for flop in (False, True)
        ]
        # All four flag combinations move the marker to a different place.
        assert len({tuple(r) for r in results}) == 4
