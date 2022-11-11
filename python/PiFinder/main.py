#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is the main entry point for PiFinder it:
* Initializes the display
* Spawns keyboard process
* Sets up time/location via GPS
* Spawns camers/solver process
* then runs the UI loop

"""
from PIL import Image, ImageDraw, ImageFont, ImageChops, ImageOps
from multiprocessing import Process, Queue
from multiprocessing.managers import BaseManager
import time
import queue

from luma.core.interface.serial import spi
from luma.core.render import canvas
from luma.oled.device import ssd1351

import keyboard
import camera
import solver

serial = spi(device=0, port=0)
device = ssd1351(serial)

# setup red filtering image
RED = (0, 0, 255)
red_image = Image.new("RGB", (128, 128), RED)


def gamma_correct(in_value):
    in_value = float(in_value) / 255
    out_value = pow(in_value, 0.5)
    out_value = int(255 * out_value)
    return out_value


def set_brightness(level):
    """
    Sets oled brightness
    0-255
    """
    device.contrast(level)


def show_image(image_obj):
    """
        Prepares and shows a camera image on screen
    """
    image_obj = image_obj.resize((128, 128), Image.LANCZOS)
    image_obj = image_obj.convert("RGB")
    image_obj = ImageChops.multiply(image_obj, red_image)
    image_obj = Image.eval(image_obj, gamma_correct)
    image_obj = ImageOps.autocontrast(image_obj)
    device.display(image_obj.convert(device.mode))


class StateManager(BaseManager):
    pass

class SharedStateObj:
    def __init__(self):
        self.__solve_state = None
        self.__last_image_time = 0
        self.__solve = None
        self.__imu = None

    def solve(self):
        return self.__solve

    def set_solve(self, v):
        self.__solve = v

    def last_image_time(self):
        return self.__last_image_time

    def set_last_image_time(self, v):
        self.__last_image_time = v

StateManager.register("SharedState", SharedStateObj)
StateManager.register("NewImage", Image.new)


def main():
    """
    Get this show on the road!
    """
    # init screen
    console_font = ImageFont.truetype("/usr/share/fonts/truetype/Roboto_Mono/static/RobotoMono-Regular.ttf", 10)
    console_screen = Image.new("RGB", (128, 128))
    console_draw = ImageDraw.Draw(console_screen)
    console_draw.text((10, 10), "Starting", font=console_font, fill=RED)
    device.display(console_screen.convert(device.mode))

    # multiprocessing.set_start_method('spawn')
    # spawn keyboard service....
    keyboard_queue = Queue()
    keyboard_process = Process(target=keyboard.run_keyboard, args=(keyboard_queue,))
    keyboard_process.start()
    console_draw.text((20, 20), "Keyboard", font=console_font, fill=RED)
    device.display(console_screen.convert(device.mode))

    # spawn imaging service
    with StateManager() as manager:
        shared_state = manager.SharedState()

        console_draw.text((20, 30), "Camera", font=console_font, fill=RED)
        device.display(console_screen.convert(device.mode))
        camera_command_queue = Queue()
        camera_image = manager.NewImage("RGB", (512,512))
        image_process = Process(
            target=camera.get_images, args=(shared_state, camera_image, camera_command_queue)
        )
        image_process.start()

        # Wait for camera to start....
        time.sleep(2)

        # Solver
        console_draw.text((20, 40), "Solver", font=console_font, fill=RED)
        device.display(console_screen.convert(device.mode))
        solver_process = Process(
            target=solver.solver, args=(shared_state, camera_image)
        )
        solver_process.start()

        console_draw.text((20, 50), "Main Event Loop", font=console_font, fill=RED)
        device.display(console_screen.convert(device.mode))

        # Start main event loop
        last_image_fetched = time.time()
        while True:
            try:
                keycode = keyboard_queue.get(block=False)
            except queue.Empty:
                keycode = None

            if keycode != None:
                print(keycode)

            if keycode == 5:
                camera_command_queue.put("exp_dn")
            if keycode == 4:
                camera_command_queue.put("exp_up")
            if keycode == 7:
                camera_command_queue.put("save")
            if keycode == 0:
                camera_command_queue.put("wedge")

            # display an image
            last_image_time = shared_state.last_image_time()
            if last_image_time > last_image_fetched:
                show_image(camera_image)
                last_image_fetched = last_image_time
            # sleep(1/10)


if __name__ == "__main__":
    main()
