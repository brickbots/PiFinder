"""Request-level regression tests for the equipment forms (#569).

Reproduced against a live PiFinder during the 2.6.1 test pass::

    POST /equipment/add_eyepiece/-1  focal_length_mm=7,5  field_stop=8,0
      -> HTTP 200 + "Eyepiece added, restart your PiFinder to use"
      -> eyepiece count unchanged.  Nothing was saved.

The handlers caught the parse error, logged it and rendered the success
template regardless.  The Selenium suite runs en-US and structurally
cannot catch a decimal-comma bug, so cover it here: these drive the real
routes through Flask's test client and run in CI.
"""

import pytest

from PiFinder import server as server_module
from PiFinder.equipment import Equipment, Eyepiece, Telescope

SUCCESS_EYEPIECE = "Eyepiece added"
SUCCESS_INSTRUMENT = "Instrument Added"


def a_telescope(name="Dobsonian"):
    return Telescope(
        make="Generic",
        name=name,
        aperture_mm=200,
        focal_length_mm=1000,
        obstruction_perc=17.0,
        mount_type="alt/az",
        flip_image=False,
        flop_image=False,
        reverse_arrow_a=False,
        reverse_arrow_b=False,
    )


def an_eyepiece(name="Plossl", focal_length_mm=25):
    return Eyepiece(
        make="Generic",
        name=name,
        focal_length_mm=focal_length_mm,
        afov=50,
        field_stop=21.2,
    )


class FakeConfig:
    """Stands in for config.Config() so no real config file is touched."""

    def __init__(self):
        self.equipment = Equipment(
            telescopes=[a_telescope()], eyepieces=[an_eyepiece()]
        )
        self.saved = False

    def save_equipment(self):
        self.saved = True


@pytest.fixture
def equipment_client(monkeypatch):
    cfg = FakeConfig()
    monkeypatch.setattr(server_module.config, "Config", lambda: cfg)

    server = server_module.Server()
    server.app.testing = True
    client = server.app.test_client()
    with client.session_transaction() as session:
        session["authenticated"] = True
    return client, cfg


def eyepiece_form(**overrides):
    form = {
        "make": "TeleVue",
        "name": "Nagler",
        "focal_length_mm": "7.5",
        "afov": "82",
        "field_stop": "8.0",
    }
    form.update(overrides)
    return form


def instrument_form(**overrides):
    form = {
        "make": "Celestron",
        "name": "C11",
        "aperture": "279.4",
        "focal_length_mm": "2800",
        "obstruction_perc": "34",
        "mount_type": "alt/az",
    }
    form.update(overrides)
    return form


# ── the reported failure: a comma decimal saved nothing ────────────


@pytest.mark.unit
def test_eyepiece_with_comma_decimal_is_saved(equipment_client):
    client, cfg = equipment_client

    response = client.post(
        "/equipment/add_eyepiece/-1",
        data=eyepiece_form(focal_length_mm="7,5", field_stop="8,0"),
    )

    assert response.status_code == 200
    assert SUCCESS_EYEPIECE in response.text
    added = [ep for ep in cfg.equipment.eyepieces if ep.name == "Nagler"]
    assert len(added) == 1
    assert added[0].focal_length_mm == 7.5
    assert added[0].field_stop == 8.0
    assert cfg.saved


@pytest.mark.unit
def test_instrument_with_comma_decimal_is_saved(equipment_client):
    client, cfg = equipment_client

    response = client.post(
        "/equipment/add_instrument/-1", data=instrument_form(aperture="279,4")
    )

    assert response.status_code == 200
    assert SUCCESS_INSTRUMENT in response.text
    added = [t for t in cfg.equipment.telescopes if t.name == "C11"]
    assert len(added) == 1
    assert added[0].aperture_mm == 279.4
    assert cfg.saved


# ── a rejected entry must not report success ───────────────────────


