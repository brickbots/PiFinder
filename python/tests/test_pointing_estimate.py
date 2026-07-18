"""Unit tests for the PointingEstimate dataclass surface and the
solver/integrator merge semantics that travel through it."""

import copy
import math

import numpy as np
import pytest
import quaternion

from PiFinder.types.positioning import (
    AlignCancel,
    AlignOnRaDec,
    AlignedResult,
    AlignmentResult,
    FailedSolve,
    ImuSample,
    Pointing,
    PointingAxis,
    PointingEstimate,
    PointingMatrix,
    ReloadSqmCalibration,
    SolveDiagnostics,
    SolveSource,
    SuccessfulSolve,
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

    def test_from_radecroll_converts_radians_to_degrees(self):
        from PiFinder.types.coordinates import RaDecRoll

        r = RaDecRoll(np.pi, np.pi / 4, np.pi / 2)
        p = Pointing.from_radecroll(r)
        assert p == Pointing(RA=180.0, Dec=45.0, Roll=90.0)

    def test_radecroll_round_trip_is_identity(self):
        original = Pointing(RA=123.4, Dec=-12.3, Roll=271.0)
        round_tripped = Pointing.from_radecroll(original.as_radecroll())
        assert round_tripped.RA == pytest.approx(original.RA)
        assert round_tripped.Dec == pytest.approx(original.Dec)
        assert round_tripped.Roll == pytest.approx(original.Roll)


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
            estimate_time=12345.6789,
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

    def test_solve_result_messages_round_trip(self):
        import pickle

        success = SuccessfulSolve(
            camera=Pointing(RA=1.0, Dec=2.0, Roll=3.0),
            aligned=Pointing(RA=1.5, Dec=2.5, Roll=3.0),
            imu_anchor=quaternion.quaternion(1, 0, 0, 0),
            last_solve_attempt=12345.0,
            last_solve_success=12345.0,
            diagnostics=SolveDiagnostics(Matches=9, RMSE=0.3),
            alignment=AlignmentResult(x_target=128.0, y_target=256.0),
            matched_centroids=[(1.0, 2.0)],
            matched_stars=[[1.0, 2.0, 5.5]],
        )
        failure = FailedSolve(
            diagnostics=SolveDiagnostics(Matches=0, T_extract=40.0),
            last_solve_attempt=200.0,
            last_solve_success=None,
        )
        for msg in (success, failure):
            assert pickle.loads(pickle.dumps(msg)) == msg

    def test_imu_sample_round_trips_with_quaternion(self):
        import pickle

        original = ImuSample(
            quat=quaternion.quaternion(0.1, 0.2, 0.3, 0.4),
            timestamp=12345.6789,
            status=3,
            moving=True,
            gyro=(0.01, 0.02, 0.03),
            accel=(0.1, 0.2, 0.3),
        )
        roundtripped = pickle.loads(pickle.dumps(original))
        assert roundtripped == original
        # quat must come back as a real numpy.quaternion — consumers rely on
        # quaternion math / .w/.x/.y/.z — not the 4-float pickle form.
        assert isinstance(roundtripped.quat, quaternion.quaternion)
        assert roundtripped.quat == original.quat
        # __getstate__ must not mutate the live object in place.
        assert isinstance(original.quat, quaternion.quaternion)

    def test_none_quaternion_anchor_round_trips(self):
        import pickle

        # A solve on a frame with no IMU sample carries imu_anchor=None; the
        # float round-trip must preserve None (the helpers are None-safe).
        est = PointingEstimate()  # imu_anchor defaults to None
        assert est.imu_anchor is None
        assert pickle.loads(pickle.dumps(est)).imu_anchor is None

        solve = SuccessfulSolve(
            camera=Pointing(RA=1.0, Dec=2.0, Roll=3.0),
            aligned=Pointing(RA=1.5, Dec=2.5, Roll=3.0),
            imu_anchor=None,
            last_solve_attempt=1.0,
            last_solve_success=1.0,
        )
        assert pickle.loads(pickle.dumps(solve)).imu_anchor is None


# ---------------------------------------------------------------------
# Solver builder semantics
# ---------------------------------------------------------------------


class TestSolverBuilders:
    """The solver builds a SolveResult per attempt; verify both the
    success (SuccessfulSolve) and failure (FailedSolve) shapes match
    what the integrator expects to apply."""

    def _make_image_metadata(self, with_imu=True):
        meta = {"exposure_end": 1000.5, "exposure_time": 500_000}
        if with_imu:
            meta["imu"] = ImuSample(
                quat=quaternion.quaternion(1, 0, 0, 0), timestamp=1000.5
            )
        return meta

    def test_successful_solve_carries_flat_axes_and_imu(self):
        from PiFinder.solver import _build_successful_solve

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
            "matched_catID": [123],
        }
        result = _build_successful_solve(
            solution=solution,
            last_image_metadata=self._make_image_metadata(),
            last_solve_attempt=999.0,
            last_solve_success=999.0,
        )
        assert isinstance(result, SuccessfulSolve)
        # Flat camera axis = matched-stars solution (no target offset).
        assert result.camera == Pointing(RA=100.0, Dec=20.0, Roll=5.0)
        # Flat aligned axis = target-pixel solution.
        assert result.aligned == Pointing(RA=100.5, Dec=20.5, Roll=5.0)
        # Anchor + diagnostics + matched-* payloads.
        assert result.imu_anchor == quaternion.quaternion(1, 0, 0, 0)
        assert result.diagnostics.Matches == 12
        assert result.diagnostics.RMSE == pytest.approx(0.4)
        assert result.diagnostics.FOV == pytest.approx(10.2)
        assert result.alignment.is_set()
        assert result.matched_centroids == [(1.0, 2.0)]
        assert result.matched_stars == [[1.0, 2.0, 5.5]]
        assert result.matched_catID == [123]
        # The solved frame's epoch is last_solve_success (no separate
        # solve_time); the integrator promotes it to estimate_time.
        assert result.last_solve_success == pytest.approx(999.0)
        assert result.last_solve_attempt == pytest.approx(999.0)

    def test_successful_solve_without_imu_has_none_anchor(self):
        from PiFinder.solver import _build_successful_solve

        solution = {"RA": 1.0, "Dec": 2.0, "Roll": 3.0}
        result = _build_successful_solve(
            solution=solution,
            last_image_metadata=self._make_image_metadata(with_imu=False),
            last_solve_attempt=999.0,
            last_solve_success=999.0,
        )
        assert result.imu_anchor is None
        # Aligned falls back to the camera RA/Dec when no target offset.
        assert result.camera == Pointing(RA=1.0, Dec=2.0, Roll=3.0)
        assert result.aligned == Pointing(RA=1.0, Dec=2.0, Roll=3.0)

    def test_failed_solve_carries_diagnostics_and_timing_only(self):
        from PiFinder.solver import _build_failed_solve

        result = _build_failed_solve(
            last_solve_attempt=999.0,
            last_solve_success=None,
            t_extract_ms=42.0,
        )
        assert isinstance(result, FailedSolve)
        assert result.diagnostics.Matches == 0
        assert result.diagnostics.T_extract == pytest.approx(42.0)
        assert result.last_solve_attempt == pytest.approx(999.0)
        assert result.last_solve_success is None
        # No pointing / anchor fields exist on a FailedSolve.
        assert not hasattr(result, "imu_anchor")
        assert not hasattr(result, "camera")


