"""
Crash-only smoke harness for the PiFinder UI modules.

Goal: instantiate every on-device screen and exercise every ``key_*`` method
(plus ``update`` / display-mode cycling). A case passes if nothing raises --
there is *no* assertion about rendered pixels. This is a broad safety net for
import / construction / key-handler regressions across all UI modules, built
with as little mocking as possible.

How it works (see ``docs/ax/ui.md`` section 9 for the construction recipe):

* Discovery walks the real ``menu_structure.pifinder_menu`` tree and yields a
  case for *every node that carries a "class" key* -- so each distinct
  ``item_definition`` (all the ``UITextMenu`` menus, every ``UIObjectList``
  source, ...) is exercised with its real config. An explicit list of fixtures
  covers the modules that are only pushed dynamically at runtime
  (``UIObjectDetails``, ``UILog``, ``UIDateEntry``, the SQM tools).
* Construction goes through a real ``MenuManager`` with real dependencies: a
  headless display, a directly-instantiated ``SharedStateObj`` (+ ``UIState``),
  a real ``Config`` and a real ``Catalogs`` built from the bundled DB.
* Each module is exercised twice -- ``cold`` (fresh shared state) and ``warm``
  (a representative ``PointingEstimate`` from a camera solve, published via
  ``set_solution``) -- to cover the "no solve yet" and "solved"
  branches modules guard on.
* Because the real ``add_to_stack`` callback is wired in, modules a handler
  pushes onto the stack as a side effect get swept too (bounded).

Mocking is confined to narrow off-device / hardware boundaries, each in its own
autouse session fixture:
  * ``sys_utils`` -> inert mock. It is the OS/hardware action layer (shutdown,
    restart_system, switch_cam_*, wifi switches); the key sweep selects menu
    items that fire these, which on a Pi would reboot/reconfigure the device.
  * ``UISoftware``'s live GitHub version fetch (``requests.get``).
  * ``/boot/config.txt`` read in ``callbacks.get_camera_type`` (Pi-only file).
  * the comet catalog's background network download during catalog build.
  * ``time.sleep`` -> no-op (the SQM wizards are per-update capture state
    machines that sleep on every frame; otherwise the sweep takes minutes).
All UI logic itself stays real. (``UIStatus``'s ``/sys`` read is already
``try/except``-guarded.) ``UIChart`` / ``UIAlign`` need ``hip_main.dat``,
which ships in the repo under ``astro_data/``; those cases skip
if it is ever missing.

Run from ``python/`` (paths in ``PiFinder.utils`` are relative to CWD):
    pytest -m integration tests/test_ui_modules.py
    nox -s ui_tests
"""

import builtins
import copy
import datetime
import importlib
import io
import pkgutil
import queue
import shutil
from typing import Iterator
from unittest import mock

import pytest
from PIL import Image

# Installs the ``_()`` gettext builtin that the UI modules and menu_structure
# rely on. MUST precede any ``PiFinder.ui`` import.
import PiFinder.i18n  # noqa: F401

import PiFinder.ui as ui_pkg
from PiFinder import utils
from PiFinder.catalogs import CatalogBuilder, CatalogFilter, Catalogs
from PiFinder.config import Config
from PiFinder.displays import get_display
from PiFinder.state import Location, SharedStateObj, UIState
from PiFinder.types.positioning import (
    Pointing,
    PointingAxis,
    PointingEstimate,
    PointingMatrix,
    SolveDiagnostics,
    SolveSource,
)
from PiFinder.ui import callbacks, menu_structure
from PiFinder.ui.base import UIModule
from PiFinder.ui.menu_manager import MenuManager

# Dynamic-only module classes (pushed at runtime, never as static tree nodes).
from PiFinder.ui.object_details import UIObjectDetails
from PiFinder.ui.log import UILog
from PiFinder.ui.dateentry import UIDateEntry
from PiFinder.ui.sqm_calibration import UISQMCalibration
from PiFinder.ui.sqm_sweep import UISQMSweep
from PiFinder.ui.software import UIMigrationConfirm, UIMigrationProgress


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

# command_queues keys main.py wires up; modules .put() onto these (no consumer)
_COMMAND_QUEUE_KEYS = (
    "camera",
    "console",
    "ui_queue",
    "align_command",
    "align_response",
    "gps",
)

