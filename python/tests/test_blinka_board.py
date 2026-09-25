import pytest

from PiFinder import blinka_board

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "model,expected",
    [
        ("Raspberry Pi Compute Module 4 Rev 1.0", "RASPBERRY_PI_CM4"),
        ("Raspberry Pi Compute Module 4S Rev 1.0", "RASPBERRY_PI_CM4S"),
        ("Raspberry Pi Compute Module 5 Rev 1.0", "RASPBERRY_PI_CM5"),
        ("Raspberry Pi Compute Module 5 Lite Rev 1.0", "RASPBERRY_PI_CM5_LITE"),
        ("Raspberry Pi 4 Model B Rev 1.4", None),
        ("Raspberry Pi 5 Model B Rev 1.0", None),
    ],
)
def test_board_for_model(model, expected):
    assert blinka_board.board_for_model(model) == expected


def _model(tmp_path, text):
    f = tmp_path / "model"
    f.write_bytes(text.encode() + b"\x00")
    return f


def test_sets_board_for_cm4_without_revision(tmp_path):
    env = {}
    got = blinka_board.force_pi_board(
        env,
        _model(tmp_path, "Raspberry Pi Compute Module 4 Rev 1.0"),
        tmp_path / "no-revision",
    )
    assert got == "RASPBERRY_PI_CM4"
    assert env == {"BLINKA_FORCEBOARD": "RASPBERRY_PI_CM4"}


def test_leaves_env_when_revision_exists(tmp_path):
    rev = tmp_path / "linux,revision"
    rev.write_bytes(b"\x00\xb0\x31\x41")
    env = {}
    got = blinka_board.force_pi_board(
        env, _model(tmp_path, "Raspberry Pi Compute Module 4 Rev 1.0"), rev
    )
    assert got is None and env == {}


def test_keeps_an_explicit_setting(tmp_path):
    env = {"BLINKA_FORCEBOARD": "RASPBERRY_PI_4B"}
    blinka_board.force_pi_board(
        env,
        _model(tmp_path, "Raspberry Pi Compute Module 4 Rev 1.0"),
        tmp_path / "no-revision",
    )
    assert env == {"BLINKA_FORCEBOARD": "RASPBERRY_PI_4B"}


def test_pi4_is_left_to_platformdetect(tmp_path):
    env = {}
    got = blinka_board.force_pi_board(
        env, _model(tmp_path, "Raspberry Pi 4 Model B Rev 1.4"), tmp_path / "none"
    )
    assert got is None and env == {}


def test_missing_model_file_changes_nothing(tmp_path):
    env = {}
    assert (
        blinka_board.force_pi_board(env, tmp_path / "nope", tmp_path / "none") is None
    )
    assert env == {}
