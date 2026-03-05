#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is runs the keyboard matrix
and adds keys to the provided queue

"""

from time import sleep
import libinput
from PiFinder.keyboard_interface import KeyboardInterface
import RPi.GPIO as GPIO
import logging
from PiFinder.multiproclogging import MultiprocLogging

logger = logging.getLogger("Keyboard.Pi")


class KeyboardPi(KeyboardInterface):
    def __init__(self, q, bloom_remap=False):
        self.q = q

        # GPIO pin numbers for the rows and columns of the keyboard matrix
        self.cols = [16, 23, 26, 27]
        self.rows = [19, 17, 18, 22, 20]

        if bloom_remap:
            _up = self.RIGHT
            _down = self.LEFT
            _left = self.UP
            _right = self.DOWN
            _lng_up = self.LNG_RIGHT
            _lng_down = self.LNG_LEFT
            _lng_left = self.LNG_UP
            _lng_right = self.LNG_DOWN
            _alt_up = self.ALT_RIGHT
            _alt_down = self.ALT_LEFT
            _alt_left = self.ALT_UP
            _alt_right = self.ALT_DOWN
        else:
            _up = self.UP
            _down = self.DOWN
            _left = self.LEFT
            _right = self.RIGHT
            _lng_up = self.LNG_UP
            _lng_down = self.LNG_DOWN
            _lng_left = self.LNG_LEFT
            _lng_right = self.LNG_RIGHT
            _alt_up = self.ALT_UP
            _alt_down = self.ALT_DOWN
            _alt_left = self.ALT_LEFT
            _alt_right = self.ALT_RIGHT

        # fmt: off
        self.keymap = [
            7 , 8 , 9 , self.NA,
            4 , 5 , 6 , self.PLUS,
            1 , 2 , 3 , self.MINUS,
            self.NA, 0 , self.NA, self.SQUARE,
            _left, _up , _down , _right,
        ]
        # If SQUARE is pressed together with key, ALT_<key> is sent
        self.alt_keymap = [
            self.NA, self.NA, self.NA, self.NA,
            self.NA, self.NA, self.NA, self.ALT_PLUS,
            self.NA, self.NA, self.NA, self.ALT_MINUS,
            self.NA, self.ALT_0, self.NA, self.NA,
            _alt_left, _alt_up, _alt_down, _alt_right,
        ]
        self.long_keymap = [
            self.NA, self.NA, self.NA, self.NA,
            self.NA, self.NA, self.NA, self.NA,
            self.NA, self.NA, self.NA, self.NA,
            self.NA, self.NA, self.NA, self.LNG_SQUARE,
            _lng_left, _lng_up, _lng_down, _lng_right,
        ]
        # fmt: on

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
                    if list(pressed)[-1] in [17, 18]:
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
                        if 15 in pressed:
                            # Released while ENT is pressed
                            alt_sent = True
                            self.q.put(self.alt_keymap[keycode])
                        else:
                            if keycode == 15 and alt_sent:
                                alt_sent = False
                            elif hold_sent:
                                hold_sent = False
                            else:
                                self.q.put(self.keymap[keycode])
                GPIO.setup(self.rows[i], GPIO.IN)


def run_keyboard(q, shared_state, log_queue, bloom_remap=False):
    MultiprocLogging.configurer(log_queue)
    keyboard = KeyboardPi(q, bloom_remap=bloom_remap)
    keyboard.run_keyboard(log_queue)
