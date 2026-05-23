"""Unit tests for the PointingEstimate dataclass surface and the
solver/integrator merge semantics that travel through it."""

import copy

import numpy as np
import pytest
import quaternion

from PiFinder.types.positioning import (
    AlignCancel,
    AlignOnRaDec,
    AlignedResult,
    AlignmentResult,
    Pointing,
    PointingAxis,
    PointingEstimate,
    PointingMatrix,
    ReloadSqmCalibration,
    SolveDiagnostics,
    SolveSource,
)


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------
# PointingEstimate basics
# ---------------------------------------------------------------------


class TestPointingEstimateDefaults:
    def test_fresh_estimate_has_no_pointing(self):
        est = PointingEstimate()
        assert est.has_pointing() is False
        assert est.is_camera_solve() is False
        assert est.is_imu_solve() is False
        assert est.pointing.aligned.estimate is None
        assert est.pointing.camera.solve is None
        assert est.diagnostics.Matches == 0
        assert est.solve_source is None
        assert est.imu_anchor is None
        assert est.matched_centroids is None
        assert est.matched_stars is None

    def test_has_pointing_only_tracks_aligned_estimate(self):
        est = PointingEstimate()
        est.pointing.camera.estimate = Pointing(RA=10.0, Dec=20.0, Roll=0.0)
        # Camera-only estimate does NOT count as published pointing.
        assert est.has_pointing() is False

        est.pointing.aligned.estimate = Pointing(RA=10.0, Dec=20.0, Roll=0.0)
        assert est.has_pointing() is True


class TestSolveSourceEnum:
    def test_camera_enum_compares_equal_to_string(self):
        # Inheritance from str preserves the legacy equality behavior.
        assert SolveSource.CAMERA == "CAM"
        assert SolveSource.CAMERA_FAILED == "CAM_FAILED"
        assert SolveSource.IMU == "IMU"

    def test_predicates_match_enum(self):
        est = PointingEstimate(solve_source=SolveSource.CAMERA)
        assert est.is_camera_solve() is True
        assert est.is_imu_solve() is False

        est.solve_source = SolveSource.IMU
        assert est.is_camera_solve() is False
        assert est.is_imu_solve() is True


# ---------------------------------------------------------------------
# Pointing leaf type
# ---------------------------------------------------------------------


class TestPointing:
    def test_as_radecroll_converts_degrees_to_radians(self):
        p = Pointing(RA=180.0, Dec=45.0, Roll=90.0)
        r = p.as_radecroll()
        assert r.ra == pytest.approx(np.pi)
        assert r.dec == pytest.approx(np.pi / 4)
        assert r.roll == pytest.approx(np.pi / 2)


# ---------------------------------------------------------------------
# AlignmentResult helpers
# ---------------------------------------------------------------------


class TestAlignmentResult:
    def test_empty_alignment_is_unset(self):
        a = AlignmentResult()
        assert a.is_set() is False
        assert a.target_pixel() is None

    def test_target_pixel_returns_y_x_order(self):
        # The pixel is (Y, X) by convention.
        a = AlignmentResult(x_target=128.0, y_target=256.0)
        assert a.is_set() is True
        assert a.target_pixel() == (256.0, 128.0)


# ---------------------------------------------------------------------
# AlignedResult queue message
# ---------------------------------------------------------------------


class TestAlignedResult:
    def test_as_target_pixel_returns_y_x(self):
        r = AlignedResult(y_target=200.0, x_target=300.0)
        assert r.as_target_pixel() == (200.0, 300.0)


# ---------------------------------------------------------------------
# Picklability of all queue and shared-state payloads
# ---------------------------------------------------------------------


