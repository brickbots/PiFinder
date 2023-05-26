from time import sleep
from rpi_hardware_pwm import HardwarePWM

"""
This module is runs the keyboard matrix
and adds keys to the provided queue

"""


class KeyboardPi(KeyboardInterface):
    import RPi.GPIO as GPIO
    NA = 10
    UP = 11
    DN = 12
    ENT = 13
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
    LNG_A = 200
    LNG_B = 201
    LNG_C = 202
    LNG_D = 203
    LNG_ENT = 204

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

    def __init__(self):
        self.keypad_pwm = HardwarePWM(pwm_channel=1, hz=120)
        self.keypad_pwm.start(0)

    def set_brightness(self, level, cfg):
        # deterime offset for keypad
        keypad_offsets = {
            "+3": 2,
            "+2": 1.6,
            "+1": 1.3,
            "0": 1,
            "-1": 0.75,
            "-2": 0.5,
            "-3": 0.25,
            "Off": 0,
        }
        keypad_brightness = cfg.get_option("keypad_brightness")
        self.keypad_pwm.change_duty_cycle(level * 0.05 * keypad_offsets[keypad_brightness])

    def run_keyboard(self, q, script_path=None):
        """
        scans keyboard matrix, puts release events in queue
        """
        GPIO = self.GPIO
        cols = self.cols
        rows = self.rows
        # if script_path:
        #     run_script(q, script_path)

        GPIO.setmode(GPIO.BCM)
        GPIO.setup(rows, GPIO.IN)
        GPIO.setup(cols, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        pressed = set()
        alt_sent = False
        hold_counter = 0
        hold_sent = False
        while True:
            sleep(1 / 60)
            if len(pressed) > 0 and not hold_sent:
                hold_counter += 1
                if hold_counter > 60 and not alt_sent:
                    keycode = pressed.pop()
                    pressed = set()
                    q.put(self.long_keymap[keycode])
                    hold_counter = 0
                    hold_sent = True
            else:
                hold_counter = 0
            for i in range(len(rows)):
                GPIO.setup(rows[i], GPIO.OUT, initial=GPIO.LOW)
                for j in range(len(cols)):
                    keycode = i * len(cols) + j
                    newval = GPIO.input(cols[j]) == GPIO.LOW
                    if newval and keycode not in pressed:
                        # initial press
                        pressed.add(keycode)
                        # print(str(keymap[keycode]), "Pressed")
                    elif not newval and keycode in pressed:
                        # release
                        pressed.discard(keycode)
                        if 15 in pressed:
                            # Released while ENT is pressed
                            alt_sent = True
                            q.put(self.alt_keymap[keycode])
                        else:
                            if keycode == 15 and alt_sent:
                                alt_sent = False
                            elif hold_sent:
                                hold_sent = False
                            else:
                                q.put(self.keymap[keycode])
                GPIO.setup(rows[i], GPIO.IN)