# Modules that need the Hipparcos catalogue to construct (build plot.Starfield)
_HIP_REQUIRED = {"UIChart", "UIAlign"}

# Modules the generic sweep can't fairly exercise, with the reason. These are
# still constructed and covered by the completeness guard -- only the key sweep
# is skipped. UIAlign is a stateful alignment wizard: its update()/key handlers
# assume a live solve has populated self.solution and self.visible_stars via a
# prior successful starfield plot, which a generic isolated sweep
# can't provide. It warrants dedicated alignment-flow tests instead.
_SWEEP_SKIP: dict[str, str] = {
    "UIAlign": "needs a live solve + alignment-star sequence; "
    "cover via dedicated tests",
}

# UIModule subclasses that are intentionally *not* exercised, with the reason.
# Keeps the completeness guard (test_all_ui_modules_covered) honest.
_COVERAGE_SKIP: dict[str, str] = {
    "UIReleaseNotes": (
        "Pushed onto the stack by UISoftware's Notes action with a "
        "notes-payload item_definition; not reachable from the menu tree "
        "and needs live update-channel state to construct."
    ),
}

# Bound on the auto-sweep so a handler that keeps pushing modules
# can't run away.
_MAX_SWEEP_MODULES = 80


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #


def _iter_menu_nodes(node):
    """Yield every dict in the menu tree that carries a "class" key."""
    if isinstance(node, dict):
        if "class" in node:
            yield node
        for value in node.values():
            yield from _iter_menu_nodes(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_menu_nodes(item)


def _resolve_class_name(cls) -> str:
    """Real UIModule subclass name behind a menu node's "class".

    Some nodes reference a class wrapped by the ``@singleton`` decorator
    (``console.singleton``), whose ``__name__`` is ``getinstance``; the real
    class is captured in the closure. Unwrap it so ids and the coverage guard
    see the true subclass name.
    """
    if getattr(cls, "__name__", "") == "getinstance" and getattr(
        cls, "__closure__", None
    ):
        for cell in cls.__closure__:
            value = cell.cell_contents
            if isinstance(value, type) and issubclass(value, UIModule):
                return value.__name__
    return getattr(cls, "__name__", str(cls))


def _node_id(node) -> str:
    """A readable, hopefully-unique pytest id for a menu node."""
    cls = _resolve_class_name(node["class"])
    tag = node.get("label") or node.get("name") or "node"
    return f"{cls}-{tag}".replace(" ", "_").replace("/", "-")


_MENU_NODES = list(_iter_menu_nodes(menu_structure.pifinder_menu))
_MENU_IDS = [_node_id(n) for n in _MENU_NODES]

# Dynamic-only modules, parametrized by id; item_definition built at run time
# (some need a real catalog object).
_DYNAMIC_IDS = [
    "UIObjectDetails",
    "UILog",
    "UIDateEntry",
    "UISQMCalibration",
    "UISQMSweep",
    "UIMigrationConfirm",
    "UIMigrationProgress",
]


def _build_dynamic_item_definition(spec_id: str, sample_object) -> dict:
    """Return an item_definition modeled on each module's real launch site."""
    if spec_id == "UIObjectDetails":
        # object_list.py:748
        return {
            "name": getattr(sample_object, "display_name", "Object"),
            "class": UIObjectDetails,
            "object": sample_object,
            "object_list": [sample_object],
            "label": "object_details",
        }
    if spec_id == "UILog":
        # object_details.py:690
        return {"name": "LOG", "class": UILog, "object": sample_object}
    if spec_id == "UIDateEntry":
        # timeentry.py:194
        return {
            "name": "Set Date",
            "class": UIDateEntry,
            "time_str": "12:00:00",
            "custom_callback": callbacks.set_datetime,
        }
    if spec_id == "UISQMCalibration":
        # sqm.py:290
        return {
            "name": "SQM Calibration",
            "class": UISQMCalibration,
            "label": "sqm_calibration",
        }
    if spec_id == "UISQMSweep":
        # sqm.py:302
        return {"name": "SQM Sweep", "class": UISQMSweep, "label": "sqm_sweep"}
    if spec_id == "UIMigrationConfirm":
        # Pushed by UISoftware.key_square() after a 7x-square unlock.
        return {
            "name": "Confirm Migration",
            "class": UIMigrationConfirm,
            "version_info": {"version": "2.5.0"},
            "current_version": "2.4.0",
            "label": "migration_confirm",
        }
    if spec_id == "UIMigrationProgress":
        # Pushed by UIMigrationConfirm after the user confirms.
        return {
            "name": "Migration Progress",
            "class": UIMigrationProgress,
            "version_info": {"version": "2.5.0"},
            "label": "migration_progress",
        }
    raise KeyError(spec_id)  # pragma: no cover


def _all_uimodule_subclasses() -> set[str]:
    """Names of every UIModule subclass defined under PiFinder.ui."""
    for mod in pkgutil.iter_modules(ui_pkg.__path__):
        importlib.import_module(f"PiFinder.ui.{mod.name}")

    found: set[str] = set()

    def _recurse(cls):
        for sub in cls.__subclasses__():
            # Only classes that live in the UI package count — test helpers
            # subclassing UIModule elsewhere (e.g. test_battery_titlebar_icon's
            # _BareModule) must not trip the coverage guard.
            if sub.__module__.startswith("PiFinder.ui"):
                found.add(sub.__name__)
            _recurse(sub)

    _recurse(UIModule)
    return found


# --------------------------------------------------------------------------- #
# Session-scoped fixtures (heavy / read-only resources)
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="session", autouse=True)
def _require_data_files():
    """Skip the whole module if not run from python/
    (paths are CWD-relative)."""
    if not utils.pifinder_db.exists():
        pytest.skip(
            f"{utils.pifinder_db} not found -- run the UI harness from python/"
            " (astro_data paths are relative to CWD)."
        )


