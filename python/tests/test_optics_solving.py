"""End-to-end check that the derived FOV gate actually solves real frames.

Everything in test_optics.py is arithmetic. This module runs the arithmetic
through tetra3 against the frames in ``test_images/``, because the failure
mode being guarded against is not a wrong number -- it is a plausible-looking
number that silently stops every frame from solving.

Requires the tetra3 submodule and its bundled pattern database; skipped when a
worktree has not initialised it (see CLAUDE.md).
"""

import numpy as np
import pytest
from PIL import Image

from PiFinder import utils
from PiFinder.optics import LENSES, build_optical_train

pytestmark = pytest.mark.integration


# Both frames the debug camera cycles through that contain stars. empty.png is
# excluded: it is there to exercise the no-centroids path.
DEBUG_FRAMES = ("pifinder_debug_01.png", "pifinder_debug_02.png")

# What tetra3 fits these frames at, unconstrained. Recorded here so the
# expectations below are anchored to a measurement rather than to the same
# derivation they are testing.
MEASURED_DEBUG_FRAME_FOV = 10.2


@pytest.fixture(scope="module")
def tetra3_module():
    import sys

    database = utils.tetra3_dir / "data" / "default_database.npz"
    if not database.exists():
        pytest.skip(
            "tetra3 submodule not initialised: "
            "git submodule update --init python/PiFinder/tetra3"
        )
    sys.path.append(str(utils.tetra3_dir))
    import tetra3

    return tetra3


@pytest.fixture(scope="module")
def solver(tetra3_module):
    return tetra3_module.Tetra3(str(utils.tetra3_dir / "data" / "default_database.npz"))


@pytest.fixture(scope="module")
def debug_centroids(tetra3_module):
    centroids = {}
    for name in DEBUG_FRAMES:
        image = Image.open(utils.pifinder_dir / "test_images" / name).convert("L")
        centroids[name] = tetra3_module.get_centroids_from_image(
            np.asarray(image, dtype=np.uint8)
        )
    return centroids


def _solve(solver, centroids, train):
    fov_estimate, fov_max_error = train.solver_fov_params()
    return solver.solve_from_centroids(
        centroids,
        (512, 512),
        fov_estimate=fov_estimate,
        fov_max_error=fov_max_error,
        match_max_error=0.005,
    )


@pytest.mark.parametrize("frame", DEBUG_FRAMES)
def test_debug_frames_solve_with_the_declared_train(solver, debug_centroids, frame):
    """`--camera debug` must still solve after the sensor relabel.

    This is the check that would have caught the regression: with the debug
    camera declaring imx296, the gate is centred on 13.71 degrees and no debug
    frame solves at all.
    """
    solution = _solve(solver, debug_centroids[frame], build_optical_train("hq"))
    assert solution.get("RA") is not None, f"{frame} failed to solve"


@pytest.mark.parametrize("frame", DEBUG_FRAMES)
def test_fitted_fov_agrees_with_the_derived_one(solver, debug_centroids, frame):
    """The gate is centred close to what tetra3 independently measures.

    Comparing the fitted FOV against the derived one is how a mis-stated lens
    would be diagnosed, so the two need to actually agree on a correct setup.
    """
    solution = _solve(solver, debug_centroids[frame], build_optical_train("hq"))
    fitted = solution["FOV"]
    derived = build_optical_train("hq").fov_degrees

    assert fitted == pytest.approx(MEASURED_DEBUG_FRAME_FOV, abs=0.1)
    # Well inside the +/-15% gate, with room to spare for lens-sample spread.
    assert abs(fitted - derived) / derived < 0.05


@pytest.mark.parametrize("frame", DEBUG_FRAMES)
def test_a_mis_stated_train_rejects_a_perfectly_good_frame(
    solver, debug_centroids, frame
):
    """Documents the deliberate no-recovery consequence of ADR 0027.

    The centroids here are the same ones that solve above. Naming the wrong
    optical train discards them before verification, and nothing detects or
    corrects it -- which is exactly why the lens setting has to be right and
    why this presents as an exposure problem in the UI.
    """
    solution = _solve(solver, debug_centroids[frame], build_optical_train("imx296"))
    assert solution.get("RA") is None


# Every lens a config can name. The debug camera's sensor is fixed at hq, so
# these are exactly the trains `--camera debug` can find itself resolving --
# and only one of them is the one the frames were shot through.
STATEABLE_LENSES = tuple(LENSES)


def _solve_without_a_gate(solver, centroids):
    """What the solver does under an **unknown optical train**.

    Mirrors `solver.py`'s branch rather than re-deriving anything: when the
    frames did not come through this device's optics there is nothing to
    derive a gate from, so `fov_estimate`/`fov_max_error` are not passed.
    """
    return solver.solve_from_centroids(
        centroids,
        (512, 512),
        match_max_error=0.005,
    )


@pytest.mark.parametrize("frame", DEBUG_FRAMES)
@pytest.mark.parametrize("lens_key", STATEABLE_LENSES)
def test_a_stated_lens_gates_out_the_debug_frames(
    solver, debug_centroids, frame, lens_key
):
    """The regression itself, asserted rather than described.

    ADR 0027 fixed the debug camera's *sensor* and left its lens reading live
    from config, so stating one pairs hq with glass that is not in the loop:
    16mm implies 17.12 deg and 12mm 20.43, against 10.2 deg frames. Only the
    25mm -- the lens these frames were actually shot through -- still solves,
    which is precisely why nobody noticed until a config stated something.
    """
    train = build_optical_train("hq", lens_key)
    solution = _solve(solver, debug_centroids[frame], train)

    if lens_key == "25mm":
        assert solution.get("RA") is not None
    else:
        assert solution.get("RA") is None, (
            f"{lens_key} on hq derives {train.fov_degrees:.2f} deg; "
            f"if this now solves the gate is no longer doing its job"
        )


@pytest.mark.parametrize("frame", DEBUG_FRAMES)
@pytest.mark.parametrize("lens_key", STATEABLE_LENSES)
def test_no_gate_solves_the_debug_frames_whatever_config_states(
    solver, debug_centroids, frame, lens_key
):
    """The fix: `--camera debug` works on any config, including yours.

    The lens is parametrised but unused by the solve on purpose -- that is
    the property under test. Under an unknown optical train the config's lens
    cannot reach the solver at all, so every one of these has to pass.
    """
    solution = _solve_without_a_gate(solver, debug_centroids[frame])

    assert solution.get("RA") is not None, f"failed to solve with {lens_key} stated"
    assert solution["FOV"] == pytest.approx(MEASURED_DEBUG_FRAME_FOV, abs=0.1)


@pytest.mark.parametrize("frame", DEBUG_FRAMES)
def test_dropping_in_frames_from_another_train_still_solves(
    solver, debug_centroids, frame
):
    """Why no gate, rather than the camera declaring the frames' own FOV.

    A developer replacing test_images/ with frames off their own device is
    the main use of debug mode. Any declared gate -- including one centred on
    10.2 deg -- would reject those, which is the bug we are fixing wearing a
    different hat. Asserted here with the imx296/12mm gate (16.38 deg) as the
    stand-in for "a train nobody anticipated": it rejects these frames, and
    no-gate does not.
    """
    foreign = build_optical_train("imx296", "12mm")
    assert _solve(solver, debug_centroids[frame], foreign).get("RA") is None
    assert _solve_without_a_gate(solver, debug_centroids[frame]).get("RA") is not None
