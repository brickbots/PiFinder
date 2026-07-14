#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is runs the keyboard matrix
and adds keys to the provided queue

"""

from time import monotonic, sleep, time
import libinput
from PiFinder.keyboard_interface import KeyboardInterface
import RPi.GPIO as GPIO
import logging
from PiFinder.multiproclogging import MultiprocLogging

logger = logging.getLogger("Keyboard.Pi")


KEY_ESC = 1
KEY_1 = 2
KEY_2 = 3
KEY_3 = 4
KEY_4 = 5
KEY_5 = 6
KEY_6 = 7
KEY_7 = 8
KEY_8 = 9
KEY_9 = 10
KEY_0 = 11
KEY_MINUS = 12
KEY_EQUAL = 13
KEY_BACKSPACE = 14
KEY_Q = 16
KEY_W = 17
KEY_E = 18
KEY_R = 19
KEY_T = 20
KEY_Y = 21
KEY_U = 22
KEY_I = 23
KEY_O = 24
KEY_P = 25
KEY_ENTER = 28
KEY_LEFTCTRL = 29
KEY_A = 30
KEY_S = 31
KEY_D = 32
KEY_F = 33
KEY_G = 34
KEY_H = 35
KEY_J = 36
KEY_K = 37
KEY_L = 38
KEY_LEFTSHIFT = 42
KEY_Z = 44
KEY_X = 45
KEY_C = 46
KEY_V = 47
KEY_B = 48
KEY_N = 49
KEY_M = 50
KEY_RIGHTSHIFT = 54
KEY_LEFTALT = 56
KEY_SPACE = 57
KEY_KP7 = 71
KEY_KP8 = 72
KEY_KP9 = 73
KEY_KPMINUS = 74
KEY_KP4 = 75
KEY_KP5 = 76
KEY_KP6 = 77
KEY_KPPLUS = 78
KEY_KP1 = 79
KEY_KP2 = 80
KEY_KP3 = 81
KEY_KP0 = 82
KEY_KPENTER = 96
KEY_RIGHTCTRL = 97
KEY_RIGHTALT = 100
KEY_UP = 103
KEY_LEFT = 105
KEY_RIGHT = 106
KEY_DOWN = 108

PHYSICAL_HOLD_SECONDS = 1.0
PHYSICAL_REPEAT_SECONDS = 0.08
PHYSICAL_CTRL_KEYS = {KEY_LEFTCTRL, KEY_RIGHTCTRL}
PHYSICAL_SHIFT_KEYS = {KEY_LEFTSHIFT, KEY_RIGHTSHIFT}
PHYSICAL_ALT_KEYS = {KEY_LEFTALT, KEY_RIGHTALT}
PHYSICAL_MODIFIER_KEYS = PHYSICAL_CTRL_KEYS | PHYSICAL_SHIFT_KEYS | PHYSICAL_ALT_KEYS


class KeyboardPi(KeyboardInterface):
    def __init__(self, q):
        self.q = q

        # GPIO pin numbers for the rows and columns of the keyboard matrix
        self.cols = [16, 23, 26, 27, 21]
        self.rows = [19, 17, 18, 22, 20]
        self.power_gpio = 15

        # Timer for power-off debounce, and latch so we only emit
        # one POWER_BTN per physical press
        self.power_press_time = 0
        self.power_sent = False

        # fmt: off
        self.keymap = [
            7 , 8 , 9 , self.NA, self.UP,
            4 , 5 , 6 , self.PLUS, self.LEFT,
            1 , 2 , 3 , self.MINUS, self.DOWN,
            self.NA, 0 , self.NA, self.SQUARE, self.RIGHT,
            self.LEFT, self.UP , self.DOWN , self.RIGHT, self.SQUARE,
        ]
        # If SQUARE is pressed together with key, ALT_<key> is sent
        self.alt_keymap = [
            self.NA, self.NA, self.NA, self.NA, self.ALT_UP,
            self.NA, self.NA, self.NA, self.ALT_PLUS, self.ALT_LEFT,
            self.NA, self.NA, self.NA, self.ALT_MINUS, self.ALT_DOWN,
            self.NA, self.ALT_0, self.NA, self.NA, self.ALT_RIGHT,
            self.ALT_LEFT, self.ALT_UP, self.ALT_DOWN, self.ALT_RIGHT, self.NA,
        ]
        self.long_keymap = [
            self.NA, self.NA, self.NA, self.NA, self.LNG_UP,
            self.NA, self.NA, self.NA, self.NA, self.LNG_LEFT,
            self.NA, self.NA, self.NA, self.NA, self.LNG_DOWN,
            self.NA, self.NA, self.NA, self.LNG_SQUARE, self.LNG_RIGHT,
            self.LNG_LEFT, self.LNG_UP, self.LNG_DOWN, self.LNG_RIGHT, self.LNG_SQUARE,
        ]
        # fmt: on

        # Derive keycodes from the keymap so they track the matrix layout
        # (cols/rows) rather than being hard-coded. SQUARE is the brightness/
        # alt-chord modifier; the d-pad up/down buttons auto-repeat when held.
        self.square_keycodes = {
            i for i, v in enumerate(self.keymap) if v == self.SQUARE
        }
        self.repeat_keycodes = {
            i for i, v in enumerate(self.keymap) if v in (self.UP, self.DOWN)
        }

        # physical keyboard support init
        self.li_kb = libinput.LibInput(context_type=libinput.ContextType.UDEV)
        self.li_kb.assign_seat("seat0")
        self.physical_pressed = set()
        self.physical_press_times: dict[int, float] = {}
        self.physical_last_repeat_times: dict[int, float] = {}
        self.physical_hold_sent: set[int] = set()
        self.physical_press_modifiers: dict[int, set[int]] = {}

        self.text_physical_key_mapping: dict[int, int] = {
            KEY_SPACE: self.text_key(" "),
            KEY_A: self.text_key("a"),
            KEY_B: self.text_key("b"),
            KEY_C: self.text_key("c"),
            KEY_D: self.text_key("d"),
            KEY_E: self.text_key("e"),
            KEY_F: self.text_key("f"),
            KEY_G: self.text_key("g"),
            KEY_H: self.text_key("h"),
            KEY_I: self.text_key("i"),
            KEY_J: self.text_key("j"),
            KEY_K: self.text_key("k"),
            KEY_L: self.text_key("l"),
            KEY_M: self.text_key("m"),
            KEY_N: self.text_key("n"),
            KEY_O: self.text_key("o"),
            KEY_P: self.text_key("p"),
            KEY_Q: self.text_key("q"),
            KEY_R: self.text_key("r"),
            KEY_S: self.text_key("s"),
            KEY_T: self.text_key("t"),
            KEY_U: self.text_key("u"),
            KEY_V: self.text_key("v"),
            KEY_W: self.text_key("w"),
            KEY_X: self.text_key("x"),
            KEY_Y: self.text_key("y"),
            KEY_Z: self.text_key("z"),
        }
        self.shift_text_physical_key_mapping: dict[int, int] = {
            key: self.text_key(chr(value - self.TEXT_BASE).upper())
            for key, value in self.text_physical_key_mapping.items()
        }
        self.physical_key_mapping: dict[int, int] = {
            KEY_UP: self.UP,
            KEY_DOWN: self.DOWN,
            KEY_LEFT: self.LEFT,
            KEY_RIGHT: self.RIGHT,
            KEY_ENTER: self.SQUARE,
            KEY_KPENTER: self.SQUARE,
            KEY_ESC: self.LEFT,
            KEY_BACKSPACE: self.MINUS,
            KEY_EQUAL: self.PLUS,
            KEY_KPPLUS: self.PLUS,
            KEY_MINUS: self.MINUS,
            KEY_KPMINUS: self.MINUS,
            KEY_1: 1,
            KEY_2: 2,
            KEY_3: 3,
            KEY_4: 4,
            KEY_5: 5,
            KEY_6: 6,
            KEY_7: 7,
            KEY_8: 8,
            KEY_9: 9,
            KEY_0: 0,
            KEY_KP1: 1,
            KEY_KP2: 2,
            KEY_KP3: 3,
            KEY_KP4: 4,
            KEY_KP5: 5,
            KEY_KP6: 6,
            KEY_KP7: 7,
            KEY_KP8: 8,
            KEY_KP9: 9,
            KEY_KP0: 0,
        }
        self.alt_physical_key_mapping: dict[int, int] = {
            KEY_UP: self.ALT_UP,
            KEY_DOWN: self.ALT_DOWN,
            KEY_LEFT: self.ALT_LEFT,
            KEY_RIGHT: self.ALT_RIGHT,
            KEY_EQUAL: self.ALT_PLUS,
            KEY_KPPLUS: self.ALT_PLUS,
            KEY_MINUS: self.ALT_MINUS,
            KEY_KPMINUS: self.ALT_MINUS,
            KEY_0: self.ALT_0,
            KEY_KP0: self.ALT_0,
            KEY_ENTER: self.ALT_SQUARE,
            KEY_KPENTER: self.ALT_SQUARE,
        }
        self.long_physical_key_mapping: dict[int, int] = {
            KEY_UP: self.LNG_UP,
            KEY_DOWN: self.LNG_DOWN,
            KEY_LEFT: self.LNG_LEFT,
            KEY_RIGHT: self.LNG_RIGHT,
            KEY_ENTER: self.LNG_SQUARE,
            KEY_KPENTER: self.LNG_SQUARE,
        }

    def _remember_physical_press(self, key: int) -> None:
        if key in self.physical_pressed:
            return

        self.physical_press_times[key] = monotonic()
        self.physical_last_repeat_times.pop(key, None)
        self.physical_hold_sent.discard(key)
        self.physical_press_modifiers[key] = set(
            self.physical_pressed & PHYSICAL_MODIFIER_KEYS
        )
        self.physical_pressed.add(key)

    def _forget_physical_press(self, key: int) -> None:
        self.physical_pressed.discard(key)
        self.physical_press_times.pop(key, None)
        self.physical_last_repeat_times.pop(key, None)
        self.physical_hold_sent.discard(key)
        self.physical_press_modifiers.pop(key, None)

    def _physical_key_modifiers(self, key: int) -> set[int]:
        return (
            set(self.physical_press_modifiers.get(key, set()))
            | (self.physical_pressed & PHYSICAL_MODIFIER_KEYS)
        )

    def _get_physical_hold_key(self) -> int:
        now = monotonic()
        held_keys = sorted(
            self.physical_pressed,
            key=lambda key: self.physical_press_times.get(key, now),
        )

        for key in held_keys:
            if key in PHYSICAL_MODIFIER_KEYS:
                continue

            press_time = self.physical_press_times.get(key)
            if press_time is None or now - press_time < PHYSICAL_HOLD_SECONDS:
                continue

            modifiers = self._physical_key_modifiers(key)
            if modifiers & PHYSICAL_ALT_KEYS:
                continue

            if key in [KEY_UP, KEY_DOWN]:
                if modifiers:
                    continue

                last_repeat = self.physical_last_repeat_times.get(key)
                if last_repeat is None or now - last_repeat >= PHYSICAL_REPEAT_SECONDS:
                    self.physical_last_repeat_times[key] = now
                    return self.physical_key_mapping[key]
                continue

            if key in self.physical_hold_sent:
                continue

            mapped_key = self.long_physical_key_mapping.get(key)
            if mapped_key is not None:
                self.physical_hold_sent.add(key)
                return mapped_key

        return 0

    def get_keyboard_key(self) -> int:
        """
        Checks libinput keyboard and maps key events to PiFinder keycodes.

        Returns 0 for no key registered
        """
        while True:
            while True:
                if hold_key := self._get_physical_hold_key():
                    return hold_key

                self.li_kb._libinput.libinput_dispatch(self.li_kb._li)
                hevent = self.li_kb._libinput.libinput_get_event(self.li_kb._li)
                if not hevent:
                    return self._get_physical_hold_key()
                type_ = self.li_kb._libinput.libinput_event_get_type(hevent)

                if type_.is_keyboard():
                    kbev = libinput.KeyboardEvent(hevent, self.li_kb._libinput)
                    if kbev.key_state == libinput.constant.KeyState.PRESSED:
                        self._remember_physical_press(kbev.key)
                        continue
                    if kbev.key_state != libinput.constant.KeyState.RELEASED:
                        continue

                    press_modifiers = self.physical_press_modifiers.get(
                        kbev.key, set()
                    )
                    release_modifiers = (
                        set(self.physical_pressed) | set(press_modifiers)
                    )
                    was_hold_sent = kbev.key in self.physical_hold_sent
                    self._forget_physical_press(kbev.key)

                    if kbev.key in PHYSICAL_MODIFIER_KEYS:
                        continue
                    if was_hold_sent:
                        continue

                    alt_pressed = bool(PHYSICAL_ALT_KEYS & release_modifiers)
                    if alt_pressed:
                        mapped_key = self.alt_physical_key_mapping.get(kbev.key)
                        return mapped_key if mapped_key is not None else 0

                    ctrl_pressed = bool(PHYSICAL_CTRL_KEYS & release_modifiers)
                    shift_pressed = bool(PHYSICAL_SHIFT_KEYS & release_modifiers)
                    if ctrl_pressed or shift_pressed:
                        mapped_key = self.long_physical_key_mapping.get(kbev.key)
                        if mapped_key is not None:
                            return mapped_key
                        if ctrl_pressed:
                            return 0
                        return self.shift_text_physical_key_mapping.get(kbev.key, 0)

                    return self.physical_key_mapping.get(
                        kbev.key, self.text_physical_key_mapping.get(kbev.key, 0)
                    )

    def run_keyboard(self, log_queue):
        """
        scans keyboard matrix, puts release events in queue
        """
        MultiprocLogging.configurer(log_queue)

        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.rows, GPIO.IN)
        GPIO.setup(self.cols, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        # Setup power GPIO, no pullup needed, has it's own
        GPIO.setup(self.power_gpio, GPIO.IN)

        pressed = set()
        alt_sent = False
        hold_counter = 0
        hold_sent = False
        scan_freq = 60
        while True:
            # Check physical keyboard
            if keyboard_key := self.get_keyboard_key():
                self.q.put(keyboard_key)

            sleep(1 / scan_freq)
            if len(pressed) > 0:
                hold_counter += 1
                if hold_counter > scan_freq:
                    # Held for more than 1 second
                    if list(pressed)[-1] in self.repeat_keycodes:
                        # Up/Down arrows repeat
                        self.q.put(self.keymap[list(pressed)[-1]])
                        hold_counter = int(scan_freq / 1.05)
                    else:
                        if not alt_sent and not hold_sent:
                            keycode = pressed.pop()
                            pressed = set()
                            self.q.put(self.long_keymap[keycode])
                            hold_counter = 0
                            hold_sent = True
            else:
                hold_counter = 0
            for i in range(len(self.rows)):
                GPIO.setup(self.rows[i], GPIO.OUT, initial=GPIO.LOW)
                for j in range(len(self.cols)):
                    keycode = i * len(self.cols) + j
                    newval = GPIO.input(self.cols[j]) == GPIO.LOW
                    if newval and keycode not in pressed:
                        # initial press
                        pressed.add(keycode)
                    elif not newval and keycode in pressed:
                        # release
                        pressed.discard(keycode)
                        if pressed & self.square_keycodes:
                            # Released while SQUARE is pressed
                            alt_sent = True
                            self.q.put(self.alt_keymap[keycode])
                        else:
                            if keycode in self.square_keycodes and alt_sent:
                                alt_sent = False
                            elif hold_sent:
                                hold_sent = False
                            else:
                                self.q.put(self.keymap[keycode])
                GPIO.setup(self.rows[i], GPIO.IN)

            # Check power button explicitly it is wired directly to a GPIO
            # and goes LOW when pressed
            if not GPIO.input(self.power_gpio):
                if self.power_press_time == 0:
                    self.power_press_time = time()
                else:
                    if time() - self.power_press_time > 1 and not self.power_sent:
                        self.q.put(self.POWER_BTN)
                        self.power_sent = True
            else:
                self.power_press_time = 0
                self.power_sent = False


def run_keyboard(q, shared_state, log_queue):
    MultiprocLogging.configurer(log_queue)
    keyboard = KeyboardPi(q)
    keyboard.run_keyboard(log_queue)
