#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is runs the keyboard matrix
and adds keys to the provided queue

"""

from time import sleep, time
import libinput
from PiFinder import keypad
from PiFinder.keyboard_interface import KeyboardInterface
import RPi.GPIO as GPIO
import logging
from PiFinder.multiproclogging import MultiprocLogging

logger = logging.getLogger("Keyboard.Pi")


class KeyboardPi(KeyboardInterface):
    def __init__(self, q):
        self.q = q

        # Matrix wiring and keymaps live in PiFinder.keypad, which is
        # import-safe (no RPi.GPIO / libinput) so bring-up and the unit tests
        # can read the same tables this scanner runs on.
        self.cols = keypad.MATRIX_COLS
        self.rows = keypad.MATRIX_ROWS
        self.power_gpio = keypad.POWER_GPIO

        # Timer for power-off debounce, and latch so we only emit
        # one POWER_BTN per physical press
        self.power_press_time = 0
        self.power_sent = False

        self.keymap = keypad.KEYMAP
        # If SQUARE is pressed together with key, ALT_<key> is sent
        self.alt_keymap = keypad.ALT_KEYMAP
        self.long_keymap = keypad.LONG_KEYMAP

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

    def get_keyboard_key(self) -> int:
        """
        Checks libinput keyboard, if keyrelesed
        map to our keycode and return

        Returns 0 for no key registered
        """
        key_mapping: dict[int, int] = {
            103: self.UP,
            108: self.DOWN,
            105: self.LEFT,
            106: self.RIGHT,
            28: self.SQUARE,
            78: self.MINUS,
            74: self.PLUS,
        }

        while True:
            while True:
                self.li_kb._libinput.libinput_dispatch(self.li_kb._li)
                hevent = self.li_kb._libinput.libinput_get_event(self.li_kb._li)
                if not hevent:
                    return 0
                type_ = self.li_kb._libinput.libinput_event_get_type(hevent)

                if type_.is_keyboard():
                    kbev = libinput.KeyboardEvent(hevent, self.li_kb._libinput)
                    if kbev.key_state == libinput.constant.KeyState.RELEASED:
                        return key_mapping.get(kbev.key, 0)

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
                    keycode = keypad.keymap_index(i, j)
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
