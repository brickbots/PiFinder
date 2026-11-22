"""A save writes only its own keys into config.json.

Every process -- UI, camera, web server, integrator -- holds its own
``Config``, read when it started.  Saving used to dump that whole dict back
to disk, which reverted whatever the other processes had saved since.  The
case that surfaced it: leaving Align (Day) restores a manual exposure, the
camera process saves ``camera_exp`` from its boot-time copy, and the
alignment the UI saved moments before is gone after the next restart.
"""

import json
import os
import stat

import pytest

from PiFinder import config


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config.utils, "data_dir", tmp_path)
    return tmp_path


def write_config(config_dir, settings):
    (config_dir / "config.json").write_text(json.dumps(settings))


def read_config(config_dir):
    return json.loads((config_dir / "config.json").read_text())


@pytest.mark.unit
def test_a_stale_process_saving_one_key_keeps_everything_else(config_dir):
    write_config(config_dir, {"camera_exp": 400000, "target_pixel": [256, 256]})
    ui = config.Config()
    camera = config.Config()  # loaded at the same boot, never reloaded

    ui.set_option("target_pixel", [120.0, 330.0])
    camera.set_option("camera_exp", 200000)

    on_disk = read_config(config_dir)
    assert on_disk["target_pixel"] == [120.0, 330.0]
    assert on_disk["camera_exp"] == 200000


@pytest.mark.unit
def test_an_alignment_survives_the_camera_saving_an_exposure(config_dir):
    """The reported sequence, end to end through a telescope's point."""
    write_config(config_dir, {"camera_exp": 400000})
    ui = config.Config()
    camera = config.Config()

    ui.save_target_pixel((120.0, 330.0))
    camera.set_option("camera_exp", 400000)

    assert config.Config().active_target_pixel() == (120.0, 330.0)


@pytest.mark.unit
def test_resetting_filters_removes_filters_saved_by_other_processes(config_dir):
    write_config(config_dir, {"filter.magnitude": 10, "language": "de"})
    stale = config.Config()
    other = config.Config()
    other.set_option("filter.altitude", 20)

    stale.reset_filters()

    assert read_config(config_dir) == {"language": "de"}


@pytest.mark.unit
def test_the_first_save_creates_the_file(config_dir):
    config.Config().set_option("language", "fr")

    assert read_config(config_dir) == {"language": "fr"}


@pytest.mark.unit
def test_an_unreadable_file_is_replaced_by_what_this_process_knows(config_dir):
    write_config(config_dir, {"language": "de", "camera_exp": 1})
    cfg = config.Config()
    (config_dir / "config.json").write_text('{"language": "de", "came')

    cfg.set_option("camera_exp", 2)

    assert read_config(config_dir) == {"language": "de", "camera_exp": 2}


@pytest.mark.unit
def test_the_write_keeps_the_file_mode_and_leaves_no_temp_file(config_dir):
    write_config(config_dir, {"language": "de"})
    os.chmod(config_dir / "config.json", 0o644)

    config.Config().set_option("language", "es")

    mode = stat.S_IMODE(os.stat(config_dir / "config.json").st_mode)
    assert mode == 0o644
    leftovers = [p.name for p in config_dir.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []
