from PiFinder.keyboard_interface import KeyboardInterface


def test_text_key_round_trip():
    keycode = KeyboardInterface.text_key("A")

    assert KeyboardInterface.is_text_key(keycode)
    assert KeyboardInterface.text_from_keycode(keycode) == "A"


def test_regular_keys_are_not_text_keys():
    assert not KeyboardInterface.is_text_key(KeyboardInterface.LEFT)
    assert not KeyboardInterface.is_text_key(KeyboardInterface.POWER_BTN)