class TestPicklability:
    """The shared-state proxy and solver_queue pickle their payloads,
    so every dataclass that travels there must round-trip cleanly."""

    def test_pointing_estimate_with_quaternion_round_trips(self):
        import pickle

        original = PointingEstimate(
            pointing=PointingMatrix(
                camera=PointingAxis(
                    solve=Pointing(RA=1.1, Dec=2.2, Roll=3.3),
                    estimate=Pointing(RA=1.1, Dec=2.2, Roll=3.3),
                ),
                aligned=PointingAxis(
                    solve=Pointing(RA=4.4, Dec=5.5, Roll=6.6),
                    estimate=Pointing(RA=4.4, Dec=5.5, Roll=6.6),
                ),
            ),
            imu_anchor=quaternion.quaternion(1, 0, 0, 0),
            solve_source=SolveSource.CAMERA,
            solve_time=12345.6789,
            diagnostics=SolveDiagnostics(Matches=42, RMSE=0.5, FOV=10.2),
            alignment=AlignmentResult(x_target=128.0, y_target=256.0),
            matched_centroids=[(100.0, 200.0), (110.0, 210.0)],
            matched_stars=[[1.0, 2.0, 5.5], [3.0, 4.0, 6.5]],
        )
        roundtripped = pickle.loads(pickle.dumps(original))
        assert roundtripped == original
        # Quaternion compares specially, double-check:
        assert roundtripped.imu_anchor == original.imu_anchor

    def test_alignment_queue_messages_pickle(self):
        import pickle

        for msg in (
            AlignOnRaDec(ra=12.3, dec=45.6),
            AlignCancel(),
            ReloadSqmCalibration(),
            AlignedResult(y_target=10.0, x_target=20.0),
        ):
            assert pickle.loads(pickle.dumps(msg)) == msg


# ---------------------------------------------------------------------
# Solver builder semantics
# ---------------------------------------------------------------------


class TestSolverBuilders:
    """The solver builds a fresh PointingEstimate per attempt; verify
    both the success and failure shapes match what the integrator
    expects to merge."""

    def _make_image_metadata(self, with_imu=True):
        meta = {"exposure_end": 1000.5, "exposure_time": 500_000}
        if with_imu:
            meta["imu"] = {"quat": quaternion.quaternion(1, 0, 0, 0)}
        return meta

    def test_successful_solve_populates_both_axes_and_imu(self):
        from PiFinder.solver import _build_solved_estimate

        solution = {
            "RA": 100.0,
            "Dec": 20.0,
            "Roll": 5.0,
            "RA_target": 100.5,
            "Dec_target": 20.5,
            "Matches": 12,
            "RMSE": 0.4,
            "FOV": 10.2,
            "T_solve": 50.0,
            "T_extract": 60.0,
            "x_target": 128.0,
            "y_target": 256.0,
            "matched_centroids": [(1.0, 2.0)],
            "matched_stars": [[1.0, 2.0, 5.5]],
        }
        est = _build_solved_estimate(
            solution=solution,
            last_image_metadata=self._make_image_metadata(),
            last_solve_attempt=999.0,
            last_solve_success=999.0,
        )
        # Camera axis = matched-stars solution (no target offset).
        assert est.pointing.camera.solve == Pointing(RA=100.0, Dec=20.0, Roll=5.0)
        assert est.pointing.camera.estimate == Pointing(RA=100.0, Dec=20.0, Roll=5.0)
        # Aligned axis = target-pixel solution.
        assert est.pointing.aligned.solve == Pointing(RA=100.5, Dec=20.5, Roll=5.0)
        assert est.pointing.aligned.estimate == Pointing(RA=100.5, Dec=20.5, Roll=5.0)
        # Anchor + diagnostics + matched-* payloads.
        assert est.imu_anchor == quaternion.quaternion(1, 0, 0, 0)
        assert est.diagnostics.Matches == 12
        assert est.diagnostics.RMSE == pytest.approx(0.4)
        assert est.diagnostics.FOV == pytest.approx(10.2)
        assert est.solve_source == SolveSource.CAMERA
        assert est.alignment.is_set()
        assert est.matched_centroids == [(1.0, 2.0)]
        assert est.matched_stars == [[1.0, 2.0, 5.5]]

    def test_successful_solve_without_imu_has_none_anchor(self):
        from PiFinder.solver import _build_solved_estimate

        solution = {"RA": 1.0, "Dec": 2.0, "Roll": 3.0}
        est = _build_solved_estimate(
            solution=solution,
            last_image_metadata=self._make_image_metadata(with_imu=False),
            last_solve_attempt=999.0,
            last_solve_success=999.0,
        )
        assert est.imu_anchor is None
        assert est.has_pointing() is True

    def test_failed_solve_has_empty_pointing_and_failed_source(self):
        from PiFinder.solver import _build_failed_estimate

        est = _build_failed_estimate(
            last_image_metadata=self._make_image_metadata(),
            last_solve_attempt=999.0,
            last_solve_success=None,
            t_extract_ms=42.0,
        )
        assert est.has_pointing() is False
        assert est.solve_source == SolveSource.CAMERA_FAILED
        assert est.diagnostics.Matches == 0
        assert est.diagnostics.T_extract == pytest.approx(42.0)
        assert est.last_solve_attempt == pytest.approx(999.0)
        # Anchor not populated on failure.
        assert est.imu_anchor is None


