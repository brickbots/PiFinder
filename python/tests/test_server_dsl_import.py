"""Regression tests for the DeepskyLog equipment import route.

The Flask migration (#331) changed the eyepiece-add call in
``/equipment/import_from_deepskylog`` from ``cfg.equipment.add_eyepiece(...)``
to ``cfg.equipment.eyepieces.add_eyepiece(...)``.  ``Equipment.eyepieces`` is
a plain list with no such method, so the first *new* eyepiece raised
``AttributeError`` — surfacing as "Internal Server Error" in the web UI — and
nothing was saved because ``save_equipment()`` comes after the import loop.

These tests drive the real route through Flask's test client with the
DeepskyLog API and config mocked out, using a real ``Equipment`` instance so
the plain-list attribute error would reproduce.
"""

import pytest

from PiFinder import server as server_module
from PiFinder.equipment import Equipment, Eyepiece


def _dsl_eyepiece(name, focal_length, afov=100, field_stop=0.0, make="TeleVue"):
    """An eyepiece dict shaped like pydeepskylog.dsl_eyepieces() output."""
    return {
        "name": name,
        "eyepiece_make": {"name": make},
        "focalLength": focal_length,
        "apparentFOV": afov,
        "field_stop_mm": field_stop,
    }


class FakeConfig:
    """Stands in for config.Config() so no real config file is read or written."""

    def __init__(self):
        self.equipment = Equipment(telescopes=[], eyepieces=[])
        self.saved = False

    def save_equipment(self):
        self.saved = True


@pytest.fixture
def import_client(monkeypatch):
    cfg = FakeConfig()
    monkeypatch.setattr(server_module.config, "Config", lambda: cfg)
    monkeypatch.setattr(server_module.pds, "dsl_instruments", lambda username: [])

    server = server_module.Server()
    server.app.testing = True
    client = server.app.test_client()
    with client.session_transaction() as session:
        session["authenticated"] = True
    return client, cfg


@pytest.mark.unit
def test_import_adds_new_eyepieces(monkeypatch, import_client):
    client, cfg = import_client
    monkeypatch.setattr(
        server_module.pds,
        "dsl_eyepieces",
        lambda username: [
            _dsl_eyepiece("Nagler 31 &quot;T5&quot; &amp; case", 31.0, afov=82),
            _dsl_eyepiece("Ethos 13", 13.0),
        ],
    )

    response = client.post(
        "/equipment/import_from_deepskylog", data={"dsl_name": "someuser"}
    )

    assert response.status_code == 200
    # add_eyepiece() keeps the list sorted by focal length, unlike append()
    assert [ep.focal_length_mm for ep in cfg.equipment.eyepieces] == [13.0, 31.0]
    # HTML entities in names are decoded
    assert cfg.equipment.eyepieces[1].name == 'Nagler 31 "T5" & case'
    assert cfg.saved


@pytest.mark.unit
def test_import_skips_existing_eyepiece(monkeypatch, import_client):
    client, cfg = import_client
    existing = Eyepiece(
        make="TeleVue", name="Ethos 13", focal_length_mm=13.0, afov=100, field_stop=0.0
    )
    cfg.equipment.add_eyepiece(existing)
    monkeypatch.setattr(
        server_module.pds,
        "dsl_eyepieces",
        lambda username: [_dsl_eyepiece("Ethos 13", 13.0)],
    )

    response = client.post(
        "/equipment/import_from_deepskylog", data={"dsl_name": "someuser"}
    )

    assert response.status_code == 200
    assert cfg.equipment.eyepieces == [existing]
