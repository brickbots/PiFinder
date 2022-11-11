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
from time import sleep
import queue

from luma.core.interface.serial import spi
from luma.core.render import canvas
from luma.oled.device import ssd1351

import keyboard
import camera

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
    image_obj = ImageChops.multiply(image_obj, red_image)
    image_obj = Image.eval(image_obj, gamma_correct)
    image_obj = ImageOps.autocontrast(image_obj)
    device.display(image_obj.convert(device.mode))


class ImageManager(BaseManager):
    pass


ImageManager.register("NewImage", Image.new)


def main():
    """
    Get this show on the road!
    """
    # init screen
    console_font = ImageFont.load_default()
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
    with ImageManager() as manager:
        camera_command_queue = Queue()
        shared_image = manager.NewImage("RGB", (128, 128), (0, 0, 0))
        image_process = Process(
            target=camera.get_images, args=(shared_image, camera_command_queue)
        )
        image_process.start()
        console_draw.text((20, 30), "Solver", font=console_font, fill=RED)
        device.display(console_screen.convert(device.mode))

        # Wait for camera to start....
        sleep(2)

        # Start main event loop
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
            device.display(shared_image.convert(device.mode))
            # sleep(1/10)


if __name__ == "__main__":
    main()
