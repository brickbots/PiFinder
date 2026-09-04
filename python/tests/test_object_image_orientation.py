"""Sky-orientation contract shared by POSS images and Gaia charts."""

from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image, ImageDraw

from PiFinder.object_images.gaia_chart import GaiaChartGenerator
from PiFinder.object_images.image_utils import eyepiece_image_rotation
from PiFinder.object_images.poss_provider import POSSImageProvider


RESOLUTION = (100, 100)
CENTER_RA = 120.0
CENTER_DEC = 0.0
FOV_DEG = 1.0
SKY_OFFSET_DEG = 0.25


def _marker_position(image):
    red = np.asarray(image)[:, :, 0]
    ys, xs = np.nonzero(red)
    assert len(xs), "orientation marker was lost during rendering"
    weights = red[ys, xs].astype(float)
    return np.average(xs, weights=weights), np.average(ys, weights=weights)


def _sky_coordinate(direction):
    if direction == "north":
        return CENTER_RA, CENTER_DEC + SKY_OFFSET_DEG
    return CENTER_RA + SKY_OFFSET_DEG, CENTER_DEC


def _render_gaia_marker(direction, roll, flip, flop, eyepiece_baseline=True):
    ra, dec = _sky_coordinate(direction)
    stars = np.array([[ra, dec, 1.0]])
    generator = GaiaChartGenerator.__new__(GaiaChartGenerator)
    return generator.render_chart(
        stars,
        CENTER_RA,
        CENTER_DEC,
        FOV_DEG,
        RESOLUTION,
        rotation=eyepiece_image_rotation(roll) if eyepiece_baseline else roll,
        flip_image=flip,
        flop_image=flop,
    )


def _render_poss_marker(monkeypatch, direction, roll, flip, flop, obstruction):
    # A survey plate is North-up/East-left before telescope transforms.
    source = Image.new("RGB", (1024, 1024))
    offset = round(1024 * SKY_OFFSET_DEG / FOV_DEG)
    cx = cy = 512
    if direction == "north":
        marker_center = (cx, cy - offset)
    else:
        marker_center = (cx - offset, cy)
    draw = ImageDraw.Draw(source)
    x, y = marker_center
    draw.rectangle((x - 3, y - 3, x + 3, y + 3), fill="white")

    monkeypatch.setattr(
        "PiFinder.object_images.poss_provider.Image.open",
        lambda _path: source.copy(),
    )
    provider = POSSImageProvider()
    monkeypatch.setattr(provider, "_resolve_image_name", lambda *_args, **_kwargs: "x")

    telescope = SimpleNamespace(
        obstruction_perc=obstruction,
        flip_image=flip,
        flop_image=flop,
    )
    config = SimpleNamespace(
        equipment=SimpleNamespace(active_telescope=telescope),
    )
    display = SimpleNamespace(
        fov_res=RESOLUTION[0],
        resX=RESOLUTION[0],
        resY=RESOLUTION[1],
        colors=SimpleNamespace(
            red_image=Image.new("RGB", RESOLUTION, (255, 0, 0)),
        ),
    )
    catalog_object = SimpleNamespace(catalog_code="T", sequence="1", names=[])
    return provider.get_image(
        catalog_object,
        "test",
        FOV_DEG,
        roll,
        display,
        burn_in=False,
        config_object=config,
    )


@pytest.mark.unit
@pytest.mark.parametrize("direction", ["north", "east"])
@pytest.mark.parametrize("roll", [0.0, 37.0, 90.0, 180.0, 270.0])
@pytest.mark.parametrize("obstruction", [0.0, 17.0])
@pytest.mark.parametrize(
    ("flip", "flop"),
    [(False, False), (True, False), (False, True), (True, True)],
)
def test_gaia_and_poss_share_sky_orientation(
    monkeypatch, direction, roll, obstruction, flip, flop
):
    """The generated chart must put sky directions where a survey plate does."""
    gaia = _render_gaia_marker(direction, roll, flip, flop)
    poss = _render_poss_marker(monkeypatch, direction, roll, flip, flop, obstruction)

    gaia_x, gaia_y = _marker_position(gaia)
    poss_x, poss_y = _marker_position(poss)
    assert gaia_x == pytest.approx(poss_x, abs=1.5)
    assert gaia_y == pytest.approx(poss_y, abs=1.5)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("roll", "north_quadrant", "east_quadrant"),
    [
        (0.0, "up", "left"),
        (90.0, "left", "down"),
        (180.0, "down", "right"),
        (270.0, "right", "up"),
    ],
)
def test_positive_roll_follows_the_plate_solve_definition(
    roll, north_quadrant, east_quadrant
):
    """Positive roll turns celestial North counter-clockwise from image up."""
    expected_signs = {
        "up": (0, -1),
        "down": (0, 1),
        "left": (-1, 0),
        "right": (1, 0),
    }
    center_x, center_y = (size / 2 for size in RESOLUTION)

    positions = {}
    for direction in ("north", "east"):
        image = _render_gaia_marker(
            direction, roll, False, False, eyepiece_baseline=False
        )
        x, y = _marker_position(image)
        dx = int(np.sign(x - center_x))
        dy = int(np.sign(y - center_y))
        positions[direction] = (dx, dy)

    assert positions["north"] == expected_signs[north_quadrant]
    assert positions["east"] == expected_signs[east_quadrant]
