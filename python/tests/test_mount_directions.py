"""Direction keys: from the eyepiece view (or a compass) to a sky move."""

import math
from queue import Queue
from unittest.mock import Mock

import pytest

from PiFinder.cat_images import cardinal_vectors
from PiFinder.mount_settings import MountSettings
from PiFinder.mountcontrol_indi import MountControlIndi
from PiFinder.state import SharedStateObj
from PiFinder.ui.mount_page import ARROW_KEYS, compass_letter, sky_directions

pytestmark = pytest.mark.unit


def _approx(moves):
    return {k: pytest.approx(v, abs=1e-9) for k, v in moves.items()}


def test_compass_is_north_up_east_left():
    moves = sky_directions("compass", 37.0, True, True)
    assert moves == _approx({8: (1, 0), 2: (-1, 0), 4: (0, 1), 6: (0, -1)})
    letters = {k: compass_letter(*v) for k, v in moves.items()}
    assert letters == {8: "N", 2: "S", 4: "E", 6: "W"}


def test_eyepiece_without_a_solve_falls_back_to_compass():
    assert sky_directions("eyepiece", None, False, False) == sky_directions(
        "compass", None, False, False
    )


def test_eyepiece_roll_zero_is_the_inverted_view():
    """With roll 0 the view is turned 180° (a Newtonian): south at the top."""
    moves = sky_directions("eyepiece", 0.0, False, False)
    assert moves == _approx({8: (-1, 0), 2: (1, 0), 4: (0, -1), 6: (0, 1)})


def test_flop_swaps_east_and_west():
    plain = sky_directions("eyepiece", 0.0, False, False)
    flopped = sky_directions("eyepiece", 0.0, False, True)
    assert flopped[4] == pytest.approx((plain[4][0], -plain[4][1]), abs=1e-9)
    assert flopped[8] == pytest.approx(plain[8], abs=1e-9)


@pytest.mark.parametrize("roll", [0.0, 30.0, 90.0, 217.0])
@pytest.mark.parametrize("flip", [False, True])
@pytest.mark.parametrize("flop", [False, True])
def test_each_key_moves_to_what_the_view_shows_in_that_direction(roll, flip, flop):
    """The sky direction of a key, drawn with the N and E vectors of the
    POSS image, points the same way as the key on the screen."""
    n, e = cardinal_vectors(180.0 + roll, -1 if flop else 1, -1 if flip else 1)
    for key, (north, east) in sky_directions("eyepiece", roll, flip, flop).items():
        screen = (north * n[0] + east * e[0], north * n[1] + east * e[1])
        assert screen == pytest.approx(ARROW_KEYS[key], abs=1e-9)
        assert math.hypot(north, east) == pytest.approx(1.0)


def test_mount_moves_by_one_step_in_the_sky_direction():
    mount = MountControlIndi(
        Queue(), Queue(), Mock(spec=SharedStateObj), None, MountSettings(True, "x")
    )
    mount.current_ra, mount.current_dec = 100.0, 60.0
    mount._goto = Mock(return_value=True)
    assert mount.move_mount_offset(1.0, 0.0, 0.5)
    mount._goto.assert_called_with(pytest.approx(100.0), pytest.approx(60.5))
    # East at Dec 60: the RA step is twice the sky step.
    assert mount.move_mount_offset(0.0, 1.0, 0.5)
    mount._goto.assert_called_with(pytest.approx(101.0), pytest.approx(60.0))
    mount.current_ra = None
    assert not mount.move_mount_offset(1.0, 0.0, 0.5)