@pytest.fixture(scope="session", autouse=True)
def _sandbox_data_dir(tmp_path_factory):
    """Redirect user data dir to a temp dir so no test writes real settings.

    Copies the developer's config.json in (reads stay realistic) but points all
    writes -- config, observations DB, debug dumps -- at the sandbox.
    """
    sandbox = tmp_path_factory.mktemp("pifinder_data")
    (sandbox / "cache").mkdir(exist_ok=True)
    (sandbox / "screenshots").mkdir(exist_ok=True)
    (sandbox / "solver_debug_dumps").mkdir(exist_ok=True)

    real_config = utils.data_dir / "config.json"
    if real_config.exists():
        shutil.copy(real_config, sandbox / "config.json")

    with (
        mock.patch.object(utils, "data_dir", sandbox),
        mock.patch.object(utils, "observations_db", sandbox / "observations.db"),
        mock.patch.object(utils, "debug_dump_dir", sandbox / "solver_debug_dumps"),
    ):
        yield sandbox


class _StubTimezoneFinder:
    """Instant stand-in for timezonefinder.TimezoneFinder."""

    def timezone_at(self, **kwargs):
        return "UTC"


@pytest.fixture(scope="session", autouse=True)
def _fast_timezonefinder():
    """Stub TimezoneFinder so SharedStateObj construction is instant.

    SharedStateObj.__init__ builds a fresh TimezoneFinder (loads a multi-MB
    timezone binary), and the harness constructs a SharedStateObj per test
    (cold/warm). The real init is cheap-ish on a dev box but brutally slow
    on a CI runner -- hundreds of inits take ~10 min and look like a hang.
    Timezone resolution is irrelevant to UI crash-smoke,
    so a constant-"UTC" stub is fine.
    """
    with mock.patch("PiFinder.state.TimezoneFinder", _StubTimezoneFinder):
        yield


@pytest.fixture(scope="session", autouse=True)
def _fast_sleep():
    """No-op time.sleep for the whole harness.

    Several wizards (SQM calibration/sweep/correction) are per-update state
    machines that sleep 0.2-0.5s on every frame while driving the real camera.
    Driven by the key sweep with no camera process, those sleeps add up to
    minutes of pure wall-clock waiting. None of these modules busy-loop on a
    condition (no ``while``+sleep), so removing the waits is safe and changes
    no logic -- we only care that nothing raises.
    """
    with mock.patch("time.sleep", lambda *a, **k: None):
        yield


