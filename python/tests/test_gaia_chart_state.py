"""
The Gaia chart generator reads SQM and location from the current frame's
state snapshot (CurrentSnapshot), not through the shared-state manager.
"""

from types import SimpleNamespace

import pytest

# Installs the ``_()`` gettext builtin that PiFinder.ui modules rely on.
import PiFinder.i18n  # noqa: F401
from PiFinder.object_images.gaia_chart import GaiaChartGenerator
from PiFinder.object_images.star_catalog import CatalogState
from PiFinder.state import SQM, Location
from PiFinder.state_snapshot import StateSnapshot
from PiFinder.ui.base import CurrentSnapshot, UIModule

pytestmark = pytest.mark.unit


def test_the_generator_reads_sqm_and_location_from_the_frame_snapshot(monkeypatch):
    sqm = SQM(value=19.5)
    location = Location(lat=51.0, lon=4.4, lock=True)
    monkeypatch.setattr(
        UIModule, "snapshot", StateSnapshot({"sqm": sqm, "location": location})
    )
    config = SimpleNamespace(equipment=SimpleNamespace(active_eyepiece=None))
    generator = GaiaChartGenerator(config, CurrentSnapshot())
    seen = []
    monkeypatch.setattr(
        generator, "get_limiting_magnitude", lambda s: seen.append(s) or 12.0
    )

    key = generator.get_cache_key(SimpleNamespace(catalog_code="M", sequence=1))
    assert key == "M1_none_lm12.0"
    assert seen == [sqm]

    started = []
    generator.catalog = SimpleNamespace(
        state=CatalogState.NOT_LOADED,
        start_background_load=lambda lat, lm: started.append((lat, lm)),
    )
    generator.ensure_catalog_loading()
    assert started == [(51.0, 12.0)]
