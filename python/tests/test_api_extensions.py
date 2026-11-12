"""Regression tests for the REST API's PointingEstimate serialization.

PR #429 migrated ``shared_state.solution()`` from the legacy ``solved``
dict to a :class:`PointingEstimate` dataclass, but the ``/api/solution``
and ``/api/visible_stars`` endpoints kept reading it dict-style
(``sol["RA"]``, ``sol.get("FOV")``, ``sol["camera_solve"]``), which would
raise ``TypeError``/``AttributeError`` at runtime.

``_solution_to_dict`` re-emits the legacy ``solved`` dict shape so external
clients (e.g. OpenClaw) keep a stable wire contract. These tests lock in
that mapping.
"""

import json

import pytest

from PiFinder.api_extensions import _pointing_to_dict, _solution_to_dict
from PiFinder.types.positioning import (
    Pointing,
    PointingAxis,
    PointingEstimate,
    PointingMatrix,
    SolveDiagnostics,
    SolveSource,
)


def _populated() -> PointingEstimate:
    """A successful solve with a real alignment offset (aligned != camera)."""
    camera = Pointing(RA=10.0, Dec=20.0, Roll=5.0)
    aligned = Pointing(RA=10.5, Dec=20.2, Roll=5.0)
    return PointingEstimate(
        pointing=PointingMatrix(
            camera=PointingAxis(solve=camera, estimate=camera),
            aligned=PointingAxis(solve=aligned, estimate=aligned),
        ),
        Alt=45.0,
        Az=180.0,
        solve_source=SolveSource.CAMERA,
        estimate_time=1234.5,
        last_solve_attempt=1234.5,
        last_solve_success=1234.5,
        constellation="Ori",
        diagnostics=SolveDiagnostics(
            Matches=12, RMSE=0.3, Prob=1e-9, FOV=10.2, T_solve=0.05, T_extract=0.01
        ),
    )


@pytest.mark.unit
def test_pointing_to_dict_none_is_all_none():
    assert _pointing_to_dict(None) == {"RA": None, "Dec": None, "Roll": None}


@pytest.mark.unit
def test_pointing_to_dict_values_are_floats():
    d = _pointing_to_dict(Pointing(RA=1, Dec=2, Roll=3))
    assert d == {"RA": 1.0, "Dec": 2.0, "Roll": 3.0}
    assert all(isinstance(v, float) for v in d.values())


@pytest.mark.unit
def test_empty_estimate_serializes_without_error():
    """A fresh (un-solved) estimate must serialize to all-None, not crash."""
    d = _solution_to_dict(PointingEstimate())
    json.dumps(d, default=str)  # must not raise
    assert d["RA"] is None
    assert d["camera_solve"] == {"RA": None, "Dec": None, "Roll": None}
    assert d["solve_source"] is None
    assert d["Matches"] == 0  # diagnostics default


@pytest.mark.unit
def test_top_level_radec_is_aligned_estimate():
    """Old contract: top-level RA/Dec/Roll == aligned (eyepiece) pointing,
    NOT the camera centre."""
    d = _solution_to_dict(_populated())
    assert (d["RA"], d["Dec"], d["Roll"]) == (10.5, 20.2, 5.0)


@pytest.mark.unit
def test_camera_solve_is_camera_solve_cell():
    d = _solution_to_dict(_populated())
    assert d["camera_solve"] == {"RA": 10.0, "Dec": 20.0, "Roll": 5.0}
    assert d["camera_center"]["RA"] == 10.0


@pytest.mark.unit
def test_diagnostics_and_timing_keys_preserved():
    d = _solution_to_dict(_populated())
    assert d["FOV"] == 10.2
    assert d["Matches"] == 12
    assert d["solve_source"] == "CAM"
    # solve_time keeps the old key name (estimate_time under the hood)
    assert d["solve_time"] == 1234.5
    assert d["cam_solve_time"] == 1234.5
    json.dumps(d, default=str)  # full payload is JSON-serializable


@pytest.mark.unit
def test_raw_png_preserves_16bit_values():
    """A 12-bit sensor frame must survive the PNG round trip intact.

    Rendering uint16 via Image.fromarray(..., mode="L") reinterprets the
    16-bit buffer as 8-bit and yields interleaved-byte noise that still looks
    like a plausible image -- convincing enough to waste a night of captures
    before anyone checks the histogram. Pin the values.
    """
    import io

    import numpy as np
    from PIL import Image

    from PiFinder.api_extensions import _raw_to_png as to_png

    frame = np.array([[0, 1, 255, 256], [4095, 2048, 300, 65535]], dtype=np.uint16)

    buf = io.BytesIO()
    to_png(frame).save(buf, format="PNG")
    buf.seek(0)
    restored = np.asarray(Image.open(buf))

    np.testing.assert_array_equal(restored, frame)


@pytest.mark.unit
def test_full_raw_request_is_one_shot():
    """One request yields one frame; the camera must not keep publishing 4 MB."""
    from PiFinder.state import SharedStateObj

    state = SharedStateObj()
    assert state.cam_raw_full_requested() is False

    state.request_cam_raw_full()
    assert state.cam_raw_full_requested() is True

    state.set_cam_raw_full(object())
    assert state.cam_raw_full_requested() is False
