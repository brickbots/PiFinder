#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is runs the keyboard matrix
and adds keys to the provided queue

"""

from time import sleep
from PiFinder.keyboard_interface import KeyboardInterface
import RPi.GPIO as GPIO


class KeyboardPi(KeyboardInterface):
    def __init__(self, q):
        self.q = q

        self.cols = [16, 23, 26, 27]
        self.rows = [19, 17, 18, 22, 20]
        # fmt: off
        self.keymap = [
            7 , 8 , 9 , self.NA,
            4 , 5 , 6 , self.PLUS,
            1 , 2 , 3 , self.MINUS,
            self.NA, 0 , self.NA, self.STAR,
            self.LEFT , self.UP , self.DOWN , self.RIGHT,
        ]
        self.alt_keymap = [
            self.NA, self.NA, self.NA, self.NA,
            self.NA, self.NA, self.NA, self.ALT_PLUS,
            self.NA, self.NA, self.NA, self.ALT_MINUS,
            self.NA, self.ALT_0, self.NA, self.NA,
            self.ALT_LEFT, self.ALT_UP, self.ALT_DOWN, self.ALT_RIGHT,
        ]
        self.long_keymap = [
            self.NA, self.NA, self.NA, self.NA,
            self.NA, self.NA, self.NA, self.NA,
            self.NA, self.NA, self.NA, self.NA,
            self.NA, self.NA, self.NA, self.LNG_STAR,
            self.LNG_LEFT, self.LNG_UP, self.LNG_DOWN, self.LNG_RIGHT,
        ]
        # fmt: on

    def run_keyboard(self):
        """
        scans keyboard matrix, puts release events in queue
        """

        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.rows, GPIO.IN)
        GPIO.setup(self.cols, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        pressed = set()
        alt_sent = False
        hold_counter = 0
        hold_sent = False
        scan_freq = 60
        while True:
            sleep(1 / scan_freq)
            if len(pressed) > 0 and hold_sent is False:
                hold_counter += 1
                if hold_counter > scan_freq and not alt_sent:
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


def run_keyboard(q, shared_state):
    keyboard = KeyboardPi(q)
    keyboard.run_keyboard()
