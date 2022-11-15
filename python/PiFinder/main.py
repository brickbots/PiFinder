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
import time
import queue
import datetime
from PIL import Image, ImageDraw, ImageFont, ImageChops, ImageOps
from multiprocessing import Process, Queue
from multiprocessing.managers import BaseManager

from luma.core.interface.serial import spi
from luma.core.render import canvas
from luma.oled.device import ssd1351

import keyboard
import camera
import solver
import gps
import config

from uimodules import UIPreview, UIConsole, UIStatus

serial = spi(device=0, port=0)
device = ssd1351(serial)


def set_brightness(level):
    """
    Sets oled brightness
    0-255
    """
    device.contrast(level)


class StateManager(BaseManager):
    pass


class SharedStateObj:
    def __init__(self):
        self.__solve_state = None
        self.__last_image_time = 0
        self.__solution = None
        self.__imu = None
        self.__location = None
        self.__datetime = None

    def solve_state(self):
        return self.__solve_state

    def set_solve_state(self, v):
        self.__solve_state = v

    def solution(self):
        return self.__solution

    def set_solution(self, v):
        self.__solution = v

    def location(self):
        return self.__location

    def set_location(self, v):
        self.__location = v

    def last_image_time(self):
        return self.__last_image_time

    def set_last_image_time(self, v):
        self.__last_image_time = v

    def datetime(self):
        return self.__datetime

    def set_datetime(self, dt):
        self.__datetime = dt


StateManager.register("SharedState", SharedStateObj)
StateManager.register("NewImage", Image.new)


def main():
    """
    Get this show on the road!
    """
    console_queue = Queue()
    cfg = config.Config()
    # init screen
    screen_brightness = cfg.get_option("display_brightness")
    set_brightness(screen_brightness)
    console = UIConsole(device, None, None, None)
    console.write("Starting....")
    console.update()

    # multiprocessing.set_start_method('spawn')
    # spawn keyboard service....
    console.write("   Keyboard")
    console.update()
    keyboard_queue = Queue()
    keyboard_process = Process(target=keyboard.run_keyboard, args=(keyboard_queue,))
    keyboard_process.start()

    # spawn gps service....
    console.write("   GPS")
    console.update()
    gps_queue = Queue()
    gps_process = Process(
        target=gps.gps_monitor,
        args=(
            gps_queue,
            console_queue,
        ),
    )
    gps_process.start()

    # spawn imaging service
    with StateManager() as manager:
        shared_state = manager.SharedState()

        # Load last location, set lock to false
        initial_location = cfg.get_option("last_location")
        shared_state.set_location(initial_location)

        console.write("   Camera")
        console.update()
        camera_command_queue = Queue()
        camera_image = manager.NewImage("RGB", (512, 512))
        image_process = Process(
            target=camera.get_images,
            args=(shared_state, camera_image, camera_command_queue, console_queue),
        )
        image_process.start()

        # Wait for camera to start....
        time.sleep(2)

        # Solver
        console.write("   Solver")
        console.update()
        solver_process = Process(
            target=solver.solver, args=(shared_state, camera_image, console_queue)
        )
        solver_process.start()

        # Start main event loop
        console.write("   Event Loop")
        console.update()

        # init UI Modes
        command_queues = {
            "camera": camera_command_queue,
        }
        ui_modes = [
            console,
            UIPreview(device, camera_image, shared_state, command_queues),
            UIStatus(device, camera_image, shared_state, command_queues),
        ]
        ui_mode_index = 1

        while True:
            # Console
            try:
                console_msg = console_queue.get(block=False)
                console.write(console_msg)
            except queue.Empty:
                pass

            # GPS
            try:
                gps_msg = gps_queue.get(block=False)
                if gps_msg.sentence_type == "GGA":
                    location = shared_state.location()
                    location["lat"] = gps_msg.latitude
                    location["lon"] = gps_msg.longitude
                    location["altitude"] = gps_msg.altitude
                    if location["gps_lock"] == False:
                        # Write to config if we just got a lock
                        cfg.set_option("last_location", location)
                        location["gps_lock"] = True
                    shared_state.set_location(location)
                if gps_msg.sentence_type == "RMC":
                    shared_state.set_datetime(
                        datetime.datetime.combine(gps_msg.datestamp, gps_msg.timestamp)
                    )
            except queue.Empty:
                pass

            # Keyboard
            try:
                keycode = keyboard_queue.get(block=False)
            except queue.Empty:
                keycode = None

            if keycode != None:
                print(f"{keycode =}")
                if keycode > 99:
                    # Special codes....
                    if keycode == keyboard.ALT_UP or keycode == keyboard.ALT_DN:
                        if keycode == keyboard.ALT_UP:
                            screen_brightness = screen_brightness + 10
                            if screen_brightness > 255:
                                screen_brightness = 255
                        else:
                            screen_brightness = screen_brightness - 10
                            if screen_brightness < 1:
                                screen_brightness = 1
                        set_brightness(screen_brightness)
                        cfg.set_option("display_brightness", screen_brightness)
                        console.write("Brightness: " + str(screen_brightness))

                elif keycode == keyboard.A:
                    # A key, mode switch
                    ui_mode_index += 1
                    if ui_mode_index >= len(ui_modes):
                        ui_mode_index = 0
                    ui_modes[ui_mode_index].active()

                else:
                    if keycode < 10:
                        ui_modes[ui_mode_index].key_number(keycode)

                    elif keycode == keyboard.UP:
                        ui_modes[ui_mode_index].key_up()

                    elif keycode == keyboard.DN:
                        ui_modes[ui_mode_index].key_down()

                    elif keycode == keyboard.GO:
                        ui_modes[ui_mode_index].key_enter()

                    elif keycode == keyboard.B:
                        ui_modes[ui_mode_index].key_b()

                    elif keycode == keyboard.C:
                        ui_modes[ui_mode_index].key_c()

                    elif keycode == keyboard.D:
                        ui_modes[ui_mode_index].key_d()

            ui_modes[ui_mode_index].update()


if __name__ == "__main__":
    main()
