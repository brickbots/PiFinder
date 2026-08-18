"""The Lens menu's callbacks, which resolve and apply both halves of the train.

``get_camera_lens`` is the one consumer that reaches the camera profile
without going through ``OpticalTrainResolver``, so it needs the same tolerance
the resolver has: it runs while the menu is being built, and raising there
leaves the user with a menu that cannot be opened -- on exactly the screen
they would go to in order to fix a camera problem. It reads both halves from
``shared_state`` rather than config, because self-heal writes the lens from
another process and this one's ``Config`` is loaded at boot.

``set_camera_lens`` must restart. Everything that reads the lens live picks a
change up on the next frame, but tetra3's ``_pattern_cache`` stores
FOV-*pruned* results under a key that does not mention the FOV gate and is
never invalidated, so entries pruned for the old lens survive the change and
can withhold the patterns the new one needs.
"""

from types import SimpleNamespace

import pytest

# Installs the ``_()`` gettext builtin that PiFinder.ui modules rely on.
import PiFinder.i18n  # noqa: F401

from PiFinder.ui import callbacks


_UNSET = object()


def _ui_module(camera_type, lens_key, config_lens=_UNSET):
    """A UI module whose two views of the lens can be made to disagree.

    ``config_lens`` defaults to matching shared state, which is the ordinary
    case. Passing it separately models the window after self-heal has written
    a lens from the integrator and this process's ``Config`` has not been
    reloaded.
    """
    stale = lens_key if config_lens is _UNSET else config_lens
    return SimpleNamespace(
        shared_state=SimpleNamespace(
            camera_type=lambda: camera_type,
            camera_lens=lambda: lens_key,
        ),
        config_object=SimpleNamespace(get_option=lambda _key: stale),
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

    def test_shows_the_self_healed_lens_not_this_process_stale_config(self):
        """The regression guard, and the reason this reads shared state.

        Self-heal writes ``camera_lens`` from the integrator. The UI process
        loaded its ``Config`` at boot and reloads it only on an explicit
        ``reload_config``, so ``config_object`` still reports the *assumed*
        16mm on a rev4 that has just measured itself as a 12mm. Showing that
        would put the wrong lens on the one screen that says which lens is
        fitted -- and ``text_menu`` writes the highlighted entry on select, so
        confirming it would state a lens the device measured itself out of and
        stop solving for good.
        """
        healed = _ui_module("imx462", "12mm", config_lens=None)

        assert callbacks.get_camera_lens(healed) == ["12mm"]


def _applying_ui_module(lens_key):
    """A UI module that records what the callback did to it."""
    published: list = []
    messages: list = []
    return SimpleNamespace(
        config_object=SimpleNamespace(get_option=lambda _key: lens_key),
        shared_state=SimpleNamespace(set_camera_lens=published.append),
        message=lambda text, _timeout=None: messages.append(text),
        published=published,
        messages=messages,
    )


@pytest.mark.unit
class TestSetCameraLens:
    @pytest.fixture
    def restarts(self, monkeypatch):
        calls: list = []
        monkeypatch.setattr(
            callbacks.sys_utils, "restart_pifinder", lambda: calls.append("restart")
        )
        return calls

    def test_restarts_so_the_solver_drops_its_pattern_cache(self, restarts):
        # The regression guard. tetra3 prunes the pattern catalog by FOV gate
        # inside a cache keyed only on the pattern hash, and never invalidates
        # it -- so without a restart a lens change can silently fail to take.
        callbacks.set_camera_lens(_applying_ui_module("12mm"))

        assert restarts == ["restart"]

    def test_publishes_the_new_lens_before_restarting(self, restarts):
        # Kept ahead of the restart so the change still lands when the restart
        # is a no-op, as it is under sys_utils_fake on a dev machine.
        ui_module = _applying_ui_module("12mm")

        callbacks.set_camera_lens(ui_module)

        assert ui_module.published == ["12mm"]

    def test_publishes_none_when_no_lens_is_configured(self, restarts):
        # Reachable only by a hand-edited config; None means "assumed", which
        # the solver's resolvers handle, so it must not be coerced to a key.
        ui_module = _applying_ui_module(None)

        callbacks.set_camera_lens(ui_module)

        assert ui_module.published == [None]
        assert restarts == ["restart"]
