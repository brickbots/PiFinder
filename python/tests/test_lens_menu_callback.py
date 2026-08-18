"""The Lens menu's value callback, which resolves both halves of the train.

``get_camera_lens`` is the one consumer that reaches the camera profile
without going through ``OpticalTrainResolver``, so it needs the same tolerance
the resolver has: it runs while the menu is being built, and raising there
leaves the user with a menu that cannot be opened -- on exactly the screen
they would go to in order to fix a camera problem.
"""

from types import SimpleNamespace

import pytest

# Installs the ``_()`` gettext builtin that PiFinder.ui modules rely on.
import PiFinder.i18n  # noqa: F401

from PiFinder.ui import callbacks


def _ui_module(camera_type, lens_key):
    return SimpleNamespace(
        shared_state=SimpleNamespace(camera_type=lambda: camera_type),
        config_object=SimpleNamespace(get_option=lambda _key: lens_key),
    )


@pytest.mark.unit
class TestGetCameraLens:
    def test_shows_the_configured_lens(self):
        assert callbacks.get_camera_lens(_ui_module("imx296", "12mm")) == ["12mm"]

    def test_shows_the_shipped_lens_when_nothing_is_configured(self):
        # An install predating the setting: which lens that means depends on
        # the detected sensor, so the menu must resolve rather than guess.
        assert callbacks.get_camera_lens(_ui_module("hq", None)) == ["25mm"]

    def test_an_unknown_sensor_still_opens_the_menu(self):
        assert callbacks.get_camera_lens(_ui_module("none", None)) == ["16mm"]

    def test_an_unknown_sensor_still_honours_a_configured_lens(self):
        assert callbacks.get_camera_lens(_ui_module("none", "12mm")) == ["12mm"]
