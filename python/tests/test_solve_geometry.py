"""Tests for solve-frame geometry and optical calibration."""

import math

import numpy as np
import pytest
from PIL import Image

from PiFinder.solve_geometry import (
    CALIBRATED_FOV_MAX_ERROR,
    DISPLAY_FRAME_SIZE,
    FAILURES_BEFORE_RECALIBRATION,
    OpticalCalibration,
    SolveGeometry,
    build_geometry,
    identity_geometry,
    max_solve_frame_size,
)
from PiFinder.camera_profiles import CAMERA_PROFILES

SENSOR_PROFILES = ["imx296", "imx462", "imx290", "hq"]
ROTATIONS = [90, 270]


# The display path downscales the sensor by up to 3x, so a single-pixel marker
# can be dropped entirely. Use a block wide enough to survive, and locate it by
# centroid so the two pipelines' different resampling cancels out.
MARKER_HALF_WIDTH = 16


def _marker_raw(profile, marker_yx):
    """A raw sensor frame that is zero except for one bright square."""
    width, height = profile.raw_size
    raw = np.zeros((height, width), dtype=np.uint16)
    y, x = marker_yx
    raw[
        y - MARKER_HALF_WIDTH : y + MARKER_HALF_WIDTH,
        x - MARKER_HALF_WIDTH : x + MARKER_HALF_WIDTH,
    ] = 4095
    return raw


def _marker_centre(array):
    """The (y, x) centroid of the bright marker in an array."""
    lit = np.argwhere(array > array.max() / 2)
    assert len(lit), "marker did not survive the pipeline"
    return tuple(lit.mean(axis=0))


def _run_display_pipeline(profile, raw, rotation):
    """Reproduce the camera's display path: crop, rot90, resize, rotate."""
    cropped = profile.crop_and_rotate(raw)
    image = Image.fromarray(np.asarray(cropped >> 4, dtype=np.uint8))
    image = image.resize((DISPLAY_FRAME_SIZE, DISPLAY_FRAME_SIZE), Image.NEAREST)
    return np.asarray(image.rotate(rotation))


def _run_solve_pipeline(profile, raw, rotation):
    """Reproduce the camera's solve path: optional 2x2 bin, rot90, transpose."""
    full = profile.full_frame(raw)
    image = Image.fromarray(np.asarray(full, dtype=np.uint16) >> 4)
    if rotation == 90:
        image = image.transpose(Image.Transpose.ROTATE_90)
    elif rotation == 270:
        image = image.transpose(Image.Transpose.ROTATE_270)
    return np.asarray(image)


@pytest.mark.unit
@pytest.mark.parametrize("name", SENSOR_PROFILES)
@pytest.mark.parametrize("rotation", ROTATIONS)
def test_solve_frame_dimensions_match_the_pipeline(name, rotation):
    """The geometry's advertised solve size is what the camera actually produces."""
    profile = CAMERA_PROFILES[name]
    raw = _marker_raw(profile, (0, 0))
    geometry = build_geometry(profile, rotation, full_frame=True)

    produced = _run_solve_pipeline(profile, raw, rotation)

    assert produced.shape == (geometry.solve_height, geometry.solve_width)
    assert geometry.solve_size == produced.shape


@pytest.mark.unit
@pytest.mark.parametrize("name", SENSOR_PROFILES)
@pytest.mark.parametrize("rotation", ROTATIONS)
def test_display_to_solve_maps_the_same_sensor_pixel(name, rotation):
    """A star lands where the mapping says it should in both frames.

    Drives one bright raw pixel through both real pipelines and checks that
    transforming its display-frame position gives its solve-frame position.
    """
    profile = CAMERA_PROFILES[name]
    width, height = profile.raw_size
    crop_left, _ = profile.crop_x
    crop_top, _ = profile.crop_y

    # Somewhere inside the square crop, off-centre on both axes so a
    # transposed or mirrored mapping cannot pass by accident.
    marker = (
        crop_top + (height - 2 * crop_top) // 3,
        crop_left + (width - 2 * crop_left) // 4,
    )
    raw = _marker_raw(profile, marker)
    geometry = build_geometry(profile, rotation, full_frame=True)

    display_yx = _marker_centre(_run_display_pipeline(profile, raw, rotation))
    solve_yx = _marker_centre(_run_solve_pipeline(profile, raw, rotation))

    mapped = geometry.display_to_solve(display_yx)

    # The display frame is a coarser sampling of the sensor, so a display pixel
    # covers several solve pixels; allow that much slack.
    scale = max(profile.raw_size) / DISPLAY_FRAME_SIZE
    assert mapped[0] == pytest.approx(solve_yx[0], abs=scale + 1)
    assert mapped[1] == pytest.approx(solve_yx[1], abs=scale + 1)


