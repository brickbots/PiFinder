"""One-time migration for persisted asteroid filter selections."""

import json

import pytest

from PiFinder import utils
from PiFinder.config import Config


def write_config_files(tmp_path, saved):
    (tmp_path / "default_config.json").write_text(
        json.dumps(
            {
                "filter.selected_catalogs": ["NGC", "MP"],
                "filter.object_types": ["Gx", "AS"],
            }
        )
    )
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "config.json").write_text(json.dumps(saved))
    return data_dir


@pytest.mark.unit
def test_existing_saved_filters_gain_asteroids_once(tmp_path, monkeypatch):
    data_dir = write_config_files(
        tmp_path,
        {
            "filter.selected_catalogs": ["NGC"],
            "filter.object_types": ["Gx"],
        },
    )
    monkeypatch.setattr(utils, "data_dir", data_dir)
    monkeypatch.setattr(utils, "pifinder_dir", tmp_path)

    config = Config()
    assert config.get_option("filter.selected_catalogs") == ["NGC", "MP"]
    assert config.get_option("filter.object_types") == ["Gx", "AS"]

    # Once migrated, an explicit user choice remains authoritative.
    config.set_option("filter.selected_catalogs", ["NGC"])
    config.set_option("filter.object_types", ["Gx"])
    reloaded = Config()
    assert reloaded.get_option("filter.selected_catalogs") == ["NGC"]
    assert reloaded.get_option("filter.object_types") == ["Gx"]
