"""The per-telescope target pixel reaches the solver, and every save lands
on the active telescope.

``test_target_pixel_per_telescope.py`` covers the record and the Config
resolver.  This file covers the wiring around them -- each piece is one line
in production code, and removing any of them leaves the resolver tests green:

* selecting a telescope in the device menu pushes its point to shared state
  (the Telescope menu's ``post_callback``);
* ``SharedStateObj`` starts from the active telescope's point;
* solve-based alignment, the Align screen's reset key and daytime alignment
  all save through ``Config.save_target_pixel``;
* entering align mode starts from the active telescope's point, not from a
  star left over from an earlier alignment.

The web page's path (the ``reload_config`` handler in ``main.py``) sits
inside ``main()``'s event loop and is not reachable from a unit test.
"""

import json
import queue
from types import SimpleNamespace
from unittest import mock

import pytest
from PIL import Image

# Installs the ``_()`` gettext builtin that PiFinder.ui modules rely on.
import PiFinder.i18n  # noqa: F401

from PiFinder import config
from PiFinder.displays import get_display
from PiFinder.state import SharedStateObj, UIState
from PiFinder.types.positioning import AlignedResult
from PiFinder.ui import align as align_module
from PiFinder.ui.align import UIAlign, align_on_radec
from PiFinder.ui.align_daytime import UIAlignDaytime
from PiFinder.ui.menu_manager import MenuManager, find_menu_by_label

GLOBAL_POINT = [310.0, 190.0]
POINT_A = [100.0, 400.0]


def telescope_dict(name, target_pixel=None):
    return {
        "make": "Generic",
        "name": name,
        "aperture_mm": 200,
        "focal_length_mm": 1000,
        "obstruction_perc": 17.0,
        "mount_type": "alt/az",
        "flip_image": False,
        "flop_image": False,
        "reverse_arrow_a": False,
        "reverse_arrow_b": False,
        "target_pixel": target_pixel,
    }


class _StubTimezoneFinder:
    """SharedStateObj builds a TimezoneFinder, which loads a multi-MB file."""

    def timezone_at(self, **_kwargs):
        return "UTC"


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    """Telescope A aligned, telescope B not, A active."""
    monkeypatch.setattr(config.utils, "data_dir", tmp_path)
    (tmp_path / "config.json").write_text(
        json.dumps(
            {
                "target_pixel": GLOBAL_POINT,
                "equipment": {
                    "telescopes": [
                        telescope_dict("A", POINT_A),
                        telescope_dict("B"),
                    ],
                    "eyepieces": [],
                    "active_telescope_index": 0,
                },
            }
        )
    )
    return config.Config()


@pytest.fixture
def shared_state(cfg, monkeypatch):
    monkeypatch.setattr(
        "PiFinder.state.timezonefinder",
        SimpleNamespace(TimezoneFinder=_StubTimezoneFinder),
    )
    state = SharedStateObj()
    state.set_ui_state(UIState())
    return state


def saved_point(cfg, index):
    on_disk = json.loads(cfg.config_file_path.read_text())
    return on_disk["equipment"]["telescopes"][index]["target_pixel"]


# ── reaching the solver ────────────────────────────────────────────


@pytest.mark.unit
def test_shared_state_starts_from_the_active_telescopes_point(shared_state):
    assert tuple(shared_state.target_pixel()) == tuple(POINT_A)


@pytest.mark.unit
def test_selecting_a_telescope_in_the_menu_moves_the_solver(cfg, shared_state):
    queues = {
        key: queue.Queue()
        for key in ("camera", "console", "ui_queue", "align_command")
        + ("align_response", "gps")
    }
    with mock.patch.object(MenuManager, "preload_modules", lambda self: None):
        menu_manager = MenuManager(
            get_display("headless"),
            Image.new("RGB", (512, 512)),
            shared_state,
            queues,
            cfg,
            mock.MagicMock(),
        )
    menu_manager.add_to_stack(find_menu_by_label("select_telescope"))
    telescope_menu = menu_manager.stack[-1]

    telescope_menu.key_down()
    telescope_menu.key_right()  # select B: not aligned, so the global point

    assert cfg.equipment.active_telescope.name == "B"
    assert tuple(shared_state.target_pixel()) == tuple(GLOBAL_POINT)

    telescope_menu.key_up()
    telescope_menu.key_right()  # back to A

    assert cfg.equipment.active_telescope.name == "A"
    assert tuple(shared_state.target_pixel()) == tuple(POINT_A)


