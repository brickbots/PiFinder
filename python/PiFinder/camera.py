#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is the camera
* Captures images
* Places preview images in queue
* Places solver images in queue
* Takes full res images on demand

"""
import os
import queue
import time

from PIL import Image, ImageDraw, ImageFont, ImageChops
from picamera2 import Picamera2

from PiFinder import config

RED = (0, 0, 255)


exposure_time = None
analog_gain = None


def set_camera_defaults(camera):
    # Initialize camera, defaults :
    # gain: 10
    # exposure: 1.5m
    global exposure_time, analog_gain
    camera.stop()

    # using this smaller scale auto-selects binning on the sensor...
    cam_config = camera.create_still_configuration({"size": (512, 512)})
    camera.configure(cam_config)
    camera.set_controls({"AeEnable": False})
    camera.set_controls({"AnalogueGain": analog_gain})
    camera.set_controls({"ExposureTime": exposure_time})
    camera.start()


def set_camera_config(camera):
    # Initialize camera, defaults :
    # gain: 10
    # exposure: 1.5m
    global exposure_time, analog_gain
    camera.stop()
    camera.set_controls({"AnalogueGain": analog_gain})
    camera.set_controls({"ExposureTime": exposure_time})
    camera.start()


def set_camera_highres(camera):
    global exposure_time, analog_gain
    camera.stop()
    cam_config = camera.create_still_configuration()
    camera.configure(cam_config)
    camera.set_controls({"AeEnable": False})
    camera.set_controls({"AnalogueGain": analog_gain})
    camera.set_controls({"ExposureTime": exposure_time})
    camera.start()


def get_images(shared_state, camera_image, command_queue, console_queue):
    global exposure_time, analog_gain
    debug = False
    camera = Picamera2()
    cfg = config.Config()
    exposure_time = cfg.get_option("camera_exp")
    analog_gain = cfg.get_option("camera_gain")
    set_camera_defaults(camera)

    red_image = Image.new("RGB", (128, 128), (0, 0, 255))

    # Set path for test images
    root_dir = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))
    test_image_path = os.path.join(root_dir, "test_images", "pifinder_debug.png")

    while True:
        imu = shared_state.imu()
        if imu and imu["moving"] and imu["status"] > 0:
            pass
        else:
            image_start_time = time.time()
            if not debug:
                base_image = camera.capture_image("main")
                base_image = base_image.convert("L")
                base_image = base_image.rotate(90)
            else:
                # load image and wait
                base_image = Image.open(test_image_path)
                time.sleep(1)
            camera_image.paste(base_image)
            shared_state.set_last_image_time((image_start_time, time.time()))

        command = True
        while command:
            try:
                command = command_queue.get(block=False)
            except queue.Empty:
                command = ""

            if command == "debug":
                if debug == True:
                    debug = False
                else:
                    debug = True

            if command.startswith("set_exp"):
                exposure_time = int(command.split(":")[1])
                set_camera_config(camera)
                console_queue.put("CAM: Exp=" + str(exposure_time))

            if command.startswith("set_gain"):
                analog_gain = int(command.split(":")[1])
                set_camera_config(camera)
                console_queue.put("CAM: Gain=" + str(analog_gain))

            if command == "exp_up" or command == "exp_dn":
                if command == "exp_up":
                    exposure_time = int(exposure_time * 1.25)
                else:
                    exposure_time = int(exposure_time * 0.75)
                camera.set_controls({"ExposureTime": exposure_time})
                console_queue.put("CAM: Exp=" + str(exposure_time))
            if command == "exp_save":
                console_queue.put("CAM: Exp Saved")
                cfg.set_option("camera_exp", exposure_time)
                cfg.set_option("camera_gain", analog_gain)

            if command.startswith("save"):
                filename = command.split(":")[1]
                filename = f"/home/pifinder/PiFinder_data/captures/{filename}.png"
                camera.capture_file(filename)
                console_queue.put("CAM: Saved Image")

            if command.startswith("save_hi"):
                # Save high res image....
                filename = command.split(":")[1]
                filename = f"/home/pifinder/PiFinder_data/captures/{filename}.png"
                set_camera_highres(camera)
                camera.capture_file(filename)
                console_queue.put("CAM: Saved Hi Image")
                set_camera_defaults(camera)
