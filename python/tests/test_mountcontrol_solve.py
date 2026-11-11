"""The plate-solve input of the mount state machine: JNow conversion, the
solve reader, and the REFINE wait for a solve taken after the move."""

import datetime
import time
from queue import Queue
from unittest.mock import Mock

import pytest

from PiFinder import calc_utils
from PiFinder.mountcontrol_interface import MountControlBase, MountControlPhases
from PiFinder.state import SharedStateObj
from PiFinder.types.positioning import (
    Pointing,
    PointingAxis,
    PointingEstimate,
    PointingMatrix,
)

pytestmark = pytest.mark.unit

NOW = datetime.datetime(2026, 11, 11, 22, 0, tzinfo=datetime.timezone.utc)


def _estimate(ra, dec, solve_time, imu_ra=None):
    """An estimate whose aligned solve is (ra, dec). imu_ra moves only the
    IMU-progressed estimate cell."""
    solve = Pointing(RA=ra, Dec=dec, Roll=0.0)
    estimate = Pointing(RA=imu_ra if imu_ra is not None else ra, Dec=dec, Roll=0.0)
    return PointingEstimate(
        pointing=PointingMatrix(
            camera=PointingAxis(solve=solve, estimate=estimate),
            aligned=PointingAxis(solve=solve, estimate=estimate),
        ),
        last_solve_success=solve_time,
    )


class _Mount(MountControlBase):
    def __init__(self, shared_state):
        super().__init__(Queue(), Queue(), shared_state)
        self.sync_mount = Mock(return_value=True)
        self.move_mount_to_target = Mock(return_value=True)
        self.is_mount_moving = Mock(return_value=False)
        self.refine_solve_timeout_s = 0.2


def _shared_state(solution):
    shared_state = Mock(spec=SharedStateObj)
    shared_state.solution.return_value = solution
    shared_state.datetime.return_value = NOW
    return shared_state


def _run(gen, timeout=1.0):
    start = time.time()
    try:
        while time.time() - start < timeout:
            next(gen)
    except StopIteration:
        pass


def test_j2000_to_jnow_precesses_and_round_trips():
    # Vega. 26.9 years of precession move RA by about +0.23 degrees.
    ra, dec = calc_utils.j2000_to_jnow(279.2347, 38.7837, NOW)
    assert 0.15 < ra - 279.2347 < 0.35
    assert abs(dec - 38.7837) < 0.1
    back_ra, back_dec = calc_utils.jnow_to_j2000(ra, dec, NOW)
    assert back_ra == pytest.approx(279.2347, abs=1e-6)
    assert back_dec == pytest.approx(38.7837, abs=1e-6)


def test_latest_solve_is_jnow_aligned_solve_not_imu_estimate():
    mount = _Mount(_shared_state(_estimate(100.0, 20.0, 1234.5, imu_ra=150.0)))
    ra, dec, t = mount.latest_solve()
    expected = calc_utils.j2000_to_jnow(100.0, 20.0, NOW)
    assert (ra, dec) == pytest.approx(expected)
    assert t == 1234.5


@pytest.mark.parametrize(
    "solution",
    [None, PointingEstimate(), _estimate(1.0, 2.0, None)],
)
def test_latest_solve_none_without_solve(solution):
    assert _Mount(_shared_state(solution)).latest_solve() is None


def test_latest_solve_none_without_datetime():
    shared_state = _shared_state(_estimate(1.0, 2.0, 5.0))
    shared_state.datetime.return_value = None
    assert _Mount(shared_state).latest_solve() is None


def test_refine_ignores_a_solve_from_before_the_move():
    # The only solve is older than the move, so REFINE times out.
    mount = _Mount(_shared_state(_estimate(10.0, 10.0, time.time() - 60)))
    mount.state = MountControlPhases.MOUNT_TARGET_ACQUISITION_REFINE
    mount.target_ra, mount.target_dec = 10.0, 10.0
    mount._refine_after = time.time()
    _run(mount._process_phase())
    assert mount.state == MountControlPhases.MOUNT_TRACKING
    mount.sync_mount.assert_not_called()
    assert mount.console_queue.get_nowait()[0] == "WARNING"


def test_refine_syncs_to_jnow_solve_and_moves_again():
    mount = _Mount(_shared_state(_estimate(10.5, 10.0, time.time() + 1)))
    mount.state = MountControlPhases.MOUNT_TARGET_ACQUISITION_REFINE
    mount.target_ra, mount.target_dec = 10.0, 10.0
    _run(mount._process_phase())
    mount.sync_mount.assert_called_once()
    sync_ra, sync_dec = mount.sync_mount.call_args.args
    assert (sync_ra, sync_dec) == pytest.approx(
        calc_utils.j2000_to_jnow(10.5, 10.0, NOW)
    )
    mount.move_mount_to_target.assert_called_with(10.0, 10.0)
    assert mount.state == MountControlPhases.MOUNT_TARGET_ACQUISITION_MOVE
    assert mount._refine_count == 1


def test_refine_stops_after_max_iterations():
    mount = _Mount(_shared_state(_estimate(10.5, 10.0, time.time() + 1)))
    mount.state = MountControlPhases.MOUNT_TARGET_ACQUISITION_REFINE
    mount.target_ra, mount.target_dec = 10.0, 10.0
    mount._refine_count = mount.refine_max_iterations
    _run(mount._process_phase())
    mount.sync_mount.assert_not_called()
    assert mount.state == MountControlPhases.MOUNT_TRACKING


def test_refine_handles_ra_wrap():
    # Target at RA 359.999, solve at JNow RA just past 0: within tolerance.
    solve = calc_utils.jnow_to_j2000(0.004, 10.0, NOW)
    mount = _Mount(_shared_state(_estimate(solve[0], solve[1], time.time() + 1)))
    mount.state = MountControlPhases.MOUNT_TARGET_ACQUISITION_REFINE
    mount.target_ra, mount.target_dec = 359.999, 10.0
    _run(mount._process_phase())
    assert mount.state == MountControlPhases.MOUNT_DRIFT_COMPENSATION
