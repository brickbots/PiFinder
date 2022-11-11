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

RED = (0, 0, 255)


def get_images(shared_state, camera_image, command_queue):
    # Initialize camera
    exposure_time = 1500000
    analog_gain = 10
    camera = Picamera2()
    cam_config = camera.create_still_configuration(main={"size": (512, 512)})
    camera.configure(cam_config)
    camera.set_controls({"AeEnable": False})
    camera.set_controls({"AnalogueGain": analog_gain})
    camera.set_controls({"ExposureTime": exposure_time})
    camera.start()
    pprint.pprint(camera.camera_controls)

    red_image = Image.new("RGB", (128, 128), (0, 0, 255))

    while True:
        start_time = time.time()

        base_image = camera.capture_image("main")
        base_image = base_image.convert("L")
        base_image = base_image.rotate(90)
        camera_image.paste(base_image)
        shared_state.set_last_image_time(time.time())


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
            filename = f"/home/pifinder/captures/{filename}.png"
            camera.capture_file(filename)

        if command == "wedge":
            gain_wedges = [10,15,20]
            exp_wedges = [750000, 1000000, 1500000, 2000000, 3000000]
            filename_base = str(uuid.uuid1()).split("-")[0][:4]
            console_font = ImageFont.truetype("/usr/share/fonts/truetype/Roboto_Mono/static/RobotoMono-Regular.ttf", 30)
            for gain in gain_wedges:
                for exp in exp_wedges:
                    camera.set_controls({"AnalogueGain": gain,"ExposureTime": exp})
                    print(f"Capturing... {gain =} {exp =}")
                    wait = True
                    last_exp = 0
                    last_gain = 0
                    while wait:
                        md = camera.capture_metadata()
                        if md["AnalogueGain"] == last_gain and md["ExposureTime"] == last_exp:
                            wait = False
                        else:
                            last_gain=md["AnalogueGain"]
                            last_exp = md["ExposureTime"]
                            print(f"\t Waiting... {md['AnalogueGain']} / {md['ExposureTime']}")

                    filename = f"/home/pifinder/captures/{filename_base}_{last_gain:.0f}_{last_exp:.0f}.png"
                    camera.capture_file(filename)
                    base_image = camera.capture_image("main")
                    base_image = base_image.convert("L")
                    base_image = base_image.rotate(90)

                    # this also generates a copy here
                    preview = base_image.convert("RGB")
                    preview_draw = ImageDraw.Draw(preview)
                    preview_draw.text((10, 10), str(gain), font=console_font, fill=RED)
                    preview_draw.text((10, 40), str(exp), font=console_font, fill=RED)
                    camera_image.paste(preview)
                    shared_state.set_last_image_time(time.time())