# ---------------------------------------------------------------------
# Integrator merge semantics — the contract that lets dead-reckoning
# survive a failed plate-solve.
# ---------------------------------------------------------------------


class _FakeIdr:
    """Capture-only fake for ImuDeadReckoning that records solve() calls."""

    def __init__(self):
        self.solve_calls = []
        self._initialized = False

    def solve(self, radecroll, q_x2imu):
        self.solve_calls.append((radecroll, q_x2imu))
        self._initialized = True

    def predict(self, q_x2imu):  # pragma: no cover - not used in these tests
        return None

    def is_initialized(self):
        return self._initialized

    def reset(self):
        self._initialized = False


class TestIntegratorApplySuccess:
    def _make_snapshot(self):
        return PointingEstimate(
            pointing=PointingMatrix(
                camera=PointingAxis(
                    solve=Pointing(RA=1.0, Dec=2.0, Roll=3.0),
                    estimate=Pointing(RA=1.0, Dec=2.0, Roll=3.0),
                ),
                aligned=PointingAxis(
                    solve=Pointing(RA=1.5, Dec=2.5, Roll=3.0),
                    estimate=Pointing(RA=1.5, Dec=2.5, Roll=3.0),
                ),
            ),
            imu_anchor=quaternion.quaternion(1, 0, 0, 0),
            solve_source=SolveSource.CAMERA,
            solve_time=500.0,
            cam_solve_time=500.0,
            last_solve_attempt=499.5,
            last_solve_success=499.5,
            diagnostics=SolveDiagnostics(Matches=7),
            alignment=AlignmentResult(),
            matched_centroids=[(0.0, 1.0)],
            matched_stars=[[1.0, 2.0, 5.5]],
        )

    def test_successful_solve_replaces_anchor_and_reseeds_both_idrs(self):
        from PiFinder.integrator import _apply_successful_solve

        estimate = PointingEstimate()
        snapshot = self._make_snapshot()
        idr_camera = _FakeIdr()
        idr_aligned = _FakeIdr()

        merged = _apply_successful_solve(estimate, snapshot, idr_camera, idr_aligned)

        # Both axes now reflect the snapshot's solve and estimate cells.
        assert merged.pointing.camera.solve == snapshot.pointing.camera.solve
        assert merged.pointing.aligned.solve == snapshot.pointing.aligned.solve
        assert merged.pointing.camera.estimate == snapshot.pointing.camera.estimate
        assert merged.pointing.aligned.estimate == snapshot.pointing.aligned.estimate
        assert merged.imu_anchor == snapshot.imu_anchor
        assert merged.matched_centroids == snapshot.matched_centroids
        assert merged.matched_stars == snapshot.matched_stars

        # Each IDR reseeded with the matching axis solve.
        assert len(idr_camera.solve_calls) == 1
        assert len(idr_aligned.solve_calls) == 1
        camera_radecroll, camera_q = idr_camera.solve_calls[0]
        aligned_radecroll, aligned_q = idr_aligned.solve_calls[0]
        # RaDecRoll round-trip back to degrees for comparison.
        assert camera_radecroll.get(deg=True) == pytest.approx((1.0, 2.0, 3.0))
        assert aligned_radecroll.get(deg=True) == pytest.approx((1.5, 2.5, 3.0))
        assert camera_q == snapshot.imu_anchor
        assert aligned_q == snapshot.imu_anchor

    def test_solve_with_no_anchor_passes_nan_quaternion(self):
        from PiFinder.integrator import _apply_successful_solve

        snapshot = self._make_snapshot()
        snapshot.imu_anchor = None  # IMU not available on this frame
        idr_camera = _FakeIdr()
        idr_aligned = _FakeIdr()

        _apply_successful_solve(PointingEstimate(), snapshot, idr_camera, idr_aligned)

        # The fake captured a quaternion that's NaN-on-all-components.
        _, q = idr_camera.solve_calls[0]
        assert bool(np.isnan(q))