# ---------------------------------------------------------------------
# Integrator merge semantics — the contract that lets dead-reckoning
# survive a failed plate-solve.
# ---------------------------------------------------------------------


class _FakeIdr:
    """Capture-only fake for ImuDeadReckoning that records solve() calls."""

    def __init__(self):
        self.solve_calls = []
        self._initialized = False

    def solve(self, camera, aligned, q_x2imu):
        self.solve_calls.append((camera, aligned, q_x2imu))
        self._initialized = True

    def predict(self, q_x2imu):  # pragma: no cover - not used in these tests
        return None

    def is_initialized(self):
        return self._initialized

    def reset(self):
        self._initialized = False


class TestIntegratorApplySuccess:
    def _make_result(self):
        return SuccessfulSolve(
            camera=Pointing(RA=1.0, Dec=2.0, Roll=3.0),
            aligned=Pointing(RA=1.5, Dec=2.5, Roll=3.0),
            imu_anchor=quaternion.quaternion(1, 0, 0, 0),
            last_solve_attempt=499.5,
            last_solve_success=499.5,
            diagnostics=SolveDiagnostics(Matches=7),
            alignment=AlignmentResult(),
            matched_centroids=[(0.0, 1.0)],
            matched_stars=[[1.0, 2.0, 5.5]],
            matched_catID=[123],
        )

    def test_successful_solve_fans_into_both_cells_and_reseeds_idr(self):
        from PiFinder.integrator import _apply_successful_solve

        estimate = PointingEstimate()
        result = self._make_result()
        idr = _FakeIdr()

        merged = _apply_successful_solve(estimate, result, idr)

        # The flat solve-truth fans into both solve and estimate cells.
        assert merged.pointing.camera.solve == result.camera
        assert merged.pointing.camera.estimate == result.camera
        assert merged.pointing.aligned.solve == result.aligned
        assert merged.pointing.aligned.estimate == result.aligned
        assert merged.imu_anchor == result.imu_anchor
        assert merged.matched_centroids == result.matched_centroids
        assert merged.matched_stars == result.matched_stars
        assert merged.matched_catID == result.matched_catID
        assert merged.solve_source == SolveSource.CAMERA
        # The solved frame's epoch (last_solve_success) becomes estimate_time.
        assert merged.estimate_time == pytest.approx(499.5)

        # Single IDR reseeded with the (camera, aligned) pair.
        assert len(idr.solve_calls) == 1
        camera_radecroll, aligned_radecroll, q = idr.solve_calls[0]
        # RaDecRoll round-trip back to degrees for comparison.
        assert camera_radecroll.get(deg=True) == pytest.approx((1.0, 2.0, 3.0))
        assert aligned_radecroll.get(deg=True) == pytest.approx((1.5, 2.5, 3.0))
        assert q == result.imu_anchor

    def test_solve_with_no_anchor_passes_nan_quaternion(self):
        from PiFinder.integrator import _apply_successful_solve

        result = self._make_result()
        result.imu_anchor = None  # IMU not available on this frame
        idr = _FakeIdr()

        _apply_successful_solve(PointingEstimate(), result, idr)

        # The fake captured the NaN sentinel quaternion (nan, 0, 0, 0).
        _, _, q = idr.solve_calls[0]
        assert math.isnan(q.w)


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
            estimate_time=100.0,
            diagnostics=SolveDiagnostics(Matches=8, RMSE=0.6),
        )

        # Drive the real integrator failed-solve path end to end.
        from PiFinder.solver import _build_failed_solve
        from PiFinder.integrator import _apply_failed_solve

        failed_result = _build_failed_solve(
            last_solve_attempt=200.0,
            last_solve_success=100.0,
            t_extract_ms=50.0,
        )
        integrator_estimate = _apply_failed_solve(integrator_estimate, failed_result)

        # solve cells + anchor still present so IMU dead-reckoning has
        # something to track against.
        assert integrator_estimate.pointing.camera.solve == Pointing(
            RA=10.0, Dec=20.0, Roll=0.0
        )
        assert integrator_estimate.pointing.aligned.solve == Pointing(
            RA=10.5, Dec=20.5, Roll=0.0
        )
        assert integrator_estimate.imu_anchor == previous_anchor
        # estimate cells PRESERVED: once anchored, a failed solve must not
        # drop to "no solve" — dead-reckoning still knows where we point.
        assert integrator_estimate.pointing.camera.estimate == Pointing(
            RA=10.0, Dec=20.0, Roll=0.0
        )
        assert integrator_estimate.pointing.aligned.estimate == Pointing(
            RA=10.5, Dec=20.5, Roll=0.0
        )
        assert integrator_estimate.has_pointing() is True
        # Source flips to CAMERA_FAILED but solve_state (has_pointing) holds.
        assert integrator_estimate.solve_source == SolveSource.CAMERA_FAILED
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
        assert self._dispatch(AlignOnRaDec(ra=12.3, dec=45.6)) == (
            "align_on",
            12.3,
            45.6,
        )

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
