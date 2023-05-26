#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module is the camera
* Captures images
* Places preview images in queue
* Places solver images in queue
* Takes full res images on demand

"""
import time
from PIL import Image
from PiFinder import config
from PiFinder import utils
from PiFinder.camera_interface import CameraInterface
from pathlib import Path
from shutil import copyfile
import time
from PiFinder.camera_interface import CameraInterface
import zwoasi as asi
from typing import Dict, Tuple
import logging


class CameraASI(CameraInterface):
    """The camera class for PI cameras.  Implements the CameraInterface interface."""

    def __init__(self) -> None:
        import zwoasi as asi
        # find a camera
        # asi.init("/lib/zwoasi/armv7/libASICamera2.so")  # Initialize the ASI library
        asi.init("/Users/mike/Downloads/ASI_Camera_SDK/ASI_linux_mac_SDK_V1.29/lib/armv8/libASICamera2.so")  # Initialize the ASI library
        num_cameras = asi.get_num_cameras()  # Get the number of connected cameras
        if num_cameras == 0:
            self.handpad.display("Error:", " no camera found", "")
            self.camType = "not found"
            logging.info("camera not found")
            time.sleep(1)
        else:
            asi.list_cameras()
            self.initialize()
            self.handpad.display("ZWO camera found", "", "")
            logging.info("ZWO camera found")
            time.sleep(1)
        self.camType = "ZWO"

    def initialize(self) -> None:
        """Initializes the camera and set the needed control parameters"""
        if self.camType == "not found":
            return
        self.camera = asi.Camera(0)  # Initialize the camera
        self.camera.set_control_value(
            asi.ASI_BANDWIDTHOVERLOAD,
            self.camera.get_controls()["BandWidth"]["MinValue"],
        )
        self.camera.disable_dark_subtract()
        self.camera.set_control_value(asi.ASI_WB_B, 99)
        self.camera.set_control_value(asi.ASI_WB_R, 75)
        self.camera.set_control_value(asi.ASI_GAMMA, 50)
        self.camera.set_control_value(asi.ASI_BRIGHTNESS, 50)
        self.camera.set_control_value(asi.ASI_FLIP, 0)
        self.camera.set_image_type(asi.ASI_IMG_RAW8)


    def capture(self) -> Image.Image:
        self.camera.set_control_value(asi.ASI_GAIN, self.gain)
        self.camera.set_control_value(asi.ASI_EXPOSURE, self.exposure_time)  # microseconds
        return Image.fromarray(self.camera.capture().astype('uint8'), 'RGB')

    def capture_file(self, filename) -> None:
        self.camera.set_control_value(asi.ASI_GAIN, gain)
        self.camera.set_control_value(asi.ASI_EXPOSURE, exposure_time)  # microseconds
        self.camera.capture(filename=filename)

    def set_camera_config(self, exposure_time: float, gain: float) -> Tuple[float, float, float]:
        self.exposure_time = exposure_time
        self.gain = gain
        return exposure_time, gain, gain

    def get_cam_type(self) -> str:
        return self.camType