class TestIntegratorFailedSolve:
    """The user-confirmed contract: integrator owns the anchor; on a
    failed solve the previous solve cells survive so dead-reckoning
    continues."""

    def test_failed_snapshot_preserves_previous_solve_cells(self):
        # Build an integrator-side estimate that has prior solve cells.
        previous_anchor = quaternion.quaternion(1, 0, 0, 0)
        integrator_estimate = PointingEstimate(
            pointing=PointingMatrix(
                camera=PointingAxis(
                    solve=Pointing(RA=10.0, Dec=20.0, Roll=0.0),
                    estimate=Pointing(RA=10.0, Dec=20.0, Roll=0.0),
                ),
                aligned=PointingAxis(
                    solve=Pointing(RA=10.5, Dec=20.5, Roll=0.0),
                    estimate=Pointing(RA=10.5, Dec=20.5, Roll=0.0),
                ),
            ),
            imu_anchor=previous_anchor,
            solve_source=SolveSource.CAMERA,
            solve_time=100.0,
            diagnostics=SolveDiagnostics(Matches=8, RMSE=0.6),
        )

        # Simulate the failed-solve branch of the integrator loop body.
        from PiFinder.solver import _build_failed_estimate

        failed_snapshot = _build_failed_estimate(
            last_image_metadata={"exposure_end": 200.0, "exposure_time": 500_000},
            last_solve_attempt=200.0,
            last_solve_success=100.0,
            t_extract_ms=50.0,
        )
        # Same body as integrator loop (failed-solve branch).
        integrator_estimate.diagnostics = failed_snapshot.diagnostics
        integrator_estimate.last_solve_attempt = failed_snapshot.last_solve_attempt
        integrator_estimate.last_solve_success = failed_snapshot.last_solve_success
        integrator_estimate.solve_source = SolveSource.CAMERA_FAILED
        integrator_estimate.pointing.camera.estimate = None
        integrator_estimate.pointing.aligned.estimate = None

        # solve cells + anchor still present so IMU dead-reckoning has
        # something to track against.
        assert integrator_estimate.pointing.camera.solve == Pointing(
            RA=10.0, Dec=20.0, Roll=0.0
        )
        assert integrator_estimate.pointing.aligned.solve == Pointing(
            RA=10.5, Dec=20.5, Roll=0.0
        )
        assert integrator_estimate.imu_anchor == previous_anchor
        # estimate cells cleared.
        assert integrator_estimate.pointing.camera.estimate is None
        assert integrator_estimate.pointing.aligned.estimate is None
        # Diagnostics refreshed.
        assert integrator_estimate.diagnostics.Matches == 0
        assert integrator_estimate.last_solve_attempt == pytest.approx(200.0)
        assert integrator_estimate.last_solve_success == pytest.approx(100.0)


# ---------------------------------------------------------------------
# Alignment queue dispatch via isinstance
# ---------------------------------------------------------------------


class TestAlignmentQueueDispatch:
    """Mirror the solver loop's command dispatch to lock in the
    isinstance contract."""

    def _dispatch(self, command):
        """Return a tag identifying which branch the solver would take."""
        if isinstance(command, AlignOnRaDec):
            return "align_on", command.ra, command.dec
        if isinstance(command, AlignCancel):
            return "cancel"
        if isinstance(command, ReloadSqmCalibration):
            return "reload_sqm"
        return ("unknown", type(command).__name__)

    def test_align_on_radec_routes_correctly(self):
        assert self._dispatch(AlignOnRaDec(ra=12.3, dec=45.6)) == ("align_on", 12.3, 45.6)

    def test_align_cancel_routes_correctly(self):
        assert self._dispatch(AlignCancel()) == "cancel"

    def test_reload_sqm_routes_correctly(self):
        assert self._dispatch(ReloadSqmCalibration()) == "reload_sqm"

    def test_unknown_command_caught_by_fallback(self):
        tag = self._dispatch(("legacy_string_command", 1, 2))
        assert tag[0] == "unknown"


# ---------------------------------------------------------------------
# Deep copy — integrator publishes deepcopies into shared_state so
# downstream readers can't mutate the integrator's working estimate.
# ---------------------------------------------------------------------


class TestPublishDeepCopy:
    def test_deepcopy_isolates_published_state(self):
        original = PointingEstimate(
            pointing=PointingMatrix(
                aligned=PointingAxis(
                    estimate=Pointing(RA=1.0, Dec=2.0, Roll=3.0),
                ),
            ),
        )
        published = copy.deepcopy(original)
        original.pointing.aligned.estimate.RA = 999.0
        # Published copy unaffected.
        assert published.pointing.aligned.estimate.RA == pytest.approx(1.0)