@pytest.fixture(scope="session", autouse=True)
def _no_network():
    """Stub UISoftware's live GitHub version check
    the one hard network call)."""
    fake = mock.Mock()
    fake.text = "1.0.0"
    fake.status_code = 200
    with mock.patch("PiFinder.ui.software.requests.get", return_value=fake):
        yield


@pytest.fixture(scope="session", autouse=True)
def _no_comet_download():
    """Stop the comet catalog from downloading over the network.

    CometCatalog.__init__ spawns a daemon thread that fetches the comet TSV
    via requests.get during CatalogBuilder.build().
    Stub the network function to report "no download" (success=False);
    the real catalog/threading logic stays intact
    and just loads no comets, keeping the suite hermetic.
    """
    import PiFinder.comets as comets

    with mock.patch.object(
        comets, "comet_data_download", return_value=(False, None, None)
    ):
        yield


@pytest.fixture(scope="session", autouse=True)
def _inert_sys_utils():
    """Neutralize the system-action boundary.

    sys_utils is the OS/hardware action layer: shutdown(), restart_system(),
    switch_cam_*(), go_wifi_*(), update_software(). The key sweep selects menu
    items, which fire these as real actions -- on a Pi this harness would
    reboot or reconfigure the device, and off-Pi sys_utils_fake is missing
    some of them (e.g. switch_cam_imx462).
    Replace it with an inert mock everywhere the UI imported it,
    so actions are safe no-ops while all UI logic stays real.
    """
    inert = mock.MagicMock(name="sys_utils")
    with (
        mock.patch.object(callbacks, "sys_utils", inert),
        mock.patch("PiFinder.ui.software.sys_utils", inert),
        mock.patch("PiFinder.ui.status.sys_utils", inert),
        mock.patch.object(utils, "get_sys_utils", lambda: inert),
    ):
        yield


@pytest.fixture(scope="session", autouse=True)
def _stub_pi_files():
    """Make the hardcoded /boot/config.txt read succeed off a Pi.

    callbacks.get_camera_type opens /boot/config.txt directly (not via the
    sys_utils_fake shim), and the menu dict captured the original function
    reference at import, so the read itself must be satisfied rather than the
    function patched. Delegate every other path to the real open.
    """
    real_open = builtins.open

    def fake_open(path, *args, **kwargs):
        if str(path) == "/boot/config.txt":
            return io.StringIO("dtoverlay=imx296\n")
        return real_open(path, *args, **kwargs)

    with mock.patch("builtins.open", side_effect=fake_open):
        yield


@pytest.fixture(scope="session", autouse=True)
def _no_preload():
    """Disable MenuManager's chart/align preload.

    Preloading constructs plot.Starfield (needs hip_main.dat) at *every*
    MenuManager construction, which would couple all cases to Hipparcos.
    With it off, chart/align are constructed on demand only when
    their own node is the case under test, and gated behind hip_main_available.
    """
    with mock.patch.object(MenuManager, "preload_modules", lambda self: None):
        yield


@pytest.fixture(scope="session")
def display():
    return get_display("headless")


@pytest.fixture(scope="session")
def camera_image():
    # UISQM / UIPreview call .copy() on this, so it must be a real image.
    return Image.new("RGB", (512, 512))


@pytest.fixture(scope="session")
def catalogs(_sandbox_data_dir, _no_comet_download) -> Iterator[Catalogs]:
    """Build the real catalogs once from the bundled DB.

    Teardown stops the perpetual catalog timers. The planet and comet catalogs
    run a self-rescheduling, *non-daemon* threading.Timer (via TimerMixin);
    left running they keep the interpreter alive at shutdown,
    so `nox -s ui_tests` would never exit.
    Stopping them on teardown lets the process end cleanly.
    """
    boot_state = SharedStateObj()
    boot_state.set_ui_state(UIState())
    built = CatalogBuilder().build(boot_state, queue.Queue())
    yield built

    for catalog in built.get_catalogs(only_selected=False):
        timer = getattr(catalog, "_timer", None)
        if timer is not None:
            timer.stop()
    loader = getattr(built, "_background_loader", None)
    if loader is not None:
        loader.stop()


@pytest.fixture(scope="session")
def sample_object(catalogs):
    """A real CompositeObject for the object_details / log fixtures."""
    objs = catalogs.get_objects(only_selected=False, filtered=False)
    if not objs:
        pytest.skip("no catalog objects available to build object fixtures")
    return objs[0]