@pytest.mark.unit
@pytest.mark.parametrize("name", SENSOR_PROFILES)
@pytest.mark.parametrize("rotation", ROTATIONS)
def test_display_solve_round_trip(name, rotation):
    profile = CAMERA_PROFILES[name]
    geometry = build_geometry(profile, rotation, full_frame=True)

    for point in [(0.0, 0.0), (255.5, 255.5), (100.0, 400.0), (511.0, 3.0)]:
        assert geometry.solve_to_display(
            geometry.display_to_solve(point)
        ) == pytest.approx(point, abs=1e-6)


@pytest.mark.unit
@pytest.mark.parametrize("name", SENSOR_PROFILES)
@pytest.mark.parametrize("rotation", ROTATIONS)
def test_display_frame_centre_maps_to_solve_frame_centre(name, rotation):
    """Both frames are concentric, so RA/Dec of centre is shared."""
    profile = CAMERA_PROFILES[name]
    geometry = build_geometry(profile, rotation, full_frame=True)

    centre = (DISPLAY_FRAME_SIZE - 1) / 2.0
    mapped = geometry.display_to_solve((centre, centre))

    assert mapped[0] == pytest.approx((geometry.solve_height - 1) / 2.0, abs=1.0)
    assert mapped[1] == pytest.approx((geometry.solve_width - 1) / 2.0, abs=1.0)


@pytest.mark.unit
@pytest.mark.parametrize("name", SENSOR_PROFILES)
def test_solve_to_display_array_matches_scalar(name):
    geometry = build_geometry(CAMERA_PROFILES[name], 90, full_frame=True)
    points = np.array([[10.0, 20.0], [300.0, 400.0], [1.0, 999.0]])

    batch = geometry.solve_to_display_array(points)

    for point, mapped in zip(points, batch):
        assert tuple(mapped) == pytest.approx(geometry.solve_to_display(point))


@pytest.mark.unit
def test_solve_to_display_array_handles_empty_input():
    geometry = build_geometry(CAMERA_PROFILES["imx462"], 90, full_frame=True)
    assert geometry.solve_to_display_array(np.empty((0, 2))).shape == (0, 2)


@pytest.mark.unit
@pytest.mark.parametrize("name", SENSOR_PROFILES)
@pytest.mark.parametrize("rotation", ROTATIONS)
def test_display_fov_never_exceeds_the_solve_fov(name, rotation):
    """The display frame is a crop of the solve frame, so it can only be narrower.

    On sensors whose square crop already spans the short side, the two are
    equal after the camera's quarter turn -- the extra sky arrives vertically.
    """
    geometry = build_geometry(CAMERA_PROFILES[name], rotation, full_frame=True)

    display_fov = geometry.display_fov(12.0)

    assert 0 < display_fov <= 12.0 + 1e-9


@pytest.mark.unit
@pytest.mark.parametrize("name", SENSOR_PROFILES)
@pytest.mark.parametrize("rotation", ROTATIONS)
def test_solve_fov_inverts_display_fov(name, rotation):
    geometry = build_geometry(CAMERA_PROFILES[name], rotation, full_frame=True)

    assert geometry.display_fov(geometry.solve_fov(10.2)) == pytest.approx(10.2)


