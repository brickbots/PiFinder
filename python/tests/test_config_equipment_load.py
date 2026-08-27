"""Config must survive an equipment section it cannot decode (#291).

A telescope written with a string aperture aborted ``main()`` at
``Equipment.from_dict`` before the UI came up — the PiFinder booted to
nothing until someone ssh'd in and hand-edited config.json.  The web forms
validate everything they write now, but a config from an older release (or
a hand edit) must still boot.
"""

import json

import pytest

from PiFinder import config


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config.utils, "data_dir", tmp_path)
    return tmp_path


def write_config(config_dir, equipment):
    (config_dir / "config.json").write_text(json.dumps({"equipment": equipment}))


@pytest.mark.unit
def test_undecodable_equipment_falls_back_to_defaults(config_dir, caplog):
    write_config(
        config_dir,
        {
            "telescopes": [
                {
                    "make": "Celestron",
                    "name": "Deep Space",
                    "aperture_mm": "not a number",
                    "focal_length_mm": "1960",
                    "obstruction_perc": 13.0,
                    "mount_type": "equatorial",
                    "flip_image": True,
                    "flop_image": True,
                    "reverse_arrow_a": True,
                    "reverse_arrow_b": True,
                }
            ],
            "eyepieces": [],
        },
    )

    cfg = config.Config()

    assert cfg.equipment.telescopes  # the defaults, not an aborted boot
    assert "Could not load saved equipment" in caplog.text


@pytest.mark.unit
def test_decimal_aperture_written_as_a_string_still_loads(config_dir):
    """The exact config from #291: measurements are floats, so "279.5" is
    now a value the dataclasses can read rather than one that aborts."""
    write_config(
        config_dir,
        {
            "telescopes": [
                {
                    "make": "Celestron",
                    "name": "Deep Space",
                    "aperture_mm": "279.5",
                    "focal_length_mm": "1960",
                    "obstruction_perc": 13.0,
                    "mount_type": "equatorial",
                    "flip_image": True,
                    "flop_image": True,
                    "reverse_arrow_a": True,
                    "reverse_arrow_b": True,
                }
            ],
            "eyepieces": [],
        },
    )

    cfg = config.Config()

    assert cfg.equipment.telescopes[0].aperture_mm == 279.5
    assert cfg.equipment.telescopes[0].name == "Deep Space"