@pytest.fixture(scope="session")
def hip_main_available() -> bool:
    """Whether the Hipparcos catalog is present (it ships in the repo).

    Kept as a defensive guard: if astro_data/hip_main.dat is ever missing,
    the chart/align cases skip instead of erroring.
    """
    return (utils.astro_data_dir / "hip_main.dat").exists()


# --------------------------------------------------------------------------- #
# Per-test construction + exercise helpers
# --------------------------------------------------------------------------- #


def _make_shared_state(state: str) -> SharedStateObj:
    shared_state = SharedStateObj()
    shared_state.set_ui_state(UIState())
    if state == "warm":
        location = Location()
        location.lat = 34.05
        location.lon = -118.24
        location.altitude = 100.0
        location.lock = True
        location.lock_type = 2
        location.source = "TEST"
        shared_state.set_location(location)
        shared_state.set_datetime(
            datetime.datetime(2024, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc),
            force=True,
        )
        now = shared_state.datetime().timestamp() if shared_state.datetime() else 0
        # A fresh camera plate-solve: both axes' solve and estimate cells are
        # populated together (no IMU progression yet, so estimate == solve),
        # and the eyepiece-aligned axis equals the camera axis
        # (no alignment offset).
        # Mirrors what the integrator produces from a SuccessfulSolve.
        direction = Pointing(RA=83.82, Dec=-5.39, Roll=0.0)
        solved = PointingEstimate(
            pointing=PointingMatrix(
                camera=PointingAxis(solve=direction, estimate=direction),
                aligned=PointingAxis(solve=direction, estimate=direction),
            ),
            # imu_anchor stays None: a CAM solve on a frame with no IMU sample.
            Alt=45.0,
            Az=120.0,
            solve_source=SolveSource.CAMERA,
            estimate_time=now,
            last_solve_success=now,
            constellation="Ori",
            # Solver diagnostics several screens read off a CAM solve.
            diagnostics=SolveDiagnostics(Matches=12, RMSE=0.5, FOV=10.2),
        )
        # set_solution derives solve_state from has_pointing() (True here).
        shared_state.set_solution(solved)
    return shared_state


def _make_command_queues() -> dict:
    return {key: queue.Queue() for key in _COMMAND_QUEUE_KEYS}


def _exercise_one(module: UIModule) -> None:
    """Run the full key sweep against a single module instance.

    Exceptions propagate -- that is the test's pass/fail signal.
    """
    module.active()
    module.update()

    for name in sorted(dir(module)):
        if not name.startswith("key_"):
            continue
        method = getattr(module, name)
        if not callable(method):
            continue
        if name == "key_number":
            for digit in range(10):
                method(digit)
                module.update()
        else:
            method()
            module.update()

    # Cycle through every display mode (key_square advances the cycle).
    for _mode in getattr(module, "_display_mode_list", [None]):
        module.key_square()
        module.update()

    module.inactive()


def _sweep_stack(menu_manager: MenuManager, seen: set) -> None:
    """Exercise every not-yet-seen module on the stack, repeatedly, bounded.

    Picks up modules pushed as a side effect of a key handler (the auto-sweep).
    """
    count = 0
    while count < _MAX_SWEEP_MODULES:
        pending = [m for m in menu_manager.stack if id(m) not in seen]
        if not pending:
            break
        for module in pending:
            seen.add(id(module))
            if type(module).__name__ in _SWEEP_SKIP:
                # Constructed via another module's navigation, but the generic
                # sweep can't fairly drive it (see _SWEEP_SKIP).
                continue
            _exercise_one(module)
            count += 1
            if count >= _MAX_SWEEP_MODULES:
                break


def _build_and_exercise(item_definition, state, display, camera_image, catalogs):
    """Construct a module through a real MenuManager and exercise it."""
    cfg = Config()
    shared_state = _make_shared_state(state)
    command_queues = _make_command_queues()

    # Reset the (session-shared) catalog filter onto this test's shared_state.
    catalog_filter = CatalogFilter(shared_state=shared_state)
    catalog_filter.load_from_config(cfg)
    catalogs.set_catalog_filter(catalog_filter)

    menu_manager = MenuManager(
        display, camera_image, shared_state, command_queues, cfg, catalogs
    )

    # Ignore whatever MenuManager pushed at construction (the root menu);
    # only exercise the module under test and anything it pushes.
    seen = {id(m) for m in menu_manager.stack}
    menu_manager.add_to_stack(copy.deepcopy(item_definition))
    _sweep_stack(menu_manager, seen)


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