@pytest.mark.unit
def test_display_fov_recovers_the_known_crop_field():
    """imx462's square crop is the ~10.2 degree field the crop pipeline solves.

    Its solve frame is 1080 raw pixels wide (the sensor's short side, after the
    quarter turn) against the crop's 980, so the horizontal field grows by about
    a tenth -- the bulk of the 2x area gain is vertical.
    """
    profile = CAMERA_PROFILES["imx462"]
    geometry = build_geometry(profile, 90, full_frame=True)
    solve_fov = geometry.solve_fov(10.2)

    assert geometry.solve_width == 1080
    assert solve_fov == pytest.approx(11.2, abs=0.1)

    # Gnomonic expectation: same focal length, narrower sensor width.
    focal_px = (geometry.solve_width / 2) / math.tan(math.radians(solve_fov) / 2)
    crop_width_native = 980
    expected = math.degrees(2 * math.atan((crop_width_native / 2) / focal_px))
    assert geometry.display_fov(solve_fov) == pytest.approx(expected, rel=1e-6)


@pytest.mark.unit
@pytest.mark.parametrize("name", SENSOR_PROFILES)
def test_full_frame_covers_more_sky_than_the_crop(name):
    """The whole point: the solve frame samples more of the sensor."""
    profile = CAMERA_PROFILES[name]
    geometry = build_geometry(profile, 90, full_frame=True)

    crop_width, _ = profile.crop_x
    crop_top, _ = profile.crop_y
    cropped_area = (profile.raw_size[0] - 2 * crop_width) * (
        profile.raw_size[1] - 2 * crop_top
    )
    solve_area = np.prod(profile.solve_frame_size)

    assert solve_area > cropped_area
    assert geometry.solve_width * geometry.solve_height > 0


@pytest.mark.unit
def test_identity_geometry_is_a_no_op():
    geometry = identity_geometry()

    assert geometry.full_frame is False
    assert geometry.solve_size == (DISPLAY_FRAME_SIZE, DISPLAY_FRAME_SIZE)
    assert geometry.display_to_solve((17.0, 42.0)) == pytest.approx((17.0, 42.0))


@pytest.mark.unit
def test_build_geometry_without_full_frame_is_identity():
    geometry = build_geometry(CAMERA_PROFILES["imx462"], 90, full_frame=False)
    assert geometry.solve_size == (DISPLAY_FRAME_SIZE, DISPLAY_FRAME_SIZE)


@pytest.mark.unit
def test_geometry_survives_serialisation():
    """The geometry crosses a process boundary via shared state."""
    original = build_geometry(CAMERA_PROFILES["hq"], 270, full_frame=True)

    restored = SolveGeometry.from_dict(original.as_dict())

    assert restored.solve_size == original.solve_size
    assert restored.full_frame == original.full_frame
    assert restored.display_to_solve((3.0, 7.0)) == pytest.approx(
        original.display_to_solve((3.0, 7.0))
    )


@pytest.mark.unit
def test_shared_buffer_fits_every_solve_frame():
    buffer_width, buffer_height = max_solve_frame_size()

    for profile in CAMERA_PROFILES.values():
        width, height = profile.solve_frame_size
        # Either orientation, since the camera loop may rotate a quarter turn.
        assert max(width, height) <= min(buffer_width, buffer_height)


@pytest.mark.unit
def test_solve_frame_is_the_whole_sensor():
    assert CAMERA_PROFILES["imx462"].solve_frame_size == (1920, 1080)
    assert CAMERA_PROFILES["hq"].solve_frame_size == (2028, 1520)
    assert CAMERA_PROFILES["imx296"].solve_frame_size == (1456, 1088)


@pytest.mark.unit
def test_full_frame_keeps_native_sampling():
    """No binning: the mosaic goes to star detection at full resolution.

    Binning was measured to cost matches without buying accuracy -- the finer
    sampling is what lets marginal stars clear the detection threshold.
    """
    profile = CAMERA_PROFILES["imx462"]
    width, height = profile.raw_size
    raw = np.zeros((height, width), dtype=np.uint16)
    raw[0, 0], raw[0, 1], raw[1, 0], raw[1, 1] = 10, 20, 30, 40

    full = profile.full_frame(raw)

    assert full.shape == (height, width)
    np.testing.assert_array_equal(full[:2, :2], [[10, 20], [30, 40]])


