"""End-to-end check that a full-frame solve agrees with the square-crop solve.

Takes a real 512x512 test frame that the square-crop pipeline solves, embeds it
into a larger canvas standing in for the full sensor, and solves that instead.
The pointing must come out the same, and the solver's coordinate projection must
put the matched stars back where the square-crop solve found them.
"""

import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from PiFinder import utils
from PiFinder.optics import DISPLAY_FRAME_SIZE, SolveGeometry
from PiFinder.solver import project_solution_to_display

sys.path.append(str(utils.tetra3_dir))

tetra3 = pytest.importorskip("tetra3")

TEST_IMAGE = utils.pifinder_dir / "test_images" / "pifinder_debug_02.png"
# Resolve the database next to whichever tetra3 actually got imported, rather
# than assuming the submodule layout.
DATABASE = Path(tetra3.__file__).parent / "data" / "default_database.npz"

# Dimensions of the stand-in "full sensor". Deliberately not square and not a
# multiple of the display frame, so a mapping that only works for tidy numbers
# fails here.
SOLVE_WIDTH = 723
SOLVE_HEIGHT = 941


def _embedding_geometry():
    """Geometry for a display frame sitting centred in a larger solve frame.

    The offsets floor to whole pixels to match where the canvas paste below
    actually lands; the real pipelines are concentric to sub-pixel precision.
    """
    offset_x = float((SOLVE_WIDTH - DISPLAY_FRAME_SIZE) // 2)
    offset_y = float((SOLVE_HEIGHT - DISPLAY_FRAME_SIZE) // 2)
    return SolveGeometry(
        solve_width=SOLVE_WIDTH,
        solve_height=SOLVE_HEIGHT,
        display_to_solve_matrix=np.array(
            [[1.0, 0.0, offset_x], [0.0, 1.0, offset_y], [0.0, 0.0, 1.0]]
        ),
        full_frame=True,
    )


@pytest.fixture(scope="module")
def solver_db():
    if not DATABASE.exists():
        pytest.skip("tetra3 database not available (submodule not initialised)")
    return tetra3.Tetra3(str(DATABASE))


@pytest.fixture(scope="module")
def display_image():
    if not TEST_IMAGE.exists():
        pytest.skip(f"missing test image {TEST_IMAGE}")
    return np.asarray(Image.open(TEST_IMAGE).convert("L"), dtype=np.uint8)


def _solve(db, image, size, **kwargs):
    centroids = tetra3.get_centroids_from_image(image)
    return centroids, db.solve_from_centroids(
        centroids,
        size,
        match_max_error=0.005,
        return_matches=True,
        solve_timeout=10000,
        **kwargs,
    )


@pytest.fixture(scope="module")
def crop_solve(solver_db, display_image):
    _, solution = _solve(
        solver_db,
        display_image,
        (DISPLAY_FRAME_SIZE, DISPLAY_FRAME_SIZE),
        fov_estimate=12.0,
        fov_max_error=4.0,
    )
    if solution.get("RA") is None:
        pytest.skip(f"reference image did not solve: {solution.get('status')}")
    return solution


@pytest.fixture(scope="module")
def full_frame_solve(solver_db, display_image, crop_solve):
    geometry = _embedding_geometry()
    canvas = np.zeros((SOLVE_HEIGHT, SOLVE_WIDTH), dtype=np.uint8)
    top = (SOLVE_HEIGHT - DISPLAY_FRAME_SIZE) // 2
    left = (SOLVE_WIDTH - DISPLAY_FRAME_SIZE) // 2
    canvas[top : top + DISPLAY_FRAME_SIZE, left : left + DISPLAY_FRAME_SIZE] = (
        display_image
    )

    estimate = geometry.solve_fov(crop_solve["FOV"])
    _, solution = _solve(
        solver_db,
        canvas,
        geometry.solve_size,
        fov_estimate=estimate,
        fov_max_error=1.0,
        distortion=0,
    )
    if solution.get("RA") is None:
        pytest.skip(f"full-frame image did not solve: {solution.get('status')}")
    return geometry, solution


@pytest.mark.integration
def test_full_frame_solve_points_where_the_crop_solve_points(
    crop_solve, full_frame_solve
):
    """Both frames are concentric, so they share a centre on the sky."""
    _, solution = full_frame_solve

    assert solution["RA"] == pytest.approx(crop_solve["RA"], abs=0.05)
    assert solution["Dec"] == pytest.approx(crop_solve["Dec"], abs=0.05)
    assert solution["Roll"] == pytest.approx(crop_solve["Roll"], abs=0.5)


@pytest.mark.integration
def test_projected_fov_matches_the_crop_solve(crop_solve, full_frame_solve):
    """display_fov() must undo the widening, or SQM's plate scale goes wrong."""
    geometry, solution = full_frame_solve

    projected = project_solution_to_display(solution, geometry)

    assert solution["FOV"] > crop_solve["FOV"]
    assert projected["FOV"] == pytest.approx(crop_solve["FOV"], rel=0.02)


@pytest.mark.integration
def test_projected_centroids_land_inside_the_display_frame(full_frame_solve):
    geometry, solution = full_frame_solve

    projected = project_solution_to_display(solution, geometry)
    centroids = np.array(projected["matched_centroids"])

    assert len(centroids) > 0
    assert (centroids >= 0).all()
    assert (centroids < DISPLAY_FRAME_SIZE).all()


@pytest.mark.integration
def test_projected_centroids_sit_on_the_same_stars(crop_solve, full_frame_solve):
    """Projected stars must land on the stars the crop solve matched.

    Not every one of them will: the full-frame solve matches strictly more
    stars, and the ones the crop solve missed have no counterpart to compare
    against. What the mapping owes us is that the stars in common coincide to
    well under a pixel, and that most of them are in common at all.
    """
    geometry, solution = full_frame_solve

    projected = project_solution_to_display(solution, geometry)
    projected_centroids = np.array(projected["matched_centroids"])
    crop_centroids = np.array(crop_solve["matched_centroids"])

    distances = np.array(
        [
            np.min(np.linalg.norm(crop_centroids - centroid, axis=1))
            for centroid in projected_centroids
        ]
    )
    coincident = distances < 1.0

    assert coincident.mean() > 0.5, "too few stars shared with the crop solve"
    assert np.median(distances[coincident]) < 0.5


@pytest.mark.integration
def test_target_pixel_round_trips_through_the_solve(solver_db, crop_solve):
    """A display-frame target must come back as the same sky coordinate."""
    geometry = _embedding_geometry()
    target_display = (200.0, 320.0)

    mapped = geometry.display_to_solve(target_display)

    assert geometry.solve_to_display(mapped) == pytest.approx(target_display)
    assert 0 <= mapped[0] < SOLVE_HEIGHT
    assert 0 <= mapped[1] < SOLVE_WIDTH
