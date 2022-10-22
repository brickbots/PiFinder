#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is the solver
* Captures images
* Checks IMU
* Places preview images in queue
* Plate solves high-res image
* Takes full res images on demand

"""
import queue
import uuid
import pprint
import time
from tetra3 import Tetra3

from PIL import Image, ImageDraw, ImageFont, ImageChops
from picamera2 import Picamera2

RED = (0, 0, 255)


def get_images(shared_image, command_queue):
    t3 = Tetra3("default_database")
    exposure_time = 750000
    # Initialize camera
    camera = Picamera2()
    cam_config = camera.create_still_configuration(main={"size": (512, 512)})
    camera.configure(cam_config)
    camera.set_controls({"AeEnable": False})
    camera.set_controls({"AnalogueGain": 10})
    camera.set_controls({"ExposureTime": exposure_time})
    camera.start()
    pprint.pprint(camera.camera_controls)

    red_image = Image.new("RGB", (128, 128), (0, 0, 255))

    console_font = ImageFont.load_default()
    while True:
        start_time = time.time()

        solve_image = camera.capture_image("main")
        solve_image = solve_image.convert("L")
        solve_image = solve_image.rotate(90)
        solved = t3.solve_from_image(
                solve_image,
                fov_estimate=10.16,
                pattern_checking_stars=6
        )
        pprint.pprint(solved)
        # this also generates a copy here
        preview_image = solve_image.resize((128, 128), Image.LANCZOS)
        preview_image = preview_image.convert("RGB")
        preview_image = ImageChops.multiply(preview_image, red_image)
        preview_draw = ImageDraw.Draw(preview_image)
        preview_draw.text((10, 10), str(exposure_time), font=console_font, fill=RED)
        if solved["Dec"] != None:
            preview_draw.text(
                (10, 30), str(round(solved["Dec"], 3)), font=console_font, fill=RED
            )
            preview_draw.text(
                (67, 30), str(round(solved["RA"], 3)), font=console_font, fill=RED
            )
        shared_image.paste(preview_image)

        try:
            command = command_queue.get(block=False)
        except queue.Empty:
            command = None

        if command == "exp_up":
            exposure_time = int(exposure_time * 1.1)
            camera.set_controls({"ExposureTime": exposure_time})
            print("Exp: " + str(exposure_time))

        if command == "exp_dn":
            exposure_time = int(exposure_time * 0.9)
            camera.set_controls({"ExposureTime": exposure_time})
            print("Exp: " + str(exposure_time))

        if command == "save":
            filename = str(uuid.uuid1()).split("-")[0]
            filename = filename + ".bmp"
            camera.capture_file(filename)

        print(time.time() - start_time)