@pytest.mark.unit
def test_calibration_starts_wide_then_narrows():
    calibration = OpticalCalibration(16.0, 8.0)

    assert calibration.calibrated is False
    assert calibration.solver_args() == {
        "fov_estimate": 16.0,
        "fov_max_error": 8.0,
        "distortion": 0,
    }

    calibration.record_success({"FOV": 19.87, "distortion": -0.021})

    assert calibration.calibrated is True
    assert calibration.solver_args() == {
        "fov_estimate": pytest.approx(19.87),
        "fov_max_error": CALIBRATED_FOV_MAX_ERROR,
        "distortion": pytest.approx(-0.021),
    }


@pytest.mark.unit
def test_calibration_keeps_its_first_measurement():
    """Later solves must not drag the calibration around."""
    calibration = OpticalCalibration(16.0, 8.0)
    calibration.record_success({"FOV": 19.87, "distortion": -0.021})

    calibration.record_success({"FOV": 12.0, "distortion": 0.5})

    assert calibration.fov == pytest.approx(19.87)
    assert calibration.distortion == pytest.approx(-0.021)


@pytest.mark.unit
@pytest.mark.parametrize("fov", [4.0, 45.0])
def test_calibration_rejects_fov_outside_the_database_range(fov):
    calibration = OpticalCalibration(16.0, 8.0)

    calibration.record_success({"FOV": fov, "distortion": 0.0})

    assert calibration.calibrated is False


@pytest.mark.unit
def test_calibration_handles_a_solve_without_distortion():
    """distortion is absent from the solution when the caller disabled it."""
    calibration = OpticalCalibration(16.0, 8.0)

    calibration.record_success({"FOV": 13.6})

    assert calibration.distortion == 0.0


@pytest.mark.unit
def test_sustained_failure_discards_the_calibration():
    calibration = OpticalCalibration(16.0, 8.0)
    calibration.record_success({"FOV": 19.87, "distortion": -0.021})

    for _ in range(FAILURES_BEFORE_RECALIBRATION):
        calibration.record_failure()

    assert calibration.calibrated is False
    assert calibration.solver_args()["fov_max_error"] == 8.0


@pytest.mark.unit
def test_a_success_resets_the_failure_run():
    calibration = OpticalCalibration(16.0, 8.0)
    calibration.record_success({"FOV": 19.87, "distortion": -0.021})

    for _ in range(FAILURES_BEFORE_RECALIBRATION - 1):
        calibration.record_failure()
    calibration.record_success({"FOV": 19.87, "distortion": -0.021})
    calibration.record_failure()

    assert calibration.calibrated is True


@pytest.mark.unit
def test_failed_solve_is_passed_through_unprojected():
    """A starless frame must not raise.

    tetra3 returns every value as None when it cannot match, and that is the
    common case indoors, at dusk, or under cloud. Projecting it blindly raised
    TypeError on every such frame -- caught only on real hardware, because the
    integration test skips when a solve fails and the unit tests fed only
    successful solutions.
    """
    from PiFinder.solver import project_solution_to_display

    geometry = build_geometry(CAMERA_PROFILES["imx462"], 90, full_frame=True)
    failed = {
        "RA": None,
        "Dec": None,
        "Roll": None,
        "FOV": None,
        "distortion": None,
        "Matches": None,
        "T_solve": 12.3,
        "status": "NO_MATCH",
    }

    assert project_solution_to_display(failed, geometry) == failed


@pytest.mark.unit
def test_failed_solve_still_records_against_calibration():
    """The failure counter must advance even though nothing is projected."""
    calibration = OpticalCalibration(11.2, 4.4)
    calibration.record_success({"FOV": 11.2, "distortion": -0.02})

    calibration.record_failure()

    assert calibration.calibrated is True
