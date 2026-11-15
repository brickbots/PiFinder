"""The signs of the custom track rates for each pier side, and their store."""

import json

import pytest

from PiFinder.mount_rate_signs import AxisSign, RateSigns, RateSignStore

pytestmark = pytest.mark.unit

MODEL = "Telescope Simulator"
WITH = (True, False)
AGAINST = (False, True)
NONE = (False, False)


def measure(signs: RateSigns, ra=NONE, dec=NONE) -> None:
    signs.measure(*ra, *dec)


def test_store_writes_and_reads_the_signs_of_each_model(tmp_path):
    path = tmp_path / "signs.json"
    store = RateSignStore(path)
    assert store.load(MODEL) == {}
    store.save(MODEL, "PIER_EAST", [-1.0, 1.0])
    store.save(MODEL, "PIER_WEST", [None, -1.0])
    store.save("Other", "PIER_EAST", [1.0, 1.0])
    assert json.loads(path.read_text())[MODEL] == {
        "PIER_EAST": [-1.0, 1.0],
        "PIER_WEST": [None, -1.0],
    }
    again = RateSignStore(path)
    assert again.load(MODEL) == {"PIER_EAST": [-1.0, 1.0], "PIER_WEST": [None, -1.0]}
    assert again.load("Other") == {"PIER_EAST": [1.0, 1.0]}


def test_store_skips_bad_content(tmp_path):
    path = tmp_path / "signs.json"
    path.write_text("not json")
    assert RateSignStore(path).load(MODEL) == {}
    path.write_text(
        json.dumps({MODEL: {"PIER_EAST": [2, "x"], "PIER_UP": [1, 1], "X": 3}})
    )
    assert RateSignStore(path).load(MODEL) == {"PIER_EAST": [1.0, None]}
    path.write_text(json.dumps({MODEL: [1, 2]}))
    assert RateSignStore(path).load(MODEL) == {}


def test_axis_sign_confirms_after_two_and_turns():
    axis = AxisSign(1.0)
    # Not confirmed: one measurement against turns it.
    assert not axis.measure(*AGAINST)
    assert axis.sign == -1.0 and not axis.confirmed
    # Two with the request in a row confirm it.
    assert not axis.measure(*WITH)
    assert not axis.measure(*NONE)
    assert not axis.measure(*WITH)
    assert axis.measure(*WITH)
    assert axis.confirmed
    # Confirmed: one against is not enough, two in a row turn it, and the
    # turned sign is confirmed.
    assert not axis.measure(*AGAINST)
    assert not axis.measure(*WITH)
    assert not axis.measure(*AGAINST)
    assert axis.sign == -1.0
    assert axis.measure(*AGAINST)
    assert axis.sign == 1.0 and axis.confirmed


def test_confirmed_sign_is_stored_for_the_pier_side():
    store = RateSignStore()
    signs = RateSigns(store)
    signs.load(MODEL)
    assert signs.set_pier("PIER_WEST")
    assert not signs.set_pier("PIER_WEST")
    measure(signs, dec=AGAINST)
    assert signs.dec.sign == -1.0
    assert store.load(MODEL) == {}
    measure(signs, dec=WITH)
    measure(signs, dec=WITH)
    assert store.load(MODEL) == {"PIER_WEST": [None, -1.0]}
    measure(signs, ra=WITH)
    measure(signs, ra=WITH)
    assert store.load(MODEL) == {"PIER_WEST": [-1.0, -1.0]}


def test_pier_flip_uses_the_stored_sign_of_the_other_side_at_once():
    store = RateSignStore()
    store.save(MODEL, "PIER_EAST", [-1.0, 1.0])
    store.save(MODEL, "PIER_WEST", [-1.0, -1.0])
    signs = RateSigns(store)
    signs.load(MODEL)
    signs.set_pier("PIER_EAST")
    assert (signs.dec.sign, signs.dec.confirmed) == (1.0, True)
    signs.set_pier("PIER_WEST")
    assert (signs.dec.sign, signs.dec.confirmed) == (-1.0, True)
    # A stored sign turns only after two measurements against, and the
    # store gets the new sign.
    measure(signs, dec=AGAINST)
    assert signs.dec.sign == -1.0
    measure(signs, dec=AGAINST)
    assert signs.dec.sign == 1.0
    assert store.load(MODEL)["PIER_WEST"] == [-1.0, 1.0]
    assert store.load(MODEL)["PIER_EAST"] == [-1.0, 1.0]


def test_pier_flip_without_a_stored_sign_learns_that_side():
    store = RateSignStore()
    store.save(MODEL, "PIER_EAST", [-1.0, 1.0])
    signs = RateSigns(store)
    signs.load(MODEL)
    signs.set_pier("PIER_EAST")
    signs.set_pier("PIER_WEST")
    # The sign of the east side, not confirmed for the west side.
    assert (signs.dec.sign, signs.dec.confirmed) == (1.0, False)
    measure(signs, dec=AGAINST)
    assert signs.dec.sign == -1.0
    measure(signs, dec=WITH)
    measure(signs, dec=WITH)
    assert store.load(MODEL) == {
        "PIER_EAST": [-1.0, 1.0],
        "PIER_WEST": [None, -1.0],
    }
    # Back east: the stored sign at once.
    signs.set_pier("PIER_EAST")
    assert (signs.dec.sign, signs.dec.confirmed) == (1.0, True)


def test_mount_without_a_pier_side_has_one_sign_that_is_not_stored():
    store = RateSignStore()
    store.save(MODEL, "PIER_EAST", [1.0, -1.0])
    signs = RateSigns(store)
    signs.load(MODEL)
    assert not signs.set_pier(None)
    assert (signs.ra.sign, signs.dec.sign) == (-1.0, 1.0)
    measure(signs, dec=WITH)
    measure(signs, dec=WITH)
    assert signs.dec.confirmed
    assert store.load(MODEL) == {"PIER_EAST": [1.0, -1.0]}


def test_drift_turn_is_not_confirmed():
    signs = RateSigns()
    signs.load(MODEL)
    signs.set_pier("PIER_EAST")
    signs.dec.turn()
    assert (signs.dec.sign, signs.dec.confirmed) == (-1.0, False)
    assert signs.store.load(MODEL) == {}