@pytest.mark.integration
@pytest.mark.parametrize("state", ["cold", "warm"])
@pytest.mark.parametrize("node", _MENU_NODES, ids=_MENU_IDS)
def test_menu_node_module(
    node, state, display, camera_image, catalogs, hip_main_available
):
    """Every menu-tree node with a class constructs
    and survives a key sweep."""
    class_name = _resolve_class_name(node["class"])
    if class_name in _SWEEP_SKIP:
        pytest.skip(_SWEEP_SKIP[class_name])
    if class_name in _HIP_REQUIRED and not hip_main_available:
        pytest.skip("hip_main.dat unavailable (needed by chart/align)")
    _build_and_exercise(node, state, display, camera_image, catalogs)


@pytest.mark.integration
@pytest.mark.parametrize("state", ["cold", "warm"])
@pytest.mark.parametrize("spec_id", _DYNAMIC_IDS)
def test_dynamic_ui_module(
    spec_id, state, display, camera_image, catalogs, sample_object, hip_main_available
):
    """Dynamically-pushed modules construct and survive a key sweep."""
    item_definition = _build_dynamic_item_definition(spec_id, sample_object)
    if item_definition["class"].__name__ in _HIP_REQUIRED and not hip_main_available:
        pytest.skip("hip_main.dat unavailable (needed by chart/align)")
    _build_and_exercise(item_definition, state, display, camera_image, catalogs)


@pytest.mark.integration
def test_object_details_tracks_target(display, camera_image, catalogs):
    """UIObjectDetails mirrors the viewed object into ui_state.target().

    The chart's target cross reads ui_state.target(); UIObjectDetails is the
    single writer, setting it in update_object_info() so it tracks the
    last-viewed object on both open and scroll (see the "Target" term in
    docs/ax/ui/CONTEXT.md).
    """
    cfg = Config()
    shared_state = _make_shared_state("warm")
    command_queues = _make_command_queues()
    catalog_filter = CatalogFilter(shared_state=shared_state)
    catalog_filter.load_from_config(cfg)
    catalogs.set_catalog_filter(catalog_filter)

    # Two catalog objects with distinct object_ids (scroll_object indexes by
    # equality, which is object_id-based).
    objs = catalogs.get_objects(only_selected=False, filtered=False)
    obj_a = objs[0]
    obj_b = next((o for o in objs if o.object_id != obj_a.object_id), None)
    if obj_b is None:
        pytest.skip("need two distinct catalog objects for the scroll assertion")

    item_definition = {
        "name": getattr(obj_a, "display_name", "Object"),
        "class": UIObjectDetails,
        "object": obj_a,
        "object_list": [obj_a, obj_b],
        "label": "object_details",
    }
    module = UIObjectDetails(
        display,
        camera_image,
        shared_state,
        command_queues,
        cfg,
        catalogs,
        item_definition=item_definition,
    )

    # Set on open (update_object_info runs in __init__)...
    assert shared_state.ui_state().target() is obj_a
    # ...and updated on scroll.
    module.scroll_object(1)
    assert shared_state.ui_state().target() is obj_b


@pytest.mark.integration
def test_all_ui_modules_covered():
    """Fail if a UIModule subclass is reached by neither discovery path.

    Guards against a newly-added screen silently escaping smoke coverage.
    Known, deliberate exceptions live in _COVERAGE_SKIP
    with a documented reason.
    """
    covered = {_resolve_class_name(node["class"]) for node in _MENU_NODES}
    covered |= set(_DYNAMIC_IDS)

    defined = _all_uimodule_subclasses()
    uncovered = defined - covered - set(_COVERAGE_SKIP)

    assert not uncovered, (
        "UIModule subclasses with no smoke coverage: "
        f"{sorted(uncovered)}. Wire them into the menu tree, add a fixture"
        " to _DYNAMIC_IDS, or document an exception in _COVERAGE_SKIP."
    )
