#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is runs the keyboard matrix
and adds keys to the provided queue

"""
import sh
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
            4 , 5 , 6 , self.UP,
            1 , 2 , 3 , self.DN,
            self.NA, 0 , self.NA, self.ENT,
            self.A , self.B , self.C , self.D,
        ]
        self.alt_keymap = [
            self.NA, self.NA, self.NA, self.NA,
            self.NA, self.NA, self.NA, self.ALT_UP,
            self.NA, self.NA, self.NA, self.ALT_DN,
            self.NA, self.ALT_0, self.NA, self.NA,
            self.ALT_A, self.ALT_B, self.ALT_C, self.ALT_D,
        ]
        self.long_keymap = [
            self.NA, self.NA, self.NA, self.NA,
            self.NA, self.NA, self.NA, self.NA,
            self.NA, self.NA, self.NA, self.NA,
            self.NA, self.NA, self.NA, self.LNG_ENT,
            self.LNG_A, self.LNG_B, self.LNG_C, self.LNG_D,
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
        while True:
            sleep(1 / 60)
            if len(pressed) > 0 and hold_sent is False:
                hold_counter += 1
                if hold_counter > 60 and not alt_sent:
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