# ── every save lands on the active telescope ───────────────────────


class _AlignResponses:
    """align_on_radec drains stale replies first, then polls for its own."""

    def __init__(self, reply):
        self._replies = [None, reply]  # None: the drain finds nothing

    def get(self, block=False):
        reply = self._replies.pop(0) if self._replies else None
        if reply is None:
            raise queue.Empty
        return reply


@pytest.mark.unit
def test_solve_based_alignment_saves_onto_the_active_telescope(cfg, shared_state):
    cfg.set_option("equipment.active_telescope", cfg.equipment.telescopes[1])
    queues = {
        "align_command": queue.Queue(),
        "console": queue.Queue(),
        "align_response": _AlignResponses(AlignedResult(y_target=50, x_target=60)),
    }

    assert align_on_radec(10.0, 20.0, queues, cfg, shared_state)

    assert saved_point(cfg, 1) == [50.0, 60.0]
    assert saved_point(cfg, 0) == POINT_A
    assert tuple(shared_state.target_pixel()) == (50.0, 60.0)


def _align_screen(cfg, shared_state):
    """Just the attributes UIAlign's key handlers touch; constructing the
    real screen needs the Hipparcos catalogue."""
    screen = SimpleNamespace(
        config_object=cfg,
        shared_state=shared_state,
        display_class=SimpleNamespace(resX=128, resY=128, centerX=64, centerY=64),
        align_mode=False,
        alignment_star=None,
        marker_position=(0, 0),
        update=lambda force=False: None,
    )
    screen._target_pixel_marker = lambda: UIAlign._target_pixel_marker(screen)
    return screen


@pytest.mark.unit
def test_the_align_reset_key_resets_the_active_telescope_only(cfg, shared_state):
    screen = _align_screen(cfg, shared_state)
    screen.align_mode = True

    UIAlign.key_number(screen, 1)

    assert saved_point(cfg, 0) == [256.0, 256.0]
    assert saved_point(cfg, 1) is None
    assert json.loads(cfg.config_file_path.read_text())["target_pixel"] == (
        GLOBAL_POINT
    )


@pytest.mark.unit
def test_daytime_alignment_saves_onto_the_active_telescope(cfg, shared_state):
    cfg.set_option("equipment.active_telescope", cfg.equipment.telescopes[1])
    screen = SimpleNamespace(
        selector=(32, 96),
        display_class=SimpleNamespace(resX=128, resY=128),
        shared_state=shared_state,
        config_object=cfg,
        started=True,
        message=lambda *args: None,
        remove_from_stack=None,
    )

    UIAlignDaytime._save_alignment(screen)

    # display (x=32, y=96) on a 128 panel -> native (Y, X) = (384, 128)
    assert saved_point(cfg, 1) == [384.0, 128.0]
    assert saved_point(cfg, 0) == POINT_A


# ── the Align screen follows the active telescope ──────────────────


@pytest.mark.unit
def test_align_mode_starts_from_the_active_telescope_not_an_old_star(
    cfg, shared_state, monkeypatch
):
    """The Align screen is preloaded once. A star picked in an earlier
    alignment would otherwise pull the marker back to it, and SQUARE would
    re-align on that star onto the telescope now active."""
    screen = _align_screen(cfg, shared_state)
    screen.alignment_star = {"ra_degrees": 1.0, "dec_degrees": 2.0}
    cfg.set_option("equipment.active_telescope", cfg.equipment.telescopes[1])

    UIAlign.key_square(screen)  # enter align mode

    assert screen.align_mode
    assert screen.alignment_star is None
    # B falls back to the global (Y, X) = (310, 190); display is (x, y) / 4
    assert screen.marker_position == (190.0 / 4, 310.0 / 4)

    # Leaving again without choosing a star must not align on anything.
    sent = []
    monkeypatch.setattr(align_module, "align_on_radec", lambda *a: sent.append(a))
    screen.message = lambda *args: None
    UIAlign.key_square(screen)

    assert sent == []
    assert saved_point(cfg, 1) is None
