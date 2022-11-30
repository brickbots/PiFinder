#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is runs the keyboard matrix
and adds keys to the provided queue

"""
import RPi.GPIO as GPIO
from time import sleep

NA = 10
UP = 11
DN = 12
GO = 13
A = 20
B = 21
C = 22
D = 24
ALT_UP = 101
ALT_DN = 102
ALT_A = 103
ALT_B = 104
ALT_C = 105
ALT_D = 106
ALT_0 = 110

cols = [16, 23, 26, 27]
rows = [19, 17, 18, 22, 20]
# fmt: off
keymap = [
    7 , 8 , 9 , NA,
    4 , 5 , 6 , UP,
    1 , 2 , 3 , DN,
    NA, 0 , NA, GO,
    A , B , C , D,
]
alt_keymap = [
    NA, NA, NA, NA,
    NA, NA, NA, ALT_UP,
    NA, NA, NA, ALT_DN,
    NA, ALT_0, NA, NA,
    ALT_A, ALT_B, ALT_C, ALT_D,
]
# fmt: on


def run_keyboard(q):
    """
    scans keyboard matrix, puts release events in queue
    """
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(rows, GPIO.IN)
    GPIO.setup(cols, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    pressed = set()
    alt_sent = False
    while True:
        sleep(1 / 60)
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
                        else:
                            q.put(keymap[keycode])
            GPIO.setup(rows[i], GPIO.IN)
