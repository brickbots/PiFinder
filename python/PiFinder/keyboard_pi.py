#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is runs the keyboard matrix
and adds keys to the provided queue

"""
import sh
import RPi.GPIO as GPIO
from time import sleep


cols = [16, 23, 26, 27]
rows = [19, 17, 18, 22, 20]
# fmt: off
keymap = [
    7 , 8 , 9 , NA,
    4 , 5 , 6 , UP,
    1 , 2 , 3 , DN,
    NA, 0 , NA, ENT,
    A , B , C , D,
]
alt_keymap = [
    NA, NA, NA, NA,
    NA, NA, NA, ALT_UP,
    NA, NA, NA, ALT_DN,
    NA, ALT_0, NA, NA,
    ALT_A, ALT_B, ALT_C, ALT_D,
]
long_keymap = [
    NA, NA, NA, NA,
    NA, NA, NA, NA,
    NA, NA, NA, NA,
    NA, NA, NA, LNG_ENT,
    LNG_A, LNG_B, LNG_C, LNG_D,
]
# fmt: on


class KeyboardPi(KeyboardInterface):
    def __init__(self, q):
        self.q = q

    def run_keyboard(self, q, script_path=None):
        """
        scans keyboard matrix, puts release events in queue
        """
        if script_path:
            run_script(q, script_path)

        GPIO.setmode(GPIO.BCM)
        GPIO.setup(rows, GPIO.IN)
        GPIO.setup(cols, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        pressed = set()
        alt_sent = False
        hold_counter = 0
        hold_sent = False
        while True:
            sleep(1 / 60)
            if len(pressed) > 0 and hold_sent == False:
                hold_counter += 1
                if hold_counter > 60 and not alt_sent:
                    keycode = pressed.pop()
                    pressed = set()
                    q.put(long_keymap[keycode])
                    hold_counter = 0
                    hold_sent = True
            else:
                hold_counter = 0
            for i in range(len(rows)):
                GPIO.setup(rows[i], GPIO.OUT, initial=GPIO.LOW)
                for j in range(len(cols)):
                    keycode = i * len(cols) + j
                    newval = GPIO.input(cols[j]) == GPIO.LOW
                    if newval and not keycode in pressed:
                        # initial press
                        pressed.add(keycode)
                        # print(str(keymap[keycode]), "Pressed")
                    elif not newval and keycode in pressed:
                        # release
                        pressed.discard(keycode)
                        if 15 in pressed:
                            # Released while ENT is pressed
                            alt_sent = True
                            q.put(alt_keymap[keycode])
                        else:
                            if keycode == 15 and alt_sent:
                                alt_sent = False
                            elif hold_sent:
                                hold_sent = False
                            else:
                                q.put(keymap[keycode])
                GPIO.setup(rows[i], GPIO.IN)


def run_keyboard(self, q, script_path=None):
    keyboard = KeyboardPi(q)
    if script_path:
        keyboard.run_script(script_path)

    keyboard.run_keyboard()
