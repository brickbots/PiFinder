#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is the camera
* Captures images
* Places preview images in queue
* Places solver images in queue
* Takes full res images on demand

"""
import queue
import uuid
import pprint
import time

from PIL import Image, ImageDraw, ImageFont, ImageChops
from picamera2 import Picamera2

import config

RED = (0, 0, 255)


def get_images(shared_state, camera_image, command_queue, console_queue):
    cfg = config.Config()
    # Initialize camera, defaults :
    # gain: 10
    # exposure: 1.5m
    exposure_time = cfg.get_option("camera_exp")
    analog_gain = cfg.get_option("camera_gain")
    camera = Picamera2()
    cam_config = camera.create_still_configuration(main={"size": (512, 512)})
    camera.configure(cam_config)
    camera.set_controls({"AeEnable": False})
    camera.set_controls({"AnalogueGain": analog_gain})
    camera.set_controls({"ExposureTime": exposure_time})
    camera.start()
    # pprint.pprint(camera.camera_controls)

    red_image = Image.new("RGB", (128, 128), (0, 0, 255))

    while True:
        start_time = time.time()

        base_image = camera.capture_image("main")
        base_image = base_image.convert("L")
        base_image = base_image.rotate(90)
        camera_image.paste(base_image)
        shared_state.set_last_image_time(time.time())

        command = True
        while command:
            try:
                command = command_queue.get(block=False)
            except queue.Empty:
                command = None

            if command == "exp_up" or command == "exp_dn":
                if command == "exp_up":
                    exposure_time = int(exposure_time * 1.1)
                else:
                    exposure_time = int(exposure_time * 0.9)
                camera.set_controls({"ExposureTime": exposure_time})
                console_queue.put("CAM: Exp=" + str(exposure_time))
            if command == "exp_save":
                cfg.set_option("camera_exp", exposure_time)

            if command == "save":
                filename = str(uuid.uuid1()).split("-")[0]
                filename = f"/home/pifinder/captures/{filename}.png"
                camera.capture_file(filename)
                console_queue.put("CAM: Saved Image")
