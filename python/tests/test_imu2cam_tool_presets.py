"""Parity between the imu2cam tool's presets and the production tables.

The visual derivation tool at PiFinder/pointing_model/docs/imu2cam_tool.html
embeds one preset per shipped build variant: the variant's expected
q_imu2cam quaternion and its paired rotate_amount. Those presets are the
tool's self-validation ("does this physical arrangement reproduce the
shipped value?"), so they must track the production tables exactly:

    - ImuDeadReckoning._q_imu2cam()  (pointing_model/imu_dead_reckoning.py)
    - SCREEN_ROTATE_AMOUNTS          (camera_interface.py)

If you change either table, update the tool's JSON block (and vice versa).
"""

import json
import re
from pathlib import Path

import numpy as np
import pytest
import quaternion  # noqa: F401  (numpy-quaternion extends the np namespace)

from PiFinder.camera_interface import SCREEN_ROTATE_AMOUNTS
from PiFinder.pointing_model.imu_dead_reckoning import ImuDeadReckoning

TOOL_PATH = (
    Path(__file__).parent.parent
    / "PiFinder"
    / "pointing_model"
    / "docs"
    / "imu2cam_tool.html"
)


def _load_presets():
    html = TOOL_PATH.read_text(encoding="utf-8")
    match = re.search(
        r'<script type="application/json" id="imu2cam-presets">(.*?)</script>',
        html,
        re.DOTALL,
    )
    assert match, "presets JSON block not found in imu2cam_tool.html"
    return json.loads(match.group(1))["presets"]


PRESETS = _load_presets()


@pytest.mark.unit
def test_presets_cover_every_screen_direction():
    assert {p["key"] for p in PRESETS} == set(SCREEN_ROTATE_AMOUNTS)


@pytest.mark.unit
@pytest.mark.parametrize("preset", PRESETS, ids=lambda p: p["key"])
def test_preset_quaternion_matches_table(preset):
    expected = quaternion.as_float_array(ImuDeadReckoning._q_imu2cam(preset["key"]))
    embedded = np.array(preset["q"])
    # q and -q are the same rotation (double cover); compare up to sign.
    assert np.allclose(embedded, expected, atol=1e-9) or np.allclose(
        embedded, -expected, atol=1e-9
    ), f"tool preset '{preset['key']}' drifted from _q_imu2cam"


@pytest.mark.unit
@pytest.mark.parametrize("preset", PRESETS, ids=lambda p: p["key"])
def test_preset_rotate_amount_matches_table(preset):
    assert preset["rotate"] == SCREEN_ROTATE_AMOUNTS[preset["key"]], (
        f"tool preset '{preset['key']}' rotate_amount drifted from "
        "SCREEN_ROTATE_AMOUNTS"
    )
