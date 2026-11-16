"""Fixtures of the satellite tests. The data and the helpers are in
satellite_helpers.py."""

import pytest

# Installs the ``_()`` gettext builtin the UI modules rely on. MUST precede any
# ``PiFinder.ui`` import.
import PiFinder.i18n  # noqa: F401

from PiFinder import utils
from PiFinder.ui import sat_groups
from PiFinder.ui.base import UIModule


@pytest.fixture
def fresh_sat_messages(monkeypatch):
    """An empty download queue of the Sat groups menu and no message on
    the screen."""
    monkeypatch.setattr(sat_groups, "downloads", sat_groups.GroupDownloads())
    monkeypatch.setattr(UIModule, "message_until", 0.0)


@pytest.fixture
def sat_dir(tmp_path, monkeypatch, fresh_sat_messages):
    """An empty satellite data directory that the device code uses."""
    directory = tmp_path / "satellites"
    monkeypatch.setattr(utils, "satellite_data_dir", directory)
    return directory