@pytest.mark.unit
@pytest.mark.parametrize(
    "overrides",
    [
        {"focal_length_mm": "not a number"},
        {"focal_length_mm": "0"},
        {"name": ""},
        {"afov": "400"},
        {"field_stop": "-1"},
    ],
    ids=[
        "garbage",
        "zero-focal-length",
        "blank-name",
        "afov-too-wide",
        "negative-stop",
    ],
)
def test_invalid_eyepiece_is_rejected_not_reported_as_added(
    equipment_client, overrides
):
    client, cfg = equipment_client
    before = list(cfg.equipment.eyepieces)

    response = client.post(
        "/equipment/add_eyepiece/-1", data=eyepiece_form(**overrides)
    )

    assert response.status_code == 200
    assert SUCCESS_EYEPIECE not in response.text
    assert cfg.equipment.eyepieces == before
    assert not cfg.saved


@pytest.mark.unit
@pytest.mark.parametrize(
    "overrides",
    [
        {"name": ""},
        {"aperture": "abc"},
        {"obstruction_perc": "120"},
        {"focal_length_mm": ""},
        {"mount_type": "hammock"},
    ],
    ids=[
        "blank-name",
        "garbage",
        "obstruction-over-100",
        "blank-focal-length",
        "bad-mount",
    ],
)
def test_invalid_instrument_is_rejected_not_reported_as_added(
    equipment_client, overrides
):
    client, cfg = equipment_client
    before = list(cfg.equipment.telescopes)

    response = client.post(
        "/equipment/add_instrument/-1", data=instrument_form(**overrides)
    )

    assert response.status_code == 200
    assert SUCCESS_INSTRUMENT not in response.text
    assert cfg.equipment.telescopes == before
    assert not cfg.saved


@pytest.mark.unit
def test_rejected_eyepiece_comes_back_with_the_typed_values(equipment_client):
    """The form is re-rendered so the user can fix one field, not retype all."""
    client, _ = equipment_client

    response = client.post(
        "/equipment/add_eyepiece/-1",
        data=eyepiece_form(name="Nagler", focal_length_mm="seven"),
    )

    assert 'action="/equipment/add_eyepiece/-1"' in response.text
    assert 'value="Nagler"' in response.text
    assert 'value="seven"' in response.text
    assert "must be a number" in response.text


@pytest.mark.unit
def test_editing_an_eyepiece_with_a_bad_value_leaves_it_untouched(equipment_client):
    client, cfg = equipment_client
    original = cfg.equipment.eyepieces[0]

    response = client.post(
        "/equipment/add_eyepiece/0", data=eyepiece_form(focal_length_mm="")
    )

    assert response.status_code == 200
    assert cfg.equipment.eyepieces[0] == original
    assert not cfg.saved


# ── indices nobody owns used to raise IndexError as a 500 ──────────


@pytest.mark.unit
@pytest.mark.parametrize(
    "path",
    [
        "/equipment/edit_eyepiece/99",
        "/equipment/edit_instrument/99",
        "/equipment/delete_eyepiece/99",
        "/equipment/delete_instrument/99",
        "/equipment/set_active_eyepiece/99",
        "/equipment/set_active_instrument/99",
    ],
)
def test_out_of_range_index_does_not_crash(equipment_client, path):
    client, cfg = equipment_client

    response = client.get(path)

    assert response.status_code == 200
    assert len(cfg.equipment.eyepieces) == 1
    assert len(cfg.equipment.telescopes) == 1
    assert not cfg.saved


@pytest.mark.unit
def test_new_eyepiece_form_starts_blank(equipment_client):
    """Zeros are not values an eyepiece may keep, so don't pre-fill them."""
    client, _ = equipment_client

    response = client.get("/equipment/edit_eyepiece/-1")

    assert response.status_code == 200
    assert 'id="focal_length_mm" type="text" inputmode="decimal"' in response.text
    assert 'value=""' in response.text


@pytest.mark.unit
def test_stored_whole_millimetres_render_without_a_trailing_zero(equipment_client):
    """focal_length_mm is a float now; the table must still read "1000"."""
    client, _ = equipment_client

    response = client.get("/equipment")

    assert "<td>1000</td>" in response.text
    assert "<td>1000.0</td>" not in response.text
